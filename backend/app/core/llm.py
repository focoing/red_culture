# -*- coding: utf-8 -*-
"""LLM 大模型封装：硅基流动 SiliconFlow（OpenAI 兼容接口），默认 DeepSeek-V4.1-Flash。"""
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import (
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_THINKING,
    LLM_TIMEOUT,
    ZHIPU_API_KEY,
    ZHIPU_BASE_URL,
)


@lru_cache(maxsize=2)  # 流式 / 非流式各缓存一个实例
def get_llm(streaming: bool = False) -> ChatOpenAI:
    """返回接入硅基流动 DeepSeek 的 ChatOpenAI 实例。

    Args:
        streaming: 是否开启流式输出（对话接口使用）。

    稳定性设计：
        - timeout: 生成类模型耗时较长，超时需放宽；
        - max_retries: 平台高峰期限流（429）时按指数退避重试，
          大幅提高瞬时拥塞下的成功率。
    """
    if not ZHIPU_API_KEY:
        raise RuntimeError("未配置 ZHIPU_API_KEY，请在 backend/.env 中填入硅基流动 API Key")

    kwargs = {}
    if LLM_THINKING in ("true", "false"):  # 显式配置时才下发思考开关，否则尊重模型默认行为
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if LLM_THINKING == "true" else "disabled"}}

    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=ZHIPU_API_KEY,
        base_url=ZHIPU_BASE_URL,
        temperature=LLM_TEMPERATURE,
        streaming=streaming,
        timeout=LLM_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
        **kwargs,
    )


def check_llm() -> bool:
    """探测 LLM API 是否已配置（密钥存在即视为就绪）。"""
    return bool(ZHIPU_API_KEY)
