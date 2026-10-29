# -*- coding: utf-8 -*-
"""导览服务：点位讲解词流式生成（路线导览 RAG）。

复用 RAG 管线，以「场馆 + 小节」双过滤做点位级检索（召回不足自动放宽整馆），
附加导览讲解任务 Prompt。讲解词无对话历史，可命中语义缓存——
同一场馆同学段的点位讲解只生成一次，之后零延迟、零 LLM 消耗。
"""
from typing import AsyncGenerator

from app.core.prompts import TOUR_EXPLAIN_TASK
from app.core.rag import agenerate_stream


async def explain_stream(venue: str, section: str, grade: str) -> AsyncGenerator[dict, None]:
    """流式生成某场馆某点位的导览讲解词（含结尾研学小任务）。

    use_tools=False：检索已由三级放宽管线完成（venue+section 精确取料），
    无需工具循环，单轮流式直出，首字延迟更低。
    """
    question = f"请为「{venue}」的「{section}」展区撰写本点位的导览讲解词。"
    async for event in agenerate_stream(
        question, grade=grade,
        venue_filter=venue, section_filter=section,
        extra_task=TOUR_EXPLAIN_TASK, use_tools=False,
    ):
        yield event
