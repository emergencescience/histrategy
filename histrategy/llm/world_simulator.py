"""
World Simulator — LLM-driven nonlinear simulation layer for v3.

Builds full context from WorldState + historical memory, calls LLM
to generate structured delta (battle overrides, morale events, political
events, NPC actions, butterfly effects), then validates against guardrails.

Usage:
    sim = WorldSimulator(llm_adapter)
    delta = sim.simulate(world_state, commands, baseline_result, turn_memory)
    # delta is a dict matching the output schema
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from histrategy.llm.prompt_loader import WORLD_SIMULATOR_SYSTEM

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter


class WorldSimulator:
    """LLM-driven world simulation — generates nonlinear deltas."""

    def __init__(self, llm_adapter: LLMAdapter | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available

    def simulate(
        self,
        world_state: WorldState,
        player_commands: list,
        player_decision: str,
        baseline_result,
        turn_memory: list[dict] | None = None,
        epoch_memory: list[dict] | None = None,
        pre_morale: dict[str, int] | None = None,
    ) -> dict:
        """Generate nonlinear simulation delta from full context.

        Args:
            world_state: Current WorldState (v2 format)
            player_commands: Parsed player Command objects
            player_decision: Original natural language player decision
            baseline_result: TurnResult from deterministic engine
            turn_memory: Recent turn history (last N turns)
            epoch_memory: Long-term persistent effects
            pre_morale: Pre-turn morale values per faction (for context)

        Returns:
            Structured delta dict matching the output schema, or empty dict
            if LLM unavailable or parsing fails.
        """
        if not self.llm_available or not self.llm:
            return {}

        context = self._build_context(
            world_state,
            player_commands,
            player_decision,
            baseline_result,
            turn_memory or [],
            epoch_memory or [],
            pre_morale or {},
        )

        messages = [
            {"role": "system", "content": WORLD_SIMULATOR_SYSTEM},
            {"role": "user", "content": context},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4096,
            )
            return self._validate_output(result)
        except Exception:
            # Fallback: try plain chat with JSON extraction
            try:
                result = self.llm.chat(
                    messages,
                    temperature=0.3,
                    max_tokens=4096,
                )
                return self._validate_output(self._extract_json(result))
            except Exception:
                return {}

    # ── Context Builder ───────────────────────────────────────

    def _build_context(
        self,
        ws,
        commands: list,
        decision: str,
        baseline,
        turn_memory: list[dict],
        epoch_memory: list[dict],
        pre_morale: dict[str, int],
    ) -> str:
        """Build the full simulation context for the LLM."""
        lines: list[str] = []

        # Time
        season_cn = ws.season.cn if hasattr(ws.season, "cn") else str(ws.season)
        lines.append(f"## 当前时间\n{ws.year}年{season_cn} | 第{ws.turn_number}回合\n")

        # Player context
        lines.append(f"## 玩家势力\nfaction_id: {ws.player_faction_id}\n")
        lines.append("## 玩家原始决策")
        lines.append(decision)
        lines.append("")

        # Parsed commands
        lines.append("## 玩家结构化命令")
        for cmd in commands:
            notes = getattr(cmd, "notes", "")
            note_str = f"  // {notes}" if notes else ""
            lines.append(f"- {cmd.type}: {json.dumps(cmd.params, ensure_ascii=False)}{note_str}")
        lines.append("")

        # Faction states
        lines.append("## 势力状态")
        for fid, f in ws.factions.items():
            if not getattr(f, "is_active", True):
                continue
            personality = self._format_personality(f)
            lines.append(
                f"- {fid} ({f.name}): "
                f"兵力={getattr(f, 'strength_actual', 0)}, "
                f"资金={f.treasury}, 粮草={f.food}, "
                f"民心={getattr(f, 'morale_actual', 0)}, "
                f"税率={f.tax_rate}, "
                f"领地={list(f.territories) if f.territories else []}"
            )
            if personality:
                lines.append(f"  个性: {personality}")
        lines.append("")

        # Armies
        lines.append("## 军队部署")
        for army in ws.armies.values():
            if army.total_troops <= 0:
                continue
            commander = f" (统帅: {army.commander_id})" if army.commander_id else ""
            lines.append(
                f"- {army.id}: faction={army.faction_id}, "
                f"location={army.location}, "
                f"troops={army.total_troops}{commander}"
            )
        lines.append("")

        # Deterministic baseline
        lines.append("## 确定性引擎基线结果")
        if hasattr(baseline, "battles") and baseline.battles:
            lines.append("### 战斗结果")
            for b in baseline.battles:
                lines.append(f"- {b.location}: {b.attacker_id} vs {b.defender_id} → {b.result.value}")
                if hasattr(b, "territory_captured") and b.territory_captured:
                    lines.append(f"  → 领地易手: {b.location} 归 {b.attacker_id}")
                atk_loss = sum(b.attacker_casualties.values()) if hasattr(b, "attacker_casualties") else 0
                def_loss = sum(b.defender_casualties.values()) if hasattr(b, "defender_casualties") else 0
                lines.append(f"  基线伤亡: 攻方{atk_loss} 守方{def_loss}")
        else:
            lines.append("本回合无战斗。")
        lines.append("")

        if hasattr(baseline, "resource_changes") and baseline.resource_changes:
            lines.append("### 资源变化")
            for fid, changes in baseline.resource_changes.items():
                parts = []
                if changes.get("food_delta", 0):
                    parts.append(f"粮草{changes['food_delta']:+d}")
                if changes.get("tax_revenue", 0):
                    parts.append(f"税收+{changes['tax_revenue']}")
                if parts:
                    lines.append(f"- {fid}: {', '.join(parts)}")
            lines.append("")

        # v2 deterministic morale changes (so LLM knows what v2 already did)
        if pre_morale:
            lines.append("### v2 引擎民心变化")
            for fid, f in ws.factions.items():
                if not getattr(f, "is_active", True):
                    continue
                old = pre_morale.get(fid)
                new = getattr(f, "morale_actual", 50)
                if old is not None and abs(new - old) > 0:
                    direction = "+" if new >= old else ""
                    lines.append(f"- {fid} ({f.name}): {old} → {new} ({direction}{new - old:+d})")
            lines.append("")

        # Character list (relevant characters only)
        lines.append("## 关键人物")
        for char in ws.characters.values():
            if not char.alive:
                continue
            loc = char.location if hasattr(char, "location") else "?"
            loyalty = char.loyalty if hasattr(char, "loyalty") else 50
            lines.append(
                f"- {char.id} ({char.name}): faction={char.faction_id}, location={loc}, loyalty={loyalty}, alive=True"
            )
        lines.append("")

        # Historical memory
        if turn_memory:
            lines.append("## 历史记忆（最近回合）")
            for mem in turn_memory:
                lines.append(
                    f"Turn {mem.get('turn', '?')} ({mem.get('year', '?')}年"
                    f"{mem.get('season', '?')}): "
                    f"{mem.get('outcome_summary', '')}"
                )
            lines.append("")

        # Persistent effects (epoch memory)
        if epoch_memory:
            lines.append("## 持续性政策效应")
            for effect in epoch_memory:
                lines.append(f"- {effect.get('note', '')}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_personality(f) -> str:
        """Format faction personality traits."""
        traits = []
        for attr, label in [
            ("aggression", "侵略性"),
            ("cunning", "狡诈"),
            ("caution", "谨慎"),
            ("diplomacy", "外交"),
            ("development_focus", "发展"),
            ("mercy", "仁德"),
        ]:
            val = getattr(f, attr, 0.5)
            if val != 0.5:
                traits.append(f"{label}={val:.1f}")
        return ", ".join(traits) if traits else ""

    # ── Output Validation ────────────────────────────────────

    def _validate_output(self, result: dict) -> dict:
        """Basic structural validation of LLM output."""
        if not isinstance(result, dict):
            return {}

        # Ensure all expected keys exist with defaults
        validated = {
            "battle_overrides": result.get("battle_overrides", []),
            "morale_events": result.get("morale_events", []),
            "political_events": result.get("political_events", []),
            "npc_faction_actions": result.get("npc_faction_actions", result.get("npc_actions", [])),
            "narrative_seeds": result.get("narrative_seeds", []),
        }

        # Ensure lists
        for key in validated:
            if not isinstance(validated[key], list):
                validated[key] = []

        return validated

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM text response."""
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
