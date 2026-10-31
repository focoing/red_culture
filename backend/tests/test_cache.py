# -*- coding: utf-8 -*-
"""语义缓存测试：维度隔离（串台防护）、命中/未命中、TTL 过期。"""
import hashlib
import math

import pytest

from app.core import cache


@pytest.fixture()
def fake_embed(monkeypatch):
    """确定性伪向量：相同问题 → 相同向量，不同问题 → 低相似向量。"""
    def _fake(question: str) -> list[float]:
        # 64 维确定性伪向量（4 段 MD5 拼接）并归一化（真实 BGE 向量即归一化的，
        # cache._cosine 是点积，只有归一化后才等价于余弦）：
        # 相同问题 → sim=1；不同问题 → 近似正交，远低于 0.92 阈值
        b = b"".join(hashlib.md5(f"{i}:{question}".encode("utf-8")).digest() for i in range(4))
        vec = [(x - 128) / 128.0 for x in b]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    monkeypatch.setattr(cache, "_embed", _fake)
    return _fake


# ---------- 缓存维度（rag._cache_dim，串台防护的核心逻辑） ----------

def test_cache_dim_no_section_returns_venue():
    from app.core.rag import _cache_dim
    assert _cache_dim("辛亥革命博物馆", None) == "辛亥革命博物馆"
    assert _cache_dim(None, None) is None


def test_cache_dim_section_widens_isolation():
    """同馆不同点位必须产生不同的缓存维度（串台修复的回归测试）。"""
    from app.core.rag import _cache_dim
    tour = _cache_dim("辛亥革命博物馆", "打捞展区")
    accompany = _cache_dim("辛亥革命博物馆", None, cache_section="金口之战展区")
    assert tour != accompany
    assert tour == "辛亥革命博物馆｜打捞展区"
    assert accompany == "辛亥革命博物馆｜金口之战展区"


def test_cache_dim_section_without_venue():
    from app.core.rag import _cache_dim
    assert _cache_dim(None, None, cache_section="某展区") == "某展区"


# ---------- 缓存读写 ----------

def test_store_and_lookup_hit(fake_embed):
    q = "辛亥革命第一枪在哪里打响？"
    cache.store(q, "junior", None, "答案内容", [{"venue": "武昌起义纪念馆", "section": "导言"}])
    hit = cache.lookup(q, "junior", None)
    assert hit is not None
    assert hit["answer"] == "答案内容"
    assert hit["similarity"] >= 0.92


def test_lookup_miss_on_different_question(fake_embed):
    cache.store("问题甲", "junior", None, "答案", [])
    assert cache.lookup("完全不同的问题乙", "junior", None) is None


def test_cache_isolated_by_grade_and_venue(fake_embed):
    q = "同一个人在不同维度的提问"
    cache.store(q, "junior", None, "全局答案", [])
    assert cache.lookup(q, "senior", None) is None
    assert cache.lookup(q, "junior", "某场馆") is None


def test_cache_section_dimension_prevents_cross_section_hit(fake_embed):
    """回归：随行问答在同馆两个点位提同一个问题，第二个点位不得命中第一个点位的缓存。"""
    venue, section_a, section_b = "辛亥革命博物馆", "打捞展区", "金口之战展区"
    from app.core.rag import _cache_dim
    q = "这条船是怎么被打捞起来的？"
    cache.store(q, "junior", _cache_dim(venue, None, cache_section=section_a), "A 区答案", [])
    assert cache.lookup(q, "junior", _cache_dim(venue, None, cache_section=section_a)) is not None
    assert cache.lookup(q, "junior", _cache_dim(venue, None, cache_section=section_b)) is None


def test_cache_ttl_expiry(fake_embed, monkeypatch):
    q = "TTL 过期测试问题"
    cache.store(q, "junior", None, "旧答案", [])
    # 直改 created_at 模拟过期
    conn = cache._get_conn()
    conn.execute("UPDATE answer_cache SET created_at = 0")
    conn.commit()
    assert cache.lookup(q, "junior", None) is None


def test_store_skips_empty_answer(fake_embed):
    cache.store("空答案问题", "junior", None, "", [])
    assert cache.lookup("空答案问题", "junior", None) is None


def test_stats_shape():
    s = cache.stats()
    assert {"hits", "misses", "entries"} <= set(s)


def test_cache_disabled_when_db_unavailable(monkeypatch, tmp_path):
    """数据库不可用时缓存整体静默停用（lookup 返回 None，store 不抛错）。"""
    real_conn = cache._conn
    monkeypatch.setattr(cache, "_conn", None)
    monkeypatch.setattr(cache, "CACHE_DB", tmp_path / "no_dir" / "x" / "bad.db")
    assert cache.lookup("任意", None, None) is None
    cache.store("任意", None, None, "答案", [])  # 不应抛异常
    monkeypatch.undo()
    cache._conn = real_conn  # 恢复真实连接，避免影响同会话后续测试
