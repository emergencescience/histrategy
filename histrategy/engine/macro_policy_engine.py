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


OUTPUT_SCHEMA_HINT = """\
仅输出{battle_results,npc_faction_actions,morale_events,political_events}四个字段。
禁止输出knowledge_cards/black_swan/narrative_seeds/diplomatic_reactions等额外字段。

## npc_faction_actions
[{"faction":"cao","action_type":"develop|diplomacy|tax|declare_war|none","target":"shu","reason":"...","params":{},"narrative":"曹操命..."}]
注意：NPC征兵由游戏引擎自动根据士气+人口计算，LLM无需生成conscript动作。

## battle_results
[{"location":"xinye","attacker":"cao","defender":"shu","result":"attack_win|defend_win|stalemate|rout","territory_captured":true,"narrative":"..."}]

## morale_events
[{"faction":"shu","change":5,"reason":"...","territories_affected":["xinye"]}]

## political_events
[{"faction":"cao","type":"court_intrigue|reform_feedback|succession|factionalism","description":"...","effects":{"character_loyalty":{"xunyu":-5}}}]
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
            quarter_number=quarter_number,
        )

        system_prompt = _load_macro_prompt(self.scenario, self.lang) or ""
        messages = [
            {"role": "system", "content": system_prompt + "\n" + OUTPUT_SCHEMA_HINT},
            {"role": "user", "content": context},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=3500,
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
            validated = self._validate_output(result)

            # ── No hard enforcement: let narrative constraints guide NPC behavior ──
            # Previously, Q1-Q2 had hardcoded no-war constraints that also
            # blocked the PLAYER's commands (e.g. Cao Cao attacking Xinye).
            # Removed per user directive: use narrative/historical context
            # (north not yet pacified, attacking alerts Liu Biao) instead of
            # hard blocks that corrupt world_state serialization.

            return validated
        except Exception as e:
            import logging
            _log = logging.getLogger("histrategy.macro")
            _log.error(
                "[room=%s Q%d] macro_sim LLM call failed: %s",
                room_id, quarter_number, e, exc_info=True,
            )
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
        quarter_number: int = 0,
    ) -> str:
        lines = []

        season = getattr(baseline, "season_name", None) or "?"
        year = getattr(baseline, "year", ws.year) if baseline else ws.year
        lines.append(f"## 当前时间\n{year}年{season} | 第{quarter_number}季度\n")

        # ── Historical narrative constraints (soft guidance, not hard blocks) ──
        if quarter_number <= 2:
            lines.append("## ⚠️ 历史背景约束 — 请作为NPC决策的重要参考")
            if quarter_number == 1:
                lines.append("- 曹操刚定河北，袁绍残部（袁尚、袁谭）及乌桓尚未彻底平定，北方根基未固。")
                lines.append("- 此时若贸然南下攻击刘备，可能激怒刘表、打草惊蛇，促使荆襄各方提前联合。")
                lines.append("- 且新野距宛城虽近，但刘备有关羽张飞为将，诸葛亮为辅，非轻易可取。")
                lines.append("- 历史上曹操在彻底平定河北（207年）后才于208年南征。当前时序尚未到此。")
                lines.append("- 建议NPC势力以征兵、屯田、外交为主，酝酿战略态势而非仓促开战。")
            elif quarter_number == 2:
                lines.append("- 北方局势稍稳但仍需警惕。袁氏残余与乌桓仍有扰动可能。")
                lines.append("- 曹操可对刘表施加外交压力（diplomacy threaten），试探荆襄态度。")
                lines.append("- 孙权正巩固江夏新占，不宜两面树敌。可继续整训水师。")
                lines.append("- 小规模边缘战斗（NPC vs NPC）可以发生，但大规模诸侯之战需审慎。")
            lines.append("")

        lines.append("## 玩家策令")
        lines.append(decision)
        lines.append("")

        if commands:
            lines.append("## 结构化策令")
            for cmd in commands:
                if isinstance(cmd, str):
                    lines.append(f"- {cmd}")
                else:
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
