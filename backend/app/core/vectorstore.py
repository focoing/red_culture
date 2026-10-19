# -*- coding: utf-8 -*-
"""Chroma 向量数据库封装：写入 / 检索 / 统计（直接使用 chromadb 客户端）。"""
from typing import List, Sequence

import chromadb
from langchain_core.documents import Document

from app.config import CHROMA_COLLECTION, CHROMA_DIR, SCORE_THRESHOLD, TOP_K
from app.core.embeddings import get_embeddings


def get_collection():
    """连接（或创建）持久化 Chroma 集合，余弦距离度量。"""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(docs: Sequence[Document]) -> int:
    """批量向量化并写入集合。

    upsert 覆盖同 id 旧块，重复执行入库脚本不会产生重复数据。
    """
    if not docs:
        return 0
    col = get_collection()
    ids = [f"chunk-{i}" for i in range(len(docs))]
    embeddings = get_embeddings().embed_documents([d.page_content for d in docs])
    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[d.page_content for d in docs],
        metadatas=[d.metadata for d in docs],
    )
    return len(docs)


def search(
    query: str,
    top_k: int = TOP_K,
    score_threshold: float = SCORE_THRESHOLD,
    where: dict | None = None,
) -> List[Document]:
    """带相似度过滤的检索。

    BGE 归一化向量 + 余弦空间，Chroma 返回的 distance 越小越相关；
    距离大于 score_threshold 的块视为弱相关而被丢弃，
    以此约束生成端只依据可靠史料作答，降低史实幻觉。
    若全部被过滤，则回退为原始召回，保证可用性。

    Args:
        query: 用户查询。
        top_k: 召回数量。
        score_threshold: 余弦距离上限（0~2，越小越严格）。
        where: Chroma 元数据过滤，如 {"venue": "八七会议会址纪念馆"}。
    """
    col = get_collection()
    if col.count() == 0:
        return []

    emb = get_embeddings().embed_query(query)
    res = col.query(
        query_embeddings=[emb],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    docs = [
        Document(page_content=text, metadata=meta or {})
        for text, meta in zip(res["documents"][0], res["metadatas"][0])
    ]
    dists = res["distances"][0]
    picked = [d for d, dist in zip(docs, dists) if dist <= score_threshold]
    return picked if picked else docs


def collection_stats() -> dict:
    """返回知识库统计信息（供健康检查）。"""
    col = get_collection()
    count = col.count()
    venues = set()
    if count:
        for meta in col.get(include=["metadatas"])["metadatas"]:
            if meta and meta.get("venue"):
                venues.add(meta["venue"])
    return {"chunks": count, "venues": len(venues), "venue_names": sorted(venues)}
