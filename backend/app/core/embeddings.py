# -*- coding: utf-8 -*-
"""BAAI-BGE 本地 Embedding 封装（懒加载单例）。

使用 langchain_community 的 HuggingFaceBgeEmbeddings，
底层由 sentence-transformers 加载本地 BGE 权重，查询侧自动附加检索指令。
"""
from functools import lru_cache

from app.config import (
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL,
    EMBED_QUERY_INSTRUCTION,
)


@lru_cache(maxsize=1)
def get_embeddings():
    """返回全局共享的 BGE Embedding 实例（懒加载，进程内复用）。"""
    from langchain_community.embeddings import HuggingFaceBgeEmbeddings

    return HuggingFaceBgeEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": EMBEDDING_DEVICE},
        encode_kwargs={"normalize_embeddings": True},  # 归一化 -> 余弦相似度
        query_instruction=EMBED_QUERY_INSTRUCTION,
    )

