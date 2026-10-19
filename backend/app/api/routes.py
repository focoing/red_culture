# -*- coding: utf-8 -*-
"""API 路由层。

端点：
    GET  /api/health              健康检查（含 LLM/知识库状态）
    GET  /api/venues              场馆目录
    GET  /api/grades              学段定义
    POST /api/chat/stream         分级 RAG 问答（SSE 流式）
    POST /api/chat                分级 RAG 问答（一次性）
    POST /api/route               研学路线生成
    POST /api/tasks               研学任务单生成
    POST /api/explanation         场馆讲解词生成
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import DEFAULT_GRADE, GRADE_LEVELS, LLM_MODEL
from app.core import cache as answer_cache
from app.core.llm import check_llm
from app.core.prompts import grade_label
from app.core.vectorstore import collection_stats
from app.services import chat_service, study_service, venue_service
from openai import RateLimitError

router = APIRouter(prefix="/api")


async def _llm_call(fn, *args, **kwargs):
    """执行 LLM 生成调用；智谱限流（429）时转为友好的 503 提示。"""
    try:
        return await fn(*args, **kwargs)
    except RateLimitError:
        raise HTTPException(status_code=503, detail="智谱大模型当前繁忙（429 限流），请稍后重试")


# ---------------- Schemas ----------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="学生提问")
    grade: str = Field(DEFAULT_GRADE, description="学段 primary_low/primary_high/junior/senior")
    session_id: str | None = Field(None, description="会话ID，为空则新建")
    venue: str | None = Field(None, description="限定场馆（可选）")


class RouteRequest(BaseModel):
    grade: str = Field(DEFAULT_GRADE)
    theme: str = Field("", description="主题：辛亥革命/党史/工运/抗战/综合")
    days: str = Field("一日", description="半日/一日")


class TaskRequest(BaseModel):
    grade: str = Field(DEFAULT_GRADE)
    venue: str = Field(..., description="场馆名称")


class ExplainRequest(BaseModel):
    grade: str = Field(DEFAULT_GRADE)
    venue: str = Field(..., description="场馆名称")
    topic: str = Field("", description="讲解重点（可选）")


def _validate_grade(grade: str) -> str:
    if grade not in GRADE_LEVELS:
        raise HTTPException(400, f"非法学段 {grade}，可选：{list(GRADE_LEVELS)}")
    return grade


# ---------------- 基础端点 ----------------
@router.get("/health")
def health():
    return {
        "status": "ok",
        "llm": {"model": LLM_MODEL, "llm_ready": check_llm()},
        "kb": collection_stats(),
        "cache": answer_cache.stats(),
    }


@router.get("/venues")
def venues(theme: str | None = None):
    data = venue_service.list_venues()
    if theme:
        data = [v for v in data if v["theme"] == theme]
    return {"venues": data, "themes": venue_service.themes()}


@router.get("/grades")
def grades():
    return {"grades": GRADE_LEVELS, "default": DEFAULT_GRADE}


# ---------------- 对话 ----------------
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    _validate_grade(req.grade)
    sid = req.session_id or chat_service.new_session()
    question = req.question.strip()

    async def sse():
        yield f"event: meta\ndata: {json.dumps({'session_id': sid, 'grade_label': grade_label(req.grade)}, ensure_ascii=False)}\n\n"
        try:
            async for event in chat_service.chat_stream(sid, question, req.grade):
                payload = json.dumps(event, ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@router.post("/chat")
async def chat(req: ChatRequest):
    _validate_grade(req.grade)
    sid = req.session_id or chat_service.new_session()
    from app.core.rag import agenerate

    result = await _llm_call(
        agenerate,
        req.question.strip(), grade=req.grade,
        history=chat_service.get_history(sid),
        venue_filter=req.venue,
    )
    chat_service.append_history(sid, req.question.strip(), result["answer"])
    return {"session_id": sid, **result}


# ---------------- 研学服务 ----------------
@router.post("/route")
async def route(req: RouteRequest):
    _validate_grade(req.grade)
    result = await _llm_call(study_service.generate_route, req.grade, req.theme, req.days)
    return {"grade_label": grade_label(req.grade), **result}


@router.post("/tasks")
async def tasks(req: TaskRequest):
    _validate_grade(req.grade)
    if not venue_service.get_venue(req.venue):
        raise HTTPException(404, f"未找到场馆：{req.venue}")
    result = await _llm_call(study_service.generate_tasks, req.grade, req.venue)
    return {"grade_label": grade_label(req.grade), **result}


@router.post("/explanation")
async def explanation(req: ExplainRequest):
    _validate_grade(req.grade)
    if not venue_service.get_venue(req.venue):
        raise HTTPException(404, f"未找到场馆：{req.venue}")
    result = await _llm_call(study_service.generate_explanation, req.grade, req.venue, req.topic)
    return {"grade_label": grade_label(req.grade), **result}
