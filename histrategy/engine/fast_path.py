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
                       is_losing: bool, turn: int = 0) -> int:
    """Deterministically pick which of the 3 packages an NPC faction chooses.

    Returns 0, 1, or 2 (index into the turn's 3 packages).
    Uses turn number to vary NPC behavior — prevents identical NPC
    action text across all 4 turns.
    """
    scores = [0.0, 0.0, 0.0]
    scores[0] += aggression * 2.0
    scores[2] += caution * 2.0
    scores[1] += diplomacy * 2.0
    scores[1] += development * 1.5

    if is_winning:
        scores[0] += 2.0
        scores[2] -= 1.5
    if is_losing:
        scores[2] += 2.0
        scores[0] -= 1.5

    # Inject turn-based variance so NPCs don't pick same package every turn.
    # Multi-turn games were showing identical NPC action text for all 4 turns.
    if turn > 0:
        scores[(turn + hash(faction_id)) % 3] += 0.8

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
                       player_suggestion_id: str, lang: str = "zh") -> dict:
    """Run deterministic fast-path simulation for any faction.

    Args:
        room: GameRoom object with current world state
        player_decision: Full decision text (for narrative extraction)
        player_suggestion_id: e.g. "nanming_t1_defend", "qing_t2_storm"
        lang: UI language (zh | en) — drives narrative and suggestion language.

    Returns:
        dict matching the CommandResponse format.
    """
    player_fid = _parse_player_faction(player_suggestion_id)

    ws = getattr(room, 'world_state', None)
    if ws is None:
        raise ValueError("Room has no world_state — has the game been started?")

    # ── Load faction data from world state ──
    factions = {}
    # Pre-compute territory populations from world_state
    _ws_territories = getattr(ws, 'territories', {}) if ws else {}
    _territory_population = {}
    for _tid, _tobj in (_ws_territories.items() if isinstance(_ws_territories, dict) else []):
        _tp = getattr(_tobj, 'population', 0) or 0
        if _tp:
            _territory_population[_tid] = _tp

    for fid, f in ws.factions.items():
        _terrs = list(getattr(f, 'territories', []))
        _pop = sum(_territory_population.get(
            getattr(t, 'id', str(t)) if hasattr(t, 'id') else str(t), 0
        ) for t in _terrs)
        factions[fid] = {
            "troops": getattr(f, 'strength_actual', getattr(f, 'strength', 10000)),
            "morale": getattr(f, 'morale_actual', getattr(f, 'morale', 50)),
            "food": getattr(f, 'food', 10000),
            "treasury": getattr(f, 'treasury', 10000),
            "territories": _terrs,
            "population": _pop,
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
        avg_troops = sum(f2["troops"] for f2 in factions.values()) / max(len(factions), 1)
        # Consider both territory control and military strength
        territory_strong = len(f["territories"]) > avg_terr * 1.2
        military_strong = f["troops"] > avg_troops * 1.2
        is_winning = territory_strong and military_strong
        is_losing = len(f["territories"]) <= 1 or f["troops"] < avg_troops * 0.6
        idx = _pick_npc_package(
            fid, f["aggression"], f["caution"],
            f["diplomacy"], f["development"],
            is_winning, is_losing, turn,
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
                # Transfer territory population
                _tp = _territory_population.get(target, 0)
                factions[enemy_fid]["population"] = factions[enemy_fid].get("population", 0) + _tp
                factions[player_fid]["population"] = max(0, factions[player_fid].get("population", 0) - _tp)
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
                state_changes[target] = f"sieged_by_{enemy_fid}"
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["food"] -= int(factions[player_fid]["food"] * 0.15)
                factions[player_fid]["morale"] -= 3
            else:
                events.append(f"{_FACTION_ZH.get(player_fid, player_fid)}守住{target_zh}")
                state_changes[target] = "defended"
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["morale"] += 5

            break  # One attack per NPC faction per turn

    # Also: if player is aggressive, they may attack an enemy's border territory
    if is_player_aggressive:
        _try_player_counterattack(player_fid, factions, npc_choices, events, state_changes, _territory_population)

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
    npc_decisions: dict[str, str] = {}
    for fid, idx in npc_choices.items():
        action = _build_npc_action(fid, idx, factions, player_fid, events)
        npc_actions.append(action)
        npc_decisions[fid] = action

    # ── Advance season ──
    seasons = ["spring", "summer", "autumn", "winter"]
    season_idx = seasons.index(room.season) if room.season in seasons else 0
    new_season_idx = (season_idx + 1) % 4
    new_year = room.year + 1 if new_season_idx == 0 else room.year
    new_season = seasons[new_season_idx]

    season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
    season_str = season_zh.get(new_season, new_season)

    narrative = _build_rich_narrative(
        player_fid, player_suggestion_id, events, factions, npc_actions, season_str, new_year, lang
    )
    aftermath = f"公元{new_year}年{season_str}。{'、'.join(events) if events else '各方按兵不动，局势暂时平稳。'}"

    pf = factions[player_fid]
    return {
        "game_id": room.id,
        "narrative": narrative,
        "aftermath": aftermath,
        "state_changes": state_changes,
        "events_occurred": events,
        "npc_actions": npc_actions,
        "npc_decisions": npc_decisions,
        "new_suggestions": _get_next_suggestions(
            room.scenario or "nanming", player_fid, turn, lang),
        "game_over": None,
        "faction_status": {
            "name": _FACTION_ZH.get(player_fid, player_fid),
            "faction_id": player_fid,
            "strength": pf["troops"],
            "population": pf.get("population", 0),
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
        "all_factions": factions,  # For world_state sync by caller
    }


def _try_player_counterattack(player_fid: str, factions: dict,
                               npc_choices: dict, events: list,
                               state_changes: dict,
                               territory_population: dict | None = None):
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
        # Transfer territory population
        _tp = (territory_population or {}).get(best_target, 0)
        factions[player_fid]["population"] = factions[player_fid].get("population", 0) + _tp
        factions[best_enemy]["population"] = max(0, factions[best_enemy].get("population", 0) - _tp)
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
            return "大清：多尔衮令八旗主力南下，已破数城，清军乘胜追击，兵锋直指江南。"
        elif siege:
            return "大清：清军兵临城下，围而不攻，意图断绝城中粮道。八旗铁骑在城外扎营。"
        else:
            return "大清：多尔衮调集八旗精锐南征，铁骑所过之处烟尘蔽日。然守军据城死守，攻势受阻。"
    elif idx == 1:
        return "大清：多尔衮稳健推进，一面加紧围城一面遣使招降，以威慑江南士绅。"
    else:
        return "大清：清军暂缓攻势，在已占领土推行圈地与剃发令，巩固后方统治。"


def _npc_nongmin(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"农民军：李自成率大顺军趁机攻城掠地，军威大振，兵力{troops//1000}K。"
        else:
            return f"农民军：李自成率大顺军余部东出，趁乱攻城掠地，兵力{troops//1000}K，然军纪涣散。"
    elif idx == 1:
        return "农民军：观望时局，李自成遣使与各方周旋，寻求利益最大化。"
    else:
        return "农民军：固守川中，李自成秣马厉兵，休养生息以待天时。"


def _npc_zheng(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return "郑氏：郑成功率水师突袭沿海，千艘战船攻占城池，福建水师声威大震。"
        else:
            return "郑氏：郑成功率水师北上，千艘战船游弋于沿海，然陆上兵力有限。"
    elif idx == 1:
        return "郑氏：郑氏利用海上贸易积累财富，郑成功以商养战，同时遣使联络各方势力。"
    else:
        return "郑氏：郑成功退守福建沿海，以水师屏障确保海洋退路，积蓄力量。"


def _npc_nanming(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return "南明：史可法督师北伐，收复失地，朝廷上下士气大振。"
        elif siege:
            return "南明：四镇出兵北伐，围困清军城池，欲收复中原。"
        else:
            return "南明：史可法督师扬州，四镇兵马严阵以待，然军中派系林立军令难一。"
    elif idx == 1:
        return [
            "南明：弘光朝廷遣使四方，一面备战一面寻求外交途径。",
            "南明：朝中主和派力主与清廷划江而治，遣密使北上议和。",
            "南明：史可法力主联寇抗清，遣使联络农民军共商大计。",
        ][hash(f"nanming_d_{troops}") % 3]
    else:
        return [
            "南明：朝廷内部党争不休，四镇各怀异心，史可法独木难支。",
            "南明：江北四镇拥兵自重，左良玉以清君侧为名挥师东下。",
        ][hash(f"nanming_c_{troops}") % 2]


# ── Narrative builder ────────────────────────────────────────


def _build_narrative(player_fid: str, suggestion_id: str, events: list,
                     factions: dict, season: str, year: int = 0,
                     lang: str = "zh") -> str:
    """Build faction-specific narrative from simulation results.

    Args:
        lang: "zh" or "en" — generates narrative in the corresponding language.
    """
    pf = factions.get(player_fid, {})
    faction_name = _FACTION_ZH.get(player_fid, player_fid) if lang == "zh" else _FACTION_EN.get(player_fid, player_fid)
    territories_count = len(pf.get("territories", []))
    morale = pf.get('morale', 50)
    troops = pf.get('troops', 0)

    # Check what happened
    player_lost = [e for e in events if "攻陷" in e and faction_name not in e.split("攻陷")[0]]
    player_gained = [e for e in events if "攻陷" in e and faction_name in e.split("攻陷")[0]]
    player_sieged = [e for e in events if "围困" in e and faction_name not in e.split("围困")[0]]
    player_held = [e for e in events if "守住" in e and faction_name in e]

    # Compute reign year dynamically from actual year
    _REIGN_BASE = {
        "nanming": ("弘光", 1645),
        "qing": ("顺治", 1644),
        "nongminjun": ("永昌", 1644),
        "zheng": ("隆武", 1645),
    }
    _REIGN_EN = {
        "nanming": ("Hongguang", 1645),
        "qing": ("Shunzhi", 1644),
        "nongminjun": ("Yongchang", 1644),
        "zheng": ("Longwu", 1645),
    }
    _CN_NUM = {1: "元", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}

    if lang == "zh":
        _reign_name, _reign_start = _REIGN_BASE.get(player_fid, ("", year))
        if year > 0 and _reign_name:
            _reign_year = max(1, year - _reign_start + 1)
            _reign_label = _CN_NUM.get(_reign_year, str(_reign_year))
            season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
            parts = [f"{_reign_name}{_reign_label}年{season_zh.get(season, season)}，"]
        else:
            parts = [f"{faction_name}{season}，"]
    else:
        _reign_name, _reign_start = _REIGN_EN.get(player_fid, ("", year))
        if year > 0 and _reign_name:
            _reign_year = max(1, year - _reign_start + 1)
            season_en = season.capitalize()
            parts = [f"{_reign_name} {_reign_year}, {season_en}. {faction_name} "]
        else:
            parts = [f"{faction_name} in {season}. "]

    # Action description based on package type
    if lang == "zh":
        if "defend" in suggestion_id or "hold" in suggestion_id:
            parts.append(f"{faction_name}加固防线，坚守阵地。")
        elif "retreat" in suggestion_id or "relocate" in suggestion_id or "sail" in suggestion_id:
            parts.append(f"{faction_name}保存实力，战略转移。")
        elif any(kw in suggestion_id for kw in ["ally", "counter", "invade", "storm", "march",
                                                  "commit", "offensive", "retake"]):
            parts.append(f"{faction_name}主动出击，先发制人。")
        elif any(kw in suggestion_id for kw in ["recover", "trade", "buildup", "consolidate"]):
            parts.append(f"{faction_name}休养生息，积蓄力量。")
        else:
            parts.append(f"{faction_name}审时度势，发布诏令。")

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

        parts.append(
            f"{faction_name}尚有{morale}点民心、"
            f"{troops}兵马、"
            f"{territories_count}座城池。"
        )
    else:
        # English
        if "defend" in suggestion_id or "hold" in suggestion_id:
            parts.append(f"fortified their defenses and held their ground. ")
        elif "retreat" in suggestion_id or "relocate" in suggestion_id or "sail" in suggestion_id:
            parts.append(f"executed a strategic withdrawal to preserve strength. ")
        elif any(kw in suggestion_id for kw in ["ally", "counter", "invade", "storm", "march",
                                                  "commit", "offensive", "retake"]):
            parts.append(f"launched a preemptive strike, seizing the initiative. ")
        elif any(kw in suggestion_id for kw in ["recover", "trade", "buildup", "consolidate"]):
            parts.append(f"focused on recovery and building reserves. ")
        else:
            parts.append(f"assessed the situation and issued decrees. ")

        if player_lost:
            lost_cities = [e.split("攻陷")[1] for e in player_lost if "攻陷" in e and len(e.split("攻陷")) > 1]
            if lost_cities:
                parts.append(f"{', '.join(lost_cities)} fell to the enemy. ")
        if player_gained:
            gained_cities = [e.split("攻陷")[1] for e in player_gained if "攻陷" in e and len(e.split("攻陷")) > 1]
            if gained_cities:
                parts.append(f"Captured {', '.join(gained_cities)}! ")
        if player_sieged:
            sieged = [e.split("围困")[1] for e in player_sieged if "围困" in e and len(e.split("围困")) > 1]
            if sieged:
                parts.append(f"{', '.join(sieged)} under siege. ")
        if player_held:
            held = [e.split("守住")[1] for e in player_held if "守住" in e and len(e.split("守住")) > 1]
            if held:
                parts.append(f"{', '.join(held)} held firm. ")

        parts.append(
            f"{faction_name} has {morale} morale, "
            f"{troops} troops, "
            f"{territories_count} cities."
        )

    return "".join(parts)


def _build_rich_narrative(player_fid: str, suggestion_id: str, events: list,
                          factions: dict, npc_actions: list, season: str,
                          year: int = 0, lang: str = "zh") -> str:
    """Compose a multi-section markdown narrative for a hard-coded (fast-path) turn.

    Even without an LLM call, a fast-path turn should read like a proper chronicle
    (大事纪 / 兵争武事 / 各方动向), so the shared page and game UI look identical to
    LLM turns. Reuses _build_narrative for the opening summary, then appends the
    deterministic events and the hard-coded NPC actions as their own sections.
    """
    base = _build_narrative(player_fid, suggestion_id, events, factions, season, year, lang)
    sections: list[str] = []
    if lang == "zh":
        sections.append("### 大事纪\n" + base)
        if events:
            sections.append("### 兵争武事\n" + "；".join(events) + "。")
        if npc_actions:
            sections.append("### 各方动向\n" + "\n".join(f"- {a}" for a in npc_actions))
    else:
        sections.append("### Chronicle\n" + base)
        if events:
            sections.append("### Military Affairs\n" + "; ".join(events) + ".")
        if npc_actions:
            sections.append("### Factions' Movements\n" + "\n".join(f"- {a}" for a in npc_actions))
    return "\n\n".join(sections)


# ── Next-turn suggestions ────────────────────────────────────


def _get_next_suggestions(scenario: str, faction_id: str, turn: int,
                           lang: str) -> list[str]:
    """Get suggestions for next turn from EARLY_TURNS_SUGGESTIONS.

    After turn 4, returns empty — the guided tutorial phase ends
    and the player should use free-text input (LLM path) for
    richer, context-aware narratives.

    IMPORTANT: The [suggestion_id] prefix (e.g. [nanming_t2_counter])
    MUST be preserved — it is the routing key for fast-path detection.
    The frontend strips it for display via suggestionTitle/suggestionBody.
    """
    # Beyond turn 4: let LLM path take over
    if turn >= 4:
        return []

    try:
        from histrategy.engine.helpers import EARLY_TURNS_SUGGESTIONS
        data = EARLY_TURNS_SUGGESTIONS.get(scenario, {}).get(faction_id, {})
        # turn = current turn being resolved (quarter_number + 1).
        # We need suggestions for the NEXT turn.
        next_turn = turn + 1
        turn_data = data.get(next_turn, {})
        return turn_data.get(lang, [])
    except Exception:
        return []


# ── Quick path detection ─────────────────────────────────────


def should_use_fast_path(decision: str) -> bool:
    """Check if a decision qualifies for fast-path simulation."""
    sid = extract_suggestion_id(decision)
    return sid is not None
