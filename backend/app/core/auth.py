# -*- coding: utf-8 -*-
"""账户体系：注册 / 登录 / 签名令牌校验（SQLite 存储，零第三方依赖）。

设计要点：
- 密码使用 PBKDF2-HMAC-SHA256（60 万次迭代）加盐哈希，不存明文；
- 令牌为 HMAC-SHA256 签名的 URL-safe JSON（含 sub/role/grade/exp），
  等价于 JWT HS256，但避免新增依赖；过期默认 7 天；
- 用户库与会话库分离（users.db），任何数据库异常均返回明确错误，
  不静默降级——账户操作失败必须让用户知道，而不是悄悄放行。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from fastapi import HTTPException, Request

from app.config import AUTH_SECRET, TOKEN_TTL_HOURS, USERS_DB

_PBKDF2_ITERATIONS = 600_000
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """懒加载用户库连接（线程安全）；初始化失败直接抛错（账户功能不可降级）。"""
    global _conn
    if _conn is not None:
        return _conn
    conn = sqlite3.connect(str(USERS_DB), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL UNIQUE,
            pw_hash    TEXT NOT NULL,
            salt       TEXT NOT NULL,
            role       TEXT NOT NULL DEFAULT 'student',
            grade      TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )"""
    )
    conn.commit()
    _conn = conn
    return _conn


# ---------- 密码哈希 ----------

def hash_password(password: str) -> tuple[str, str]:
    """返回 (pw_hash, salt)。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS,
    )
    return hmac.compare_digest(digest.hex(), pw_hash)


# ---------- 用户 CRUD ----------

def create_user(username: str, password: str, grade: str = "") -> dict:
    """注册新用户；用户名重复抛 ValueError。"""
    pw_hash, salt = hash_password(password)
    try:
        with _lock:
            cur = _get_conn().execute(
                "INSERT INTO users (username, pw_hash, salt, role, grade, created_at) "
                "VALUES (?, ?, ?, 'student', ?, ?)",
                (username, pw_hash, salt, grade, time.time()),
            )
            _get_conn().commit()
            return {"id": cur.lastrowid, "username": username, "role": "student", "grade": grade}
    except sqlite3.IntegrityError as e:
        raise ValueError("用户名已被注册") from e


def get_user_by_username(username: str) -> dict | None:
    row = _get_conn().execute(
        "SELECT id, username, pw_hash, salt, role, grade FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "pw_hash": row[2], "salt": row[3],
            "role": row[4], "grade": row[5]}


# ---------- 签名令牌（HMAC-SHA256，等价 JWT HS256） ----------

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: dict, ttl_hours: int | None = None) -> str:
    """为用户签发令牌：payload.sig，payload 为 URL-safe JSON。"""
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user.get("role", "student"),
        "grade": user.get("grade", ""),
        "iat": int(time.time()),
        "exp": int(time.time()) + (ttl_hours or TOKEN_TTL_HOURS) * 3600,
    }
    body = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(AUTH_SECRET.encode(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict | None:
    """校验令牌签名与有效期；合法返回 payload，否则 None。"""
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(AUTH_SECRET.encode(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expect, _b64d(sig)):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ---------- FastAPI 依赖 ----------

def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def resolve_user(request: Request) -> dict | None:
    """从请求中解析用户（供限流等中间件使用）；无效/缺失返回 None。"""
    token = _bearer_token(request)
    if not token:
        return None
    payload = verify_token(token)
    if not payload:
        return None
    return {"id": payload.get("sub"), "username": payload.get("username", ""),
            "role": payload.get("role", "student"), "grade": payload.get("grade", "")}


def require_user(request: Request) -> dict:
    """保护端点依赖：未登录或令牌无效时返回 401。"""
    user = resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期，请先登录")
    return user
