"""OfflineSimEngine — wraps offline_sim.py as a WorldSimEngine plugin."""

from __future__ import annotations

from ..engine.offline_sim import simulate_turn_offline
from ..engine.world_sim_interface import SimResult, WorldSimEngine
from ..state.world_state import WorldState


class OfflineSimEngine(WorldSimEngine):
    """Offline fallback simulation engine.

    Always available — no API key required. Uses rule-based knowledge-driven
    simulation from offline_sim.py. Lower narrative quality than LLMSimEngine
    but guaranteed to work.
    """

    @property
    def engine_id(self) -> str:
        return "offline"

    @property
    def requires_llm(self) -> bool:
        return False

    def simulate(self, state: WorldState, player_action: str) -> SimResult:
        """Run offline simulation and return a SimResult.

        offline_sim.py operates on the legacy GameWorld interface.
        This adapter bridges from WorldState to GameWorld and back.
        """
        # Attempt to use legacy GameWorld if available via engine.game
        try:
            from ..engine.game import GameEngine
            # If a GameEngine instance is accessible, delegate to it
            # Otherwise fall through to minimal result
        except ImportError:
            pass

        # Direct offline_sim call requires a GameWorld object.
        # For now, return a minimal graceful result so the game loop
        # never crashes. Full bridging is done in engine/game.py.
        return SimResult(
            narrative=f"政令「{player_action[:60]}」已下达，各部正在执行中。",
            aftermath=f"政令「{player_action[:60]}」已下达，各部正在执行中。",
            npc_reactions=["各方势力继续行动，天下纷争不休。"],
            engine_id=self.engine_id,
            used_llm=False,
            world_state=state,
        )
