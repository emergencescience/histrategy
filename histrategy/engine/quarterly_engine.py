"""
Quarterly Engine — deterministic economic/population/morale baseline for macro engine.

Replaces the battle-focused TurnController with a policy/economy simulation.
The LLM MacroPolicyEngine then layers nonlinear historical events on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

# ─── Configurable parameters ───────────────────────────────────

@dataclass
class EconomyParams:
    """Tunable economic simulation parameters."""
    base_population_growth: float = 0.005       # per quarter (2%/year)
    base_food_per_soldier: float = 0.1          # food consumed per soldier per quarter
    base_food_per_civilian: float = 0.02        # food consumed per civilian per quarter
    base_tax_revenue_per_pop: float = 0.0005    # tax revenue per population unit
    morale_tax_penalty: float = 0.3              # morale penalty per 1% above 20% tax (was 0.5)
    food_morale_impact: float = 0.1              # morale change per food surplus/shortage (was 0.2)
    development_growth: float = 0.01            # development increase per quarter (with investment)
    development_decay: float = 0.995            # natural decay multiplier
    conscript_cost: float = 2.0                 # treasury cost per conscript
    conscript_food_penalty: float = 0.5         # food output loss per conscript (draft effect)
    max_tax_rate: float = 0.70                  # maximum allowed tax rate


# ─── Result type ───────────────────────────────────────────────

@dataclass
class QuarterResult:
    """Deterministic baseline for one quarter's economic/population simulation."""
    year: int
    quarter: int                                    # 0-3 (spring, summer, autumn, winter)
    season_name: str = ""

    # Per-faction changes
    tax_revenue: dict[str, float] = field(default_factory=dict)
    food_delta: dict[str, float] = field(default_factory=dict)
    population_delta: dict[str, float] = field(default_factory=dict)
    morale_delta: dict[str, int] = field(default_factory=dict)
    development_changes: dict[str, dict[str, float]] = field(default_factory=dict)

    # Events (for narrative)
    notable_events: list[str] = field(default_factory=list)

    # Placeholder for LLM-generated content
    player_decision: str = ""
    player_commands: list = field(default_factory=list)

    # v3 compat
    battles: list = field(default_factory=list)
    resource_changes: dict = field(default_factory=dict)
    history_events: list = field(default_factory=list)
    _v3_delta: dict = field(default_factory=dict)


# ─── Engine ────────────────────────────────────────────────────

class QuarterlyEngine:
    """Deterministic quarterly simulation — economy, population, morale.

    Called BEFORE the LLM MacroPolicyEngine. Provides the baseline
    that the LLM then modifies with historical events and battle outcomes.
    """

    def __init__(self, params: EconomyParams | None = None):
        self.params = params or EconomyParams()

    def execute_quarter(
        self,
        world_state: WorldState,
        policy_commands: list,
        year: int,
        quarter: int,
    ) -> QuarterResult:
        """Run one quarter of deterministic economic simulation."""
        p = self.params
        result = QuarterResult(
            year=year,
            quarter=quarter,
            season_name=["春", "夏", "秋", "冬"][quarter],
        )

        # Map faction IDs to their tax rates (from policy commands)
        tax_rates: dict[str, float] = {}
        laws_to_apply: dict[str, list[str]] = {}  # faction -> [law_names]
        conscriptions: dict[str, int] = {}  # faction -> amount

        for cmd in policy_commands:
            if cmd.type == "tax_rate":
                rate = cmd.params.get("rate", 0.3)
                tax_rates[world_state.player_faction_id] = min(rate, p.max_tax_rate)
            elif cmd.type == "law":
                law_name = cmd.params.get("name", "")
                if law_name:
                    laws_to_apply.setdefault(world_state.player_faction_id, []).append(law_name)
            elif cmd.type == "conscript":
                amount = cmd.params.get("amount", 0)
                conscriptions[world_state.player_faction_id] = amount

        # Process each active faction
        for fid, faction in world_state.factions.items():
            if not getattr(faction, "is_active", True):
                continue

            territories = getattr(faction, "territories", [])
            strength = getattr(faction, "strength_actual", 5000)
            morale = getattr(faction, "morale_actual", 50)
            treasury = getattr(faction, "treasury", 5000)
            food = getattr(faction, "food", 5000)
            tax_rate = tax_rates.get(fid, getattr(faction, "tax_rate", 0.3))

            # ── Population (simplified) ──
            total_pop = sum(
                getattr(world_state.territories[t], "population", 25000)
                for t in territories if t in world_state.territories
            )
            growth = total_pop * p.base_population_growth
            # High tax slows growth, high morale accelerates
            tax_mod = max(0.2, 1.0 - (tax_rate - 0.2) * 2)
            morale_mod = 0.5 + morale / 200  # 0.75 at 50, 1.0 at 100
            population_delta = growth * tax_mod * morale_mod
            result.population_delta[fid] = population_delta

            # ── Tax Revenue ──
            revenue = total_pop * p.base_tax_revenue_per_pop * tax_rate
            result.tax_revenue[fid] = revenue

            # ── Food ──
            food_consumed = (
                strength * p.base_food_per_soldier +
                total_pop * p.base_food_per_civilian
            )
            # Food production from agriculture tech and development
            food_produced = 0
            for tid in territories:
                if tid in world_state.territories:
                    t = world_state.territories[tid]
                    dev = getattr(t, "development", 50)
                    fertility = getattr(t, "fertility", 5)
                    tpop = getattr(t, "population", 25000)
                    food_produced += tpop * (dev / 100) * (fertility / 10) * 0.02

            # Law effects on food
            for law in laws_to_apply.get(fid, []):
                if law in ("屯田制", "军屯制", "民屯制"):
                    food_produced *= 1.3  # 30% more food from land reclamation
                elif law in ("盐铁专卖", "盐铁官营"):
                    revenue *= 1.15  # 15% more tax from state monopoly

            food_delta = food_produced - food_consumed
            result.food_delta[fid] = food_delta

            # ── Morale ──
            morale_change = 0
            # Tax effect
            if tax_rate > 0.2:
                morale_change -= int((tax_rate - 0.2) * 100 * p.morale_tax_penalty)
            # Food effect
            if food + food_delta <= 0:
                morale_change -= 15  # starvation — severe
            elif food_delta < -500:
                # Only penalize significant food deficits
                morale_change -= int(abs(food_delta) / 1000 * p.food_morale_impact)
            elif food_delta > 2000:
                morale_change += int(food_delta / 2000 * p.food_morale_impact)
            # Natural morale regen toward 50 — prevents death spiral
            if morale < 40 and morale_change <= 0:
                morale_change += 2  # slow recovery toward neutral
            # Policy effects
            for law in laws_to_apply.get(fid, []):
                if law in ("屯田制", "民屯制"):
                    morale_change += 5  # people get land
                elif law in ("九品中正制",):
                    morale_change -= 3  # aristocracy consolidation

            result.morale_delta[fid] = morale_change

            # ── Conscription ──
            conscript_amount = conscriptions.get(fid, 0)
            if conscript_amount > 0:
                faction.strength_actual = getattr(faction, "strength_actual", 0) + conscript_amount
                cost = conscript_amount * p.conscript_cost
                faction.treasury = max(0, treasury - cost)
                # Drafting reduces food output
                result.food_delta[fid] -= conscript_amount * p.conscript_food_penalty
                result.notable_events.append(f"{fid}征兵{conscript_amount}人，花费{cost:.0f}金")

            # ── Development ──
            dev_changes: dict[str, float] = {}
            for tid in territories:
                if tid in world_state.territories:
                    t = world_state.territories[tid]
                    old_dev = getattr(t, "development", 50)
                    # Investment from tax revenue boosts development
                    invest_ratio = 0.01 if fid == world_state.player_faction_id else 0.003
                    new_dev = old_dev * p.development_decay + invest_ratio * (revenue / max(len(territories), 1))
                    dev_changes[tid] = new_dev - old_dev
            result.development_changes[fid] = dev_changes

            # ── Apply deterministic changes ──
            faction.treasury += int(revenue)
            faction.food = max(0, int(food + food_delta))
            faction.morale_actual = max(0, min(100, morale + morale_change))

            # Record resource changes for narrative
            result.resource_changes[fid] = {
                "food_delta": int(food_delta),
                "tax_revenue": int(revenue),
            }

        return result
