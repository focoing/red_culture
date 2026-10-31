# -*- coding: utf-8 -*-
"""会话存储测试：会话归属、历史读写。"""
import uuid

from app.core import storage


def test_new_session_with_owner():
    uid = str(uuid.uuid4())
    sid = storage.new_session(uid)
    assert len(sid) == 12
    assert storage.session_owner(sid) == uid


def test_session_owner_unknown_returns_none():
    assert storage.session_owner("nonexistent-id") is None


def test_session_owner_without_registration():
    """历史遗留会话（无归属记录）返回 None，交由调用方按策略处理。"""
    assert storage.session_owner("unregistered000") is None


def test_history_roundtrip():
    sid = storage.new_session(str(uuid.uuid4()))
    assert storage.get_history(sid) == []
    storage.append_history(sid, "问题一", "回答一")
    storage.append_history(sid, "问题二", "回答二")
    history = storage.get_history(sid)
    assert [h["content"] for h in history] == ["问题一", "回答一", "问题二", "回答二"]
    assert [h["role"] for h in history] == ["user", "assistant", "user", "assistant"]


def test_history_scoped_by_session():
    s1, s2 = storage.new_session(str(uuid.uuid4())), storage.new_session(str(uuid.uuid4()))
    storage.append_history(s1, "会话一的问题", "会话一的回答")
    assert storage.get_history(s2) == []
