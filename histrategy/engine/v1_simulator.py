"""
V1 纯 LLM 仿真引擎 — deepseek-v4-pro 直接推演世界状态。

V1 不做任何确定性计算，所有状态变化由单次 LLM 调用完成。
输入：所有势力状态 + 全部指令
输出：新状态 + 叙事 + 事件

Usage:
    engine = V1Simulator(llm)
    result = engine.simulate(world_state, faction_decisions, turn_memory)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

logger = logging.getLogger("histrategy.v1")

# ── Prompt cache ─────────────────────────────────────────────
_PROMPT_DIR = Path(__file__).parent.parent / "llm" / "prompts"
_DEFAULT_SYSTEM_PROMPT = (_PROMPT_DIR / "v1_simulator.md").read_text(encoding="utf-8")
_PROMPT_CACHE: dict[str, str] = {}  # scenario → prompt


def _load_simulator_prompt(scenario: str | None, lang: str = "zh") -> str:
    """Load scenario-specific simulator prompt with fallback to default.

    Args:
        scenario: Scenario ID (e.g. 'three-kingdoms', 'rome-triumvirate')
        lang: Language preference ('zh' or 'en')
    """
    cache_key = f"{scenario}:{lang}"

    # Default (three-kingdoms) handled below with language
    if scenario in _PROMPT_CACHE and not scenario:
        return _PROMPT_CACHE[scenario]

    if cache_key in _PROMPT_CACHE:
        return _PROMPT_CACHE[cache_key]

    # Try scenario-specific prompts in language-preference order
    candidates = []
    if scenario and scenario not in ("three-kingdoms", ""):
        if lang == "en":
            candidates = [
                Path(f"scenarios/{scenario}/prompts/v1_simulator_en.md"),
                Path(f"scenarios/{scenario}/prompts/v1_simulator.md"),
            ]
        else:
            candidates = [
                Path(f"scenarios/{scenario}/prompts/v1_simulator_zh.md"),
                Path(f"scenarios/{scenario}/prompts/v1_simulator.md"),
                Path(f"scenarios/{scenario}/prompts/v1_simulator_en.md"),
            ]
    else:
        # three-kingdoms: use language-specific default
        if lang == "en":
            candidates = [
                _PROMPT_DIR / "v1_simulator_en.md",
            ]

    for p in candidates:
        if p.is_file():
            _PROMPT_CACHE[cache_key] = p.read_text(encoding="utf-8")
            return _PROMPT_CACHE[cache_key]

    # Final fallback: default Chinese prompt
    _PROMPT_CACHE[cache_key] = _DEFAULT_SYSTEM_PROMPT
    return _DEFAULT_SYSTEM_PROMPT



# ── Historical timeline reference (nanming) ──────────────────

_NANMING_TIMELINE_ZH = {
    1: """## 历史时间线（仅供参考，不强制遵循）
- 1645年春：清摄政王多尔衮命多铎为定国大将军，率八旗精兵南下
- 清军主攻方向：山东→徐州→扬州→南京（由北向南，沿运河南下）
- 扬州是南京门户，史可法督师坚守。扬州在长江以北，南京在长江以南
- 郑氏据福建广东，与清控区不相邻（中间隔着南明的浙江、江西）
- 清军无水师，短期内无法直接威胁福建沿海""",
    2: """## 历史时间线（仅供参考）
- 1645年夏：多铎攻破扬州，史可法殉国。清军渡江在即
- 南京朝廷震动，弘光帝考虑南逃
- 郑氏水师可沿长江北上支援南京防御""",
    3: """## 历史时间线（仅供参考）
- 1645年秋：清军攻陷南京，弘光帝被俘。南明朝廷瓦解
- 唐王朱聿键在福州即位（隆武），郑芝龙成为实际掌权者
- 清军推行剃发令，激起江南士民激烈反抗""",
    4: """## 历史时间线（仅供参考）
- 1645年冬—1646年：清军继续南下，进入浙江、江西
- 郑芝龙与清军秘密谈判，郑成功力主抗清
- 福建开始面临清军直接威胁""",
}

_NANMING_TIMELINE_EN = {
    1: "## Historical Timeline (reference only)\n"
       "- Spring 1645: Dorgon orders Dodo south with the Eight Banners.\n"
       "- Qing main thrust: Shandong → Xuzhou → Yangzhou → Nanjing (canal route).\n"
       "- Yangzhou is Nanjing's northern gate; Shi Kefa holds the defense.\n"
       "- Zheng controls Fujian/Guangdong, not bordering Qing territory.\n"
       "- Qing has no navy — cannot directly threaten the Fujian coast.",
    2: "## Historical Timeline (reference only)\n"
       "- Summer 1645: Yangzhou falls, Shi Kefa dies. Qing forces prepare to cross the Yangtze.\n"
       "- The Nanjing court panics; Hongguang Emperor considers fleeing south.\n"
       "- Zheng's navy could sail up the Yangtze to reinforce Nanjing's defense.",
    3: "## Historical Timeline (reference only)\n"
       "- Autumn 1645: Nanjing falls, Hongguang Emperor captured. Southern Ming court collapses.\n"
       "- Prince Tang enthroned in Fuzhou (Longwu era); Zheng Zhilong becomes de facto ruler.\n"
       "- Qing enforces the queue order; Jiangnan erupts in resistance.",
    4: "## Historical Timeline (reference only)\n"
       "- Winter 1645-1646: Qing forces advance into Zhejiang and Jiangxi.\n"
       "- Zheng Zhilong negotiates secretly with Qing; Zheng Chenggong urges resistance.\n"
       "- Fujian faces direct Qing threat for the first time.",
}

def _add_historical_timeline(parts: list, turn: int, lang: str = "zh") -> None:
    """Append historical timeline reference for nanming early turns."""
    if lang == "en":
        timeline = _NANMING_TIMELINE_EN.get(turn, "")
    else:
        timeline = _NANMING_TIMELINE_ZH.get(turn, "")
    if timeline:
        parts.append(timeline)

# ── Bilingual labels for _build_context ────────────────────
_LABELS = {
    "zh": {
        "world_state": "当前世界状态",
        "cities": "城池",
        "no_territory": "无领地",
        "population": "人口",
        "troops": "兵力",
        "food": "粮草",
        "treasury": "库金",
        "morale": "民心",
        "tax_rate": "税率",
        "policies": "政策",
        "decisions": "本季度决策",
        "decision": "决策",
        "structured_commands": "结构化命令",
        "history": "历史摘要",
        "diplomacy": "当前外交与特殊状态",
    },
    "en": {
        "world_state": "Current World State",
        "cities": "Territories",
        "no_territory": "No territory",
        "population": "Population",
        "troops": "Troops",
        "food": "Food",
        "treasury": "Treasury",
        "morale": "Morale",
        "tax_rate": "Tax Rate",
        "policies": "Policies",
        "decisions": "This Quarter's Decisions",
        "decision": "Decision",
        "structured_commands": "Structured Commands",
        "history": "Historical Summary",
        "diplomacy": "Current Diplomacy & Special Status",
    },
}


def _get_faction_display_name(faction, lang: str = "zh") -> str:
    """Return the faction's display name in the requested language.

    Falls back to faction.name (Chinese) if name_en is not available.
    """
    if lang == "en" and getattr(faction, "name_en", ""):
        return faction.name_en
    return faction.name


def _build_context(
    ws: WorldState,
    faction_decisions: dict[str, dict],
    turn_memory: list[dict],
    lang: str = "zh",
) -> str:
    """Build V1 simulation context.

    Packs world state and all faction decisions into LLM-readable text.
    No fog of war — all information is public.
    """
    L = _LABELS.get(lang, _LABELS["zh"])
    parts: list[str] = []

    # 1. Current world state
    parts.append(f"## {L['world_state']}\n")
    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        territories_str = (
            "、".join([f"{ws.territories[tid].name}({tid})" for tid in faction.territories if tid in ws.territories])
            or L["no_territory"]
        )
        # Compute total population from territories (H15e fix: FactionState has no population field)
        computed_population = getattr(faction, "population", 0)
        if not computed_population:
            computed_population = sum(
                ws.territories[tid].population for tid in faction.territories if tid in ws.territories
            )
        display_name = _get_faction_display_name(faction, lang)
        parts.append(
            f"### {display_name} ({fid})\n"
            f"- {L['cities']}: {territories_str}\n"
            f"- {L['population']}: {computed_population}\n"
            f"- {L['troops']}: {getattr(faction, 'strength_actual', 0)}\n"
            f"- {L['food']}: {faction.food}\n"
            f"- {L['treasury']}: {faction.treasury}\n"
            f"- {L['morale']}: {getattr(faction, 'morale_actual', 50)}\n"
            f"- {L['tax_rate']}: {int(getattr(faction, 'tax_rate', 0.3) * 100)}%\n"
        )
        # Current active policies
        policies = getattr(faction, "policies", {})
        if policies:
            policy_lines = [f"- {L['policies']}: {json.dumps(policies, ensure_ascii=False)}"]
            parts.append("\n".join(policy_lines))

    # 2. Faction decisions
    parts.append(f"\n## {L['decisions']}\n")
    for fid, decision_info in faction_decisions.items():
        faction = ws.factions.get(fid)
        name = _get_faction_display_name(faction, lang) if faction else fid
        decision_text = decision_info.get("decision", "") if isinstance(decision_info, dict) else str(decision_info)
        commands = decision_info.get("commands", []) if isinstance(decision_info, dict) else []

        parts.append(f"### {name} ({fid})\n{L['decision']}: {decision_text}")
        if commands:
            parts.append(f"{L['structured_commands']}: " + json.dumps(commands, ensure_ascii=False))

    # 3. Turn memory (recent round summaries)
    if turn_memory:
        parts.append(f"\n## {L['history']}\n")
        for i, summary in enumerate(turn_memory[-4:]):
            parts.append(f"Q{summary.get('quarter', i + 1)}: {json.dumps(summary, ensure_ascii=False)}")

    # 4. Diplomatic/special status detection
    diplomatic_notes = _build_diplomatic_context(ws, lang)
    if diplomatic_notes:
        parts.append(f"\n## {L['diplomacy']}\n")
        parts.append(diplomatic_notes)

    # 5. Historical timeline reference (nanming only, early turns)
    scenario = getattr(ws, "scenario", "")
    turn = getattr(ws, "turn_number", 1) or 1
    if scenario == "nanming" and turn <= 4:
        _add_historical_timeline(parts, turn, lang)

    return "\n".join(parts)


# ── Bilingual diplomatic labels ─────────────────────────────
_DIP_LABELS = {
    "zh": {
        "destroyed": "已灭亡",
        "lost_territory": "已失去所有领地，目前依附于",
        "exile": "已失去所有领地，流亡状态（兵力",
        "vassal": "实力远逊于",
        "de_facto_vassal": "），实质附庸",
        "troops_vs": "兵力",
        "vs": "vs",
        "allies_header": "🤝 当前盟友关系",
        "ally_with": "与",
        "ally": "结盟",
        "no_allies": "无盟友",
    },
    "en": {
        "destroyed": "DESTROYED",
        "lost_territory": "Lost all territories, now a client of",
        "exile": "Lost all territories, in exile (troops:",
        "vassal": "Far weaker than",
        "de_facto_vassal": "), de facto vassal",
        "troops_vs": "Troops",
        "vs": "vs",
        "allies_header": "🤝 Current Alliances",
        "ally_with": "allied with",
        "ally": "alliance",
        "no_allies": "No alliances",
    },
}


def _build_diplomatic_context(ws: WorldState, lang: str = "zh") -> str:
    """Detect diplomatic/special status and generate structured context for V1 prompt.

    Detection rules (deterministic, not LLM-dependent):
    - Faction territories=0 and is_active=True -> surrendered/vassal (infer overlord)
    - Faction is_active=False -> destroyed
    - Also includes explicit ally relationships from WorldState
    """
    L = _DIP_LABELS.get(lang, _DIP_LABELS["zh"])
    lines: list[str] = []

    # ── Allies section ──
    lines.append(f"{L['allies_header']}:")
    any_allies = False
    for _fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        allies = getattr(faction, "allies", []) or []
        if allies:
            any_allies = True
            ally_names = []
            for aid in allies:
                ally_f = ws.factions.get(aid)
                ally_names.append(_get_faction_display_name(ally_f, lang) if ally_f else aid)
            lines.append(f"- {_get_faction_display_name(faction, lang)} {L['ally_with']} " + "、".join(ally_names))
    if not any_allies:
        lines.append(f"- {L['no_allies']}")
    lines.append(
        "\n**重要约束**: 盟友之间各自保留独立兵力。"
        "盟友的部队绝不可合并——各势力兵力独立计算，"
        "即使共同作战也只是配合作战，兵力分开管理。"
    )

    # ── Status section ──
    for fid, faction in ws.factions.items():
        if not faction.is_active:
            lines.append(f"- {_get_faction_display_name(faction, lang)} ({fid}): 💀 {L['destroyed']}")
            continue
        has_territory = bool(getattr(faction, "territories", []))
        troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
        govt = getattr(faction, "government", "")
        if not has_territory:
            # Only mark as "client of X" if faction is explicitly a vassal/client/ally of someone
            # Otherwise just mark as exile — they're an independent force without land
            found_overlord = False
            allies = getattr(faction, "allies", []) or []
            if "client" in str(govt).lower() or "vassal" in str(govt).lower():
                for other_fid, other_f in ws.factions.items():
                    if other_fid == fid:
                        continue
                    if getattr(other_f, "territories", []):
                        lines.append(f"- {_get_faction_display_name(faction, lang)} ({fid}): ⚠️ {L['lost_territory']} {_get_faction_display_name(other_f, lang)}")
                        found_overlord = True
                        break
            if not found_overlord:
                lines.append(f"- {_get_faction_display_name(faction, lang)} ({fid}): ⚠️ {L['exile']} {troops})")
        # Detect extreme power imbalance (likely de facto vassal)
        elif troops < 1000:
            for other_fid, other_f in ws.factions.items():
                if other_fid == fid:
                    continue
                other_troops = getattr(other_f, "strength_actual", 0) or getattr(other_f, "strength", 0) or 0
                if other_troops > troops * 10 and getattr(other_f, "territories", []):
                    lines.append(
                        f"- {_get_faction_display_name(faction, lang)} ({fid}): {L['vassal']} {_get_faction_display_name(other_f, lang)} "
                        f"({L['troops_vs']} {troops} {L['vs']} {other_troops}{L['de_facto_vassal']}"
                    )
                    break
    return "\n".join(lines) if lines else ""


class V1Simulator:
    """V1 纯 LLM 仿真引擎。

    与 V3 的混合引擎不同，V1 不做任何确定性计算。
    世界状态完全由 LLM 推理生成。
    """

    def __init__(self, llm: LLMAdapter | None = None):
        self.llm = llm
        self._available = llm is not None and llm.is_available

    @property
    def is_available(self) -> bool:
        return self._available

    def simulate(
        self,
        ws: WorldState,
        faction_decisions: dict[str, dict],
        turn_memory: list[dict] | None = None,
        room_id: str = "",
        quarter_number: int = 0,
        scenario: str | None = None,
        lang: str = "zh",
    ) -> dict:
        """Execute V1 simulation — single LLM call handles all state evolution.

        Args:
            ws: Current world state
            faction_decisions: {faction_id: {decision: str, commands: list}}
            turn_memory: Turn memory (recent round summaries)
            room_id: Game room ID for DB logging
            quarter_number: Current quarter for DB logging
            scenario: Scenario ID for loading scenario-specific prompt
            lang: Language ('zh' or 'en') for prompt selection

        Returns:
            {
                "narrative": str,
                "factions": dict,
                "events": list[str],
                "battles": list[dict],
                "diplomacy": list[dict],
                "knowledge_cards": list[dict],
                "token_usage": dict,
            }
        """
        if not self.is_available:
            return self._fallback(ws, faction_decisions, lang)

        context = _build_context(ws, faction_decisions, turn_memory or [], lang=lang)
        system_prompt = _load_simulator_prompt(scenario, lang)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        try:
            response = self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=32768,
                metadata={
                    "category": "v1_simulate",
                    "room_id": room_id,
                    "quarter_number": quarter_number,
                },
            )
            result = self._parse_response(response)
            # If JSON parsing failed (V1 解析失败), use heuristic fallback
            # instead of returning empty factions with zero stats
            if not result.get("factions") and "V1 解析失败" in str(result.get("narrative", "")):
                logger.warning(
                    f"V1 parse failed (len={len(response)}), falling back to heuristic. "
                    f"Raw response prefix: {response[:200]}"
                )
                result = self._fallback(ws, faction_decisions, lang=lang, reason="error")
                # Preserve token usage from the failed attempt
                result["token_usage"] = {
                    "prompt_tokens": len(context) // 3,
                    "completion_tokens": len(response) // 3,
                    "total_tokens": (len(context) + len(response)) // 3,
                }
            else:
                result["token_usage"] = {
                    "prompt_tokens": len(context) // 3,  # rough estimate
                    "completion_tokens": len(response) // 3,
                    "total_tokens": (len(context) + len(response)) // 3,
                }

            # ── Log simulation events to DB (H14b) ──
            if room_id:
                self._log_sim_events_to_db(room_id, quarter_number, result)

            return result
        except Exception as e:
            logger.error(f"V1 simulation failed: {e}")
            return self._fallback(ws, faction_decisions, lang=lang, reason="error")

    @staticmethod
    def _log_sim_events_to_db(room_id: str, quarter_number: int, result: dict) -> None:
        """Log simulation events (battles, diplomacy, events) to the DB."""
        try:
            from histrategy.db.models import log_sim_event

            # Log events (black swans, natural disasters, etc.)
            for event_text in result.get("events", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="black_swan"
                    if "灾" in event_text or "祸" in event_text or "变" in event_text
                    else "state_mutation",
                    event_data={"description": event_text},
                )

            # Log battles
            for battle in result.get("battles", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="baseline",
                    event_data={"type": "battle", "info": battle},
                )

            # Log diplomacy
            for dip in result.get("diplomacy", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="baseline",
                    event_data={"type": "diplomacy", "info": dip},
                )
        except Exception as e:
            logger.warning(f"Failed to log sim events to DB: {e}")

    def _parse_response(self, response: str) -> dict:
        """解析 LLM 输出的 JSON，带 json_repair 回退。"""
        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        text = response.strip()

        # 去掉 ```json ... ``` 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取第一个完整的 JSON 对象（brace counting）
        brace_start = text.find("{")
        brace_count = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                brace_count += 1
            elif text[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    extracted = text[brace_start : i + 1]
                    try:
                        return json.loads(extracted)
                    except json.JSONDecodeError:
                        break

        # json_repair 回退 — 修复 LLM 输出的格式偏差（缺失引号、尾部逗号等）
        try:
            from json_repair import repair_json

            repaired = repair_json(text)
            return json.loads(repaired)
        except Exception:
            pass

        logger.warning(f"V1: failed to parse LLM response (len={len(response)}), using fallback")
        return {
            "narrative": "V1 解析失败",
            "factions": {},
            "events": [],
            "battles": [],
            "diplomacy": [],
            "knowledge_cards": [],
        }

    def _fallback(self, ws: WorldState, faction_decisions: dict, lang: str = "zh", reason: str = "unavailable") -> dict:
        """Fallback when V1 LLM is unavailable, timed out, or errored.

        Args:
            reason: 'unavailable' (no API key), 'timeout' (LLM too slow), 'error' (LLM threw)
        """
        factions = {}
        for fid, faction in ws.factions.items():
            if not faction.is_active:
                continue
            troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
            morale = getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50
            factions[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": troops,
                "food": faction.food,
                "treasury": faction.treasury,
                "morale": morale,
                "territories": [
                    {"id": tid, "name": ws.territories[tid].name if tid in ws.territories else tid}
                    for tid in faction.territories
                ],
                "policies": {},
                "is_active": True,
            }
        if reason == "timeout":
            narrative = (
                "AI response timed out — the server is busy. "
                "Your orders have been saved. Please submit again."
                if lang == "en"
                else "AI 响应超时，服务器繁忙。你的指令已保存，请重新提交。"
            )
        elif reason == "error":
            narrative = (
                "AI encountered an error. "
                "Your orders have been saved. Please try again."
                if lang == "en"
                else "AI 处理出错，你的指令已保存，请重试。"
            )
        else:
            narrative = (
                "(Offline mode: LLM unavailable, state unchanged)"
                if lang == "en"
                else "（离线模式：无 LLM 可用，状态未变化）"
            )
        return {
            "narrative": narrative,
            "factions": factions,
            "events": [],
            "battles": [],
            "diplomacy": [],
            "knowledge_cards": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


# ── V1 状态写入 DB ──────────────────────────────────


def _normalize_territory_ids(
    territory_ids: list[str],
    available_ids: set[str],
    territory_name_map: dict[str, str],
) -> list[str]:
    """将 LLM 生成的领地名称标准化为规范 ID。

    LLM 经常输出变体名称（如 cisalpina、rome、narbonese_gaul），
    需要映射回 territories.json 中定义的规范 ID。

    使用三层策略：
    1. 精确匹配 — 直接命中规范 ID
    2. 名称映射 — 通过预构建的变体表匹配
    3. 模糊匹配 — lowercase 子串匹配（最后的兜底）
    """

    normalized = []
    for tid in territory_ids:
        # 已是 dict（{id, name} 格式）→ 提取 id
        if isinstance(tid, dict):
            raw = tid.get("id", "")
            if raw:
                tid = raw
            else:
                continue

        if not isinstance(tid, str) or not tid.strip():
            continue

        clean = tid.strip().lower().replace(" ", "_").replace("-", "_")

        # 1. 精确匹配
        if clean in available_ids:
            normalized.append(clean)
            continue

        # 2. 名称映射（变体 → 规范）
        if clean in territory_name_map:
            normalized.append(territory_name_map[clean])
            continue

        # 3. 模糊匹配 — 直接在 available_ids 中找最匹配的
        best_match = None
        best_score = 0
        for canonical in available_ids:
            # 子串包含
            if clean in canonical or canonical in clean:
                score = min(len(clean), len(canonical)) / max(len(clean), len(canonical))
                if score > best_score:
                    best_match = canonical
                    best_score = score

        if best_match and best_score >= 0.5:
            logger.debug(
                f"Territory fuzzy match: '{tid}' → '{best_match}' "
                f"(score={best_score:.2f})"
            )
            normalized.append(best_match)
        else:
            # 无法匹配 — 保留原值并警告
            logger.warning(
                f"Territory name '{tid}' not recognized in available IDs. "
                f"Available: {sorted(available_ids)}"
            )
            normalized.append(clean)

    return normalized


def _build_territory_name_map(scenario: str) -> tuple[set[str], dict[str, str]]:
    """从场景知识库构建领地名称映射表。

    Returns:
        (available_ids, name_map)
        - available_ids: 所有规范 ID 的集合
        - name_map: 变体名 → 规范 ID 的映射
    """
    import json as _json
    from pathlib import Path as _Path

    available_ids: set[str] = set()
    name_map: dict[str, str] = {}

    candidates = [
        _Path(f"scenarios/{scenario}/knowledge/territories.json"),
        _Path(f"scenarios/{scenario}/territories.json"),
    ]

    for p in candidates:
        if not p.exists():
            continue
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        if isinstance(data, list):
            for t in data:
                if not isinstance(t, dict):
                    continue
                tid = t.get("id", "")
                if not tid:
                    continue
                available_ids.add(tid)

                # 添加英文名映射
                en = t.get("name_en", "")
                if en:
                    key = en.strip().lower().replace(" ", "_").replace("-", "_")
                    name_map[key] = tid

                # 添加中文名映射
                cn = t.get("name", "")
                if cn:
                    key = cn.strip().lower()
                    # 移除常见后缀
                    for suffix in ["行省", "省", "地区", "区域"]:
                        if key.endswith(suffix):
                            key = key[:-len(suffix)]
                    name_map[key] = tid

                # 添加常见 LLM 变体（从英文名推导）
                if en:
                    parts = en.strip().lower().split()
                    # 如 "Cisalpine Gaul" → cisalpine
                    if len(parts) >= 2:
                        name_map[parts[0]] = tid
                    # 如 "Hispania Citerior" → hispania
                    for part in parts:
                        if len(part) > 3:
                            name_map[part] = tid
        break

    # 罗马场景专用：LLM 常见变体映射
    _rome_variants = {
        "rome": "roma",
        "roma": "roma",
        "cisalpine": "cisalpine_gaul",
        "cisalpina": "cisalpine_gaul",
        "narbonensis": "narbonensis",
        "narbonese_gaul": "narbonensis",
        "narbonese": "narbonensis",
        "narbonne": "narbonensis",
        "hispania": "hispania_citerior",
        "transalpine": "transalpine_gaul",
        "sicily": "sicilia",
        "egypt": "aegyptus",
        "aegypt": "aegyptus",
        "illyricum": "illyria",
        "italy": "italia",
        "greece": "graecia",
        "macedon": "macedonia",
        "mesopotamia": "mesopotamia",
        "cyrene": "cyrenaica",
        "cyprus": "cyprus",
        "sardinia": "sardinia",
        "africa": "africa",
        "syria": "syria",
        "asia": "asia",
        "senate": None,  # 非领地，忽略
    }
    for variant, canonical in _rome_variants.items():
        if canonical is None:
            name_map.pop(variant, None)
        elif variant not in name_map and canonical in available_ids:
            name_map[variant] = canonical

    return available_ids, name_map


def _apply_v1_state_to_world(ws: WorldState, v1_factions: dict) -> WorldState:
    """将 V1 输出的状态写回 WorldState。

    V1 输出的是 JSON dict，需要小心地映射回 WorldState 对象。
    只更新数值字段，不改变结构。

    边界守卫: 兵力单季度变化不超过 ±30%（与 v1_simulator.md 提示词一致）。
    超过边界时 clamp 并记录警告。
    """
    _MAX_TROOP_CHANGE_RATIO = 0.30

    # ── 领地名称标准化准备 ──
    available_territory_ids = set(ws.territories.keys()) if hasattr(ws, "territories") else set()
    scenario = getattr(ws, "scenario", "") or ""
    if scenario:
        _scenario_ids, _scenario_map = _build_territory_name_map(scenario)
        if _scenario_ids:
            available_territory_ids = _scenario_ids
    else:
        _scenario_map = {}

    for fid, data in v1_factions.items():
        if fid not in ws.factions:
            continue
        faction = ws.factions[fid]

        # 数值更新 — 兼容两个 WorldState 版本的字段名
        if "population" in data and hasattr(faction, "population"):
            faction.population = data["population"]
        if "troops" in data:
            new_troops = int(data["troops"])
            old_troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
            # ── 边界守卫: clamp ±30% except for the very first turn (Q0→Q1) ──
            if old_troops > 0 and new_troops != old_troops:
                ratio = abs(new_troops - old_troops) / old_troops
                if ratio > _MAX_TROOP_CHANGE_RATIO:
                    if new_troops > old_troops:
                        clamped = int(old_troops * (1 + _MAX_TROOP_CHANGE_RATIO))
                    else:
                        clamped = int(old_troops * (1 - _MAX_TROOP_CHANGE_RATIO))
                    logger.warning(
                        f"V1 guardrail: {faction.name} ({fid}) troops "
                        f"{old_troops}→{new_troops} "
                        f"({ratio:.0%} change) exceeds ±{_MAX_TROOP_CHANGE_RATIO:.0%}, "
                        f"clamping to {clamped}"
                    )
                    new_troops = clamped
            # V2 engine uses strength_actual, V1 legacy uses strength
            if hasattr(faction, "strength_actual"):
                faction.strength_actual = new_troops
            elif hasattr(faction, "strength"):
                faction.strength = new_troops
        if "food" in data:
            faction.food = data["food"]
        if "treasury" in data:
            faction.treasury = data["treasury"]
        if "morale" in data:
            if hasattr(faction, "morale_actual"):
                faction.morale_actual = data["morale"]
            elif hasattr(faction, "morale"):
                faction.morale = data["morale"]
        if "navy" in data:
            if hasattr(faction, "navy"):
                faction.navy = int(data["navy"])
            elif hasattr(faction, "naval_strength"):
                faction.naval_strength = int(data["navy"])
        if "policies" in data:
            faction.policies = data["policies"]
        if "is_active" in data:
            faction.is_active = data["is_active"]

        # 城池易手
        if "territories" in data:
            raw_territory_ids = [t["id"] if isinstance(t, dict) else t for t in data["territories"]]
            # 标准化领地名称（LLM 输出变体 → 规范 ID）
            new_territory_ids = _normalize_territory_ids(
                raw_territory_ids, available_territory_ids, _scenario_map
            )
            # 城池易手：新占城池从原所有者移除，并同步 territory.owner_id
            lost_ids = set(faction.territories) - set(new_territory_ids)
            for tid in new_territory_ids:
                if tid not in faction.territories:
                    # 从原所有者移除
                    for other_fid, other_f in ws.factions.items():
                        if other_fid != fid and tid in other_f.territories:
                            other_f.territories.remove(tid)
                # 同步 territory.owner_id（V1 prompt 不保证此字段正确）
                if hasattr(ws, "territories") and tid in ws.territories:
                    ws.territories[tid].owner_id = fid
            # 失去的城池清除 owner_id
            for tid in lost_ids:
                if hasattr(ws, "territories") and tid in ws.territories:
                    ws.territories[tid].owner_id = ""
            faction.territories = new_territory_ids

    return ws


def save_v1_state_to_db(
    room_id: str,
    quarter_number: int,
    ws: WorldState,
    v1_result: dict,
    old_state: dict | None = None,
):
    """将 V1 仿真结果写入数据库（game_state + turn_delta + policy_state）。

    Args:
        old_state: 仿真前的状态快照 {fid: {population, troops, food, treasury, morale}}
                   用于计算 turn_delta。若为 None 则跳过 delta 写入。
    """
    from histrategy.db.models import save_game_state, save_policy_state, save_turn_delta

    v1_factions = v1_result.get("factions", {})
    # Input validation: LLM may return factions as a list
    if isinstance(v1_factions, list):
        logger.warning(f"V1 DB save: factions is a list, not dict. Converting. room={room_id}")
        # Try to convert list of {id, ...} dicts to {id: data} dict
        _fixed = {}
        for item in v1_factions:
            if isinstance(item, dict) and "id" in item:
                _fixed[item["id"]] = item
        v1_factions = _fixed

    if not v1_factions or not isinstance(v1_factions, dict):
        # V1 prompt may use "state_changes" instead of "factions"
        # (e.g. rome-triumvirate prompt). Fall back to WorldState data.
        logger.info(f"V1 DB save: no factions in LLM output, building from WorldState. room={room_id}")
        v1_factions = {}
        for fid, faction in ws.factions.items():
            if not faction.is_active:
                continue
            troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
            morale = getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50
            v1_factions[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": troops,
                "food": faction.food,
                "treasury": faction.treasury,
                "morale": morale,
                "territories": [
                    {"id": tid, "name": ws.territories[tid].name if tid in ws.territories else tid}
                    for tid in faction.territories
                ],
                "policies": getattr(faction, "policies", {}),
                "is_active": True,
            }

    success_count = 0
    error_count = 0
    for fid, data in v1_factions.items():
        try:
            # Skip factions not present in the actual WorldState (regardless of scenario)
            faction = ws.factions.get(fid)
            if not faction:
                logger.debug(f"V1 DB save: skipping unknown faction '{fid}' (not in WorldState). room={room_id}")
                continue

            # Coerce numeric fields (LLM may return strings or non-numeric values)
            def _safe_int(val, default=0):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default

            def _safe_float(val, default=0.0):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            # ── 保存完整状态快照 (game_state) ──
            save_game_state(
                room_id=room_id,
                quarter_number=quarter_number,
                faction_id=fid,
                population=_safe_int(data.get("population", 0)),
                troops=_safe_int(data.get("troops", 0)),
                food=_safe_float(data.get("food", 0)),
                treasury=_safe_float(data.get("treasury", 0)),
                morale=_safe_int(data.get("morale", 50)),
                territories=data.get("territories", []) if isinstance(data.get("territories"), list) else [],
                policies=data.get("policies", {}) if isinstance(data.get("policies"), dict) else {},
                is_active=bool(data.get("is_active", True)),
            )

            # ── 保存五项增量 (turn_delta) ──
            if old_state and fid in old_state:
                try:
                    old = old_state[fid]
                    delta_map = [
                        ("population", _safe_int(old.get("population", 0)), _safe_int(data.get("population", 0))),
                        ("troops", _safe_int(old.get("troops", 0)), _safe_int(data.get("troops", 0))),
                        ("food", _safe_float(old.get("food", 0)), _safe_float(data.get("food", 0))),
                        ("treasury", _safe_float(old.get("treasury", 0)), _safe_float(data.get("treasury", 0))),
                        ("morale", _safe_int(old.get("morale", 50)), _safe_int(data.get("morale", 50))),
                    ]
                    for delta_type, old_val, new_val in delta_map:
                        if old_val == new_val:
                            continue
                        save_turn_delta(
                            room_id=room_id,
                            quarter_number=quarter_number,
                            faction_id=fid,
                            delta_type=delta_type,
                            old_value=old_val,
                            new_value=new_val,
                            reason="V1 LLM simulation",
                            source="llm",
                        )
                except Exception as delta_err:
                    logger.warning(f"V1 DB save: turn_delta failed for {fid}: {delta_err}", exc_info=True)

            # ── 保存政策变更 (policy_state) ──
            policies = data.get("policies", {})
            if policies and isinstance(policies, dict):
                for policy_name, policy_info in policies.items():
                    try:
                        if isinstance(policy_info, dict):
                            save_policy_state(
                                room_id=room_id,
                                quarter_number=quarter_number,
                                faction_id=fid,
                                policy_type=policy_info.get("type", "law"),
                                policy_name=policy_name,
                                policy_level=policy_info.get("level", 1),
                                params=policy_info.get("params", {}),
                                status=policy_info.get("status", "active"),
                            )
                    except Exception as policy_err:
                        logger.warning(
                            f"V1 DB save: policy_state failed for {fid}/{policy_name}: {policy_err}", exc_info=True
                        )

            success_count += 1
        except Exception as faction_err:
            error_count += 1
            logger.warning(f"V1 DB save failed for faction '{fid}': {faction_err}", exc_info=True)

    if error_count > 0:
        logger.warning(
            f"V1 DB save: {success_count} factions saved, {error_count} failed. room={room_id} q={quarter_number}"
        )
    elif success_count > 0:
        logger.info(
            f"V1 DB save: {success_count} factions saved successfully. "
            f"room={room_id} q={quarter_number}"
        )


# ─── Territory Change Detection ────────────────────────────────────


def detect_territory_changes(
    old_state: dict,
    v1_factions: dict,
    ws: "WorldState",
    narrative: str,
) -> str:
    """Detect territory changes and append missing narrative explanations.

    When the LLM changes territory ownership without mentioning it in the
    narrative, we detect the change and append a concise annotation.
    This fixes the \"silent territory loss\" bug where cities change hands
    without any narrative explanation.

    Args:
        old_state: Pre-simulation faction state {fid: {territories: [...]}}
        v1_factions: LLM output factions dict
        ws: WorldState (post-application, for territory names)
        narrative: The existing global narrative string

    Returns:
        Enhanced narrative with territory change annotations appended.
    """
    # Gather gains and losses grouped by faction
    gains_by_faction: dict[str, list[str]] = {}
    losses_by_faction: dict[str, list[str]] = {}

    for fid, data in v1_factions.items():
        faction = ws.factions.get(fid)
        if not faction:
            continue

        old_territories = set(old_state.get(fid, {}).get("territories", []))
        new_territories_raw = data.get("territories", [])
        new_territories = set(
            t["id"] if isinstance(t, dict) else t for t in new_territories_raw
        )

        gained = new_territories - old_territories
        lost = old_territories - new_territories

        faction_name = getattr(faction, "name", fid) or fid

        for tid in gained:
            tname = (
                ws.territories[tid].name
                if hasattr(ws, "territories") and tid in ws.territories
                else tid
            )
            if tname not in narrative and tid not in narrative:
                gains_by_faction.setdefault(faction_name, []).append(tname)

        for tid in lost:
            tname = (
                ws.territories[tid].name
                if hasattr(ws, "territories") and tid in ws.territories
                else tid
            )
            if tname not in narrative and tid not in narrative:
                losses_by_faction.setdefault(faction_name, []).append(tname)

    if gains_by_faction or losses_by_faction:
        total = sum(len(v) for v in gains_by_faction.values()) + sum(len(v) for v in losses_by_faction.values())
        logger.info(
            f"V1 territory change detection: {total} undocumented "
            f"changes found, appending to narrative"
        )

        lines: list[str] = []
        # Gains first (⚔️), then losses (📉)
        for name, cities in gains_by_faction.items():
            city_list = "\u3001".join(cities)  # 、
            lines.append(f"> **{name}** ⚔️ 夺取 → {city_list}")
        for name, cities in losses_by_faction.items():
            city_list = "\u3001".join(cities)
            lines.append(f"> **{name}** 📉 失去 → {city_list}")

        appendix = "\n\n---\n**🏰 本回合城池易手**\n\n" + "\n".join(lines)
        return narrative + appendix

    return narrative
