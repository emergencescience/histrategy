"""LLMSimEngine — wraps GameMaster as a WorldSimEngine plugin."""

from __future__ import annotations

from pathlib import Path
from ..engine.world_sim_interface import SimResult, WorldSimEngine
from ..state.world_state import WorldState
from ..engine.narrative_director import NarrativeDirector
from .adapter import LLMAdapter
from .game_master import GameMaster


class LLMSimEngine(WorldSimEngine):
    """Primary simulation engine: LLM-powered via GameMaster.

    Requires a live LLM API key. Falls back to OfflineSimEngine via
    ResilientSimEngine when unavailable.
    """

    def __init__(self, adapter: LLMAdapter) -> None:
        self._gm = GameMaster(adapter)
        self._adapter = adapter
        arc_path = Path(__file__).parent.parent / "knowledge" / "data" / "arc_goals.json"
        self._narrative_director = NarrativeDirector.from_json(arc_path)

    @property
    def engine_id(self) -> str:
        return "llm"

    @property
    def requires_llm(self) -> bool:
        return True

    def health_check(self) -> bool:
        """Check if LLM API is reachable."""
        try:
            return self._adapter.is_available()
        except Exception:
            return False

    def simulate(self, state: WorldState, player_action: str) -> SimResult:
        """Run Command Mode and return a SimResult."""
        pressure_hint = self._narrative_director.get_pressure_hint(state.turn, state.player_deviation)
        result = self._gm.generate_command_mode(state, player_action, pressure_hint=pressure_hint)
        
        # Mark completed events
        updated_state = result.get("world_state", state)
        if updated_state and updated_state.completed_events:
            for ev in updated_state.completed_events:
                self._narrative_director.mark_completed(ev)

        return SimResult(
            narrative=result.get("aftermath", ""),
            aftermath=result.get("aftermath", ""),
            bureaucracy=result.get("bureaucracy", []),
            short_term=result.get("short_term", {"changes": {}}),
            state_changes=result.get("state_changes", {}),
            seeds=result.get("seeds", []),
            npc_reactions=result.get("npc_reactions", []),
            game_over=None,
            world_state=updated_state,
            engine_id=self.engine_id,
            used_llm=True,
        )

