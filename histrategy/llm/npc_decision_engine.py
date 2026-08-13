"""
NPCDecisionEngine — generates independent quarterly decisions for a single NPC faction.

Each NPC faction gets its own LLM call — not generated "as a side effect"
inside MacroPolicyEngine. This is a core component of the symmetric multiplayer
engine: NPCs and humans are fully symmetric in their decision-generation path.

Major factions (cao/shu/wu):
    Use LLM independent decisions → NPCDecisionEngine.generate()

Minor factions (liubiao/liuzhang/machao/zhanglu):
    Use heuristic rules → _generate_heuristic()
    Reason: reduce token cost and prevent behavior from deviating from history
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from histrategy.engine.faction_slot import FactionSlot
from histrategy.llm.prompt_loader import NPC_DECISION_SYSTEM, NPC_DECISION_SYSTEM_EN

logger = logging.getLogger("histrategy.npc")

# ── Retry configuration ─────────────────────────────────────
NPC_LLM_MAX_RETRIES = 3
NPC_LLM_RETRY_BASE_DELAY = 1.5  # seconds; exponential backoff: 1.5, 3, 6
NPC_LLM_RETRYABLE_ERRORS = (
    "timeout",
    "connection",
    "rate_limit",
    "server_error",
    "Service Unavailable",
    "503",
    "502",
    "504",
    "429",
    "timed out",
    "connection reset",
)

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

def _load_active_policies_for_faction(ws, faction_id: str) -> list[dict]:
    """Load active policies from policy_state table for a faction.

    Returns list of policy dicts with keys: policy_name, policy_type,
    policy_level, params, status.
    """
    try:
        from histrategy.db.models import get_active_policies

        # Determine room_id from world_state
        room_id = getattr(ws, "room_id", "")
        if not room_id:
            return []
        return get_active_policies(room_id, faction_id)
    except Exception:
        return []


# Module-level cache of NPC decision prompts keyed by (scenario, language)
_NPC_PROMPT_CACHE: dict[tuple[str, str], str] = {}

# ── Bilingual labels for _build_context ────────────────────
_NPC_LABELS = {
    "zh": {
        "current_time": "当前时间",
        "quarter": "季度",
        "your_faction": "你的势力",
        "faction": "势力",
        "ruler": "君主",
        "troops": "兵力",
        "funds": "资金",
        "food": "粮草",
        "morale": "民心",
        "tax_rate": "税率",
        "territories": "领地",
        "personality": "你的个性",
        "aggression": "侵略性",
        "caution": "谨慎",
        "diplomacy": "外交倾向",
        "mercy": "仁慈",
        "relations": "外交关系",
        "friendly": "友好",
        "hostile": "敌对",
        "neutral": "中立",
        "rel_value": "关系值",
        "world_intel": "天下势力（斥候探报，兵力为估算值）",
        "troops_est": "兵力≈",
        "morale_est": "民心≈",
        "recent_events": "近期大事",
        "make_decision": "制定决策",
        "decision_instruction": "基于以上信息，制定本季度（三个月）的战略决策。不要重复上一回合已经失败的行动——如果攻城未克，考虑围城、外交、或转攻他处。**注意其他势力的领土变化**——如果某势力突然扩张，应立即评估威胁并做出反应。如果你有盟友，注意他们是否在抢你的战略目标（如益州）。",
        "json_output": "输出 JSON 包含 decision（自然语言描述）和 commands（结构化命令数组）。",
        "not_active": "该势力已不存在，无需决策。",
        "strategic_reminder": "策略提醒",
        "failed_attack": "⚠️ 上一回合你攻打 {target} 未克。考虑：1）围城断粮 2）外交谈判 3）转攻其他目标 4）巩固后方。盲目重复失败的行动是战略大忌。",
    },
    "en": {
        "current_time": "Current Time",
        "quarter": "Quarter",
        "your_faction": "Your Faction",
        "faction": "Faction",
        "ruler": "Ruler",
        "troops": "Troops",
        "funds": "Treasury",
        "food": "Food",
        "morale": "Morale",
        "tax_rate": "Tax Rate",
        "territories": "Territories",
        "personality": "Your Personality",
        "aggression": "Aggression",
        "caution": "Caution",
        "diplomacy": "Diplomacy",
        "mercy": "Mercy",
        "relations": "Diplomatic Relations",
        "friendly": "Friendly",
        "hostile": "Hostile",
        "neutral": "Neutral",
        "rel_value": "Relation",
        "world_intel": "Known Factions (scout reports, troop estimates)",
        "troops_est": "Troops ≈",
        "morale_est": "Morale ≈",
        "recent_events": "Recent Events",
        "make_decision": "Make Your Decision",
        "decision_instruction": "Based on the above intelligence, formulate this quarter's (three month) strategic decision. Do not repeat an action that already failed last turn — if your assault was repelled, consider siege, diplomacy, or a different target.",
        "json_output": "Output JSON with 'decision' (natural language description) and 'commands' (structured command array).",
        "not_active": "This faction no longer exists. No decision needed.",
        "strategic_reminder": "Strategic Reminder",
        "failed_attack": "⚠️  Your attack on {target} failed last turn. Consider: 1) Siege and starve them out 2) Diplomatic negotiation 3) Attack a different target 4) Consolidate your rear. Repeating a failed assault is a strategic blunder.",
    },
}

# Default Three Kingdoms prompt (for backward compatibility)


def _load_npc_prompt(scenario: str | None, language: str = "zh") -> str:
    """Load scenario-specific NPC decision prompt with language fallback.

    Priority:
    1. scenarios/{scenario}/prompts/npc_decision_{lang}.md
    2. scenarios/{scenario}/prompts/npc_decision_en.md
    3. scenarios/{scenario}/prompts/npc_decision.md
    4. Fall back to module-level default (Three Kingdoms)
    """
    if not scenario or scenario in ("three-kingdoms", ""):
        # For Three Kingdoms, support English prompt
        if language and language.startswith("en"):
            return NPC_DECISION_SYSTEM_EN
        return NPC_DECISION_SYSTEM

    cache_key = (scenario, language)
    if cache_key in _NPC_PROMPT_CACHE:
        return _NPC_PROMPT_CACHE[cache_key]

    # Try scenario-specific prompts directory
    candidates = [
        Path(f"scenarios/{scenario}/prompts/npc_decision_{language}.md"),
        Path(f"scenarios/{scenario}/prompts/npc_decision_en.md"),
        Path(f"scenarios/{scenario}/prompts/npc_decision.md"),
    ]

    for p in candidates:
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                _NPC_PROMPT_CACHE[cache_key] = content
                return content
            except Exception:
                pass

    # Fall back to default
    return NPC_DECISION_SYSTEM


# Available command types (must match IntentParser)
NPC_COMMAND_TYPES = [
    "attack",
    "defend",
    "recruit",
    "move",
    "develop",
    "diplomacy",
    "tax",
    "conscript",
    "disband",
    "appoint",
    "wait",
]


def _resolve_border(ws: WorldState, faction_id: str, neighbor_id: str) -> str | None:
    """Find the border territory between two factions.

    Returns the territory ID of the faction that borders the neighbor, or None.
    """
    faction = ws.factions.get(faction_id)
    neighbor = ws.factions.get(neighbor_id)
    if not faction or not neighbor:
        return None

    my_territories = set(getattr(faction, "territories", []))
    neighbor_territories = set(getattr(neighbor, "territories", []))

    for tid in my_territories:
        territory = ws.territories.get(tid)
        if territory and hasattr(territory, "neighbors"):
            for nid in territory.neighbors:
                if nid in neighbor_territories:
                    return tid
    return None


class NPCDecisionEngine:
    """Generates independent quarterly decisions for a single NPC faction.

    Key design principles:
    1. FOW (Fog of War) — NPC only sees estimated troop counts of adjacent factions
    2. Personality-driven — different NPCs have different aggression/caution params
    3. Memory-aware — NPC sees summaries of the last N turns
    4. Scenario-aware — loads scenario-specific prompts from scenarios/{name}/prompts/,
       with multi-language support
    """

    def __init__(self, llm: LLMAdapter | None = None, scenario: str | None = None, language: str = "zh"):
        self.llm = llm
        self.llm_available = llm is not None and llm.is_available
        self.scenario = scenario
        self.language = language
        self._history_engine = None  # set via set_history_engine()

    def set_history_engine(self, engine) -> None:
        """Attach a ConditionalHistoryEngine for context injection."""
        self._history_engine = engine

    def generate(
        self,
        world_state: WorldState,
        faction_id: str,
        turn_memory: list[dict] | None = None,
        slot: FactionSlot | None = None,
        room_id: str = "",
        quarter_number: int = 0,
        scenario: str | None = None,
    ) -> tuple[str, list]:
        """Generate this NPC faction's quarterly decision.

        Args:
            world_state: Current world state (global view, but NPC internally projects FOW)
            faction_id: This NPC's faction ID
            turn_memory: Recent turn summary list
            slot: FactionSlot (optional, for reading AI config)
            scenario: Override scenario name (for loading scenario-specific prompt)
            room_id: Room ID (for DB logging)
            quarter_number: Quarter number (for DB logging)

        Returns:
            (decision_text, parsed_commands)
                decision_text: Natural language decision text (for narrative and record)
                parsed_commands: Structured command list
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            L = _NPC_LABELS.get(self.language, _NPC_LABELS["zh"])
            return L["not_active"], []

        # Use LLM for major factions; fall back to heuristic for minor
        use_llm = self.llm_available and self.llm is not None

        if not use_llm:
            return self._generate_heuristic(world_state, faction_id)

        # ── Retry loop with exponential backoff ──────────────────
        last_error: Exception | None = None
        for attempt in range(1, NPC_LLM_MAX_RETRIES + 1):
            try:
                return self._generate_llm(
                    world_state,
                    faction_id,
                    faction,
                    turn_memory or [],
                    slot,
                    room_id,
                    quarter_number,
                    scenario or self.scenario,
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_retryable = any(keyword.lower() in error_str for keyword in NPC_LLM_RETRYABLE_ERRORS)

                if not is_retryable:
                    # Non-retryable error (e.g. JSON parse error, bad request)
                    logger.warning(
                        f"NPCDecisionEngine non-retryable LLM error for {faction_id} "
                        f"(attempt {attempt}/{NPC_LLM_MAX_RETRIES}): {e}"
                    )
                    break

                if attempt < NPC_LLM_MAX_RETRIES:
                    delay = NPC_LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"NPCDecisionEngine LLM error for {faction_id} "
                        f"(attempt {attempt}/{NPC_LLM_MAX_RETRIES}, "
                        f"retrying in {delay:.1f}s): {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"NPCDecisionEngine LLM failed after {NPC_LLM_MAX_RETRIES} attempts for {faction_id}: {e}"
                    )

        # All retries exhausted or non-retryable error → fall back to heuristic
        logger.warning(f"NPCDecisionEngine falling back to heuristic for {faction_id} (last error: {last_error})")
        return self._generate_heuristic(world_state, faction_id)

    def _generate_llm(
        self,
        ws: WorldState,
        faction_id: str,
        faction,
        turn_memory: list[dict],
        slot: FactionSlot | None,
        room_id: str = "",
        quarter_number: int = 0,
        scenario: str | None = None,
    ) -> tuple[str, list]:
        """LLM-generated decision."""
        context = self._build_context(ws, faction_id, faction, turn_memory)

        temperature = slot.ai_temperature if slot else 0.7
        system_prompt = _load_npc_prompt(scenario or self.scenario, self.language)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        response = self.llm.chat_structured(
            messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=800,
            metadata={
                "category": "npc_decision",
                "faction_id": faction_id,
                "system_prompt_type": "npc_decision",
                "room_id": room_id,
                "quarter_number": quarter_number,
            },
        )

        if isinstance(response, str):
            response = self._extract_json(response)

        decision = response.get(
            "decision", "观望待机" if self.language == "zh" else "Watching and waiting for the right moment."
        )
        raw_commands = response.get("commands", [])

        # Normalize commands to canonical format
        commands = self._normalize_commands(raw_commands, faction_id)

        # Note: LLMAdapter already logs the call to llm_call_log via _log_to_db.
        # No separate log_llm_call needed here.

        return decision, commands

    def _generate_heuristic(
        self,
        ws: WorldState,
        faction_id: str,
    ) -> tuple[str, list]:
        """Heuristic rule-based decision (minor factions or when LLM unavailable).

        Now significantly more context-aware:
        - Considers neighbor threats (troop ratios, hostile relations)
        - Strategic defense when outnumbered
        - Opportunistic attack when stronger than neighbors
        - Development when at peace
        - Tax/economic management
        """
        faction = ws.factions.get(faction_id)
        if not faction:
            return "休整" if self.language == "zh" else "Rest", []

        is_en = self.language == "en"
        commands: list[dict] = []
        decision_parts: list[str] = []

        def _cmd(type_: str, params: dict, reasoning: str) -> dict:
            return {
                "type": type_,
                "params": params,
                "reasoning": reasoning,
                "faction_id": faction_id,
            }

        strength = getattr(faction, "strength_actual", 0)
        treasury = getattr(faction, "treasury", 0)
        food = getattr(faction, "food", 0)
        morale = getattr(faction, "morale_actual", 50)
        territories = list(getattr(faction, "territories", []))
        capital = getattr(faction, "capital", territories[0] if territories else None)
        aggression = getattr(faction, "aggression", 0.5)
        diplomacy = getattr(faction, "diplomacy", 0.5)
        relations = getattr(faction, "relations", {})

        # ── Analyze neighbors ──────────────────────────────────
        neighbors = self._get_neighbors(ws, faction_id)
        hostile_neighbors = []
        friendly_neighbors = []
        total_neighbor_strength = 0

        for nid in neighbors:
            nf = ws.factions.get(nid)
            if nf is None or not getattr(nf, "is_active", True):
                continue
            n_strength = getattr(nf, "strength_actual", 0)
            total_neighbor_strength += n_strength

            rel = relations.get(nid, 0)
            if rel < -30:
                hostile_neighbors.append((nid, nf, n_strength))
            elif rel > 30:
                friendly_neighbors.append((nid, nf, n_strength))

        # ── NPC recruitment: handled by the LLM npc_decision path via structured
        # recruit/conscript/disband commands (see quarterly_resolver H36k/H36r).
        # This heuristic fallback deliberately omits recruit/conscript to avoid
        # double-recruitment. The old deterministic auto-recruit
        # (execute_npc_recruitment) was removed in H37d.

        # ── Priority 2.5: Starvation — MUST develop if food is 0 ──
        if food <= 0 and territories:
            # Develop the capital or most populated territory to grow food
            develop_target = capital or territories[0]
            commands.append(
                _cmd(
                    "develop",
                    {"territory": develop_target},
                    "粮草断绝，紧急屯田以解燃眉之急" if not is_en else "Starving — emergency farming to avert famine",
                )
            )
            decision_parts.append(
                f"屯田{develop_target}" if not is_en else f"Farm {develop_target}"
            )
            # Also trade for food if treasury allows
            if treasury > 1000:
                commands.append(
                    _cmd(
                        "trade",
                        {"resource": "food"},
                        "以金购粮，救急" if not is_en else "Buy food with treasury",
                    )
                )

        # ── Priority 3: Attack weak hostile neighbor ──
        # ⚠️ Food gate: no attacking when starving — develop/trade instead
        # Threshold: 1.2x strength advantage (lowered from 1.5x to prevent stagnation)
        attack_made = False
        if hostile_neighbors and aggression > 0.3 and food > 0:
            # Sort by strength ascending — target the weakest hostile neighbor
            hostile_neighbors.sort(key=lambda x: x[2])
            for nid, nf, n_strength in hostile_neighbors:
                if strength > n_strength * 1.2 and strength > 3000:
                    n_territories = list(getattr(nf, "territories", []))
                    target = n_territories[0] if n_territories else None
                    if target:
                        commands.append(
                            _cmd(
                                "attack",
                                {"target": target, "target_faction": nid},
                                f"趁敌弱，先发制人进攻{nid}" if not is_en else f"Preemptive strike on weaker {nid}",
                            )
                        )
                        decision_parts.append(f"出兵攻打{nid}" if not is_en else f"Attack {nid}")
                        attack_made = True
                        break

        # ── Priority 3.5: Desperation attack — when outnumbered but must fight ──
        # If we couldn't attack through Priority 3 (no 1.2x advantage) but have
        # hostile neighbors and enough troops, gamble on a surprise attack.
        # This prevents the infinite "defend → defend → defend" stagnation loop.
        if not attack_made and hostile_neighbors and food > 5000 and strength > 10000:
            # Target the weakest hostile, even if stronger than us
            hostile_neighbors.sort(key=lambda x: x[2])
            for nid, nf, n_strength in hostile_neighbors:
                if strength > n_strength * 0.6:  # Don't suicide against 2x stronger
                    n_territories = list(getattr(nf, "territories", []))
                    target = n_territories[0] if n_territories else None
                    if target:
                        commands.append(
                            _cmd(
                                "attack",
                                {"target": target, "target_faction": nid},
                                f"背水一战，奇袭{nid}" if not is_en else f"Desperate gamble — surprise attack on {nid}",
                            )
                        )
                        decision_parts.append(
                            f"孤注一掷奇袭{nid}" if not is_en else f"Desperate attack on {nid}"
                        )
                        attack_made = True
                        break

        # ── Priority 4: Defend against stronger hostile neighbors ──
        if hostile_neighbors and not attack_made:
            stronger_hostiles = [(nid, nf, s) for nid, nf, s in hostile_neighbors if s > strength]
            if stronger_hostiles:
                strongest = max(stronger_hostiles, key=lambda x: x[2])
                border = _resolve_border(ws, faction_id, strongest[0])
                commands.append(
                    _cmd(
                        "defend",
                        {"target": strongest[0], "border": border},
                        f"敌强我弱，固守{border or '边境'}防御{strongest[0]}"
                        if not is_en
                        else f"Outnumbered, fortify {border or 'border'} against {strongest[0]}",
                    )
                )
                decision_parts.append(
                    f"固守{border or '边境'}以御{strongest[0]}"
                    if not is_en
                    else f"Fortify border against {strongest[0]}"
                )

        # ── Priority 5: Develop economy during peace ──
        if not attack_made and treasury > 3000 and food > 2000 and capital and not hostile_neighbors:
            commands.append(
                _cmd(
                    "develop",
                    {"territory": capital},
                    "天下太平，发展领地经济" if not is_en else f"Peacetime development of {capital}",
                )
            )
            decision_parts.append(f"开发{capital}" if not is_en else f"Develop {capital}")

        # ── Priority 6: Tax adjustment ──
        if morale < 30 and getattr(faction, "tax_rate", 0.3) > 0.25:
            new_rate = max(0.15, getattr(faction, "tax_rate", 0.3) - 0.10)
            commands.append(
                _cmd(
                    "tax",
                    {"tax_rate": round(new_rate, 2)},
                    "民心低迷，轻徭薄赋以安民" if not is_en else "Morale low, reducing taxes to pacify populace",
                )
            )
            decision_parts.append(
                f"减税至{int(new_rate * 100)}%" if not is_en else f"Reduce tax to {int(new_rate * 100)}%"
            )
        elif getattr(faction, "tax_rate", 0.3) > 0.35:
            commands.append(
                _cmd("tax", {"tax_rate": 0.30}, "减轻民负，稳定统治" if not is_en else "Ease the people's burden")
            )
            decision_parts.append("降低税率至三成" if not is_en else "Reduce tax rate to 30%")

        # ── Priority 7: Diplomacy with neutrals if warlike ──
        if not attack_made and hostile_neighbors and aggression < 0.5 and diplomacy > 0.4:
            neutral_neighbors = [
                nid
                for nid in neighbors
                if nid not in {h[0] for h in hostile_neighbors} and nid not in {f[0] for f in friendly_neighbors}
            ]
            if neutral_neighbors and treasury > 2000:
                target = neutral_neighbors[0]
                commands.append(
                    _cmd(
                        "diplomacy",
                        {"target": target, "action": "improve_relations"},
                        f"派出使者改善与{target}的关系"
                        if not is_en
                        else f"Send envoy to improve relations with {target}",
                    )
                )
                decision_parts.append(f"出使{target}改善邦交" if not is_en else f"Send envoy to {target}")

        # ── Build final decision text ──
        if is_en:
            joiner = "; "
            suffix = "."
        else:
            joiner = "；"
            suffix = "。"

        if decision_parts:
            # Make it read like a coherent strategic assessment
            decision_text = joiner.join(decision_parts) + suffix
        else:
            decision_text = "休整观望，静待时机。" if not is_en else "Resting and observing, awaiting the right moment."

        return decision_text, commands

    def _build_context(
        self,
        ws: WorldState,
        faction_id: str,
        faction,
        turn_memory: list[dict],
    ) -> str:
        """Build LLM decision context (FOW-aware). Language-controlled via self.language."""
        L = _NPC_LABELS.get(self.language, _NPC_LABELS["zh"])
        lines: list[str] = []

        # Explicit language instruction at the very top
        if self.language == "en":
            lines.append(
                "IMPORTANT: You MUST write the decision_text in English. "
                "All narrative output must be in English. "
                "Do NOT output Chinese characters."
            )
            lines.append("")

        # Time
        season_cn = getattr(ws, "current_season_cn", str(getattr(ws, "season_index", "?")))
        turn = getattr(ws, "turn", 0)
        lines.append(f"## {L['current_time']}\n{ws.year}, {season_cn} | {L['quarter']} {turn}\n")

        # Own state — clearly mark current territory ownership
        lines.append(f"## {L['your_faction']}")
        lines.append("### ⚠️ 当前实际控制（请勿用历史知识覆盖）")
        lines.append(f"{L['faction']}: {faction.name} ({faction_id})")
        lines.append(f"{L['ruler']}: {getattr(faction, 'ruler_id', '')}")
        lines.append(f"{L['troops']}: {getattr(faction, 'strength_actual', 0):,}")
        lines.append(
            f"{L['funds']}: {getattr(faction, 'treasury', 0):,} | {L['food']}: {getattr(faction, 'food', 0):,}"
        )
        lines.append(
            f"{L['morale']}: {getattr(faction, 'morale_actual', 50)} | {L['tax_rate']}: {int(getattr(faction, 'tax_rate', 0.3) * 100)}%"
        )
        territories = list(getattr(faction, "territories", []))
        if territories:
            lines.append(f"🏰 **{L['territories']}**: {territories}")
        else:
            no_territory_text = (
                "[] （无固定领地，可能处于迁徙中或依附他方）"
                if self.language == "zh"
                else "[] (no fixed territory — may be migrating or vassalized)"
            )
            lines.append(f"🏰 **{L['territories']}**: {no_territory_text}")
        lines.append("")

        # ── 财政可持续性预警 (Treasury Sustainability Warning) ──
        # H36b: NPCs need to see their financial runway to make realistic decisions.
        # 金兵比 = treasury / troops shows how many "gold units" back each soldier.
        # Below 1.0, the faction cannot sustain its army — NPCs must react.
        _treasury_val = getattr(faction, "treasury", 0)
        _strength_val = getattr(faction, "strength_actual", 1)
        _gold_per_soldier = _treasury_val / max(_strength_val, 1)
        _maint_est = int(_strength_val * 0.015)  # rough quarterly maintenance
        if self.language == "zh":
            lines.append("## ⚠️ 财政预警 (Treasury Warning)")
            lines.append(f"当前金库: {_treasury_val:,} | 兵力: {_strength_val:,} | 金兵比: {_gold_per_soldier:.2f}")
            lines.append(f"每季军费约: {_maint_est:,}（兵力 × 0.015）")
            if _gold_per_soldier <= 0:
                lines.append("🚨 **金库已空！无法发饷！必须立即裁军或掠夺。继续维持当前兵力将导致士气崩溃和逃兵潮。**")
                lines.append("- 不可进攻、不可征兵、不可维持大军")
                lines.append("- 优先行动：裁军/提高税率/掠夺邻国/求和")
            elif _gold_per_soldier < 0.5:
                lines.append(f"⚠️ 金兵比仅 {_gold_per_soldier:.2f}——军饷仅够维持 {int(_gold_per_soldier * 3)} 个月。请优先增加收入或缩减军队。")
                lines.append("- 谨慎进攻，优先发展经济")
            elif _gold_per_soldier < 1.0:
                lines.append(f"⚡ 金兵比 {_gold_per_soldier:.2f}——财政偏紧。维持现有军队可行但无余裕扩张。")
        else:
            lines.append("## ⚠️ Treasury Warning")
            lines.append(f"Current Treasury: {_treasury_val:,} | Troops: {_strength_val:,} | Gold/Soldier: {_gold_per_soldier:.2f}")
            lines.append(f"Est. quarterly maintenance: {_maint_est:,} (troops × 0.015)")
            if _gold_per_soldier <= 0:
                lines.append("🚨 **Treasury is EMPTY! Cannot pay troops! Must disband or raid immediately.**")
                lines.append("- No attacks, no recruitment, cannot sustain current army")
                lines.append("- Priority: disband troops / raise taxes / raid neighbors / sue for peace")
            elif _gold_per_soldier < 0.5:
                lines.append(f"⚠️ Gold/Soldier only {_gold_per_soldier:.2f} — can only sustain army for ~{int(_gold_per_soldier * 3)} months. Prioritize income or reduce troops.")
            elif _gold_per_soldier < 1.0:
                lines.append(f"⚡ Gold/Soldier {_gold_per_soldier:.2f} — treasury is tight. Can maintain current army but no room for expansion.")
        lines.append("")

        # ── H36m: 士气预警 (Morale Warning) ──
        # Morale death spiral: once morale drops below ~20, tax penalties suppress
        # recovery → morale → 0 → faction effectively paralyzed. NPCs must break
        # this cycle by lowering taxes and/or winning a battle.
        _morale_val = getattr(faction, "morale_actual", 50)
        if self.language == "zh":
            if _morale_val < 10:
                lines.append("## 🚨 士气崩溃预警 (Morale Collapse)")
                lines.append(f"当前士气仅 {_morale_val}！**这是你的首要危机。**")
                lines.append(f"- 当前税率 {int(getattr(faction, 'tax_rate', 0.3) * 100)}% —— **必须立即降至 10% 以下**，否则士气将继续下降。")
                lines.append("- 禁止征兵（conscript 会进一步打击士气）。")
                lines.append("- 优先行动：降税 → 发展经济 → 犒赏三军。暂停一切进攻。")
            elif _morale_val < 20:
                lines.append("## ⚠️ 士气危机预警 (Morale Crisis)")
                lines.append(f"当前士气仅 {_morale_val}，军队人心浮动。")
                lines.append("- 若税率 > 10%，士气每季将继续下降。**强烈建议降税。**")
                lines.append("- 谨慎进攻——若战败，士气将进一步恶化。")
            elif _morale_val < 35:
                lines.append("## ⚡ 士气偏弱预警 (Low Morale)")
                lines.append(f"当前士气 {_morale_val}，低于健康水平。")
                lines.append("- 高税率（>20%）会压制士气恢复。考虑适当减税。")
        else:
            if _morale_val < 10:
                lines.append("## 🚨 Morale Collapse Warning")
                lines.append(f"Current morale: {_morale_val}! **This is your TOP priority.**")
                lines.append(f"- Current tax rate {int(getattr(faction, 'tax_rate', 0.3) * 100)}% — **MUST reduce below 10%** or morale keeps dropping.")
                lines.append("- No conscription (further morale hit).")
                lines.append("- Priority: lower taxes → develop economy → reward troops. No attacks.")
            elif _morale_val < 20:
                lines.append("## ⚠️ Morale Crisis Warning")
                lines.append(f"Current morale: {_morale_val}. Troops are wavering.")
                lines.append("- If tax rate > 10%, morale will drop every quarter. **Strongly recommend tax cut.**")
                lines.append("- Avoid risky attacks — a defeat will worsen morale further.")

        # ── FULL TERRITORY MAP: show which faction controls which territories ──
        # Without this, NPCs hallucinate enemy presence in wrong regions
        # (e.g. Zheng attacking "Qing in Xiamen" when Qing has zero coastal territory).
        lines.append("## 🌍 天下版图 (Territory Map — ALL factions)")
        lines.append("⚠️ 以下为当前回合的实际版图。请根据此版图规划行动，勿用历史知识覆盖。")
        for ofid, ofaction in ws.factions.items():
            if not getattr(ofaction, "is_active", True):
                continue
            oterrs = list(getattr(ofaction, "territories", []))
            oname = getattr(ofaction, "name", ofid)
            if oterrs:
                lines.append(f"- **{oname}** ({ofid}): {', '.join(oterrs)}")
            else:
                lines.append(f"- **{oname}** ({ofid}): 无固定领地 ≈ 流亡/附庸状态")
        lines.append("")
        lines.append("### 🚫 地理约束 (Geography Constraints)")
        lines.append("- 清(qing)仅在北方五省(北京/盛京/山西/陕西/甘肃)。1645年尚未控制福建、广东、浙江等南方地区")
        lines.append("- 郑(zheng)仅据福建、广东沿海，不应在北方内陆与清军陆战")
        lines.append("- 农民军(nongminjun)据襄阳、四川(成都+汉中)，不与郑氏或清军内陆直接接壤")
        lines.append("- 南明(nanming)控制长江以南至河南、山东，是四股势力中领土最广的")
        lines.append("- **仅当两势力领土相邻时，才能发生直接军事冲突。** 不相邻的势力不可远征攻伐。")
        lines.append("")

        # Terrain / strategic geography
        lines.append("## 战略地理 (Strategic Geography)")
        if "jiangling" in territories or "baiti" in territories or "cd" in territories:
            lines.append("- 三峡天险: 溯江攻蜀需经三峡(白帝→巴郡→成都)，水急滩险，一季最多推进至白帝城")
            lines.append("- 蜀道难行: 益州山地栈道崎岖，从白帝到成都需约6个月")
        # Check for Hefei-related proximity
        for t in territories:
            if t in ("jianye", "chaishang", "lujiang", "wujun"):
                lines.append("- **合肥(hefei)**: 曹操从合肥渡淮南下可直逼建业，是东线牵制的关键")
                break
        # ── Rome-specific political constraints (44 BC) ──
        if getattr(self, "_scenario", "") == "rome-triumvirate" or "rome" in str(getattr(ws, "scenario", "")):
            lines.append("## ⚖️ Rome Political Reality (44 BC)")
            lines.append("- **Res Publica**: The Republic still exists in name. Direct military attacks on Rome or fellow citizens without Senatorial authorization = tyranny = ALL factions unite against you.")
            lines.append("- **Legitimacy > Legions**: Consuls, tribunes, and Senatorial decrees carry legal weight. A faction with Senate backing can raise troops legally; one without it is a warlord.")
            lines.append("- **Cicero's Game**: The Senate (Cicero) will try to play Antony and Octavian against each other. The young Octavian is their 'tool to be praised, used, and discarded.'")
            lines.append("- **Antony's Burden**: As consul, Antony controls Rome legally — but every move he makes is scrutinized. Attacking Octavian directly would justify Cicero's 'Antony is a tyrant' narrative.")
            lines.append("- **Octavian's Weapon**: He has no army but possesses Caesar's name. Veterans will flock to him if he can secure his inheritance. His best move is political: ally with Senate, demand inheritance, build legitimacy.")
            lines.append("- **Cleopatra's Position**: Egypt is rich but vulnerable. She must back a Roman strongman to survive — but backing the wrong one means ruin.")
            lines.append("- **The Real Enemy**: Brutus and Cassius are raising armies in the East. The Caesarian factions must eventually deal with the Liberators — or be destroyed by them.")
            lines.append("")
            lines.append("")

        # Personality params
        aggression = getattr(faction, "aggression", 0.5)
        caution = getattr(faction, "caution", 0.5)
        diplomacy = getattr(faction, "diplomacy", 0.5)
        mercy = getattr(faction, "mercy", 0.5)
        lines.append(f"## {L['personality']}")
        lines.append(f"{L['aggression']}: {aggression:.1f} | {L['caution']}: {caution:.1f}")
        lines.append(f"{L['diplomacy']}: {diplomacy:.1f} | {L['mercy']}: {mercy:.1f}")
        lines.append("")

        # Conditional historical events — inject what could happen
        if self._history_engine is not None:
            history_ctx = self._history_engine.get_active_context(ws)
            if history_ctx:
                lines.append(history_ctx)
                lines.append("")

        # Diplomatic relations
        relations = getattr(faction, "relations", {})
        if relations:
            lines.append(f"## {L['relations']}")
            for target_id, rel in relations.items():
                if target_id == faction_id:
                    continue
                target = ws.factions.get(target_id)
                target_name = target.name if target else target_id
                if rel > 30:
                    rel_str = L["friendly"]
                elif rel < -30:
                    rel_str = L["hostile"]
                else:
                    rel_str = L["neutral"]
                lines.append(f"- {target_name} ({target_id}): {rel_str} ({L['rel_value']} {rel})")
            lines.append("")

        # Surrounding intelligence (FOW: estimated values)
        lines.append(f"## {L['world_intel']}")
        for fid, f in ws.factions.items():
            if fid == faction_id or not getattr(f, "is_active", True):
                continue
            est_str = getattr(f, "strength_actual", 0)
            morale_est = getattr(f, "morale_actual", 50)
            food_est = getattr(f, "food", 0)
            treasury_est = getattr(f, "treasury", 0)
            ft = list(getattr(f, "territories", []))
            lines.append(
                f"- {getattr(f, 'name', fid)} ({fid}): "
                f"{L['troops_est']}{est_str:,}, {L['morale_est']}{morale_est}, "
                f"粮≈{food_est:,}, 金≈{treasury_est:,}, "
                f"{L['territories']}={ft}"
            )
        lines.append("")

        # Active policies — inject faction-specific political/diplomatic state
        # (e.g. "马士英被闲置", "屯田制已实施", "与南明结盟").
        # This prevents LLM from hallucinating events that contradict past decisions.
        active_policies = _load_active_policies_for_faction(ws, faction_id)
        if active_policies:
            lines.append("## 📜 当前生效的政策法令 (Active Policies)")
            lines.append("以下政策是此前决策的结果，已实际生效。你的决策必须遵守这些约束：")
            for p in active_policies:
                pname = p.get("policy_name", "")
                ptype = p.get("policy_type", "law")
                plevel = p.get("policy_level", 1)
                pparams = p.get("params", {})
                extra = ""
                if isinstance(pparams, dict) and pparams:
                    extra_parts = [f"{k}={v}" for k, v in pparams.items() if k not in ("status", "type")]
                    if extra_parts:
                        extra = f" ({', '.join(extra_parts)})"
                lines.append(f"- [{ptype}] {pname} (Lv.{plevel}){extra}")
            lines.append("")

        # Historical memory
        if turn_memory:
            lines.append(f"## {L['recent_events']}")
            last_attack_target = None
            last_attack_quarter = -1
            for mem in turn_memory[-5:]:
                summary = mem.get("outcome_summary", "")
                qnum = mem.get("quarter", 0)
                if summary:
                    lines.append(f"- {summary}")
                    # 检测上一回合是否有本势力的进攻
                    arrow = f"{faction_id}→"
                    if arrow in summary:
                        m = re.search(rf"{re.escape(faction_id)}→(\w+)", summary)
                        if m and qnum > last_attack_quarter:
                            last_attack_target = m.group(1)
                            last_attack_quarter = qnum
            lines.append("")

            # Show NPC's own last decision so they can deliberately change strategy
            last_own = turn_memory[-1] if turn_memory else None
            if last_own:
                last_decision = (
                    last_own.get(f"decision_{faction_id}", "")
                    or last_own.get("decision", "")
                )
                if last_decision:
                    lines.append("## ⚠️ 你的上一轮决策 (Your Last Quarter's Decision)")
                    lines.append(f"上一轮你决定: {last_decision}")
                    lines.append("**你必须在本轮采取不同的策略。不可重复相同的行动。**")
                    lines.append("")

            # 只在最近一回合有进攻行为时显示策略提醒（避免死循环）
            current_quarter = getattr(ws, "turn", 0) or 0
            if last_attack_target and last_attack_quarter >= current_quarter - 1:
                lines.append(f"## {L['strategic_reminder']}")
                lines.append(L["failed_attack"].format(target=last_attack_target))
                lines.append("")

        # Instructions
        lines.append(f"## {L['make_decision']}")
        lines.append(L["decision_instruction"])
        lines.append(L["json_output"])

        return "\n".join(lines)

    def _normalize_commands(self, raw: list, faction_id: str) -> list[dict]:
        """Normalize LLM output commands to canonical format."""
        commands = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            cmd_type = item.get("type", "")
            if cmd_type not in NPC_COMMAND_TYPES:
                continue
            commands.append(
                {
                    "type": cmd_type,
                    "params": item.get("params", {}),
                    "reasoning": item.get("reasoning", ""),
                    "faction_id": faction_id,
                }
            )
        return commands

    def _get_neighbors(self, ws: WorldState, faction_id: str) -> list[str]:
        """Get list of neighboring faction IDs."""
        neighbors: set[str] = set()
        faction = ws.factions.get(faction_id)
        if not faction:
            return []
        my_territories = set(faction.territories) if faction.territories else set()
        for tid in my_territories:
            territory = ws.territories.get(tid)
            if territory and territory.neighbors:
                for nid in territory.neighbors:
                    neighbor_territory = ws.territories.get(nid)
                    if neighbor_territory and neighbor_territory.owner_id != faction_id:
                        neighbors.add(neighbor_territory.owner_id)
        return list(neighbors)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from text response."""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试提取 {...}
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {}
