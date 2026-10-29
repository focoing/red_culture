# -*- coding: utf-8 -*-
"""对话服务：会话管理（SQLite 持久化）+ RAG 分级问答。"""
import time

from app.core import storage
from app.core.prompts import TOUR_SCENE_TASK
from app.core.rag import agenerate_stream


def new_session() -> str:
    return storage.new_session()


def get_history(session_id: str) -> list[dict]:
    return storage.get_history(session_id)


def append_history(session_id: str, question: str, answer: str) -> None:
    storage.append_history(session_id, question, answer)


async def chat_stream(
    session_id: str,
    question: str,
    grade: str,
    venue: str | None = None,
    section: str | None = None,
):
    """流式对话生成器：透传 RAG 流事件，结束后写回会话历史。

    导览随行问答：传入 venue + section 时注入当前展区场景（检索限定整馆，
    保证跨点位问题也能召回相关史料），并切换为口语化的随行应答风格。
    """
    extra_task = ""
    if venue and section:
        extra_task = TOUR_SCENE_TASK.format(venue=venue, section=section)
    history = get_history(session_id)
    full_answer_parts = []
    started = time.time()

    async for event in agenerate_stream(
        question, grade=grade, history=history,
        venue_filter=venue, extra_task=extra_task,
    ):
        if event["type"] == "delta":
            full_answer_parts.append(event["data"])
        elif event["type"] == "done":
            event = {**event, "elapsed": round(time.time() - started, 2)}
        yield event

    if full_answer_parts:
        append_history(session_id, question, "".join(full_answer_parts))
