# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth_routes
from app.api.routes import router
from app.config import (
    APP_HOST, APP_PORT, AUTH_SECRET_EPHEMERAL, CHROMA_DIR, CORS_ORIGINS,
    DATA_DIR, RATELIMIT_DB, VENUES_DIR,
)
from app.core.ratelimit import RateLimitMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s %(message)s")
logger = logging.getLogger("red-culture")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期检查：知识库、数据目录、密钥配置。"""
    if not CHROMA_DIR.exists():
        logger.warning(
            "Chroma 向量库不存在（%s）。请先运行: python ingest.py", CHROMA_DIR,
        )
    else:
        logger.info("已加载本地向量库：%s", CHROMA_DIR)
    logger.info("史料目录：%s（%d 个文件）", VENUES_DIR, len(list(VENUES_DIR.glob('*.md'))))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if AUTH_SECRET_EPHEMERAL:
        logger.warning(
            "AUTH_SECRET 未配置：本次运行使用临时随机密钥，重启后所有登录令牌失效。"
            "生产部署请在 .env 中显式设置 AUTH_SECRET",
        )
    yield


app = FastAPI(
    title="武汉红色文化导览小助手",
    description="面向中小学生红色研学的垂直 RAG 智能导览系统：BGE 检索 + Chroma + 智谱 GLM",
    version="1.1.0",
    lifespan=lifespan,
)

# 注册顺序：限流先注册（内层）、CORS 后注册（外层），保证 429 响应同样携带 CORS 头。
# 限流计数写入 SQLite（RATELIMIT_DB），多 worker / 多进程共享同一配额。
app.add_middleware(RateLimitMiddleware, db_path=RATELIMIT_DB)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_routes.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：记录完整堆栈，返回统一友好文案（不向客户端泄露内部细节）。"""
    logger.exception("未处理异常 %s %s：%s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "服务器开小差了，请稍后再试～"})


@app.get("/")
def root():
    return {
        "app": "武汉红色文化导览小助手",
        "docs": "/docs",
        "api": "/api",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False)
