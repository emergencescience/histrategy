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
    # Recruitment is cheap (volunteers flock to the banner).
    # Maintenance scales with army size — large standing armies strain logistics.
    # Progressive: first 100k troops base rate, each additional 100k adds +50%.
    military_maintenance_per_soldier: float = 0.015  # base gold per soldier per quarter
    conscript_cost: float = 0.5  # one-time gold cost per conscript
    conscript_food_penalty: float = 0.1  # food output loss per conscript
    conscription_fatigue_factor: float = 0.3  # each consecutive draft reduces available pool by this %

    # ── Food consumption (progressive for large armies) ──
    base_food_per_soldier: float = 0.005  # food per soldier per quarter (base)
    large_army_food_per_soldier: float = 0.008  # food per soldier when troops > 200k
    large_army_threshold: int = 200000  # troop count above which food cost increases

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

# Track consecutive quarters with treasury=0 per faction for progressive penalties
_treasury_zero_streak: dict[str, int] = {}


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

        player_fid = world_state.player_faction_id
        for cmd in policy_commands:
            if cmd.type == "tax_rate":
                rate = cmd.params.get("rate", 0.3)
                tax_rates[player_fid] = min(rate, p.max_tax_rate)
            elif cmd.type == "law":
                law_name = cmd.params.get("name", "")
                if law_name:
                    laws_to_apply.setdefault(player_fid, []).append(law_name)
            elif cmd.type in ("conscript", "recruit"):
                cmd_fid = getattr(cmd, "faction_id", "") or player_fid
                # Only process player faction conscription — NPCs get
                # automatic morale-based recruitment instead (see execute_npc_recruitment).
                if cmd_fid == player_fid:
                    conscriptions[cmd_fid] = conscriptions.get(cmd_fid, 0) + cmd.params.get("amount", 0)

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
            # Progressive food consumption: large armies strain logistics
            food_per_soldier = p.large_army_food_per_soldier if strength > p.large_army_threshold else p.base_food_per_soldier
            food_consumed = strength * food_per_soldier + total_pop * p.base_food_per_civilian
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
            # Progressive: each 100k troops above 100k adds +50% to base rate.
            # 50k→750, 150k→3,375, 250k→7,500, 400k→15,000, 500k→22,500
            scale_bracket = max(0, (strength - 100000) // 100000)  # 0 for <100k, 1 for 100-200k, etc.
            maint_rate = p.military_maintenance_per_soldier * (1.0 + scale_bracket * 0.5)
            maintenance_cost = int(strength * maint_rate)
            if maintenance_cost > 0:
                treasury_after_maint = max(0, treasury - maintenance_cost)
                actual_cost = treasury - treasury_after_maint
                faction.treasury = treasury_after_maint
                treasury = treasury_after_maint
                if actual_cost > 0:
                    scale_note = f"（大军{scale_bracket+1}级补给）" if scale_bracket > 0 else ""
                    result.notable_events.append(f"{fid}军费{actual_cost}金（兵力{strength}）{scale_note}")

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

    def execute_npc_recruitment(
        self,
        world_state: WorldState,
        result: QuarterResult | None = None,
    ) -> None:
        """Automatic morale-based NPC recruitment — runs every quarter.

        NPC factions DO NOT issue conscript commands through the LLM.
        Instead, recruitment is a deterministic function of population × morale.

        Design: recruitment depends on morale, not treasury.
        - Below 20 morale: desertion (troops leave)
        - 20-30 morale: no recruitment (no volunteers)
        - 30-50 morale: reduced recruitment
        - 50-80 morale: normal rate
        - Above 80 morale: enthusiastic volunteers (+bonus)
        """
        p = self.params
        for fid, faction in world_state.factions.items():
            if fid == world_state.player_faction_id:
                continue
            if not getattr(faction, "is_active", True):
                continue

            total_pop = getattr(faction, "population", 0) or 0
            if total_pop <= 0:
                continue

            morale = getattr(faction, "morale_actual", 50)
            strength = getattr(faction, "strength_actual", 0)
            treasury = getattr(faction, "treasury", 0)

            # ── Apply maintenance FIRST (same progressive rate as execute_quarter) ──
            # Without this, NPCs recruit before paying their army costs,
            # leading to infinite growth at high morale.
            scale_bracket = max(0, (strength - 100000) // 100000)
            maint_rate = p.military_maintenance_per_soldier * (1.0 + scale_bracket * 0.5)
            maintenance_cost = int(strength * maint_rate)
            if maintenance_cost > 0 and treasury > 0:
                actual_maint = min(treasury, maintenance_cost)
                faction.treasury = treasury - actual_maint
                treasury = faction.treasury
                if actual_maint > 500:
                    bracket_note = f"（大军{scale_bracket+1}级补给）" if scale_bracket > 0 else ""
                    if result:
                        result.notable_events.append(
                            f"{fid}自动军费{actual_maint}金（兵力{strength}）{bracket_note}"
                        )

            base_rate = p.dynamic_conscript_ratio(total_pop)

            if morale < 20:
                morale_factor = -0.015  # desertion
            elif morale < 30:
                morale_factor = 0.0  # no recruitment
            elif morale < 50:
                morale_factor = (morale - 30) / 40.0  # 0.0→0.5
            elif morale < 80:
                morale_factor = 0.5 + (morale - 50) / 60.0  # 0.5→1.0
            else:
                morale_factor = 1.0 + (morale - 80) / 100.0  # 1.0→1.2

            recruit_rate = base_rate * max(0, morale_factor)
            raw_amount = int(total_pop * recruit_rate)

            if morale_factor < 0:
                desert = max(int(strength * 0.02), int(total_pop * 0.005))
                if desert > 100:
                    faction.strength_actual = max(500, strength - desert)
                    if result:
                        result.notable_events.append(f"{fid}士气崩溃，逃兵{desert}人")
                continue

            if raw_amount <= 0:
                continue

            # Cost scales inversely with morale — volunteers cost less
            cost_per_soldier = p.conscript_cost * (2.0 - min(morale_factor, 1.2))
            max_affordable = int(treasury / cost_per_soldier) if cost_per_soldier > 0 else raw_amount
            actual = min(raw_amount, max_affordable)

            if actual > 50:
                faction.strength_actual = getattr(faction, "strength_actual", 0) + actual
                faction.treasury = max(0, treasury - actual * cost_per_soldier)
                if result:
                    vol_note = "（义从踊跃）" if morale > 80 else ""
                    result.notable_events.append(
                        f"{fid}自动征兵{actual}人（士气{morale}，花费{actual * cost_per_soldier:.0f}金）{vol_note}"
                    )

    def execute_treasury_penalties(
        self,
        world_state,
        result=None,
        apply_to_player: bool = False,
    ) -> None:
        """Apply progressive penalties for factions with critically low treasury.

        Historical basis: Armies without pay mutiny (e.g. Ming dynasty's frequent
        mutinies when the treasury couldn't pay troops). Officials unpaid for
        months become corrupt or defect. Populations without relief starve.

        Progressive scale:
        - 0 gold for 1 quarter: morale -2, tiny desertion (0.5% troops)
        - 0 gold for 2-3 quarters: morale -5, moderate desertion (2% troops), loyalty crisis
        - 0 gold for 4+ quarters: morale -10, mass desertion (5% troops), potential defection

        Also applies moderate penalties when food=0 or morale < 15.
        """
        for fid, faction in world_state.factions.items():
            if not getattr(faction, "is_active", True):
                continue
            if not apply_to_player and fid == getattr(world_state, "player_faction_id", None):
                continue

            treasury = getattr(faction, "treasury", 0)
            food = getattr(faction, "food", 0)
            morale = getattr(faction, "morale_actual", 50)
            strength = getattr(faction, "strength_actual", 0)

            # ── Treasury penalties (progressive) ──
            if treasury <= 0:
                streak = _treasury_zero_streak.get(fid, 0) + 1
                _treasury_zero_streak[fid] = streak

                if streak == 1:
                    morale_penalty = 2
                    desertion_pct = 0.005  # 0.5%
                    desc = "金库空虚，士卒微有不安"
                elif streak <= 3:
                    morale_penalty = 5
                    desertion_pct = 0.02   # 2%
                    desc = "连续缺饷，军心浮动，逃兵日增"
                else:
                    morale_penalty = 10
                    desertion_pct = 0.05   # 5%
                    desc = "久不發餉，營兵嘩變，將士離心"

                # Apply morale penalty
                new_morale = max(0, morale - morale_penalty)
                faction.morale_actual = new_morale

                # Apply desertion
                if strength > 500:
                    deserters = max(100, int(strength * desertion_pct))
                    faction.strength_actual = max(500, strength - deserters)
                else:
                    deserters = 0

                if result and hasattr(result, "notable_events"):
                    result.notable_events.append(
                        f"{fid}{desc}：士气-{morale_penalty}，逃兵{deserters}人（连续{streak}季无饷）"
                    )
            else:
                # Reset streak when treasury recovers
                if fid in _treasury_zero_streak:
                    del _treasury_zero_streak[fid]

            # ── Food starvation (separate from treasury) ──
            if food <= 0 and strength > 1000:
                starve_loss = max(200, int(strength * 0.03))
                faction.strength_actual = max(500, strength - starve_loss)
                faction.morale_actual = max(0, morale - 3)
                if result and hasattr(result, "notable_events"):
                    result.notable_events.append(
                        f"{fid}粮草断绝，饿殍{starve_loss}人，民心-3"
                    )

            # ── Morale collapse threshold ──
            if morale <= 10 and strength > 5000:
                rout = max(1000, int(strength * 0.10))
                faction.strength_actual = max(500, strength - rout)
                if result and hasattr(result, "notable_events"):
                    result.notable_events.append(
                        f"{fid}民心崩溃，大军溃散{rout}人"
                    )
