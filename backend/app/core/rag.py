# -*- coding: utf-8 -*-
"""RAG 核心管线：检索 -> 上下文拼装 -> 分级 Prompt -> 智谱 GLM 生成。

支持流式（SSE）与一次性两种输出模式。
回答保留 [n] 引用角标（与参考资料编号对应），来源原文随 sources 下发，
前端渲染为可点击角标 + 史料原文展开，实现逐句溯源。
"""
from typing import AsyncGenerator, List

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.config import AGENT_MAX_STEPS, CACHE_ENABLED, MAX_HISTORY_ROUNDS, SECTION_MIN_DOCS, TOOL_CALLING_ENABLED
from app.core import cache as answer_cache
from app.core.llm import get_llm
from app.core.prompts import CHAT_TEMPLATE, build_system_prompt
from app.core.tools import MAX_TOOLS_PER_CALL, get_tools, run_tool_calls
from app.core.vectorstore import search

# 开启工具调用时追加到 System Prompt 的意图路由提示：
# 参观信息走结构化工具，史料不足走补充检索，充足则直接依据参考资料作答
_TOOL_HINT = (
    "\n\n【工具使用】你可以调用本地工具获取信息，并可多步组合使用"
    f"（每轮最多 2 个，总共最多 {AGENT_MAX_STEPS} 轮）：\n"
    "- search_history(query, venue)：在史料知识库中检索史料段落——当参考资料不足以回答时，"
    "用不同关键词再次检索，或限定某场馆检索\n"
    "- query_venue_info(venue_name)：查询某场馆的地址、开放时间、预约方式、建议游览时长等参观信息\n"
    "- list_venues(theme)：按主题列出可参观的场馆目录\n"
    "使用原则：参观信息类问题优先调用工具获取结构化数据；参考资料不足时可多步检索补全；"
    "资料已足够时直接依据参考资料作答，不要调用工具。"
)


def _retrieve(
    question: str,
    venue_filter: str | None = None,
    section_filter: str | None = None,
) -> List[Document]:
    """导览三级放宽检索：点位内 -> 场馆内 -> 全局。

    - 点位讲解（venue+section 双过滤）：召回不足 SECTION_MIN_DOCS 时放宽为整馆，
      查询本身含点位名，整馆召回仍会优先命中本点位史料块；
    - 随行问答（仅 venue 过滤）：直接整馆检索，保证跨点位问题（如在打捞展区问
      萨师俊）也能召回金口之战等其它小节的相关史料。
    """
    if venue_filter and section_filter:
        docs = search(question, where={"venue": venue_filter, "section": section_filter})
        if len(docs) >= SECTION_MIN_DOCS:
            return docs
    if venue_filter:
        return search(question, where={"venue": venue_filter})
    return search(question)


def _cache_dim(venue_filter: str | None, section_filter: str | None) -> str | None:
    """语义缓存隔离维度：点位讲解把 section 并入隔离维度。

    讲解问题是模板化文本，不同站点仅差点位名几个字，语义相似度极高；
    若 section 不进隔离维度，第 2 站会误命中第 1 站的缓存答案（串台）。
    venue_filter 在缓存 SQL 中是精确匹配维度，可直接拼接。
    """
    if not section_filter:
        return venue_filter
    return f"{venue_filter}｜{section_filter}" if venue_filter else section_filter


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
    """提取召回文档来源（场馆 + 小节 + 摘要 + 完整原文）。

    content 为该召回块全文，前端点击引用角标 [n] 时展开对应原文，实现逐句溯源。
    """
    return [
        {
            "venue": d.metadata.get("venue", ""),
            "section": d.metadata.get("section", ""),
            "snippet": d.page_content.strip()[:80],
            "content": d.page_content.strip(),
        }
        for d in docs
    ]


async def agenerate(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
    section_filter: str | None = None,
    use_tools: bool | None = None,
) -> dict:
    """一次性生成完整回答。

    仅对无对话历史的提问启用语义缓存（追问依赖上下文，不适合回放缓存答案）；
    缓存模块任何异常均在内部兜底为"未命中"，不会阻断正常管线。

    Args:
        use_tools: 是否启用工具调用循环。None 跟随全局 TOOL_CALLING_ENABLED；
            点位讲解等检索已由管线完成的场景传 False，单轮直出更快。

    Returns:
        {"answer": str, "sources": [{venue, section, snippet}]}
    """
    tools_on = TOOL_CALLING_ENABLED if use_tools is None else use_tools
    if CACHE_ENABLED and not history:
        hit = answer_cache.lookup(question, grade, _cache_dim(venue_filter, section_filter))
        if hit is not None:
            return {"answer": hit["answer"], "sources": hit["sources"], "cached": True}

    docs = _retrieve(question, venue_filter, section_filter)
    messages = build_messages(question, grade, docs, history, extra_task, use_tools=tools_on)
    llm = get_llm(streaming=False)
    tools_used: list[str] = []
    if tools_on:
        # 受控 Agentic 循环：模型按需调用工具（含史料补充检索），最多 AGENT_MAX_STEPS 轮；
        # 普通史实问题首轮即直接作答（零额外延迟）
        llm_tools = llm.bind_tools(get_tools())
        steps = 0
        while steps < AGENT_MAX_STEPS:
            resp = await llm_tools.ainvoke(messages)
            calls = (resp.tool_calls or [])[:MAX_TOOLS_PER_CALL]
            if not calls:
                break
            tools_used.extend(c.get("name", "") for c in calls)
            # 本地执行工具（毫秒级，不调 LLM），结果以 ToolMessage 回填
            messages = list(messages) + [
                AIMessage(content=resp.content or "", tool_calls=calls),
                *run_tool_calls(resp),
            ]
            steps += 1
        else:
            # 步数耗尽仍请求工具：强制基于已获取资料生成最终回答（不再绑定工具）
            messages.append(("system", "工具调用已达上限，请直接依据已获取的资料回答学生问题。"))
            resp = await llm.ainvoke(messages)
    else:
        resp = await llm.ainvoke(messages)
    sources = _sources_of(docs)
    result = {"answer": resp.content, "sources": sources}
    if tools_used:
        result["tools_used"] = tools_used
    if CACHE_ENABLED and not history:
        answer_cache.store(question, grade, _cache_dim(venue_filter, section_filter),
                           result["answer"], sources)
    return result


async def agenerate_stream(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
    section_filter: str | None = None,
    use_tools: bool | None = None,
) -> AsyncGenerator[dict, None]:
    """流式生成：先 yield 检索来源，再逐块 yield 文本增量。

    use_tools: 是否启用工具调用循环；None 跟随全局开关。
    点位讲解传 False（检索已由三级放宽管线完成），单轮流式直出更快。
    """
    tools_on = TOOL_CALLING_ENABLED if use_tools is None else use_tools
    # 语义缓存命中：以事件流形式一次性回放，免调 LLM
    if CACHE_ENABLED and not history:
        hit = answer_cache.lookup(question, grade, _cache_dim(venue_filter, section_filter))
        if hit is not None:
            yield {"type": "sources", "data": hit["sources"]}
            yield {"type": "delta", "data": hit["answer"]}
            yield {"type": "done", "data": hit["answer"], "cached": True}
            return

    docs = _retrieve(question, venue_filter, section_filter)
    sources = _sources_of(docs)
    yield {"type": "sources", "data": sources}

    messages = build_messages(question, grade, docs, history, extra_task, use_tools=tools_on)
    llm = get_llm(streaming=True)
    final_chunks: list[str] = []  # 仅最终回答轮的文本（中间工具轮文本不计入完整答案）

    async def _stream(runnable, msgs):
        """流式产出文本增量并累积到 final_chunks。"""
        async for chunk in runnable.astream(msgs):
            if chunk.content:
                final_chunks.append(chunk.content)
                yield {"type": "delta", "data": chunk.content}

    if tools_on:
        # 受控 Agentic 循环（流式版）：普通问题首轮直接流式产出（体验与纯 RAG 完全一致）；
        # 模型请求工具时推送 tool 事件、本地执行后进入下一轮，最多 AGENT_MAX_STEPS 轮
        steps = 0
        while steps < AGENT_MAX_STEPS:
            aggregated = None
            step_chunks: list[str] = []
            async for chunk in llm.bind_tools(get_tools()).astream(messages):
                if chunk.content:
                    step_chunks.append(chunk.content)
                    yield {"type": "delta", "data": chunk.content}
                aggregated = chunk if aggregated is None else aggregated + chunk
            calls = []
            if aggregated is not None:
                calls = (getattr(aggregated, "tool_calls", None) or [])[:MAX_TOOLS_PER_CALL]
            if not calls:
                final_chunks = step_chunks  # 本轮即最终回答
                break
            # 通知前端正在查询（前端不识别该事件时自动忽略，向后兼容）
            yield {"type": "tool", "data": [
                {"name": c.get("name", ""), "args": c.get("args", {})} for c in calls
            ]}
            messages = list(messages) + [
                AIMessage(content=aggregated.content or "", tool_calls=calls),
                *run_tool_calls(aggregated),
            ]
            steps += 1
        else:
            # 步数耗尽：强制基于已获取资料流式生成最终回答（不再绑定工具）
            messages.append(("system", "工具调用已达上限，请直接依据已获取的资料回答学生问题。"))
            async for ev in _stream(llm, messages):
                yield ev
    else:
        async for ev in _stream(llm, messages):
            yield ev

    full = "".join(final_chunks)
    if CACHE_ENABLED and not history:
        answer_cache.store(question, grade, _cache_dim(venue_filter, section_filter), full, sources)
    yield {"type": "done", "data": full}
