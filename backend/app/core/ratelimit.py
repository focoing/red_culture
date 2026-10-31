# -*- coding: utf-8 -*-
"""滑动窗口限流，保护 GLM API 配额与后端稳定性。

设计要点：
- 计数存储默认写入 SQLite（多 worker / 多进程共享同一配额），故障时自动降级为
  进程内内存窗口（单 worker 语义），保证限流本身永远可用；
- 限流维度：已登录按用户 ID，未登录按客户端真实 IP（X-Forwarded-For 首段）；
- 仅对消耗 LLM 配额的接口生效；超限返回 429 + Retry-After。
"""
import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import RATE_LIMIT_PER_MIN

logger = logging.getLogger("red-culture.ratelimit")

PROTECTED_PATHS = {
    "/api/chat", "/api/chat/stream", "/api/route", "/api/tasks", "/api/explanation",
    "/api/tour/explain",
}


def _client_ip(request) -> str:
    """解析客户端真实 IP：优先反代注入的 X-Forwarded-For 首段，回退直连地址。

    Docker 部署时 nginx 反代 /api，request.client.host 是 nginx 容器 IP，
    所有用户会共享一个地址导致限流退化为全局配额；故以 XFF 首段为准。
    后端仅在 docker 内网/本地可达，不暴露公网直连，XFF 伪造风险可控。
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


class MemoryWindowStore:
    """进程内滑动窗口：SQLite 故障时的降级路径（与修复前行为一致）。"""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float, limit: int, window: float) -> tuple[bool, int]:
        """记账并判定。返回 (是否放行, 重试等待秒数)；放行时秒数为 0。"""
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:  # 滑出窗口的旧记录
                q.popleft()
            if len(q) >= limit:
                retry_after = max(1, int(window - (now - q[0])) + 1)
                return False, retry_after
            q.append(now)
            if len(self._hits) > 4096:  # 轻量清理过期 IP，防内存无限增长
                stale = [k for k, v in self._hits.items()
                         if not v or v[0] <= now - window]
                for k in stale:
                    del self._hits[k]
            return True, 0


class SQLiteWindowStore:
    """SQLite 共享滑动窗口：计数落库，多 uvicorn worker 共享同一配额。

    每次请求在一个短事务内完成"清理过期 + 计数 + 记账"；学校场景的请求量级
    （<100 QPS）对 WAL 模式的 SQLite 毫无压力。
    """

    def __init__(self, db_path: Path):
        self._path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._failed = False

    def _get_conn(self) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("CREATE TABLE IF NOT EXISTS rl_hits ("
                         "key TEXT NOT NULL, ts REAL NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rl_key_ts ON rl_hits(key, ts)")
            conn.commit()
            self._conn = conn
        except Exception:
            self._conn = None
        return self._conn

    def hit(self, key: str, now: float, limit: int, window: float) -> tuple[bool, int]:
        if self._failed:
            raise RuntimeError("sqlite store disabled")
        conn = self._get_conn()
        if conn is None:
            raise RuntimeError("sqlite unavailable")
        with self._lock:
            try:
                conn.execute("DELETE FROM rl_hits WHERE ts < ?", (now - window,))
                row = conn.execute(
                    "SELECT COUNT(*), MIN(ts) FROM rl_hits WHERE key = ? AND ts >= ?",
                    (key, now - window),
                ).fetchone()
                count, oldest = row[0], row[1]
                if count >= limit:
                    retry_after = max(1, int(window - (now - oldest)) + 1)
                    conn.commit()
                    return False, retry_after
                conn.execute("INSERT INTO rl_hits (key, ts) VALUES (?, ?)", (key, now))
                conn.commit()
                return True, 0
            except Exception:
                conn.rollback()
                raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    """每用户/每 IP 每分钟最多 per_minute 次受保护接口调用。"""

    def __init__(self, app, per_minute: int = RATE_LIMIT_PER_MIN,
                 db_path: Path | None = None):
        super().__init__(app)
        self.per_minute = max(1, per_minute)
        self._window = 60.0
        self._memory = MemoryWindowStore()
        self._sqlite: SQLiteWindowStore | None = (
            SQLiteWindowStore(db_path) if db_path is not None else None
        )

    def _hit(self, key: str, now: float) -> tuple[bool, int]:
        """优先走 SQLite 共享窗口；任何故障降级为进程内内存窗口。"""
        if self._sqlite is not None:
            try:
                return self._sqlite.hit(key, now, self.per_minute, self._window)
            except Exception as e:  # noqa: BLE001
                logger.warning("限流 SQLite 存储不可用，降级为进程内窗口：%s", e)
        return self._memory.hit(key, now, self.per_minute, self._window)

    async def dispatch(self, request, call_next):
        if request.url.path in PROTECTED_PATHS:
            # 已登录按用户维度限流；未登录按客户端 IP（解析失败不影响放行）
            from app.core import auth

            user = auth.resolve_user(request)
            if user and user.get("id"):
                key = f"u:{user['id']}"
            else:
                key = f"ip:{_client_ip(request)}"
            now = time.time()  # 墙钟：SQLite 窗口跨 worker 共享，不能用进程内 monotonic
            allowed, retry_after = self._hit(key, now)
            if not allowed:
                logger.info("限流触发：key=%s", key)
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"提问太频繁啦，请 {retry_after} 秒后再试～"},
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)
