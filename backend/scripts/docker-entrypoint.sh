#!/bin/sh
# 容器启动：等待 Ollama 可用 -> 确保知识库已入库 -> 启动 API
set -e

echo "[entrypoint] 等待 Ollama 服务（${OLLAMA_BASE_URL:-http://ollama:11434}）..."
i=0
until curl -s "${OLLAMA_BASE_URL:-http://ollama:11434}/api/tags" >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -ge 120 ]; then
    echo "[entrypoint] 警告：等待 Ollama 超时（120s），继续启动但问答将不可用"
    break
  fi
  sleep 2
done

if [ ! -d "/app/chroma_db" ] || [ -z "$(ls -A /app/chroma_db 2>/dev/null)" ]; then
  echo "[entrypoint] 首次启动：正在构建知识库（BGE 向量化入库）..."
  python ingest.py
fi

echo "[entrypoint] 启动 FastAPI ..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}"
