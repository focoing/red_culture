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

# ---------- LLM（Ollama + Qwen2.5） ----------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "8192"))

# ---------- RAG 检索 ----------
TOP_K = int(os.getenv("TOP_K", "5"))              # 召回文档数
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.55"))  # 余弦距离上限，越小越严格
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))

# ---------- 应用 ----------
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
MAX_HISTORY_ROUNDS = int(os.getenv("MAX_HISTORY_ROUNDS", "6"))  # 对话历史轮数

# ---------- 学段定义 ----------
GRADE_LEVELS = {
    "primary_low":  {"label": "小学低年级(1-3年级)", "ages": "6-9岁"},
    "primary_high": {"label": "小学高年级(4-6年级)", "ages": "9-12岁"},
    "junior":       {"label": "初中(7-9年级)", "ages": "12-15岁"},
    "senior":       {"label": "高中", "ages": "15-18岁"},
}
DEFAULT_GRADE = "primary_high"
