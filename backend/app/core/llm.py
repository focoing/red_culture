# -*- coding: utf-8 -*-
"""Ollama + Qwen2.5 本地大模型封装。"""
from functools import lru_cache

from langchain_ollama import ChatOllama

from app.config import (
    LLM_MODEL,
    LLM_NUM_CTX,
    LLM_TEMPERATURE,
    OLLAMA_BASE_URL,
)


@lru_cache(maxsize=2)  # 流式 / 非流式各缓存一个实例
def get_llm(streaming: bool = False) -> ChatOllama:
    """返回 ChatOllama 实例。

    Args:
        streaming: 是否开启流式输出（对话接口使用）。
    """
    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        num_ctx=LLM_NUM_CTX,
        streaming=streaming,
    )


def check_ollama() -> bool:
    """探测 Ollama 服务与模型是否可用。"""
    import httpx

    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        base = LLM_MODEL.split(":")[0]
        return any(m == LLM_MODEL or m.startswith(base) for m in models)
    except Exception:
        return False
