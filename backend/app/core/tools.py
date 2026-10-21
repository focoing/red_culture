# -*- coding: utf-8 -*-
"""GLM Function Calling 工具集：本地白名单查询，供模型按需调用。

设计约束（面向中小学生场景的稳健性考虑）：
    - 只读白名单：仅暴露场馆信息查询与史料检索类工具，杜绝模型拼接执行任意指令；
    - 零 LLM 成本：工具均为本地毫秒级操作（读取史料 front matter / 向量检索），
      不发起额外的大模型请求；
    - 硬上限：单轮最多执行 MAX_TOOLS_PER_CALL 个工具，决策循环轮数由
      config.AGENT_MAX_STEPS 限制（rag.py 中控制），防止模型滥用。
"""
import json

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from app.services import venue_service

# 单轮最多执行的工具数（超出直接截断）
MAX_TOOLS_PER_CALL = 2


@tool
def query_venue_info(venue_name: str) -> str:
    """查询指定红色文化场馆的结构化参观信息：地址、所在区、开放时间、预约方式、建议游览时长、适合学段。

    当用户询问某个场馆"在哪里/怎么去/几点开门/要不要预约/门票/适合参观多久"等参观信息时调用。

    Args:
        venue_name: 场馆名称（支持模糊匹配），如"辛亥革命博物馆"、"八七会议会址"
    """
    venue = venue_service.get_venue(venue_name.strip())
    if not venue:
        return f"未找到场馆「{venue_name}」。请调用 list_venues 查看当前支持的场馆目录。"
    return json.dumps(venue, ensure_ascii=False)


@tool
def list_venues(theme: str = "") -> str:
    """列出知识库支持的全部红色文化场馆目录（名称/地址/主题/开放时间），可按主题筛选。

    当用户询问"有哪些场馆可以参观"、"某主题下有什么场馆"时调用。

    Args:
        theme: 可选主题筛选词，如"辛亥革命"、"党史"、"工运"、"抗战"；留空返回全部
    """
    venues = venue_service.list_venues()
    kw = theme.strip()
    if kw:
        venues = [v for v in venues if kw in v["theme"] or v["theme"] in kw]
    if not venues:
        return f"未找到主题「{theme}」的场馆。当前支持的主题：{'、'.join(venue_service.themes())}"
    catalog = [
        {
            "name": v["name"],
            "address": v["address"],
            "theme": v["theme"],
            "opening_hours": v["opening_hours"],
        }
        for v in venues
    ]
    return json.dumps({"count": len(catalog), "venues": catalog}, ensure_ascii=False)


@tool
def search_history(query: str, venue: str = "") -> str:
    """在武汉红色文化史料知识库中检索相关史料段落（向量检索，最多返回 5 段）。

    当已有参考资料不足以回答学生问题时，用不同关键词/表述再次检索；也可限定在某场馆史料内检索。
    支持多步组合：先检索某主题，再根据结果换关键词细化检索。

    Args:
        query: 检索关键词或问题表述（可换不同说法多次检索）
        venue: 可选，限定场馆全名（如"辛亥革命博物馆"），留空检索全部史料
    """
    from app.core.vectorstore import search as _search  # 延迟导入，避免模块级循环依赖

    docs = _search(query, where={"venue": venue.strip()} if venue.strip() else None)
    if not docs:
        return "（未检索到相关史料，请尝试更换关键词）"
    blocks = []
    for i, d in enumerate(docs, 1):
        v = d.metadata.get("venue", "未知来源")
        s = d.metadata.get("section", "")
        head = f"[{i}] {v}{('·' + s) if s else ''}"
        blocks.append(f"{head}\n{d.page_content.strip()[:400]}")
    return "\n\n".join(blocks)


# 工具白名单：模型可调用的全部工具（新增工具必须在此注册才会生效）
_TOOLS = [query_venue_info, list_venues, search_history]
_TOOL_MAP = {t.name: t for t in _TOOLS}


def get_tools() -> list:
    """返回绑定给 LLM 的工具列表。"""
    return list(_TOOLS)


def run_tool_calls(ai_message) -> list[ToolMessage]:
    """执行模型请求的工具调用（白名单校验 + 数量硬上限），返回 ToolMessage 列表。

    任何工具异常都转为错误文本回填给模型，不影响主流程。
    """
    results = []
    for tc in (getattr(ai_message, "tool_calls", None) or [])[:MAX_TOOLS_PER_CALL]:
        name = tc.get("name", "")
        try:
            tool_fn = _TOOL_MAP.get(name)
            if tool_fn is None:
                raise ValueError(f"未在白名单注册的工具：{name}")
            output = tool_fn.invoke(tc.get("args", {}))
        except Exception as e:  # noqa: BLE001
            output = f"工具执行失败：{e}"
        results.append(ToolMessage(content=str(output), tool_call_id=tc.get("id", "")))
    return results
