"""
Macro Policy Engine — LLM-driven quarterly historical simulation.

Replaces the battle-focused WorldSimulator. Instead of overriding
individual battle outcomes, this generates a full quarter's worth of
historical events: battle results, diplomatic reactions, black swan
events, and narrative seeds.

Input: WorldState + PolicyCommands + deterministic QuarterResult
Output: Structured delta with battle outcomes, morale events, 
        political events, NPC actions, butterfly effects,
        knowledge cards, and narrative seeds.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from histrategy.llm.prompt_loader import load_prompt

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter
    from histrategy.engine.quarterly_engine import QuarterResult

MACRO_SIM_SYSTEM = load_prompt("macro_simulator.md", default="""\
你是《三國志略》的太史令（Macro Historical Simulator）。你负责基于玩家的季度策令和确定性经济基线，推演一个季度内的历史事件。

## 你的职责

1. **战争推演** — 如果有宣战，根据兵力对比、地形、季节、将领，推演战役结果。不是算数值，是推演历史叙事。
2. **外交反应** — NPC 势力根据玩家的行动做出外交反应。
3. **黑天鹅事件** — 根据历史引力（historical gravity），决定哪些正史事件在此季度触发，以及偏离度。
4. **政治事件** — 朝堂内部的派系斗争、人事变动、政策反馈。
5. **知识卡片** — 为本季度涉及的历史制度、人物、事件生成知识卡片。

## 核心原则

- **历史真实感优先** — 不是"5K vs 5K = defeat"，而是"15万大军南下，刘表恰于此时病亡，刘琮投降"
- **蝴蝶效应** — 玩家的每个策令都可能改变历史轨迹
- **涌现而非编排** — 不要预设结果，让状态自然涌现

## 输出格式

输出一个 JSON 对象，包含以下字段：

```json
{
  "battle_results": [...],       // 战斗结果（如有宣战）
  "diplomatic_reactions": [...], // NPC 外交反应
  "black_swan_events": [...],    // 触发的历史事件
  "political_events": [...],     // 朝堂政治事件
  "morale_events": [...],        // 民心变化事件
  "npc_actions": [...],          // NPC 自主行动
  "butterfly_effects": [...],    // 蝴蝶效应
  "narrative_seeds": [...],      // 叙事种子
  "knowledge_cards": [...]       // 知识卡片
}
```

详细的字段 schema 见下方。
""")

OUTPUT_SCHEMA_HINT = """
## battle_results
[{
  "location": "xiangyang",
  "attacker": "cao", "defender": "liubiao",
  "result": "attack_win|defend_win|stalemate|rout",
  "casualties": {"attacker": {"infantry": 3000}, "defender": {"infantry": 8000}},
  "territory_captured": true,
  "commander_performance": {"xiahouyuan": "英勇冲锋，率先登城"},
  "narrative": "刘表病亡消息传到襄阳，刘琮畏战..."
}]

## diplomatic_reactions
[{
  "faction": "wu",
  "reaction": "alarmed|pleased|neutral|hostile",
  "action": "孙权紧急召见周瑜鲁肃...",
  "relation_delta": {"cao": -10, "shu": +15}
}]

## black_swan_events
[{
  "event_id": "liubiao_death_208",
  "triggered": true,
  "outcome": "刘表病亡，次子刘琮继位...",
  "effects": {"liubiao_dead": true, "jingzhou_owner": "cao"}
}]

## political_events
[{
  "faction": "cao",
  "type": "court_intrigue|reform_feedback|succession|factionalism",
  "description": "荀彧对曹操称公之议表示反对...",
  "effects": {"character_loyalty": {"xunyu": -20}}
}]

## morale_events
[{
  "faction": "cao",
  "change": 5,
  "reason": "减税政策深得民心",
  "territories_affected": ["xuchang", "ye"]
}]

## npc_actions
[{
  "faction": "shu",
  "action": "刘备派遣诸葛亮出使东吴，游说孙权联合抗曹",
  "effects": {"wu_shu_relation": +10}
}]

## butterfly_effects
[{
  "cause": "玩家提前实行屯田制",
  "effect": "北方粮食产量提前5年达到历史水平，加快了曹操统一北方的经济基础",
  "magnitude": "medium"
}]

## narrative_seeds
["曹操不战而得荆州，天下震动", "刘备仓皇南逃，百姓十余万跟随"]

## knowledge_cards
[{
  "topic": "屯田制",
  "historical_source": "《三国志·魏书·武帝纪》",
  "source_quote": "是岁，乃兴屯田...",
  "modern_scholarship": "田余庆认为屯田制的核心是人口控制...",
  "scholar": "田余庆",
  "scholar_work": "《秦汉魏晋史探微》",
  "engine_logic": "屯田制: 粮食产出+30%, 民心+5",
  "related_topics": ["均田制", "府兵制", "曹操经济政策"]
}]
"""


class MacroPolicyEngine:
    """LLM-driven quarterly historical simulation."""

    def __init__(self, llm_adapter: LLMAdapter | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available

    def simulate(
        self,
        world_state: WorldState,
        policy_commands: list,
        player_decision: str,
        baseline: QuarterResult,
        history_events: list[dict] | None = None,
        turn_memory: list[dict] | None = None,
        epoch_memory: list[dict] | None = None,
    ) -> dict:
        """Generate quarterly historical simulation.

        Returns:
            Structured delta dict, or empty dict if LLM unavailable.
        """
        if not self.llm_available or not self.llm:
            return {}

        context = self._build_context(
            world_state, policy_commands, player_decision,
            baseline, history_events or [],
            turn_memory or [], epoch_memory or [],
        )

        messages = [
            {"role": "system", "content": MACRO_SIM_SYSTEM + "\n" + OUTPUT_SCHEMA_HINT},
            {"role": "user", "content": context},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4096,
                metadata={
                    "category": "macro_sim",
                    "reason": "quarterly_simulation",
                },
            )
            return self._validate_output(result)
        except Exception:
            try:
                result = self.llm.chat(
                    messages, temperature=0.3, max_tokens=4096,
                )
                return self._validate_output(self._extract_json(result))
            except Exception:
                return {}

    # ── Context Builder ────────────────────────────────────

    def _build_context(
        self, ws, commands, decision, baseline,
        history_events, turn_memory, epoch_memory,
    ) -> str:
        lines = []

        season = baseline.season_name or "?"
        lines.append(f"## 当前时间\n{baseline.year}年{season} | 第{ws.turn_number}季度\n")

        lines.append("## 玩家策令")
        lines.append(decision)
        lines.append("")

        if commands:
            lines.append("## 结构化策令")
            for cmd in commands:
                n = getattr(cmd, "notes", "")
                p = json.dumps(getattr(cmd, "params", {}), ensure_ascii=False)
                lines.append(f"- {cmd.type}: {p}" + (f"  // {n}" if n else ""))
            lines.append("")

        lines.append("## 势力状态")
        for fid, f in ws.factions.items():
            if not getattr(f, "is_active", True):
                continue
            territories = list(f.territories) if f.territories else []
            lines.append(
                f"- {fid} ({f.name}): "
                f"兵力={getattr(f, 'strength_actual', 0)}, "
                f"资金={f.treasury}, 粮草={f.food}, "
                f"民心={getattr(f, 'morale_actual', 0)}, "
                f"税率={getattr(f, 'tax_rate', 0.3):.0%}, "
                f"领地={territories}"
            )
        lines.append("")

        lines.append("## 确定性经济基线")
        for fid in ws.factions:
            if not getattr(ws.factions[fid], "is_active", True):
                continue
            fname = ws.factions[fid].name
            tax = baseline.tax_revenue.get(fid, 0)
            food = baseline.food_delta.get(fid, 0)
            morale = baseline.morale_delta.get(fid, 0)
            pop = baseline.population_delta.get(fid, 0)
            lines.append(
                f"- {fid} ({fname}): 税收+{tax:.0f}, 粮草{food:+.0f}, "
                f"民心{morale:+d}, 人口{pop:+.0f}"
            )
        lines.append("")

        if history_events:
            lines.append("## 本季度历史事件候选")
            for evt in history_events:
                lines.append(f"- {evt.get('event_id', '?')}: {evt.get('title', '?')}")
            lines.append("")

        if turn_memory:
            lines.append("## 历史记忆")
            for mem in turn_memory[-5:]:
                lines.append(f"  {mem.get('outcome_summary', '')}")
            lines.append("")

        return "\n".join(lines)

    # ── Output Validation ──────────────────────────────────

    def _validate_output(self, result: dict) -> dict:
        if not isinstance(result, dict):
            return {}

        validated = {
            "battle_results": result.get("battle_results", []),
            "diplomatic_reactions": result.get("diplomatic_reactions", []),
            "black_swan_events": result.get("black_swan_events", []),
            "political_events": result.get("political_events", []),
            "morale_events": result.get("morale_events", []),
            "npc_actions": result.get("npc_actions", []),
            "butterfly_effects": result.get("butterfly_effects", []),
            "narrative_seeds": result.get("narrative_seeds", []),
            "knowledge_cards": result.get("knowledge_cards", []),
        }
        for key in validated:
            if not isinstance(validated[key], list):
                validated[key] = []

        return validated

    @staticmethod
    def _extract_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        import re
        match = re.search(r"```(?:json)?\s*\n?({.*?})\n?\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return {}
