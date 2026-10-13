# 武汉红色文化导览小助手 - 后端镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# 系统依赖（chromadb/编译所需）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 BGE 权重到镜像内（离线可跑）
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"

COPY . .

# 入库脚本在容器首次启动时由 entrypoint 触发（可幂等重复执行）
RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["scripts/docker-entrypoint.sh"]
