"""
RoomManager — 多人游戏房间管理。

管理内存中的 GameRoom 实例，提供创建/加入/提交决策/查询状态等操作。
所有操作同时持久化到 SQL（本地 SQLite / Railway PostgreSQL）。

房间状态机：
    LOBBY → (host calls start) → WAITING → (all submitted) → RESOLVING → WAITING → ...
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

from histrategy.engine.faction_slot import OccupantType, create_human_slot

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

logger = logging.getLogger("histrategy.room_manager")

# 内存中的房间注册表 {room_id: GameRoom}
_rooms: dict[str, "GameRoom"] = {}


def _try_save(room: "GameRoom", ws_dict: dict | None = None):
    """尝试持久化房间到 SQL（静默失败）。"""
    try:
        from histrategy.db.models import save_room

        save_room(room, ws_dict)
    except Exception as e:
        logger.warning(f"Room save failed (non-fatal): {e}")


def create_room(
    host_user_id: str = "",
    scenario: str = "207",
    faction_ids: list[str] | None = None,
) -> "GameRoom":
    from histrategy.engine.game_room import GameRoom
    from histrategy.engine.faction_slot import create_open_slot

    if faction_ids is None:
        faction_ids = ["cao", "shu", "wu"]

    room = GameRoom(
        host_user_id=host_user_id,
        scenario=scenario,
    )

    for fid in faction_ids:
        room.slots[fid] = create_open_slot(fid)

    _rooms[room.id] = room
    _try_save(room)
    logger.info(f"Room created: {room.id} ({len(faction_ids)} factions)")
    return room


def get_room(room_id: str) -> "GameRoom | None":
    """获取房间（内存优先，回退 SQL）。"""
    if room_id in _rooms:
        return _rooms[room_id]

    # 尝试从 SQL 加载
    try:
        from histrategy.db.models import load_room

        room = load_room(room_id)
        if room:
            _rooms[room_id] = room
            return room
    except Exception as e:
        logger.warning(f"Room load from DB failed: {e}")

    return None


def join_room(
    room_id: str,
    faction_id: str,
    user_id: str,
    display_name: str = "",
) -> dict:
    """玩家加入房间。

    Returns:
        {"ok": True, "faction": str} 或 {"ok": False, "error": str}
    """
    room = get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room.phase.value not in ("lobby",):
        return {"ok": False, "error": "游戏已开始，无法加入"}

    if faction_id not in room.slots:
        return {"ok": False, "error": f"势力 {faction_id} 不可用"}

    slot = room.slots[faction_id]

    # 已经有人类占据？
    if slot.is_human():
        if slot.occupant_id == user_id:
            return {"ok": True, "faction": faction_id, "already_joined": True}
        return {"ok": False, "error": f"势力 {faction_id} 已被其他人选择"}

    # 加入
    room.slots[faction_id] = create_human_slot(faction_id, user_id)
    _try_save(room)
    logger.info(f"Player {user_id} ({display_name}) joined room {room_id} as {faction_id}")
    return {"ok": True, "faction": faction_id}


def start_game(room_id: str, user_id: str) -> dict:
    """开始游戏。

    需要是房主，或第一个加入的人类玩家。

    Returns:
        {"ok": True, "game_id": str, ...} 或 {"ok": False, "error": str}
    """
    room = get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room.phase.value != "lobby":
        return {"ok": False, "error": "游戏已经开始"}

    # 检查是否至少有一个人类玩家
    human_count = len(room.human_slots())
    if human_count < 1:
        return {"ok": False, "error": "至少需要一个玩家"}

    # 将未填充的 slot 变为 AI
    from histrategy.engine.faction_slot import create_ai_slot
    for fid, s in list(room.slots.items()):
        if s.is_open():
            room.slots[fid] = create_ai_slot(fid)

    # 初始化 WorldState
    try:
        _init_world_state_for_room(room)
    except Exception as e:
        logger.error(f"WorldState init failed: {e}")
        return {"ok": False, "error": f"初始化世界状态失败: {e}"}

    room.start_game()
    _try_save(room)

    humans = [s.faction_id for s in room.human_slots()]
    ais = [s.faction_id for s in room.ai_slots()]
    return {
        "ok": True,
        "room_id": room.id,
        "phase": room.phase.value,
        "humans": humans,
        "ai_npcs": ais,
        "year": room.year,
        "season": room.season,
    }


def _init_world_state_for_room(room: "GameRoom"):
    """为房间初始化 WorldState。"""
    from histrategy.engine.game import GameEngine

    engine = GameEngine(scenario=room.scenario, new_game=True)

    # 用第一个人类玩家的 faction 初始化引擎
    humans = room.human_slots()
    if humans:
        engine.set_player_faction(humans[0].faction_id)

    room.world_state = engine.world_state_v2


def submit_decision(
    room_id: str,
    faction_id: str,
    user_id: str,
    decision: str,
) -> dict:
    """提交本季度决策。

    Returns:
        {"ok": True, "status": "waiting|ready", ...} 或 {"ok": False, "error": str}
    """
    room = get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room.phase.value not in ("waiting",):
        return {"ok": False, "error": f"当前阶段 {room.phase.value} 不能提交决策"}

    if faction_id not in room.slots:
        return {"ok": False, "error": f"势力 {faction_id} 不存在"}

    slot = room.slots[faction_id]
    if not slot.is_active:
        return {"ok": False, "error": f"势力 {faction_id} 已灭亡"}

    if not slot.is_human():
        return {"ok": False, "error": f"势力 {faction_id} 由AI控制"}

    if slot.occupant_id and slot.occupant_id != user_id:
        return {"ok": False, "error": f"你不是势力 {faction_id} 的控制者"}

    slot.submit_decision(decision)
    _try_save(room)

    # 检查是否全员提交
    all_ready = room.all_slots_submitted()
    if all_ready:
        # 触发季度执行
        _resolve_and_advance(room)

    return {
        "ok": True,
        "status": "ready" if all_ready else "waiting",
        "submitted": [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()],
        "pending": room.pending_slots(),
    }


def get_room_status(room_id: str, faction_id: str | None = None) -> dict:
    """获取房间状态。

    如果季度已执行完毕，返回上一个季度的 narrative。
    """
    room = get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    status = {
        "ok": True,
        "room_id": room.id,
        "phase": room.phase.value,
        "year": room.year,
        "season": room.season,
        "quarter": room.quarter_number,
        "slots": {
            fid: {
                "faction_id": fid,
                "occupant_type": s.occupant_type.value,
                "occupant_id": s.occupant_id,
                "has_submitted": s.has_submitted(),
                "is_active": s.is_active,
            }
            for fid, s in room.slots.items()
        },
        "submitted": [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()],
        "pending": room.pending_slots(),
    }

    # 如果有上一季度的叙事，返回该 faction 的版本
    if faction_id and hasattr(room, "_last_narratives"):
        narratives = getattr(room, "_last_narratives", {})
        status["narrative"] = narratives.get(faction_id, "")
        status["all_narratives"] = narratives
        status["npc_actions"] = getattr(room, "_last_npc_actions", [])

    return status


def _resolve_and_advance(room: "GameRoom"):
    """执行季度模拟并推进。"""
    from histrategy.engine.decision_bus import collect_all_decisions
    from histrategy.engine.quarterly_resolver import QuarterlyResolver
    from histrategy.engine.game_room import RoomPhase

    if room.phase.value == "resolving":
        return  # 防止重入

    room.phase = RoomPhase.RESOLVING

    ws = room.world_state
    if ws is None:
        logger.error("No world state for room %s", room.id)
        room.advance_quarter()
        return

    # 尝试获取 LLM
    llm = _get_llm()

    # 收集决策
    decisions = collect_all_decisions(
        room, ws, llm=llm,
        turn_memory=room.turn_summaries,
    )

    # 执行季度
    resolver = QuarterlyResolver(
        turn_controller=getattr(room, "_turn_controller", None),
        macro_policy_engine=getattr(room, "_macro_sim", None),
    )

    result = resolver.resolve(room, ws, decisions, llm=llm)

    # 保存叙事到 room
    room._last_narratives = result.narratives

    # NPC actions
    npc_actions = []
    for fid, dr in decisions.items():
        if room.slots.get(fid) and room.slots[fid].is_ai():
            faction = ws.factions.get(fid) if ws else None
            name = faction.name if faction else fid
            npc_actions.append(f"{name}: {dr.decision_text[:80]}")
    room._last_npc_actions = npc_actions

    # 回合摘要
    if result.turn_summary:
        room.turn_summaries.append(result.turn_summary)
        if len(room.turn_summaries) > 8:
            room.turn_summaries = room.turn_summaries[-8:]

    # 推进季度
    _advance_season(ws)
    room.advance_quarter()

    # 更新世界状态
    room.world_state = ws

    # 持久化
    ws_dict = ws.to_dict() if hasattr(ws, "to_dict") else None
    _try_save(room, ws_dict)
    _save_quarter_record(room, decisions, result)

    # 文件备份（只写）
    try:
        from histrategy.db.file_backup import write_room_snapshot, cleanup_old_backups

        write_room_snapshot(room, ws_dict, "quarter_complete")
        cleanup_old_backups(room.id, keep=20)
    except Exception:
        pass

    logger.info(
        "Room %s quarter %d resolved: %d factions, %d narratives",
        room.id, room.quarter_number, len(decisions), len(result.narratives),
    )


def _get_llm() -> "LLMAdapter | None":
    """获取 LLM 适配器。"""
    try:
        from histrategy.llm.adapter import LLMAdapter

        return LLMAdapter()
    except Exception:
        return None


def _advance_season(ws: "WorldState"):
    """推进季度（原地修改）。"""
    try:
        from histrategy_engine.world import Season

        seasons = list(Season)
        idx = seasons.index(ws.season)
        ws.season = seasons[(idx + 1) % len(seasons)]
        if ws.season == seasons[0]:
            ws.year += 1
        ws.turn_number += 1
    except (ValueError, IndexError, AttributeError):
        pass


def _save_quarter_record(room, decisions, result):
    """持久化季度记录到 SQL。"""
    try:
        from histrategy.db.models import save_quarter_turn

        faction_decisions = {
            fid: {
                "decision": dr.decision_text,
                "commands": dr.commands,
                "source": dr.source,
            }
            for fid, dr in decisions.items()
        }

        save_quarter_turn(
            room.id,
            room.quarter_number,
            room.year,
            room.season,
            faction_decisions=faction_decisions,
            narratives=result.narratives,
            state_changes=result.state_changes,
        )
    except Exception as e:
        logger.warning(f"Quarter record save failed: {e}")


def list_rooms() -> list[dict]:
    """列出活跃房间。"""
    return [
        {
            "id": room.id,
            "scenario": room.scenario,
            "phase": room.phase.value,
            "players": len(room.human_slots()),
            "slots": {
                fid: s.occupant_type.value
                for fid, s in room.slots.items()
            },
        }
        for room in _rooms.values()
    ]
