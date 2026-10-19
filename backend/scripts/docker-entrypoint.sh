#!/bin/sh
# 容器启动：确保知识库已入库 -> 启动 API
set -e

if [ -z "${ZHIPU_API_KEY:-}" ]; then
  echo "[entrypoint] 警告：未配置 ZHIPU_API_KEY，继续启动但问答将不可用"
fi

if [ ! -d "/app/chroma_db" ] || [ -z "$(ls -A /app/chroma_db 2>/dev/null)" ]; then
  echo "[entrypoint] 首次启动：正在构建知识库（BGE 向量化入库）..."
  python ingest.py
fi

echo "[entrypoint] 启动 FastAPI ..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}"
