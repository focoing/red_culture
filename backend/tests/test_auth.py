# -*- coding: utf-8 -*-
"""账户体系测试：注册/登录/令牌校验/受保护端点。"""
import uuid

from fastapi.testclient import TestClient

from app.core import auth
from app.main import app

client = TestClient(app)


def _rand_name() -> str:
    return f"学生{uuid.uuid4().hex[:8]}"


def test_register_login_me_roundtrip():
    name = _rand_name()
    r = client.post("/api/auth/register", json={
        "username": name, "password": "pass123456", "grade": "junior",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == name
    assert body["user"]["role"] == "student"
    assert body["token"]

    r = client.post("/api/auth/login", json={"username": name, "password": "pass123456"})
    assert r.status_code == 200
    token = r.json()["token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == name


def test_register_duplicate_username():
    name = _rand_name()
    payload = {"username": name, "password": "pass123456"}
    assert client.post("/api/auth/register", json=payload).status_code == 200
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 400
    assert "已被注册" in r.json()["detail"]


def test_register_invalid_username_and_grade():
    # 过短用户名：Pydantic 边界校验（422）或自定义正则（400）均视为拒绝
    assert client.post("/api/auth/register", json={
        "username": "a", "password": "pass123456",
    }).status_code in (400, 422)
    assert client.post("/api/auth/register", json={
        "username": _rand_name(), "password": "pass123456", "grade": "college",
    }).status_code == 400


def test_login_wrong_password():
    name = _rand_name()
    client.post("/api/auth/register", json={"username": name, "password": "pass123456"})
    r = client.post("/api/auth/login", json={"username": name, "password": "wrong-pass"})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


def test_protected_endpoint_requires_auth():
    r = client.post("/api/chat", json={"question": "辛亥革命在哪里打响？"})
    assert r.status_code == 401
    assert "未登录" in r.json()["detail"]
    r = client.post("/api/chat/stream", json={"question": "问题"})
    assert r.status_code == 401


def test_public_endpoints_stay_open():
    assert client.get("/api/grades").status_code == 200
    assert client.get("/api/venues").status_code == 200


def test_verify_token_rejects_tamper_and_expiry():
    name = _rand_name()
    body = client.post("/api/auth/register", json={
        "username": name, "password": "pass123456",
    }).json()
    token = body["token"]
    assert auth.verify_token(token) is not None
    tampered = token[:-4] + "AAAA"
    assert auth.verify_token(tampered) is None
    assert auth.verify_token("garbage") is None
    expired = auth.issue_token({"id": 1, "username": name}, ttl_hours=-1)
    assert auth.verify_token(expired) is None


def test_password_hashed_not_plaintext():
    name = _rand_name()
    client.post("/api/auth/register", json={"username": name, "password": "pass123456"})
    user = auth.get_user_by_username(name)
    assert user["pw_hash"] != "pass123456"
    assert auth.verify_password("pass123456", user["pw_hash"], user["salt"])
    assert not auth.verify_password("wrong", user["pw_hash"], user["salt"])
