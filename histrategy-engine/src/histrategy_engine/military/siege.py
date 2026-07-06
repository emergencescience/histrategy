"""
Siege Mechanics for the Military Engine.

Handles prolonged city attacks: wall breaching, starvation, surrender,
and morale cascades. Critical for nanming-era gameplay (Yangzhou, Nanjing).

All calculations are deterministic — no LLM dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import Army, Territory, Season


# ── Siege constants ────────────────────────────────────────────

# How many turns a city can hold out before starvation
BASE_SIEGE_RESISTANCE = 3  # turns before food runs out
FORT_SIEGE_BONUS = 2       # extra turns per 25 fortification
GRANARY_SIEGE_BONUS = 2    # extra turns if the city has food surplus

# Damage per turn of siege
SIEGE_ATTRITION_BASE = 0.05     # 5% troop loss per turn for defenders
SIEGE_ATTRITION_STARVATION = 0.10  # 10% when food exhausted
SIEGE_POPULATION_LOSS = 0.03    # 3% civilian loss per turn

# Breach mechanics (gunpowder-era)
GUNPOWDER_BREACH_BONUS = 0.20   # +20% breach chance per turn with cannons
BASE_BREACH_CHANCE = 0.05       # 5% per turn without gunpowder

# Surrender conditions
SURRENDER_MORALE_THRESHOLD = 20  # morale below this → surrender check
SURRENDER_BASE_CHANCE = 0.15     # base surrender chance per turn
SURRENDER_STARVATION_BONUS = 0.30  # extra chance when starving
SURRENDER_RELIEF_HOPE_BONUS = -0.20  # reduced chance when relief army nearby


@dataclass
class SiegeState:
    """Tracks the state of an ongoing siege."""

    city_id: str
    attacker_faction_id: str
    defender_faction_id: str
    turns_under_siege: int = 0
    walls_breached: bool = False
    food_exhausted: bool = False
    defender_morale_start: int = 50

    @property
    def can_hold_out(self) -> int:
        """How many more turns the defender can hold before starvation."""
        return max(0, self.turns_under_siege - BASE_SIEGE_RESISTANCE)


@dataclass
class SiegeResult:
    """Result of one siege tick."""

    city_id: str
    turns_under_siege: int
    walls_breached: bool
    food_exhausted: bool
    defender_surrendered: bool
    defender_troops_lost: int
    civilian_loss: int
    morale_change_defender: int
    morale_change_attacker: int
    narrative: str


def calculate_siege_resistance(
    fortification: int,
    has_granary: bool = False,
) -> int:
    """How many turns a city can resist siege before food runs out."""
    resistance = BASE_SIEGE_RESISTANCE
    # Fortification extends resistance
    resistance += (fortification // 25) * FORT_SIEGE_BONUS
    # Food stockpile extends resistance
    if has_granary:
        resistance += GRANARY_SIEGE_BONUS
    return max(1, resistance)


def resolve_siege_tick(
    state: SiegeState,
    attacker_troops: int,
    defender_troops: int,
    fortification: int,
    defender_food: int,
    defender_morale: int,
    has_gunpowder: bool = False,
    relief_army_nearby: bool = False,
    season: Season | None = None,
) -> SiegeResult:
    """Process one turn of siege.

    Returns the results: casualties, breach progress, surrender check.
    """
    state.turns_under_siege += 1
    resistance = calculate_siege_resistance(fortification, defender_food > 0)

    # ── Food exhaustion ──
    food_exhausted = state.turns_under_siege > resistance
    if food_exhausted and not state.food_exhausted:
        state.food_exhausted = True

    # ── Wall breach ──
    breach_chance = BASE_BREACH_CHANCE
    if has_gunpowder:
        breach_chance += GUNPOWDER_BREACH_BONUS
    # Higher after food runs out (defenders weakened)
    if food_exhausted:
        breach_chance += 0.10

    walls_breached = state.walls_breached or (
        state.turns_under_siege >= 2 and _seeded_check(state, breach_chance)
    )
    if walls_breached and not state.walls_breached:
        state.walls_breached = True

    # ── Attrition ──
    if food_exhausted:
        attrition = SIEGE_ATTRITION_STARVATION
    else:
        attrition = SIEGE_ATTRITION_BASE

    # Winter: worse attrition (cold, no shelter)
    if season and season.value == "winter":
        attrition *= 1.5

    defender_troops_lost = int(defender_troops * attrition)
    civilian_loss = int(1000 * SIEGE_POPULATION_LOSS * state.turns_under_siege)  # accumulates

    # ── Morale changes ──
    morale_loss = -5  # base per turn under siege
    if food_exhausted:
        morale_loss -= 3  # starvation despair
    if walls_breached:
        morale_loss -= 5  # walls breached

    # Attacker morale: slight drain from prolonged siege (supply lines, boredom)
    attacker_morale_change = -1
    if walls_breached:
        attacker_morale_change = 2  # encouraged by breach
    if state.turns_under_siege > 5:
        attacker_morale_change = -3  # frustrated by long siege

    # ── Surrender check ──
    defender_surrendered = False
    if defender_morale + morale_loss < SURRENDER_MORALE_THRESHOLD:
        surrender_chance = SURRENDER_BASE_CHANCE
        if food_exhausted:
            surrender_chance += SURRENDER_STARVATION_BONUS
        if walls_breached:
            surrender_chance += 0.25
        if relief_army_nearby:
            surrender_chance += SURRENDER_RELIEF_HOPE_BONUS  # negative → less likely

        defender_surrendered = _seeded_check(state, max(0.0, min(0.95, surrender_chance)))

    # ── Narrative ──
    parts = []
    if food_exhausted and state.turns_under_siege == resistance + 1:
        parts.append(f"城中粮尽，守军开始宰杀战马充饥。")
    if walls_breached and not state.walls_breached:
        parts.append(f"城墙被{'火炮轰塌' if has_gunpowder else '撞车攻破'}一个缺口。")
    if defender_surrendered:
        parts.append(f"守军士气崩溃，开城投降。")
    elif food_exhausted and state.turns_under_siege > resistance + 2:
        parts.append(f"城内饿殍遍野，守军仍在苦撑。")

    narrative = " ".join(parts) if parts else f"围城第{state.turns_under_siege}日，守军仍在坚守。"

    return SiegeResult(
        city_id=state.city_id,
        turns_under_siege=state.turns_under_siege,
        walls_breached=walls_breached,
        food_exhausted=food_exhausted,
        defender_surrendered=defender_surrendered,
        defender_troops_lost=defender_troops_lost,
        civilian_loss=civilian_loss,
        morale_change_defender=morale_loss,
        morale_change_attacker=attacker_morale_change,
        narrative=narrative,
    )


def _seeded_check(state: SiegeState, probability: float) -> bool:
    """Deterministic check using hash of siege state (no random)."""
    import hashlib

    seed = f"{state.city_id}:{state.attacker_faction_id}:{state.turns_under_siege}:breach"
    seed_hash = hashlib.sha256(seed.encode()).digest()
    seed_int = int.from_bytes(seed_hash[:8], "big")
    return (seed_int % 10000) / 10000 < probability
