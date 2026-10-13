# -*- coding: utf-8 -*-
"""对话服务：会话管理（内存版）+ RAG 分级问答。"""
import time
import uuid
from collections import defaultdict, deque

from app.config import MAX_HISTORY_ROUNDS
from app.core.rag import agenerate_stream

# 简单内存会话池：session_id -> deque[(role, content)]
# 生产环境可替换为 Redis
_SESSIONS: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY_ROUNDS * 2))


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    _SESSIONS[sid] = deque(maxlen=MAX_HISTORY_ROUNDS * 2)
    return sid


def get_history(session_id: str) -> list[dict]:
    return [{"role": r, "content": c} for r, c in _SESSIONS[session_id]]


def append_history(session_id: str, question: str, answer: str) -> None:
    hist = _SESSIONS[session_id]
    hist.append(("user", question))
    hist.append(("assistant", answer))


async def chat_stream(session_id: str, question: str, grade: str):
    """流式对话生成器：透传 RAG 流事件，结束后写回会话历史。"""
    history = get_history(session_id)
    full_answer_parts = []
    started = time.time()

    async for event in agenerate_stream(question, grade, history=history):
        if event["type"] == "delta":
            full_answer_parts.append(event["data"])
        elif event["type"] == "done":
            event = {**event, "elapsed": round(time.time() - started, 2)}
        yield event

    if full_answer_parts:
        append_history(session_id, question, "".join(full_answer_parts))
