"""
Fast-Path Deterministic Simulation Engine.

Replaces V1 LLM simulation when player clicks a suggestion package.
Runs in <1ms using formula-based combat/economy/morale resolution.

Supports: nanming scenario × 4 factions (nanming, qing, nongminjun, zheng).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("histrategy.fast_path")

# ── ID extraction ────────────────────────────────────────────


def extract_suggestion_id(decision: str) -> str | None:
    """Extract [suggestion_id] prefix from a decision string."""
    m = re.match(r'^\[([a-z_]+_t\d_\w+)\]', decision)
    return m.group(1) if m else None


def _parse_player_faction(suggestion_id: str) -> str:
    """Extract player faction from suggestion ID.
    
    e.g. "nanming_t1_defend" → "nanming"
         "qing_t2_storm" → "qing"
         "nongmin_t1_revolt" → "nongminjun"
         "zheng_t1_maritime" → "zheng"
    """
    prefix = suggestion_id.split("_")[0]
    # Normalize: "nongmin_t1_*" → faction is "nongminjun"
    if prefix == "nongmin":
        return "nongminjun"
    return prefix


# ── Faction metadata ─────────────────────────────────────────

_FACTION_ZH = {
    "nanming": "南明",
    "qing": "大清",
    "nongminjun": "农民军",
    "zheng": "郑氏",
}

_FACTION_EN = {
    "nanming": "Southern Ming",
    "qing": "Qing Empire",
    "nongminjun": "Peasant Army",
    "zheng": "Zheng Clan",
}

_FACTION_DEFAULT_TERRITORIES = {
    "nanming": ["nanjing", "zhejiang", "jiangxi", "huguang", "shandong", "henan"],
    "qing": ["beijing", "shengjing", "shanxi", "shaanxi", "gansu"],
    "nongminjun": ["sichuan", "xiangyang"],
    "zheng": ["fujian", "guangdong", "guangxi", "taiwan"],
}

# Which territories an aggressive faction targets when attacking each player
_FACTION_ATTACK_TARGETS = {
    "qing": {
        "nanming": ["shandong", "henan"],
        "nongminjun": ["xiangyang", "sichuan"],
        "zheng": ["fujian"],
    },
    "nanming": {
        "qing": ["shandong", "henan"],
        "nongminjun": ["xiangyang"],
        "zheng": ["fujian"],
    },
    "nongminjun": {
        "qing": ["shaanxi", "gansu"],
        "nanming": ["huguang", "henan"],
        "zheng": ["guangdong"],
    },
    "zheng": {
        "qing": ["shandong"],
        "nanming": ["zhejiang", "fujian"],
        "nongminjun": ["guangdong"],
    },
}

# Player package type detection keywords
_DEFENSIVE_KW = ["defend", "hold", "retreat", "relocate", "peace", "sail",
                 "recover", "warlord", "watch", "defend", "taiwan", "submit",
                 "double", "consolidate", "persuade", "serve"]
_AGGRESSIVE_KW = ["ally", "counter", "totalwar", "laststand", "fight",
                  "invade", "storm", "revolt", "raid", "march", "commit",
                  "offensive", "retake", "wait"]
# Default: balanced/diplomatic


# ── NPC package selection ────────────────────────────────────


def _pick_npc_package(faction_id: str, aggression: float, caution: float,
                       diplomacy: float, development: float, is_winning: bool,
                       is_losing: bool) -> int:
    """Deterministically pick which of the 3 packages an NPC faction chooses.

    Returns 0, 1, or 2 (index into the turn's 3 packages).
    """
    scores = [0.0, 0.0, 0.0]
    scores[0] += aggression * 2.0
    scores[2] += caution * 2.0
    scores[1] += diplomacy * 2.0
    scores[1] += development * 1.5

    if is_winning:
        scores[0] += 1.5
        scores[2] -= 1.0
    if is_losing:
        scores[2] += 1.5
        scores[0] -= 1.0

    return max(range(3), key=lambda i: scores[i])


# ── Deterministic combat resolution ──────────────────────────


def _resolve_combat(attacker_troops: int, defender_troops: int,
                    is_south_of_yangtze: bool = False,
                    defender_dug_in: bool = False) -> dict:
    """Resolve a single battle deterministically."""
    effective_defender = defender_troops
    if is_south_of_yangtze:
        effective_defender = int(defender_troops * 1.5)
    if defender_dug_in:
        effective_defender = int(effective_defender * 1.3)

    ratio = attacker_troops / max(effective_defender, 1)

    if ratio >= 3.0:
        return {
            "won": True, "city_falls": True, "siege_only": False,
            "attacker_losses": int(attacker_troops * 0.05),
            "defender_losses": int(defender_troops * 0.30),
        }
    if ratio >= 1.5:
        return {
            "won": True, "city_falls": False, "siege_only": True,
            "attacker_losses": int(attacker_troops * 0.03),
            "defender_losses": int(defender_troops * 0.10),
        }
    return {
        "won": False, "city_falls": False, "siege_only": False,
        "attacker_losses": int(attacker_troops * 0.08),
        "defender_losses": int(defender_troops * 0.05),
    }


# ── Territory Chinese names ──────────────────────────────────
_TERRITORY_ZH = {
    "shandong": "山东", "henan": "河南", "nanjing": "南京",
    "zhejiang": "浙江", "jiangxi": "江西", "huguang": "湖广",
    "fujian": "福建", "guangdong": "广东", "guangxi": "广西",
    "yunnan": "云南", "sichuan": "四川", "beijing": "北京",
    "shengjing": "盛京", "shanxi": "山西", "shaanxi": "陕西",
    "gansu": "甘肃", "yangzhou": "扬州", "xiangyang": "襄阳",
    "taiwan": "台湾",
}

_YANGTZE_SOUTH = {"nanjing", "zhejiang", "jiangxi", "huguang",
                  "yangzhou", "fujian", "guangdong", "taiwan"}


# ── Main simulation ──────────────────────────────────────────


def simulate_fast_path(room, player_decision: str,
                       player_suggestion_id: str) -> dict:
    """Run deterministic fast-path simulation for any faction.

    Args:
        room: GameRoom object with current world state
        player_decision: Full decision text (for narrative extraction)
        player_suggestion_id: e.g. "nanming_t1_defend", "qing_t2_storm"

    Returns:
        dict matching the CommandResponse format.
    """
    player_fid = _parse_player_faction(player_suggestion_id)

    ws = getattr(room, 'world_state', None)
    if ws is None:
        raise ValueError("Room has no world_state — has the game been started?")

    # ── Load faction data from world state ──
    factions = {}
    for fid, f in ws.factions.items():
        factions[fid] = {
            "troops": getattr(f, 'strength_actual', getattr(f, 'strength', 10000)),
            "morale": getattr(f, 'morale_actual', getattr(f, 'morale', 50)),
            "food": getattr(f, 'food', 10000),
            "treasury": getattr(f, 'treasury', 10000),
            "territories": list(getattr(f, 'territories', [])),
            "aggression": getattr(f, 'aggression', 0.5),
            "caution": getattr(f, 'caution', 0.5),
            "diplomacy": getattr(f, 'diplomacy', 0.5),
            "development": getattr(f, 'development_focus', 0.5),
            "is_active": getattr(f, 'is_active', True),
            "name": getattr(f, 'name', _FACTION_ZH.get(fid, fid)),
        }

    turn = (room.quarter_number or 0) + 1

    # ── Determine NPC package choices ──
    npc_choices = {}
    for fid in list(factions.keys()):
        if fid == player_fid:
            continue
        f = factions[fid]
        if not f["is_active"]:
            continue
        avg_terr = sum(len(f2["territories"]) for f2 in factions.values()) / max(len(factions), 1)
        is_winning = len(f["territories"]) > avg_terr * 1.3
        is_losing = len(f["territories"]) < avg_terr * 0.7
        idx = _pick_npc_package(
            fid, f["aggression"], f["caution"],
            f["diplomacy"], f["development"],
            is_winning, is_losing,
        )
        npc_choices[fid] = idx

    # ── Determine player stance ──
    is_player_defensive = any(kw in player_suggestion_id for kw in _DEFENSIVE_KW)
    is_player_aggressive = any(kw in player_suggestion_id for kw in _AGGRESSIVE_KW)

    # ── Combat: each hostile NPC may attack the player ──
    events = []
    state_changes = {}
    npc_actions = []

    for enemy_fid, choice_idx in npc_choices.items():
        if choice_idx != 0:
            continue  # Only aggressive NPCs (package 0) attack

        # Determine attack targets from the lookup table
        targets = _FACTION_ATTACK_TARGETS.get(enemy_fid, {}).get(player_fid, [])
        if not targets:
            continue

        player_territories = factions[player_fid]["territories"]
        for target in targets:
            if target not in player_territories:
                continue  # Already controlled by attacker or another faction

            atk_ratio = 0.4 if choice_idx == 0 else 0.25
            atk = int(factions[enemy_fid]["troops"] * atk_ratio)
            def_troops = int(factions[player_fid]["troops"] / max(len(player_territories), 1))
            is_south = target in _YANGTZE_SOUTH

            result = _resolve_combat(atk, def_troops, is_south,
                                     defender_dug_in=is_player_defensive)

            target_zh = _TERRITORY_ZH.get(target, target)
            enemy_zh = _FACTION_ZH.get(enemy_fid, enemy_fid)

            if result["city_falls"]:
                factions[enemy_fid]["territories"].append(target)
                player_territories.remove(target)
                events.append(f"{enemy_zh}攻陷{target_zh}")
                state_changes[target] = enemy_fid
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["morale"] -= 8
                factions[enemy_fid]["morale"] += 3
                if is_south:
                    factions[enemy_fid]["morale"] -= 3
            elif result["siege_only"]:
                events.append(f"{enemy_zh}围困{target_zh}")
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["food"] -= int(factions[player_fid]["food"] * 0.15)
                factions[player_fid]["morale"] -= 3
            else:
                events.append(f"{_FACTION_ZH.get(player_fid, player_fid)}守住{target_zh}")
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["morale"] += 5

            break  # One attack per NPC faction per turn

    # Also: if player is aggressive, they may attack an enemy's border territory
    if is_player_aggressive:
        _try_player_counterattack(player_fid, factions, npc_choices, events, state_changes)

    # ── Apply player domestic/economic effects (faction-agnostic) ──
    pf = factions[player_fid]
    if is_player_defensive:
        pf["food"] += int(pf["food"] * 0.05)
        pf["morale"] += 2
    elif is_player_aggressive:
        pf["treasury"] -= int(pf["treasury"] * 0.08)
        pf["morale"] += 3
    else:
        # Balanced/diplomatic
        pf["treasury"] += int(pf["treasury"] * 0.03)
        pf["morale"] += 1

    # ── Natural attrition (all factions) ──
    for fid in factions:
        factions[fid]["troops"] = max(1000, int(factions[fid]["troops"] * 0.97))
        factions[fid]["food"] = max(500, int(factions[fid]["food"] * 0.95))
        factions[fid]["morale"] = max(10, min(100, factions[fid]["morale"]))

    # ── NPC faction actions summary ──
    for fid, idx in npc_choices.items():
        npc_actions.append(_build_npc_action(fid, idx, factions, player_fid, events))

    # ── Advance season ──
    seasons = ["spring", "summer", "autumn", "winter"]
    season_idx = seasons.index(room.season) if room.season in seasons else 0
    new_season_idx = (season_idx + 1) % 4
    new_year = room.year + 1 if new_season_idx == 0 else room.year
    new_season = seasons[new_season_idx]

    season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
    season_str = season_zh.get(new_season, new_season)

    narrative = _build_narrative(player_fid, player_suggestion_id, events, factions, season_str)
    aftermath = f"公元{new_year}年{season_str}。{'、'.join(events) if events else '各方按兵不动，局势暂时平稳。'}"

    pf = factions[player_fid]
    return {
        "game_id": room.id,
        "narrative": narrative,
        "aftermath": aftermath,
        "state_changes": state_changes,
        "events_occurred": events,
        "npc_actions": npc_actions,
        "new_suggestions": _get_next_suggestions(
            room.scenario or "nanming", player_fid, turn, "zh"),
        "game_over": None,
        "faction_status": {
            "name": _FACTION_ZH.get(player_fid, player_fid),
            "faction_id": player_fid,
            "strength": pf["troops"],
            "food": pf["food"],
            "treasury": pf["treasury"],
            "morale": pf["morale"],
            "territories": pf["territories"],
            "is_active": True,
            "year": new_year,
            "season": season_zh.get(new_season, new_season),
            "turn": turn,
        },
        "year": new_year,
        "season": new_season,
        "turn": turn,
    }


def _try_player_counterattack(player_fid: str, factions: dict,
                               npc_choices: dict, events: list,
                               state_changes: dict):
    """If player is aggressive, they attempt to capture an enemy border territory."""
    player_territories = set(factions[player_fid]["territories"])

    # Find weakest enemy with a border territory
    best_target = None
    best_enemy = None
    best_defense = float('inf')

    for enemy_fid in npc_choices:
        enemy_targets = _FACTION_ATTACK_TARGETS.get(player_fid, {}).get(enemy_fid, [])
        for t in enemy_targets:
            enemy_territories = factions[enemy_fid]["territories"]
            if t not in enemy_territories:
                continue
            def_troops = int(factions[enemy_fid]["troops"] / max(len(enemy_territories), 1))
            if def_troops < best_defense:
                best_defense = def_troops
                best_target = t
                best_enemy = enemy_fid

    if not best_target:
        return

    atk = int(factions[player_fid]["troops"] * 0.3)
    result = _resolve_combat(atk, int(best_defense),
                              best_target in _YANGTZE_SOUTH, defender_dug_in=False)

    target_zh = _TERRITORY_ZH.get(best_target, best_target)
    player_zh = _FACTION_ZH.get(player_fid, player_fid)
    enemy_zh = _FACTION_ZH.get(best_enemy, best_enemy)

    if result["city_falls"]:
        factions[player_fid]["territories"].append(best_target)
        factions[best_enemy]["territories"].remove(best_target)
        events.append(f"{player_zh}攻陷{target_zh}")
        state_changes[best_target] = player_fid
        factions[player_fid]["troops"] -= result["attacker_losses"]
        factions[best_enemy]["troops"] -= result["defender_losses"]
        factions[player_fid]["morale"] += 5
        factions[best_enemy]["morale"] -= 8
    elif result["siege_only"]:
        events.append(f"{player_zh}围困{target_zh}")
        factions[player_fid]["troops"] -= result["attacker_losses"]
        factions[best_enemy]["troops"] -= result["defender_losses"]


# ── NPC action narrative builder ─────────────────────────────


def _build_npc_action(fid: str, package_idx: int, factions: dict,
                      player_fid: str, events: list) -> str:
    """Build a context-aware NPC action description."""
    fname = _FACTION_ZH.get(fid, fid)
    fdata = factions.get(fid, {})
    f_troops = fdata.get("troops", 0)

    # Check if this NPC had combat events
    npc_events = [e for e in events if fname in e]
    had_conquest = any("攻陷" in e for e in npc_events)
    had_siege = any("围困" in e for e in npc_events)
    was_repelled = any("守住" in e for e in npc_events)

    if fid == "qing":
        return _npc_qing(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
    elif fid == "nongminjun":
        return _npc_nongmin(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
    elif fid == "zheng":
        return _npc_zheng(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
    elif fid == "nanming":
        return _npc_nanming(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
    else:
        return f"{fname}：兵力{f_troops//1000}K，按兵不动。"


def _npc_qing(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"大清：多尔衮令八旗主力南下，已破数城，清军乘胜追击，兵锋直指江南。"
        elif siege:
            return f"大清：清军兵临城下，围而不攻，意图断绝城中粮道。八旗铁骑在城外扎营。"
        else:
            return f"大清：多尔衮调集八旗精锐南征，铁骑所过之处烟尘蔽日。然守军据城死守，攻势受阻。"
    elif idx == 1:
        return f"大清：多尔衮稳健推进，一面加紧围城一面遣使招降，以威慑江南士绅。"
    else:
        return f"大清：清军暂缓攻势，在已占领土推行圈地与剃发令，巩固后方统治。"


def _npc_nongmin(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"农民军：李自成率大顺军趁机攻城掠地，军威大振，兵力{troops//1000}K。"
        else:
            return f"农民军：李自成率大顺军余部东出，趁乱攻城掠地，兵力{troops//1000}K，然军纪涣散。"
    elif idx == 1:
        return f"农民军：观望时局，李自成遣使与各方周旋，寻求利益最大化。"
    else:
        return f"农民军：固守川中，李自成秣马厉兵，休养生息以待天时。"


def _npc_zheng(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"郑氏：郑成功率水师突袭沿海，千艘战船攻占城池，福建水师声威大震。"
        else:
            return f"郑氏：郑成功率水师北上，千艘战船游弋于沿海，然陆上兵力有限。"
    elif idx == 1:
        return f"郑氏：郑氏利用海上贸易积累财富，郑成功以商养战，同时遣使联络各方势力。"
    else:
        return f"郑氏：郑成功退守福建沿海，以水师屏障确保海洋退路，积蓄力量。"


def _npc_nanming(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"南明：史可法督师北伐，收复失地，朝廷上下士气大振。"
        elif siege:
            return f"南明：四镇出兵北伐，围困清军城池，欲收复中原。"
        else:
            return f"南明：史可法督师扬州，四镇兵马严阵以待，然军中派系林立军令难一。"
    elif idx == 1:
        return f"南明：弘光朝廷遣使四方，一面备战一面寻求外交途径。"
    else:
        return f"南明：朝廷内部党争不休，四镇各怀异心，史可法独木难支。"


# ── Narrative builder ────────────────────────────────────────


def _build_narrative(player_fid: str, suggestion_id: str, events: list,
                     factions: dict, season: str) -> str:
    """Build faction-specific narrative from simulation results."""
    pf = factions.get(player_fid, {})
    faction_zh = _FACTION_ZH.get(player_fid, player_fid)
    territories_count = len(pf.get("territories", []))

    # Check what happened
    player_lost = [e for e in events if "攻陷" in e and faction_zh not in e.split("攻陷")[0]]
    player_gained = [e for e in events if "攻陷" in e and faction_zh in e.split("攻陷")[0]]
    player_sieged = [e for e in events if "围困" in e and faction_zh not in e.split("围困")[0]]
    player_held = [e for e in events if "守住" in e and faction_zh in e]

    parts = []

    # Faction-specific intro
    intros = {
        "nanming": f"弘光元年{season}，",
        "qing": f"顺治二年{season}，",
        "nongminjun": f"永昌二年{season}，",
        "zheng": f"隆武元年{season}，",
    }
    parts.append(intros.get(player_fid, f"{faction_zh}{season}，"))

    # Action description based on package type
    if "defend" in suggestion_id or "hold" in suggestion_id:
        parts.append(f"{faction_zh}加固防线，坚守阵地。")
    elif "retreat" in suggestion_id or "relocate" in suggestion_id or "sail" in suggestion_id:
        parts.append(f"{faction_zh}保存实力，战略转移。")
    elif any(kw in suggestion_id for kw in ["ally", "counter", "invade", "storm", "march",
                                              "commit", "offensive", "retake"]):
        parts.append(f"{faction_zh}主动出击，先发制人。")
    elif any(kw in suggestion_id for kw in ["recover", "trade", "buildup", "consolidate"]):
        parts.append(f"{faction_zh}休养生息，积蓄力量。")
    else:
        parts.append(f"{faction_zh}审时度势，发布诏令。")

    if player_lost:
        lost_cities = [e.split("攻陷")[1] for e in player_lost if "攻陷" in e and len(e.split("攻陷")) > 1]
        if lost_cities:
            parts.append(f"{'、'.join(lost_cities)}失陷，前线告急。")

    if player_gained:
        gained_cities = [e.split("攻陷")[1] for e in player_gained if "攻陷" in e and len(e.split("攻陷")) > 1]
        if gained_cities:
            parts.append(f"攻克{'、'.join(gained_cities)}，军威大振。")

    if player_sieged:
        sieged = [e.split("围困")[1] for e in player_sieged if "围困" in e and len(e.split("围困")) > 1]
        if sieged:
            parts.append(f"{'、'.join(sieged)}被围，粮道断绝。")

    if player_held:
        held = [e.split("守住")[1] for e in player_held if "守住" in e and len(e.split("守住")) > 1]
        if held:
            parts.append(f"{'、'.join(held)}防线稳固，士气大振。")

    # State summary
    parts.append(
        f"{faction_zh}尚有{pf.get('morale', 50)}点民心、"
        f"{pf.get('troops', 0)}兵马、"
        f"{territories_count}座城池。"
    )

    return "".join(parts)


# ── Next-turn suggestions ────────────────────────────────────


def _get_next_suggestions(scenario: str, faction_id: str, turn: int,
                           lang: str) -> list[str]:
    """Get suggestions for next turn from EARLY_TURNS_SUGGESTIONS."""
    try:
        from histrategy.engine.helpers import EARLY_TURNS_SUGGESTIONS
        data = EARLY_TURNS_SUGGESTIONS.get(scenario, {}).get(faction_id, {})
        # turn = current turn being resolved (quarter_number + 1).
        # We need suggestions for the NEXT turn.
        next_turn = min(turn + 1, 4)
        turn_data = data.get(next_turn, {})
        return turn_data.get(lang, [])
    except Exception:
        return []


# ── Quick path detection ─────────────────────────────────────


def should_use_fast_path(decision: str) -> bool:
    """Check if a decision qualifies for fast-path simulation."""
    sid = extract_suggestion_id(decision)
    return sid is not None
