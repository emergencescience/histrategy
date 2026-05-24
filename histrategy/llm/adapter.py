"""LLM adapter for 三國志略 — Multi-provider support."""
from __future__ import annotations

import json
import os
import re

import httpx

# Provider configurations in priority order
PROVIDER_CONFIGS = [
    {
        "name": "deepseek",
        "env_key": "DEEPSEEK_API_KEY",
        "default_base": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
        "supports_json_mode": True,
    },
    {
        "name": "openai",
        "env_key": "OPENAI_API_KEY",
        "env_base": "OPENAI_API_BASE",
        "default_base": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "supports_json_mode": True,
    },
    {
        "name": "tongyi",
        "env_key": "TONGYI_API_KEY",
        "default_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "supports_json_mode": True,
    },
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "default_base": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-v4-pro",
        "supports_json_mode": False,
    },
]


def detect_provider() -> dict:
    """Auto-detect the best available LLM provider.

    Priority:
      1. LLM_PROVIDER env var (explicit override)
      2. DEEPSEEK_API_KEY
      3. OPENAI_API_KEY
      4. TONGYI_API_KEY
      5. OPENROUTER_API_KEY
      6. OPENAI_API_BASE + OPENAI_API_KEY (custom endpoint)
    """
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()

    if explicit == "custom":
        return {
            "name": "custom",
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
            "api_base": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            "supports_json_mode": True,
        }

    if explicit:
        for cfg in PROVIDER_CONFIGS:
            if cfg["name"] == explicit:
                key = os.environ.get(cfg["env_key"], "")
                if key:
                    base_override = os.environ.get(cfg.get("env_base", ""), "")
                    return {
                        "name": cfg["name"],
                        "api_key": key,
                        "api_base": base_override or cfg["default_base"],
                        "model": os.environ.get("LLM_MODEL", cfg["default_model"]),
                        "supports_json_mode": cfg["supports_json_mode"],
                    }
                return {
                    "name": cfg["name"],
                    "api_key": "",
                    "api_base": cfg["default_base"],
                    "model": os.environ.get("LLM_MODEL", cfg["default_model"]),
                    "supports_json_mode": cfg["supports_json_mode"],
                }

    # Auto-detect: first provider with a valid key wins
    for cfg in PROVIDER_CONFIGS:
        key = os.environ.get(cfg["env_key"], "")
        if key and not key.startswith("your-") and len(key) > 10:
            base_override = os.environ.get(cfg.get("env_base", ""), "")
            return {
                "name": cfg["name"],
                "api_key": key,
                "api_base": base_override or cfg["default_base"],
                "model": os.environ.get("LLM_MODEL", cfg["default_model"]),
                "supports_json_mode": cfg["supports_json_mode"],
            }

    # Fallback: try OPENAI_API_BASE + OPENAI_API_KEY (custom endpoint)
    base = os.environ.get("OPENAI_API_BASE", "")
    key = os.environ.get("OPENAI_API_KEY", "")
    if base and key:
        return {
            "name": "custom",
            "api_key": key,
            "api_base": base,
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            "supports_json_mode": True,
        }

    return {"name": None, "api_key": "", "api_base": "", "model": "", "supports_json_mode": False}


class LLMAdapter:
    """Adapter for LLM API calls. Supports multiple providers with auto-detection."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ):
        self.provider_config = detect_provider()

        # Explicit overrides take precedence
        self.api_key = api_key or self.provider_config["api_key"] or ""
        self.api_base = (api_base or self.provider_config["api_base"]
                         or "https://api.openai.com/v1")
        self.model = (model or self.provider_config["model"]
                      or "gpt-4o-mini")
        self.supports_json = self.provider_config["supports_json_mode"]
        self.provider_name = provider or self.provider_config["name"] or "none"

        if self.api_key:
            self.client = httpx.Client(
                base_url=self.api_base.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        else:
            self.client = None

    @property
    def is_available(self) -> bool:
        """Check if API is configured and ready."""
        return bool(self.api_key) and self.client is not None

    def chat(self, messages: list[dict], temperature: float = 0.7,
             max_tokens: int = 2048) -> str:
        """Send a chat completion request."""
        if not self.is_available:
            raise RuntimeError(
                "No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, "
                "or TONGYI_API_KEY environment variable."
            )

        response = self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def chat_structured(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """Send a chat completion request with structured output.

        Uses JSON mode when the provider supports it, otherwise
        parses JSON from the text response.
        """
        if not self.is_available:
            raise RuntimeError(
                "No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, "
                "or TONGYI_API_KEY environment variable."
            )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # JSON mode for supported providers
        use_json_mode = response_format and self.supports_json
        # OpenAI/DeepSeek use response_format, others may not
        if use_json_mode:
            if response_format:
                payload["response_format"] = response_format
            else:
                payload["response_format"] = {"type": "json_object"}

        response = self.client.post(
            "/chat/completions",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Try to parse JSON
        if use_json_mode:
            return json.loads(content)

        # Fallback: extract JSON from text response
        return self._extract_json(content)

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from a text response when JSON mode isn't available."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try ```json ... ``` blocks
        json_match = re.search(r"```(?:json)?\s*\n?({.*?})\n?\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try { ... } outermost block
        brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from response:\n{text[:500]}")
