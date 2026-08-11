"""
Quarterly Engine — deterministic economic/population/morale baseline for macro engine.

Replaces the battle-focused TurnController with a policy/economy simulation.
The LLM MacroPolicyEngine then layers nonlinear historical events on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

# ─── Configurable parameters ───────────────────────────────────


@dataclass
class EconomyParams:
    """Tunable economic simulation parameters.

    Calibration target: a mid-sized faction (5 territories, ~125k pop)
    should be able to sustain ~50k troops with a small surplus at 30% tax.

    Design principle: prevent snowballing. Large factions face
    diminishing returns — more territory = more occupation cost,
    more troops = more maintenance, repeated conscription = fatigue.
    """

    # ── Population ──
    base_population_growth: float = 0.003  # per quarter (1.2%/year, down from 2%)

    # ── Food ──
    base_food_per_soldier: float = 0.005  # food per soldier per quarter (was 0.008, reduced for nanming sustainability)
    base_food_per_civilian: float = 0.0015  # food per civilian per quarter (was 0.002)
    food_production_multiplier: float = 0.05  # food output per population * dev * fertility (was 0.03, increased for nanming)

    # ── Seasonal food coefficients (spring=0, summer=1, autumn=2, winter=3) ──
    # Default: East Asian monsoon climate (spring planting, autumn harvest, winter barren)
    # Mediterranean: mild wet winter, dry summer, spring harvest, autumn sowing
    season_food_multipliers: tuple = (1.0, 1.2, 1.5, 0.3)

    # Climate-aware seasonal presets (class-level constants)
    SEASONAL_PRESETS: ClassVar[dict[str, tuple]] = {
        # East Asian monsoon: spring=planting, summer=growing, autumn=harvest, winter=barren
        "east_asian": (1.0, 1.2, 1.5, 0.3),
        # Mediterranean: spring=harvest, summer=dry/dormant, autumn=sowing, winter=mild/growing
        "mediterranean": (1.4, 0.8, 1.1, 0.9),
    }

    # Scenario → climate preset mapping (class-level constant)
    SCENARIO_CLIMATE: ClassVar[dict[str, str]] = {
        "three-kingdoms": "east_asian",
        "rome-triumvirate": "mediterranean",
        "nanming": "east_asian",
    }

    @classmethod
    def for_scenario(cls, scenario: str | None = None) -> EconomyParams:
        """Create EconomyParams with climate-appropriate seasonal multipliers."""
        params = cls()
        if scenario and scenario in cls.SCENARIO_CLIMATE:
            climate = cls.SCENARIO_CLIMATE[scenario]
            if climate in cls.SEASONAL_PRESETS:
                params.season_food_multipliers = cls.SEASONAL_PRESETS[climate]
        return params

    # ── Taxation (revenue = pop × base_tax_revenue_per_pop × tax_rate) ──
    base_tax_revenue_per_pop: float = 0.015  # tax revenue per population unit per quarter (reduced from 0.02)
    max_tax_rate: float = 0.70  # maximum allowed tax rate

    # ── Military costs ──
    # Recruitment is cheap (刘备仁德感召, volunteers flock to the banner).
    # Maintenance is expensive — the real cost of a large army is keeping it fed, paid, and equipped.
    military_maintenance_per_soldier: float = 0.05  # gold per soldier per quarter (16x increase: was 0.003)
    conscript_cost: float = 0.5  # one-time gold cost per conscript (was 3.0 → near-free mobilization)
    conscript_food_penalty: float = 0.1  # food output loss per conscript (was 0.5)
    conscription_fatigue_factor: float = 0.3  # each consecutive draft reduces available pool by this %

    # ── Occupation / governance costs (scales with territory count) ──
    occupation_cost_per_territory: float = 200.0  # gold per non-core territory per quarter (increased 4x)
    core_territory_count: int = 3  # first N territories are "core" (reduced from 4)

    # ── Morale ──
    morale_tax_penalty: float = 0.3  # morale penalty per 1% above 20% tax
    food_morale_impact: float = 0.1  # morale change per food surplus/shortage

    # ── Development ──
    development_growth: float = 0.01  # development increase per quarter (with investment)
    development_decay: float = 0.995  # natural decay multiplier

    # ── Conscription limits ──
    max_conscript_ratio: float = 0.04  # max conscripts per quarter as % of total population (reduced from 5%)

    @staticmethod
    def dynamic_conscript_ratio(population: int) -> float:
        """Scale conscription rate inversely with faction size.

        Small factions can mobilize a larger share of their population
        (emergency mobilization). Large empires face diminishing returns
        (bureaucratic overhead, need to keep farmers in fields).

        Historical precedent: Liu Bei's 30k pop could support 5-10k troops
        (~15-30%), while Cao Cao's 600k pop supported 150k troops (~25% but
        built over years, not quarters).
        """
        if population <= 0:
            return 0.04  # fallback
        if population < 50000:
            return 0.12  # desperate: up to 12% per quarter
        elif population < 100000:
            return 0.08
        elif population < 300000:
            return 0.06
        elif population < 600000:
            return 0.05
        else:
            return 0.04  # large empire: 4%


# ─── Result type ───────────────────────────────────────────────


@dataclass
class QuarterResult:
    """Deterministic baseline for one quarter's economic/population simulation."""

    year: int
    quarter: int  # 0-3 (spring, summer, autumn, winter)
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

    def __init__(self, params: EconomyParams | None = None, scenario: str | None = None):
        self.params = params or EconomyParams.for_scenario(scenario)
        self.scenario = scenario
        self._draft_streak: dict[str, int] = {}  # faction_id → consecutive draft quarters

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
            elif cmd.type in ("conscript", "recruit"):
                amount = cmd.params.get("amount", 0)
                fid = getattr(cmd, "faction_id", "") or world_state.player_faction_id
                conscriptions[fid] = conscriptions.get(fid, 0) + amount

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

            # ── Population ──
            # Use faction.population as primary source (de-coupled from territories).
            # Fall back to territory sum for backward compatibility.
            faction_pop = getattr(faction, "population", 0)
            if faction_pop <= 0:
                faction_pop = sum(
                    getattr(world_state.territories[t], "population", 25000)
                    for t in territories
                    if t in world_state.territories
                )
                # Seed faction.population from territory sum on first pass
                if faction_pop > 0:
                    faction.population = faction_pop
            total_pop = faction_pop
            growth = total_pop * p.base_population_growth
            # High tax slows growth, high morale accelerates
            tax_mod = max(0.2, 1.0 - (tax_rate - 0.2) * 2)
            morale_mod = 0.5 + morale / 200  # 0.75 at 50, 1.0 at 100
            population_delta = growth * tax_mod * morale_mod
            result.population_delta[fid] = population_delta
            # Apply population delta to faction.population
            faction.population = max(0, int(faction_pop + population_delta))

            # ── Tax Revenue ──
            revenue = total_pop * p.base_tax_revenue_per_pop * tax_rate
            result.tax_revenue[fid] = revenue

            # ── Food ──
            season_idx = quarter % 4
            food_consumed = strength * p.base_food_per_soldier + total_pop * p.base_food_per_civilian
            # Winter increases consumption (heating, transport losses)
            if season_idx == 3:  # winter
                food_consumed *= 1.3
            # Food production from agriculture tech and development
            food_produced = 0
            for tid in territories:
                if tid in world_state.territories:
                    t = world_state.territories[tid]
                    dev = getattr(t, "development", 50)
                    fertility = getattr(t, "fertility", 5)
                    tpop = getattr(t, "population", 25000)
                    food_produced += tpop * (dev / 100) * (fertility / 10) * p.food_production_multiplier

            # Apply seasonal modifier — winter food is scarce
            seasonal_mult = p.season_food_multipliers[season_idx] if 0 <= season_idx < 4 else 1.0
            food_produced *= seasonal_mult

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
            # H16: No morale recovery when starving (food <= 0)
            if morale < 40 and morale_change <= 0 and food > 0:
                morale_change += 2  # slow recovery toward neutral (only if not starving)
            # Diminishing returns above 80 — harder to reach 100
            if morale >= 80 and morale_change > 0:
                diminishing = int((morale - 80) / 10)  # -1 at 80, -2 at 90, -3 at 99
                morale_change = max(0, morale_change - diminishing)
            # Policy effects (only apply law bonuses once per faction per game)
            for law in laws_to_apply.get(fid, []):
                if law in ("屯田制", "民屯制"):
                    morale_change += 5  # people get land
                elif law in ("九品中正制",):
                    morale_change -= 3  # aristocracy consolidation

            result.morale_delta[fid] = morale_change

            # ── Conscription ──
            conscript_amount = conscriptions.get(fid, 0)
            if conscript_amount > 0:
                # Track consecutive drafts for fatigue
                streak = self._draft_streak.get(fid, 0) + 1
                self._draft_streak[fid] = streak
                # Fatigue: each consecutive draft quarter reduces effective pool
                fatigue_mult = max(0.3, 1.0 - (streak - 1) * p.conscription_fatigue_factor)
                adjusted_pool = int(total_pop * fatigue_mult)
                # Cap: can't conscript more than dynamic max ratio of adjusted population
                # Small factions get higher rates (emergency mobilization)
                dyn_ratio = p.dynamic_conscript_ratio(total_pop)
                max_draft = int(adjusted_pool * dyn_ratio)
                actual_amount = min(conscript_amount, max_draft)
                # Cap: can't spend more than available treasury
                max_affordable = int(treasury / p.conscript_cost) if p.conscript_cost > 0 else actual_amount
                actual_amount = min(actual_amount, max_affordable)
                if actual_amount > 0:
                    faction.strength_actual = getattr(faction, "strength_actual", 0) + actual_amount
                    cost = actual_amount * p.conscript_cost
                    faction.treasury = max(0, treasury - cost)
                    treasury = faction.treasury  # update local for subsequent cost calcs
                    # Drafting reduces food output
                    result.food_delta[fid] -= actual_amount * p.conscript_food_penalty
                    fatigue_note = f"（连续第{streak}季征兵，效率{int(fatigue_mult*100)}%）" if streak > 1 else ""
                    result.notable_events.append(f"{fid}征兵{actual_amount}人，花费{cost:.0f}金{fatigue_note}")
            else:
                # Reset draft streak when no conscription
                self._draft_streak[fid] = 0

            # ── Military Maintenance ──
            # Every soldier costs gold each quarter (pay, equipment, supplies beyond food)
            maintenance_cost = int(strength * p.military_maintenance_per_soldier)
            if maintenance_cost > 0:
                treasury_after_maint = max(0, treasury - maintenance_cost)
                actual_cost = treasury - treasury_after_maint
                faction.treasury = treasury_after_maint
                treasury = treasury_after_maint
                if actual_cost > 0:
                    result.notable_events.append(f"{fid}军费{actual_cost}金（兵力{strength}）")

            # ── Occupation / Governance Costs ──
            # Territories beyond the core count cost gold to administer
            num_territories = len(territories)
            if num_territories > p.core_territory_count:
                occupied = num_territories - p.core_territory_count
                occupation_cost = int(occupied * p.occupation_cost_per_territory)
                treasury_after_occ = max(0, treasury - occupation_cost)
                actual_occ_cost = treasury - treasury_after_occ
                faction.treasury = treasury_after_occ
                treasury = treasury_after_occ
                if actual_occ_cost > 0:
                    result.notable_events.append(
                        f"{fid}领地治理{actual_occ_cost}金（{num_territories}领地，{p.core_territory_count}核心+{occupied}占领区）"
                    )

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
