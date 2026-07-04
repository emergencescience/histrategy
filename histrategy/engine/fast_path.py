"""
Fast-Path Deterministic Simulation Engine.

Replaces V1 LLM simulation when player clicks a suggestion package.
Runs in <1ms using formula-based combat/economy/morale resolution.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy.server.room_manager import GameRoom

logger = logging.getLogger("histrategy.fast_path")

# ── ID extraction ────────────────────────────────────────────


def extract_suggestion_id(decision: str) -> str | None:
    """Extract [suggestion_id] prefix from a decision string."""
    m = re.match(r'^\[([a-z_]+_t\d_\w+)\]', decision)
    return m.group(1) if m else None


# ── NPC package selection ────────────────────────────────────
# Each NPC faction has personality weights that influence which
# package they pick. We map (faction_id, current_situation) → package index.


def _pick_npc_package(faction_id: str, aggression: float, caution: float,
                       diplomacy: float, development: float, is_winning: bool,
                       is_losing: bool) -> int:
    """Deterministically pick which of the 3 packages an NPC faction chooses.

    Returns 0, 1, or 2 (index into the turn's 3 packages).
    """
    # Package 0 = aggressive/offensive, 1 = balanced/diplomatic, 2 = defensive/retreating
    scores = [0.0, 0.0, 0.0]

    # Aggressive factions prefer package 0
    scores[0] += aggression * 2.0
    # Cautious factions prefer package 2
    scores[2] += caution * 2.0
    # Diplomatic factions prefer package 1
    scores[1] += diplomacy * 2.0
    # Development-focused factions prefer package 1
    scores[1] += development * 1.5

    # Winning → more aggressive
    if is_winning:
        scores[0] += 1.5
        scores[2] -= 1.0
    # Losing → more defensive
    if is_losing:
        scores[2] += 1.5
        scores[0] -= 1.0

    # Pick highest score
    return max(range(3), key=lambda i: scores[i])


# ── Deterministic combat resolution ──────────────────────────


def _resolve_combat(attacker_troops: int, defender_troops: int,
                    is_south_of_yangtze: bool = False,
                    defender_dug_in: bool = False) -> dict:
    """Resolve a single battle deterministically.

    Returns:
        dict with keys: won (bool), city_falls (bool), siege_only (bool),
        attacker_losses (int), defender_losses (int)
    """
    # Apply Yangtze defense bonus (1.5x effective troops for south-bank defenders)
    effective_defender = defender_troops
    if is_south_of_yangtze:
        effective_defender = int(defender_troops * 1.5)

    # Apply dug-in bonus (+30% if player ordered defense)
    if defender_dug_in:
        effective_defender = int(effective_defender * 1.3)

    ratio = attacker_troops / max(effective_defender, 1)

    # 3:1 or better → city falls immediately
    if ratio >= 3.0:
        return {
            "won": True,
            "city_falls": True,
            "siege_only": False,
            "attacker_losses": int(attacker_troops * 0.05),
            "defender_losses": int(defender_troops * 0.30),
        }

    # 1.5:1 to 3:1 → siege starts, city holds for 2 quarters
    if ratio >= 1.5:
        return {
            "won": True,
            "city_falls": False,
            "siege_only": True,
            "attacker_losses": int(attacker_troops * 0.03),
            "defender_losses": int(defender_troops * 0.10),
        }

    # Below 1.5:1 → attack fails
    return {
        "won": False,
        "city_falls": False,
        "siege_only": False,
        "attacker_losses": int(attacker_troops * 0.08),
        "defender_losses": int(defender_troops * 0.05),
    }


# ── Main simulation ──────────────────────────────────────────


_YANGTZE_SOUTH = {"nanjing", "zhejiang", "jiangxi", "huguang",
                  "yangzhou", "fujian", "guangdong"}
_YANGTZE_NORTH = {"shandong", "henan", "beijing", "shengjing",
                  "shanxi", "shaanxi", "gansu", "sichuan"}


def simulate_fast_path(room, player_decision: str,
                       player_suggestion_id: str) -> dict:
    """Run deterministic fast-path simulation.

    Args:
        room: GameRoom object with current world state
        player_decision: Full decision text (for narrative extraction)
        player_suggestion_id: e.g. "nanming_t1_defend"

    Returns:
        dict matching the CommandResponse format:
        {narrative, aftermath, state_changes, events_occurred,
         npc_actions, new_suggestions, game_over, faction_status,
         year, season, turn}
    """
    # Use the room object directly (world_state is in-memory, not in DB)
    ws = getattr(room, 'world_state', None)
    if ws is None:
        raise ValueError("Room has no world_state — has the game been started?")

    # Get faction personalities
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
        }

    # Determine current turn number
    turn = (room.quarter_number or 0) + 1

    # ── Determine NPC package choices ──
    npc_choices = {}
    for fid in list(factions.keys()):
        if fid == "nanming":
            continue  # Player faction
        f = factions[fid]
        # Determine if winning/losing based on territory count vs average
        avg_terr = sum(len(f2["territories"]) for f2 in factions.values()) / max(len(factions), 1)
        is_winning = len(f["territories"]) > avg_terr * 1.3
        is_losing = len(f["territories"]) < avg_terr * 0.7
        idx = _pick_npc_package(
            fid, f["aggression"], f["caution"],
            f["diplomacy"], f["development"],
            is_winning, is_losing,
        )
        npc_choices[fid] = idx

    # ── Run combat simulation ──
    events = []
    state_changes = {}
    npc_actions = []

    # Parse player's package type from suggestion_id
    # e.g. "nanming_t1_defend" → is_defensive=True
    pid_parts = player_suggestion_id.split("_")
    is_player_defensive = any(kw in player_suggestion_id
                              for kw in ["defend", "hold", "retreat",
                                         "relocate", "peace", "sail"])

    # Determine which territories Qing attacks based on their package choice
    qing_choice = npc_choices.get("qing", 0)
    qing_targets = []
    if qing_choice == 0:  # Aggressive
        qing_targets = ["shandong", "henan"]
    elif qing_choice == 1:  # Balanced
        qing_targets = ["shandong"]
    # else: defensive — no attack

    for target in qing_targets:
        if target in ["shandong", "henan"]:
            # These are nanming territories
            atk = int(factions["qing"]["troops"] * 0.4)  # 40% of Qing troops
            defender_territories = factions.get("nanming", {}).get("territories", [])
            if target not in defender_territories:
                continue  # Already captured

            def_troops = int(factions["nanming"]["troops"] / max(len(defender_territories), 1))
            is_south = target in _YANGTZE_SOUTH

            result = _resolve_combat(atk, def_troops, is_south,
                                     defender_dug_in=is_player_defensive)

            if result["city_falls"]:
                factions["qing"]["territories"].append(target)
                defender_territories.remove(target)
                events.append(f"{target} | qing captures {target}")
                state_changes[target] = "qing"
                # Update troops
                factions["qing"]["troops"] -= result["attacker_losses"]
                factions["nanming"]["troops"] -= result["defender_losses"]
                factions["nanming"]["morale"] -= 8
                factions["qing"]["morale"] += 3
                # Qing expedition decay if south of Yangtze
                if is_south:
                    factions["qing"]["morale"] -= 3
            elif result["siege_only"]:
                # City under siege, not fallen
                events.append(f"{target} | qing besieges {target}")
                factions["qing"]["troops"] -= result["attacker_losses"]
                factions["nanming"]["troops"] -= result["defender_losses"]
                factions["nanming"]["food"] -= int(factions["nanming"]["food"] * 0.15)
                factions["nanming"]["morale"] -= 3
            else:
                # Attack repelled
                events.append(f"{target} | nanming defends {target}")
                factions["qing"]["troops"] -= result["attacker_losses"]
                factions["nanming"]["troops"] -= result["defender_losses"]
                factions["nanming"]["morale"] += 5

    # ── Apply player domestic/economic effects ──
    if "defend" in player_suggestion_id:
        factions["nanming"]["food"] += int(factions["nanming"]["food"] * 0.05)
        factions["nanming"]["morale"] += 2
    elif "ally" in player_suggestion_id:
        factions["nanming"]["treasury"] -= int(factions["nanming"]["treasury"] * 0.10)
        factions["nanming"]["morale"] += 3
    elif "retreat" in player_suggestion_id or "relocate" in player_suggestion_id:
        factions["nanming"]["treasury"] += int(factions["nanming"]["treasury"] * 0.05)
        factions["nanming"]["morale"] -= 2

    # ── Natural attrition (all factions) ──
    for fid in factions:
        factions[fid]["troops"] = max(1000, int(factions[fid]["troops"] * 0.97))
        factions[fid]["food"] = max(500, int(factions[fid]["food"] * 0.95))
        factions[fid]["morale"] = max(10, min(100, factions[fid]["morale"]))

    # ── NPC faction actions summary ──
    for fid, idx in npc_choices.items():
        fname = {"qing": "大清", "nongminjun": "农民军", "zheng": "郑氏"}.get(fid, fid)
        action_words = ["进攻", "外交斡旋", "防御"] 
        npc_actions.append(f"{fname}: 选择了{action_words[idx] if idx < len(action_words) else '观望'}策略")

    # ── Advance season ──
    seasons = ["spring", "summer", "autumn", "winter"]
    season_idx = seasons.index(room.season) if room.season in seasons else 0
    new_season_idx = (season_idx + 1) % 4
    new_year = room.year + 1 if new_season_idx == 0 else room.year
    new_season = seasons[new_season_idx]

    # ── Build response ──
    season_zh = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
    season_str = season_zh.get(new_season, new_season)

    narrative = _build_narrative(player_suggestion_id, events, factions, season_str)
    aftermath = f"公元{new_year}年{season_str}。{'、'.join(events) if events else '各方按兵不动，局势暂时平稳。'}"

    return {
        "game_id": room.id,
        "narrative": narrative,
        "aftermath": aftermath,
        "state_changes": state_changes,
        "events_occurred": events,
        "npc_actions": npc_actions,
        "new_suggestions": _get_next_suggestions(room.scenario or "nanming",
                                                  "nanming", turn, "zh"),
        "game_over": None,
        "faction_status": {
            "name": "南明",
            "faction_id": "nanming",
            "strength": factions["nanming"]["troops"],
            "food": factions["nanming"]["food"],
            "treasury": factions["nanming"]["treasury"],
            "morale": factions["nanming"]["morale"],
            "territories": factions["nanming"]["territories"],
            "is_active": True,
            "year": new_year,
            "season": new_season,
            "turn": turn,
        },
        "year": new_year,
        "season": new_season,
        "turn": turn,
    }


def _get_next_suggestions(scenario: str, faction_id: str, turn: int,
                           lang: str) -> list[str]:
    """Get suggestions for next turn from EARLY_TURNS_SUGGESTIONS."""
    try:
        from histrategy.engine.helpers import EARLY_TURNS_SUGGESTIONS
        data = EARLY_TURNS_SUGGESTIONS.get(scenario, {}).get(faction_id, {})
        turn_data = data.get(turn, {})
        return turn_data.get(lang, [])
    except Exception:
        return []


def _build_narrative(suggestion_id: str, events: list[str],
                     factions: dict, season: str) -> str:
    """Build a narrative from the simulation results."""
    parts = []

    # Identify what happened
    qing_gains = [e for e in events if "captures" in e]
    qing_sieges = [e for e in events if "besieges" in e]
    nanming_defends = [e for e in events if "defends" in e]

    nm = factions.get("nanming", {})
    q = factions.get("qing", {})

    if "defend" in suggestion_id:
        parts.append(
            f"弘光元年{season}，史可法督师扬州，集中四镇兵马加固江淮防线。"
        )
    elif "ally" in suggestion_id:
        parts.append(
            f"弘光元年{season}，黄得功率部出河南牵制清军侧翼，"
            f"密使联络李自成共抗清军。"
        )
    elif "retreat" in suggestion_id or "relocate" in suggestion_id:
        parts.append(
            f"弘光元年{season}，四镇断后掩护朝廷南撤至浙江，"
            f"江南粮仓付之一炬。"
        )
    else:
        parts.append(f"弘光元年{season}，南明朝廷发布诏令，整军备战。")

    if qing_gains:
        lost_cities = [e.split("|")[0].strip() for e in qing_gains]
        parts.append(f"清军攻陷{'、'.join(lost_cities)}，江北告急。")

    if qing_sieges:
        sieged = [e.split("|")[0].strip() for e in qing_sieges]
        parts.append(f"清军兵临{'、'.join(sieged)}城下，围城之中粮道断绝。")

    if nanming_defends:
        held = [e.split("|")[0].strip() for e in nanming_defends]
        parts.append(f"{'、'.join(held)}防线稳固，军民士气大振。")

    # State summary
    parts.append(
        f"南明尚有{nm.get('morale', 50)}点民心、"
        f"{nm.get('troops', 0)}兵马、"
        f"{len(nm.get('territories', []))}座城池。"
    )

    return "。".join(parts) + "。"


# ── Quick path detection ─────────────────────────────────────


def should_use_fast_path(decision: str) -> bool:
    """Check if a decision qualifies for fast-path simulation."""
    sid = extract_suggestion_id(decision)
    return sid is not None
