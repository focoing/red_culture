# -*- coding: utf-8 -*-
"""RAG 核心管线：检索 -> 上下文拼装 -> 分级 Prompt -> Qwen2.5 生成。

支持流式（SSE）与一次性两种输出模式。
"""
import re
from typing import AsyncGenerator, List

from langchain_core.documents import Document

from app.config import MAX_HISTORY_ROUNDS
from app.core.llm import get_llm
from app.core.prompts import CHAT_TEMPLATE, build_system_prompt
from app.core.vectorstore import search

_CITATION_RE = re.compile(r"\s*【?\[(\d+)\]】?\s*")


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
) -> list:
    """构建完整的消息列表（含裁剪后的对话历史）。"""
    system_prompt = build_system_prompt(grade, extra_task)
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


async def agenerate(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
) -> dict:
    """一次性生成完整回答。

    Returns:
        {"answer": str, "sources": [{venue, section, snippet}]}
    """
    docs = search(question, where={"venue": venue_filter} if venue_filter else None)
    messages = build_messages(question, grade, docs, history, extra_task)
    llm = get_llm(streaming=False)
    resp = await llm.ainvoke(messages)
    return {
        "answer": clean_citation(resp.content),
        "sources": [
            {
                "venue": d.metadata.get("venue", ""),
                "section": d.metadata.get("section", ""),
                "snippet": d.page_content.strip()[:80],
            }
            for d in docs
        ],
    }


async def agenerate_stream(
    question: str,
    grade: str | None,
    history: List[dict] | None = None,
    extra_task: str = "",
    venue_filter: str | None = None,
) -> AsyncGenerator[dict, None]:
    """流式生成：先 yield 检索来源，再逐块 yield 文本增量。"""
    docs = search(question, where={"venue": venue_filter} if venue_filter else None)
    yield {
        "type": "sources",
        "data": [
            {
                "venue": d.metadata.get("venue", ""),
                "section": d.metadata.get("section", ""),
                "snippet": d.page_content.strip()[:80],
            }
            for d in docs
        ],
    }

    messages = build_messages(question, grade, docs, history, extra_task)
    llm = get_llm(streaming=True)
    buffer = []
    async for chunk in llm.astream(messages):
        if chunk.content:
            buffer.append(chunk.content)
            yield {"type": "delta", "data": chunk.content}
    yield {"type": "done", "data": clean_citation("".join(buffer))}
