# -*- coding: utf-8 -*-
"""API 路由层。

端点：
    GET  /api/health              健康检查（含 LLM/知识库状态）
    GET  /api/venues              场馆目录
    GET  /api/venues/{name}/detail 场馆史料详情（预置讲解词，不调 LLM）
    GET  /api/grades              学段定义
    GET  /api/tour/{venue}/route  场馆导览点位时序线
    POST /api/tour/explain        点位导览讲解词（SSE 流式）
    POST /api/chat/stream         分级 RAG 问答（SSE 流式，支持导览场景）
    POST /api/chat                分级 RAG 问答（一次性）
    POST /api/route               研学路线生成
    POST /api/route/transit       跨场馆真实公交/地铁换乘（高德，可选 Key）
    POST /api/tasks               研学任务单生成
    POST /api/explanation         场馆讲解词生成
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import DEFAULT_GRADE, GRADE_LEVELS, LLM_MODEL
from app.core import cache as answer_cache
from app.core import storage
from app.core.auth import require_user
from app.core.llm import check_llm
from app.core.prompts import TOUR_SCENE_TASK, grade_label
from app.core.safety import check_question, sanitize_question
from app.core.vectorstore import collection_stats
from app.services import amap_service, chat_service, study_service, tour_service, venue_service
from openai import RateLimitError

logger = logging.getLogger("red-culture.api")

router = APIRouter(prefix="/api")

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # nginx 禁用响应缓冲，保证流式实时性
    "Connection": "keep-alive",
}

_LLM_BUSY_MSG = "大模型当前访问量过大（高峰期限流），请稍等片刻再重试"


async def _llm_call(fn, *args, **kwargs):
    """执行 LLM 生成调用；LLM 限流（429）时转为友好的 503 提示。"""
    try:
        return await fn(*args, **kwargs)
    except RateLimitError:
        raise HTTPException(status_code=503, detail="大模型当前繁忙（429 限流），请稍后重试")


async def _sse_with_heartbeat(source, interval: float = 15.0):
    """将业务事件流转为 SSE 帧；长时间无事件时发送注释心跳，防止代理断连。

    业务事件生成在独立任务中泵入队列，主循环带超时读取——超时不取消
    源生成器，避免打断进行中的 LLM 流式调用。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump():
        try:
            async for event in source:
                await queue.put(event)
        except RateLimitError:
            await queue.put({"type": "error", "data": {"message": _LLM_BUSY_MSG}})
        except Exception as e:  # noqa: BLE001
            logger.exception("SSE 流处理异常")
            await queue.put({"type": "error", "data": {"message": str(e)}})
        finally:
            await queue.put(None)

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if event is None:
                break
            payload = json.dumps(event.get("data", ""), ensure_ascii=False)
            yield f"event: {event['type']}\ndata: {payload}\n\n"
    finally:
        task.cancel()


def _resolve_session(session_id: str | None, user: dict) -> str:
    """复用或创建会话；已有会话必须属于当前用户（防止跨用户读取他人历史）。"""
    if session_id:
        owner = storage.session_owner(session_id)
        if owner and owner != str(user["id"]):
            raise HTTPException(403, "无权访问该会话")
        return session_id
    return chat_service.new_session(user["id"])


def _check_question(text: str) -> str:
    """输入安全边界：清洗 + 规则审查，违规返回 400。"""
    cleaned = sanitize_question(text)
    ok, reason = check_question(cleaned)
    if not ok:
        raise HTTPException(400, reason)
    return cleaned


# ---------------- Schemas ----------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="学生提问")
    grade: str = Field(DEFAULT_GRADE, description="学段 primary_low/primary_high/junior/senior")
    session_id: str | None = Field(None, description="会话ID，为空则新建")
    venue: str | None = Field(None, description="限定场馆（可选，导览随行问答时传入）")
    section: str | None = Field(None, description="当前导览点位/展区（可选，与 venue 一起构成随行场景）")


class TourExplainRequest(BaseModel):
    grade: str = Field(DEFAULT_GRADE)
    venue: str = Field(..., description="场馆名称")
    section: str = Field(..., description="点位（史料小节）名称")


class TransitRequest(BaseModel):
    venues: list[str] = Field(..., min_length=2, max_length=6, description="按游览顺序排列的场馆名称")


class RouteRequest(BaseModel):
    grade: str = Field(DEFAULT_GRADE)
    theme: str = Field("", description="主题：辛亥革命/党史/工运/抗战/综合")
    days: str = Field("一日", description="半日/一日")
    venues: list[str] = Field(default_factory=list, description="已选场馆（可选，围绕这些场馆规划顺序）")


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


@router.get("/venues/{name}/detail")
def venue_detail(name: str):
    """场馆史料详情：直接读取史料 Markdown 小节（预置讲解词，零 LLM 消耗）。"""
    detail = venue_service.get_venue_detail(name)
    if not detail:
        raise HTTPException(404, f"未找到场馆：{name}")
    return detail


@router.get("/grades")
def grades():
    return {"grades": GRADE_LEVELS, "default": DEFAULT_GRADE}


# ---------------- 对话 ----------------
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(require_user)):
    _validate_grade(req.grade)
    sid = _resolve_session(req.session_id, user)
    question = _check_question(req.question)

    async def sse():
        yield f"event: meta\ndata: {json.dumps({'session_id': sid, 'grade_label': grade_label(req.grade)}, ensure_ascii=False)}\n\n"
        async for chunk in _sse_with_heartbeat(
            chat_service.chat_stream(sid, question, req.grade, venue=req.venue, section=req.section),
        ):
            yield chunk

    return StreamingResponse(sse(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_user)):
    _validate_grade(req.grade)
    sid = _resolve_session(req.session_id, user)
    question = _check_question(req.question)
    from app.core.rag import agenerate

    extra_task = ""
    if req.venue and req.section:
        extra_task = TOUR_SCENE_TASK.format(venue=req.venue, section=req.section)
    result = await _llm_call(
        agenerate,
        question, grade=req.grade,
        history=chat_service.get_history(sid),
        venue_filter=req.venue,
        cache_section=req.section,
        extra_task=extra_task,
    )
    chat_service.append_history(sid, question, result["answer"])
    # 落请求追踪：与流式路径（chat_service）同维度，按会话可回溯调用链
    storage.append_trace(
        sid, "chat", question, req.grade, req.venue, req.section,
        result.get("doc_count"), result.get("tools_used") or [],
        bool(result.get("cached")), result.get("elapsed_ms"),
    )
    return {"session_id": sid, **result}


# ---------------- 场馆导览 ----------------
@router.get("/tour/{venue}/route")
def tour_route(venue: str):
    """导览点位时序线：史料小节即点位（零 LLM，秒级响应）。"""
    route = venue_service.get_tour_route(venue)
    if not route:
        raise HTTPException(404, f"未找到场馆：{venue}")
    return route


@router.post("/tour/explain")
async def tour_explain(req: TourExplainRequest, user: dict = Depends(require_user)):
    """点位导览讲解词（SSE 流式，命中语义缓存时零延迟回放）。"""
    _validate_grade(req.grade)
    route = venue_service.get_tour_route(req.venue)
    if not route:
        raise HTTPException(404, f"未找到场馆：{req.venue}")
    if not any(p["section"] == req.section for p in route["points"]):
        raise HTTPException(404, f"场馆「{req.venue}」下未找到点位：{req.section}")

    async def sse():
        yield f"event: meta\ndata: {json.dumps({'venue': req.venue, 'section': req.section, 'grade_label': grade_label(req.grade)}, ensure_ascii=False)}\n\n"
        async for chunk in _sse_with_heartbeat(
            tour_service.explain_stream(req.venue, req.section, req.grade),
        ):
            yield chunk

    return StreamingResponse(sse(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------- 研学服务 ----------------
@router.post("/route")
async def route(req: RouteRequest, user: dict = Depends(require_user)):
    _validate_grade(req.grade)
    result = await _llm_call(study_service.generate_route, req.grade, req.theme, req.days,
                             req.venues or None)
    return {"grade_label": grade_label(req.grade), **result}


@router.post("/route/transit")
async def route_transit(req: TransitRequest):
    """跨场馆真实公交/地铁换乘规划（高德 Web 服务，未配置 Key 时优雅降级）。"""
    items = []
    for name in req.venues:
        venue = venue_service.get_venue(name)
        if not venue:
            raise HTTPException(404, f"未找到场馆：{name}")
        items.append({"name": venue["name"], "address": venue["address"]})
    return await amap_service.plan_transit(items)


@router.post("/tasks")
async def tasks(req: TaskRequest, user: dict = Depends(require_user)):
    _validate_grade(req.grade)
    if not venue_service.get_venue(req.venue):
        raise HTTPException(404, f"未找到场馆：{req.venue}")
    result = await _llm_call(study_service.generate_tasks, req.grade, req.venue)
    return {"grade_label": grade_label(req.grade), **result}


@router.post("/explanation")
async def explanation(req: ExplainRequest, user: dict = Depends(require_user)):
    _validate_grade(req.grade)
    if not venue_service.get_venue(req.venue):
        raise HTTPException(404, f"未找到场馆：{req.venue}")
    topic = sanitize_question(req.topic)
    result = await _llm_call(study_service.generate_explanation, req.grade, req.venue, topic)
    return {"grade_label": grade_label(req.grade), **result}
