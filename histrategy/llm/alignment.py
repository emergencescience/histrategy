"""LLM Alignment Engine — non-linear friction on top of deterministic physics.

This module implements Step 2 of the 5-step asymmetric game loop:
  1. Physics simulation (Lanchester) → raw numerical results
  2. LLM alignment → adds non-linear friction (rain, disease, ambush, etc.)
  3. Fog-of-war projection
  4. NPC decisions
  5. Player decisions

The alignment layer is what makes the game feel alive — it transforms
cold numbers into a rich, unpredictable world where plans go wrong,
unexpected events shift the balance, and history feels organic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapter import LLMAdapter

# ─── System Prompt ────────────────────────────────────────────


ALIGNMENT_SYSTEM_PROMPT = """你是《三國志略》的「天命推演官」（Fate Weaving Officer）。

## 你的使命
游戏物理引擎已经计算出本回合的基础数值结果（粮食消耗、战役伤亡、税收等）。
你的任务是在这些确定性的数值上，加入合乎逻辑的非线性「战争摩擦力」。

## 规则
1. **只微调数值，不改变结论**：如果物理引擎判定曹操赢了，你不能改成刘备赢。你只能调整伤亡数字、粮草消耗、民心变化等数值。
2. **调整范围**：任何数值的调整幅度不得超过原值的 ±20%。
   - 例如：物理引擎算出曹军阵亡 10,000 人，你可以调整为 8,000 ~ 12,000。
3. **必须有叙事理由**：每个调整都必须附带一个简短的历史合理解释。
   - ✅ "因突降暴雨，撤退途中曹军额外溺亡 500 人，总伤亡增至 10,500"
   - ❌ "曹操战神下凡秒杀 10 万人"
4. **最多产生 1-3 个摩擦力事件**，不要过度。
5. **可能的事件类型**：
   - 天时：暴雨、大雾、酷暑、寒潮
   - 地利：山路崩塌、河流泛滥、瘟疫
   - 人和：粮草被劫、内奸告密、武将疾病、逃兵
   - 谋略：误判敌情、伏兵突现、同盟背刺

## 输出格式
严格输出 JSON（不要任何 Markdown 包裹）：
{
  "friction_events": [
    {
      "type": "weather|terrain|human|deception",
      "title": "突降暴雨",
      "description": "撤退途中曹军遭暴雨，伤亡加重",
      "affected_faction": "cao",
      "affected_stat": "casualties",
      "original_value": 10000,
      "adjusted_value": 10500,
      "adjustment_pct": 5.0
    }
  ]
}

如果没有值得添加的摩擦力事件，返回空的 friction_events 数组。
"""

VALIDATION_SYSTEM_PROMPT = """你是《三國志略》的「数值审核官」（Chief Auditor）。

请审查以下天命推演官的输出。检查：
1. 所有 numerical adjustment 是否在原始值的 ±25% 以内？
2. 事件的叙事理由是否合理、符合三国历史常识？
3. JSON 格式是否正确？

如果全部通过，返回：
{"approved": true}

如果有问题，返回：
{
  "approved": false,
  "issues": ["问题1", "问题2"],
  "suggested_fix": "建议修正方式"
}
"""

MAX_RETRIES = 3
MAX_ADJUSTMENT_PCT = 0.25  # 25% max allowed adjustment


@dataclass
class FrictionEvent:
    """A single non-linear event added by LLM alignment."""

    type: str  # weather, terrain, human, deception
    title: str
    description: str
    affected_faction: str
    affected_stat: str  # casualties, food_loss, morale_change, etc.
    original_value: float
    adjusted_value: float
    adjustment_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "affected_faction": self.affected_faction,
            "affected_stat": self.affected_stat,
            "original_value": self.original_value,
            "adjusted_value": self.adjusted_value,
            "adjustment_pct": self.adjustment_pct,
        }


@dataclass
class AlignmentResult:
    """Result of the alignment process."""

    approved: bool
    attempt_count: int
    friction_events: list[FrictionEvent] = field(default_factory=list)
    raw_llm_response: str = ""
    validation_errors: list[str] = field(default_factory=list)
    fallback_used: bool = False  # True if we fell back to raw numbers


class AlignmentEngine:
    """Orchestrates the LLM alignment pipeline.

    Flow:
      1. Receive raw TurnResult from physics engine
      2. Build alignment context (numbers + weather + history)
      3. Send to LLM for friction event generation
      4. Validate output → reject if out of bounds → retry (max 3)
      5. Return approved AlignmentResult
    """

    def __init__(self, llm: LLMAdapter):
        self._llm = llm
        self._retries = 0

    @property
    def is_available(self) -> bool:
        """Check if LLM is available for alignment."""
        return self._llm is not None and self._llm.is_available

    def align(
        self,
        turn_result: dict,
        climate_events: dict[str, str] | None = None,
        faction_names: dict[str, str] | None = None,
    ) -> AlignmentResult:
        """Run the alignment pipeline.

        Args:
            turn_result: Raw TurnResult from physics engine (dict form).
                Expected keys: battles, resource_changes, diplomacy, etc.
            climate_events: Territory ID → climate event name mapping.
            faction_names: Faction ID → display name mapping.

        Returns:
            AlignmentResult with approved friction events (or fallback).
        """
        if not self.is_available:
            return AlignmentResult(approved=True, attempt_count=0)

        context = self._build_context(turn_result, climate_events, faction_names)

        metadata = {
            "turn": turn_result.get("turn_number", 0),
            "year": turn_result.get("year", 207),
            "season": turn_result.get("season").value if hasattr(turn_result.get("season"), "value") else str(turn_result.get("season", "spring")),
            "category": "alignment",
            "reason": "align",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                raw_response = self._call_llm(context, ALIGNMENT_SYSTEM_PROMPT, metadata=metadata)
                events = self._parse_events(raw_response)

                if not events:
                    # No friction events — this is fine
                    return AlignmentResult(
                        approved=True,
                        attempt_count=attempt,
                        friction_events=[],
                        raw_llm_response=raw_response,
                    )

                # Validate adjustments
                validation = self._validate_events(events, turn_result)
                if validation["approved"]:
                    return AlignmentResult(
                        approved=True,
                        attempt_count=attempt,
                        friction_events=events,
                        raw_llm_response=raw_response,
                    )

                # Retry with feedback
                context = self._build_retry_context(context, validation["issues"], validation.get("suggested_fix", ""))

            except Exception:
                pass

        # Max retries exceeded → fall back to raw numbers
        return AlignmentResult(
            approved=True,
            attempt_count=MAX_RETRIES,
            friction_events=[],
            fallback_used=True,
            validation_errors=validation.get("issues", []) if "validation" in dir() else [],
        )

    def _build_context(
        self,
        turn_result: dict,
        climate_events: dict[str, str] | None,
        faction_names: dict[str, str] | None,
    ) -> str:
        """Build the LLM context from raw physics results."""
        parts = []

        # Battles
        battles = turn_result.get("battles", [])
        if battles:
            parts.append("## 本回合战役\n")
            for b in battles:
                attacker = faction_names.get(b.attacker_id, b.attacker_id) if faction_names else b.attacker_id
                defender = faction_names.get(b.defender_id, b.defender_id) if faction_names else b.defender_id
                parts.append(
                    f"- {attacker} vs {defender}（{b.location}）："
                    f"结果 {b.result.value if hasattr(b.result, 'value') else b.result}，"
                    f"攻方伤亡 {b.attacker_casualties}，守方伤亡 {b.defender_casualties}"
                )

        # Resource changes
        resources = turn_result.get("resource_changes", {})
        if resources:
            parts.append("\n## 资源变动\n")
            for fid, changes in resources.items():
                name = faction_names.get(fid, fid) if faction_names else fid
                food_d = changes.get("food_delta", 0)
                tax_r = changes.get("tax_revenue", 0)
                spent = changes.get("treasury_spent", 0)
                parts.append(f"- {name}：粮草{'%+d' % food_d}，税收{'+%d' % tax_r}，支出{spent}" if spent else "")

        # Climate
        if climate_events:
            parts.append("\n## 天时\n")
            for tid, evt in climate_events.items():
                parts.append(f"- {tid}：{evt}")

        # Character events
        char_events = turn_result.get("character_events", [])
        if char_events:
            parts.append("\n## 人事变动\n")
            for ev in char_events[:10]:
                parts.append(f"- {ev}")

        return "\n".join(parts)

    def _build_retry_context(self, original_context: str, issues: list[str], suggested_fix: str) -> str:
        """Build context for retry with validation feedback."""
        return (
            original_context
            + "\n\n## ❌ 上次审核未通过\n问题：\n- "
            + "\n- ".join(issues)
            + f"\n\n建议修正：{suggested_fix}\n\n请重新生成，确保数值在允许范围内。"
        )

    def _call_llm(self, context: str, system_prompt: str, metadata: dict | None = None) -> str:
        """Send context to LLM and get raw response."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]
        return self._llm.chat(messages, temperature=0.5, max_tokens=1024, metadata=metadata)

    def _parse_events(self, raw_response: str) -> list[FrictionEvent]:
        """Parse LLM response into FrictionEvent objects."""
        try:
            # Try direct JSON parse
            data = json.loads(raw_response)
        except json.JSONDecodeError:
            # Try extracting from markdown block
            import re

            match = re.search(r'\{[^{}]*"friction_events"[^{}]*\[.*?\][^{}]*\}', raw_response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return []
            else:
                return []

        events = []
        for item in data.get("friction_events", []):
            try:
                events.append(
                    FrictionEvent(
                        type=item.get("type", "unknown"),
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                        affected_faction=item.get("affected_faction", ""),
                        affected_stat=item.get("affected_stat", ""),
                        original_value=float(item.get("original_value", 0)),
                        adjusted_value=float(item.get("adjusted_value", 0)),
                        adjustment_pct=float(item.get("adjustment_pct", 0)),
                    )
                )
            except (ValueError, KeyError, TypeError):
                continue

        return events

    def _validate_events(self, events: list[FrictionEvent], turn_result: dict) -> dict:
        """Validate that all adjustments are within allowed bounds.

        Returns {'approved': bool, 'issues': [...]}
        """
        issues = []

        for event in events:
            if event.original_value == 0:
                actual_pct = float("inf") if event.adjusted_value != 0 else 0.0
            else:
                actual_pct = abs((event.adjusted_value - event.original_value) / event.original_value)

            if actual_pct > MAX_ADJUSTMENT_PCT:
                issues.append(
                    f"「{event.title}」的调整幅度 {actual_pct:.0%} 超出上限 {MAX_ADJUSTMENT_PCT:.0%}"
                    f"（原值 {event.original_value} → 调整值 {event.adjusted_value}）"
                )

            if not event.description or len(event.description) < 5:
                issues.append(f"「{event.title}」缺少合理的叙事理由")

        if issues:
            return {
                "approved": False,
                "issues": issues,
                "suggested_fix": "请缩小调整幅度至 ±25% 以内，并为每个事件补充三国历史背景的叙事理由。",
            }

        return {"approved": True, "issues": []}
