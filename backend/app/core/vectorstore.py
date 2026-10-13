# -*- coding: utf-8 -*-
"""Chroma 向量数据库封装：加载 / 检索 / 统计。"""
from functools import lru_cache
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import CHROMA_COLLECTION, CHROMA_DIR, SCORE_THRESHOLD, TOP_K
from app.core.embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """连接（或创建）持久化 Chroma 集合。"""
    return Chroma(
        collection_name=CHROMA_COLLECTION,
        persist_directory=str(CHROMA_DIR),
        embedding_function=get_embeddings(),
    )


def search(
    query: str,
    top_k: int = TOP_K,
    score_threshold: float = SCORE_THRESHOLD,
    where: dict | None = None,
) -> List[Document]:
    """带相似度过滤的检索。

    Chroma（归一化向量）返回余弦距离 distance，越小越相关；
    距离大于 score_threshold 的块视为弱相关而被丢弃，
    以此约束生成端只依据可靠史料作答，降低史实幻觉。
    若全部被过滤，则回退为原始召回，保证可用性。

    Args:
        query: 用户查询。
        top_k: 召回数量。
        score_threshold: 距离上限（0~2，越小越严格）。
        where: Chroma 元数据过滤，如 {"venue": "八七会议会址纪念馆"}。
    """
    store = get_vectorstore()
    docs_with_dist = store.similarity_search_with_score(
        query, k=top_k, filter=where,
    )
    picked = [doc for doc, dist in docs_with_dist if dist <= score_threshold]
    return picked if picked else [doc for doc, _ in docs_with_dist]


def collection_stats() -> dict:
    """返回知识库统计信息（供健康检查）。"""
    store = get_vectorstore()
    count = store._collection.count()
    venues = set()
    if count:
        for meta in store._collection.get(include=["metadatas"])["metadatas"]:
            if meta and meta.get("venue"):
                venues.add(meta["venue"])
    return {"chunks": count, "venues": len(venues), "venue_names": sorted(venues)}
