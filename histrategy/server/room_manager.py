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
_rooms: dict[str, GameRoom] = {}
# 内存中的玩家 {room_id: {user_id: {role, display_name}}}
_players: dict[str, dict[str, dict]] = {}


def _try_save(room: GameRoom, ws_dict: dict | None = None):
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
    human_faction_ids: list[str] | None = None,
    pre_assigned: dict[str, str] | None = None,
) -> dict:
    """创建房间并立即开始游戏。

    Host 预分配势力（推荐）：pre_assigned = {"caocao": "张三", "liubei": "李四"}
    → 每个玩家获得专属链接 /mp?room=xxx&faction=caocao&player_token=<token>
    → 未分配的势力自动变 AI NPC

    兼容旧 API：human_faction_ids = ["caocao", "liubei"] → 设为 OPEN 等待加入

    Returns:
        {"ok": True, "room_id": str, "player_links": [{faction, token, url}], ...}
    """
    from histrategy.engine.faction_slot import (
        FACTION_DISPLAY_TO_ID,
        FACTION_ID_TO_DISPLAY,
        LLM_NPC_FACTIONS,
        PLAYABLE_FACTIONS,
        create_ai_slot,
        create_open_slot,
    )
    from histrategy.engine.game_room import GameRoom, RoomPhase

    # 翻译显示名 → 内部 ID（caocao→cao, liubei→shu, sunquan→wu）
    if pre_assigned:
        # 新流程：Host 预分配势力到具体玩家
        internal_map = {}
        for display_fid, player_name in pre_assigned.items():
            internal_fid = FACTION_DISPLAY_TO_ID.get(display_fid, display_fid)
            internal_map[internal_fid] = player_name
        internal_ids = list(internal_map.keys())
    else:
        internal_ids = [FACTION_DISPLAY_TO_ID.get(f, f) for f in (human_faction_ids or PLAYABLE_FACTIONS)]
        internal_map = None

    if not internal_ids:
        internal_ids = ["cao", "shu", "wu"]

    room = GameRoom(
        host_user_id=host_user_id,
        scenario=scenario,
    )
    _rooms[room.id] = room
    _players[room.id] = {}

    # 人类势力 → OPEN（等待玩家加入）或 HUMAN（预分配）
    player_links = []
    for fid in internal_ids:
        if internal_map:
            # 预分配：直接设为 HUMAN，生成专属 token
            from histrategy.engine.faction_slot import create_human_slot
            player_user_id = "u_" + uuid.uuid4().hex
            player_token = uuid.uuid4().hex
            slot = create_human_slot(fid, player_user_id)
            room.slots[fid] = slot
            player_name = internal_map[fid]
            display_fid = FACTION_ID_TO_DISPLAY.get(fid, fid)
            player_links.append({
                "faction": display_fid,
                "player_name": player_name,
                "player_token": player_token,
                "url": f"/mp?room={room.id}&faction={display_fid}&player_token={player_token}",
            })
            # 注册玩家
            _enter_player(room.id, player_user_id, "player", player_name, player_token)
        else:
            room.slots[fid] = create_open_slot(fid)

    # 未指定的势力 → AI NPC
    for fid in LLM_NPC_FACTIONS:
        if fid not in room.slots:
            room.slots[fid] = create_ai_slot(fid)

    # host 进入房间
    host_token = uuid.uuid4().hex
    _enter_player(room.id, host_user_id or ("host_" + uuid.uuid4().hex[:6]), "host", host_name or "房主", host_token)

    # 立即初始化世界状态并开始游戏
    _init_world_state(room)
    room.phase = RoomPhase.WAITING
    _try_save(room)

    # AI NPC 马上开始生成决策
    _trigger_npc_decisions(room)

    # 返回显示名列表供前端展示
    display_factions = [FACTION_ID_TO_DISPLAY.get(f, f) for f in internal_ids]

    logger.info(f"Room created+started: {room.id} by {host_user_id or 'anon'} (humans: {display_factions})")
    result = {
        "ok": True,
        "room_id": room.id,
        "host_token": host_token,
        "phase": "waiting",
        "human_factions": display_factions,
    }
    if player_links:
        result["player_links"] = player_links
    return result


def enter_room(
    room_id: str,
    user_id: str = "",
    display_name: str = "",
    faction: str = "",
    player_token: str = "",
) -> dict:
    """进入房间。

    简化模式：玩家访问 /mp?room=xxx&faction=cao&player_token=xxx 即可自动进入。
    player_token 是 Host 创建房间时分配的凭证，防止同浏览器 session 混淆。

    Returns:
        {"ok": True, "faction": str, ...} 或 error
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if room_id not in _players:
        _players[room_id] = {}

    # 自动生成 user_id（不需要人类维护 user 表）
    if not user_id:
        # 如果提供了 player_token，尝试查找已有玩家
        if player_token and room_id in _players:
            for uid, pdata in _players[room_id].items():
                if pdata.get("player_token") == player_token:
                    user_id = uid
                    break
        if not user_id:
            user_id = "u_" + uuid.uuid4().hex  # full UUID v4 for uniqueness

    # 翻译显示名 → 内部 ID
    if faction:
        from histrategy.engine.faction_slot import FACTION_DISPLAY_TO_ID

        faction = FACTION_DISPLAY_TO_ID.get(faction, faction)

    # 如果指定了 faction，自动占据该势力（如果 slot 存在且 open）
    if faction and faction in room.slots:
        slot = room.slots[faction]
        if slot.is_open():
            # 自动占据势力
            from histrategy.engine.faction_slot import create_human_slot

            room.slots[faction] = create_human_slot(faction, user_id)
            logger.info(f"Player {user_id} auto-claimed {faction} in room {room_id}")
            _try_save(room)
        elif slot.is_human() and slot.occupant_id != user_id:
            return {"ok": False, "error": f"势力 {faction} 已被其他人占据"}

    # 如果已在房间里，返回当前状态
    if user_id in _players[room_id]:
        p = _players[room_id][user_id]
        result = {
            "ok": True,
            "already_in": True,
            "user_id": user_id,
            "player_token": p.get("player_token", ""),
            "role": p["role"],
            "faction": faction,
            "room": _room_summary(room),
        }
        return result

    # 新玩家
    role = "player"
    # 保留调用者传入的 player_token（预分配模式），否则生成新的
    if not player_token:
        player_token = uuid.uuid4().hex
    _enter_player(room_id, user_id, role, display_name or ("玩家_" + user_id[-4:]), player_token)

    result = {
        "ok": True,
        "role": role,
        "user_id": user_id,
        "faction": faction,
        "player_token": player_token,
        "room": _room_summary(room),
    }
    return result


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


def submit_decision(room_id: str, faction_id: str, user_id: str, decision: str, player_token: str = "") -> dict:
    """提交本季度决策。全员提交后自动 resolve。

    如果提供了 player_token，优先用它解析 user_id（预分配模式）。
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    # player_token 解析（预分配模式：前端可能不知道 user_id）
    if player_token and room_id in _players:
        for uid, pdata in _players[room_id].items():
            if pdata.get("player_token") == player_token:
                user_id = uid
                break

    if not user_id:
        return {"ok": False, "error": "缺少 user_id 或 player_token"}

    # 自动修复：如果 room 有 world_state 但 phase 还是 lobby
    from histrategy.engine.game_room import RoomPhase
    if room.phase == RoomPhase.LOBBY and room.world_state is not None:
        logger.warning(f"Room {room_id} has world_state but phase=lobby — auto-advancing to WAITING")
        room.phase = RoomPhase.WAITING
        _try_save(room)

    if room.phase.value != "waiting":
        return {"ok": False, "error": f"当前阶段 {room.phase.value} 不能提交决策"}

    # 翻译显示名 → 内部 ID
    from histrategy.engine.faction_slot import FACTION_DISPLAY_TO_ID
    faction_id = FACTION_DISPLAY_TO_ID.get(faction_id, faction_id)

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
        # 异步执行（LLM 调用可能耗时 30-60s，不能阻塞 HTTP 响应）
        import threading
        import traceback

        def _resolve_safe(room):
            try:
                _resolve_and_advance(room)
            except Exception as exc:
                logger.error("Room %s resolve failed: %s", room.id, exc)
                traceback.print_exc()
                room.phase = type(room.phase).WAITING  # reset on error

        t = threading.Thread(target=_resolve_safe, args=(room,), daemon=True)
        t.start()

    status = "resolving" if not pending else "waiting"
    return {
        "ok": True,
        "status": status,
        "submitted": submitted,
        "pending": pending,
    }


def get_room_status(room_id: str, faction_id: str | None = None) -> dict:
    """获取房间状态（含玩家列表、势力分配）。"""
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    from histrategy.engine.faction_slot import FACTION_ID_TO_DISPLAY

    room_players = _players.get(room_id, {})
    submitted = [
        FACTION_ID_TO_DISPLAY.get(fid, fid) for fid, s in room.slots.items() if s.is_active and s.has_submitted()
    ]
    pending = [
        FACTION_ID_TO_DISPLAY.get(fid, fid) for fid, s in room.slots.items() if s.is_active and not s.has_submitted()
    ]

    status = {
        "ok": True,
        "room_id": room.id,
        "host_user_id": room.host_user_id,
        "phase": room.phase.value,
        "year": room.year,
        "season": room.season,
        "quarter": room.quarter_number,
        "players": {
            uid: {"role": p["role"], "display_name": p.get("display_name", "")} for uid, p in room_players.items()
        },
        "slots": {
            FACTION_ID_TO_DISPLAY.get(fid, fid): {
                "faction_id": FACTION_ID_TO_DISPLAY.get(fid, fid),
                "internal_id": fid,
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


def _trigger_npc_decisions(room: GameRoom):
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
    ai_only = {fid: s for fid, s in room.slots.items() if s.is_ai() and s.is_active}

    if not ai_only:
        return

    logger.info(f"Room {room.id} Q{room.quarter_number}: triggering NPC decisions for {list(ai_only.keys())}")

    # 临时替换 room.slots 为只含 AI 的版本，避免 DecisionBus 等待人类
    # 使用 collect_all_decisions 为 AI 生成决策
    try:
        decisions = collect_all_decisions(room, ws, llm=llm, turn_memory=room.turn_summaries)
        # 将 AI 决策写入对应的 slot
        for fid, dr in decisions.items():
            if fid in room.slots:
                room.slots[fid].submit_decision(dr.decision_text, dr.commands)
        logger.info(f"Room {room.id}: NPC decisions ready — {list(decisions.keys())}")
    except Exception as e:
        logger.error(f"Room {room.id}: NPC decision trigger failed: {e}")


def _get_room(room_id: str) -> GameRoom | None:
    if room_id in _rooms:
        return _rooms[room_id]
    try:
        from histrategy.db.models import load_room

        room = load_room(room_id)
        if room:
            _rooms[room_id] = room
            # 从 DB 恢复玩家注册（支持服务器重启后重新连接）
            _restore_players_from_db(room_id)
            # 从 DB 恢复的房间如果处于 WAITING 阶段且有 AI NPC，
            # 需要立即触发 NPC 决策生成（from_dict 会清空 pending_decision）
            if room.phase.value == "waiting" and any(s.is_ai() and s.is_active for s in room.slots.values()):
                logger.info(f"Room {room_id} loaded from DB (Q{room.quarter_number}), triggering NPC decisions")
                _trigger_npc_decisions(room)
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
    _save_player_to_db(room_id, user_id, role, display_name, player_token)


def _save_player_to_db(room_id: str, user_id: str, role: str, display_name: str, player_token: str = ""):
    try:
        from histrategy.db.connection import execute_write

        pid = f"{room_id}_{user_id}"
        # 尝试写入 player_token（H13o 新增列），如果列不存在则回退
        try:
            execute_write(
                """INSERT OR REPLACE INTO room_player (id, room_id, user_id, role, display_name, player_token)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (pid, room_id, user_id, role, display_name, player_token),
            )
        except Exception:
            # player_token 列可能还不存在（迁移未运行），回退到 5 列版本
            execute_write(
                """INSERT OR REPLACE INTO room_player (id, room_id, user_id, role, display_name)
                VALUES (?, ?, ?, ?, ?)""",
                (pid, room_id, user_id, role, display_name),
            )
    except Exception:
        pass


def _restore_players_from_db(room_id: str):
    """从 room_player 表恢复玩家注册信息到内存（服务器重启后）。"""
    try:
        from histrategy.db.connection import execute

        # 先尝试读取包含 player_token 列（H13o+），失败则回退
        try:
            rows = execute(
                "SELECT user_id, role, display_name, player_token FROM room_player WHERE room_id = ?",
                (room_id,),
            )
        except Exception:
            rows = execute(
                "SELECT user_id, role, display_name FROM room_player WHERE room_id = ?",
                (room_id,),
            )
        if rows:
            if room_id not in _players:
                _players[room_id] = {}
            for row in rows:
                uid = row["user_id"]
                if uid not in _players[room_id]:
                    _players[room_id][uid] = {
                        "role": row["role"],
                        "display_name": row["display_name"] or "",
                        "player_token": row.get("player_token", "") or "",
                    }
            logger.info(f"Restored {len(rows)} players for room {room_id} from DB")
    except Exception:
        pass


def _room_summary(room: GameRoom) -> dict:
    return {
        "room_id": room.id,
        "phase": room.phase.value,
        "slots": {fid: s.occupant_type.value for fid, s in room.slots.items()},
    }


def _init_world_state(room: GameRoom):
    from histrategy.engine.game import GameEngine

    engine = GameEngine(scenario=room.scenario, new_game=True)
    humans = [s for s in room.slots.values() if s.is_human()]
    if humans:
        engine.set_player_faction(humans[0].faction_id)
    room.world_state = engine.world_state_v2


def _resolve_and_advance(room: GameRoom):
    from histrategy.engine.decision_bus import collect_all_decisions
    from histrategy.engine.engine_switch import EngineMode, detect_engine_mode
    from histrategy.engine.game_room import RoomPhase

    if room.phase.value == "resolving":
        return

    room.phase = RoomPhase.RESOLVING
    ws = room.world_state
    if ws is None:
        room.advance_quarter()
        return

    engine_mode = detect_engine_mode()
    llm = _get_llm()
    decisions = collect_all_decisions(room, ws, llm=llm, turn_memory=room.turn_summaries)

    # 根据引擎模式选择仿真器
    if engine_mode == EngineMode.V1:
        result = _resolve_v1(room, ws, decisions, llm)
    else:
        result = _resolve_v3(room, ws, decisions, llm)

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


def _resolve_v1(room, ws, decisions, llm):
    """V1 引擎：纯 LLM 仿真。"""
    from dataclasses import dataclass

    from histrategy.engine.v1_simulator import V1Simulator, _apply_v1_state_to_world, save_v1_state_to_db

    simulator = V1Simulator(llm)

    fd = {}
    for fid, dr in decisions.items():
        fd[fid] = {"decision": dr.decision_text, "commands": dr.commands}

    v1_result = simulator.simulate(ws, fd, room.turn_summaries)
    logger.warning(
        "V1 resolve: room=%s result_keys=%s factions_count=%d",
        room.id, list(v1_result.keys()), len(v1_result.get("factions", {})),
    )

    # ── 先捕获旧状态（用于 turn_delta 计算）──
    old_state = {}
    v1_factions = v1_result.get("factions", {})
    for fid in v1_factions:
        faction = ws.factions.get(fid)
        if faction:
            old_state[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": getattr(faction, "strength_actual", 0),
                "food": faction.food,
                "treasury": faction.treasury,
                "morale": getattr(faction, "morale_actual", 50),
            }

    # 将 V1 结果应用到 WorldState
    _apply_v1_state_to_world(ws, v1_factions)

    # 写入 DB（传入旧状态以计算 delta）
    # Note: room.quarter_number hasn't been incremented yet — save with next quarter
    save_v1_state_to_db(room.id, room.quarter_number + 1, ws, v1_result, old_state=old_state)

    # 构建兼容 result 对象
    @dataclass
    class V1Result:
        narratives: dict
        state_changes: dict
        turn_summary: dict | None

    narratives = {}
    for fid in decisions:
        narratives[fid] = v1_result.get("narrative", "")

    return V1Result(
        narratives=narratives,
        state_changes={},
        turn_summary={"quarter": room.quarter_number, "engine": "v1"},
    )


def _resolve_v3(room, ws, decisions, llm):
    """V3 引擎：完整初始化的 QuarterlyResolver。"""

    from histrategy.engine.quarterly_resolver import QuarterlyResolver

    # ── 先捕获旧状态（用于 turn_delta 计算）──
    old_state = {}
    for fid in ws.factions:
        faction = ws.factions[fid]
        old_state[fid] = {
            "population": getattr(faction, "population", 0),
            "troops": getattr(faction, "strength_actual", 0),
            "food": faction.food,
            "treasury": faction.treasury,
            "morale": getattr(faction, "morale_actual", 50),
        }

    # 创建临时 GameEngine 来获取所有子引擎
    try:
        import os
        os.environ.setdefault("HISTRATEGY_MACRO", "1")
        from histrategy.engine.game import GameEngine
        engine = GameEngine(scenario=room.scenario, new_game=True, llm=llm)
        engine.world_state_v2 = ws
        engine._use_v2 = True
        for slot in room.human_slots():
            engine.set_player_faction(slot.faction_id)
            break
    except Exception as e:
        logger.warning(f"GameEngine init failed: {e}, using bare QuarterlyResolver")
        resolver = QuarterlyResolver()
        result = resolver.resolve(room, ws, decisions, llm=llm)
        # Still save state to DB
        _save_v3_state_to_db(room, ws, decisions, result, old_state)
        return result

    resolver = QuarterlyResolver(
        intent_parser=getattr(engine, "_macro_parser", None),
        turn_controller=getattr(engine, "turn_controller", None),
        history_engine=getattr(engine, "history_engine", None),
        macro_policy_engine=getattr(engine, "_macro_sim", None),
        narrative_engine=getattr(engine, "narrative_engine", None),
        black_swan_injector=getattr(engine, "_black_swan", None),
        guardrail_validator=getattr(engine, "guardrail_validator", None),
        state_applier=getattr(engine, "state_applier", None),
    )
    result = resolver.resolve(room, ws, decisions, llm=llm)
    _save_v3_state_to_db(room, ws, decisions, result, old_state)
    return result


def _save_v3_state_to_db(room, ws, decisions, result, old_state: dict):
    """将 V3 仿真结果写入 game_state + turn_delta 表。"""
    try:
        from histrategy.db.models import save_game_state, save_turn_delta

        for fid, faction in ws.factions.items():
            if not faction.is_active:
                continue

            # 城池列表
            territories_list = []
            for tid in faction.territories:
                t = ws.territories.get(tid)
                territories_list.append(
                    {"id": tid, "name": t.name if t else tid}
                )

            # 写入 game_state
            save_game_state(
                room_id=room.id,
                quarter_number=room.quarter_number,
                faction_id=fid,
                population=getattr(faction, "population", 0),
                troops=getattr(faction, "strength_actual", 0),
                food=faction.food,
                treasury=faction.treasury,
                morale=getattr(faction, "morale_actual", 50),
                territories=territories_list,
                policies=getattr(faction, "policies", {}),
                is_active=faction.is_active,
            )

            # 写入 turn_delta（五项）
            if fid not in old_state:
                continue
            old = old_state[fid]
            delta_map = [
                ("population", old.get("population", 0), getattr(faction, "population", 0)),
                ("troops", old.get("troops", 0), getattr(faction, "strength_actual", 0)),
                ("food", old.get("food", 0), faction.food),
                ("treasury", old.get("treasury", 0), faction.treasury),
                ("morale", old.get("morale", 50), getattr(faction, "morale_actual", 50)),
            ]
            for delta_type, old_val, new_val in delta_map:
                if old_val == new_val:
                    continue
                save_turn_delta(
                    room_id=room.id,
                    quarter_number=room.quarter_number,
                    faction_id=fid,
                    delta_type=delta_type,
                    old_value=old_val,
                    new_value=new_val,
                    reason="V3 hybrid simulation",
                    source="llm",
                )
    except Exception as e:
        logger.warning(f"V3 DB save failed (non-fatal): {e}")


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

        fd = {
            fid: {"decision": dr.decision_text, "commands": dr.commands, "source": dr.source}
            for fid, dr in decisions.items()
        }
        save_quarter_turn(
            room.id,
            room.quarter_number,
            room.year,
            room.season,
            faction_decisions=fd,
            narratives=result.narratives,
            state_changes=result.state_changes,
        )
    except Exception as e:
        logger.warning(f"Quarter save failed: {e}")


def _write_backup(room, ws_dict):
    try:
        from histrategy.db.file_backup import cleanup_old_backups, write_room_snapshot

        write_room_snapshot(room, ws_dict, "quarter_complete")
        cleanup_old_backups(room.id, keep=20)
    except Exception:
        pass
