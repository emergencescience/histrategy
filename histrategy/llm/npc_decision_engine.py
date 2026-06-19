"""
NPCDecisionEngine — 为一个 NPC faction 生成独立季度决策。

每个 NPC faction 有独立的 LLM 调用——不是"顺便"在 MacroPolicyEngine 里生成。
这是对称多人引擎的核心组件：NPC 和人类在决策生成路径上完全对称。

主要势力 (cao/shu/wu):
    使用 LLM 独立决策 → NPCDecisionEngine.generate()

次要势力 (liubiao/liuzhang/machao/zhanglu):
    使用启发式规则 → _generate_heuristic()
    原因：减少 token 成本和防止行为偏离历史
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from histrategy.engine.faction_slot import LLM_NPC_FACTIONS, FactionSlot
from histrategy.llm.prompt_loader import load_prompt

logger = logging.getLogger("histrategy.npc")

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

# Module-level cache of NPC decision prompts keyed by (scenario, language)
_NPC_PROMPT_CACHE: dict[tuple[str, str], str] = {}

# ── Bilingual labels for _build_context ────────────────────
_NPC_LABELS = {
    "zh-CN": {
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
        "decision_instruction": "基于以上信息，制定本季度（三个月）的战略决策。不要重复上一回合已经失败的行动——如果攻城未克，考虑围城、外交、或转攻他处。",
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
_NPC_DECISION_SYSTEM_DEFAULT = load_prompt(
    "npc_decision.md",
    default="你是《三國志略》中的一位诸侯，请根据当前天下形势制定本季度战略决策。",
)
_NPC_DECISION_SYSTEM_EN = load_prompt(
    "npc_decision_en.md",
    default="You are a warlord in the Three Kingdoms. Formulate this quarter's strategic decision based on the current situation.",
)


def _load_npc_prompt(scenario: str | None, language: str = "zh-CN") -> str:
    """Load scenario-specific NPC decision prompt with language fallback.

    Priority:
    1. scenarios/{scenario}/prompts/npc_decision_{lang}.md
    2. scenarios/{scenario}/prompts/npc_decision_en.md
    3. scenarios/{scenario}/prompts/npc_decision.md
    4. Fall back to module-level default (Three Kingdoms)
    """
    if not scenario or scenario in ("207", "three-kingdoms", ""):
        # For Three Kingdoms, support English prompt
        if language and language.startswith("en"):
            return _NPC_DECISION_SYSTEM_EN
        return _NPC_DECISION_SYSTEM_DEFAULT

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
    return _NPC_DECISION_SYSTEM_DEFAULT

# 可用命令类型（与 IntentParser 保持一致）
NPC_COMMAND_TYPES = [
    "attack",
    "defend",
    "recruit",
    "move",
    "develop",
    "diplomacy",
    "tax",
    "conscript",
    "appoint",
    "wait",
]


class NPCDecisionEngine:
    """为一个 NPC faction 生成独立季度决策。

    关键设计原则：
    1. FOW (Fog of War) — NPC 只能看到相邻势力的估算兵力
    2. 个性驱动 — 不同 NPC 有不同 aggression/caution 参数
    3. 记忆感知 — NPC 能看到最近 N 回合的历史摘要
    4. 场景感知 — 从 scenarios/{name}/prompts/ 加载专属 prompt，支持多语言
    """

    def __init__(self, llm: LLMAdapter | None = None, scenario: str | None = None, language: str = "zh-CN"):
        self.llm = llm
        self.llm_available = llm is not None and llm.is_available
        self.scenario = scenario
        # Normalize language: room metadata uses "zh"/"en", engine uses "zh-CN"/"en"
        if language == "zh":
            language = "zh-CN"
        self.language = language

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
        """生成 NPC 的本季度决策。

        Args:
            world_state: 当前世界状态（全局视角，但NPC内部会投影FOW）
            faction_id: 该NPC的势力ID
            turn_memory: 最近回合摘要列表
            slot: FactionSlot（可选，用于读取AI配置）
            scenario: 覆盖场景名（用于加载专属 prompt）
            room_id: 房间 ID（用于 DB 日志）
            quarter_number: 季度编号（用于 DB 日志）

        Returns:
            (decision_text, parsed_commands)
                decision_text: 自然语言决策文本（用于叙事和记录）
                parsed_commands: 结构化命令列表
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            L = _NPC_LABELS.get(self.language, _NPC_LABELS["zh-CN"])
            return L["not_active"], []

        # Minor factions use heuristic rules
        faction_set = set(getattr(slot, "__dict__", {}))
        if faction_id not in LLM_NPC_FACTIONS and faction_id not in (slot.faction_id if slot else ""):
            pass  # 继续尝试 LLM 或 heuristic

        # Use LLM for major factions; fall back to heuristic for minor
        use_llm = self.llm_available and self.llm is not None

        if not use_llm:
            return self._generate_heuristic(world_state, faction_id)

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
            # LLM 失败时回退到启发式
            logger.warning(f"NPCDecisionEngine LLM failed for {faction_id}, falling back to heuristic: {e}")
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
        """LLM 生成决策。"""
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
            max_tokens=4096,
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

        decision = response.get("decision", "观望待机" if self.language == "zh-CN" else "Watching and waiting for the right moment.")
        raw_commands = response.get("commands", [])

        # 标准化命令
        commands = self._normalize_commands(raw_commands, faction_id)

        # Note: LLMAdapter already logs the call to llm_call_log via _log_to_db.
        # No separate log_llm_call needed here.

        return decision, commands

    def _generate_heuristic(
        self,
        ws: WorldState,
        faction_id: str,
    ) -> tuple[str, list]:
        """启发式规则生成决策（次要势力或LLM不可用时）。Language-aware via self.language."""
        faction = ws.factions.get(faction_id)
        if not faction:
            return "休整" if self.language == "zh-CN" else "Rest", []

        is_en = self.language == "en"
        commands: list[dict] = []
        decision_parts: list[str] = []

        # 1. 招募/Recruit：兵力不足时
        strength = getattr(faction, "strength_actual", 0)
        if strength < 10000 and faction.treasury > 2000:
            commands.append(
                {
                    "type": "conscript",
                    "params": {"amount": 3000},
                    "reasoning": "兵力薄弱，扩充军备以自保" if not is_en else "Troops weak, expanding military for self-defense",
                }
            )
            decision_parts.append("征兵三千" if not is_en else "Conscript 3,000")

        # 2. 发展/Develop：稳定期开发领地
        if faction.treasury > 5000 and faction.food > 3000:
            capital = faction.capital or (faction.territories[0] if faction.territories else None)
            if capital:
                commands.append(
                    {
                        "type": "develop",
                        "params": {"territory": capital},
                        "reasoning": "发展领地经济" if not is_en else f"Develop {capital} economy",
                    }
                )
                decision_parts.append(f"开发{capital}" if not is_en else f"Develop {capital}")

        # 3. 外交：与相邻势力保持和平
        neighbors = self._get_neighbors(ws, faction_id)
        for nid in neighbors:
            if nid in faction.relations and faction.relations[nid] > -50:
                continue
        # 不主动进攻

        default = "休整观望，静待时机。" if not is_en else "Resting and observing, awaiting the right moment."
        decision_text = "、".join(decision_parts) + "。" if decision_parts and not is_en else ", ".join(decision_parts) + "." if decision_parts and is_en else default
        return decision_text, commands

    def _build_context(
        self,
        ws: WorldState,
        faction_id: str,
        faction,
        turn_memory: list[dict],
    ) -> str:
        """Build LLM decision context (FOW-aware). Language-controlled via self.language."""
        L = _NPC_LABELS.get(self.language, _NPC_LABELS["zh-CN"])
        lines: list[str] = []

        # Time
        season_cn = getattr(ws, "current_season_cn", str(getattr(ws, "season_index", "?")))
        turn = getattr(ws, "turn", 0)
        lines.append(f"## {L['current_time']}\n{ws.year}, {season_cn} | {L['quarter']} {turn}\n")

        # Own state
        lines.append(f"## {L['your_faction']}")
        lines.append(f"{L['faction']}: {faction.name} ({faction_id})")
        lines.append(f"{L['ruler']}: {getattr(faction, 'ruler_id', '')}")
        lines.append(f"{L['troops']}: {getattr(faction, 'strength_actual', 0):,}")
        lines.append(f"{L['funds']}: {getattr(faction, 'treasury', 0):,} | {L['food']}: {getattr(faction, 'food', 0):,}")
        lines.append(f"{L['morale']}: {getattr(faction, 'morale_actual', 50)} | {L['tax_rate']}: {int(getattr(faction, 'tax_rate', 0.3) * 100)}%")
        territories = list(getattr(faction, 'territories', []))
        lines.append(f"{L['territories']}: {territories}")
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

        # Historical memory
        if turn_memory:
            lines.append(f"## {L['recent_events']}")
            last_attack_target = None
            for mem in turn_memory[-5:]:
                summary = mem.get("outcome_summary", "")
                if summary:
                    lines.append(f"- {summary}")
                    # 检测上一回合是否有本势力的进攻
                    arrow = f"{faction_id}→"
                    if arrow in summary and "attack" in str(mem.get("quarter", "")) or arrow in summary:
                        # Extract target from "antony→roma" pattern
                        import re
                        m = re.search(rf"{re.escape(faction_id)}→(\w+)", summary)
                        if m:
                            last_attack_target = m.group(1)
            lines.append("")

            # 如果检测到上一回合本势力发动了进攻，添加策略提醒
            if last_attack_target:
                lines.append(f"## {L['strategic_reminder']}")
                lines.append(L['failed_attack'].format(target=last_attack_target))
                lines.append("")

        # Instructions
        lines.append(f"## {L['make_decision']}")
        lines.append(L["decision_instruction"])
        lines.append(L["json_output"])

        return "\n".join(lines)

    def _normalize_commands(self, raw: list, faction_id: str) -> list[dict]:
        """标准化 LLM 输出的命令格式。"""
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
        """获取相邻势力列表。"""
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
        """从文本中提取 JSON。"""
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
