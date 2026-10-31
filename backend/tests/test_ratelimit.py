# -*- coding: utf-8 -*-
"""限流测试：IP 解析、内存窗口、SQLite 共享窗口。"""
import tempfile
from pathlib import Path


class _Req:
    def __init__(self, headers, host):
        self.headers = headers
        self.client = type("C", (), {"host": host})() if host else None


# ---------- _client_ip ----------

def test_client_ip_prefers_xff_first_hop():
    r = _Req({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "172.18.0.5")
    from app.core.ratelimit import _client_ip
    assert _client_ip(r) == "203.0.113.7"


def test_client_ip_fallbacks():
    from app.core.ratelimit import _client_ip
    assert _client_ip(_Req({"x-real-ip": "198.51.100.9"}, "172.18.0.5")) == "198.51.100.9"
    assert _client_ip(_Req({}, "127.0.0.1")) == "127.0.0.1"
    assert _client_ip(_Req({"x-forwarded-for": "  , ,"}, "127.0.0.1")) == "127.0.0.1"
    assert _client_ip(_Req({}, None)) == "unknown"


# ---------- MemoryWindowStore ----------

def test_memory_store_allow_then_deny_then_recover():
    from app.core.ratelimit import MemoryWindowStore
    store = MemoryWindowStore()
    for i in range(3):
        allowed, _ = store.hit("k1", 1000.0 + i, limit=3, window=60.0)
        assert allowed
    allowed, retry = store.hit("k1", 1003.0, limit=3, window=60.0)
    assert not allowed and retry >= 1
    # 窗口滑过：全部记录过期
    allowed, _ = store.hit("k1", 1061.0, limit=3, window=60.0)
    assert allowed


def test_memory_store_keys_isolated():
    from app.core.ratelimit import MemoryWindowStore
    store = MemoryWindowStore()
    store.hit("a", 0.0, limit=1, window=60.0)
    allowed, _ = store.hit("b", 1.0, limit=1, window=60.0)
    assert allowed


# ---------- SQLiteWindowStore ----------

def test_sqlite_store_shared_across_instances():
    """两个独立实例（模拟两个 uvicorn worker）共享同一配额。"""
    from app.core.ratelimit import SQLiteWindowStore
    db = Path(tempfile.mkdtemp(prefix="rc_rl_")) / "rl.db"
    s1, s2 = SQLiteWindowStore(db), SQLiteWindowStore(db)
    for i in range(3):
        allowed, _ = s1.hit("u:1", 1000.0 + i, limit=3, window=60.0)
        assert allowed
    allowed, retry = s2.hit("u:1", 1004.0, limit=3, window=60.0)
    assert not allowed and retry >= 1
    # 其他 key 不受影响
    allowed, _ = s2.hit("u:2", 1004.0, limit=3, window=60.0)
    assert allowed


def test_sqlite_store_window_expiry():
    from app.core.ratelimit import SQLiteWindowStore
    db = Path(tempfile.mkdtemp(prefix="rc_rl_")) / "rl.db"
    store = SQLiteWindowStore(db)
    store.hit("u:1", 1000.0, limit=1, window=60.0)
    allowed, _ = store.hit("u:1", 1001.0, limit=1, window=60.0)
    assert not allowed
    allowed, _ = store.hit("u:1", 1061.0, limit=1, window=60.0)
    assert allowed


# ---------- 限流维度 ----------

def test_protected_paths_cover_all_llm_endpoints():
    from app.core.ratelimit import PROTECTED_PATHS
    for p in ("/api/chat", "/api/chat/stream", "/api/route", "/api/tasks",
              "/api/explanation", "/api/tour/explain"):
        assert p in PROTECTED_PATHS, f"缺少 LLM 端点限流保护：{p}"


def test_public_paths_not_rate_limited():
    from app.core.ratelimit import PROTECTED_PATHS
    for p in ("/api/venues", "/api/grades", "/api/tour/red/tour-route", "/api/auth/login"):
        assert p not in PROTECTED_PATHS
