"""
三國志略 — 单人模式 API

薄封装层：单人模式 = 多人房间系统 + 1个人类 + 2个AI NPC
对外暴露旧版 GameCreatedResponse / CommandResponse 格式，
前端体验与之前完全一致。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom

# 旧 faction key → 内部 ID 映射（已统一为短码，保留映射仅为兼容）
from histrategy.engine.faction_slot import FACTION_ID_TO_DISPLAY

logger = logging.getLogger("histrategy.single_player")

FACTION_KEY_TO_ID = {"cao": "cao", "shu": "shu", "wu": "wu"}
FACTION_KEY_TO_DISPLAY = FACTION_ID_TO_DISPLAY  # {"cao": "caocao", "shu": "liubei", "wu": "sunquan"}

# 轮询参数
RESOLVE_POLL_INTERVAL = 2.0  # 秒
RESOLVE_TIMEOUT = 180.0  # 秒（LLM 最长等待时间）


# ── Public API ────────────────────────────────────────────────────────────────


def start(
    faction: str, scenario: str = "three-kingdoms", language_style: str = "vernacular", lang: str = "zh"
) -> dict:
    """创建单人游戏。

    内部：创建 1人类+2AI 房间 → 初始化世界 → 触发 NPC → 返回 intro

    Args:
        faction: 势力 key (cao | shu | wu)
        scenario: 剧本 (默认 207)
        language_style: 语言风格 (classical | vernacular)
        lang: 界面语言 (zh | en)

    Returns:
        GameCreatedResponse 格式:
        {game_id, scenario, faction, intro: {narrative, npc_actions, ...}, faction_status}
    """
    from histrategy.server.room_manager import (
        _get_room,
        create_room,
    )

    internal_fid = FACTION_KEY_TO_ID.get(faction, faction)
    display_fid = FACTION_KEY_TO_DISPLAY.get(faction, faction)

    # 1. 创建房间：1 个人类（用 pre_assigned）+ AI NPC 自动填充
    result = create_room(

        scenario=scenario,
        pre_assigned={display_fid: "Player"},
        metadata={"lang": lang},
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "创建房间失败")}

    room_id = result["room_id"]
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间创建后无法加载"}

    # 2. 构建 intro（初始叙事）
    intro = _build_intro(room, internal_fid, language_style, lang)

    # 3. 构建 faction_status
    faction_status = _build_faction_status(room, internal_fid)

    return {
        "game_id": room_id,
        "scenario": scenario,
        "faction": faction,
        "intro": intro,
        "faction_status": faction_status,
    }


def command(game_id: str, decision: str, lang: str = "zh") -> dict:
    """执行玩家命令（阻塞等待 LLM 推演完成）。

    Args:
        game_id: 房间 ID
        decision: 玩家自然语言决策
        lang: 语言 (zh | en)。优先使用显式传入的值，否则从房间 metadata 读取。
    """
    from histrategy.server.room_manager import (
        _get_room,
        submit_decision,
    )

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏不存在"}

    # Auto-detect lang from room metadata if not explicitly passed
    if lang == "zh":
        room_lang = getattr(room, "metadata", {}).get("lang", "zh")
        if room_lang and room_lang != "zh":
            lang = room_lang

    # 找到人类势力
    human_fid = _find_human_faction(room)
    if not human_fid:
        return {"ok": False, "error": "找不到人类势力"}

    # 记录提交前的 quarter（必须在 submit_decision 之前！）
    prev_quarter = room.quarter_number

    # 1. 提交决策 → 同步 resolve（submit_decision 内部调用 _resolve_and_advance）
    from histrategy.server.room_manager import _trigger_npc_decisions

    submit_result = submit_decision(game_id, human_fid, decision)
    if not submit_result.get("ok"):
        return {"ok": False, "error": submit_result.get("error", "提交决策失败")}

    # 2. 检查 resolve 是否已完成（同步调用，应该已经完成）
    # 不需要轮询 — submit_decision 内部是同步的 _resolve_and_advance
    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏在推演中丢失"}

    if room.quarter_number <= prev_quarter:
        # NPC 决策可能还没生成完（异步线程延迟）
        # 尝试同步触发 NPC 决策并 resolve
        logger.info(f"Room {game_id}: quarter unchanged ({prev_quarter}) — triggering NPC decisions sync")
        try:
            _trigger_npc_decisions(room)
            submit_decision(game_id, human_fid, decision)
        except Exception as e:
            logger.warning(f"Room {game_id}: sync NPC trigger failed: {e}")

        room = _get_room(game_id)
        if not room or room.quarter_number <= prev_quarter:
            return {"ok": False, "error": "推演失败，请重试"}

    # 3. 读取推演结果
    narratives = getattr(room, "_last_narratives", {})
    npc_actions = getattr(room, "_last_npc_actions", [])

    narrative = narratives.get(human_fid, "")
    if not narrative:
        # fallback: 用第一个有内容的叙事
        for n in narratives.values():
            if n:
                narrative = n
                break

    # 4. 构建 state_changes（从 world_state 提取当前状态作为变化）
    faction_status = _build_faction_status(room, human_fid)

    # 5. 构建建议
    suggestions = _build_suggestions(room, human_fid, lang)

    return {
        "game_id": game_id,
        "narrative": narrative or "天下无事。",
        "aftermath": _build_aftermath(faction_status, lang),
        "state_changes": {},  # LLM 推演的变化反映在 faction_status 中
        "events_occurred": _extract_events(room),
        "npc_actions": npc_actions,
        "new_suggestions": suggestions,
        "game_over": None,
        "faction_status": faction_status,
        "year": faction_status.get("year", 207),
        "season": faction_status.get("season", "春"),
        "turn": faction_status.get("turn", 0),
    }


def status(game_id: str) -> dict:
    """获取游戏状态。

    Args:
        game_id: 房间 ID

    Returns:
        {game_id, year, season, turn, faction_status, npc_actions, is_waiting}
    """
    from histrategy.server.room_manager import _get_room

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏不存在"}

    human_fid = _find_human_faction(room)
    faction_status = _build_faction_status(room, human_fid) if human_fid else {}
    npc_actions = getattr(room, "_last_npc_actions", [])

    return {
        "game_id": game_id,
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
        "faction_status": faction_status,
        "npc_actions": npc_actions,
        "is_waiting": room.phase.value == "waiting",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_human_faction(room: GameRoom) -> str | None:
    """找到房间中的人类势力 ID。"""
    for fid, slot in room.slots.items():
        if slot.is_human():
            return fid
    return None


def _build_intro(room: GameRoom, faction_id: str, language_style: str, lang: str = "zh") -> dict:
    """构建初始介绍（old IntroScene 格式）。"""
    # 根据 faction 生成介绍叙事
    narrative = _get_intro_narrative(faction_id, language_style, lang)
    is_en = lang == "en"

    return {
        "narrative": narrative,
        "npc_actions": [],  # NPC 的初始行动（在第一回合推演后才有）
        "new_choices": ["Develop Economy", "Military Action", "Recruit Talent", "Consolidate"]
        if is_en
        else ["发展内政", "对外用兵", "广纳贤才", "休养生息"],
        "state_changes": {},
        "events_occurred": [],
    }


def _get_intro_narrative(faction_id: str, language_style: str, lang: str = "zh") -> str:
    """获取初始叙事文本。"""
    from histrategy.server.intro_narratives import INTRO_NARRATIVES_EN, INTRO_NARRATIVES_ZH

    if lang == "en" and faction_id in INTRO_NARRATIVES_EN:
        return INTRO_NARRATIVES_EN[faction_id]
    faction_narratives = INTRO_NARRATIVES_ZH.get(faction_id)
    if faction_narratives:
        return faction_narratives.get(language_style, faction_narratives.get("vernacular", ""))
    return f"历史进入了关键的时刻。你将以{faction_id}势力的身份，在这乱世中书写自己的篇章。"


def _build_faction_status(room: GameRoom, faction_id: str) -> dict:
    """构建 faction_status（old FactionStatus 格式）。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None

    if not faction:
        return {
            "name": faction_id,
            "faction_id": faction_id,
            "strength": 0,
            "food": 0,
            "treasury": 0,
            "territories": [],
            "morale": 50,
            "is_active": False,
            "year": room.year,
            "season": room.season,
            "turn": room.quarter_number,
        }

    territories = []
    pop_sum = 0
    for tid in getattr(faction, "territories", []) or []:
        tid_str = getattr(tid, "id", None) or str(tid)
        territories.append(tid_str)
        # Sum territory populations from ws
        if ws and hasattr(ws, "territories"):
            t_obj = ws.territories.get(tid_str)
            if t_obj:
                pop_sum += getattr(t_obj, "population", 0) or 0

    return {
        "name": getattr(faction, "name", faction_id),
        "faction_id": faction_id,
        "strength": getattr(faction, "strength", 0) or getattr(faction, "strength_actual", 0) or 0,
        "food": int(getattr(faction, "food", 0) or 0),
        "treasury": int(getattr(faction, "treasury", 0) or 0),
        "territories": territories,
        "morale": getattr(faction, "morale", 50) or getattr(faction, "morale_actual", 50) or 50,
        "is_active": getattr(faction, "is_active", True),
        "population": pop_sum,
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
    }


def _build_aftermath(faction_status: dict, lang: str = "zh") -> str:
    """构建 aftermath 文本。"""
    if lang == "en":
        return (
            f"Troops {faction_status.get('strength', 0):,}. "
            f"Food {faction_status.get('food', 0):,}. "
            f"Treasury {faction_status.get('treasury', 0):,}. "
            f"Morale {faction_status.get('morale', 50)}. "
            f"Population {faction_status.get('population', 0):,}."
        )
    return (
        f"兵力{faction_status.get('strength', 0):,}。"
        f"粮草{faction_status.get('food', 0):,}。"
        f"资金{faction_status.get('treasury', 0):,}。"
        f"民心{faction_status.get('morale', 50)}。"
        f"人口{faction_status.get('population', 0):,}。"
    )


def _extract_events(room: GameRoom) -> list[str]:
    """提取历史事件。"""
    events = []
    turn_summaries = getattr(room, "turn_summaries", [])
    if turn_summaries:
        last = turn_summaries[-1]
        if isinstance(last, dict):
            outcome = last.get("outcome_summary", "")
            if outcome and "→" in outcome:
                events_part = outcome.split("→")[-1].strip()
                if events_part and events_part != "天下无事":
                    events = [e.strip() for e in events_part.split(";") if e.strip()]
    return events


def _build_suggestions(room: GameRoom, faction_id: str, lang: str = "zh") -> list[str]:
    """生成策略建议。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None
    suggestions = []
    is_en = lang == "en"

    if faction:
        food = getattr(faction, "food", 0) or 0
        treasury = getattr(faction, "treasury", 0) or 0
        morale = getattr(faction, "morale_actual", 50) or 50
        strength = getattr(faction, "strength_actual", 0) or 0
        territories = len(getattr(faction, "territories", []) or [])

        if food < 5000:
            suggestions.append(
                "Low food — develop agriculture, establish supply lines" if is_en else "粮草不足，宜发展农业、推行屯田"
            )
        if treasury < 5000:
            suggestions.append(
                "Low treasury — cut spending, develop trade" if is_en else "资金短缺，宜降低开支、发展商业"
            )
        if morale < 40:
            suggestions.append(
                "Low morale — reduce taxes, appease the people" if is_en else "民心不稳，宜减轻赋税、安抚百姓"
            )
        if strength < 5000:
            suggestions.append(
                "Low troops — recruit soldiers, train forces" if is_en else "兵力薄弱，宜招募新兵、训练士卒"
            )
        if territories <= 1:
            suggestions.append("Small territory — seek expansion opportunities" if is_en else "领地狭小，宜伺机扩张")

    # 通用建议
    if len(suggestions) < 3:
        defaults = (
            ["Hold council for strategic advice", "Send spies to assess rivals", "Develop new technologies"]
            if is_en
            else ["召开朝会听取谋士建议", "派遣细作探查邻国动向", "发展科技树解锁新政"]
        )
        for d in defaults:
            if d not in suggestions:
                suggestions.append(d)
            if len(suggestions) >= 3:
                break

    return suggestions[:3]
