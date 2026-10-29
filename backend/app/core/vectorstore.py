# -*- coding: utf-8 -*-
"""检索封装：向量检索 + BM25 关键词检索（RRF 融合）+ 可选 CrossEncoder 重排。

混合检索动机：纯向量检索对专名（"八七会议"/"陈潭秋"）召回不稳，
BM25 恰好精确定位关键词；两路召回经 Reciprocal Rank Fusion 按名次
融合，再（可选）用 bge-reranker 对候选精排，提升 Top-K 命中率。
知识库仅数百 chunk，BM25 索引全量常驻内存（毫秒级查询，零外部服务）。
"""
import threading
from typing import List, Sequence

import chromadb
from langchain_core.documents import Document

from app.config import (
    BM25_CANDIDATES,
    CHROMA_COLLECTION,
    CHROMA_DIR,
    HYBRID_ENABLED,
    MAX_PER_VENUE,
    RERANK_CANDIDATES,
    RERANKER_ENABLED,
    RERANKER_MODEL,
    RRF_K,
    RRF_WEIGHT_BM25,
    RRF_WEIGHT_VECTOR,
    SCORE_THRESHOLD,
    TOP_K,
)
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


# ---------------- 向量检索 ----------------
def _to_chroma_where(where: dict | None) -> dict | None:
    """多条件 where 翻译为 Chroma $and 操作符语法。

    上层以普通多 key dict 表达 AND 语义（同时供 BM25 分支的元数据过滤使用），
    但 Chroma 要求多条件必须写成 {"$and": [{k: v}, ...]}，单条件保持原样。
    """
    if not where or len(where) <= 1:
        return where
    return {"$and": [{k: v} for k, v in where.items()]}


def _search_vector(query: str, top_k: int, score_threshold: float,
                   where: dict | None) -> list[tuple[str, Document]]:
    """纯向量检索：返回 (chunk_id, Document)，按余弦距离升序。

    BGE 归一化向量 + 余弦空间，Chroma 返回的 distance 越小越相关；
    距离大于 score_threshold 的块视为弱相关而被丢弃，
    以此约束生成端只依据可靠史料作答，降低史实幻觉。
    若全部被过滤，则回退为原始召回，保证可用性。
    """
    col = get_collection()
    if col.count() == 0:
        return []

    emb = get_embeddings().embed_query(query)
    res = col.query(
        query_embeddings=[emb],
        n_results=top_k,
        where=_to_chroma_where(where),
        include=["documents", "metadatas", "distances"],
    )
    ids = res["ids"][0]
    docs = [
        Document(page_content=text, metadata=meta or {})
        for text, meta in zip(res["documents"][0], res["metadatas"][0])
    ]
    dists = res["distances"][0]
    picked = [(cid, d) for cid, d, dist in zip(ids, docs, dists) if dist <= score_threshold]
    return picked if picked else list(zip(ids, docs))


# ---------------- BM25 关键词检索 ----------------
_bm25_lock = threading.Lock()
_bm25_cache: dict = {"count": 0, "ids": [], "docs": [], "bm25": None}
_jieba = None


def _tokenize(text: str) -> list[str]:
    """jieba 中文分词（模型懒加载；标点与空白不计入词项）。"""
    global _jieba
    if _jieba is None:
        import jieba
        _jieba = jieba
    return [t for t in _jieba.lcut(text) if t.strip()]


def _get_bm25() -> dict:
    """懒构建/复用 BM25 内存索引；集合数量变化（重新入库）时自动重建。

    依赖缺失（jieba / rank_bm25 未安装）时打印一次告警并降级为空索引，
    混合检索自动退化为纯向量，不影响主流程。
    """
    with _bm25_lock:
        col = get_collection()
        count = col.count()
        if count == 0 or _bm25_cache["count"] == count:
            return _bm25_cache
        try:
            from rank_bm25 import BM25Okapi

            res = col.get(include=["documents", "metadatas"])
            ids = list(res["ids"])
            docs = [
                Document(page_content=t, metadata=m or {})
                for t, m in zip(res["documents"], res["metadatas"])
            ]
            bm25 = BM25Okapi([_tokenize(d.page_content) for d in docs]) if docs else None
            _bm25_cache.update(count=count, ids=ids, docs=docs, bm25=bm25)
        except ImportError as e:
            print(f"[warn] BM25 依赖缺失（{e}），混合检索降级为纯向量：pip install jieba rank-bm25")
            _bm25_cache.update(count=count)
        return _bm25_cache


def _search_bm25(query: str, top_k: int, where: dict | None) -> list[tuple[str, Document]]:
    """BM25 关键词检索：返回 (chunk_id, Document)，按 BM25 得分降序。"""
    cache = _get_bm25()
    if not cache["bm25"]:
        return []

    pairs = list(zip(cache["ids"], cache["docs"]))
    if where:
        pairs = [
            (cid, d) for cid, d in pairs
            if all(d.metadata.get(k) == v for k, v in where.items())
        ]
    if not pairs:
        return []

    scores = cache["bm25"].get_scores(_tokenize(query))
    idx = {cid: i for i, cid in enumerate(cache["ids"])}
    scored = sorted(
        ((scores[idx[cid]], cid, d) for cid, d in pairs),
        key=lambda x: x[0], reverse=True,
    )
    return [(cid, d) for s, cid, d in scored[:top_k] if s > 0]


# ---------------- RRF 融合与重排 ----------------
def _rrf_fuse(*result_lists: list[tuple[str, Document]], k: int = RRF_K,
              weights: tuple[float, ...] | None = None) -> list[Document]:
    """加权 Reciprocal Rank Fusion：score = Σ w/(k+rank)。

    向量腿为主（语义泛化能力强）、BM25 腿为辅（专名精确匹配），
    避免 BM25 的高频词块（如顺带提及事件名的"研学价值"小节）挤掉向量腿的优质召回。
    """
    if weights is None:
        weights = (1.0,) * len(result_lists)
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}
    for results, w in zip(result_lists, weights):
        for rank, (cid, doc) in enumerate(results, 1):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
            docs[cid] = doc
    return [docs[cid] for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def _diversify(docs: list[Document], top_k: int, max_per_venue: int = MAX_PER_VENUE) -> list[Document]:
    """场馆多样性约束：同一场馆最多保留 max_per_venue 块。

    避免某场馆的近重复块占满 Top-K 上下文（如"武昌起义门"3 块挤占其余场馆），
    挤出的名额由后续其他场馆块回填，提升参考资料的覆盖面。
    """
    if max_per_venue <= 0:
        return docs[:top_k]
    picked, count = [], {}
    for d in docs:
        venue = d.metadata.get("venue", "")
        if count.get(venue, 0) >= max_per_venue:
            continue
        picked.append(d)
        count[venue] = count.get(venue, 0) + 1
        if len(picked) >= top_k:
            break
    return picked


_reranker = None
_reranker_failed = False


def _rerank(query: str, docs: list[Document], top_k: int) -> list[Document]:
    """CrossEncoder 二阶段重排；模型加载/推理失败时自动回退融合名次。"""
    global _reranker, _reranker_failed
    if _reranker_failed or not docs:
        return docs[:top_k]
    try:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
        ranked = sorted(
            zip(_reranker.predict([(query, d.page_content) for d in docs]), docs),
            key=lambda x: x[0], reverse=True,
        )
        return [d for _, d in ranked[:top_k]]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 重排模型不可用，回退 RRF 融合名次（{type(e).__name__}: {e}）")
        _reranker_failed = True
        return docs[:top_k]


# ---------------- 统一入口 ----------------
def search(
    query: str,
    top_k: int = TOP_K,
    score_threshold: float = SCORE_THRESHOLD,
    where: dict | None = None,
) -> List[Document]:
    """混合检索入口：向量 + BM25 双路召回 → RRF 融合 →（可选）重排。

    HYBRID_ENABLED=false 时退化为原纯向量检索（含阈值过滤与回退），
    供 evaluate.py 做基线对比实验。

    Args:
        query: 用户查询。
        top_k: 最终返回文档数。
        score_threshold: 向量腿的余弦距离上限（0~2，越小越严格）。
        where: Chroma 元数据过滤，如 {"venue": "八七会议会址纪念馆"}。
    """
    if not HYBRID_ENABLED:
        return [d for _, d in _search_vector(query, top_k, score_threshold, where)]

    n_candidates = max(top_k, BM25_CANDIDATES)
    vec = _search_vector(query, n_candidates, score_threshold, where)
    bm25 = _search_bm25(query, n_candidates, where)
    fused = _rrf_fuse(vec, bm25, weights=(RRF_WEIGHT_VECTOR, RRF_WEIGHT_BM25))
    if not fused:  # 双路皆空（如空库）
        return []
    if where:
        # 已限定单场馆：不做多样性约束，保留该馆全部命中块
        fused = fused[:max(top_k, RERANK_CANDIDATES) if RERANKER_ENABLED else top_k]
    elif RERANKER_ENABLED:
        fused = _diversify(fused, RERANK_CANDIDATES)
    else:
        fused = _diversify(fused, top_k)
    if RERANKER_ENABLED:
        return _rerank(query, fused, top_k)
    return fused


def collection_stats() -> dict:
    """返回知识库统计信息（供健康检查）。"""
    col = get_collection()
    count = col.count()
    venues = set()
    if count:
        for meta in col.get(include=["metadatas"])["metadatas"]:
            if meta and meta.get("venue"):
                venues.add(meta.get("venue"))
    return {"chunks": count, "venues": len(venues), "venue_names": sorted(venues)}
