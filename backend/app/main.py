# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import APP_HOST, APP_PORT, CHROMA_DIR, CORS_ORIGINS, VENUES_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("red-culture")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期检查：知识库是否存在；不存在时提示先运行 ingest。"""
    if not CHROMA_DIR.exists():
        logger.warning(
            "Chroma 向量库不存在（%s）。请先运行: python ingest.py", CHROMA_DIR,
        )
    else:
        logger.info("已加载本地向量库：%s", CHROMA_DIR)
    logger.info("史料目录：%s（%d 个文件）", VENUES_DIR, len(list(VENUES_DIR.glob('*.md'))))
    yield


app = FastAPI(
    title="武汉红色文化导览小助手",
    description="面向中小学生红色研学的垂直 RAG 智能导览系统：BGE 检索 + Chroma + Ollama/Qwen2.5",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


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
