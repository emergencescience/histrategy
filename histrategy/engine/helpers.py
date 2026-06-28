"""
Engine helper functions and constants extracted from game.py.

Contains:
  - FIRST_TURN_SUGGESTIONS
  - create_initial_world()
  - _suppress_stderr()
  - _inject_v3_into_baseline()
  - _auto_mobilize_for_attack()
  - _build_faction_id_map()
  - _build_territory_id_map()
  - apply_event_effects()
"""

from __future__ import annotations

import os

# ─── v2 engine (always available) ────────────────────────────────
from histrategy_engine import (  # noqa: E402
    WorldState as V2WorldState,
)

from ..state.world_state import (  # noqa: E402
    FactionState,
    WorldState,
    save_world,
)
from .faction_slot import FACTION_LEGACY_MAP as V2_FACTION_MAP  # noqa: F401 — backward compat

# ─── Macro engine: first-turn hard-coded suggestions ───────────
# Skip LLM call on turn 0 — all factions start from the same 207 scenario
# Saves ~18s latency with flash model, ~40s with pro model

FIRST_TURN_SUGGESTIONS = {
    "cao": [
        "【南征荆州】整编水师于邺城玄武池，命于禁毛玠督练，准备南征刘表",
        "【安抚河北】降低冀州税率至20%，安抚新附之民，巩固河北后方",
        "【屯田许昌】在许昌周边推行军屯，储备南征粮草",
        "【劝降孙权】遣使赴江东，以朝廷名义封孙权为讨虏将军，试探其意",
    ],
    "shu": [
        "【三顾茅庐】携关羽张飞再赴隆中，以诚心感动诸葛亮，求问天下大计",
        "【练兵新野】在新野招募训练新兵，扩充军力以备不时之需",
        "【结好刘表】遣简雍赴襄阳，以宗室之谊请求刘表支援粮草军械",
        "【北境设防】命赵云巡视新野北境，设烽火台警戒宛城曹军动向",
    ],
    "wu": [
        "【水军扩建】命周瑜在鄱阳湖大造战船，扩编水军至三万",
        "【稳定山越】派程普鲁肃安抚山越诸部，巩固江东后方",
        "【联刘抗曹】遣鲁肃赴新野，以吊刘表之名探刘备虚实，商议联盟",
        "【发展江东】降低吴郡会稽税率，鼓励农商，充实府库",
    ],
}


def create_initial_world(player_faction_id: str) -> WorldState:
    """Create a fresh world state for a new game (v1).

    Faction data is loaded from the scenario JSON (e.g. 207_liubei.json)
    rather than hardcoded Python dicts.
    """
    from ..engine.log_exporter import clear_session_log
    from .loader import load_scenario, load_territories

    clear_session_log()

    state = WorldState()
    state.scenario = "three-kingdoms"
    state.player_faction_id = player_faction_id

    scenario = load_scenario("three-kingdoms")
    factions_data = scenario.get("factions", {}) if scenario else {}

    for fid, fd in factions_data.items():
        state.factions[fid] = FactionState(
            id=fid,
            name=fd["name"],
            ruler_id=fd.get("ruler", ""),
            capital=fd.get("capital", ""),
            strength=fd.get("strength", 5000),
            economy=fd.get("economy", 50),
            morale=fd.get("morale_actual", 50),
            treasury=fd.get("treasury", 5000),
            food=fd.get("food", 3000),
            territories=list(fd.get("territories", [])),
        )

    # Load territories so build_faction_status_for_api can compute population
    import contextlib

    with contextlib.suppress(Exception):
        state.territories = load_territories("three-kingdoms")

    save_world(state)
    return state


# ─── V2 faction maps ──────────────────────────────────────────────
# (imported at top of file)


def _suppress_stderr():
    """Context manager to suppress stderr during optional LLM calls."""
    import sys as _sys

    class _Suppress:
        def __enter__(self):
            self._stderr = _sys.stderr
            _sys.stderr = open(os.devnull, "w")
            return self

        def __exit__(self, *args):
            _sys.stderr.close()
            _sys.stderr = self._stderr

    return _Suppress()


def _inject_v3_into_baseline(baseline_result, v3_delta: dict) -> None:
    """Inject v3 delta events into baseline for narrative generation."""
    if not hasattr(baseline_result, "character_events"):
        baseline_result.character_events = []
    if not hasattr(baseline_result, "diplomatic_events"):
        baseline_result.diplomatic_events = []

    # Add political events as character/diplomatic events
    for pe in v3_delta.get("political_events", []):
        baseline_result.character_events.append(
            {
                "event": pe.get("type", "court_dispute"),
                "description": pe.get("description", ""),
                "faction": pe.get("faction", ""),
            }
        )

    # Add npc actions as diplomatic events
    for na in v3_delta.get("npc_actions", []):
        baseline_result.diplomatic_events.append(
            {
                "faction": na.get("faction", ""),
                "action": na.get("action", ""),
                "target": na.get("target", ""),
                "reason": na.get("reasoning", ""),
            }
        )

    # Add morale events
    for me in v3_delta.get("morale_events", []):
        baseline_result.character_events.append(
            {
                "event": "morale_change",
                "faction": me.get("faction", ""),
                "change": me.get("change", 0),
                "reason": me.get("reason", ""),
            }
        )


def _auto_mobilize_for_attack(commands: list, world_state) -> None:
    """Auto-mobilize faction reserves for attack commands in v3 mode.

    When a player says "attack with 60K from wancheng" but only 5K army
    exists, transfer faction.strength_actual reserves to the army.
    """
    from histrategy_engine.world import UnitType

    faction = world_state.factions.get(world_state.player_faction_id)
    if not faction:
        return

    for cmd in commands:
        if getattr(cmd, "type", "") != "attack":
            continue
        source = cmd.params.get("source_territory", "")
        requested = cmd.params.get("amount", 0)
        if not source or not requested:
            continue

        army = None
        for a in world_state.armies.values():
            if a.location == source and a.faction_id == world_state.player_faction_id:
                army = a
                break
        if not army:
            continue

        current = army.total_troops
        reserves = faction.strength_actual - current
        needed = min(requested - current, reserves)

        if needed > 0 and needed <= reserves:
            infantry_needed = int(needed * 0.9)
            cavalry_needed = needed - infantry_needed
            army.units[UnitType.INFANTRY] = army.units.get(UnitType.INFANTRY, 0) + infantry_needed
            army.units[UnitType.CAVALRY] = army.units.get(UnitType.CAVALRY, 0) + cavalry_needed
            faction.strength_actual -= needed


def _build_faction_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → faction pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "曹操"),
    annotated names (e.g. "曹操(cao)"), or bare pinyin IDs.
    """
    id_map: dict[str, str] = {}
    for fid, f in ws.factions.items():
        id_map[fid] = fid  # "cao" → "cao"
        if hasattr(f, "name") and f.name:
            id_map[f.name] = fid  # "曹操" → "cao"
    return id_map


def _build_territory_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → territory pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "襄阳"),
    or bare pinyin IDs (e.g. "xiangyang").
    """
    id_map: dict[str, str] = {}
    for tid, t in ws.territories.items():
        id_map[tid] = tid  # "xiangyang" → "xiangyang"
        if hasattr(t, "name") and t.name:
            id_map[t.name] = tid  # "襄阳" → "xiangyang"
    return id_map


def apply_event_effects(world_state: V2WorldState, effects: dict) -> None:
    """Apply the outcomes/effects of a triggered historical event directly to WorldState."""
    from histrategy_engine.world import FactionState

    def transfer_territory(tid: str, fid: str):
        if tid in world_state.territories:
            old_owner_id = world_state.territories[tid].owner_id
            world_state.territories[tid].owner_id = fid
            # Remove from old owner's territories list
            if old_owner_id and old_owner_id in world_state.factions:
                old_faction = world_state.factions[old_owner_id]
                if tid in old_faction.territories:
                    old_faction.territories.remove(tid)
            # Add to new owner's territories list
            if fid and fid in world_state.factions:
                new_faction = world_state.factions[fid]
                if tid not in new_faction.territories:
                    new_faction.territories.append(tid)

    for key, value in effects.items():
        # 1. Advisor joining
        # e.g., "liubei_advisor": "zhugeliang"
        if key.endswith("_advisor") and value and value != "none":
            faction_id = key.split("_")[0]
            faction_id = V2_FACTION_MAP.get(faction_id, faction_id)
            char = world_state.characters.get(value)
            if char:
                char.faction_id = faction_id
                char.loyalty = 95
                char.alive = True
                ruler_id = world_state.factions.get(faction_id, FactionState()).ruler_id
                ruler = world_state.characters.get(ruler_id)
                if ruler:
                    char.location = ruler.location

        # 2. Characters dying/status changes
        # e.g., "guanyu_dead": True, "zhangfei_dead": True
        elif key.endswith("_dead") and value is True:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.alive = False

        # 3. Locations
        # e.g., "liubei_location": "jiangkou"
        elif key.endswith("_location") and value:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.location = value

        # 4. Territory ownership
        # e.g., "jingzhou_owner": "cao" or "liubei" or "sunquan"
        elif key == "jingzhou_owner" and value:
            target_fid = V2_FACTION_MAP.get(value, value)
            for tid in ["xiangyang", "jiangling", "jiangxia", "changsha", "lingling", "wuling", "guiyang", "nanyang"]:
                transfer_territory(tid, target_fid)

        # e.g. "liubei_controls": "yizhou"
        elif key.endswith("_controls") and value:
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            if value == "yizhou":
                for tid in ["chengdu", "hanshui", "hanzhong", "ziyang", "baqi"]:
                    transfer_territory(tid, target_fid)
            elif value == "jingzhou":
                for tid in [
                    "xiangyang",
                    "jiangling",
                    "jiangxia",
                    "changsha",
                    "lingling",
                    "wuling",
                    "guiyang",
                    "nanyang",
                ]:
                    transfer_territory(tid, target_fid)

        # e.g., "liubei_territories_add": ["wuling", "changsha", "lingling", "guiyang"]
        elif key.endswith("_territories_add") and isinstance(value, list):
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            for tid in value:
                transfer_territory(tid, target_fid)

        # 5. Relations
        # e.g., "sunliu_relation": "+20" or "-10"
        elif key.endswith("_relation") and value:
            f1_f2 = key.rsplit("_", 1)[0]
            f1, f2 = None, None
            if "sunliu" in f1_f2 or "sun_liu" in f1_f2:
                f1, f2 = "wu", "shu"
            if f1 and f2:
                try:
                    delta = int(value)
                    fac1 = world_state.factions.get(f1)
                    if fac1:
                        fac1.relations[f2] = max(-100, min(100, fac1.relations.get(f2, 0) + delta))
                    fac2 = world_state.factions.get(f2)
                    if fac2:
                        fac2.relations[f1] = max(-100, min(100, fac2.relations.get(f1, 0) + delta))
                except Exception:
                    pass

        # 6. Army/Power losses
        elif key.endswith("_army") and value == "devastated":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.3))
        elif key.endswith("_power") and value == "crippled":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.4))
                faction.treasury = max(500, int(faction.treasury * 0.5))
                faction.food = max(500, int(faction.food * 0.5))
