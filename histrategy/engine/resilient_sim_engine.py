"""ResilientSimEngine — auto-fallback from LLM to offline.

This is the engine the game loop should use in production.
It transparently handles LLM API failures by falling back to OfflineSimEngine.
No UI code or game logic changes are needed to handle API outages.
"""

from __future__ import annotations

import logging

from ..engine.offline_sim_engine import OfflineSimEngine
from ..engine.world_sim_interface import SimResult, WorldSimEngine
from ..state.world_state import WorldState

logger = logging.getLogger(__name__)


class ResilientSimEngine(WorldSimEngine):
    """Wraps a primary engine with automatic fallback to OfflineSimEngine.

    Usage:
        from histrategy.llm.adapter import LLMAdapter
        from histrategy.llm.llm_sim_engine import LLMSimEngine
        from histrategy.engine.resilient_sim_engine import ResilientSimEngine

        adapter = LLMAdapter()
        engine = ResilientSimEngine(LLMSimEngine(adapter))

    The game loop calls engine.simulate() without worrying about API availability.
    """

    def __init__(
        self,
        primary: WorldSimEngine,
        fallback: WorldSimEngine | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback or OfflineSimEngine()

    @property
    def engine_id(self) -> str:
        return f"resilient({self._primary.engine_id})"

    @property
    def requires_llm(self) -> bool:
        return False  # Always has a non-LLM fallback

    def simulate(self, state: WorldState, player_action: str) -> SimResult:
        """Try primary engine; fall back to offline on any failure."""
        # Health check before committing to primary
        if self._primary.requires_llm and not self._primary.health_check():
            logger.warning(
                "Primary engine %s unavailable, using fallback %s",
                self._primary.engine_id,
                self._fallback.engine_id,
            )
            result = self._fallback.simulate(state, player_action)
            result.narrative = f"[离线模式] {result.narrative}"
            return result

        try:
            return self._primary.simulate(state, player_action)
        except Exception as exc:
            logger.warning(
                "Primary engine %s failed (%s), using fallback %s",
                self._primary.engine_id,
                exc,
                self._fallback.engine_id,
            )
            result = self._fallback.simulate(state, player_action)
            result.narrative = f"[离线模式] {result.narrative}"
            return result
