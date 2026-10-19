# -*- coding: utf-8 -*-
"""语义缓存：相似问题命中后直接回放历史答案，免调 GLM（省配额、零延迟）。

设计要点：
- SQLite 存储（问题向量 JSON + 答案 + 来源），按 学段 + 场馆过滤 维度隔离；
- 命中条件：余弦相似度 >= CACHE_SIM_THRESHOLD 且未超过 CACHE_TTL_HOURS；
- BGE 输出已归一化，点积即余弦相似度；
- 异常回退：任何缓存故障均静默降级为"未命中"，不影响正常 RAG 管线。
"""
import json
import sqlite3
import threading
import time

from app.config import CACHE_DB, CACHE_SIM_THRESHOLD, CACHE_TTL_HOURS

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_stats = {"hits": 0, "misses": 0}


def _get_conn() -> sqlite3.Connection | None:
    """懒加载 SQLite 连接；初始化失败返回 None（缓存整体停用）。"""
    global _conn
    if _conn is not None:
        return _conn
    try:
        conn = sqlite3.connect(str(CACHE_DB), check_same_thread=False)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS answer_cache (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                grade        TEXT NOT NULL,
                venue_filter TEXT,
                question     TEXT NOT NULL,
                question_emb TEXT NOT NULL,
                answer       TEXT NOT NULL,
                sources      TEXT NOT NULL,
                created_at   REAL NOT NULL
            )"""
        )
        conn.commit()
        _conn = conn
    except Exception:
        _conn = None
    return _conn


def _embed(question: str) -> list[float] | None:
    """问题向量化；Embedding 模型异常时返回 None（视为未命中）。"""
    try:
        from app.core.embeddings import get_embeddings
        return get_embeddings().embed_query(question)
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def lookup(question: str, grade: str | None, venue_filter: str | None = None) -> dict | None:
    """查询语义缓存。

    Returns:
        命中时 {"answer", "sources", "similarity"}；未命中或内部异常时 None。
    """
    conn = _get_conn()
    if conn is None:
        return None
    try:
        emb = _embed(question)
        if emb is None:
            return None
        # SQLite 的 IS 比较支持 NULL 安全等值判断
        rows = conn.execute(
            "SELECT question_emb, answer, sources, created_at FROM answer_cache "
            "WHERE grade = ? AND venue_filter IS ?",
            (grade or "", venue_filter),
        ).fetchall()
        deadline = time.time() - CACHE_TTL_HOURS * 3600
        best, best_sim = None, -1.0
        for qemb, answer, sources, created in rows:
            if created < deadline:
                continue
            sim = _cosine(emb, json.loads(qemb))
            if sim > best_sim:
                best, best_sim = (answer, json.loads(sources)), sim
        with _lock:
            _stats["hits" if (best is not None and best_sim >= CACHE_SIM_THRESHOLD) else "misses"] += 1
        if best is not None and best_sim >= CACHE_SIM_THRESHOLD:
            return {"answer": best[0], "sources": best[1], "similarity": round(best_sim, 4)}
        return None
    except Exception:
        return None


def store(question: str, grade: str | None, venue_filter: str | None,
          answer: str, sources: list) -> None:
    """写入一条缓存（问题 + 向量 + 答案 + 来源）。失败静默跳过。"""
    conn = _get_conn()
    if conn is None or not answer:
        return
    try:
        emb = _embed(question)
        if emb is None:
            return
        with _lock:
            conn.execute(
                "INSERT INTO answer_cache (grade, venue_filter, question, question_emb, "
                "answer, sources, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (grade or "", venue_filter, question, json.dumps(emb),
                 answer, json.dumps(sources), time.time()),
            )
            conn.commit()
    except Exception:
        pass


def clear() -> int:
    """清空缓存（知识库重建后调用，避免旧史料答案残留）。返回删除条数。"""
    conn = _get_conn()
    if conn is None:
        return 0
    try:
        with _lock:
            n = conn.execute("DELETE FROM answer_cache").rowcount
            conn.commit()
        return max(n, 0)
    except Exception:
        return 0


def stats() -> dict:
    """缓存统计（供健康检查展示）。"""
    conn = _get_conn()
    entries = 0
    if conn is not None:
        try:
            entries = conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0]
        except Exception:
            entries = 0
    return {"entries": entries, **_stats}
