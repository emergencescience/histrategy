"""Shared deterministic-combat helpers and attack-target tables.

Migrated from the deprecated ``histrategy.engine.fast_path`` module
(fast-path deterministic simulation was removed). The combat resolution
formula and faction attack-target lookup tables are still used by
``room_manager._resolve_npc_territory_combat`` and related call sites.
"""

from __future__ import annotations

# Which territories an aggressive faction targets when attacking each player
# three-kingdoms attack targets (border conflicts)
_TK_ATTACK_TARGETS = {
    "cao": {
        "shu": ["xinye"],
        "wu": ["lujiang", "chaisang"],
        "liubiao": ["xiangyang", "wancheng"],
        "liuzhang": ["hanshui"],
        "zhanglu": ["hanzhong"],
        "machao": ["changshan"],
    },
    "shu": {
        "cao": ["wancheng"],
        "liubiao": ["xiangyang"],
        "liuzhang": ["hanshui"],
    },
    "wu": {
        "cao": ["lujiang", "xiapi"],
        "liubiao": ["jiangkou", "jiangling"],
        "shu": ["xinye"],
    },
    "liubiao": {
        "cao": ["wancheng"],
        "wu": ["chaisang", "yuzhang"],
        "shu": ["xinye"],
    },
    "liuzhang": {
        "cao": ["hanshui"],
        "liubiao": ["xiangyang"],
        "zhanglu": ["hanzhong"],
    },
}

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
# Merge three-kingdoms targets
_FACTION_ATTACK_TARGETS.update(_TK_ATTACK_TARGETS)

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

    # Historical context: Cao Cao on turn 1-2 should be cautious
    # (still pacifying Wuhuan, preparing southern campaign, Liu Biao not dead yet)
    if faction_id == "cao" and turn <= 2:
        scores[0] -= 1.0  # Mild hesitation before attacking Jingzhou
        scores[1] += 1.0  # Slight preference for preparation

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


_YANGTZE_SOUTH = {"nanjing", "zhejiang", "jiangxi",
                  "wuchang", "huguang_west", "huguang_south",
                  "yangzhou", "fujian", "guangdong", "taiwan",
                  # three-kingdoms: south of Yangtze
                  "jianye", "wu", "yuzhang", "kuaiji", "danyang",
                  "chaisang", "changsha", "jiangkou", "jiangling"}
