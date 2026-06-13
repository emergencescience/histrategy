"""
RoomManager — 多人游戏房间管理（v2: room_player 对称架构）。

核心改进：
  - room_player 表：进入房间 ≠ 选择势力。host 可以观战。
  - 创建/加入统一为 "enter" — 任何人都可以进入房间。
  - host 负责开始游戏；billing 默认 host 付费。

玩家角色：
  host      — 创建房间的人，可以开始游戏、踢人
  player    — 普通玩家，可以选势力
  spectator — 观战者，不能选势力也不能决策
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

logger = logging.getLogger("histrategy.room_manager")

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom

# 内存中的房间 {room_id: GameRoom}
_rooms: dict[str, "GameRoom"] = {}
# 内存中的玩家 {room_id: {user_id: {role, display_name}}}
_players: dict[str, dict[str, dict]] = {}


def _try_save(room: "GameRoom", ws_dict: dict | None = None):
    try:
        from histrategy.db.models import save_room
        save_room(room, ws_dict)
    except Exception as e:
        logger.warning(f"Room save failed (non-fatal): {e}")


# ── Room CRUD ────────────────────────────────────────


def create_room(
    host_user_id: str = "",
    host_name: str = "",
    scenario: str = "207",
    faction_ids: list[str] | None = None,
) -> dict:
    """创建一个新房间。host 不自动选势力。

    Returns:
        {"ok": True, "room_id": str}
    """
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
    _players[room.id] = {}

    # host 自动进入房间，生成 player_token
    host_token = uuid.uuid4().hex
    _enter_player(room.id, host_user_id, "host", host_name, host_token)
    _try_save(room)

    logger.info(f"Room created: {room.id} by {host_user_id or 'anon'}")
    return {"ok": True, "room_id": room.id, "host_token": host_token}


def enter_room(
    room_id: str,
    user_id: str,
    display_name: str = "",
) -> dict:
    """进入房间（玩家/观战者）。

    Returns:
        {"ok": True, "role": "player", "room": {...}} 或 error
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room_id not in _players:
        _players[room_id] = {}

    # 如果已在房间里，返回当前状态
    if user_id in _players[room_id]:
        p = _players[room_id][user_id]
        return {
            "ok": True, "already_in": True,
            "role": p["role"], "room": _room_summary(room),
        }

    # 新玩家：默认 player 角色
    role = "player"

    # 生成 player_token 用于同浏览器多 tab 隔离
    # 这个 token 独立于 JWT——两个 Chrome tab 使用不同的 token，
    # 即使 JWT 相同也能区分不同玩家
    player_token = uuid.uuid4().hex

    _enter_player(room_id, user_id, role, display_name, player_token)
    return {
        "ok": True,
        "role": role,
        "player_token": player_token,
        "room": _room_summary(room),
    }


def kick_player(room_id: str, host_user_id: str, target_user_id: str) -> dict:
    """host 踢人。"""
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    host = _players.get(room_id, {}).get(host_user_id, {})
    if host.get("role") != "host":
        return {"ok": False, "error": "只有房主可以踢人"}

    if target_user_id in _players.get(room_id, {}):
        # 释放该玩家占据的势力
        for slot in room.slots.values():
            if slot.is_human() and slot.occupant_id == target_user_id:
                from histrategy.engine.faction_slot import create_open_slot
                room.slots[slot.faction_id] = create_open_slot(slot.faction_id)
        del _players[room_id][target_user_id]

    return {"ok": True}


def pick_faction(room_id: str, user_id: str, faction_id: str) -> dict:
    """玩家选择一个势力。

    Returns:
        {"ok": True, "faction": str} 或 error
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    player = _players.get(room_id, {}).get(user_id)
    if not player:
        return {"ok": False, "error": "请先进入房间"}

    if player["role"] == "spectator":
        return {"ok": False, "error": "观战者不能选择势力"}

    if room.phase.value not in ("lobby",):
        return {"ok": False, "error": "游戏已开始，不能选势力"}

    if faction_id not in room.slots:
        return {"ok": False, "error": f"势力 {faction_id} 不可用"}

    slot = room.slots[faction_id]
    if slot.is_human() and slot.occupant_id != user_id:
        return {"ok": False, "error": f"势力 {faction_id} 已被其他人选择"}

    # 先释放该玩家之前选的势力（如果有）
    for fid, s in room.slots.items():
        if s.is_human() and s.occupant_id == user_id and fid != faction_id:
            from histrategy.engine.faction_slot import create_open_slot
            room.slots[fid] = create_open_slot(fid)

    # 占据新势力
    from histrategy.engine.faction_slot import create_human_slot
    room.slots[faction_id] = create_human_slot(faction_id, user_id)
    _try_save(room)

    logger.info(f"Player {user_id} picked {faction_id} in room {room_id}")
    return {"ok": True, "faction": faction_id}


def start_game(room_id: str, user_id: str) -> dict:
    """host 开始游戏。未选的势力自动变 AI。

    Returns:
        {"ok": True, "phase": "waiting", "humans": [...], "ai_npcs": [...]}
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    player = _players.get(room_id, {}).get(user_id, {})
    if player.get("role") != "host":
        return {"ok": False, "error": "只有房主可以开始游戏"}

    if room.phase.value != "lobby":
        return {"ok": False, "error": "游戏已经开始"}

    # 至少需要一个人类玩家
    human_count = sum(1 for s in room.slots.values() if s.is_human())
    if human_count < 1:
        return {"ok": False, "error": "至少需要一个玩家选择势力"}

    # 未选的 slot 变 AI
    from histrategy.engine.faction_slot import create_ai_slot
    for fid, s in list(room.slots.items()):
        if s.is_open():
            room.slots[fid] = create_ai_slot(fid)

    # 初始化 WorldState
    try:
        _init_world_state(room)
    except Exception as e:
        logger.error(f"WorldState init failed: {e}")
        return {"ok": False, "error": f"初始化世界状态失败: {e}"}

    room.start_game()
    _try_save(room)

    # NPC 立即下命令（不等人类提交）
    _trigger_npc_decisions(room)

    humans = [s.faction_id for s in room.slots.values() if s.is_human()]
    ais = [s.faction_id for s in room.slots.values() if s.is_ai()]
    return {
        "ok": True,
        "room_id": room.id,
        "phase": "waiting",
        "humans": humans,
        "ai_npcs": ais,
        "year": room.year,
        "season": room.season,
    }


# ── Decision & Status ───────────────────────────────


def submit_decision(room_id: str, faction_id: str, user_id: str, decision: str) -> dict:
    """提交本季度决策。全员提交后自动 resolve。"""
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room.phase.value != "waiting":
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

    submitted = [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()]
    pending = [fid for fid, s in room.slots.items() if s.is_active and not s.has_submitted()]

    if not pending:
        _resolve_and_advance(room)

    return {
        "ok": True,
        "status": "ready" if not pending else "waiting",
        "submitted": submitted,
        "pending": pending,
    }


def get_room_status(room_id: str, faction_id: str | None = None) -> dict:
    """获取房间状态（含玩家列表、势力分配）。"""
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    room_players = _players.get(room_id, {})
    submitted = [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()]
    pending = [fid for fid, s in room.slots.items() if s.is_active and not s.has_submitted()]

    status = {
        "ok": True,
        "room_id": room.id,
        "host_user_id": room.host_user_id,
        "phase": room.phase.value,
        "year": room.year,
        "season": room.season,
        "quarter": room.quarter_number,
        "players": {
            uid: {"role": p["role"], "display_name": p.get("display_name", "")}
            for uid, p in room_players.items()
        },
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
        "submitted": submitted,
        "pending": pending,
    }

    if faction_id and hasattr(room, "_last_narratives"):
        narratives = getattr(room, "_last_narratives", {})
        status["narrative"] = narratives.get(faction_id, "")
        status["npc_actions"] = getattr(room, "_last_npc_actions", [])

    return status


# ── Internal ─────────────────────────────────────────


def _trigger_npc_decisions(room: "GameRoom"):
    """在回合开始时立即为所有 AI NPC 生成决策。

    这样当人类玩家提交决策后，不需要等待 NPC LLM 调用——
    NPC 已经提前提交了决策，最后一个人类提交即可立即 resolve。
    """
    from histrategy.engine.decision_bus import collect_all_decisions

    ws = room.world_state
    if ws is None:
        return

    llm = _get_llm()

    # 只收集 AI NPC 的决策（人类会在自己的时机提交）
    ai_only = {
        fid: s
        for fid, s in room.slots.items()
        if s.is_ai() and s.is_active
    }

    if not ai_only:
        return

    logger.info(
        f"Room {room.id} Q{room.quarter_number}: triggering NPC decisions for {list(ai_only.keys())}"
    )

    # 临时替换 room.slots 为只含 AI 的版本，避免 DecisionBus 等待人类
    # 使用 collect_all_decisions 为 AI 生成决策
    try:
        decisions = collect_all_decisions(
            room, ws, llm=llm, turn_memory=room.turn_summaries
        )
        # 将 AI 决策写入对应的 slot
        for fid, dr in decisions.items():
            if fid in room.slots:
                room.slots[fid].submit_decision(dr.decision_text, dr.commands)
        logger.info(
            f"Room {room.id}: NPC decisions ready — {list(decisions.keys())}"
        )
    except Exception as e:
        logger.error(f"Room {room.id}: NPC decision trigger failed: {e}")


def _get_room(room_id: str) -> "GameRoom | None":
    if room_id in _rooms:
        return _rooms[room_id]
    try:
        from histrategy.db.models import load_room
        room = load_room(room_id)
        if room:
            _rooms[room_id] = room
            return room
    except Exception:
        pass
    return None


def _enter_player(room_id: str, user_id: str, role: str, display_name: str, player_token: str = ""):
    if room_id not in _players:
        _players[room_id] = {}
    _players[room_id][user_id] = {
        "role": role,
        "display_name": display_name,
        "player_token": player_token,
    }
    _save_player_to_db(room_id, user_id, role, display_name)


def _save_player_to_db(room_id: str, user_id: str, role: str, display_name: str):
    try:
        from histrategy.db.connection import execute_write
        pid = f"{room_id}_{user_id}"
        execute_write(
            """INSERT OR REPLACE INTO room_player (id, room_id, user_id, role, display_name)
            VALUES (?, ?, ?, ?, ?)""",
            (pid, room_id, user_id, role, display_name),
        )
    except Exception:
        pass


def _room_summary(room: "GameRoom") -> dict:
    return {
        "room_id": room.id,
        "phase": room.phase.value,
        "slots": {
            fid: s.occupant_type.value
            for fid, s in room.slots.items()
        },
    }


def _init_world_state(room: "GameRoom"):
    from histrategy.engine.game import GameEngine
    engine = GameEngine(scenario=room.scenario, new_game=True)
    humans = [s for s in room.slots.values() if s.is_human()]
    if humans:
        engine.set_player_faction(humans[0].faction_id)
    room.world_state = engine.world_state_v2


def _resolve_and_advance(room: "GameRoom"):
    from histrategy.engine.decision_bus import collect_all_decisions
    from histrategy.engine.quarterly_resolver import QuarterlyResolver
    from histrategy.engine.game_room import RoomPhase

    if room.phase.value == "resolving":
        return

    room.phase = RoomPhase.RESOLVING
    ws = room.world_state
    if ws is None:
        room.advance_quarter()
        return

    llm = _get_llm()
    decisions = collect_all_decisions(room, ws, llm=llm, turn_memory=room.turn_summaries)

    resolver = QuarterlyResolver(
        turn_controller=getattr(room, "_turn_controller", None),
    )
    result = resolver.resolve(room, ws, decisions, llm=llm)

    room._last_narratives = result.narratives
    npc_actions = []
    for fid, dr in decisions.items():
        if room.slots.get(fid) and room.slots[fid].is_ai():
            faction = ws.factions.get(fid) if ws else None
            name = faction.name if faction else fid
            npc_actions.append(f"{name}: {dr.decision_text[:80]}")
    room._last_npc_actions = npc_actions

    if result.turn_summary:
        room.turn_summaries.append(result.turn_summary)
        if len(room.turn_summaries) > 8:
            room.turn_summaries = room.turn_summaries[-8:]

    _advance_season(ws)
    room.advance_quarter()
    room.world_state = ws

    # 下个季度 NPC 立即下命令
    _trigger_npc_decisions(room)

    ws_dict = ws.to_dict() if hasattr(ws, "to_dict") else None
    _try_save(room, ws_dict)
    _save_quarter(room, decisions, result)
    _write_backup(room, ws_dict)


def _get_llm():
    try:
        from histrategy.llm.adapter import LLMAdapter
        return LLMAdapter()
    except Exception:
        return None


def _advance_season(ws):
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


def _save_quarter(room, decisions, result):
    try:
        from histrategy.db.models import save_quarter_turn
        fd = {fid: {"decision": dr.decision_text, "commands": dr.commands, "source": dr.source}
              for fid, dr in decisions.items()}
        save_quarter_turn(room.id, room.quarter_number, room.year, room.season,
                          faction_decisions=fd, narratives=result.narratives,
                          state_changes=result.state_changes)
    except Exception as e:
        logger.warning(f"Quarter save failed: {e}")


def _write_backup(room, ws_dict):
    try:
        from histrategy.db.file_backup import write_room_snapshot, cleanup_old_backups
        write_room_snapshot(room, ws_dict, "quarter_complete")
        cleanup_old_backups(room.id, keep=20)
    except Exception:
        pass
