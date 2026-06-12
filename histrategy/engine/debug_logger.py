"""
Debug Logger — collects LLM call records and simulation events
during a turn, then fires a single batch POST to the orchestrator.

Usage per turn:
    from .debug_logger import TurnLogCollector
    log = TurnLogCollector(session_id, turn_number, orchestrator_url, jwt_token)
    log.llm("macro_simulate", "deepseek", "deepseek-chat", 1200, 3500, 4700, 28000, ...)
    log.event("black_swan", {"event_id": "liubiao_death_208", ...})
    log.flush()  # fire-and-forget
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import httpx

_logger = logging.getLogger("histrategy.debug_logger")


class TurnLogCollector:
    """Collects log records in memory and flushes to orchestrator.
    
    Fire-and-forget: flush() spawns a daemon thread so it never
    blocks the game turn if the orchestrator is slow/unreachable.
    """

    def __init__(
        self,
        session_id: str,
        turn_number: int,
        orchestrator_url: str = "",
        jwt_token: str = "",
    ):
        self.session_id = session_id
        self.turn_number = turn_number
        self.orchestrator_url = (orchestrator_url or os.environ.get("ORCHESTRATOR_URL", "")).rstrip("/")
        self.jwt_token = jwt_token
        self._llm_calls: list[dict[str, Any]] = []
        self._sim_events: list[dict[str, Any]] = []

    def llm(
        self,
        call_type: str,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        reasoning_tokens: int | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        response: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record an LLM call."""
        self._llm_calls.append({
            "call_type": call_type,
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": reasoning_tokens,
            "latency_ms": latency_ms,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "error": error,
        })

    def event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Record a simulation event."""
        self._sim_events.append({
            "event_type": event_type,
            "event_data": event_data,
        })

    def flush(self) -> None:
        """Fire-and-forget POST to orchestrator. Never blocks."""
        if not self._llm_calls and not self._sim_events:
            return
        if not self.orchestrator_url:
            return

        payload = {
            "session_id": self.session_id,
            "turn_number": self.turn_number,
            "llm_calls": self._llm_calls,
            "sim_events": self._sim_events,
        }

        # Clear local buffers immediately (even if POST fails)
        llm_calls = self._llm_calls
        sim_events = self._sim_events
        self._llm_calls = []
        self._sim_events = []

        url = f"{self.orchestrator_url}/games/histrategy/api/log/batch"
        headers = {"Content-Type": "application/json"}
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"

        def _post():
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code >= 400:
                        _logger.debug(f"Log batch POST returned {resp.status_code}: {resp.text[:200]}")
            except Exception:
                _logger.debug("Log batch POST failed (non-critical)", exc_info=True)

        t = threading.Thread(target=_post, daemon=True)
        t.start()
