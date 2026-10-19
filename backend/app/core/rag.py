# -*- coding: utf-8 -*-
"""RAG 核心管线：检索 -> 上下文拼装 -> 分级 Prompt -> 智谱 GLM 生成。

支持流式（SSE）与一次性两种输出模式。
"""
import re
from typing import AsyncGenerator, List

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.config import CACHE_ENABLED, MAX_HISTORY_ROUNDS, TOOL_CALLING_ENABLED
from app.core import cache as answer_cache
from app.core.llm import get_llm
from app.core.prompts import CHAT_TEMPLATE, build_system_prompt
from app.core.tools import MAX_TOOLS_PER_CALL, get_tools, run_tool_calls
from app.core.vectorstore import search

_CITATION_RE = re.compile(r"\s*【?\[(\d+)\]】?\s*")

# 开启工具调用时追加到 System Prompt 的意图路由提示：
# 参观信息走工具（结构化数据更准确），史实问题走 RAG 参考资料
_TOOL_HINT = (
    "\n\n【工具使用】你可以调用本地查询工具获取准确的实时信息：\n"
    "- query_venue_info(venue_name)：查询某场馆的地址、开放时间、预约方式、建议游览时长等参观信息\n"
    "- list_venues(theme)：按主题列出可参观的场馆目录\n"
    "学生询问开放时间、预约方式、地址等参观信息时，优先调用工具获取数据；"
    "历史故事类问题直接依据参考资料作答，不需要调用工具。"
)


def _format_context(docs: List[Document]) -> str:
    """将召回文档编号拼装为参考资料块，便于模型引用与前端展示来源。"""
    if not docs:
        return "（未检索到相关史料）"
    blocks = []
    for i, doc in enumerate(docs, 1):
        venue = doc.metadata.get("venue", "未知来源")
        section = doc.metadata.get("section", "")
        blocks.append(f"[{i}] 来源：{venue}{('·' + section) if section else ''}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


def clean_citation(text: str) -> str:
    """移除正文中的 [1] 式引用标记（来源已单独展示）。"""
    return _CITATION_RE.sub(" ", text)


def build_messages(
    question: str,
    grade: str | None,
    docs: List[Document],
    history: List[dict] | None = None,
    extra_task: str = "",
    use_tools: bool = False,
) -> list:
    """构建完整的消息列表（含裁剪后的对话历史）。"""
    system_prompt = build_system_prompt(grade, extra_task)
    if use_tools:
        system_prompt += _TOOL_HINT
    msgs = [("system", system_prompt)]
    if history:
        for h in history[-MAX_HISTORY_ROUNDS * 2:]:
            role = h.get("role", "user")
            if role in ("user", "assistant"):
                msgs.append((role, h.get("content", "")))
    msgs.append(("human", CHAT_TEMPLATE.format(
        context=_format_context(docs), question=question,
    )))
    return msgs


def _sources_of(docs: List[Document]) -> list:
    """提取召回文档的来源摘要（场馆 + 小节 + 片段）。"""
    return [
        {
            "venue": d.metadata.get("venue", ""),
            "section": d.metadata.get("section", ""),
            "snippet": d.page_content.strip()[:80],
        }
        for d in docs
    ]


async def agenerate(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
) -> dict:
    """一次性生成完整回答。

    仅对无对话历史的提问启用语义缓存（追问依赖上下文，不适合回放缓存答案）；
    缓存模块任何异常均在内部兜底为"未命中"，不会阻断正常管线。

    Returns:
        {"answer": str, "sources": [{venue, section, snippet}]}
    """
    if CACHE_ENABLED and not history:
        hit = answer_cache.lookup(question, grade, venue_filter)
        if hit is not None:
            return {"answer": hit["answer"], "sources": hit["sources"], "cached": True}

    docs = search(question, where={"venue": venue_filter} if venue_filter else None)
    messages = build_messages(question, grade, docs, history, extra_task, use_tools=TOOL_CALLING_ENABLED)
    llm = get_llm(streaming=False)
    tools_used: list[str] = []
    if TOOL_CALLING_ENABLED:
        # 绑定工具的同一次调用：模型仅在参观信息类问题上发起 tool_calls，
        # 普通史实问题不调用工具，仍是单次 LLM 调用（零额外延迟）
        resp = await llm.bind_tools(get_tools()).ainvoke(messages)
        calls = (resp.tool_calls or [])[:MAX_TOOLS_PER_CALL]
        if calls:
            tools_used = [c.get("name", "") for c in calls]
            # 本地执行工具（毫秒级，不调 LLM），结果以 ToolMessage 回填
            messages = list(messages) + [
                AIMessage(content=resp.content or "", tool_calls=calls),
                *run_tool_calls(resp),
            ]
            # 第二次调用不再绑定工具（单轮工具调用上限），生成最终分级回答
            resp = await llm.ainvoke(messages)
    else:
        resp = await llm.ainvoke(messages)
    sources = _sources_of(docs)
    result = {"answer": clean_citation(resp.content), "sources": sources}
    if tools_used:
        result["tools_used"] = tools_used
    if CACHE_ENABLED and not history:
        answer_cache.store(question, grade, venue_filter, result["answer"], sources)
    return result


async def agenerate_stream(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
) -> AsyncGenerator[dict, None]:
    """流式生成：先 yield 检索来源，再逐块 yield 文本增量。"""
    # 语义缓存命中：以事件流形式一次性回放，免调 LLM
    if CACHE_ENABLED and not history:
        hit = answer_cache.lookup(question, grade, venue_filter)
        if hit is not None:
            yield {"type": "sources", "data": hit["sources"]}
            yield {"type": "delta", "data": hit["answer"]}
            yield {"type": "done", "data": hit["answer"], "cached": True}
            return

    docs = search(question, where={"venue": venue_filter} if venue_filter else None)
    sources = _sources_of(docs)
    yield {"type": "sources", "data": sources}

    messages = build_messages(question, grade, docs, history, extra_task, use_tools=TOOL_CALLING_ENABLED)
    llm = get_llm(streaming=True)
    buffer = []

    async def _stream(runnable, msgs):
        """流式产出文本增量并累积到 buffer。"""
        async for chunk in runnable.astream(msgs):
            if chunk.content:
                buffer.append(chunk.content)
                yield {"type": "delta", "data": chunk.content}

    if TOOL_CALLING_ENABLED:
        # 阶段一（决策与生成合一）：绑定工具的流式调用。
        # 普通问题模型直接流式产出正文（体验与未开启工具时完全一致）；
        # 参观信息类问题模型会发起 tool_calls（此时正文一般为空），聚合后本地执行。
        aggregated = None
        async for chunk in llm.bind_tools(get_tools()).astream(messages):
            if chunk.content:
                buffer.append(chunk.content)
                yield {"type": "delta", "data": chunk.content}
            aggregated = chunk if aggregated is None else aggregated + chunk
        calls = []
        if aggregated is not None:
            calls = (getattr(aggregated, "tool_calls", None) or [])[:MAX_TOOLS_PER_CALL]
        if calls:
            # 通知前端正在查询（前端不识别该事件时自动忽略，向后兼容）
            yield {"type": "tool", "data": [
                {"name": c.get("name", ""), "args": c.get("args", {})} for c in calls
            ]}
            messages = list(messages) + [
                AIMessage(content=aggregated.content or "", tool_calls=calls),
                *run_tool_calls(aggregated),
            ]
            # 阶段二：基于工具结果流式生成最终分级回答（不再绑定工具，单轮上限）
            async for ev in _stream(llm, messages):
                yield ev
    else:
        async for ev in _stream(llm, messages):
            yield ev

    full = clean_citation("".join(buffer))
    if CACHE_ENABLED and not history:
        answer_cache.store(question, grade, venue_filter, full, sources)
    yield {"type": "done", "data": full}
