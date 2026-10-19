# -*- coding: utf-8 -*-
"""全局配置：通过环境变量 / .env 覆盖默认值。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")

# ---------- 路径 ----------
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
VENUES_DIR = DATA_DIR / "venues"
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", BASE_DIR / "chroma_db"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "wuhan_red_culture")

# ---------- Embedding（BAAI-BGE 本地模型） ----------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
# 国内镜像加速：HF_ENDPOINT=https://hf-mirror.com
os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT", "https://hf-mirror.com"))
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")  # cpu / cuda
EMBED_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# ---------- LLM（智谱 GLM，OpenAI 兼容接口） ----------
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")  # 在 https://open.bigmodel.cn 申请
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4.7-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))        # 单次请求超时（秒），推理模型耗时较长
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))  # 429 限流时的指数退避重试次数
LLM_THINKING = os.getenv("LLM_THINKING", "").lower()      # ""=模型默认 / true / false（GLM 深度思考开关）

# ---------- RAG 检索 ----------
TOP_K = int(os.getenv("TOP_K", "5"))              # 召回文档数
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.55"))  # 余弦距离上限，越小越严格
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "450"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "60"))

# ---------- 应用 ----------
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
MAX_HISTORY_ROUNDS = int(os.getenv("MAX_HISTORY_ROUNDS", "6"))  # 对话历史轮数

# ---------- 工程底座：会话持久化 / 语义缓存 / 限流 ----------
SESSION_DB = Path(os.getenv("SESSION_DB", DATA_DIR / "sessions.db"))   # 会话库（SQLite）
CACHE_DB = Path(os.getenv("CACHE_DB", DATA_DIR / "answer_cache.db"))   # 语义缓存库（SQLite）
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))              # 缓存有效期（小时）
CACHE_SIM_THRESHOLD = float(os.getenv("CACHE_SIM_THRESHOLD", "0.92"))  # 命中所需余弦相似度
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))        # 每 IP 每分钟请求上限

# ---------- 智能工具调用（P4：GLM Function Calling） ----------
TOOL_CALLING_ENABLED = os.getenv("TOOL_CALLING_ENABLED", "true").lower() in ("1", "true", "yes")

# ---------- 学段定义 ----------
GRADE_LEVELS = {
    "primary_low":  {"label": "小学低年级(1-3年级)", "ages": "6-9岁"},
    "primary_high": {"label": "小学高年级(4-6年级)", "ages": "9-12岁"},
    "junior":       {"label": "初中(7-9年级)", "ages": "12-15岁"},
    "senior":       {"label": "高中", "ages": "15-18岁"},
}
DEFAULT_GRADE = "primary_high"
