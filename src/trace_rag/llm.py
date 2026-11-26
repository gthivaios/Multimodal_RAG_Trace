"""Thin wrapper around an OpenAI-compatible chat endpoint (OpenRouter by default)."""

from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from trace_rag import config


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not config.LLM_API_KEY:
        raise RuntimeError(
            "No API key found. Copy .env.example to .env and set OPENROUTER_API_KEY."
        )
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
