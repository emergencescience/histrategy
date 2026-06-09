"""
Domestic Engine — economy, resources, and climate.

All calculations are deterministic with seeded RNG for climate.
No LLM involvement — pure math.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..world import ClimateEvent, Season, Territory

if TYPE_CHECKING:
    from ..character import CharacterEngine


# ─── Climate system ────────────────────────────────────────────

# Base probabilities per climate zone per season
CLIMATE_PROBABILITIES: dict[tuple[str, str], dict[ClimateEvent, float]] = {
    # (climate_zone, season) → {event: probability}
    # Spring
    ("north", "spring"):   {ClimateEvent.NORMAL: 0.65, ClimateEvent.DROUGHT: 0.10,
                            ClimateEvent.FLOOD: 0.10, ClimateEvent.PESTILENCE: 0.05,
                            ClimateEvent.BUMPER_HARVEST: 0.05, ClimateEvent.COLD_WAVE: 0.05},
    ("central", "spring"): {ClimateEvent.NORMAL: 0.60, ClimateEvent.DROUGHT: 0.08,
                            ClimateEvent.FLOOD: 0.12, ClimateEvent.PESTILENCE: 0.05,
                            ClimateEvent.BUMPER_HARVEST: 0.08, ClimateEvent.COLD_WAVE: 0.07},
    ("south", "spring"):   {ClimateEvent.NORMAL: 0.55, ClimateEvent.DROUGHT: 0.05,
                            ClimateEvent.FLOOD: 0.18, ClimateEvent.PESTILENCE: 0.08,
                            ClimateEvent.BUMPER_HARVEST: 0.10, ClimateEvent.COLD_WAVE: 0.04},
    # Summer
    ("north", "summer"):   {ClimateEvent.NORMAL: 0.60, ClimateEvent.DROUGHT: 0.15,
                            ClimateEvent.FLOOD: 0.05, ClimateEvent.PESTILENCE: 0.08,
                            ClimateEvent.BUMPER_HARVEST: 0.07, ClimateEvent.COLD_WAVE: 0.0},
    ("central", "summer"): {ClimateEvent.NORMAL: 0.55, ClimateEvent.DROUGHT: 0.10,
                            ClimateEvent.FLOOD: 0.10, ClimateEvent.PESTILENCE: 0.08,
                            ClimateEvent.BUMPER_HARVEST: 0.12, ClimateEvent.COLD_WAVE: 0.0},
    ("south", "summer"):   {ClimateEvent.NORMAL: 0.50, ClimateEvent.DROUGHT: 0.05,
                            ClimateEvent.FLOOD: 0.15, ClimateEvent.PESTILENCE: 0.12,
                            ClimateEvent.BUMPER_HARVEST: 0.10, ClimateEvent.COLD_WAVE: 0.0},
    # Autumn
    ("north", "autumn"):   {ClimateEvent.NORMAL: 0.65, ClimateEvent.DROUGHT: 0.05,
                            ClimateEvent.FLOOD: 0.05, ClimateEvent.PESTILENCE: 0.03,
                            ClimateEvent.BUMPER_HARVEST: 0.10, ClimateEvent.COLD_WAVE: 0.07},
    ("central", "autumn"): {ClimateEvent.NORMAL: 0.60, ClimateEvent.DROUGHT: 0.05,
                            ClimateEvent.FLOOD: 0.10, ClimateEvent.PESTILENCE: 0.05,
                            ClimateEvent.BUMPER_HARVEST: 0.12, ClimateEvent.COLD_WAVE: 0.05},
    ("south", "autumn"):   {ClimateEvent.NORMAL: 0.55, ClimateEvent.DROUGHT: 0.03,
                            ClimateEvent.FLOOD: 0.15, ClimateEvent.PESTILENCE: 0.07,
                            ClimateEvent.BUMPER_HARVEST: 0.12, ClimateEvent.COLD_WAVE: 0.03},
    # Winter
    ("north", "winter"):   {ClimateEvent.NORMAL: 0.55, ClimateEvent.DROUGHT: 0.0,
                            ClimateEvent.FLOOD: 0.0, ClimateEvent.PESTILENCE: 0.0,
                            ClimateEvent.BUMPER_HARVEST: 0.0, ClimateEvent.COLD_WAVE: 0.30},
    ("central", "winter"): {ClimateEvent.NORMAL: 0.60, ClimateEvent.DROUGHT: 0.0,
                            ClimateEvent.FLOOD: 0.0, ClimateEvent.PESTILENCE: 0.0,
                            ClimateEvent.BUMPER_HARVEST: 0.0, ClimateEvent.COLD_WAVE: 0.20},
    ("south", "winter"):   {ClimateEvent.NORMAL: 0.70, ClimateEvent.DROUGHT: 0.0,
                            ClimateEvent.FLOOD: 0.05, ClimateEvent.PESTILENCE: 0.0,
                            ClimateEvent.BUMPER_HARVEST: 0.0, ClimateEvent.COLD_WAVE: 0.05},
}


def _seeded_random(seed: str) -> random.Random:
    """Create a seeded RNG that cannot be injected by player input."""
    seed_hash = hashlib.sha256(seed.encode()).digest()
    seed_int = int.from_bytes(seed_hash[:8], "big")
    return random.Random(seed_int)


class ClimateSystem:
    """Seasonal climate with deterministic seeded randomness."""

    def roll_climate(self, territory: Territory, season: Season,
                      year: int, turn: int) -> ClimateEvent:
        """
        Roll a climate event for a territory.

        Uses a hash of (territory_id, year, season, turn) as seed.
        Players cannot influence this — no LLM, no free text injection.
        """
        seed = f"climate:{territory.id}:{year}:{season.value}:{turn}"
        rng = _seeded_random(seed)

        probs = CLIMATE_PROBABILITIES.get(
            (territory.climate_zone, season.value),
            CLIMATE_PROBABILITIES[("central", season.value)],
        )

        # Weighted random choice
        items = list(probs.items())
        total = sum(p for _, p in items)
        r = rng.random() * total

        cumulative = 0.0
        for event, prob in items:
            cumulative += prob
            if r < cumulative:
                return event

        return ClimateEvent.NORMAL

    def roll_all(self, territories: dict[str, Territory], season: Season,
                  year: int, turn: int) -> dict[str, ClimateEvent]:
        """Roll climate for all territories."""
        return {
            tid: self.roll_climate(t, season, year, turn)
            for tid, t in territories.items()
        }


# ─── Domestic calculations ─────────────────────────────────────


@dataclass
class TerritoryResult:
    """Per-territory result of a domestic season tick."""
    territory_id: str
    food_produced: int
    food_consumed: int
    food_delta: int
    population_delta: int
    tax_revenue: int
    development_change: int
    morale_change: int
    climate_event: ClimateEvent


class DomesticEngine:
    """
    Handles all economic and resource calculations.

    All formulas are deterministic. Characters modify output via
    the CharacterEngine passed during calculation.
    """

    def __init__(self, climate_system: ClimateSystem | None = None):
        self._climate = climate_system or ClimateSystem()

    @property
    def climate(self) -> ClimateSystem:
        return self._climate

    # ── Food ──

    def calculate_food_production(
        self,
        territory: Territory,
        season: Season,
        climate: ClimateEvent,
        governor_politics: int = 0,
        tech_agriculture: int = 0,
    ) -> int:
        """
        Calculate food produced in one territory for one season.

        base = fertility × 1000 × (1 + development/100)
        season_mod = spring:0.3, summer:1.0, autumn:1.2, winter:0.05
        climate_mod = normal:1.0, drought:0.4, flood:0.6, etc.
        gov_bonus = 1 + governor_politics/200
        tech_bonus = 1 + tech_agriculture × 0.1

        Returns integer food amount.
        """
        base = territory.fertility * 1000.0 * (1.0 + territory.development / 100.0)
        season_mod = season.food_multiplier
        climate_mod = climate.food_modifier
        gov_mod = 1.0 + governor_politics / 200.0
        tech_mod = 1.0 + tech_agriculture * 0.1

        return int(base * season_mod * climate_mod * gov_mod * tech_mod)

    def calculate_food_consumption(self, territory: Territory, troops: int = 0,
                                    supply_multiplier: float = 1.0) -> int:
        """
        Food consumed by population and troops in one season.

        Each soldier consumes 0.5 units per season (increased in winter by supply_multiplier).
        Each civilian consumes 0.02 units per season.
        """
        civilian_cons = territory.population * 0.02
        troop_cons = troops * 0.5 * supply_multiplier
        return int(civilian_cons + troop_cons)

    # ── Population ──

    def calculate_population_growth(
        self,
        territory: Territory,
        food_surplus: int,
        morale: int = 50,
    ) -> int:
        """
        Calculate population change for one season.

        surplus > 0: positive growth
        surplus < 0: famine → population decline
        """
        consumption = self.calculate_food_consumption(territory)
        total_food = food_surplus + consumption  # approximate

        if total_food > consumption * 1.2:
            # Food surplus → healthy growth
            rate = 0.015 * (1.0 + morale / 100.0) * (1.0 + territory.development / 200.0)
        elif total_food > consumption:
            # Barely enough → slow growth
            rate = 0.005
        elif total_food > 0:
            # Shortage → decline
            rate = -0.01
        else:
            # Famine → serious decline
            rate = -0.03

        return int(territory.population * rate)

    # ── Tax ──

    def calculate_tax_revenue(
        self,
        territory: Territory,
        tax_rate: float,
        governor_politics: int = 0,
    ) -> int:
        """
        Calculate tax revenue for one season.

        base = population × tax_rate × 0.05
        gov_mod = 1 + governor_politics/200
        """
        base = territory.population * tax_rate * 0.05
        gov_mod = 1.0 + governor_politics / 200.0
        return int(base * gov_mod)

    def calculate_tax_morale_impact(self, tax_rate: float) -> int:
        """Morale penalty for high taxes. Returns negative int (0 to -5)."""
        if tax_rate <= 0.2:
            return 0
        if tax_rate <= 0.3:
            return -1
        if tax_rate <= 0.4:
            return -2
        return -3  # tax_rate > 0.4

    # ── Development ──

    def calculate_development_cost(
        self, territory: Territory, target_level: int
    ) -> int:
        """
        Cost to increase development from current to target level.

        Uses sqrt scaling so large cities are more expensive but not impossibly so.
        cost = 150 × delta × √(population / 1000)
        Minimum cost: 300.
        """
        import math
        delta = max(0, target_level - territory.development)
        cost = 150 * delta * math.sqrt(territory.population / 1000.0)
        return max(300, int(cost))

    # ── Full season tick ──

    def process_season(
        self,
        territories: dict[str, Territory],
        season: Season,
        year: int,
        turn: int,
        char_engine: CharacterEngine | None = None,
        tax_rates: dict[str, float] | None = None,
        tech_levels: dict[str, dict[str, int]] | None = None,
        territory_troops: dict[str, int] | None = None,
    ) -> list[TerritoryResult]:
        """
        Full seasonal processing for all territories.

        1. Roll climate
        2. Calculate food production
        3. Calculate food consumption
        4. Calculate population growth
        5. Calculate tax revenue
        6. Apply morale changes
        """
        climate_events = self._climate.roll_all(territories, season, year, turn)
        results: list[TerritoryResult] = []

        for tid, territory in territories.items():
            climate = climate_events.get(tid, ClimateEvent.NORMAL)
            owner_id = territory.owner_id

            # Governor bonus
            gov_pol = 0
            if char_engine and owner_id:
                gov_pol = int((char_engine.get_governor_bonus(tid, owner_id) - 1.0) * 200)

            # Tech level
            tech_agri = 0
            if tech_levels and owner_id:
                tech_agri = tech_levels.get(owner_id, {}).get("agriculture", 0)

            # Tax rate
            tax_rate = 0.3
            if tax_rates and owner_id:
                tax_rate = tax_rates.get(owner_id, 0.3)

            # Calculate
            food_prod = self.calculate_food_production(
                territory, season, climate, gov_pol, tech_agri
            )
            troops = territory_troops.get(tid, 0) if territory_troops else 0
            food_cons = self.calculate_food_consumption(
                territory, troops, season.supply_multiplier
            )
            food_delta = food_prod - food_cons
            pop_delta = self.calculate_population_growth(
                territory, food_delta, morale=50  # default, caller can override
            )
            tax_rev = self.calculate_tax_revenue(territory, tax_rate, gov_pol)
            morale_change = self.calculate_tax_morale_impact(tax_rate)

            # Apply changes to territory
            territory.population = max(100, territory.population + pop_delta)

            results.append(TerritoryResult(
                territory_id=tid,
                food_produced=food_prod,
                food_consumed=food_cons,
                food_delta=food_delta,
                population_delta=pop_delta,
                tax_revenue=tax_rev,
                development_change=0,
                morale_change=morale_change,
                climate_event=climate,
            ))

        return results
