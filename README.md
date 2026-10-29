# 武汉红色文化导览小助手

面向**中小学生红色研学场景**的垂直 RAG 智能导览系统。

基于 **Python + LangChain** 搭建检索增强生成（RAG）架构：**BAAI-BGE** 作为本地 Embedding 模型，**Chroma** 向量数据库存储武汉红色场馆史料，**智谱 GLM（glm-4.7-flash）** 云端大模型负责生成；**FastAPI** 提供后端接口，**Vue 3** 实现前端交互，**Docker** 完成容器化部署。

## 核心特性

| 特性 | 说明 |
|---|---|
| 分级 Prompt | 按学生学段（小学低年级 / 小学高年级 / 初中 / 高中）动态切换系统提示词，自动适配认知水平的讲解风格、篇幅与任务难度 |
| 史料约束生成 | 回答仅基于知识库召回的史料块，检索无结果时如实告知，降低史实幻觉 |
| 流式问答 | SSE 流式输出，回答实时逐字呈现；每条回答附带**参考史料来源**（场馆+小节） |
| 研学路线生成 | 按主题（辛亥首义 / 党史转折 / 工人运动 / 抗战烽火）与时长生成学段适配的参观路线 |
| 研学任务单 | 为指定场馆生成"观察→记录→思考→表达"梯度递进的任务单 |
| 场馆讲解词 | 一键为任一场馆生成当前学段讲解词 |
| 智能工具调用 | GLM 按需多步调用白名单工具（史料检索/场馆信息/场馆目录），普通问题零额外延迟 |
| 工程底座 | SQLite 会话持久化、语义缓存（相似问秒回）、按 IP 限流、429 指数退避重试 |

## 项目结构

```
red_culture/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 全局配置（.env 可覆盖）
│   │   ├── api/routes.py        # 接口层
│   │   ├── core/
│   │   │   ├── embeddings.py    # BAAI-BGE 本地 Embedding
│   │   │   ├── llm.py           # 智谱 GLM（超时/重试/思考模式可配）
│   │   │   ├── vectorstore.py   # Chroma 检索
│   │   │   ├── prompts.py       # 四级学段 Prompt 体系
│   │   │   ├── rag.py           # RAG 管线（流式/一次性 + 语义缓存 + 智能工具调用）
│   │   │   ├── tools.py         # Function Calling 工具集（白名单）
│   │   │   ├── storage.py       # 会话持久化（SQLite）
│   │   │   ├── cache.py         # 语义缓存（SQLite）
│   │   │   └── ratelimit.py     # 按 IP 滑动窗口限流中间件
│   │   └── services/            # 会话/场馆/研学服务
│   ├── data/venues/             # 武汉红色场馆史料（15 篇，带元数据）
│   ├── data/eval_dataset.json   # 分学段评测集（48 题，四学段 × 知识库内外）
│   ├── evaluate.py              # 评测脚本（检索命中率/关键词覆盖/拒答正确率）
│   ├── ingest.py                # 知识库入库脚本
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # Vue 3 + Vite
│   ├── src/
│   │   ├── App.vue              # 布局 + 全局学段状态
│   │   ├── api/index.js         # axios + SSE 流式客户端
│   │   └── components/          # 问答 / 场馆 / 研学工具 / 学段选择
│   ├── nginx/default.conf       # 静态托管 + API 反代（SSE 透传）
│   └── Dockerfile
└── docker-compose.yml           # backend + frontend
```

## 快速开始（Docker 一键部署，推荐）

```bash
# 1. 申请智谱 API Key（https://open.bigmodel.cn），写入 backend/.env
cd backend
copy .env.example .env            # Linux: cp .env.example .env
# 编辑 .env，填入 ZHIPU_API_KEY=...

# 2. 构建并启动两个服务
cd ..
docker compose up -d --build
```

- 首次启动时 entrypoint 检测到知识库为空会自动执行 `ingest.py` 入库，无需手动操作
- 前端：http://localhost:8080
- 后端接口文档：http://localhost:8000/docs

## 本地开发

### 1. 配置智谱 API Key

在 https://open.bigmodel.cn 申请 API Key，复制 `backend/.env.example` 为 `backend/.env` 并填入 `ZHIPU_API_KEY`。

### 2. 后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt

python ingest.py                                  # 构建向量知识库（首次必跑）
uvicorn app.main:app --reload --port 8000
```

> 国内网络会自动走 hf-mirror 下载 `BAAI/bge-small-zh-v1.5` 权重（约 100MB）。

### 3. 前端

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173（已代理 /api -> :8000）
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（智谱 GLM 配置 / 知识库状态） |
| GET | `/api/venues` | 场馆目录（支持 `?theme=` 过滤） |
| GET | `/api/grades` | 学段定义 |
| POST | `/api/chat/stream` | 分级 RAG 问答（SSE 流式） |
| POST | `/api/chat` | 分级 RAG 问答（一次性） |
| POST | `/api/route` | 研学路线生成 |
| POST | `/api/tasks` | 场馆研学任务单生成 |
| POST | `/api/explanation` | 场馆讲解词生成 |

请求体示例：

```json
POST /api/chat/stream
{
  "question": "八七会议上毛主席说了什么名言？",
  "grade": "junior",
  "session_id": null,
  "venue": null
}
```

## RAG 架构说明

```
学生提问
   │
   ▼
┌─────────────────┐   BGE 查询指令前缀
│ BGE-small-zh    │◄──────────────────
│ (本地Embedding)  │
└────────┬────────┘
         │ 向量
         ▼
┌─────────────────┐    TOP_K=5 + 相关度过滤
│ Chroma 持久库    │──→ 召回史料块（场馆/小节元数据）
└─────────────────┘
         │ 编号拼装为【参考资料】
         ▼
┌─────────────────────────────────┐
│ 分级 System Prompt + 对话历史     │  ← 按学段切换人设/风格/深度
└────────┬────────────────────────┘
         ▼
┌─────────────────┐
│ 智谱 GLM 云端API │── SSE 流式输出 + 来源引用
└─────────────────┘
```

降低幻觉的三道约束：① 检索相关度阈值过滤弱相关史料；② System Prompt 硬性规定"只依据参考资料作答，不足则如实说明"；③ 回答附带来源场馆与出处，便于师生核查。

## 知识库数据

`backend/data/venues/` 收录 19 篇武汉红色场馆史料（Markdown + front matter 元数据），覆盖四大主题：

- **辛亥首义**：辛亥革命武昌起义纪念馆（红楼）、辛亥革命博物馆、武昌起义门
- **党史转折**：八七会议会址、中共五大会址、农讲所、武昌毛泽东同志旧居、中国共产党纪律建设历史陈列馆、武汉中共中央机关旧址、武汉国民政府旧址（南洋大楼）、宋庆龄汉口旧居、向警予烈士陵园
- **工人运动**：武汉二七纪念馆、施洋烈士陵园
- **抗战烽火**：八路军武汉办事处、汉口新四军军部旧址、中山舰博物馆、武汉受降堂、苏联空军志愿队烈士墓
- **综述**：武汉红色文化总览（线路组织与学段建议，供路线生成检索）

新增史料：在 `data/venues/` 添加同格式 Markdown 后执行 `python ingest.py` 即可；可先运行 `python validate_venues.py data/venues` 校验格式（字段完整性/取值/结构/长度阈值）。

## 学段分级 Prompt 摘要

| 学段 | 语言风格 | 篇幅 | 任务侧重 |
|---|---|---|---|
| 小学低年级 | 讲故事、短句、比喻 | ≤250 字 | 观察类："找一找""画一画" |
| 小学高年级 | 通俗准确、三要素 | ≤350 字 | 记录类：研学手册、动手小任务 |
| 初中 | 脉络因果、衔接课本 | ≤500 字 | 思考类：比较与分析 |
| 高中 | 论从史出、多元视角 | ≤700 字 | 表达类：小论文、小组研讨 |

## 智能工具调用（Agentic RAG）

对话接口在 RAG 管线上叠加 GLM 原生 Function Calling（LangChain `@tool` + `bind_tools`），并支持**受控多步工具循环**：预检索 RAG 仍作为首轮上下文，模型可按需多步调用工具补全信息；普通史实问题首轮直接作答，不增加任何延迟。

| 工具 | 功能 | 典型触发问题 |
|---|---|---|
| `search_history` | 在史料知识库中补充检索（可换关键词多次、可限定场馆） | 跨场馆比较类问题、参考资料不足时的再检索 |
| `query_venue_info` | 查询单个场馆的地址/开放时间/预约方式/建议时长/适合学段 | "辛亥革命博物馆要预约吗？几点开门？" |
| `list_venues` | 按主题列出场馆目录 | "抗战主题有哪些场馆可以参观？" |

- **多步组合**：模型可多轮调用工具（如先 `list_venues` 列目录，再逐场馆 `query_venue_info` 查学段/时长），循环轮数由 `AGENT_MAX_STEPS=3` 限制，耗尽后强制基于已有资料作答
- **意图路由**：参观信息走结构化工具，史料不足走补充检索，充足则直接依据参考资料作答
- **安全约束**：工具白名单注册、参数 Pydantic 校验、每轮最多 2 个工具 + 总轮数硬上限，不做无限制自主规划
- **流式事件**：工具执行时 SSE 先推送 `tool` 事件（前端显示"正在查询…"，旧版前端自动忽略，向后兼容）
- **开关**：`backend/.env` 中 `TOOL_CALLING_ENABLED=false` 回退纯 RAG；`AGENT_MAX_STEPS=1` 可退回单轮工具模式

## 常见问题

- **LLM 请求失败**：确认 `backend/.env` 中 `ZHIPU_API_KEY` 已填写且有效；Docker 部署时需通过环境变量传入。
- **首次问答很慢**：BGE 权重加载需要预热，属正常现象。
- **想换其他模型**：`.env` 中改 `LLM_MODEL`（如 `glm-4.5-flash`）。
- **回答太保守**：可适当调高 `SCORE_THRESHOLD` 相关度阈值或 `TOP_K`。
