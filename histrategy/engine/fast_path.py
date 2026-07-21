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
    # Rome Triumvirate
    "octavian": "Octavian",
    "antony": "Mark Antony",
    "cleopatra": "Cleopatra VII",
    "senate": "Roman Senate",
    "sextus_pompey": "Sextus Pompey",
    "lepidus": "Lepidus",
    # Three Kingdoms
    "cao": "Cao Cao",
    "shu": "Liu Bei",
    "wu": "Sun Quan",
    "liubiao": "Liu Biao",
    "zhanglu": "Zhang Lu",
    "liuzhang": "Liu Zhang",
    "machao": "Ma Chao",
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
        "nanming": ["kaifeng", "luoyang", "henan_east", "jinan", "dengzhou"],
        "nongminjun": ["xiangyang", "hanzhong", "chengdu"],
        "zheng": ["fujian"],
    },
    "nanming": {
        "qing": ["shanxi", "shaanxi"],
        "nongminjun": ["xiangyang"],
        "zheng": ["fujian"],
    },
    "nongminjun": {
        "qing": ["shaanxi", "gansu"],
        "nanming": ["wuchang", "huguang_west", "kaifeng", "luoyang"],
        "zheng": ["guangdong"],
    },
    "zheng": {
        "qing": ["dengzhou", "jinan"],
        "nanming": ["zhejiang", "fujian"],
        "nongminjun": ["guangdong"],
    },
}

# Player package type detection keywords
_DEFENSIVE_KW = ["defend", "hold", "retreat", "relocate", "peace", "sail",
                 "recover", "warlord", "watch", "defend", "taiwan", "submit",
                 "double", "consolidate", "persuade"]
# "serve" intentionally NOT defensive — 勤王 is active military-loyalty
_ACTIVE_LOYALTY_KW = ["serve", "ally", "rally", "pledge", "commit"]
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

    if ratio >= 2.5:
        return {
            "won": True, "city_falls": True, "siege_only": False,
            "attacker_losses": int(attacker_troops * 0.05),
            "defender_losses": int(defender_troops * 0.30),
        }
    if ratio >= 1.3:
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
    # nanming region split (H22a)
    "wuchang": "武昌", "huguang_west": "湖广西部", "huguang_south": "湖广南部",
    "jinan": "济南", "dengzhou": "登州",
    "kaifeng": "开封", "luoyang": "洛阳", "henan_east": "河南东部",
    "chengdu": "成都", "hanzhong": "汉中",
}

_TERRITORY_EN = {
    "shandong": "Shandong", "henan": "Henan", "nanjing": "Nanjing",
    "zhejiang": "Zhejiang", "jiangxi": "Jiangxi", "huguang": "Huguang",
    "fujian": "Fujian", "guangdong": "Guangdong", "guangxi": "Guangxi",
    "yunnan": "Yunnan", "sichuan": "Sichuan", "beijing": "Beijing",
    "shengjing": "Shengjing", "shanxi": "Shanxi", "shaanxi": "Shaanxi",
    "gansu": "Gansu", "yangzhou": "Yangzhou", "xiangyang": "Xiangyang",
    "taiwan": "Taiwan",
    "wuchang": "Wuchang", "huguang_west": "West Huguang", "huguang_south": "South Huguang",
    "jinan": "Jinan", "dengzhou": "Dengzhou",
    "kaifeng": "Kaifeng", "luoyang": "Luoyang", "henan_east": "East Henan",
    "chengdu": "Chengdu", "hanzhong": "Hanzhong",
}

_YANGTZE_SOUTH = {"nanjing", "zhejiang", "jiangxi",
                  "wuchang", "huguang_west", "huguang_south",
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

    # ── Snapshot pre-simulation state for turn_delta ──
    import copy as _copy
    old_factions: dict[str, dict] = {}
    for _fid, _fd in factions.items():
        old_factions[_fid] = {
            "troops": _fd["troops"],
            "morale": _fd["morale"],
            "food": _fd["food"],
            "treasury": _fd["treasury"],
            "territories": list(_fd.get("territories", [])),
            "population": _fd.get("population", 0),
        }

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
    # Active loyalty actions (serve, rally, pledge) are neither purely defensive
    # nor aggressive — they commit military resources but don't start new fights
    is_player_loyalty = any(kw in player_suggestion_id for kw in _ACTIVE_LOYALTY_KW)

    # ── Combat: each hostile NPC may attack the player ──
    events = []
    state_changes = {}
    npc_actions = []

    # ── Adjust NPC aggression based on player's strategic choice ──
    # When player reinforces defenses or serves loyally, NPCs are less likely to siege
    if is_player_defensive or is_player_loyalty:
        _siege_modifier = 0.5  # 50% less likely to successfully siege
    elif is_player_aggressive:
        _siege_modifier = 1.2  # 20% more likely
    else:
        _siege_modifier = 1.0

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
            # Apply siege modifier: defensive/loyalty choices reduce effective attacker strength
            atk = int(atk * _siege_modifier)
            is_south = target in _YANGTZE_SOUTH

            result = _resolve_combat(atk, def_troops, is_south,
                                     defender_dug_in=is_player_defensive)

            target_zh = _TERRITORY_ZH.get(target, target)
            enemy_zh = _FACTION_ZH.get(enemy_fid, enemy_fid)

            # Localised names
            _enemy_name = _FACTION_EN.get(enemy_fid, enemy_fid) if lang == "en" else enemy_zh
            _target_name = _TERRITORY_EN.get(target, target) if lang == "en" else target_zh
            _player_name = _FACTION_EN.get(player_fid, _FACTION_ZH.get(player_fid, player_fid)) if lang == "en" else _FACTION_ZH.get(player_fid, player_fid)
            if lang == "en":
                _fall_tmpl = "{attacker} captured {target}"
                _siege_tmpl = "{attacker} besieged {target}"
                _held_tmpl = "{defender} held {target}"
            else:
                _fall_tmpl = "{attacker}攻陷{target}"
                _siege_tmpl = "{attacker}围困{target}"
                _held_tmpl = "{defender}守住{target}"

            if result["city_falls"]:
                factions[enemy_fid]["territories"].append(target)
                player_territories.remove(target)
                _tp = _territory_population.get(target, 0)
                factions[enemy_fid]["population"] = factions[enemy_fid].get("population", 0) + _tp
                factions[player_fid]["population"] = max(0, factions[player_fid].get("population", 0) - _tp)
                events.append(_fall_tmpl.format(attacker=_enemy_name, target=_target_name))
                state_changes[target] = enemy_fid
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["morale"] -= 8
                factions[enemy_fid]["morale"] += 3
                if is_south:
                    factions[enemy_fid]["morale"] -= 3
            elif result["siege_only"]:
                events.append(_siege_tmpl.format(attacker=_enemy_name, target=_target_name))
                state_changes[target] = f"sieged_by_{enemy_fid}"
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["food"] -= int(factions[player_fid]["food"] * 0.15)
                factions[player_fid]["morale"] -= 3
            else:
                events.append(_held_tmpl.format(defender=_player_name, target=_target_name))
                state_changes[target] = "defended"
                factions[enemy_fid]["troops"] -= result["attacker_losses"]
                factions[player_fid]["troops"] -= result["defender_losses"]
                factions[player_fid]["morale"] += 5

            break  # One attack per NPC faction per turn

    # Also: if player is aggressive, they may attack an enemy's border territory
    if is_player_aggressive:
        _try_player_counterattack(player_fid, factions, npc_choices, events, state_changes, _territory_population, lang)

    # ── Apply player domestic/economic effects (faction-agnostic) ──
    pf = factions[player_fid]
    if is_player_defensive:
        pf["food"] += int(pf["food"] * 0.05)
        pf["morale"] += 2
    elif is_player_aggressive:
        pf["treasury"] -= int(pf["treasury"] * 0.08)
        pf["morale"] += 3
    elif is_player_loyalty:
        # Loyalty/勤王: costs treasury (tribute/gifts), big morale boost
        pf["treasury"] -= int(pf["treasury"] * 0.05)
        pf["morale"] += 5
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
        action = _build_npc_action(fid, idx, factions, player_fid, events, lang)
        npc_actions.append(action)
        npc_decisions[fid] = action

    # ── Advance season ──
    seasons = ["spring", "summer", "autumn", "winter"]
    season_idx = seasons.index(room.season) if room.season in seasons else 0
    new_season_idx = (season_idx + 1) % 4
    new_year = room.year + 1 if new_season_idx == 0 else room.year
    new_season = seasons[new_season_idx]

    season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
    if lang == "en":
        season_str = new_season.capitalize()
    else:
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
            "name": _FACTION_ZH.get(player_fid, player_fid) if lang == "zh" else _FACTION_EN.get(player_fid, player_fid),
            "faction_id": player_fid,
            "strength": pf["troops"],
            "population": pf.get("population", 0),
            "food": pf["food"],
            "treasury": pf["treasury"],
            "morale": pf["morale"],
            "territories": pf["territories"],
            "is_active": True,
            "year": new_year,
            "season": season_str,
            "turn": turn,
        },
        "year": new_year,
        "season": new_season,
        "turn": turn,
        "all_factions": factions,  # For world_state sync by caller
        "old_factions": old_factions,  # Pre-simulation state for turn_delta
    }


def _try_player_counterattack(player_fid: str, factions: dict,
                               npc_choices: dict, events: list,
                               state_changes: dict,
                               territory_population: dict | None = None,
                               lang: str = "zh"):
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

    # Localised names for counter-attack events
    _p_name = _FACTION_EN.get(player_fid, player_zh) if lang == "en" else player_zh
    _t_name = _TERRITORY_EN.get(best_target, target_zh) if lang == "en" else target_zh
    _e_name = _FACTION_EN.get(best_enemy, enemy_zh) if lang == "en" else enemy_zh
    if result["city_falls"]:
        factions[player_fid]["territories"].append(best_target)
        factions[best_enemy]["territories"].remove(best_target)
        _tp = (territory_population or {}).get(best_target, 0)
        factions[player_fid]["population"] = factions[player_fid].get("population", 0) + _tp
        factions[best_enemy]["population"] = max(0, factions[best_enemy].get("population", 0) - _tp)
        events.append(f"{_p_name} captured {_t_name}" if lang == "en" else f"{_p_name}攻陷{_t_name}")
        state_changes[best_target] = player_fid
        factions[player_fid]["troops"] -= result["attacker_losses"]
        factions[best_enemy]["troops"] -= result["defender_losses"]
        factions[player_fid]["morale"] += 5
        factions[best_enemy]["morale"] -= 8
    elif result["siege_only"]:
        events.append(f"{_p_name} besieged {_t_name}" if lang == "en" else f"{_p_name}围困{_t_name}")
        factions[player_fid]["troops"] -= result["attacker_losses"]
        factions[best_enemy]["troops"] -= result["defender_losses"]


# ── NPC action narrative builder ─────────────────────────────


def _build_npc_action(fid: str, package_idx: int, factions: dict,
                      player_fid: str, events: list, lang: str = "zh") -> str:
    """Build a context-aware NPC action description."""
    fname = _FACTION_ZH.get(fid, fid)
    fdata = factions.get(fid, {})
    f_troops = fdata.get("troops", 0)

    # Check if this NPC had combat events
    npc_events = [e for e in events if fname in e]
    had_conquest = any("攻陷" in e for e in npc_events)
    had_siege = any("围困" in e for e in npc_events)
    was_repelled = any("守住" in e for e in npc_events)

    if lang == "en":
        if fid == "qing":
            return _npc_qing_en(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
        elif fid == "nongminjun":
            return _npc_nongmin_en(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
        elif fid == "zheng":
            return _npc_zheng_en(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
        elif fid == "nanming":
            return _npc_nanming_en(package_idx, f_troops, npc_events, had_conquest, had_siege, was_repelled)
        else:
            return f"{_FACTION_EN.get(fid, fid)}: {f_troops//1000}K troops standing by."
    else:
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


# ── English NPC action texts ──────────────────────────────────

def _npc_qing_en(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return "Qing: Dorgon ordered the Eight Banners south. Several cities have fallen; the Qing army presses toward Jiangnan."
        elif siege:
            return "Qing: Qing forces laid siege, cutting supply lines. The Eight Banners cavalry encamped outside the city walls."
        else:
            return "Qing: Dorgon mobilized the Eight Banners elite southward. Defenders held the walls and the assault was repelled."
    elif idx == 1:
        return "Qing: Dorgon advanced cautiously, tightening the siege while sending envoys to intimidate Jiangnan gentry."
    else:
        return "Qing: Qing forces paused their offensive, enforcing land enclosure and the queue order in occupied territories."


def _npc_nongmin_en(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return f"Peasant Army: Li Zicheng's Dashun forces seized cities, morale surging. Strength: {troops//1000}K."
        else:
            return f"Peasant Army: Li Zicheng's remnants advanced eastward, seizing opportunities amid chaos. Strength: {troops//1000}K. Discipline crumbling."
    elif idx == 1:
        return "Peasant Army: Watching the situation unfold. Li Zicheng sent envoys to all sides, seeking maximum advantage."
    else:
        return "Peasant Army: Holding Sichuan. Li Zicheng drilled troops and rested, awaiting the right moment."


def _npc_zheng_en(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return "Zheng Clan: Zheng Chenggong led a naval raid along the coast. A thousand warships captured cities — Fujian's fleet grew formidable."
        else:
            return "Zheng Clan: Zheng Chenggong sailed north with his fleet. A thousand warships patrolled the coast, but land forces were limited."
    elif idx == 1:
        return "Zheng Clan: The Zhengs leveraged maritime trade for wealth. Zheng Chenggong funded war through commerce, while sending envoys to all factions."
    else:
        return "Zheng Clan: Zheng Chenggong withdrew to the Fujian coast, using naval superiority to secure a maritime escape route."


def _npc_nanming_en(idx: int, troops: int, events: list, conquest: bool, siege: bool, repelled: bool) -> str:
    if idx == 0:
        if conquest:
            return "Southern Ming: Shi Kefa led a northern expedition, recovering lost territory. The court's morale surged."
        elif siege:
            return "Southern Ming: The four garrisons marched north, besieging Qing-held cities to reclaim the Central Plains."
        else:
            return "Southern Ming: Shi Kefa commanded the defense at Yangzhou. Four garrisons stood ready — but factionalism crippled unified command."
    elif idx == 1:
        return [
            "Southern Ming: The Hongguang court dispatched envoys in all directions — preparing for war while seeking diplomatic solutions.",
            "Southern Ming: The appeasement faction urged dividing the realm along the Yangtze, sending secret envoys north to negotiate.",
            "Southern Ming: Shi Kefa advocated allying with the peasant army against the Qing, sending envoys to discuss joint action.",
        ][hash(f"nanming_d_{troops}") % 3]
    else:
        return [
            "Southern Ming: Factional strife consumed the court. The four garrisons pursued their own agendas — Shi Kefa stood alone.",
            "Southern Ming: The northern garrisons entrenched their own power. Zuo Liangyu marched east under the banner of 'purge the court'.",
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

    # Check what happened (language-aware keyword matching)
    if lang == "en":
        _FALL_KW, _SIEGE_KW, _HELD_KW = "captured", "besieged", "held"
    else:
        _FALL_KW, _SIEGE_KW, _HELD_KW = "攻陷", "围困", "守住"
    player_lost = [e for e in events if _FALL_KW in e and faction_name not in e.split(_FALL_KW)[0]]
    player_gained = [e for e in events if _FALL_KW in e and faction_name in e.split(_FALL_KW)[0]]
    player_sieged = [e for e in events if _SIEGE_KW in e and faction_name not in e.split(_SIEGE_KW)[0]]
    player_held = [e for e in events if _HELD_KW in e and faction_name in e]

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
        elif any(kw in suggestion_id for kw in _ACTIVE_LOYALTY_KW):
            parts.append(f"{faction_name}遣使勤王，整军备战。")
        else:
            parts.append(f"{faction_name}审时度势，发布诏令。")

        if player_lost:
            lost_cities = [e.split(_FALL_KW)[1].strip() for e in player_lost if _FALL_KW in e and len(e.split(_FALL_KW)) > 1]
            if lost_cities:
                if lang == "en":
                    parts.append(f"{'/'.join(lost_cities)} fell — the frontline is in crisis. ")
                else:
                    parts.append(f"{'、'.join(lost_cities)}失陷，前线告急。")
        if player_gained:
            gained_cities = [e.split(_FALL_KW)[1].strip() for e in player_gained if _FALL_KW in e and len(e.split(_FALL_KW)) > 1]
            if gained_cities:
                if lang == "en":
                    parts.append(f"Captured {'/'.join(gained_cities)}! ")
                else:
                    parts.append(f"攻克{'、'.join(gained_cities)}，军威大振。")
        if player_sieged:
            sieged = [e.split(_SIEGE_KW)[1].strip() for e in player_sieged if _SIEGE_KW in e and len(e.split(_SIEGE_KW)) > 1]
            if sieged:
                if lang == "en":
                    parts.append(f"{'/'.join(sieged)} under siege. ")
                else:
                    parts.append(f"{'、'.join(sieged)}被围，粮道断绝。")
        if player_held:
            held = [e.split(_HELD_KW)[1].strip() for e in player_held if _HELD_KW in e and len(e.split(_HELD_KW)) > 1]
            if held:
                if lang == "en":
                    parts.append(f"{'/'.join(held)} held firm. ")
                else:
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
        elif any(kw in suggestion_id for kw in _ACTIVE_LOYALTY_KW):
            parts.append(f"sent envoys and mobilized troops in loyal service. ")
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
