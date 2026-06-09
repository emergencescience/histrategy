"""
LLM adapter for histrategy-agent — thin wrapper for OpenAI-compatible APIs.

Auto-detects API keys from environment. Falls back to offline mode
when no key is configured. Zero-copy design: if httpx is not installed,
all LLM methods return None and the caller uses offline fallbacks.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


# Provider auto-detection (priority order)
PROVIDER_CONFIGS = [
    {"name": "deepseek", "env_key": "DEEPSEEK_API_KEY",
     "default_base": "https://api.deepseek.com", "default_model": "deepseek-v4-pro"},
    {"name": "openai", "env_key": "OPENAI_API_KEY",
     "default_base": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
    {"name": "tongyi", "env_key": "TONGYI_API_KEY",
     "default_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-max"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY",
     "default_base": "https://openrouter.ai/api/v1", "default_model": "deepseek/deepseek-v4-pro"},
]


def detect_provider() -> dict:
    """Auto-detect the best available LLM provider from env vars.

    Three-path design (pick the first that matches):
      1. Provider-specific API key
         Set ONE of DEEPSEEK_API_KEY / OPENAI_API_KEY / TONGYI_API_KEY /
         OPENROUTER_API_KEY. URL and model are auto-configured.
         Auto-detection priority: DeepSeek > OpenAI > Tongyi > OpenRouter.

      2. Generic OpenAI-compatible endpoint
         Set LLM_API_BASE + LLM_API_KEY. Use LLM_MODEL to override
         the model name (defaults to gpt-4o-mini).

      3. No key configured → offline mode
    """
    # Path 1: Auto-detect by provider-specific API key
    for cfg in PROVIDER_CONFIGS:
        key = os.environ.get(cfg["env_key"], "")
        if key and not key.startswith("your-") and len(key) > 10:
            return {
                "name": cfg["name"], "api_key": key,
                "api_base": os.environ.get("OPENAI_API_BASE", "") or cfg["default_base"],
                "model": os.environ.get("LLM_MODEL", cfg["default_model"]),
            }

    # Path 2: Generic OpenAI-compatible endpoint
    generic_base = os.environ.get("LLM_API_BASE", "")
    generic_key = os.environ.get("LLM_API_KEY", "")
    if generic_base and generic_key:
        return {
            "name": "custom", "api_key": generic_key,
            "api_base": generic_base,
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        }

    return {"name": None, "api_key": "", "api_base": "", "model": ""}


class LLMClient:
    """Minimal LLM client for the agent layer. No heavy deps."""

    def __init__(self):
        self._client = None
        self._provider = None
        self._model = None
        self._api_base = None

    @property
    def is_available(self) -> bool:
        return self._ensure_client()

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        if not HAS_HTTPX:
            return False
        cfg = detect_provider()
        if not cfg["api_key"]:
            return False
        self._provider = cfg["name"]
        self._model = cfg["model"]
        self._api_base = cfg["api_base"]
        self._client = httpx.Client(
            base_url=self._api_base.rstrip("/"),
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            timeout=120.0,
        )
        return True

    def chat(self, messages: list[dict], temperature: float = 0.8,
             max_tokens: int = 1024) -> str | None:
        """Send a chat completion. Returns None if unavailable."""
        if not self._ensure_client():
            return None
        try:
            resp = self._client.post("/chat/completions", json={
                "model": self._model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens,
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

    def chat_structured(self, messages: list[dict], temperature: float = 0.3,
                        max_tokens: int = 2048) -> dict | None:
        """Chat with JSON-structured output. Returns None if unavailable."""
        if not self._ensure_client():
            return None
        try:
            resp = self._client.post("/chat/completions", json={
                "model": self._model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens,
            })
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            # Extract JSON from response
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
            m = re.search(r"```(?:json)?\s*\n?({.*?})\n?\s*```", content, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            m = re.search(r"(\{.*\})", content, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            return None
        except Exception:
            return None


# Singleton
_llm_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
