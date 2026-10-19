# -*- coding: utf-8 -*-
"""会话持久化：对话历史写入 SQLite，后端重启后仍可恢复会话。

接口与原内存版保持一致：new_session / get_history / append_history。
异常回退：SQLite 不可用时自动降级为内存会话，不阻断主流程。
"""
import sqlite3
import threading
import time
import uuid

from app.config import MAX_HISTORY_ROUNDS, SESSION_DB

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_memory: dict[str, list[dict]] = {}  # 降级用的内存会话池

_SESSION_TTL_DAYS = 30  # 会话保留天数，启动时清理过期数据


def _get_conn() -> sqlite3.Connection | None:
    """懒加载 SQLite 连接（线程安全）；初始化失败返回 None 走内存降级。"""
    global _conn
    if _conn is not None:
        return _conn
    try:
        conn = sqlite3.connect(str(SESSION_DB), check_same_thread=False)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
        # 顺带清理过期会话，避免库文件无限增长
        conn.execute(
            "DELETE FROM messages WHERE created_at < ?",
            (time.time() - _SESSION_TTL_DAYS * 86400,),
        )
        conn.commit()
        _conn = conn
    except Exception:
        _conn = None
    return _conn


def new_session() -> str:
    """创建新会话，返回会话ID（行记录在首次追加历史时才产生）。"""
    return uuid.uuid4().hex[:12]


def get_history(session_id: str) -> list[dict]:
    """读取指定会话的对话历史（尾部最多 MAX_HISTORY_ROUNDS*2 条消息）。"""
    conn = _get_conn()
    if conn is None:
        return list(_memory.get(session_id, []))[-MAX_HISTORY_ROUNDS * 2:]
    try:
        with _lock:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{"role": r, "content": c} for r, c in rows][-MAX_HISTORY_ROUNDS * 2:]
    except Exception:
        return []


def append_history(session_id: str, question: str, answer: str) -> None:
    """追加一轮对话（用户提问 + 助手回答）。写入失败静默降级，不阻断对话。"""
    conn = _get_conn()
    if conn is None:
        _memory.setdefault(session_id, []).extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])
        return
    try:
        now = time.time()
        with _lock:
            conn.executemany(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [(session_id, "user", question, now),
                 (session_id, "assistant", answer, now)],
            )
            conn.commit()
    except Exception:
        pass
