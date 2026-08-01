"""LLM adapter for 三國志略 — Multi-provider support."""

from __future__ import annotations

import json
import os
import re

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .prompt_loader import KNOWN_PROMPTS

# Provider configurations in priority order
PROVIDER_CONFIGS = [
    {
        "name": "doubao",
        "env_key": "DOUBAO_API_KEY",
        "env_base": "DOUBAO_API_BASE",
        "default_base": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "ep-20260731233019-dnsbd",
        "supports_json_mode": True,
        "thinking_disabled": True,       # Disable reasoning tokens for faster responses
    },
    {
        "name": "deepseek",
        "env_key": "DEEPSEEK_API_KEY",
        "env_base": "DEEPSEEK_API_BASE",
        "default_base": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "supports_json_mode": True,
    },
    {
        "name": "gemini",
        "env_key": "GEMINI_API_KEY",
        "env_base": "GEMINI_API_BASE",
        "default_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
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
                "model": cfg["default_model"],  # Provider-specific: use its default, ignore LLM_MODEL
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
        data_dir: str | None = None,
    ):
        import logging

        self._logger = logging.getLogger("histrategy.llm")

        self.provider_config = detect_provider()

        # Explicit overrides take precedence
        self.api_key = api_key or self.provider_config["api_key"] or ""
        self.api_base = api_base or self.provider_config["api_base"] or "https://api.openai.com/v1"
        self.model = model or self.provider_config["model"] or "gpt-4o-mini"
        self.supports_json = self.provider_config["supports_json_mode"]
        self.provider_name = provider or self.provider_config["name"] or "none"
        self.last_call_stats = None
        # Cumulative token counters (thread-safe for GIL-protected int increments)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_all_tokens = 0
        self.total_calls = 0
        # Override log directory (e.g. for room-scoped logging)
        self._data_dir_override = data_dir

        # Room context for billing/logging (set via set_room_context before resolution)
        self.current_room_id: str | None = None
        self.current_quarter: int = 0
        self.current_scenario: str | None = None
        self.current_lang: str = "zh"

        self._logger.info(
            "LLMAdapter init: provider=%s model=%s base=%s available=%s",
            self.provider_name,
            self.model,
            self.api_base[:50] if self.api_base else "none",
            bool(self.api_key),
        )

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
            self._logger.warning("LLMAdapter: No API key configured — offline mode only")

    @property
    def is_available(self) -> bool:
        """Check if API is configured and ready."""
        return bool(self.api_key) and self.client is not None

    def set_room_context(self, room_id: str, quarter_number: int, scenario: str = "", lang: str = "zh") -> None:
        """Set the current room context for billing/logging and language enforcement.

        Call this at the start of each turn resolution so all LLM calls
        within the turn are automatically attributed to the correct room.
        When lang="en", all chat() calls auto-inject an English-only instruction
        into the system message — no need to hardcode it in individual prompt files.
        """
        self.current_room_id = room_id
        self.current_quarter = quarter_number
        self.current_scenario = scenario
        self.current_lang = lang

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 16384,
        metadata: dict | None = None,
    ) -> str:
        """Send a chat completion request with exponential backoff retry.

        When current_lang="en", auto-injects an English-only instruction
        into the system message. No need to hardcode language rules in
        individual prompt files.
        """
        if not self.is_available:
            raise RuntimeError(
                "No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, or TONGYI_API_KEY environment variable."
            )

        # ── Language enforcement (auto-injected, not per-prompt) ──
        messages = list(messages)  # shallow copy to avoid mutating caller
        if self.current_lang == "en":
            _LANG_INSTRUCTION = (
                "\n\nCRITICAL LANGUAGE RULE: You MUST respond entirely in English. "
                "All narrative text, NPC decisions, event descriptions, "
                "faction names, territory names, and any other output "
                "MUST be in English. Chinese characters are FORBIDDEN."
            )
            # Inject into the first system message, or prepend a new one
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    messages[i] = {**msg, "content": msg["content"] + _LANG_INSTRUCTION}
                    break
            else:
                messages.insert(0, {"role": "system", "content": _LANG_INSTRUCTION.strip()})

        import time

        @retry(
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        def _do_chat():
            start = time.perf_counter()
            body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            # Doubao Seed 2.1 turbo disables reasoning tokens for faster responses
            if self.provider_name == "doubao":
                body["thinking"] = {"type": "disabled"}
            resp = self.client.post(
                "/chat/completions",
                json=body,
            )
            latency = time.perf_counter() - start
            self._logger.info("LLM chat response: status=%d latency=%.1fs", resp.status_code, latency)
            resp.raise_for_status()
            return resp, latency

        start_time = time.perf_counter()
        response = None
        try:
            self._logger.info(
                "LLM chat: provider=%s model=%s prompt_chars=%d max_tokens=%d",
                self.provider_name,
                self.model,
                len(str(messages)),
                max_tokens,
            )
            response, latency = _do_chat()
            data = response.json()

            self._record_stats_and_log(messages, data, latency, metadata=metadata)

            return data["choices"][0]["message"]["content"]
        except Exception as e:
            latency = time.perf_counter() - start_time
            status = getattr(response, "status_code", "N/A") if response else "N/A"
            self._logger.error(
                "LLM chat FAILED after retries: provider=%s model=%s latency=%.1fs status=%s error=%s",
                self.provider_name,
                self.model,
                latency,
                status,
                str(e)[:200],
            )
            self._record_error_and_log(messages, e, latency, response, metadata=metadata)
            raise

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 16384,
        metadata: dict | None = None,
        stream_timeout: float | None = None,
    ):
        """Stream a chat completion, yielding text chunks as they arrive.

        Uses Server-Sent Events (SSE) via the OpenAI-compatible streaming API.
        Yields each content delta chunk as a string.

        stream_timeout: per-call read timeout in seconds. Defaults to 120s.
            Use a lower value (e.g. 45s) for time-sensitive streams like narrative
            generation where falling back to offline is preferred over waiting.
        """
        if not self.is_available:
            raise RuntimeError(
                "No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, "
                "or TONGYI_API_KEY environment variable."
            )

        # ── Language enforcement ──
        messages = list(messages)
        if self.current_lang == "en":
            _LANG_INSTRUCTION = (
                "\n\nCRITICAL LANGUAGE RULE: You MUST respond entirely in English. "
                "All narrative text, NPC decisions, event descriptions, "
                "faction names, territory names, and any other output "
                "MUST be in English. Chinese characters are FORBIDDEN."
            )
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    messages[i] = {**msg, "content": msg["content"] + _LANG_INSTRUCTION}
                    break
            else:
                messages.insert(0, {"role": "system", "content": _LANG_INSTRUCTION.strip()})

        import time

        start_time = time.perf_counter()
        self._logger.info(
            "LLM chat_stream: provider=%s model=%s prompt_chars=%d max_tokens=%d timeout=%s",
            self.provider_name,
            self.model,
            len(str(messages)),
            max_tokens,
            stream_timeout or "default",
        )

        _timeout = stream_timeout if stream_timeout is not None else 120.0

        try:
            stream_body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            # Doubao Seed 2.1 turbo disables reasoning tokens for faster responses
            if self.provider_name == "doubao":
                stream_body["thinking"] = {"type": "disabled"}
            with self.client.stream(
                "POST",
                "/chat/completions",
                json=stream_body,
                timeout=_timeout,
            ) as response:
                response.raise_for_status()
                full_content = []
                for line in response.iter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]  # strip "data: "
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content.append(content)
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

                latency = time.perf_counter() - start_time
                full_text = "".join(full_content)
                self._logger.info(
                    "LLM chat_stream done: provider=%s model=%s latency=%.1fs output_chars=%d",
                    self.provider_name,
                    self.model,
                    latency,
                    len(full_text),
                )
                # ── Write to DB (was missing — H31b fix) ──
                try:
                    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
                    stats = {
                        "provider": self.provider_name,
                        "model": self.model,
                        "latency": latency,
                        "prompt_tokens": max(1, prompt_chars // 4),
                        "completion_tokens": max(1, len(full_text) // 4),
                        "total_tokens": max(1, (prompt_chars + len(full_text)) // 4),
                        "reasoning_tokens": 0,
                    }
                    self._log_llm_call_to_db(
                        messages, full_text, stats, latency, metadata, error=None
                    )
                except Exception as _log_err:
                    self._logger.warning("chat_stream DB log failed: %s", _log_err)
        except Exception as e:
            latency = time.perf_counter() - start_time
            self._logger.error(
                "LLM chat_stream FAILED: provider=%s model=%s latency=%.1fs error=%s",
                self.provider_name,
                self.model,
                latency,
                str(e)[:200],
            )
            # ── Write error to DB (was missing — H31b fix) ──
            try:
                stats = {
                    "provider": self.provider_name,
                    "model": self.model,
                    "latency": latency,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "reasoning_tokens": 0,
                }
                self._log_llm_call_to_db(
                    messages, "", stats, latency, metadata, error=str(e)[:500]
                )
            except Exception as _log_err:
                self._logger.warning("chat_stream error DB log failed: %s", _log_err)
            raise

    def chat_structured(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        metadata: dict | None = None,
    ) -> dict:
        """Send a chat completion request with structured output.

        Uses JSON mode when the provider supports it, otherwise
        parses JSON from the text response.
        """
        if not self.is_available:
            raise RuntimeError(
                "No API key configured. Set DEEPSEEK_API_KEY, OPENAI_API_KEY, or TONGYI_API_KEY environment variable."
            )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Doubao Seed: disable reasoning tokens for faster responses
        if self.provider_name == "doubao":
            payload["thinking"] = {"type": "disabled"}

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
        # ── Attempt 1: with JSON mode ──
        response = None
        try:
            # Debug: log exact request params for troubleshooting
            self._logger.info(
                "chat_structured: provider=%s base=%s model=%s key_prefix=%s json_mode=%s",
                self.provider_name,
                self.client.base_url if self.client else "NONE",
                payload.get("model", "?"),
                self.api_key[:8] + "..." if self.api_key else "NONE",
                use_json_mode,
            )
            response = self.client.post(
                "/chat/completions",
                json=payload,
            )
            latency = time.perf_counter() - start_time
            response.raise_for_status()
            data = response.json()

            self._record_stats_and_log(messages, data, latency, metadata=metadata)

            content = data["choices"][0]["message"]["content"]

            # Try direct parse first (JSON mode should return clean JSON)
            if use_json_mode:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    pass  # Fall through to extraction below

            # Extract JSON from text response (handles markdown fences, etc.)
            return self._extract_json(content)
        except Exception as e:
            latency = time.perf_counter() - start_time
            # Log response body for debugging
            if response is not None:
                try:
                    resp_body = response.text[:500]
                    self._logger.error(
                        "chat_structured HTTP %s body: %s", response.status_code, resp_body
                    )
                except Exception:
                    pass
            # ── Fallback: retry without JSON mode if it failed ──
            if use_json_mode and response is not None and 400 <= response.status_code < 500:
                self._logger.warning(
                    "chat_structured JSON mode failed (HTTP %s), retrying without response_format",
                    response.status_code,
                )
                payload.pop("response_format", None)
                try:
                    retry_start = time.perf_counter()
                    response2 = self.client.post(
                        "/chat/completions",
                        json=payload,
                    )
                    retry_latency = time.perf_counter() - retry_start
                    response2.raise_for_status()
                    data2 = response2.json()
                    self._record_stats_and_log(
                        messages, data2, retry_latency, metadata=metadata
                    )
                    content2 = data2["choices"][0]["message"]["content"]
                    return self._extract_json(content2)
                except Exception as retry_e:
                    self._logger.error(
                        "chat_structured fallback also failed: %s", retry_e
                    )
            self._record_error_and_log(messages, e, latency, response, metadata=metadata)
            raise

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from a text response when JSON mode isn't available."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Clean common LLM JSON formatting issues
        cleaned = self._clean_json_text(text)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try ```json ... ``` blocks
        json_match = re.search(r"```(?:json)?\s*\n?({.*?})\n?\s*```", cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try { ... } outermost block
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not extract JSON from response:\\n{text[:500]}")

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Remove common LLM JSON formatting errors: trailing commas, + before numbers, comments."""
        # Remove + signs before numbers (LLMs often write +5 instead of 5)
        text = re.sub(r":\s*\+\s*(\d)", r": \1", text)
        # Remove trailing commas before ] or }
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Remove single-line // comments (outside strings)
        text = re.sub(r"//[^\n]*", "", text)
        return text

    def _record_stats_and_log(
        self, messages: list[dict], response_data: dict, latency: float, metadata: dict | None = None
    ) -> None:
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

            # Update cumulative counters (GIL-protected, safe for moderate concurrency)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_all_tokens += total_tokens
            self.total_calls += 1

            self._write_to_log_files(messages, response_data, latency, self.last_call_stats, metadata=metadata)
        except Exception as e:
            import sys

            print(f"[Warning] Failed to record/log LLM usage: {e}", file=sys.stderr)

    def _write_to_log_files(
        self,
        messages: list[dict],
        response_data: dict,
        latency: float,
        stats: dict,
        metadata: dict | None = None,
    ) -> None:
        import json as _json
        from datetime import datetime
        from pathlib import Path

        try:
            if self._data_dir_override:
                log_dir = Path(self._data_dir_override) / "logs"
            else:
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
            if metadata:
                jsonl_entry["metadata"] = metadata
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(jsonl_entry, ensure_ascii=False) + "\n")

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
            ]
            if metadata:
                if "category" in metadata:
                    log_entry.append(f"Category:          {metadata['category']}\n")
                if "reason" in metadata:
                    log_entry.append(f"Reason:            {metadata['reason']}\n")
                if "faction_id" in metadata:
                    log_entry.append(f"Faction:           {metadata['faction_id']}\n")
                if "year" in metadata:
                    log_entry.append(f"Year:              {metadata['year']}\n")
                if "season" in metadata:
                    log_entry.append(f"Season:            {metadata['season']}\n")
                if "turn" in metadata:
                    log_entry.append(f"Turn:              {metadata['turn']}\n")
            log_entry.extend(
                [
                    f"Prompt Tokens:     {stats['prompt_tokens']}\n",
                    f"Completion Tokens: {stats['completion_tokens']}\n",
                    f"Total Tokens:      {stats['total_tokens']}\n",
                ]
            )
            if stats["reasoning_tokens"] > 0:
                log_entry.append(f"Reasoning Tokens:  {stats['reasoning_tokens']}\n")
            log_entry.append(divider_minor)

            log_entry.append("--- INPUT MESSAGES ---\n")
            for msg in messages:
                role = msg.get("role", "unknown").upper()
                msg_content = msg.get("content", "")

                # Check for known prompts to suppress verbose logs
                if role == "SYSTEM":
                    stripped_content = msg_content.strip()
                    matched_prompt = None
                    for name, content_template in KNOWN_PROMPTS.items():
                        if content_template is not None and stripped_content == content_template.strip():
                            matched_prompt = name
                            break
                    if matched_prompt:
                        msg_content = f"(Standard Template: {matched_prompt})"
                    else:
                        first_line = stripped_content.split("\n")[0][:120]
                        msg_content = f"(Custom Prompt: {first_line}...)"

                log_entry.append(f"[{role}]:\n{msg_content}\n")
                log_entry.append(divider_minor)

            log_entry.append("--- RESPONSE ---\n")
            log_entry.append(f"{content}\n")
            log_entry.append(divider_major)
            log_entry.append("\n")

            with open(log_path, "a", encoding="utf-8") as f:
                f.writelines(log_entry)

            # 3. Write to database llm_call_log (H14b)
            self._log_llm_call_to_db(messages, content, stats, latency, metadata, error=None)

        except Exception as e:
            import sys

            print(f"[Warning] Failed to write LLM log: {e}", file=sys.stderr)

    def _log_llm_call_to_db(
        self,
        messages: list[dict],
        response_content: str,
        stats: dict,
        latency: float,
        metadata: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Write a single LLM call to the database llm_call_log table."""
        try:
            from histrategy.db.models import log_llm_call

            meta = metadata or {}
            room_id = meta.get("room_id") or self.current_room_id
            if not room_id or room_id == "unknown":
                return
            quarter_number = meta.get("quarter_number", self.current_quarter)
            call_type = meta.get("category", meta.get("call_type", "unknown"))
            faction_id = meta.get("faction_id")
            system_prompt_type = meta.get("system_prompt_type")

            # Derive system_prompt_type from messages if not in metadata
            if not system_prompt_type:
                for msg in messages:
                    if msg.get("role") == "system":
                        system_content = msg.get("content", "")
                        # Check known prompts
                        for name, template in KNOWN_PROMPTS.items():
                            if template is not None and system_content.strip() == template.strip():
                                system_prompt_type = name
                                break
                        if not system_prompt_type:
                            system_prompt_type = "custom"
                        break

            # Build user_prompt: concatenate user/assistant messages
            user_prompt_parts = []
            for msg in messages:
                if msg.get("role") != "system":
                    user_prompt_parts.append(f"[{msg['role']}]: {msg.get('content', '')}")
            user_prompt = "\n".join(user_prompt_parts) if user_prompt_parts else None

            log_llm_call(
                room_id=room_id,
                quarter_number=quarter_number,
                call_type=call_type,
                provider=stats.get("provider", "unknown"),
                model=stats.get("model", "unknown"),
                prompt_tokens=stats.get("prompt_tokens", 0),
                completion_tokens=stats.get("completion_tokens", 0),
                total_tokens=stats.get("total_tokens", 0),
                reasoning_tokens=stats.get("reasoning_tokens"),
                latency_ms=int(latency * 1000),
                system_prompt_type=system_prompt_type,
                user_prompt=user_prompt,
                response=response_content,
                error=error,
                faction_id=faction_id,
            )
        except Exception as e:
            import sys

            print(f"[Warning] Failed to write LLM call to DB: {e}", file=sys.stderr)

    def _record_error_and_log(
        self,
        messages: list[dict],
        exception: Exception,
        latency: float,
        response: httpx.Response | None = None,
        metadata: dict | None = None,
    ) -> None:
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

            self._write_error_to_log_files(messages, exception, latency, response, metadata=metadata)
        except Exception as log_err:
            import sys

            print(f"[Warning] Failed to log LLM error: {log_err}", file=sys.stderr)

    def _write_error_to_log_files(
        self,
        messages: list[dict],
        exception: Exception,
        latency: float,
        response: httpx.Response | None = None,
        metadata: dict | None = None,
    ) -> None:
        import json
        from datetime import datetime
        from pathlib import Path

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
            if metadata:
                jsonl_entry["metadata"] = metadata
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
            ]
            if metadata:
                if "category" in metadata:
                    log_entry.append(f"Category:          {metadata['category']}\n")
                if "reason" in metadata:
                    log_entry.append(f"Reason:            {metadata['reason']}\n")
                if "faction_id" in metadata:
                    log_entry.append(f"Faction:           {metadata['faction_id']}\n")
                if "year" in metadata:
                    log_entry.append(f"Year:              {metadata['year']}\n")
                if "season" in metadata:
                    log_entry.append(f"Season:            {metadata['season']}\n")
                if "turn" in metadata:
                    log_entry.append(f"Turn:              {metadata['turn']}\n")
            log_entry.extend(
                [
                    "Status:            ERROR\n",
                    f"Exception:         {str(exception)}\n",
                ]
            )
            if status_code is not None:
                log_entry.append(f"HTTP Status Code:  {status_code}\n")
            log_entry.append(divider_minor)

            log_entry.append("--- INPUT MESSAGES ---\n")
            for msg in messages:
                role = msg.get("role", "unknown").upper()
                msg_content = msg.get("content", "")

                # Check for known prompts to suppress verbose logs
                if role == "SYSTEM":
                    stripped_content = msg_content.strip()
                    matched_prompt = None
                    for name, content_template in KNOWN_PROMPTS.items():
                        if content_template is not None and stripped_content == content_template.strip():
                            matched_prompt = name
                            break
                    if matched_prompt:
                        msg_content = f"(Standard Template: {matched_prompt})"
                    else:
                        first_line = stripped_content.split("\n")[0][:120]
                        msg_content = f"(Custom Prompt: {first_line}...)"

                log_entry.append(f"[{role}]:\n{msg_content}\n")
                log_entry.append(divider_minor)

            if response_body:
                log_entry.append("--- RAW ERROR RESPONSE ---\n")
                log_entry.append(f"{response_body}\n")
                log_entry.append(divider_major)
            log_entry.append("\n")

            with open(log_path, "a", encoding="utf-8") as f:
                f.writelines(log_entry)

            # 3. Write to database llm_call_log (H14b) — error case
            self._log_llm_call_to_db(
                messages,
                response_content=response_body if response_body else "",
                stats={
                    "provider": self.provider_name,
                    "model": self.model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "reasoning_tokens": 0,
                },
                latency=latency,
                metadata=metadata,
                error=str(exception),
            )

        except Exception as e:
            import sys

            print(f"[Warning] Failed to write LLM error log: {e}", file=sys.stderr)
