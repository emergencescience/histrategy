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
        "env_base": "DEEPSEEK_API_BASE",
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
        "env_base": "TONGYI_API_BASE",
        "default_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "supports_json_mode": True,
    },
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "env_base": "OPENROUTER_API_BASE",
        "default_base": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-v4-pro",
        "supports_json_mode": False,
    },
]


def detect_provider() -> dict:
    """Auto-detect the best available LLM provider.

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
            base_override = os.environ.get(cfg.get("env_base", ""), "")
            if not base_override and cfg["name"] != "openai":
                base_override = os.environ.get("OPENAI_API_BASE", "")
            return {
                "name": cfg["name"],
                "api_key": key,
                "api_base": base_override or cfg["default_base"],
                "model": os.environ.get("LLM_MODEL", cfg["default_model"]),
                "supports_json_mode": cfg["supports_json_mode"],
            }

    # Path 2: Generic OpenAI-compatible endpoint
    generic_base = os.environ.get("LLM_API_BASE", "")
    generic_key = os.environ.get("LLM_API_KEY", "")
    if generic_base and generic_key:
        return {
            "name": "custom",
            "api_key": generic_key,
            "api_base": generic_base,
            "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            "supports_json_mode": True,
        }

    # Path 3: Legacy backward compat (OPENAI_API_BASE + OPENAI_API_KEY)
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

    # No key configured → offline mode
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
        self.last_call_stats = None

        if self.api_key:
            self.client = httpx.Client(
                base_url=self.api_base.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=180.0,
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

        import time
        start_time = time.perf_counter()
        response = None
        try:
            response = self.client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            latency = time.perf_counter() - start_time
            response.raise_for_status()
            data = response.json()

            self._record_stats_and_log(messages, data, latency)

            return data["choices"][0]["message"]["content"]
        except Exception as e:
            latency = time.perf_counter() - start_time
            self._record_error_and_log(messages, e, latency, response)
            raise

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

        import time
        start_time = time.perf_counter()
        response = None
        try:
            response = self.client.post(
                "/chat/completions",
                json=payload,
            )
            latency = time.perf_counter() - start_time
            response.raise_for_status()
            data = response.json()

            self._record_stats_and_log(messages, data, latency)

            content = data["choices"][0]["message"]["content"]

            # Try to parse JSON
            if use_json_mode:
                return json.loads(content)

            # Fallback: extract JSON from text response
            return self._extract_json(content)
        except Exception as e:
            latency = time.perf_counter() - start_time
            self._record_error_and_log(messages, e, latency, response)
            raise

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

    def _record_stats_and_log(self, messages: list[dict], response_data: dict, latency: float) -> None:
        """Parse token usage, update self.last_call_stats, and write logs."""
        try:
            usage = response_data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            reasoning_tokens = 0
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                reasoning_tokens = details.get("reasoning_tokens", 0)

            self.last_call_stats = {
                "provider": self.provider_name,
                "model": self.model,
                "latency": latency,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "reasoning_tokens": reasoning_tokens,
            }

            self._write_to_log_files(messages, response_data, latency, self.last_call_stats)
        except Exception as e:
            import sys
            print(f"[Warning] Failed to record/log LLM usage: {e}", file=sys.stderr)

    def _write_to_log_files(self, messages: list[dict], response_data: dict, latency: float, stats: dict) -> None:
        from datetime import datetime
        from pathlib import Path
        import json

        try:
            try:
                from ..state.world_state import get_data_dir
                log_dir = get_data_dir() / "logs"
            except ImportError:
                log_dir = Path(__file__).parent.parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            timestamp_str = datetime.now().isoformat()
            readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # 1. Write to JSONL (for parsed analytics)
            jsonl_path = log_dir / "llm_usage.jsonl"
            jsonl_entry = {
                "timestamp": timestamp_str,
                "provider": stats["provider"],
                "model": stats["model"],
                "latency_seconds": stats["latency"],
                "prompt_tokens": stats["prompt_tokens"],
                "completion_tokens": stats["completion_tokens"],
                "total_tokens": stats["total_tokens"],
                "reasoning_tokens": stats["reasoning_tokens"],
                "messages": messages,
                "response": content,
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

            # 2. Write to readable .log file
            log_path = log_dir / "llm_usage.log"
            divider_major = "=" * 80 + "\n"
            divider_minor = "-" * 80 + "\n"

            log_entry = [
                divider_major,
                f"Timestamp:         {readable_time}\n",
                f"Provider:          {stats['provider']}\n",
                f"Model:             {stats['model']}\n",
                f"Latency:           {stats['latency']:.2f}s\n",
                f"Prompt Tokens:     {stats['prompt_tokens']}\n",
                f"Completion Tokens: {stats['completion_tokens']}\n",
                f"Total Tokens:      {stats['total_tokens']}\n",
            ]
            if stats["reasoning_tokens"] > 0:
                log_entry.append(f"Reasoning Tokens:  {stats['reasoning_tokens']}\n")
            log_entry.append(divider_minor)

            log_entry.append("--- INPUT MESSAGES ---\n")
            for msg in messages:
                role = msg.get("role", "unknown").upper()
                msg_content = msg.get("content", "")
                log_entry.append(f"[{role}]:\n{msg_content}\n")
                log_entry.append(divider_minor)

            log_entry.append("--- RESPONSE ---\n")
            log_entry.append(f"{content}\n")
            log_entry.append(divider_major)
            log_entry.append("\n")

            with open(log_path, "a", encoding="utf-8") as f:
                f.writelines(log_entry)

        except Exception as e:
            import sys
            print(f"[Warning] Failed to write LLM log: {e}", file=sys.stderr)

    def _record_error_and_log(self, messages: list[dict], exception: Exception, latency: float, response: httpx.Response | None = None) -> None:
        """Log LLM call errors to self.last_call_stats and write to logs."""
        try:
            self.last_call_stats = {
                "provider": self.provider_name,
                "model": self.model,
                "latency": latency,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "reasoning_tokens": 0,
                "error": str(exception),
            }

            self._write_error_to_log_files(messages, exception, latency, response)
        except Exception as log_err:
            import sys
            print(f"[Warning] Failed to log LLM error: {log_err}", file=sys.stderr)

    def _write_error_to_log_files(self, messages: list[dict], exception: Exception, latency: float, response: httpx.Response | None = None) -> None:
        from datetime import datetime
        from pathlib import Path
        import json

        try:
            try:
                from ..state.world_state import get_data_dir
                log_dir = get_data_dir() / "logs"
            except ImportError:
                log_dir = Path(__file__).parent.parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            timestamp_str = datetime.now().isoformat()
            readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            status_code = response.status_code if response is not None else None
            response_body = response.text if response is not None else ""

            # 1. Write to JSONL
            jsonl_path = log_dir / "llm_usage.jsonl"
            jsonl_entry = {
                "timestamp": timestamp_str,
                "provider": self.provider_name,
                "model": self.model,
                "latency_seconds": latency,
                "error": str(exception),
                "status_code": status_code,
                "response_body": response_body,
                "messages": messages,
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

            # 2. Write to readable .log file
            log_path = log_dir / "llm_usage.log"
            divider_major = "=" * 80 + "\n"
            divider_minor = "-" * 80 + "\n"

            log_entry = [
                divider_major,
                f"Timestamp:         {readable_time}\n",
                f"Provider:          {self.provider_name}\n",
                f"Model:             {self.model}\n",
                f"Latency:           {latency:.2f}s\n",
                f"Status:            ERROR\n",
                f"Exception:         {str(exception)}\n",
            ]
            if status_code is not None:
                log_entry.append(f"HTTP Status Code:  {status_code}\n")
            log_entry.append(divider_minor)

            log_entry.append("--- INPUT MESSAGES ---\n")
            for msg in messages:
                role = msg.get("role", "unknown").upper()
                msg_content = msg.get("content", "")
                log_entry.append(f"[{role}]:\n{msg_content}\n")
                log_entry.append(divider_minor)

            if response_body:
                log_entry.append("--- RAW ERROR RESPONSE ---\n")
                log_entry.append(f"{response_body}\n")
                log_entry.append(divider_major)
            log_entry.append("\n")

            with open(log_path, "a", encoding="utf-8") as f:
                f.writelines(log_entry)

        except Exception as e:
            import sys
            print(f"[Warning] Failed to write LLM error log: {e}", file=sys.stderr)
