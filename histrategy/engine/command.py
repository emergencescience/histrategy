"""
Command Mode — Bureaucracy simulation for 三國志略.

After the player sets a plan (via Plan Mode), Command Mode
simulates the execution through the bureaucracy:
- Ministers carry out the plan
- Short-term consequences are visible immediately
- Long-term "seeds" are planted for future turns
- NPC factions react to the player's actions
"""

from __future__ import annotations

import random
import json
from typing import Optional

from ..state.world_state import WorldState, FactionState, EventEntry, add_event_to_history


# ─── Seed System ──────────────────────────────────────────

PENDING_SEEDS_FILE = "pending_seeds.json"


class CommandMode:
    """
    Simulate the execution of a player's strategic plan.

    Called after Plan Mode resolves the player's intent.
    """

    def __init__(self, state: WorldState):
        self.state = state

    def execute(self, plan: str) -> dict:
        """
        Execute a strategic plan through the bureaucracy.

        Args:
            plan: The player's strategic directive (from Plan Mode)

        Returns:
            dict with bureaucracy_report, aftermath, seeds, events
        """
        faction = self.state.get_player_faction()
        if not faction:
            return self._empty_result()

        # Classify the plan type
        plan_type = self._classify_plan(plan.lower())

        # Generate bureaucracy execution narrative
        bureaucracy = self._generate_bureaucracy(plan, plan_type, faction)

        # Compute short-term effects
        short_term = self._compute_short_term(plan_type, faction)

        # Generate long-term seeds
        seeds = self._generate_seeds(plan_type, plan, faction)

        # NPC reactions
        npc_reactions = self._simulate_npc_reactions(plan_type, faction)

        # Apply short-term effects to faction
        self._apply_effects(faction, short_term)

        # Record the event
        event = EventEntry(
            year=self.state.year,
            season=self.state.current_season,
            turn=self.state.turn,
            description=f"政令：{plan[:80]}",
            type="decision",
            faction_id=self.state.player_faction_id,
            player_decision=plan[:100],
            player_involved=True,
        )
        add_event_to_history(event)

        return {
            "bureaucracy": bureaucracy,
            "short_term": short_term,
            "seeds": seeds,
            "npc_reactions": npc_reactions,
            "plan_type": plan_type,
        }

    def _classify_plan(self, plan: str) -> str:
        """Classify a plan into one of the strategic types."""
        keywords = {
            "military": ["攻", "战", "兵", "军", "征", "讨", "伐", "打", "守", "战",
                        "扩军", "出战", "进兵", "奇袭", "先锋", "将", "杀"],
            "economy": ["赋", "税", "粮", "农", "商", "钱", "金", "银", "屯田",
                       "开仓", "放粮", "水利", "耕作", "商贸", "市集"],
            "diplomacy": ["使", "联", "盟", "交", "和", "结", "拜", "合", "联姻",
                         "出使", "结交", "同盟", "求和", "联姻"],
            "scheme": ["细作", "间", "谍", "密", "潜", "暗", "离间", "刺探",
                      "流言", "散布", "策反", "收买"],
            "domestic": ["民", "政", "法", "官", "城", "学", "教", "招贤",
                        "开仓", "放粮", "抚民", "整顿"],
        }
        scores = {}
        for cat, kws in keywords.items():
            scores[cat] = sum(1 for kw in kws if kw in plan)

        if not scores or max(scores.values()) == 0:
            return "domestic"  # default

        return max(scores, key=scores.get)

    def _generate_bureaucracy(self, plan: str, plan_type: str,
                              faction: FactionState) -> list[dict]:
        """Generate bureaucracy execution narrative for each department."""
        departments = {
            "military": ("军事", [
                f"兵部接令：{plan[:30]}。已调遣{faction.strength//10000}万将士待命",
                f"将军们收到指令后开始部署。斥候已派出，正在探查敌情",
            ]),
            "economy": ("内政", [
                f"户部核算府库：粮{max(faction.food, 0):,}石，金{max(faction.treasury, 0):,}两",
                f"地方官接令后开始{plan[:20]}…",
            ]),
            "diplomacy": ("外交", [
                f"使者已备好国书，即日启程。沿途关卡需加急通行",
                f"鸿胪寺官员奉命出使，携带礼物与盟约文书",
            ]),
            "scheme": ("密探", [
                f"密探已接到指令。他们将化装成商旅，潜入目标地域",
                f"情报网开始运转。第一批回报预计{random.randint(1,4)}个月内送达",
            ]),
            "domestic": ("内政", [
                f"政令送达各州郡。官员们开始筹备执行方案",
                f"公告已贴出，百姓议论纷纷。各地反响不一",
            ]),
        }

        dept_name, dept_lines = departments.get(plan_type, departments["domestic"])

        # Add faction-specific character names
        advisor_names = {
            "cao": "荀彧", "shu": "简雍", "wu": "程普", "yuan_shao": "田丰",
        }
        general_names = {
            "cao": "夏侯惇", "shu": "关羽", "wu": "黄盖", "yuan_shao": "颜良",
        }
        advisor = advisor_names.get(self.state.player_faction_id, "军师")
        general = general_names.get(self.state.player_faction_id, "将军")

        report = [
            {"department": "军师府", "official": advisor,
             "action": f"评估政令「{plan[:30]}」的可行性：{random.choice(['此策可行，但需谨慎', '时机恰当，宜速行', '可徐徐图之', '当先稳固根本'])}"},
            {"department": dept_name, "official": "",
             "action": random.choice(dept_lines)},
            {"department": "将军府", "official": general,
             "action": random.choice([f"收到指令，开始调配兵力。当前总兵力：{faction.strength:,}", f"正在组织行军序列，粮草辎重已开始装运"])},
        ]

        # Add treasury info for economy actions
        if plan_type == "economy":
            report.append({"department": "府库", "official": "",
                          "action": f"盘点国库：资金{faction.treasury:,}，粮草{faction.food:,}。{'尚可支应' if faction.treasury > 5000 else '颇为紧张'}"})

        return report

    def _compute_short_term(self, plan_type: str,
                            faction: FactionState) -> dict:
        """Compute immediate effects of the plan."""
        base = {
            "strength": faction.strength,
            "economy": faction.economy,
            "morale": faction.morale,
            "treasury": faction.treasury,
            "food": faction.food,
        }

        changes = {}

        if plan_type == "military":
            changes["strength"] = int(faction.strength * random.uniform(0.03, 0.08))
            changes["treasury"] = -int(faction.treasury * random.uniform(0.03, 0.08))
            changes["morale"] = random.randint(1, 3)
            changes["food"] = -int(faction.food * random.uniform(0.02, 0.06))
        elif plan_type == "economy":
            changes["economy"] = random.randint(3, 7)
            changes["morale"] = random.randint(1, 3)
            changes["treasury"] = int(faction.treasury * random.uniform(0.01, 0.04))
            changes["food"] = int(faction.food * random.uniform(0.02, 0.05))
        elif plan_type == "diplomacy":
            changes["morale"] = random.randint(1, 2)
            changes["treasury"] = -int(faction.treasury * random.uniform(0.02, 0.05))
        elif plan_type == "scheme":
            changes["treasury"] = -int(faction.treasury * random.uniform(0.02, 0.05))
        elif plan_type == "domestic":
            changes["economy"] = random.randint(1, 3)
            changes["morale"] = random.randint(2, 5)
            changes["food"] = -int(faction.food * random.uniform(0.01, 0.03))

        # Apply changes
        after = {}
        for k, v in base.items():
            delta = changes.get(k, 0)
            after[k] = v + delta

        return {
            "changes": {k: changes.get(k, 0) for k in base.keys()},
            "before": base,
            "after": after,
        }

    def _generate_seeds(self, plan_type: str, plan: str,
                        faction: FactionState) -> list[dict]:
        """Generate long-term consequence seeds."""
        seeds = []

        if plan_type == "military":
            seeds.append({
                "title": "边境紧张",
                "description": f"军事调动引起周边势力警惕。",
                "trigger_after": random.randint(2, 4),
                "type": "diplomatic",
            })
        elif plan_type == "economy":
            seeds.append({
                "title": "经济发展",
                "description": f"政令促进生产，未来几季经济持续增长。",
                "trigger_after": random.randint(1, 3),
                "type": "economic_bonus",
            })
        elif plan_type == "diplomacy":
            seeds.append({
                "title": "外交关系变化",
                "description": f"外交努力正在酝酿……",
                "trigger_after": random.randint(2, 4),
                "type": "diplomatic",
            })
        elif plan_type == "scheme":
            seeds.append({
                "title": "情报行动",
                "description": f"细作已潜入，回报将在数月后送达。",
                "trigger_after": random.randint(1, 3),
                "type": "intelligence",
            })
        elif plan_type == "domestic":
            seeds.append({
                "title": "民心变化",
                "description": f"内政措施对民心的影响将持续数季。",
                "trigger_after": random.randint(1, 2),
                "type": "morale_bonus",
            })

        return seeds

    def _simulate_npc_reactions(self, plan_type: str,
                                faction: FactionState) -> list[str]:
        """Generate reactions from NPC factions."""
        reactions = []

        # Pick a random NPC faction to react
        npc_factions = [f for f_id, f in self.state.factions.items()
                        if f_id != self.state.player_faction_id and f.is_active]
        if not npc_factions:
            return ["天下局势正在微妙变化中……"]

        reactor = random.choice(npc_factions)

        if plan_type == "military":
            reactions.append(f"⚔ {reactor.name}军注意到你的军事调动，也开始集结兵力。")
        elif plan_type == "economy":
            reactions.append(f"🌾 {reactor.name}派出的细作报告了你的内政措施。")
        elif plan_type == "diplomacy":
            if random.random() < 0.5:
                reactions.append(f"🤝 {reactor.name}表示愿意遣使回访。")
            else:
                reactions.append(f"🤨 {reactor.name}对你的示好持观望态度。")
        elif plan_type == "scheme":
            reactions.append(f"🕵 {reactor.name}加强了边境戒备。")
        else:
            reactions.append(f"📜 {reactor.name}继续按自己的步调行事。")

        # Maybe another random event
        if random.random() < 0.3:
            other = random.choice([f for f in npc_factions if f.id != reactor.id] or npc_factions)
            reactions.append(f"🔥 有消息称{other.name}与{reactor.name}之间出现了摩擦。")

        return reactions

    def _apply_effects(self, faction: FactionState, result: dict):
        """Apply state changes to the faction."""
        changes = result.get("changes", {})
        for k, v in changes.items():
            if k in ("changes", "before", "after"):
                continue
            if hasattr(faction, k):
                current = getattr(faction, k)
                setattr(faction, k, current + v)

    def _empty_result(self) -> dict:
        return {
            "bureaucracy": [],
            "short_term": {"changes": {}, "before": {}, "after": {}},
            "seeds": [],
            "npc_reactions": [],
            "plan_type": "domestic",
        }
