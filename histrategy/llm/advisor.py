"""Strategic Advisor — unified AI counselor for players and NPCs.

Implements the 'AI 军师' pattern: a single class that provides strategic
analysis to both human players (via natural language Q&A) and NPC factions
(via structured command weights).

Key design principle (from asymmetric-loop-design.md):
  Human player and NPC planner are SYMMETRIC. Both receive a LocalWorldState
  (limited fog-of-war view) and faction personality traits. The only
  difference is the output format: text for humans, JSON weights for NPCs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapter import LLMAdapter


from .prompt_loader import ADVISOR_SYSTEM, ADVISOR_SYSTEM_EN


@dataclass
class AdvisorRecommendation:
    """A single strategic recommendation."""

    action: str  # attack, defend, recruit, develop, ally, sabotage, move
    target: str
    priority: float  # 0.0 - 1.0
    reason: str


class StrategicAdvisor:
    """Unified AI advisor for both human players and NPC AI.

    Symmetric design: human players get text advice, NPCs get structured
    command weights. Both use the same LLM and projected LocalWorldState.
    """

    def __init__(self, llm: LLMAdapter, language: str = "zh"):
        self._llm = llm
        self._language = language
        self._is_en = language.startswith("en")

    @property
    def is_available(self) -> bool:
        return self._llm is not None and self._llm.is_available

    def advise_player(
        self,
        local_state: dict,
        personality: dict | None = None,
        query: str = "",
    ) -> str:
        """Provide natural language advice to a human player.

        Args:
            local_state: Projected LocalWorldState (fog-of-war view)
            personality: Optional faction personality profile
            query: Player's question (e.g., "我军现在进攻宛城胜算几何？")

        Returns:
            Advisor's response in natural language (100-200 chars)
        """
        if not self.is_available:
            return self._offline_advice(local_state, query)

        context = self._build_context(local_state, personality, query)
        messages = [
            {"role": "system", "content": ADVISOR_SYSTEM_EN if self._is_en else ADVISOR_SYSTEM},
            {"role": "user", "content": context},
        ]
        metadata = {
            "turn": local_state.get("turn", 0),
            "year": local_state.get("year", 207),
            "season": (
                local_state.get("season").value
                if hasattr(local_state.get("season"), "value")
                else str(local_state.get("season", "spring"))
            ),
            "category": "npc_decision",
            "reason": "advise_player",
            "faction_id": local_state.get("faction_id", ""),
        }
        try:
            return self._llm.chat(messages, temperature=0.7, max_tokens=1024, metadata=metadata)
        except Exception:
            return self._offline_advice(local_state, query)

    def advise_player_structured(
        self,
        local_state: dict,
        personality: dict | None = None,
        goal: str = "",
    ) -> dict:
        """Return structured strategic advice as JSON.

        Returns a dict with:
          - analysis: 2-3 sentence strategic assessment
          - suggestions: list of 3 {title, description, command}
            where 'command' is a ready-to-execute decree the player
            can send directly (bypasses keyword parse).

        Args:
            goal: Player's stated strategic goal (from the input box). When
                provided, the advisor evaluates its feasibility and either
                tailors the three strategies around it, or points out that the
                goal is infeasible (e.g. attacking a city that doesn't exist).
                When empty, falls back to generic three-strategy advice.

        Used by the /advisor API endpoint for the manual "军师" button.
        """
        if not self.is_available:
            return self._offline_structured(local_state, personality)

        context = self._build_context(local_state, personality, "")
        system = ADVISOR_SYSTEM_EN if self._is_en else ADVISOR_SYSTEM

        # ── P1-2: 注入玩家目标 ──
        # 若玩家在输入框写下了战略目标，军师必须针对该目标评估可行性：
        #   - 目标可行 → 三条策略围绕该目标展开
        #   - 目标不可行（如攻打不存在的城、实力悬殊）→ 明确点破，而非顺着编
        goal_instruction = ""
        if goal and goal.strip():
            if self._is_en:
                goal_instruction = (
                    f"\n\nThe commander has stated this goal: \"{goal.strip()}\".\n"
                    "Evaluate its FEASIBILITY first. If the goal targets a city/faction "
                    "that does not exist on this map, or is wildly beyond our current "
                    "strength, you MUST say so plainly in the analysis — do NOT invent "
                    "a path to an impossible goal. If the goal IS feasible, tailor all "
                    "three strategies around achieving it.\n"
                )
            else:
                goal_instruction = (
                    f"\n\n主公当前提出的目标是：「{goal.strip()}」。\n"
                    "请先评估此目标的可行性。若该目标指向的城池/势力根本不存在于当前地图，"
                    "或远超我方当前实力，你必须在 analysis 中**明确点破**此目标不可行，"
                    "切勿为一个不可能的目标编造实现路径。若目标可行，则三条建议应围绕该目标展开。\n"
                )
        system += goal_instruction

        # Structured output instruction
        if self._is_en:
            output_instruction = (
                "\n\nOutput a JSON object with exactly this structure:\n"
                '{"analysis": "2-3 sentence strategic assessment citing concrete numbers", '
                '"suggestions": ['
                '{"title": "≤8 word title", "description": "why this strategy (cite numbers)", '
                '"command": "exact decree the player can copy-paste and send"}, ...]}\n'
                "Provide exactly 3 suggestions ranked from best to riskiest.\n"
                "Accuracy over literary flair: plain is better than vague.\n"
                "Every 'command' must contain BOTH a concrete number (e.g. 'recruit 20000 troops', "
                "'lower tax to 20%', 'send 5000 grain') AND a clear target "
                "(e.g. 'attack Xuzhou', 'ally with Zheng', 'crush the rebels').\n"
                "Forbidden: vague commands like 'recruit', 'strengthen defenses', 'develop economy'.\n"
                "The 'command' field must be a complete, self-contained decree "
                "that a player can send without modification."
            )
        else:
            output_instruction = (
                "\n\n请输出严格的JSON格式（不要markdown代码块），结构如下：\n"
                '{"analysis": "2-3句战略分析，必须引用当前人口、兵力、资金、粮草、民心/士气的具体数值", '
                '"suggestions": ['
                '{"title": "≤8字标题", "description": "此策为何可行（引用具体数值论证）", '
                '"command": "玩家可直接照抄发送的完整政令"}, ...]}\n'
                "必须提供恰好3条建议（上策、中策、下策），按优劣排序。\n"
                "⚠️ 准确性比文学性更重要：宁可平实，不可含糊。\n"
                "每条建议的 command 字段必须同时包含：\n"
                "  (1) 明确的数值——如「征兵两万」「税率降至二成」「拨粮五千石」「动员三成民力」；\n"
                "  (2) 明确的攻击或联合对象——如「攻取徐州」「与郑氏结盟」「讨伐农民军」「联合南明」。\n"
                "严禁写出「征兵」「加强防线」「发展经济」「巩固国防」这类无数字、无对象的空泛政令。\n"
                "command 字段必须是玩家可不加修改直接发送的完整政令。\n"
                "⚠️ 三条建议必须是不同方向的策略（如：外交、军事、内政各一），不可三条都在说同一件事。\n"
                "若上次建议中有未生效的，本次必须替换为全新方向。\n"
                "若民心低（<40），至少一条建议涉及减税/屯田/赈济等恢复民心之策。\n"
                "若粮草低（<1000），至少一条建议涉及屯田/购粮/发展农业。\n"
            )

        messages = [
            {"role": "system", "content": system + output_instruction},
            {"role": "user", "content": context},
        ]
        metadata = {
            "turn": local_state.get("turn", 0),
            "year": local_state.get("year", 207),
            "season": (
                local_state.get("season").value
                if hasattr(local_state.get("season"), "value")
                else str(local_state.get("season", "spring"))
            ),
            "category": "advisor",
            "reason": "advise_player_structured",
            "faction_id": local_state.get("faction_id", ""),
        }
        try:
            result = self._llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=800,
                metadata=metadata,
            )
            return self._validate_structured(result)
        except Exception:
            return self._offline_structured(local_state, personality)

    def _validate_structured(self, raw: dict) -> dict:
        """Validate and normalize structured advisor output."""
        analysis = str(raw.get("analysis", ""))
        suggestions = raw.get("suggestions", [])
        if not isinstance(suggestions, list) or len(suggestions) == 0:
            suggestions = [{"title": "谨慎行事", "description": "暂无明确策略", "command": "固守待变"}]
        normalized = []
        for s in suggestions[:3]:
            normalized.append({
                "title": str(s.get("title", ""))[:20],
                "description": str(s.get("description", ""))[:80],
                "command": str(s.get("command", "")),
            })
        while len(normalized) < 3:
            normalized.append({"title": "", "description": "", "command": ""})
        return {"analysis": analysis, "suggestions": normalized}

    def _offline_structured(self, local_state: dict, personality: dict | None = None) -> dict:
        """Offline fallback structured advice."""
        my = local_state.get("my", {})

        if self._is_en:
            analysis = "No AI advisor available. Basic heuristic analysis follows."
            suggestions = [
                {"title": "Consolidate", "description": "Strengthen economy and defenses",
                 "command": f"Develop agriculture and recruit troops in {', '.join(my.get('territories', ['capital']))}"},
                {"title": "Scout", "description": "Gather intelligence on neighbors",
                 "command": "Send scouts to assess neighboring forces"},
                {"title": "Diplomacy", "description": "Seek alliances for security",
                 "command": "Send envoys to potential allies"},
            ]
        else:
            analysis = "离线模式：基于规则的战略建议（无LLM）"
            suggestions = [
                {"title": "固本培元", "description": "发展经济，巩固防线",
                 "command": f"在{', '.join(my.get('territories', ['主城']))}发展农业，招募民兵"},
                {"title": "刺探军情", "description": "探查邻国虚实",
                 "command": "派遣斥候探查周边势力动向"},
                {"title": "合纵连横", "description": "寻求外交同盟",
                 "command": "派遣使节出访邻国，寻求盟约"},
            ]

        return {"analysis": analysis, "suggestions": suggestions}

    def advise_player_stream(
        self,
        local_state: dict,
        personality: dict | None = None,
        query: str = "",
    ):
        """Stream strategic advice to a human player via SSE.

        Yields text chunks as they arrive from the LLM. Falls back to
        offline advice as a single chunk on failure.
        """
        if not self.is_available:
            yield self._offline_advice(local_state, query)
            return

        context = self._build_context(local_state, personality, query)
        messages = [
            {"role": "system", "content": ADVISOR_SYSTEM_EN if self._is_en else ADVISOR_SYSTEM},
            {"role": "user", "content": context},
        ]
        metadata = {
            "turn": local_state.get("turn", 0),
            "year": local_state.get("year", 207),
            "season": (
                local_state.get("season").value
                if hasattr(local_state.get("season"), "value")
                else str(local_state.get("season", "spring"))
            ),
            "category": "npc_decision",
            "reason": "advise_player_stream",
            "faction_id": local_state.get("faction_id", ""),
        }
        try:
            yield from self._llm.chat_stream(
                messages, temperature=0.7, max_tokens=1024, metadata=metadata
            )
        except Exception:
            yield self._offline_advice(local_state, query)

    def evaluate_strategy(
        self,
        local_state: dict,
        personality: dict | None = None,
        query: str | None = None,
    ) -> dict:
        """Unified entry point for both human and NPC strategic analysis.

        Args:
            local_state: Projected LocalWorldState dict
            personality: Faction personality profile (aggression, caution, etc.)
            query: If provided, returns text advice. If None, returns JSON weights.

        Returns:
            dict with 'analysis', 'recommendations', 'risk_assessment' keys.
            When query is set, also includes 'advice' text field.
        """
        if query:
            # Human player asking a question
            text = self.advise_player(local_state, personality, query)
            return {
                "analysis": text,
                "recommendations": [],
                "risk_assessment": "",
                "advice": text,
            }

        if not self.is_available:
            return self._offline_strategy(local_state, personality)

        context = self._build_context(local_state, personality, "")
        # Add instruction for structured output
        context += "\n\n请输出JSON格式的战略分析（无query模式）。"

        messages = [
            {"role": "system", "content": ADVISOR_SYSTEM_EN if self._is_en else ADVISOR_SYSTEM},
            {"role": "user", "content": context},
        ]
        metadata = {
            "turn": local_state.get("turn", 0),
            "year": local_state.get("year", 207),
            "season": (
                local_state.get("season").value
                if hasattr(local_state.get("season"), "value")
                else str(local_state.get("season", "spring"))
            ),
            "category": "npc_decision",
            "reason": "evaluate_strategy",
            "faction_id": local_state.get("faction_id", ""),
        }
        try:
            raw = self._llm.chat(messages, temperature=0.5, max_tokens=512, metadata=metadata)
            return self._parse_strategy_json(raw)
        except Exception:
            return self._offline_strategy(local_state, personality)

    def _build_context(
        self,
        local_state: dict,
        personality: dict | None,
        query: str = "",
    ) -> str:
        """Build LLM context from LocalWorldState."""
        parts = []
        en = self._is_en

        # Scenario grounding: prevent cross-era hallucination.
        _SCEN_LABELS = {
            "nanming": "山河鼎革（南明弘光，公元1645年）",
            "three-kingdoms": "三國志略（东汉末年，公元207年）",
            "rome-triumvirate": "罗马三头同盟",
        }
        _SCEN_LABELS_EN = {
            "nanming": "The Ming-Qing Transition (Southern Ming, 1645 AD)",
            "three-kingdoms": "Three Kingdoms (Late Han, 207 AD)",
            "rome-triumvirate": "Roman Triumvirate (Late Republic, 44 BC)",
        }
        scenario = local_state.get("scenario", "")
        if scenario:
            label = _SCEN_LABELS_EN.get(scenario, scenario) if en else _SCEN_LABELS.get(scenario, scenario)
            if en:
                parts.append(
                    f"## Current Scenario\n{label}. You may ONLY mention factions and characters "
                    f"listed in the intelligence below. Never reference factions from other eras.\n"
                )
            else:
                parts.append(
                    f"## 当前剧本\n{label}。你只能提及下方情报中列出的势力与人物，"
                    f"切勿套用其他时代（如三国）的势力或人物名号。\n"
                )

        my = local_state.get("my", {})
        faction_id = local_state.get("faction_id", "?")
        faction_name = faction_id
        if personality and personality.get("name"):
            faction_name = f"{personality.get('name')} ({faction_id})"

        if en:
            parts.append(
                f"## My Intelligence\n"
                f"- My faction: {faction_name}\n"
                f"- Population: {my.get('population', '?')}\n"
                f"- Troops: {my.get('strength', '?')}\n"
                f"- Army composition: {my.get('army_composition', 'all infantry')}\n"
                f"- Treasury: {my.get('treasury', '?')}\n"
                f"- Food: {my.get('food', '?')}\n"
                f"- Economy: {my.get('economy', '?')}\n"
                f"- Morale: {my.get('morale', '?')}\n"
                f"- Tax rate: {my.get('tax_rate', '?')}\n"
                f"- Territories: {', '.join(my.get('territories', []))}"
            )
        else:
            parts.append(
                f"## 我方情报\n"
                f"- 我方势力: {faction_name}\n"
                f"- 人口: {my.get('population', '?')}\n"
                f"- 兵力: {my.get('strength', '?')}\n"
                f"- 兵种构成: {my.get('army_composition', '全部步兵')}\n"
                f"- 资金: {my.get('treasury', '?')}\n"
                f"- 粮草: {my.get('food', '?')}\n"
                f"- 经济: {my.get('economy', '?')}\n"
                f"- 民心/士气: {my.get('morale', '?')}\n"
                f"- 税率: {my.get('tax_rate', '?')}\n"
                f"- 领地: {', '.join(my.get('territories', []))}"
            )

        # ── Critical Stats Analysis ──
        morale = int(my.get('morale', 50))
        food_val = float(my.get('food', 5000))
        treasury_val = float(my.get('treasury', 5000))
        tax_rate = float(my.get('tax_rate', 0.3))
        population = int(my.get('population', 0))
        strength = int(my.get('strength', 0))

        concerns = []
        if morale < 40:
            concerns.append(f"⚠️ 民心低迷（{morale}/100）。提升方法：①减税（当前税率{tax_rate:.0%}，高于20%会压制民心）"
                           f" ②发展农业提高粮草盈余 ③取得军事胜利 ④赈济百姓。民心影响征兵速度与战力。")
        elif morale < 60:
            concerns.append(f"⚡ 民心中等（{morale}/100）。维持税率≤30%，避免连年征战即可稳步恢复。")
        if food_val < 1000:
            concerns.append(f"⚠️ 粮草告急（{food_val:.0f}）。立即推行屯田制，或在领地发展农业。冬季粮耗增加30%，需提前储粮。")
        if treasury_val < 1000:
            concerns.append(f"⚠️ 国库空虚（{treasury_val:.0f}）。提高税收可增收，但会压制民心。或通过扩张领土增加税基。")
        if population > 0 and strength > population * 0.15:
            concerns.append(f"⚡ 兵力占人口{strength/population*100:.1f}%，接近动员上限。过多征兵将压缩劳动力，影响粮食产出。")

        if concerns:
            if en:
                parts.append("\n## Critical Concerns\n" + "\n".join(concerns))
            else:
                parts.append("\n## 当前隐患\n" + "\n".join(concerns))

        # ── Improvement Guide (always show) ──
        guide_lines = []
        if morale < 80:
            guide_lines.append("- 民心提升：减税（每降10%税≈+3民心/季）、屯田（+5民心）、打胜仗（+5民心）")
        if food_val < 5000:
            guide_lines.append("- 粮草提升：发展农业、推行屯田制（+30%粮食产出）、秋季收获季产出最高")
        if treasury_val < 5000:
            guide_lines.append("- 资金提升：提高税收率、扩张领土增加税基、盐铁专卖（+15%税收）")

        if guide_lines:
            if en:
                parts.append("\n## Improvement Reference\n" + "\n".join(guide_lines))
            else:
                parts.append("\n## 提升参考\n" + "\n".join(guide_lines))

        perceived = local_state.get("perceived", {})
        if perceived:
            if en:
                parts.append("\n## Strategic Landscape (Local Intelligence)")
                for _fid, pf in perceived.items():
                    border = "Bordering" if pf.get("is_border") else "Distant"
                    ally = " [Ally]" if pf.get("is_allied") else ""
                    parts.append(
                        f"- {pf['name']}{ally} ({border}): "
                        f"~{pf.get('strength', '?')} troops, "
                        f"{pf.get('territories', '?')} territories"
                    )
            else:
                parts.append("\n## 天下态势（局部情报）")
                for _fid, pf in perceived.items():
                    border = "接壤" if pf.get("is_border") else "远方"
                    ally = " [盟友]" if pf.get("is_allied") else ""
                    parts.append(
                        f"- {pf['name']}{ally}（{border}）："
                        f"兵力约 {pf.get('strength', '?')}，"
                        f"领地 {pf.get('territories', '?')} 处"
                    )

        armies = local_state.get("visible_armies", {})
        if armies:
            label = "## Visible Armies" if en else "## 可见军队"
            parts.append(label)
            for _aid, a in list(armies.items())[:5]:
                troops = a.get("troops") or a.get("estimated_troops", "?")
                loc = a.get("location", "?")
                fid = a.get("faction_id", "?")
                parts.append(f"- {fid} at {loc}: {troops}" if en else f"- {fid} 在 {loc}：{troops}")

        garrison = local_state.get("border_garrisons", {})
        if garrison:
            label = "## Border Garrisons (Estimated)" if en else "## 边境驻军估算"
            parts.append(label)
            for tid, g in garrison.items():
                name = g.get("territory_name", tid)
                troops = g.get("estimated_troops", "?")
                parts.append(f"- {name}: {troops}")

        chronicle = local_state.get("chronicle", [])
        if chronicle:
            label = "## Recent Chronicle" if en else "## 天下大事纪（最近发生）"
            parts.append(label)
            for item in chronicle:
                parts.append(f"- {item}")

        if personality:
            if en:
                parts.append(
                    f"\n## Leader Personality\n"
                    f"- Aggression: {personality.get('aggression', '?')}\n"
                    f"- Caution: {personality.get('caution', '?')}"
                )
            else:
                parts.append(
                    f"\n## 君主性格\n"
                    f"- 侵略性: {personality.get('aggression', '?')}\n"
                    f"- 谨慎度: {personality.get('caution', '?')}"
                )

        # ── Previous suggestions (avoid repetition, track what was tried) ──
        prev = local_state.get("previous_suggestions", [])
        if prev:
            parts.append("\n## ⚠️ 上次建议（请勿重复，除非上次建议已生效）")
            for i, title in enumerate(prev):
                if title:
                    parts.append(f"- 上次第{i+1}策: {title}")
            parts.append("若上次建议未被采纳或未生效，请给出全新的策略方向。")

        if query:
            label = "## Commander's Question" if en else "## 主公问策"
            parts.append(f"{label}\n{query}")

        return "\n".join(parts)

    def _parse_strategy_json(self, raw: str) -> dict:
        """Parse LLM JSON response into strategy dict."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return self._offline_strategy({}, {})
            else:
                return self._offline_strategy({}, {})

        return {
            "analysis": data.get("analysis", ""),
            "recommendations": data.get("recommendations", []),
            "risk_assessment": data.get("risk_assessment", ""),
        }

    def _offline_advice(self, local_state: dict, query: str) -> str:
        """Fallback advice when LLM unavailable."""
        my = local_state.get("my", {})
        strength = my.get("strength", 0)
        food = my.get("food", 0)

        perceived = local_state.get("perceived", {})
        border_enemies = [pf for pf in perceived.values() if pf.get("is_border") and not pf.get("is_allied")]

        if self._is_en:
            if not border_enemies:
                return "No immediate border threats. Consolidate internal development and build strength."
            names = ", ".join(p["name"] for p in border_enemies)
            advice = f"{names} threaten our borders. "
            if food < 2000:
                advice += "Food reserves are low — prioritize agriculture and stockpiling."
            elif strength < 5000:
                advice += "Troop numbers are thin — recruit in the rear to reinforce our lines."
            else:
                advice += "We can fight, but must carefully assess the balance of forces."
            return advice

        if not border_enemies:
            return "暂无边境威胁，可安心发展内政、积蓄实力。"

        advice = f"边境有 {', '.join(p['name'] for p in border_enemies)} 虎视眈眈。"
        if food < 2000:
            advice += "眼下粮草不足，宜先发展农业、固本培元。"
        elif strength < 5000:
            advice += "兵力薄弱，应在后方征兵以固防线。"
        else:
            advice += "我军尚可一战，然需审慎评估敌我实力比。"
        return advice

    def _offline_strategy(self, local_state: dict, personality: dict | None = None) -> dict:
        """Fallback strategy when LLM unavailable."""
        my = local_state.get("my", {})
        perceived = local_state.get("perceived", {})
        border_enemies = [pf for pf in perceived.values() if pf.get("is_border") and not pf.get("is_allied")]

        recommendations = []
        if my.get("food", 0) < 2000:
            recommendations.append(
                {"action": "develop", "target": my.get("territories", [""])[0], "priority": 0.9, "reason": "粮草不足"}
            )
        if my.get("strength", 0) < 5000:
            recommendations.append(
                {"action": "recruit", "target": my.get("territories", [""])[0], "priority": 0.8, "reason": "兵力薄弱"}
            )

        if border_enemies:
            for enemy in border_enemies[:2]:
                try:
                    est_str = enemy.get("strength", "0")
                    enemy_strength = int(
                        est_str.replace(",", "").split("~")[-1].strip() if "~" in est_str else est_str.replace(",", "")
                    )
                except (ValueError, AttributeError):
                    enemy_strength = 50000

                if enemy_strength < my.get("strength", 0) * 0.6:
                    recommendations.append(
                        {
                            "action": "attack",
                            "target": enemy["name"],
                            "priority": 0.7,
                            "reason": f"{enemy['name']} 势弱可图",
                        }
                    )

        return {
            "analysis": f"离线模式：基于 {len(perceived)} 个势力的局部情报分析",
            "recommendations": recommendations,
            "risk_assessment": "警告：离线分析精度有限，建议配置 LLM 以获得深度战略分析",
        }
