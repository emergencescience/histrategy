"""
Debug Logger — collects LLM call records and simulation events
during a turn for local logging.

Usage per turn:
    from .debug_logger import TurnLogCollector
    log = TurnLogCollector(session_id, turn_number)
    log.llm("macro_simulate", "deepseek", "deepseek-chat", 1200, 3500, 4700, 28000, ...)
    log.event("black_swan", {"event_id": "liubiao_death_208", ...})
    log.flush()  # logs locally
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger("histrategy.debug_logger")


class TurnLogCollector:
    """Collects log records in memory. flush() logs locally.

    No longer POSTs to orchestrator — dependency arrow is
    unilateral: orchestrator → histrategy, never reverse.
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
        # orchestrator_url + jwt_token accepted for backward compat but ignored.
        # Dependency arrow is unilateral: orchestrator → histrategy, never reverse.
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
        self._llm_calls.append(
            {
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
            }
        )

    def event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Record a simulation event."""
        self._sim_events.append(
            {
                "event_type": event_type,
                "event_data": event_data,
            }
        )

    def flush(self) -> None:
        """Log collected records locally. No longer POSTs to orchestrator.

        Dependency arrow is unilateral: orchestrator → histrategy.
        Histrategy does NOT call back to the orchestrator.
        """
        if not self._llm_calls and not self._sim_events:
            return

        llm_count = len(self._llm_calls)
        sim_count = len(self._sim_events)

        # Clear local buffers
        self._llm_calls = []
        self._sim_events = []

        _logger.info(
            f"Turn {self.turn_number}: collected {llm_count} LLM calls + "
            f"{sim_count} sim events (not POSTing to orchestrator)"
        )
