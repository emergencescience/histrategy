"""
三國志略 — 单人模式 API

薄封装层：单人模式 = 多人房间系统 + 1个人类 + 2个AI NPC
对外暴露旧版 GameCreatedResponse / CommandResponse 格式，
前端体验与之前完全一致。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom

logger = logging.getLogger("histrategy.single_player")

# 旧 faction key → 内部 ID 映射
FACTION_KEY_TO_ID = {"cao": "cao", "shu": "shu", "wu": "wu"}
FACTION_KEY_TO_DISPLAY = {"cao": "caocao", "shu": "liubei", "wu": "sunquan"}

# 轮询参数
RESOLVE_POLL_INTERVAL = 2.0  # 秒
RESOLVE_TIMEOUT = 180.0  # 秒（LLM 最长等待时间）


# ── Public API ────────────────────────────────────────────────────────────────


def start(faction: str, scenario: str = "207", language_style: str = "vernacular") -> dict:
    """创建单人游戏。

    内部：创建 1人类+2AI 房间 → 初始化世界 → 触发 NPC → 返回 intro

    Args:
        faction: 势力 key (cao | shu | wu)
        scenario: 剧本 (默认 207)
        language_style: 语言风格 (classical | vernacular)

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
    result = create_room(pre_assigned={display_fid: "Player"})

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "创建房间失败")}

    room_id = result["room_id"]
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间创建后无法加载"}

    # 2. 构建 intro（初始叙事）
    intro = _build_intro(room, internal_fid, language_style)

    # 3. 构建 faction_status
    faction_status = _build_faction_status(room, internal_fid)

    return {
        "game_id": room_id,
        "scenario": scenario,
        "faction": faction,
        "intro": intro,
        "faction_status": faction_status,
    }


def command(game_id: str, decision: str) -> dict:
    """执行玩家命令（阻塞等待 LLM 推演完成）。

    Args:
        game_id: 房间 ID
        decision: 玩家自然语言决策

    Returns:
        CommandResponse 格式:
        {game_id, narrative, aftermath, state_changes, npc_actions, ...}
    """
    from histrategy.server.room_manager import (
        _get_room,
        submit_decision,
    )

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏不存在"}

    # 找到人类势力
    human_fid = _find_human_faction(room)
    if not human_fid:
        return {"ok": False, "error": "找不到人类势力"}

    # 1. 提交决策 → 触发异步 resolve
    submit_result = submit_decision(game_id, human_fid, decision)
    if not submit_result.get("ok"):
        return {"ok": False, "error": submit_result.get("error", "提交决策失败")}

    # 2. 轮询等待 resolve 完成
    prev_quarter = room.quarter_number
    start_time = time.time()
    while time.time() - start_time < RESOLVE_TIMEOUT:
        time.sleep(RESOLVE_POLL_INTERVAL)
        # 重新加载房间（异步线程可能已更新）
        room = _get_room(game_id)
        if not room:
            return {"ok": False, "error": "游戏在推演中丢失"}
        if room.quarter_number > prev_quarter:
            break
        # 如果 resolve 失败，phase 会被重置为 WAITING，quarter 不变
        if (room.phase.value == "waiting" and room.quarter_number == prev_quarter
                and time.time() - start_time > 10):
            logger.warning(f"Room {game_id}: phase=waiting but quarter unchanged after resolve attempt")
            return {"ok": False, "error": "推演失败，请重试"}
    else:
        return {"ok": False, "error": "推演超时（超过3分钟）"}

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
    suggestions = _build_suggestions(room, human_fid)

    return {
        "game_id": game_id,
        "narrative": narrative or "天下无事。",
        "aftermath": _build_aftermath(faction_status),
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


def _build_intro(room: GameRoom, faction_id: str, language_style: str) -> dict:
    """构建初始介绍（old IntroScene 格式）。"""
    # 根据 faction 生成介绍叙事
    narrative = _get_intro_narrative(faction_id, language_style)

    return {
        "narrative": narrative,
        "npc_actions": [],  # NPC 的初始行动（在第一回合推演后才有）
        "new_choices": ["发展内政", "对外用兵", "广纳贤才", "休养生息"],
        "state_changes": {},
        "events_occurred": [],
    }


def _get_intro_narrative(faction_id: str, language_style: str) -> str:
    """获取初始叙事文本。"""
    narratives = {
        "cao": {
            "classical": "建安十二年春，曹操已平河北，拥兖豫之地，挟天子以令诸侯。帐下谋士如云，猛将如雨，然南方刘表、孙权、刘备各据州郡，天下未定。是岁，曹操于许昌大会群臣，问计于荀彧、郭嘉诸谋士。",
            "vernacular": "公元207年，曹操已平定北方，坐拥中原。挟天子以令诸侯，麾下谋士如云、猛将如雨。然而南方刘表占据荆州，孙权坐断江东，刘备屯兵新野——天下一统的大业，仍前路漫漫。这一年春天，曹操在许昌大会群臣，准备迈出南下的第一步。",
        },
        "shu": {
            "classical": "建安十二年春，刘备寄居新野，虽兵微将寡，然心怀汉室，志在天下。麾下关羽、张飞、赵云皆万人敌，唯缺谋主。闻隆中有贤士诸葛亮，刘备决意三顾茅庐。",
            "vernacular": "公元207年，刘备寄居新野小城。虽然兵力不过数千，但他心怀汉室，志在天下。关羽、张飞、赵云皆是万人敌的猛将，但缺少一位运筹帷幄的军师。听说隆中有一位奇才诸葛亮，刘备决定亲自去拜访。",
        },
        "wu": {
            "classical": "建安十二年春，孙权承父兄基业，坐领江东六郡。内有张昭、周瑜等文武之才，外有长江天险，然北有曹操虎视，西有刘表为邻，孙权日夜思量进取之策。",
            "vernacular": "公元207年，孙权继承父兄的基业，统领江东六郡。文有张昭，武有周瑜，更有长江天险作为屏障。但北方的曹操虎视眈眈，西边的刘表也是一大威胁。孙权深知，偏安一隅终非长久之计。",
        },
    }

    faction_narratives = narratives.get(faction_id, narratives["cao"])
    return faction_narratives.get(language_style, faction_narratives["vernacular"])


def _build_faction_status(room: GameRoom, faction_id: str) -> dict:
    """构建 faction_status（old FactionStatus 格式）。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None

    if not faction:
        return {
            "name": faction_id,
            "faction_id": faction_id,
            "strength": 0, "food": 0, "treasury": 0,
            "territories": [], "morale": 50, "is_active": False,
            "year": room.year, "season": room.season, "turn": room.quarter_number,
        }

    territories = []
    for t in getattr(faction, "territories", []) or []:
        tid = getattr(t, "id", str(t)) if hasattr(t, "id") else str(t)
        territories.append(tid)

    return {
        "name": getattr(faction, "name", faction_id),
        "faction_id": faction_id,
        "strength": getattr(faction, "strength_actual", 0) or 0,
        "food": int(getattr(faction, "food", 0) or 0),
        "treasury": int(getattr(faction, "treasury", 0) or 0),
        "territories": territories,
        "morale": getattr(faction, "morale_actual", 50) or 50,
        "is_active": getattr(faction, "is_active", True),
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
    }


def _build_aftermath(faction_status: dict) -> str:
    """构建 aftermath 文本。"""
    return (
        f"兵力{faction_status.get('strength', 0):,}。"
        f"粮草{faction_status.get('food', 0):,}。"
        f"资金{faction_status.get('treasury', 0):,}。"
        f"民心{faction_status.get('morale', 50)}。"
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


def _build_suggestions(room: GameRoom, faction_id: str) -> list[str]:
    """生成策略建议。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None
    suggestions = []

    if faction:
        food = getattr(faction, "food", 0) or 0
        treasury = getattr(faction, "treasury", 0) or 0
        morale = getattr(faction, "morale_actual", 50) or 50
        strength = getattr(faction, "strength_actual", 0) or 0
        territories = len(getattr(faction, "territories", []) or [])

        if food < 5000:
            suggestions.append("粮草不足，宜发展农业、推行屯田")
        if treasury < 5000:
            suggestions.append("资金短缺，宜降低开支、发展商业")
        if morale < 40:
            suggestions.append("民心不稳，宜减轻赋税、安抚百姓")
        if strength < 5000:
            suggestions.append("兵力薄弱，宜招募新兵、训练士卒")
        if territories <= 1:
            suggestions.append("领地狭小，宜伺机扩张")

    # 通用建议
    if len(suggestions) < 3:
        defaults = ["召开朝会听取谋士建议", "派遣细作探查邻国动向", "发展科技树解锁新政"]
        for d in defaults:
            if d not in suggestions:
                suggestions.append(d)
            if len(suggestions) >= 3:
                break

    return suggestions[:3]
