"""
Narrative Engine — read-only LLM narrative generation for 三國志略 v2.

Consumes physics engine output (TurnResult) and produces 文白相间
(classical/vernacular hybrid) historical chronicle text. Never modifies game state.

Integrates with histrategy-engine's HistoricalRAG for time-windowed event context.
Offline fallback returns deterministic text when no LLM key is available.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import TurnResult, WorldState

    from .adapter import LLMAdapter

from .context_helpers import collect_dead_characters
from .prompt_loader import NARRATIVE_SYSTEM, NARRATIVE_SYSTEM_EN, PLAN_SUGGESTIONS_SYSTEM

# ─── Knowledge path resolution ──────────────────────────────────


def _resolve_knowledge_path() -> str:
    """Find the scenario knowledge directory (three-kingdoms)."""
    narrative_dir = os.path.dirname(__file__)
    candidates = [
        os.path.join(narrative_dir, "..", "..", "scenarios", "three-kingdoms", "knowledge"),
        os.path.join(narrative_dir, "..", "..", "..", "scenarios", "three-kingdoms", "knowledge"),
        os.path.join(narrative_dir, "..", "..", "histrategy-knowledge"),   # legacy symlink
        os.path.join(narrative_dir, "..", "..", "..", "histrategy-knowledge"),
    ]
    for p in candidates:
        if os.path.isdir(os.path.join(p, "timeline")):
            return os.path.abspath(p)
    # Fallback: return the first candidate that exists
    for p in candidates:
        if os.path.isdir(p):
            return os.path.abspath(p)
    return os.path.abspath(os.path.join(narrative_dir, "..", "..", "scenarios", "three-kingdoms", "knowledge"))


# ─── Narrative generation prompt (read-only, no state mutation) ──

# Prompts are now loaded from external files via .prompt_loader


class NarrativeEngine:
    """Read-only narrative generator for the histrategy v2 physics engine.

    Produces historical chronicle text and strategic suggestions from engine output
    without modifying game state. Uses HistoricalRAG for time-windowed event context.

    Offline fallback generates deterministic text when no LLM key is available.
    """

    def __init__(self, llm_adapter: LLMAdapter | None = None, language: str = "zh", scenario: str = ""):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available
        self._language = language  # "zh" or "en"
        self._scenario = scenario  # e.g. "three-kingdoms", "nanming", "rome-triumvirate"

        # Initialize RAG
        self._knowledge_path = _resolve_knowledge_path()
        self._rag = None
        if os.path.isdir(self._knowledge_path):
            try:
                from histrategy_engine.history.rag import HistoricalRAG

                self._rag = HistoricalRAG(self._knowledge_path)
            except Exception:
                pass

    @property
    def is_available(self) -> bool:
        return self.llm_available

    @property
    def lang(self) -> str:
        return self._language

    @lang.setter
    def lang(self, value: str):
        self._language = value

    @property
    def scenario(self) -> str:
        return self._scenario

    @scenario.setter
    def scenario(self, value: str):
        self._scenario = value

    def _get_narrative_system_prompt(self, is_en: bool = False) -> str:
        """Load the narrative system prompt, preferring a scenario-specific one."""
        scenario = self._scenario
        # Try scenario-specific prompts first
        if scenario:
            candidates = []
            if is_en:
                candidates = [
                    Path(f"scenarios/{scenario}/prompts/narrative_en.md"),
                    Path(f"scenarios/{scenario}/prompts/narrative.md"),
                ]
            else:
                candidates = [
                    Path(f"scenarios/{scenario}/prompts/narrative_zh.md"),
                    Path(f"scenarios/{scenario}/prompts/narrative.md"),
                ]
            for p in candidates:
                if p.is_file():
                    return p.read_text(encoding="utf-8")

        # Fall back to default prompts
        if is_en:
            return NARRATIVE_SYSTEM_EN if NARRATIVE_SYSTEM_EN else NARRATIVE_SYSTEM
        return NARRATIVE_SYSTEM

    def _get_global_narrative_system_prompt(self, is_en: bool = False) -> str:
        """Load the global narrative system prompt, preferring a scenario-specific one."""
        from .prompt_loader import GLOBAL_NARRATIVE_SYSTEM, GLOBAL_NARRATIVE_SYSTEM_EN

        scenario = self._scenario
        if scenario:
            candidates = []
            if is_en:
                candidates = [
                    Path(f"scenarios/{scenario}/prompts/global_narrative_en.md"),
                    Path(f"scenarios/{scenario}/prompts/global_narrative.md"),
                ]
            else:
                candidates = [
                    Path(f"scenarios/{scenario}/prompts/global_narrative_zh.md"),
                    Path(f"scenarios/{scenario}/prompts/global_narrative.md"),
                ]
            for p in candidates:
                if p.is_file():
                    return p.read_text(encoding="utf-8")

        if is_en:
            return GLOBAL_NARRATIVE_SYSTEM_EN if GLOBAL_NARRATIVE_SYSTEM_EN else GLOBAL_NARRATIVE_SYSTEM
        return GLOBAL_NARRATIVE_SYSTEM

    @property
    def rag_available(self) -> bool:
        return self._rag is not None

    # ── Turn Narrative ────────────────────────────────────────

    def generate_turn_narrative(
        self,
        turn_result: TurnResult,
        deviation: float = 0.0,
        averted_events: list[str] | None = None,
        world_state: WorldState | None = None,
        room_id: str = "",
    ) -> str:
        """Generate a historical chronicle narrative from a turn's physics results.

        Args:
            turn_result: The complete output from TurnController.execute_turn()
            deviation: The player's historical deviation score.
            averted_events: List of event IDs that were averted.
            world_state: Complete game world state (optional) for detailed context.

        Returns:
            A 文白相间 historical narrative string (200-400 chars).
            Falls back to deterministic text if LLM unavailable.
        """
        if not self.llm_available or not self.llm:
            return self._offline_narrative(turn_result)

        # Build the prompt context from the TurnResult and WorldState
        context = self._build_narrative_context(
            turn_result,
            deviation=deviation,
            averted_events=averted_events,
            world_state=world_state,
        )

        messages = [
            {"role": "system", "content": self._get_narrative_system_prompt()},
            {"role": "user", "content": context},
        ]

        try:
            metadata = {
                "turn": getattr(turn_result, "turn_number", 0),
                "year": getattr(turn_result, "year", 207),
                "season": turn_result.season.value if hasattr(turn_result.season, "value") else str(turn_result.season),
                "category": "narrative",
                "reason": "generate_turn_narrative",
                "faction_id": getattr(turn_result, "player_faction_id", ""),
                "room_id": room_id,
            }
            result = self.llm.chat(
                messages,
                temperature=0.75,
                max_tokens=3072,
                metadata=metadata,
            )
            return result.strip()
        except Exception:
            return self._offline_narrative(turn_result)

    def generate_faction_narrative(
        self,
        ws: WorldState,
        faction_id: str,
        baseline,
        macro_delta: dict | None = None,
        decision: str = "",
        commands: list | None = None,
        room_id: str = "",
    ) -> str:
        """Generate a faction-specific narrative from baseline + macro results.

        Used by QuarterlyResolver to produce per-faction narratives for the
        shared timeline view. Falls back to deterministic text when LLM unavailable.
        """

        faction = ws.factions.get(faction_id)
        fname = faction.name if faction else faction_id
        fname_en = getattr(faction, "name_en", "") or ""

        if not self.llm_available or not self.llm:
            return self._offline_faction_narrative(fname, baseline, macro_delta or {}, name_en=fname_en)

        # Build context
        lines: list[str] = []
        lines.append(f"Faction: {fname} ({faction_id})")
        lines.append(f"Decision: {decision}")
        if commands:
            lines.append(f"Commands: {commands}")
        lines.append(f"\nBaseline results: {baseline}")
        if macro_delta:
            lines.append(f"Macro adjustments: {macro_delta}")

        system_prompt = self._get_narrative_system_prompt(is_en=(self._language == "en"))
        if self._language == "en":
            lines.append("\nIMPORTANT: Write the entire narrative in English.")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(lines)},
        ]

        try:
            result = self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=1024,
                metadata={"category": "narrative", "faction_id": faction_id, "room_id": room_id},
            )
            return result.strip()
        except Exception:
            return self._offline_faction_narrative(fname, baseline, macro_delta or {}, name_en=fname_en)

    def generate_global_narrative(
        self,
        ws,
        faction_decisions: dict[str, str],
        baseline,
        macro_delta: dict | None = None,
        history_events: list | None = None,
        room_id: str = "",
        scenario: str = "",
    ) -> str:
        """Generate a single global narrative covering ALL factions for the quarter."""
        if not self.llm_available or not self.llm:
            return self._offline_global_narrative(ws, faction_decisions)

        is_en = self._language == "en"
        system_prompt = self._get_global_narrative_system_prompt(is_en)

        # Build context
        lines: list[str] = []
        year = ws.year
        season = getattr(ws.season, "cn", str(ws.season)) if hasattr(ws, "season") else "?"
        scenario_label = f"Scenario: {scenario}" if scenario else ""

        lines.append(f"Year: {year} | Season: {season}")
        if scenario_label:
            lines.append(scenario_label)
        lines.append("")

        # Faction decisions
        lines.append("## Faction Decisions This Quarter")
        for fid, decision in faction_decisions.items():
            faction = ws.factions.get(fid)
            if faction:
                fname = getattr(faction, "name_en", "") if (is_en and getattr(faction, "name_en", "")) else faction.name
            else:
                fname = fid
            lines.append(f"- {fname} ({fid}): {decision[:200]}")
        lines.append("")

        # Baseline results — use structured formatter instead of raw str()
        from .narrative_context import format_baseline_for_narrative

        lines.append("## Baseline Results (Authoritative Physics Engine Output)")
        lines.append(format_baseline_for_narrative(baseline, ws))
        lines.append("")
        lines.append("⚠️ ABOVE IS AUTHORITATIVE: Territory ownership, battle outcomes,")
        lines.append("and resource changes above are the GROUND TRUTH. Your narrative")
        lines.append("MUST reflect these facts exactly. Do NOT invent battles that")
        lines.append("are not listed. Do NOT describe territory as belonging to a")
        lines.append("faction that does not own it per the Post-Battle Territory list.")

        # Macro adjustments
        if macro_delta:
            lines.append("## Macro Adjustments")
            lines.append(str(macro_delta))
            lines.append("")

        # Faction snapshots
        # H35y: Build territory ownership from ws.territories[].owner_id first
        faction_territories: dict[str, list[str]] = {}
        if hasattr(ws, "territories") and ws.territories:
            for tid, territory in ws.territories.items():
                owner = getattr(territory, "owner_id", "") or ""
                if owner and owner in ws.factions:
                    faction_territories.setdefault(owner, []).append(tid)

        lines.append("## Faction Snapshots (Current State)")
        for fid in faction_decisions:
            faction = ws.factions.get(fid)
            if not faction:
                continue
            fname = getattr(faction, "name_en", "") if (is_en and getattr(faction, "name_en", "")) else faction.name
            troops = getattr(faction, "strength_actual", 0)
            tids = faction_territories.get(fid, [])
            if not tids:
                tids = list(getattr(faction, "territories", []))
            territory_names = []
            for tid in tids:
                t = ws.territories.get(tid) if hasattr(ws, "territories") else None
                territory_names.append(t.name if t and hasattr(t, "name") else str(tid))
            lines.append(
                f"- {fname}: troops={troops:,} food={faction.food:,.0f} "
                f"treasury={faction.treasury:,.0f} morale={getattr(faction, 'morale_actual', 50)} "
                f"territories={territory_names}"
            )
        lines.append("")

        # History events
        if history_events:
            lines.append("## Historical Events Triggered")
            for evt in history_events:
                title = evt.get("title", str(evt))
                desc = evt.get("description", "")
                lines.append(f"- {title}: {desc}"[:200])
            lines.append("")

        user_prompt = "\n".join(lines)

        try:
            result = self.llm.chat(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7,
                max_tokens=3072,
                metadata={
                    "category": "global_narrative",
                    "room_id": room_id,
                    "scenario": scenario,
                },
            )
            return result.strip()
        except Exception:
            return self._offline_global_narrative(ws, faction_decisions)

    def generate_global_narrative_stream(
        self,
        ws,
        faction_decisions: dict[str, str],
        baseline,
        macro_delta: dict | None = None,
        history_events: list | None = None,
        room_id: str = "",
        scenario: str = "",
    ):
        """Stream global narrative via SSE, yielding chunks as they arrive.

        Yields each text chunk. On LLM failure, yields the offline fallback
        as a single chunk.
        """
        if not self.llm_available or not self.llm:
            yield self._offline_global_narrative(ws, faction_decisions)
            return

        is_en = self._language == "en"
        system_prompt = self._get_global_narrative_system_prompt(is_en)

        # Build context (same as generate_global_narrative)
        lines: list[str] = []
        year = ws.year
        season = getattr(ws.season, "cn", str(ws.season)) if hasattr(ws, "season") else "?"
        scenario_label = f"Scenario: {scenario}" if scenario else ""

        lines.append(f"Year: {year} | Season: {season}")
        if scenario_label:
            lines.append(scenario_label)
        lines.append("")

        lines.append("## Faction Decisions This Quarter")
        for fid, decision in faction_decisions.items():
            faction = ws.factions.get(fid)
            if faction:
                fname = getattr(faction, "name_en", "") if (is_en and getattr(faction, "name_en", "")) else faction.name
            else:
                fname = fid
            lines.append(f"- {fname} ({fid}): {decision[:200]}")
        lines.append("")

        # Baseline results — structured formatter
        from .narrative_context import format_baseline_for_narrative

        lines.append("## Baseline Results (Authoritative Physics Engine Output)")
        lines.append(format_baseline_for_narrative(baseline, ws))
        lines.append("")
        lines.append("⚠️ ABOVE IS AUTHORITATIVE: Territory ownership, battle outcomes,")
        lines.append("and resource changes above are the GROUND TRUTH. Your narrative")
        lines.append("MUST reflect these facts exactly.")

        if macro_delta:
            lines.append("## Macro Adjustments")
            lines.append(str(macro_delta))
            lines.append("")

        # H35y: Build territory ownership from ws.territories[].owner_id first
        faction_territories: dict[str, list[str]] = {}
        if hasattr(ws, "territories") and ws.territories:
            for tid, territory in ws.territories.items():
                owner = getattr(territory, "owner_id", "") or ""
                if owner and owner in ws.factions:
                    faction_territories.setdefault(owner, []).append(tid)

        lines.append("## Faction Snapshots (Current State)")
        for fid in faction_decisions:
            faction = ws.factions.get(fid)
            if not faction:
                continue
            fname = getattr(faction, "name_en", "") if (is_en and getattr(faction, "name_en", "")) else faction.name
            troops = getattr(faction, "strength_actual", 0)
            tids = faction_territories.get(fid, [])
            if not tids:
                tids = list(getattr(faction, "territories", []))
            territory_names = []
            for tid in tids:
                t = ws.territories.get(tid) if hasattr(ws, "territories") else None
                territory_names.append(t.name if t and hasattr(t, "name") else str(tid))
            lines.append(
                f"- {fname}: troops={troops:,} food={faction.food:,.0f} "
                f"treasury={faction.treasury:,.0f} morale={getattr(faction, 'morale_actual', 50)} "
                f"territories={territory_names}"
            )
        lines.append("")

        if history_events:
            lines.append("## Historical Events Triggered")
            for evt in history_events:
                title = evt.get("title", str(evt))
                desc = evt.get("description", "")
                lines.append(f"- {title}: {desc}"[:200])
            lines.append("")

        user_prompt = "\n".join(lines)

        import logging
        _logger = logging.getLogger("histrategy.narrative_stream")

        try:
            chunk_count = 0
            for chunk in self.llm.chat_stream(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7,
                max_tokens=3072,
                stream_timeout=45.0,  # Fall back to offline after 45s instead of hanging
                metadata={
                    "category": "global_narrative",
                    "room_id": room_id,
                    "scenario": scenario,
                },
            ):
                chunk_count += 1
                yield chunk
            _logger.info(
                "[room=%s] Global narrative stream: %d chunks from LLM",
                room_id, chunk_count,
            )
        except Exception as e:
            _logger.error(
                "[room=%s] Global narrative LLM stream FAILED, falling back to offline: %s",
                room_id, str(e)[:200],
            )
            yield self._offline_global_narrative(ws, faction_decisions)

    def _offline_global_narrative(self, ws, faction_decisions: dict[str, str]) -> str:
        """Deterministic fallback when LLM is unavailable.

        Produces a readable chronicle summary instead of dumping raw decision text.
        Raw player commands are never suitable as public-facing narrative —
        they contain typos, informal language, and private tactical intent.
        """
        is_en = self._language == "en"
        year = ws.year
        season = getattr(ws.season, "cn", str(ws.season)) if hasattr(ws, "season") else "?"
        season_label = f"{season} {year}" if is_en else f"{year}年{season}"

        # Era line for immersion
        era_info = self._ERA_MAP.get(self._scenario)
        if era_info and not is_en:
            reign_name, base_year = era_info
            era_year = year - base_year + 1
            if era_year < 1:
                era_str = f"{reign_name}前{abs(era_year - 1)}年"
            elif era_year == 1:
                era_str = f"{reign_name}元年"
            else:
                era_str = f"{reign_name}{self._number_to_chinese(era_year)}年"
            era_line = f"{era_str}{season}，天下纷争未休。"
        else:
            era_line = f"Year {year}, {season} — the realm remains in turmoil." if is_en else f"{year}年{season}，天下纷争未休。"

        lines = []
        header = f"### {season_label} · {'Annals' if is_en else '大事纪'}"
        lines.append(header)
        lines.append("")
        lines.append(era_line)
        lines.append("")

        # Per-faction status summaries (decision content replaced with intent summary)
        for fid in faction_decisions:
            faction = ws.factions.get(fid)
            if not faction:
                continue
            fname = (
                getattr(faction, "name_en", "")
                if (is_en and getattr(faction, "name_en", ""))
                else faction.name
            )
            troops = getattr(faction, "strength_actual", 0) or 0
            treasury = int(getattr(faction, "treasury", 0) or 0)
            food = int(getattr(faction, "food", 0) or 0)
            morale = getattr(faction, "morale_actual", 50) or 50
            territories = list(getattr(faction, "territories", []) or [])
            terr_count = len(territories)

            # Summarize faction status without exposing raw decision text
            if is_en:
                lines.append(
                    f"**{fname}**: {troops:,} troops, {treasury:,} gold, "
                    f"{food:,} grain, morale {morale}, {terr_count} cities."
                )
            else:
                lines.append(
                    f"**{fname}**：兵力{troops:,}，府库{treasury:,}，"
                    f"存粮{food:,}，民心{morale}，城池{terr_count}座。"
                )

        lines.append("")
        if is_en:
            lines.append(
                "_The court chronicler records this quarter's events. "
                "Detailed narratives will be generated in the next turn._"
            )
        else:
            lines.append(
                "_史官如实记录本季度各势力概况。"
                "详细的战报叙事将在下一回合中生成。_"
            )

        return "\n".join(lines)

    def _offline_faction_narrative(
        self,
        faction_name: str,
        baseline,
        macro_delta: dict,
        name_en: str = "",
    ) -> str:
        """Deterministic fallback narrative for a single faction."""
        display_name = name_en if (self._language == "en" and name_en) else faction_name
        parts = [f"{display_name} carried out their plans this quarter."]
        # Try to extract battle info from baseline
        if hasattr(baseline, "battles") and baseline.battles:
            for b in baseline.battles:
                if hasattr(b, "attacker_id") and b.attacker_id == faction_name:
                    parts.append(f"They engaged in battle at {getattr(b, 'location', 'unknown')}.")
        return " ".join(parts)

    def _build_narrative_context(
        self,
        tr: TurnResult,
        deviation: float = 0.0,
        averted_events: list[str] | None = None,
        world_state: WorldState | None = None,
    ) -> str:
        """Build a structured text context from a TurnResult for LLM input."""
        lines: list[str] = []

        # ── Time context with scenario/era awareness ──
        time_line = f"## 当前时间\n{tr.year}年{tr.season.cn} | 第{tr.turn_number}回合"
        if self._scenario:
            scenario_names = {
                "three-kingdoms": "三國志略（三国时期）",
                "nanming": "山河鼎革（南明弘光时期）",
                "rome-triumvirate": "Rome Triumvirate",
            }
            sn = scenario_names.get(self._scenario, self._scenario)
            time_line += f"\n时代背景: {sn}（{tr.year}年）"
        time_line += "\n"
        lines.append(time_line)

        # Player's original decision — critical for narrative accuracy
        if getattr(tr, "player_decision", ""):
            lines.append("## 君主决策（原文）")
            lines.append(tr.player_decision)
            lines.append("")

        # Parsed commands with notes
        if getattr(tr, "player_commands", []):
            lines.append("## 解析后的军令")
            for cmd in tr.player_commands:
                cmd_type = getattr(cmd, "type", "?")
                cmd_params = getattr(cmd, "params", {})
                cmd_notes = getattr(cmd, "notes", "")
                params_str = ", ".join(f"{k}={v}" for k, v in cmd_params.items())
                line = f"- {cmd_type}: {params_str}"
                if cmd_notes:
                    line += f"  [{cmd_notes}]"
                lines.append(line)
            lines.append("")

        # Climate events
        if tr.climate_events:
            lines.append("## 天时气候")
            for tid, event in tr.climate_events.items():
                if event.value != "normal":
                    lines.append(f"- {tid}: {event.value}")
            if all(e.value == "normal" for e in tr.climate_events.values()):
                lines.append("全境风调雨顺")
            lines.append("")

        # Resource changes
        if tr.resource_changes:
            lines.append("## 资源变化")
            for fid, changes in tr.resource_changes.items():
                parts = []
                if changes.get("food_delta", 0):
                    parts.append(f"粮草{changes['food_delta']:+d}")
                if changes.get("tax_revenue", 0):
                    parts.append(f"税收+{changes['tax_revenue']}")
                if changes.get("treasury_spent", 0):
                    parts.append(f"支出-{changes['treasury_spent']}")
                if parts:
                    lines.append(f"- {fid}: {', '.join(parts)}")
            lines.append("")

        # Battles
        if tr.battles:
            lines.append("## 兵争武事")
            for b in tr.battles:
                lines.append(f"- {b.location}: {b.attacker_id} vs {b.defender_id} → {b.result.value}")
                if b.territory_captured:
                    lines.append(f"  → 领地易手: {b.location} 归 {b.attacker_id}")
                atk_loss = sum(b.attacker_casualties.values())
                def_loss = sum(b.defender_casualties.values())
                lines.append(f"  伤亡: 攻方{atk_loss} 守方{def_loss}")
            lines.append("")

        # Character events
        if tr.character_events:
            lines.append("## 人物变易")
            for evt in tr.character_events:
                t = evt.get("type", "?")
                name = evt.get("character_name", "?")
                if t == "natural_death":
                    lines.append(f"- {name} 寿终正寝")
                elif t == "defection":
                    lines.append(f"- {name} 叛逃")
                elif t == "loyalty_impact":
                    lines.append(f"- {name} 忠诚度变化 {evt.get('delta', 0):+d}")
                else:
                    lines.append(f"- {name}: {t}")
            lines.append("")

        # Faction snapshots & territories grounding
        if world_state:
            lines.append("## 天下势力及控制城池")
            for _, fs in world_state.factions.items():
                if not fs.is_active:
                    continue
                ruler_name = "未知"
                if fs.ruler_id in world_state.characters:
                    ruler_name = world_state.characters[fs.ruler_id].name
                else:
                    ruler_name = fs.ruler_id

                t_names = []
                for tid in fs.territories:
                    t = world_state.territories.get(tid)
                    if t:
                        t_names.append(t.name)

                tech_strs = []
                if hasattr(fs, "tech_levels") and fs.tech_levels:
                    for tech_name, val in fs.tech_levels.items():
                        tech_strs.append(f"{tech_name}Lvl.{val}")
                tech_info = f"，科技: {', '.join(tech_strs)}" if tech_strs else ""

                t_str = ", ".join(t_names) if t_names else "无"
                lines.append(
                    f"- {fs.name}（君主: {ruler_name}）: 兵力{fs.strength_actual:,}，"
                    f"资金{fs.treasury:,}，粮草{fs.food:,}。控制城池: {t_str}{tech_info}"
                )
            lines.append("")

            # List deceased figures to avoid revival hallucinations
            dead_names = collect_dead_characters(world_state)

            if dead_names:
                lines.append("## 已亡故/不活跃人物（不可在此回合复活或出现活跃事迹）")
                lines.append(f"- {', '.join(dead_names)}")
                lines.append("")
        elif tr.faction_snapshots:
            lines.append("## 天下态势")
            for _, fs in tr.faction_snapshots.items():
                if not fs.is_active:
                    continue
                lines.append(
                    f"- {fs.name}: 兵力{fs.strength_actual:,} 领地{len(fs.territories)} "
                    f"资金{fs.treasury:,} 粮草{fs.food:,}"
                )
            lines.append("")

        lines.append("请将以上数据撰写为史书纪事。")

        # Inject RAG context if available
        rag_ctx = self._get_rag_context(tr.year, deviation=deviation, averted_events=averted_events)
        if rag_ctx:
            lines.insert(2, rag_ctx)

        return "\n".join(lines)

    # ── Era formatting (scenario-aware) ────────────────────────

    # Era definitions for known scenarios: (reign_name, base_year)
    _ERA_MAP: dict[str, tuple[str, int]] = {
        "three-kingdoms": ("建安", 196),
        "nanming": ("弘光", 1645),
    }

    def _format_era_line(self, year: int, season: str) -> str:
        """Format an era-name line like '建安十二年春，天下纷争未休。'"""
        era_info = self._ERA_MAP.get(self._scenario)
        if era_info:
            reign_name, base_year = era_info
            era_year = year - base_year + 1  # era years are 1-indexed
            if era_year < 1:
                era_str = f"{reign_name}前{abs(era_year - 1)}年"
            elif era_year == 1:
                era_str = f"{reign_name}元年"
            else:
                era_str = f"{reign_name}{self._number_to_chinese(era_year)}年"
            return f"{era_str}{season}，天下纷争未休。"
        return f"{year}年{season}，天下纷争未休。"

    @staticmethod
    def _number_to_chinese(n: int) -> str:
        """Convert a number < 100 to Chinese numerals (e.g. 12 -> 十二)."""
        if n < 1 or n >= 100:
            return str(n)
        digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        tens_digit = ["", "十", "二十", "三十", "四十", "五十", "六十", "七十", "八十", "九十"]
        if n < 10:
            return digits[n]
        t = n // 10
        u = n % 10
        return tens_digit[t] + digits[u]

    def _offline_narrative(self, tr: TurnResult) -> str:
        """Deterministic offline narrative from TurnResult data."""
        parts: list[str] = []
        is_en = self._language == "en"

        # Header
        if is_en:
            parts.append(f"### {tr.year} {tr.season.cn.capitalize()} · Chronicle")
            # Try to use era name if applicable
            parts.append(f"Year {tr.year}, {tr.season.cn} — the realm remains in turmoil.")
        else:
            parts.append(f"### {tr.year}年{tr.season.cn} · 大事纪")
            era_line = self._format_era_line(tr.year, tr.season.cn)
            parts.append(era_line)

        # Climate
        not_normal = {tid: ev for tid, ev in tr.climate_events.items() if ev.value != "normal"}
        if not_normal:
            events_cn = {
                "drought": "大旱",
                "flood": "洪水",
                "pestilence": "瘟疫",
                "bumper_harvest": "丰年",
                "cold_wave": "寒潮",
            }
            events_en = {
                "drought": "Drought",
                "flood": "Flood",
                "pestilence": "Pestilence",
                "bumper_harvest": "Bumper Harvest",
                "cold_wave": "Cold Wave",
            }
            if is_en:
                climate_desc = "; ".join(
                    f"{tid} suffers {events_en.get(ev.value, ev.value)}" for tid, ev in not_normal.items()
                )
                parts.append(f"\n### Climate\n{climate_desc}.")
            else:
                climate_desc = "；".join(
                    f"{tid}遭{events_cn.get(ev.value, ev.value)}" for tid, ev in not_normal.items()
                )
                parts.append(f"\n### 天时气候\n{climate_desc}。")
        else:
            if is_en:
                parts.append("\n### Climate\nFavorable weather, bountiful harvest.")
            else:
                parts.append("\n### 天时气候\n是岁风调雨顺，五谷丰登。")

        # Battles
        if tr.battles:
            if is_en:
                parts.append("\n### Military Affairs")
            else:
                parts.append("\n### 兵争武事")
            battle_results_cn = {
                "decisive_victory": "大破之",
                "victory": "击败之",
                "draw": "两军相持不下",
                "defeat": "败绩",
                "decisive_defeat": "大败而归",
            }
            battle_results_en = {
                "decisive_victory": "decisively crushed",
                "victory": "defeated",
                "draw": "fought to a draw against",
                "defeat": "was defeated by",
                "decisive_defeat": "suffered a crushing defeat by",
            }
            for b in tr.battles:
                atk_loss = sum(b.attacker_casualties.values())
                def_loss = sum(b.defender_casualties.values())
                if is_en:
                    result_en = battle_results_en.get(b.result.value, "engaged")
                    parts.append(
                        f"{b.attacker_id} {result_en} {b.defender_id} at {b.location}. "
                        f"Attacker lost {atk_loss}, defender lost {def_loss}."
                    )
                else:
                    result_cn = battle_results_cn.get(b.result.value, "交战")
                    parts.append(
                        f"{b.attacker_id}军攻{b.defender_id}于{b.location}，{result_cn}。"
                        f"攻方折兵{atk_loss}，守方损兵{def_loss}。"
                    )
                if b.territory_captured:
                    if is_en:
                        parts.append(f"{b.location} falls to {b.attacker_id}.")
                    else:
                        parts.append(f"{b.location}易手，归{b.attacker_id}所有。")

        # Character events
        deaths = [e for e in tr.character_events if "death" in str(e.get("type", ""))]
        if deaths:
            if is_en:
                parts.append("\n### Notable Deaths")
            else:
                parts.append("\n### 人物变易")
            for e in deaths:
                name = e.get("character_name", "?")
                year = e.get("year", tr.year)
                if is_en:
                    parts.append(f"{name} passed away in {year}.")
                else:
                    parts.append(f"{name}于{year}年病故。")

        # Resource summary
        if tr.resource_changes:
            if is_en:
                parts.append("\n### Realm Overview")
            else:
                parts.append("\n### 天下态势")
            for fid, changes in tr.resource_changes.items():
                food = changes.get("food_delta", 0)
                tax = changes.get("tax_revenue", 0)
                spent = changes.get("treasury_spent", 0)
                if food or tax or spent:
                    if is_en:
                        parts.append(f"{fid}: Food{food:+d} Tax+{tax} Spent{spent}")
                    else:
                        parts.append(f"{fid}: 粮草{food:+d} 税收+{tax} 支出{spent}")

        if is_en:
            parts.append(f"\n### Historian's Judgment\nYear {tr.year}, {tr.season.cn} — the board is set.")
        else:
            parts.append(f"\n### 史官评曰\n{tr.year}年{tr.season.cn}之局，诸君且观后变。")

        return "\n".join(parts)

    # ── Plan Suggestions ──────────────────────────────────────

    def generate_plan_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        """Generate strategic suggestions based on physics engine state.

        Args:
            world_state: Current world state from the physics engine
            faction_id: The faction to generate suggestions for

        Returns:
            List of 3-4 strategic suggestions (or generic offline fallback)
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            return ["【势力覆灭】你的势力已不存在。"]

        if not self.llm_available or not self.llm:
            return self._offline_suggestions(world_state, faction_id)

        context = self._build_suggestion_context(world_state, faction_id)

        messages = [
            {"role": "system", "content": PLAN_SUGGESTIONS_SYSTEM},
            {"role": "user", "content": context},
        ]

        try:
            metadata = {
                "turn": getattr(world_state, "turn", 0),
                "year": getattr(world_state, "year", 207),
                "season": world_state.current_season if hasattr(world_state, "current_season") else "spring",
                "category": "narrative",
                "reason": "generate_plan_suggestions",
                "faction_id": faction_id,
            }
            result = self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=3072,
                metadata=metadata,
            )
            return self._parse_suggestions(result.strip())
        except Exception:
            return self._offline_suggestions(world_state, faction_id)

    def _build_suggestion_context(self, world_state: WorldState, faction_id: str) -> str:
        """Build context for the plan suggestions prompt."""
        faction = world_state.factions.get(faction_id)
        if not faction:
            return ""

        lines: list[str] = [
            f"## 当前时间\n{world_state.year}年{world_state.season.cn} | 第{world_state.turn_number}回合\n",
            f"## 玩家势力: {faction.name}",
            f"- 兵力: {faction.strength_actual:,}",
            f"- 经济: {faction.economy_actual}/100",
            f"- 民心: {faction.morale_actual}/100",
            f"- 资金: {faction.treasury:,}",
            f"- 粮草: {faction.food:,}",
            f"- 首都: {faction.capital}",
            f"- 领地: {', '.join(faction.territories) if faction.territories else '暂无'}",
            f"- 税率: {faction.tax_rate:.0%}",
            "",
            "## 其他势力",
        ]

        for fid, fs in world_state.factions.items():
            if not fs.is_active or fid == faction_id:
                continue
            lines.append(
                f"- {fs.name}: 兵力{fs.strength_actual:,} "
                f"领地{len(fs.territories)} 关系{fs.relations.get(faction_id, 0):+d}"
            )

        # Add territory details for player faction
        lines.append("")
        lines.append("## 领土详情")
        for tid in faction.territories:
            t = world_state.territories.get(tid)
            if t:
                lines.append(
                    f"- {t.name} ({t.id}): 人口{t.population:,} 开发{t.development} "
                    f"肥沃度{t.fertility} 地形{t.terrain_type.value}"
                )
                if t.neighbors:
                    neighbor_names = [
                        f"{world_state.territories[n].name}({world_state.territories[n].owner_id or '空'})"
                        if n in world_state.territories
                        else n
                        for n in t.neighbors[:5]
                    ]
                    lines.append(f"  邻接: {', '.join(neighbor_names)}")

        # RAG context
        rag_ctx = self._get_rag_context(world_state.year)
        if rag_ctx:
            lines.insert(2, rag_ctx)

        lines.append("\n请基于以上物理状态，为该势力生成3-4条具体可执行的战略建议。")

        return "\n".join(lines)

    def _parse_suggestions(self, text: str) -> list[str]:
        """Parse LLM response into a list of suggestion strings."""
        suggestions: list[str] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Lines starting with 【 or containing 】 are suggestions
            if "【" in line:
                suggestions.append(line)
            elif line[0].isdigit() and ". " in line:
                suggestions.append(line.split(". ", 1)[1])
        return suggestions[:4] if suggestions else [text[:200]]

    def _offline_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        """Deterministic strategy suggestions based on physics engine state."""
        faction = world_state.factions.get(faction_id)
        if not faction:
            return []

        suggestions: list[str] = []
        territories = faction.territories

        # Resource assessment
        food_low = faction.food < 2000
        troops_low = faction.strength_actual < 5000
        treasury_ok = faction.treasury > 2000

        if food_low and territories:
            suggestions.append(
                f"【劝课农桑】发展{territories[0]}的农业，提升粮食产量。当前粮草仅{faction.food}，亟需补充。"
            )
        elif troops_low and treasury_ok and territories:
            suggestions.append(
                f"【征募乡勇】在{territories[0]}招募步兵，增强军力。当前仅{faction.strength_actual}兵卒，不足以御敌。"
            )

        # Expansion check
        for tid in territories:
            t = world_state.territories.get(tid)
            if not t:
                continue
            for nid in t.neighbors:
                nt = world_state.territories.get(nid)
                if nt and nt.owner_id != faction_id and nt.owner_id:
                    suggestions.append(
                        f"【兵锋东指】攻取{nid}（{nt.name}），当前属{nt.owner_id}。"
                        f"侦察显示该地人口{nt.population}，可充实国力。"
                    )
                    break
                elif nt and not nt.owner_id:
                    suggestions.append(f"【据土略地】派军占据{nid}（{nt.name}），该地现为空城。")
                    break
            if len(suggestions) >= 2:
                break

        # Diplomacy
        neighbors = set()
        for tid in territories:
            t = world_state.territories.get(tid)
            if t:
                for nid in t.neighbors:
                    nt = world_state.territories.get(nid)
                    if nt and nt.owner_id and nt.owner_id != faction_id:
                        neighbors.add(nt.owner_id)

        for nfid in list(neighbors)[:1]:
            nf = world_state.factions.get(nfid)
            if nf:
                rel = nf.relations.get(faction_id, 0)
                if rel >= 0:
                    suggestions.append(f"【遣使修好】派使者加强与{nf.name}的盟约关系。当前关系{rel:+d}，联合可抗强敌。")

        # Ensure 3-4 suggestions
        if len(suggestions) < 3 and territories:
            suggestions.append(f"【固本培元】发展{territories[0]}至更高开发度，提升税收和粮食产量。")
        if len(suggestions) < 3:
            suggestions.append("【远交近攻】审视外交局势，联合远方势力对抗近邻。")
        if len(suggestions) < 3:
            suggestions.append("【厉兵秣马】招募兵勇，操练新军，等待时机。")

        return suggestions[:4]

    # ── RAG Integration ────────────────────────────────────────

    def _get_rag_context(self, year: int, deviation: float = 0.0, averted_events: list[str] | None = None) -> str:
        """Retrieve and format RAG context for the given year."""
        if not self._rag:
            return ""
        try:
            events = self._rag.retrieve(year, deviation=deviation, max_events=5, averted_events=averted_events)
            if events:
                return self._rag.build_llm_context(events)
        except Exception:
            pass
        return ""

    def get_rag_instance(self):
        """Expose the RAG instance for external use."""
        return self._rag
