"""OfflineSimEngine — wraps offline_sim.py as a WorldSimEngine plugin."""

from __future__ import annotations

import copy

from .faction_slot import normalize_faction_id as _normalize
from ..engine.offline_sim import simulate_turn_offline
from ..engine.world import GameWorld
from ..engine.world_sim_interface import SimResult, WorldSimEngine
from ..state.world_state import WorldState, save_world

# ── Legacy offline_sim.py 使用的 faction_id 格式 ──
# offline_sim.py 内部使用旧格式 (liu_biao, yuan_shao, caocao, liubei...)，
# 这些映射桥接 canonical 短码 (cao, shu, liubiao, yuanshao) 与旧格式。
_STATE_TO_LEGACY: dict[str, str] = {
    "liubiao": "liu_biao",
    "yuanshao": "yuan_shao",
}
_LEGACY_TO_STATE: dict[str, str] = {
    "caocao": "cao",
    "liubei": "shu",
    "sunjian": "wu",
    "yuanshao": "yuanshao",
    "liu_biao": "liubiao",
    "liubiao": "liubiao",
    **{v: k for k, v in _STATE_TO_LEGACY.items()},
}


def _to_legacy_id(fid: str) -> str:
    """Canonical ID → legacy offline_sim ID."""
    return _STATE_TO_LEGACY.get(fid, fid)


def _from_legacy_id(fid: str) -> str:
    """Legacy offline_sim ID → canonical ID."""
    return _LEGACY_TO_STATE.get(fid, fid)


class OfflineSimEngine(WorldSimEngine):
    """Offline fallback simulation engine.

    Always available — no API key required. Uses rule-based knowledge-driven
    simulation from offline_sim.py. Lower narrative quality than LLMSimEngine
    but guaranteed to work.
    """

    def __init__(self):
        self._legacy_world: GameWorld | None = None

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
        if self._legacy_world is None:
            self._legacy_world = GameWorld(
                scenario=state.scenario or "three-kingdoms"
            )

        legacy_world = self._legacy_world
        legacy_world.current_year = state.year
        legacy_world.current_season = state.current_season
        try:
            legacy_world.season_index = legacy_world.seasons.index(
                state.current_season
            )
        except ValueError:
            legacy_world.season_index = 0
        legacy_world.turn_count = state.turn
        legacy_world.player_faction_id = _to_legacy_id(
            _normalize(state.player_faction_id)
        )

        # Sync faction stats to legacy world
        for fid, state_faction in state.factions.items():
            legacy_fid = _to_legacy_id(_normalize(fid))
            legacy_faction = legacy_world.factions.get(legacy_fid)
            if not legacy_faction:
                for k, v in _LEGACY_TO_STATE.items():
                    if v == legacy_fid or _to_legacy_id(v) == legacy_fid:
                        legacy_faction = legacy_world.factions.get(k)
                        break
            if legacy_faction:
                legacy_faction.strength = state_faction.strength
                legacy_faction.economy = state_faction.economy
                legacy_faction.morale = state_faction.morale
                legacy_faction.treasury = state_faction.treasury
                legacy_faction.food = state_faction.food

        # Run offline simulation
        result = simulate_turn_offline(legacy_world, player_action)

        # Advance turns
        legacy_world.advance_turn()

        # Create updated WorldState
        new_state = copy.deepcopy(state)
        new_state.year = legacy_world.current_year
        new_state.season_index = {
            "spring": 0,
            "summer": 1,
            "autumn": 2,
            "winter": 3,
        }.get(legacy_world.current_season, 0)
        new_state.turn = legacy_world.turn_count

        # Sync legacy faction stats back to WorldState
        for legacy_fid, legacy_faction in legacy_world.factions.items():
            state_fid = _from_legacy_id(legacy_fid)
            if state_fid in new_state.factions:
                sf = new_state.factions[state_fid]
                sf.strength = legacy_faction.strength
                sf.economy = legacy_faction.economy
                sf.morale = legacy_faction.morale
                sf.treasury = legacy_faction.treasury
                sf.food = legacy_faction.food

        save_world(new_state)

        return SimResult(
            narrative=result.get(
                "narrative", f"政令「{player_action[:60]}」已下达。"
            ),
            aftermath=result.get(
                "aftermath", f"政令「{player_action[:60]}」已下达。"
            ),
            npc_reactions=result.get(
                "npc_actions",
                result.get(
                    "npc_reactions", ["各方势力继续行动，天下纷争不休。"]
                ),
            ),
            engine_id=self.engine_id,
            used_llm=False,
            world_state=new_state,
        )
