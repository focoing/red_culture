# 武汉红色文化导览小助手 - 后端镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# 系统依赖（chromadb/编译所需）；apt 换腾讯云内网源加速
RUN sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 先装 CPU 版 torch（避免拉取 CUDA/nvidia 全家桶，镜像体积省 3GB+），再装其余依赖
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 预下载 BGE 权重到镜像内（离线可跑）
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"

COPY . .

# 入库脚本在容器首次启动时由 entrypoint 触发（可幂等重复执行）
RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["scripts/docker-entrypoint.sh"]
