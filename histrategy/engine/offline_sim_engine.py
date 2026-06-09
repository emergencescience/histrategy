"""OfflineSimEngine — wraps offline_sim.py as a WorldSimEngine plugin."""

from __future__ import annotations

import copy
from ..engine.offline_sim import simulate_turn_offline
from ..engine.world_sim_interface import SimResult, WorldSimEngine
from ..state.world_state import WorldState, save_world
from ..engine.world import GameWorld


def _map_state_id_to_legacy(fid: str) -> str:
    mapping = {
        "cao": "cao",
        "shu": "shu",
        "wu": "wu",
        "yuan_shao": "yuan_shao",
        "liu_biao": "liu_biao",
    }
    return mapping.get(fid, fid)


def _map_legacy_id_to_state(fid: str) -> str:
    mapping = {
        "caocao": "cao",
        "liubei": "shu",
        "sunjian": "wu",
        "yuanshao": "yuan_shao",
        "liubiao": "liu_biao",
    }
    return mapping.get(fid, fid)


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
            self._legacy_world = GameWorld(scenario=state.scenario or "207")

        # Sync WorldState values to legacy world
        legacy_world = self._legacy_world
        legacy_world.current_year = state.year
        legacy_world.current_season = state.current_season
        # Set current season index
        try:
            legacy_world.season_index = legacy_world.seasons.index(state.current_season)
        except ValueError:
            legacy_world.season_index = 0
        legacy_world.turn_count = state.turn
        legacy_world.player_faction_id = _map_state_id_to_legacy(state.player_faction_id)

        # Sync faction stats to legacy world
        for fid, state_faction in state.factions.items():
            legacy_fid = _map_state_id_to_legacy(fid)
            # Try to match direct ID, otherwise map standard ones
            legacy_faction = legacy_world.factions.get(legacy_fid)
            if not legacy_faction:
                # check mapped names
                for k, v in {"caocao": "cao", "liubei": "shu", "sunjian": "wu", "yuanshao": "yuan_shao", "liubiao": "liu_biao"}.items():
                    if v == legacy_fid:
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

        # Advance turns on both
        legacy_world.advance_turn()

        # Create a copy/update of WorldState
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
        for fid, legacy_faction in legacy_world.factions.items():
            state_fid = _map_legacy_id_to_state(fid)
            if state_fid in new_state.factions:
                state_faction = new_state.factions[state_fid]
                state_faction.strength = legacy_faction.strength
                state_faction.economy = legacy_faction.economy
                state_faction.morale = legacy_faction.morale
                state_faction.treasury = legacy_faction.treasury
                state_faction.food = legacy_faction.food

        save_world(new_state)

        # Wrap into SimResult
        return SimResult(
            narrative=result.get("narrative", f"政令「{player_action[:60]}」已下达。"),
            aftermath=result.get("aftermath", f"政令「{player_action[:60]}」已下达。"),
            npc_reactions=result.get("npc_actions", result.get("npc_reactions", ["各方势力继续行动，天下纷争不休。"])),
            engine_id=self.engine_id,
            used_llm=False,
            world_state=new_state,
        )
