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
| 完全本地化 | Embedding 与 LLM 均本地部署，无需外部 API Key，数据不出校 |

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
│   │   │   ├── rag.py           # RAG 管线（流式/一次性 + 语义缓存接入）
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
└── docker-compose.yml           # ollama + backend + frontend
```

## 快速开始（Docker 一键部署，推荐）

```bash
# 1. 构建并启动三个服务
docker compose up -d --build

# 2. 首次启动需拉取 Qwen2.5 模型（约 4.7GB）
docker compose exec ollama ollama pull qwen2.5:7b

# 3. 重启后端以完成首次知识库入库（entrypoint 自动执行 ingest）
docker compose restart backend
```

- 前端：http://localhost:8080
- 后端接口文档：http://localhost:8000/docs

> GPU 加速：安装 nvidia-container-toolkit 后取消 docker-compose.yml 中 GPU 注释即可。

## 本地开发

### 1. 准备 Ollama

```bash
# 安装 Ollama（https://ollama.com）
ollama pull qwen2.5:7b
ollama serve
```

### 2. 后端

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt

copy .env.example .env                            # 按需修改
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
| GET | `/api/health` | 健康检查（Ollama / 知识库状态） |
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
│ Ollama Qwen2.5  │── SSE 流式输出 + 来源引用
└─────────────────┘
```

降低幻觉的三道约束：① 检索相关度阈值过滤弱相关史料；② System Prompt 硬性规定"只依据参考资料作答，不足则如实说明"；③ 回答附带来源场馆与出处，便于师生核查。

## 知识库数据

`backend/data/venues/` 收录 15 篇武汉红色场馆史料（Markdown + front matter 元数据），覆盖四大主题：

- **辛亥首义**：辛亥革命武昌起义纪念馆（红楼）、辛亥革命博物馆、武昌起义门
- **党史转折**：八七会议会址、中共五大会址、农讲所、中共中央机关旧址、宋庆龄汉口旧居
- **工人运动**：武汉二七纪念馆、施洋烈士陵园
- **抗战烽火**：八路军武汉办事处、汉口新四军军部旧址、中山舰博物馆
- **综述**：武汉红色文化总览（线路组织与学段建议，供路线生成检索）

新增史料：在 `data/venues/` 添加同格式 Markdown 后执行 `python ingest.py` 即可。

## 学段分级 Prompt 摘要

| 学段 | 语言风格 | 篇幅 | 任务侧重 |
|---|---|---|---|
| 小学低年级 | 讲故事、短句、比喻 | ≤250 字 | 观察类："找一找""画一画" |
| 小学高年级 | 通俗准确、三要素 | ≤350 字 | 记录类：研学手册、动手小任务 |
| 初中 | 脉络因果、衔接课本 | ≤500 字 | 思考类：比较与分析 |
| 高中 | 论从史出、多元视角 | ≤700 字 | 表达类：小论文、小组研讨 |

## 智能工具调用（Function Calling）

对话接口在 RAG 管线上叠加了 GLM 原生 Function Calling（LangChain `@tool` + `bind_tools`）：工具与文本生成共用同一次 LLM 调用，仅当模型判断需要时才发起，普通史实问题不增加任何延迟。

| 工具 | 功能 | 典型触发问题 |
|---|---|---|
| `query_venue_info` | 查询单个场馆的地址/开放时间/预约方式/建议时长 | "辛亥革命博物馆要预约吗？几点开门？" |
| `list_venues` | 按主题列出场馆目录 | "抗战主题有哪些场馆可以参观？" |

- **意图路由**：参观信息类问题由模型自主调用工具获取结构化数据（读取史料 front matter，毫秒级本地查询）；历史故事类问题直接依据 RAG 参考资料作答
- **安全约束**：工具白名单注册、参数 Pydantic 校验、单轮最多执行 2 个工具、不做多步自主规划
- **流式事件**：工具执行时 SSE 先推送 `tool` 事件（旧版前端不识别时自动忽略，向后兼容）
- **开关**：`backend/.env` 中 `TOOL_CALLING_ENABLED=false` 可整体关闭，回退纯 RAG 模式

## 常见问题

- **LLM 请求失败**：确认 `backend/.env` 中 `ZHIPU_API_KEY` 已填写且有效；Docker 部署时需通过环境变量传入。
- **首次问答很慢**：BGE 权重加载需要预热，属正常现象。
- **想换其他模型**：`.env` 中改 `LLM_MODEL`（如 `glm-4.5-flash`）。
- **回答太保守**：可适当调高 `SCORE_THRESHOLD` 相关度阈值或 `TOP_K`。
