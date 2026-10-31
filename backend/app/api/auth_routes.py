# -*- coding: utf-8 -*-
"""账户接口：注册 / 登录 / 当前用户。

注册即学生身份（role=student）；登录签发 7 天签名令牌，前端以
Authorization: Bearer 携带。所有输入在边界处校验，数据库异常如实报错。
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import DEFAULT_GRADE, GRADE_LEVELS
from app.core import auth
from app.core.auth import require_user

logger = logging.getLogger("red-culture.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5]{2,20}$", re.UNICODE)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=20, description="用户名（2-20位，字母/数字/下划线/中文）")
    password: str = Field(..., min_length=6, max_length=64, description="密码（6-64位）")
    grade: str = Field(DEFAULT_GRADE, description="默认学段")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=1, max_length=64)


def _validate_username(username: str) -> str:
    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "用户名需为 2-20 位字母、数字、下划线或中文")
    return username


def _validate_grade(grade: str) -> str:
    if grade not in GRADE_LEVELS:
        raise HTTPException(400, f"非法学段 {grade}，可选：{list(GRADE_LEVELS)}")
    return grade


@router.post("/register")
def register(req: RegisterRequest):
    _validate_username(req.username)
    _validate_grade(req.grade)
    try:
        user = auth.create_user(req.username, req.password, req.grade)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("注册失败：username=%s", req.username)
        raise HTTPException(500, "注册失败，请稍后再试") from e
    logger.info("用户注册：id=%s username=%s", user["id"], user["username"])
    return {"token": auth.issue_token(user), "user": {
        "id": user["id"], "username": user["username"], "role": user["role"], "grade": user["grade"],
    }}


@router.post("/login")
def login(req: LoginRequest):
    user = auth.get_user_by_username(req.username)
    if not user or not auth.verify_password(req.password, user["pw_hash"], user["salt"]):
        logger.info("登录失败：username=%s", req.username)
        raise HTTPException(401, "用户名或密码错误")
    logger.info("用户登录：id=%s username=%s", user["id"], user["username"])
    return {"token": auth.issue_token(user), "user": {
        "id": user["id"], "username": user["username"], "role": user["role"], "grade": user["grade"],
    }}


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {"user": user}
