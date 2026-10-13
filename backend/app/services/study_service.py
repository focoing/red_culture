# -*- coding: utf-8 -*-
"""研学服务：路线生成 / 研学任务单生成 / 场馆讲解词生成。

三者均复用 RAG 管线，仅附加不同的任务级 Prompt 指令。
"""
from app.core.prompts import EXPLAIN_TASK, ROUTE_TASK, TASK_TASK
from app.core.rag import agenerate


def _route_query(theme: str, days: str) -> str:
    return (
        f"请为武汉红色研学规划路线。研学主题：{theme or '综合红色文化'}；"
        f"计划时长：{days}。请重点参考【武汉红色文化总览】中提到的经典线路与交通建议。"
    )


async def generate_route(grade: str, theme: str = "", days: str = "一日") -> dict:
    """生成研学路线（基于总览与场馆史料检索）。"""
    return await agenerate(
        _route_query(theme, days), grade=grade, extra_task=ROUTE_TASK,
    )


async def generate_tasks(grade: str, venue: str) -> dict:
    """为指定场馆生成研学任务单。"""
    query = f"请为武汉红色场馆「{venue}」生成研学任务单，任务须围绕该场馆的史料设计。"
    return await agenerate(
        query, grade=grade, extra_task=TASK_TASK, venue_filter=venue,
    )


async def generate_explanation(grade: str, venue: str, topic: str = "") -> dict:
    """为场馆生成导览讲解词。"""
    topic_part = f"，讲解重点是「{topic}」" if topic else ""
    query = f"请为武汉红色场馆「{venue}」撰写讲解词{topic_part}。"
    return await agenerate(
        query, grade=grade, extra_task=EXPLAIN_TASK, venue_filter=venue,
    )
