# -*- coding: utf-8 -*-
"""按 IP 的滑动窗口限流中间件，保护 GLM API 配额与后端稳定性。

仅对消耗 LLM 配额的接口生效；超限返回 429 + Retry-After。
"""
import threading
import time
from collections import defaultdict, deque

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import RATE_LIMIT_PER_MIN

PROTECTED_PATHS = {
    "/api/chat", "/api/chat/stream", "/api/route", "/api/tasks", "/api/explanation",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """每 IP 每分钟最多 per_minute 次受保护接口调用。"""

    def __init__(self, app, per_minute: int = RATE_LIMIT_PER_MIN):
        super().__init__(app)
        self.per_minute = max(1, per_minute)
        self._window = 60.0
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if request.url.path in PROTECTED_PATHS:
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with self._lock:
                q = self._hits[ip]
                while q and q[0] <= now - self._window:  # 滑出窗口的旧记录
                    q.popleft()
                if len(q) >= self.per_minute:
                    retry_after = max(1, int(self._window - (now - q[0])) + 1)
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"提问太频繁啦，请 {retry_after} 秒后再试～"},
                        headers={"Retry-After": str(retry_after)},
                    )
                q.append(now)
                if len(self._hits) > 4096:  # 轻量清理过期 IP，防内存无限增长
                    stale = [k for k, v in self._hits.items()
                             if not v or v[0] <= now - self._window]
                    for k in stale:
                        del self._hits[k]
        return await call_next(request)
