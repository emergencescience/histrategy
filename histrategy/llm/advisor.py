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


ADVISOR_SYSTEM_PROMPT = """你是《三國志略》的军师谋士。你可以扮演诸葛亮、荀彧、周瑜、司马懿等历史上著名的军师。

## 你的角色
你为我方主公提供战略分析和军事建议。你只能基于当前的局部情报（战争迷雾下的有限信息）来做判断，不能使用上帝视角。

## 规则
1. **仅基于已知信息**：你看到的敌军兵力是估算范围，不可假设精确数字
2. **角色扮演**：以你所扮演的军师口吻回答（文言白话混用，有谋士风范）
3. **具体建议**：不要泛泛而谈，给出具体可执行的战术建议
4. **承认局限**：如果信息不足以判断，诚实说「亮观之，事未可料」

## 输出格式（根据调用方式选择）

### 当玩家提问时（有 query）：
输出自然语言回复，100-200字，文白相间。

### 当系统请求战略分析时（无 query）：
严格输出 JSON：
{
  "analysis": "局势分析（文本，100字内）",
  "recommendations": [
    {"action": "attack|defend|recruit|develop|ally|sabotage",
     "target": "目标势力或领地",
     "priority": 0.0-1.0,
     "reason": "理由"}
  ],
  "risk_assessment": "风险评估（文本）"
}
"""


@dataclass
class AdvisorRecommendation:
    """A single strategic recommendation."""

    action: str  # attack, defend, recruit, develop, ally, sabotage
    target: str
    priority: float  # 0.0 - 1.0
    reason: str


class StrategicAdvisor:
    """Unified AI advisor for both human players and NPC AI.

    Symmetric design: human players get text advice, NPCs get structured
    command weights. Both use the same LLM and projected LocalWorldState.
    """

    def __init__(self, llm: LLMAdapter):
        self._llm = llm

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
            {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]
        try:
            return self._llm.chat(messages, temperature=0.7, max_tokens=512)
        except Exception:
            return self._offline_advice(local_state, query)

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
            {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]
        try:
            raw = self._llm.chat(messages, temperature=0.5, max_tokens=512)
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

        my = local_state.get("my", {})
        parts.append(
            f"## 我方情报\n"
            f"- 兵力: {my.get('strength', '?')}\n"
            f"- 资金: {my.get('treasury', '?')}\n"
            f"- 粮草: {my.get('food', '?')}\n"
            f"- 经济: {my.get('economy', '?')}\n"
            f"- 民心: {my.get('morale', '?')}\n"
            f"- 领地: {', '.join(my.get('territories', []))}"
        )

        perceived = local_state.get("perceived", {})
        if perceived:
            parts.append("\n## 天下态势（局部情报）")
            for fid, pf in perceived.items():
                border = "接壤" if pf.get("is_border") else "远方"
                ally = " [盟友]" if pf.get("is_allied") else ""
                parts.append(
                    f"- {pf['name']}{ally}（{border}）："
                    f"兵力约 {pf.get('strength', '?')}，"
                    f"领地 {pf.get('territories', '?')} 处"
                )

        armies = local_state.get("visible_armies", {})
        if armies:
            parts.append("\n## 可见军队")
            for aid, a in list(armies.items())[:5]:
                troops = a.get("troops") or a.get("estimated_troops", "?")
                parts.append(f"- {a.get('faction_id', '?')} 在 {a.get('location', '?')}：{troops}")

        garrison = local_state.get("border_garrisons", {})
        if garrison:
            parts.append("\n## 边境驻军估算")
            for tid, g in garrison.items():
                parts.append(f"- {g.get('territory_name', tid)}：{g.get('estimated_troops', '?')}")

        if personality:
            parts.append(
                f"\n## 君主性格\n"
                f"- 侵略性: {personality.get('aggression', '?')}\n"
                f"- 谨慎度: {personality.get('caution', '?')}"
            )

        if query:
            parts.append(f"\n## 主公问策\n{query}")

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

        if not border_enemies:
            return "暂无边境威胁，可安心发展内政、积蓄实力。"

        strongest = max(
            border_enemies,
            key=lambda p: int(
                p.get("strength", "0").replace(",", "").split("~")[-1].strip()
                if "~" in p.get("strength", "0")
                else p.get("strength", "0").replace(",", "")
            ),
            default=None,
        )

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
