# -*- coding: utf-8 -*-
"""pytest 全局配置：在任何 app 模块导入前隔离测试环境（独立数据库 + 固定密钥）。"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="rc_test_")

# 测试专用 SQLite 库，避免污染真实 data/ 目录
os.environ.setdefault("SESSION_DB", os.path.join(_TMP, "sessions.db"))
os.environ.setdefault("CACHE_DB", os.path.join(_TMP, "answer_cache.db"))
os.environ.setdefault("USERS_DB", os.path.join(_TMP, "users.db"))
os.environ.setdefault("RATELIMIT_DB", os.path.join(_TMP, "ratelimit.db"))

# 固定签名密钥保证令牌测试可复现；假 API Key 仅供配置解析，测试不发起真实 LLM 调用
os.environ["AUTH_SECRET"] = "test-secret-for-pytest"
os.environ.setdefault("ZHIPU_API_KEY", "test-key-not-real")
