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
from pathlib import Path
from typing import TYPE_CHECKING

from histrategy.llm.prompt_loader import MACRO_SIM_SYSTEM

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.engine.quarterly_engine import QuarterResult
    from histrategy.llm.adapter import LLMAdapter

_MACRO_PROMPT_CACHE: dict[tuple, str] = {}


def _load_macro_prompt(scenario: str | None, lang: str = "zh") -> str:
    """Load scenario-specific macro simulator prompt with language selection."""
    cache_key = (scenario, lang)
    if cache_key in _MACRO_PROMPT_CACHE:
        return _MACRO_PROMPT_CACHE[cache_key]

    # Try language-specific prompt first
    if lang == "en":
        candidates = [
            Path(f"scenarios/{scenario}/prompts/macro_simulator_en.md"),
            Path(f"scenarios/{scenario}/prompts/macro_simulator_zh.md"),
            Path(f"scenarios/{scenario}/prompts/macro_simulator.md"),
        ]
    else:
        candidates = [
            Path(f"scenarios/{scenario}/prompts/macro_simulator_zh.md"),
            Path(f"scenarios/{scenario}/prompts/macro_simulator_en.md"),
            Path(f"scenarios/{scenario}/prompts/macro_simulator.md"),
        ]
    for p in candidates:
        if p.is_file():
            _MACRO_PROMPT_CACHE[cache_key] = p.read_text(encoding="utf-8")
            return _MACRO_PROMPT_CACHE[cache_key]
    return MACRO_SIM_SYSTEM


OUTPUT_SCHEMA_HINT = """
仅输出以下四个字段，其余字段（knowledge_cards / black_swan_events / butterfly_effects /
narrative_seeds / diplomatic_reactions / npc_actions）一律不要生成——它们不被引擎消费，
只会拖慢推演。黑天鹅事件由确定性历史引擎单独处理。

## battle_results
[{
  "location": "yangzhou",
  "attacker": "qing", "defender": "nanming",
  "result": "attack_win|defend_win|stalemate|rout",
  "casualties": {"attacker": {"infantry": 3000}, "defender": {"infantry": 8000}},
  "territory_captured": true,
  "narrative": "多铎率八旗主力围扬州，史可法血书求援，城中粮尽..."
}]

## npc_faction_actions
[{
  "faction": "qing",
  "action_type": "declare_war|conscript|develop|diplomacy|tax|naval_blockade|none",
  "target": "nanming",
  "reason": "多尔衮见南明内讧，决意趁势南下",
  "params": {"amount": 50000},
  "narrative": "多尔衮命多铎为定国大将军，率八旗精锐南下，直指扬州"
}]

## morale_events
[{
  "faction": "nanming",
  "change": -8,
  "reason": "扬州失守，江南震动",
  "territories_affected": ["nanjing"]
}]

## political_events
[{
  "faction": "nanming",
  "type": "court_intrigue|reform_feedback|succession|factionalism",
  "description": "马士英构陷史可法，弘光帝下旨掣肘江北四镇粮饷...",
  "effects": {"character_loyalty": {"shikefa": -10}}
}]
"""


class MacroPolicyEngine:
    """LLM-driven quarterly historical simulation."""

    def __init__(self, llm_adapter: LLMAdapter | None = None, scenario: str | None = None, lang: str = "zh"):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available
        self.scenario = scenario
        self.lang = lang

    def simulate(
        self,
        world_state: WorldState,
        policy_commands: list,
        player_decision: str,
        baseline: QuarterResult,
        history_events: list[dict] | None = None,
        turn_memory: list[dict] | None = None,
        epoch_memory: list[dict] | None = None,
        room_id: str = "",
        quarter_number: int = 0,
    ) -> dict:
        """Generate quarterly historical simulation.

        Returns:
            Structured delta dict, or empty dict if LLM unavailable.
        """
        if not self.llm_available or not self.llm:
            return {}

        context = self._build_context(
            world_state,
            policy_commands,
            player_decision,
            baseline,
            history_events or [],
            turn_memory or [],
            epoch_memory or [],
        )

        system_prompt = _load_macro_prompt(self.scenario, self.lang)
        messages = [
            {"role": "system", "content": system_prompt + "\n" + OUTPUT_SCHEMA_HINT},
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
                    "room_id": room_id,
                    "quarter_number": quarter_number,
                },
            )
            # chat_structured may return raw string if json.loads fails
            if isinstance(result, str):
                result = self._extract_json(result)
            return self._validate_output(result)
        except Exception:
            return {}

    # ── Context Builder ────────────────────────────────────

    def _build_context(
        self,
        ws,
        commands,
        decision,
        baseline,
        history_events,
        turn_memory,
        epoch_memory,
    ) -> str:
        lines = []

        season = getattr(baseline, "season_name", None) or "?"
        year = getattr(baseline, "year", ws.year) if baseline else ws.year
        lines.append(f"## 当前时间\n{year}年{season} | 第{ws.turn_number}季度\n")

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
            aggression = getattr(f, "aggression", 0.5)
            caution = getattr(f, "caution", 0.5)
            personality = getattr(f, "personality", "")
            lines.append(
                f"- {fid} ({f.name}): "
                f"兵力={getattr(f, 'strength_actual', 0)}, "
                f"资金={f.treasury}, 粮草={f.food}, "
                f"民心={getattr(f, 'morale_actual', 0)}, "
                f"税率={getattr(f, 'tax_rate', 0.3):.0%}, "
                f"领地={territories}" + (f", 性格=agg{aggression:.1f} cau{caution:.1f}" if personality else "")
            )
        lines.append("")

        # Highlight NPC factions for independent decision-making
        # Skip passive factions (刘璋龟缩益州, 刘表保守观望) — they don't need AI decisions
        PASSIVE_NPC_FACTIONS = {"liuzhang", "liubiao"}
        player_fid = ws.player_faction_id
        npc_factions = [
            fid
            for fid in ws.factions
            if fid != player_fid and fid not in PASSIVE_NPC_FACTIONS and getattr(ws.factions[fid], "is_active", True)
        ]
        if npc_factions:
            lines.append("## ⚡ NPC自主决策（必须为每个活跃NPC做出至少一项独立行动）")
            lines.append("请为以上每个NPC势力输出至 npc_faction_actions 字段。")
            lines.append("NPC不应被动——曹操会扩张，孙权会巩固，刘表会权衡。")
            lines.append("若NPC宣战，需在 battle_results 中推演战役结果。")
            lines.append("NPC之间的战争同样重要——例如刘璋vs张鲁的汉中争夺。")
            lines.append("")

        lines.append("## 确定性经济基线")
        for fid in ws.factions:
            if not getattr(ws.factions[fid], "is_active", True):
                continue
            fname = ws.factions[fid].name
            tax = getattr(baseline, "tax_revenue", {}).get(fid, 0)
            food = getattr(baseline, "food_delta", {}).get(fid, 0)
            morale = getattr(baseline, "morale_delta", {}).get(fid, 0)
            pop = getattr(baseline, "population_delta", {}).get(fid, 0)
            lines.append(f"- {fid} ({fname}): 税收+{tax:.0f}, 粮草{food:+.0f}, 民心{morale:+d}, 人口{pop:+.0f}")
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
            "npc_faction_actions": result.get("npc_faction_actions", []),
            "morale_events": result.get("morale_events", []),
            "political_events": result.get("political_events", []),
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
