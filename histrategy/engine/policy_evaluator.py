"""
V3 PolicyEvaluator — Rule Spec 计算引擎。

根据势力当前生效的政策和科技树，计算本季度各项数值的加成/惩罚。
这是 V3 引擎中"确定性计算"的关键部分，在 QuarterlyEngine 之后、LLM 调整之前运行。

设计原则：
- 政策效果是声明式的（不在代码中硬编码），通过 params dict 控制
- 支持多层政策叠加（屯田制 + 水利工程 → 粮食 × 1.15）
- 输出增量值供 turn_delta 记录
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

logger = logging.getLogger("histrategy.policy_evaluator")

# ── 政策效果定义 ────────────────────────────────────
# 每个政策的效果函数。key = 政策名称，value = 应用到 faction 状态的函数
# 这些是"内置政策"，自定义政策可以通过 params dict 扩展

_BUILTIN_POLICY_EFFECTS: dict[str, dict] = {
    # 经济政策
    "屯田制": {
        "food_multiplier": 1.10,  # 粮食产出 +10%
        "morale_bonus": 2,         # 每季度民心 +2
    },
    "盐铁专营": {
        "treasury_bonus_per_pop": 0.0001,  # 每人口额外税收
        "morale_penalty": -1,               # 垄断引发民怨
    },
    "均田制": {
        "food_multiplier": 1.05,
        "tax_revenue_multiplier": 1.10,
        "morale_bonus": 3,
    },
    # 军事政策
    "征兵令": {
        "conscript_cost_multiplier": 0.7,  # 征兵费用 -30%
        "max_conscript_multiplier": 1.5,    # 征兵上限 +50%
        "morale_penalty": -3,                # 强制征兵引发不满
    },
    "军屯制": {
        "food_multiplier": 1.05,
        "troop_upkeep_multiplier": 0.8,  # 军队维持费 -20%
    },
    # 法律/行政政策
    "九品中正制": {
        "advisor_bonus": 2,       # 谋士效果 +2
        "morale_bonus": 2,
    },
    "科举制": {
        "advisor_bonus": 3,       # 谋士效果 +3
        "tax_revenue_multiplier": 1.05,  # 官僚效率提升
    },
    "察举制": {
        "advisor_bonus": 1,
        "morale_bonus": 1,
    },
    # 外交政策
    "和亲": {
        "diplomacy_bonus": 5,     # 外交关系 +5
        "morale_bonus": 2,
        "treasury_cost": 5000,    # 一次性支出
    },
    "羁縻政策": {
        "territory_stability": 0.8,  # 新占城池稳定性 +20%
    },
}


class PolicyEffect:
    """单个政策的计算结果。"""

    __slots__ = (
        "policy_name",
        "food_delta",
        "treasury_delta",
        "morale_delta",
        "troop_delta",
        "population_delta",
        "multipliers",
        "narrative",
    )

    def __init__(
        self,
        policy_name: str,
        food_delta: float = 0,
        treasury_delta: float = 0,
        morale_delta: int = 0,
        troop_delta: int = 0,
        population_delta: int = 0,
        multipliers: dict | None = None,
        narrative: str = "",
    ):
        self.policy_name = policy_name
        self.food_delta = food_delta
        self.treasury_delta = treasury_delta
        self.morale_delta = morale_delta
        self.troop_delta = troop_delta
        self.population_delta = population_delta
        self.multipliers = multipliers or {}
        self.narrative = narrative


class PolicyEvaluator:
    """V3 政策效果计算器。

    读取 faction 的 active policies → 计算各项加成 → 返回 PolicyEffect 列表。
    """

    def evaluate_faction(
        self,
        ws: WorldState,
        faction_id: str,
    ) -> list[PolicyEffect]:
        """计算一个势力所有生效政策的效果。"""
        faction = ws.factions.get(faction_id)
        if not faction or not faction.is_active:
            return []

        effects: list[PolicyEffect] = []

        # 获取势力当前政策（从 faction 属性或 DB）
        active_policies: dict = getattr(faction, "policies", {})

        for policy_name, policy_params in active_policies.items():
            effect = self._compute_policy_effect(faction, policy_name, policy_params, ws)
            if effect:
                effects.append(effect)

        return effects

    def _compute_policy_effect(
        self,
        faction,
        policy_name: str,
        policy_params: dict,
        ws: WorldState,
    ) -> PolicyEffect | None:
        """计算单个政策的效果。"""
        builtin = _BUILTIN_POLICY_EFFECTS.get(policy_name, {})

        if not builtin and not policy_params:
            return None

        food_delta = 0.0
        treasury_delta = 0.0
        morale_delta = 0
        troop_delta = 0
        population_delta = 0
        multipliers = {}
        narrative_parts = []

        food = faction.food
        treasury = faction.treasury

        # 粮食加成
        food_mult = policy_params.get("food_multiplier", builtin.get("food_multiplier", 0))
        if food_mult != 1.0 and food_mult != 0:
            food_delta = food * (food_mult - 1.0)
            multipliers["food"] = food_mult
            narrative_parts.append(f"{policy_name}：粮食 × {food_mult:.2f}")

        # 税收加成
        tax_mult = policy_params.get(
            "tax_revenue_multiplier",
            builtin.get("tax_revenue_multiplier", 0),
        )
        if tax_mult != 1.0 and tax_mult != 0:
            # 粗略估算：税收 = population × tax_rate × base_rate
            pop = getattr(faction, "population", 100000)
            tax_rate = faction.tax_rate
            base_revenue = pop * tax_rate * 0.0005  # EconomyParams.base_tax_revenue_per_pop
            treasury_delta += base_revenue * (tax_mult - 1.0)
            multipliers["tax_revenue"] = tax_mult
            narrative_parts.append(f"{policy_name}：税收 × {tax_mult:.2f}")

        # 每人口额外税收（盐铁专营等）
        treasury_bonus = policy_params.get(
            "treasury_bonus_per_pop",
            builtin.get("treasury_bonus_per_pop", 0),
        )
        if treasury_bonus > 0:
            pop = getattr(faction, "population", 100000)
            treasury_delta += pop * treasury_bonus
            narrative_parts.append(f"{policy_name}：库金 +{pop * treasury_bonus:.0f}")

        # 民心变化
        morale_bonus = policy_params.get("morale_bonus", builtin.get("morale_bonus", 0))
        morale_penalty = policy_params.get("morale_penalty", builtin.get("morale_penalty", 0))
        morale_delta = morale_bonus + morale_penalty

        # 军队维持费减免
        upkeep_mult = policy_params.get(
            "troop_upkeep_multiplier",
            builtin.get("troop_upkeep_multiplier", 0),
        )
        if upkeep_mult != 1.0 and upkeep_mult != 0:
            troops = getattr(faction, "strength_actual", 0)
            # 每兵每季度消耗 0.01 粮草
            saved_food = troops * 0.01 * (1.0 - upkeep_mult)
            food_delta += saved_food
            narrative_parts.append(f"{policy_name}：军粮节省 {saved_food:.0f}")

        # 一次性支出
        one_time_cost = policy_params.get("treasury_cost", builtin.get("treasury_cost", 0))
        if one_time_cost > 0:
            treasury_delta -= one_time_cost
            narrative_parts.append(f"{policy_name}：支出 {one_time_cost} 金")

        narrative = "；".join(narrative_parts) if narrative_parts else ""

        if food_delta == 0 and treasury_delta == 0 and morale_delta == 0 and troop_delta == 0 and population_delta == 0:
            return None

        return PolicyEffect(
            policy_name=policy_name,
            food_delta=food_delta,
            treasury_delta=treasury_delta,
            morale_delta=morale_delta,
            troop_delta=troop_delta,
            population_delta=population_delta,
            multipliers=multipliers,
            narrative=narrative,
        )

    def apply_effects(
        self,
        ws: WorldState,
        faction_id: str,
        effects: list[PolicyEffect],
    ) -> dict:
        """将政策效果应用到 WorldState 并返回变化摘要。"""
        faction = ws.factions.get(faction_id)
        if not faction:
            return {}

        summary = {
            "food_delta": 0.0,
            "treasury_delta": 0.0,
            "morale_delta": 0,
            "troop_delta": 0,
            "population_delta": 0,
            "narratives": [],
        }

        for effect in effects:
            faction.food += effect.food_delta
            faction.treasury += effect.treasury_delta
            if hasattr(faction, "morale_actual"):
                faction.morale_actual += effect.morale_delta
            if hasattr(faction, "strength_actual"):
                faction.strength_actual += effect.troop_delta
            if hasattr(faction, "population"):
                faction.population += effect.population_delta

            summary["food_delta"] += effect.food_delta
            summary["treasury_delta"] += effect.treasury_delta
            summary["morale_delta"] += effect.morale_delta
            summary["troop_delta"] += effect.troop_delta
            summary["population_delta"] += effect.population_delta
            if effect.narrative:
                summary["narratives"].append(effect.narrative)

        return summary
