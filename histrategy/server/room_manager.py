"""
RoomManager — 多人游戏房间管理（v3: 纯势力模型）。

核心简化：
  - histrategy 不追踪 user_id / host_user_id —— 身份由 orchestrator 代理层处理。
  - 房间创建时通过 pre_assigned 指定势力分配，之后不可变。
  - 没有 enter_room / kick_player / pick_faction —— 势力在创建时固定。
  - 玩家通过 faction_id 识别（/mp?room=xxx&faction=cao）。

依赖方向：单边 orchestrator → histrategy。histrategy 绝不回调 orchestrator。
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger("histrategy.room_manager")

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom

# ── Billing exceptions ────────────────────────────────────────


class CreditInsufficientError(Exception):
    """Raised when user has insufficient credits for a turn."""

    pass


class RateLimitError(Exception):
    """Raised when user exceeds turn rate limit."""

    pass




def _try_save(room: GameRoom, ws_dict: dict | None = None):
    """Persist room to DB. Auto-extracts world_state dict if not provided."""
    import time as _t
    _t0 = _t.time()
    if ws_dict is None and room.world_state is not None and hasattr(room.world_state, "to_dict"):
        ws_dict = room.world_state.to_dict()
    try:
        from histrategy.db.models import save_room

        save_room(room, ws_dict)
    except Exception as e:
        logger.warning("[room=%s] Room save failed (non-fatal): %s", room.id, e)
    _elapsed = _t.time() - _t0
    if _elapsed > 0.5:
        print(f"DEBUG _try_save room={room.id} elapsed={_elapsed:.2f}s", flush=True)


# ── Room CRUD ────────────────────────────────────────


def create_room(
    scenario: str = "three-kingdoms",
    pre_assigned: dict[str, str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """创建房间并立即开始游戏。

    Host 预分配势力：pre_assigned = {"cao": "张三", "shu": "李四"}
    → 每个玩家获得专属链接 /mp?room=xxx&faction=cao
    → 未分配的势力自动变 AI NPC

    Returns:
        {"ok": True, "room_id": str, "player_links": [{faction, url}], ...}
    """
    from histrategy.engine.faction_slot import (
        create_ai_slot,
    )
    from histrategy.engine.game_room import GameRoom, RoomPhase

    # ── Build scenario-aware faction mapping ──
    use_fallback = scenario in ("", "three-kingdoms")
    if use_fallback:
        from histrategy.engine.faction_slot import (
            FACTION_DISPLAY_TO_ID,
            LLM_NPC_FACTIONS,
            PLAYABLE_FACTIONS,
        )

        faction_display_to_id: dict[str, str] = FACTION_DISPLAY_TO_ID
        fallback_npc_factions: list[str] = list(LLM_NPC_FACTIONS)
    else:
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(scenario)
        all_factions = loader.load_factions()
        # Build display_name → internal_id mapping (e.g. "屋大维" → "octavian")
        faction_display_to_id = {
            f.get("name", f.get("name_en", fid)): fid for fid, f in all_factions.items() if not f.get("npc_only", False)
        }
        fallback_npc_factions = list(faction_display_to_id.values())

    # 翻译显示名 → 内部 ID（caocao→cao, liubei→shu, sunquan→wu）
    # Host 预分配势力到具体玩家
    # Also map internal_id → itself for pre_assigned with internal format
    display_to_id = dict(faction_display_to_id)
    for fid in all_factions if not use_fallback else PLAYABLE_FACTIONS:
        if fid not in display_to_id:
            display_to_id[fid] = fid
    internal_map = {}
    for display_fid, player_name in pre_assigned.items():
        internal_fid = display_to_id.get(display_fid, display_fid)
        internal_map[internal_fid] = player_name
    internal_ids = list(internal_map.keys())

    if not internal_ids:
        internal_ids = ["cao", "shu", "wu"]

    room = GameRoom(
        scenario=scenario,
    )
    if metadata:
        room.metadata = metadata

    # 人类势力 → HUMAN（预分配）
    # 特殊处理：player_name == "AI" 的预分配势力应作为 AI 势力
    from histrategy.engine.faction_slot import create_ai_slot as _make_ai
    from histrategy.engine.faction_slot import create_human_slot

    player_links = []
    for fid in internal_ids:
        player_name = internal_map[fid]
        if player_name == "AI":
            # AI 标签 → 创建 AI slot，不占用人类槽位
            slot = _make_ai(fid)
            room.slots[fid] = slot
        else:
            # 预分配：直接设为 HUMAN。histrategy 不追踪 user_id
            slot = create_human_slot(fid, player_name)
            room.slots[fid] = slot
        # Use fid directly — frontend resolves display names from /api/scenarios
        display_fid = fid
        player_links.append(
            {
                "faction": display_fid,
                "player_name": player_name,
                "url": f"/mp?room={room.id}&faction={display_fid}",
            }
        )
        # 注册玩家

    # 未指定的势力 → AI NPC（从场景数据动态获取，只加载可扮演势力）
    try:
        if not use_fallback:
            # Already loaded all_factions above — reuse
            scenario_faction_ids = {fid for fid, f in all_factions.items() if not f.get("npc_only", False)}
        else:
            from histrategy.engine.scenario_loader import ScenarioLoader

            loader = ScenarioLoader(room.scenario)
            all_factions = loader.load_factions()
            scenario_faction_ids = {fid for fid, f in all_factions.items() if not f.get("npc_only", False)}
        # Major NPCs: all playable scenario factions not assigned to humans
        npc_factions = list(scenario_faction_ids - set(internal_ids))
    except Exception:
        # Fallback to hardcoded defaults
        npc_factions = fallback_npc_factions

    for fid in npc_factions:
        if fid not in room.slots:
            room.slots[fid] = create_ai_slot(fid)

    # npc_only factions (dead warlords, minor powers) are NOT added as AI slots.
    # They exist only as passive territory holders in initial_state.json for
    # historical accuracy — no LLM tokens, no narratives, no decisions.

    # Mark these as major NPCs for LLM decision generation
    room.major_npc_ids = set(npc_factions)

    # host 进入房间

    # 立即初始化世界状态并开始游戏
    _init_world_state(room)
    room.phase = RoomPhase.WAITING
    # AI NPC 马上开始生成决策 — 必须在 _try_save 之前，确保 NPC 决策持久化
    _trigger_npc_decisions(room)
    ws_dict = room.world_state.to_dict() if hasattr(room.world_state, "to_dict") else None
    _try_save(room, ws_dict)  # 传入 ws_dict 防止 DB 中 world_state 被写为 NULL
    _save_initial_state_to_db(room)  # 写入 game_state (quarter=0) — MUST be after _try_save (FK to game_room)

    # 返回显示名列表供前端展示（动态从场景数据获取）
    lang = getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"
    fnames = _get_faction_names(room, lang=lang)
    display_factions = [fnames.get(f, f) for f in internal_ids]

    result = {
        "ok": True,
        "room_id": room.id,
        "phase": "waiting",
        "human_factions": display_factions,
        "faction_names": fnames,
    }
    if player_links:
        result["player_links"] = player_links
    return result


def start_game(room_id: str) -> dict:
    """开始游戏。未选的势力自动变 AI。

    histrategy 是内部服务，auth 由 orchestrator 代理层处理。
    任何人可以通过 orchestrator 调用此接口开始游戏。

    Returns:
        {"ok": True, "phase": "waiting", "humans": [...], "ai_npcs": [...]}
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}
    if room.phase.value != "lobby":
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
    # NPC 立即下命令（不等人类提交）— 必须在 _try_save 之前，确保 NPC 决策持久化
    _trigger_npc_decisions(room)
    _try_save(room)

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


def submit_decision(room_id: str, faction_id: str, decision: str) -> dict:
    """提交本季度决策。全员提交后自动 resolve。

    histrategy 是内部服务，auth 由 orchestrator 代理层处理。
    身份由 faction_id 识别（不再需要 user_id）。
    """
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    if not faction_id:
        return {"ok": False, "error": "缺少 faction_id"}

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

    slot.submit_decision(decision)
    _try_save(room)

    submitted = [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()]
    pending = [fid for fid, s in room.slots.items() if s.is_active and not s.has_submitted()]

    if not pending:
        # 同步执行（调试用 — 若卡住请检查服务器日志）
        try:
            _resolve_and_advance(room)
        except CreditInsufficientError as exc:
            logger.warning("Room %s blocked: insufficient credits", room.id)
            return {"ok": False, "error": str(exc), "code": "insufficient_credits"}
        except RateLimitError as exc:
            logger.warning("Room %s blocked: rate limit", room.id)
            return {"ok": False, "error": str(exc), "code": "rate_limited"}
        except Exception as exc:
            logger.error("[room=%s] resolve failed: %s", room.id, exc)
            room.phase = type(room.phase).WAITING  # reset on error

    status = "resolving" if not pending else "waiting"
    return {
        "ok": True,
        "status": status,
        "submitted": submitted,
        "pending": pending,
        "is_public": getattr(room, "is_public", False),
    }


def get_room_status(room_id: str, faction_id: str | None = None) -> dict:
    """获取房间状态（含势力分配）。histrategy 不追踪 user_id。"""
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间不存在"}

    # Dynamic faction names from scenario data (not hardcoded Three Kingdoms)
    lang = getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"
    fnames = _get_faction_names(room, lang=lang)
    def _display(fid):
        return fnames.get(fid, fid)

    submitted = [_display(fid) for fid, s in room.slots.items() if s.is_active and s.has_submitted()]
    pending = [_display(fid) for fid, s in room.slots.items() if s.is_active and not s.has_submitted()]

    status = {
        "ok": True,
        "room_id": room.id,
        "scenario": getattr(room, "scenario", "") or "three-kingdoms",
        "phase": room.phase.value,
        "year": room.year,
        "season": room.season,
        "quarter": room.quarter_number,
        "faction_names": fnames,  # {internal_id: display_name} for orchestrator
        "players": {
            fid: {"role": "human", "display_name": s.display_name or fid}
            for fid, s in room.slots.items() if s.is_human()
        },
        "slots": {
            _display(fid): {
                "faction_id": _display(fid),
                "internal_id": fid,
                "occupant_type": s.occupant_type.value,
                "has_submitted": s.has_submitted(),
                "is_active": s.is_active,
            }
            for fid, s in room.slots.items()
        },
        "submitted": submitted,
        "pending": pending,
        "is_public": getattr(room, "is_public", False),
    }

    if faction_id:
        narratives = getattr(room, "_last_narratives", None) or {}
        npc_actions = getattr(room, "_last_npc_actions", None) or []
        # If room was reloaded from DB, restore _last_narratives and _last_npc_actions
        if not narratives or not npc_actions:
            try:
                from histrategy.db.models import get_quarter_turns as _gqt
                db_turns = _gqt(room.id, limit=1)
                if db_turns:
                    latest = db_turns[-1]
                    nr = latest.get("narratives")
                    loaded = _json.loads(nr) if isinstance(nr, str) else (nr or {})
                    if not narratives and loaded:
                        narratives = loaded
                        room._last_narratives = loaded
                    if not npc_actions and loaded:
                        nr2 = loaded.get("_npc_actions")
                        if isinstance(nr2, str):
                            npc_actions = _json.loads(nr2)
                        elif isinstance(nr2, list):
                            npc_actions = nr2
                        if npc_actions:
                            room._last_npc_actions = npc_actions
            except Exception:
                pass
        # Unified narrative (public, same for all factions)
        status["narrative"] = narratives.get("global", "") if narratives else ""
        if npc_actions:
            status["npc_actions"] = npc_actions

    # ── Return turn history for new-tab replay ──
    history = getattr(room, "_narrative_history", [])
    if not history:
        # Fallback: load from quarter_turn DB table (survives server restart)
        try:
            from histrategy.db.models import get_quarter_turns

            db_turns = get_quarter_turns(room.id, limit=20)
            for row in reversed(db_turns):
                narratives_raw = row.get("narratives")
                narratives = _json.loads(narratives_raw) if isinstance(narratives_raw, str) else (narratives_raw or {})
                history.append(
                    {
                        "quarter": row["quarter_number"],
                        "year": row.get("year", 207),
                        "season": row.get("season", "春"),
                        "narrative": narratives.get("global", ""),  # unified
                        "npc_decisions": _json.loads(narratives.get("_npc_actions", "[]"))
                        if isinstance(narratives.get("_npc_actions"), str)
                        else narratives.get("_npc_actions", []),
                    }
                )
            # Cache for subsequent calls
            room._narrative_history = history
        except Exception:
            pass
    if history:
        status["turns"] = history

    # ── Power ranking (from game_state table) ──
    try:
        from histrategy.db.models import get_latest_game_states

        raw_states = get_latest_game_states(room_id, room.quarter_number)

        # ── Get npc_only factions to exclude from ranking ──
        npc_only_ids = set()
        try:
            from histrategy.engine.scenario_loader import ScenarioLoader
            room = _get_room(room_id)
            if room:
                loader = ScenarioLoader(room.scenario)
                factions_raw = loader.load_factions()
                npc_only_ids = {fid for fid, f in factions_raw.items() if f.get("npc_only", False)}
        except Exception:
            pass

        ranking = []
        for row in raw_states:
            fid = row["faction_id"]
            if fid in npc_only_ids:
                continue  # Skip npc_only factions (e.g. sextus_pompey)
            # Composite score: troops + population/2 + treasury/1000 + morale/100
            composite = (
                (row.get("troops") or 0)
                + (row.get("population") or 0) / 2
                + (row.get("treasury") or 0) / 1000
                + (row.get("morale") or 0) / 100
            )
            ranking.append(
                {
                    "faction_id": fid,
                    "display_name": _display(fid),
                    "troops": row.get("troops", 0),
                    "population": row.get("population", 0),
                    "treasury": row.get("treasury", 0),
                    "territories": len(
                        _json.loads(row.get("territories", "[]"))
                        if isinstance(row.get("territories"), str)
                        else (row.get("territories") or [])
                    ),
                    "composite": round(composite, 1),
                    "is_active": bool(row.get("is_active", 1)),
                }
            )
        ranking.sort(key=lambda x: x["composite"], reverse=True)
        status["power_ranking"] = ranking
    except Exception:
        status["power_ranking"] = []

    # ── Territory ownership + population for sandbox map (real-time) ──
    # territory_owners: {city_id: faction_id} — live ownership, survives restart
    # territory_populations: {city_id: population} — per-city size for map labels
    try:
        from histrategy.db.models import get_latest_game_states

        territory_owners: dict[str, str] = {}
        territory_populations: dict[str, int] = {}

        # Use locally-captured quarter/scenario — `room` may have been
        # reassigned to None by the power-ranking block above.
        quarter_no = status.get("quarter", 0)
        scenario_id = status.get("scenario", "three-kingdoms")

        # 1. Live ownership from game_state rows (each faction's territory list).
        try:
            terr_states = get_latest_game_states(room_id, quarter_no)
        except Exception:
            terr_states = []
        for row in terr_states:
            fid = row["faction_id"]
            terrs = row.get("territories", "[]")
            terrs = _json.loads(terrs) if isinstance(terrs, str) else (terrs or [])
            for item in terrs:
                # territories are serialized as [{"id","name"}, ...] but may be
                # plain id strings in older rows — handle both.
                tid = item.get("id") if isinstance(item, dict) else item
                if tid:
                    territory_owners[tid] = fid

        # 2. Baseline per-city population + fallback owner from scenario data.
        #    Read territories.json via a CWD-relative path (like the characters
        #    endpoint). ScenarioLoader resolves relative to __file__, which
        #    breaks when the package is installed outside the CWD on prod.
        try:
            import os as _os

            terr_path = _os.path.join("scenarios", scenario_id, "knowledge", "territories.json")
            if not _os.path.exists(terr_path):
                terr_path = _os.path.join(
                    "scenarios", "three-kingdoms", "knowledge", "territories.json"
                )
            if _os.path.exists(terr_path):
                with open(terr_path, encoding="utf-8") as f:
                    terr_data = _json.load(f)
                for t in terr_data:
                    tid = t.get("id", "")
                    if not tid:
                        continue
                    pop = t.get("population", 0) or 0
                    if pop:
                        territory_populations[tid] = pop
                    # Fill owner for cities not yet in any faction's live list.
                    if tid not in territory_owners:
                        base_owner = t.get("owner_id", "") or ""
                        if base_owner:
                            territory_owners[tid] = base_owner
        except Exception:
            pass

        status["territory_owners"] = territory_owners
        status["territory_populations"] = territory_populations
    except Exception:
        status["territory_owners"] = {}
        status["territory_populations"] = {}

    return status


# ── Internal ─────────────────────────────────────────


def _load_repo_npc_decisions(scenario: str) -> dict | None:
    """Load pre-baked Q0 NPC decisions from repo.

    Looks for scenarios/{scenario}/npc_decisions_q0.json.
    Returns the parsed dict or None if not found.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scenarios", scenario, "npc_decisions_q0.json")
    if not os.path.isfile(path):
        return None
    try:
        return _json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"Failed to load repo NPC decisions for {scenario}")
        return None


def _trigger_npc_decisions(room: GameRoom):
    """在回合开始时立即为所有 AI NPC 生成决策。

    这样当人类玩家提交决策后，不需要等待 NPC LLM 调用——
    NPC 已经提前提交了决策，最后一个人类提交即可立即 resolve。

    Quarter 0 decisions are cached to disk to avoid redundant LLM calls
    on room creation (same initial state for each scenario).
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

    # Extract language from room metadata (default zh)
    lang = getattr(room, "metadata", {}).get("lang", "zh")
    # Normalize: room metadata uses "zh", pre-baked decisions use "zh"
    if lang and lang.startswith("zh"):
        lang = "zh"
    elif lang and lang.startswith("en"):
        lang = "en"

    # ── Quarter 0: check for pre-baked repo decisions ──
    if room.quarter_number == 0:
        repo_decisions = _load_repo_npc_decisions(room.scenario)
        if repo_decisions:
            decisions_data = repo_decisions.get("decisions", {})
            all_cached = True
            for fid in ai_only:
                faction_decisions = decisions_data.get(fid, {})
                lang_data = faction_decisions.get(lang)
                if lang_data and lang_data.get("decision_text"):
                    room.slots[fid].submit_decision(lang_data["decision_text"], lang_data.get("commands", []))
                else:
                    all_cached = False

            if all_cached:
                logger.info(f"Room {room.id}: NPC Q0 decisions loaded from repo — {list(ai_only.keys())}")
                return
            else:
                logger.warning(
                    f"Room {room.id}: Repo NPC decisions found but missing lang={lang} "
                    f"for some factions — falling through to LLM"
                )

    # 临时替换 room.slots 为只含 AI 的版本，避免 DecisionBus 等待人类
    # 使用 collect_all_decisions 为 AI 生成决策
    # 90s 超时：每个 NPC LLM 调用 60s 超时 + 30s buffer
    _NPC_TRIGGER_TIMEOUT = 90
    try:
        decisions = collect_all_decisions(
            room, ws, llm=llm, turn_memory=room.turn_summaries, lang=lang,
            timeout=_NPC_TRIGGER_TIMEOUT,
        )
        # 将 AI 决策写入对应的 slot
        for fid, dr in decisions.items():
            if fid in room.slots:
                room.slots[fid].submit_decision(dr.decision_text, dr.commands)
        logger.info(f"Room {room.id}: NPC decisions ready — {list(decisions.keys())}")
    except Exception as e:
        logger.error("[room=%s] NPC decision trigger failed: %s", room.id, e)


def _get_room(room_id: str) -> GameRoom | None:
    """Load room from database (no in-memory cache — survives pod restart)."""
    try:
        from histrategy.db.models import load_room

        room = load_room(room_id)
        if room:
            # 从 DB 恢复的房间如果处于 WAITING 阶段且有 AI NPC 未提交，
            # 需要立即触发 NPC 决策生成。
            # 正常情况下 NPC 决策已随 _resolve_and_advance 同步保存到 DB，
            # 此处只处理异常情况（如 pod 在 _resolve_and_advance 前崩溃）。
            ai_slots = [s for s in room.slots.values() if s.is_ai() and s.is_active]
            if room.phase.value == "waiting" and ai_slots:
                missing = [s.faction_id for s in ai_slots if not s.has_submitted()]
                if missing:
                    logger.info(
                        f"Room {room_id} loaded from DB (Q{room.quarter_number}), "
                        f"NPC decisions missing for {missing}, triggering generation"
                    )
                    _trigger_npc_decisions(room)
                else:
                    logger.debug(
                        f"Room {room_id} loaded from DB (Q{room.quarter_number}), "
                        f"NPC decisions already present for {[s.faction_id for s in ai_slots]}"
                    )
            return room
    except Exception:
        pass
    return None


def _init_world_state(room: GameRoom):
    from histrategy.engine.game import create_initial_world

    humans = [s for s in room.slots.values() if s.is_human()]
    player_faction = humans[0].faction_id if humans else "cao"

    # For non-default scenarios, use ScenarioLoader to pick up
    # scenario-specific factions and year
    if room.scenario and room.scenario not in ("three-kingdoms", ""):
        from histrategy.engine.scenario_loader import ScenarioLoader

        try:
            loader = ScenarioLoader(room.scenario)
            room.world_state = loader.build_world_state(player_faction)
            if room.world_state is not None:
                room.year = room.world_state.year
                room.season = (
                    str(room.world_state.season.value)
                    if hasattr(room.world_state.season, "value")
                    else str(room.world_state.season)
                )
            logger.info(
                "Scenario WorldState built: scenario=%s player=%s factions=%s year=%s",
                room.scenario,
                player_faction,
                list(room.world_state.factions.keys()) if room.world_state else "None",
                room.year if room.world_state else "N/A",
            )
            return
        except Exception as exc:
            logger.error(
                "Scenario WorldState build FAILED for scenario=%s player=%s — falling back to Three Kingdoms: %s",
                room.scenario,
                player_faction,
                exc,
                exc_info=True,
            )
            # Fall through to default Three Kingdoms create_initial_world()

    room.world_state = create_initial_world(player_faction, room.scenario or "three-kingdoms")
    if room.world_state is not None:
        room.year = getattr(room.world_state, "year", 207)
        # Old WorldState (v1) doesn't have 'season' — default to spring
        if hasattr(room.world_state, "season"):
            ws_season = room.world_state.season
            room.season = str(ws_season.value) if hasattr(ws_season, "value") else str(ws_season)
        else:
            room.season = "spring"

    # ── Override year from scenario.toml (allows Three Kingdoms 208 Spring start) ──
    try:
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(room.scenario or "three-kingdoms")
        meta = loader._toml.get("meta", {})
        if "start_year" in meta:
            room.year = meta["start_year"]
            if room.world_state:
                room.world_state.year = meta["start_year"]
    except Exception:
        pass  # Graceful: keep existing year if TOML parse fails

    # ── Defensive check: after fallback, verify slot factions exist in WorldState ──
    if room.world_state is not None and room.scenario not in ("", "three-kingdoms"):
        ws_factions = set(room.world_state.factions.keys()) if hasattr(room.world_state, "factions") else set()
        slot_factions = set(room.slots.keys())
        missing = slot_factions - ws_factions
        if missing:
            logger.warning(
                "Room %s: FACTION MISMATCH after fallback! scenario=%s, "
                "slot factions=%s, WorldState factions=%s, missing=%s. "
                "WorldState was built from wrong scenario data.",
                room.id,
                room.scenario,
                list(slot_factions),
                list(ws_factions),
                list(missing),
            )


def _save_initial_state_to_db(room: GameRoom):
    """写入所有势力的初始状态到 game_state 表 (quarter=0)。"""
    from histrategy.db.models import save_game_state

    ws = room.world_state
    if ws is None:
        return
    try:
        # 追踪所有已创建的 slot（人类 + AI NPC）
        tracked = set(room.slots.keys())

        for fid in tracked:
            faction = ws.factions.get(fid)
            if not faction:
                logger.warning(
                    "Room %s: slot faction '%s' not found in WorldState factions (%s) — "
                    "scenario=%s. WorldState was likely built from wrong scenario!",
                    room.id,
                    fid,
                    list(ws.factions.keys()),
                    room.scenario,
                )
                continue
            territories = []
            for tid in getattr(faction, "territories", []) or []:
                # faction.territories is list[str] (territory IDs)
                # Look up actual territory object from ws.territories
                tid_str = getattr(tid, "id", None) or str(tid)
                t_obj = ws.territories.get(tid_str) if hasattr(ws, "territories") else None
                territories.append(
                    {
                        "id": tid_str,
                        "name": getattr(t_obj, "name", tid_str) if t_obj else tid_str,
                        "population": getattr(t_obj, "population", 0) if t_obj else 0,
                        "development": getattr(t_obj, "development", 50) if t_obj else 50,
                    }
                )
            policies = {}
            for p in getattr(faction, "policies", []) or []:
                policies[getattr(p, "name", "unknown")] = {
                    "level": getattr(p, "level", 1),
                    "effect": getattr(p, "effect", ""),
                }
            # FactionState uses 'strength' not 'strength_actual' at creation time
            troops = (
                getattr(faction, "strength_actual", 0)
                or getattr(faction, "strength", 0)
                or getattr(faction, "troops", 0)
            )
            # Compute population from territory sum if faction has no population attr
            pop = getattr(faction, "population", 0)
            if pop == 0 and territories:
                pop = sum(t.get("population", 0) for t in territories)

            save_game_state(
                room_id=room.id,
                quarter_number=0,
                faction_id=fid,
                population=pop,
                troops=troops,
                food=getattr(faction, "food", 0),
                treasury=getattr(faction, "treasury", 0),
                morale=(getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50)),
                territories=territories,
                policies=policies,
                is_active=getattr(faction, "is_active", True),
            )
        logger.info(f"Saved initial state: {len(tracked)} factions → game_state (Q0, room={room.id})")
    except Exception as e:
        logger.warning("[room=%s] Failed to save initial state: %s", room.id, e)


# ── Rate limiting: per-room timestamps ──
_LAST_TURN_TIME: dict[str, float] = {}
_MIN_TURN_INTERVAL_SECONDS = 30


def _check_rate_limit(room_id: str) -> bool:
    """Prevent scripted abuse: minimum interval between turns for the same room."""
    now = time.time()
    last = _LAST_TURN_TIME.get(room_id, 0)
    if now - last < _MIN_TURN_INTERVAL_SECONDS:
        return False
    _LAST_TURN_TIME[room_id] = now
    return True


def _check_credit_before_turn(room) -> bool:
    """Credit check is handled by the orchestrator before calling histrategy.

    The dependency arrow is unilateral: orchestrator → histrategy.
    Histrategy does NOT call back to the orchestrator.
    Always returns True (fail-open).
    """
    return True


def _resolve_and_advance(room: GameRoom):
    from histrategy.engine.decision_bus import collect_all_decisions
    from histrategy.engine.engine_switch import EngineMode, detect_engine_mode
    from histrategy.engine.game_room import RoomPhase

    if room.phase.value == "resolving":
        return

    # ── Pre-turn credit check (blocks if insufficient balance) ──
    if not _check_credit_before_turn(room):
        room.phase = RoomPhase.WAITING  # Reset phase so user can retry later
        raise CreditInsufficientError(
            "余额不足，无法开始新回合。请充值后再试。\nInsufficient credits. Please top up and try again."
        )

    # ── Rate limit: minimum 30s between turns ──
    if not _check_rate_limit(room.id):
        room.phase = RoomPhase.WAITING
        raise RateLimitError("操作过快，请等待 30 秒后再试。\nToo fast. Please wait 30 seconds between turns.")

    room.phase = RoomPhase.RESOLVING
    ws = room.world_state
    if ws is None:
        room.advance_quarter()
        return

    engine_mode = detect_engine_mode()
    llm = _get_llm()
    lang = getattr(room, "metadata", {}).get("lang", "zh")
    # Set room context on adapter so all LLM calls in this turn are logged
    # and language is auto-enforced (no per-prompt hardcoding needed)
    if hasattr(llm, "set_room_context"):
        llm.set_room_context(room.id, room.quarter_number + 1, room.scenario, lang=lang)
    decisions = collect_all_decisions(room, ws, llm=llm, turn_memory=room.turn_summaries, lang=lang)

    # 根据引擎模式选择仿真器
    if engine_mode == EngineMode.V1:
        result = _resolve_v1(room, ws, decisions, llm)
    elif engine_mode == EngineMode.V2:
        result = _resolve_v2_or_v3(room, ws, decisions, llm, mode="v2")
    else:
        # V3 (merged V3+Macro)
        result = _resolve_v2_or_v3(room, ws, decisions, llm, mode="v3")

    room._last_narratives = result.narratives
    room._last_state_changes = getattr(result, "state_changes", {}) or {}
    npc_actions = []
    for fid, dr in decisions.items():
        if room.slots.get(fid) and room.slots[fid].is_ai():
            faction = ws.factions.get(fid) if ws else None
            if faction:
                if lang and lang.startswith("en") and getattr(faction, "name_en", ""):
                    name = faction.name_en
                else:
                    name = faction.name
            else:
                name = fid
            npc_actions.append(f"{name}: {dr.decision_text[:80]}")
    room._last_npc_actions = npc_actions
    # Embed npc_actions into narratives so they survive DB reload
    import json as _json_persist
    result.narratives["_npc_actions"] = _json_persist.dumps(npc_actions)

    # ── Accumulate narrative history for turn replay ──
    if not hasattr(room, "_narrative_history"):
        room._narrative_history = []
    # Store unified narrative (global key) + per-faction NPC decisions
    room._narrative_history.append(
        {
            "quarter": room.quarter_number + 1,  # upcoming quarter number
            "year": room.year,
            "season": room.season,
            "narrative": result.narratives.get("global", ""),  # unified, public
            "npc_decisions": {
                fid: dr.decision_text[:120]
                for fid, dr in decisions.items()
                if room.slots.get(fid) and room.slots[fid].is_ai()
            },  # private per faction
        }
    )
    # Keep last 20 turns in memory
    if len(room._narrative_history) > 20:
        room._narrative_history = room._narrative_history[-20:]

    if result.turn_summary:
        room.turn_summaries.append(result.turn_summary)
        if len(room.turn_summaries) > 8:
            room.turn_summaries = room.turn_summaries[-8:]

    # TurnController.execute_turn() already advances the season internally.
    # Do NOT call _advance_season(ws) here — it would double-advance.
    room.advance_quarter()

    # 同步 WorldState 的 year/season 到 room（否则网页永远显示初始值）
    if hasattr(ws, "year"):
        room.year = ws.year
    if hasattr(ws, "season"):
        room.season = ws.season.value if hasattr(ws.season, "value") else str(ws.season)
    elif hasattr(ws, "current_season"):
        # v1 WorldState uses season_index + current_season property
        room.season = ws.current_season

    room.world_state = ws

    # ── Persist the CURRENT turn's results synchronously (no LLM here) ──
    ws_dict = ws.to_dict() if hasattr(ws, "to_dict") else None
    _try_save(room, ws_dict)
    _save_quarter(room, decisions, result)
    _write_backup(room, ws_dict)

    # ── H31a-B2: pre-generate NEXT quarter's NPC decisions in the BACKGROUND ──
    # This is ~30-40s of LLM latency that used to block the /command response.
    # Moving it off the critical path lets it overlap with the human's
    # think-time (reading the narrative + typing the next decision).
    #
    # Race-safety (the reason a prior async attempt was reverted): the previous
    # version let the main thread's _try_save run BEFORE the worker submitted
    # decisions, persisting an empty NPC slot. Here the worker owns its OWN
    # _try_save AFTER submitting, so the DB always ends up with the decisions.
    # If a reload/command arrives before the worker finishes (or the pod
    # restarts), the _get_room safety net re-triggers synchronously — correct,
    # just without the speedup. Worst case == old behavior; best case saves ~30s.
    def _bg_pregen_next_npc(r, wsd):
        import time as _t

        _t0 = _t.time()
        try:
            _trigger_npc_decisions(r)
            _try_save(r, wsd)
            print(f"⏱ [room={r.id}] bg npc pre-gen {_t.time() - _t0:.1f}s", flush=True)
        except Exception as e:
            logger.warning("[room=%s] bg NPC pre-gen failed: %s", r.id, e)

    try:
        import os
        import threading

        # Run synchronously under pytest (daemon-thread DB writes race with the
        # shared test SQLite DB and cause flaky "database is locked" errors) or
        # when explicitly disabled. Async is the production default.
        _async_pregen = (
            os.environ.get("HISTRATEGY_NPC_PREGEN_ASYNC", "1") == "1"
            and not os.environ.get("PYTEST_CURRENT_TEST")
        )
        if _async_pregen:
            threading.Thread(
                target=_bg_pregen_next_npc, args=(room, ws_dict), daemon=True
            ).start()
        else:
            _trigger_npc_decisions(room)
            _try_save(room, ws_dict)
    except Exception as e:
        # If we can't spawn the thread, fall back to synchronous generation
        logger.warning("[room=%s] bg thread spawn failed, running sync: %s", room.id, e)
        _trigger_npc_decisions(room)
        _try_save(room, ws_dict)


def _capture_faction_state(ws) -> dict:
    """Capture pre-resolution state for turn_delta calculation.

    Returns {faction_id: {population, troops, food, treasury, morale, territories}}.
    """
    old_state = {}
    for fid in ws.factions:
        faction = ws.factions[fid]
        old_state[fid] = {
            "population": getattr(faction, "population", 0),
            "troops": getattr(faction, "strength_actual", 0),
            "food": faction.food,
            "treasury": faction.treasury,
            "morale": getattr(faction, "morale_actual", 50),
            "territories": list(getattr(faction, "territories", [])),
        }
    return old_state


def _resolve_v1(room, ws, decisions, llm):
    """V1 引擎：纯 LLM 仿真。"""
    import concurrent.futures

    from histrategy.engine.v1_simulator import V1Simulator, _apply_v1_state_to_world, detect_territory_changes, save_v1_state_to_db

    simulator = V1Simulator(llm)

    fd = {}
    for fid, dr in decisions.items():
        fd[fid] = {"decision": dr.decision_text, "commands": dr.commands, "source": dr.source}
    # Backfill from slots: ensure human decisions are preserved even if
    # DecisionResult objects lost their text during async collection
    for slot in room.human_slots():
        if slot.faction_id not in fd or not fd[slot.faction_id].get("decision"):
            decision_text = slot.pending_decision or ""
            commands = slot.pending_commands or []
            fd[slot.faction_id] = {"decision": decision_text, "commands": commands, "source": "human"}

    # Run V1 simulation with timeout.
    # V1 sends the full world state to the LLM in one call. deepseek-v4-flash
    # thinking mode can take 60-120s for complex multi-faction scenarios.
    # We use 130s with one retry before falling back to heuristic.
    # If the first attempt times out, retry once before falling back.
    _TIMEOUT = 130
    lang = getattr(room, "metadata", {}).get("lang", "zh")
    v1_result = None
    for attempt in (1, 2):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    simulator.simulate,
                    ws,
                    fd,
                    room.turn_summaries,
                    room_id=room.id,
                    quarter_number=room.quarter_number + 1,
                    scenario=room.scenario,
                    lang=lang,
                )
                v1_result = future.result(timeout=_TIMEOUT)
            break  # success
        except concurrent.futures.TimeoutError:
            if attempt == 1:
                logger.warning(
                    f"V1 simulate timed out after {_TIMEOUT}s for room {room.id} "
                    f"(attempt {attempt}/2), retrying..."
                )
            else:
                logger.warning(
                    f"V1 simulate timed out after {_TIMEOUT}s for room {room.id} "
                    f"(attempt {attempt}/2), falling back"
                )
                v1_result = simulator._fallback(ws, fd, lang=lang, reason="timeout")
        except Exception as e:
            logger.error(f"V1 simulate failed for room {room.id}: {e}, falling back")
            v1_result = simulator._fallback(ws, fd, lang=lang, reason="error")
            break

    # ── 先捕获旧状态（用于 turn_delta 计算）──
    old_state = _capture_faction_state(ws)
    v1_factions = v1_result.get("factions", {})
    state_changes = v1_result.get("state_changes", {})
    if not v1_factions and state_changes:
        # Rome scenario prompt uses "state_changes" (delta format) instead of
        # absolute "factions". Convert deltas to absolute values by applying
        # them to current WorldState. Fixes #64.
        for fid, delta in state_changes.items():
            faction = ws.factions.get(fid)
            if not faction or not faction.is_active:
                continue
            troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
            morale = getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50
            v1_factions[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": troops + delta.get("strength_delta", 0),
                "food": faction.food,
                "treasury": faction.treasury + delta.get("treasury_delta", 0),
                "morale": morale + delta.get("morale_delta", 0),
                "territories": [
                    {"id": t, "name": ws.territories[t].name if t in ws.territories else t} for t in faction.territories
                ],
                "policies": getattr(faction, "policies", {}),
                "is_active": True,
            }
        if v1_factions:
            logger.info(f"V1: converted state_changes→factions for {list(v1_factions.keys())} (Rome delta format)")
    if not v1_factions:
        # V1 prompt may use "state_changes" instead of "factions"
        # (e.g. rome-triumvirate). Use WorldState factions as fallback.
        for fid, faction in ws.factions.items():
            if not faction.is_active:
                continue
            old_state[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": getattr(faction, "strength_actual", 0),
                "food": faction.food,
                "treasury": faction.treasury,
                "morale": getattr(faction, "morale_actual", 50),
            }
    else:
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

    # ── Territory change narrative enhancement ──
    # Detect undocumented territory changes and append to narrative.
    # Fixes: cities silently changing hands without narrative explanation
    # (e.g. Q5→Q6 Chengdu/Xi'an disappearing without mention).
    try:
        raw_narrative = v1_result.get('narrative', '')
        enhanced = detect_territory_changes(
            old_state, v1_factions, ws, raw_narrative
        )
        if enhanced != raw_narrative:
            v1_result['narrative'] = enhanced
            logger.info(
                f'V1 territory narrative enhanced: '
                f'room={room.id} q={room.quarter_number + 1}'
            )
    except Exception as e:
        logger.warning(
            f'V1 territory check failed (non-fatal): {e}'
        )

    # 写入 DB（传入旧状态以计算 delta）
    # Note: room.quarter_number hasn't been incremented yet — save with next quarter
    save_v1_state_to_db(room.id, room.quarter_number + 1, ws, v1_result, old_state=old_state)

    # V1 does not use TurnController (which advances season for V2/V3).
    # Advance season AFTER saving so Q1 is recorded with the correct starting season
    # (e.g. Rome 44 BC starts in spring, Q1 should be spring, not summer).
    _advance_season(ws)

    # 构建兼容 result 对象并返回
    return _build_v1_result(room, ws, decisions, v1_result, fd, lang)


def _resolve_v2_or_v3(room, ws, decisions, llm, mode):
    """Resolve using QuarterlyResolver — V2 (deterministic) or V3 (LLM-augmented).

    V2: TurnController + IntentParser only (zero LLM).
    V3: Full engine stack (MacroPolicy, Narrative, BlackSwan, Guardrail, StateApplier).
    """
    from histrategy.engine.quarterly_resolver import QuarterlyResolver

    # ── Capture pre-resolution state ──
    old_state = _capture_faction_state(ws)

    # ── Create temporary GameEngine to access sub-engines ──
    try:
        import os

        from histrategy.engine.game import GameEngine

        if mode == "v3":
            os.environ.setdefault("HISTRATEGY_ENGINE", "v3")
        engine = GameEngine(scenario=room.scenario, new_game=True, llm=llm)
        engine.world_state_v2 = ws
        engine._use_v2 = True
        if mode == "v3":
            for slot in room.human_slots():
                engine.set_player_faction(slot.faction_id)
                break
    except Exception as e:
        logger.warning(f"GameEngine init for {mode.upper()} failed: {e}, using bare resolver")
        resolver = QuarterlyResolver()
        result = resolver.resolve(room, ws, decisions, llm=llm)
        _save_v3_state_to_db(room, ws, decisions, result, old_state)
        return result

    # ── Build resolver based on mode ──
    if mode == "v2":
        resolver = QuarterlyResolver(
            intent_parser=getattr(engine, "intent_parser", None),
            turn_controller=getattr(engine, "turn_controller", None),
        )
    else:  # v3
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
        # Override language from room metadata on all LLM engines
        lang = getattr(room, "metadata", {}).get("lang", "zh")
        if resolver.macro_policy_engine:
            resolver.macro_policy_engine.lang = lang
        if resolver.narrative_engine:
            resolver.narrative_engine.lang = lang

    result = resolver.resolve(room, ws, decisions, llm=llm)
    _save_v3_state_to_db(room, ws, decisions, result, old_state)
    return result


# ── V1 Result Builder ─────────────────────────────────────────────


@dataclass
class _V1Result:
    narratives: dict
    state_changes: dict
    turn_summary: dict | None
    faction_decisions: dict | None = None  # V1 pass-through for _save_quarter


def _build_v1_result(room, ws, decisions, v1_result, fd, lang):
    """Build unified narrative + battle summary + V1Result from LLM output.

    Uses a single global narrative for all factions (no per-faction duplication).
    """
    faction_narratives = v1_result.get("narratives", v1_result.get("faction_narratives", {}))
    global_narrative = v1_result.get("narrative", "")

    # Prefer explicit global narrative; fall back to first faction narrative or summary
    narratives = {}
    if global_narrative and global_narrative.strip():
        narratives["global"] = global_narrative
    else:
        # Build a unified summary from faction narratives
        parts = []
        fnames = _get_faction_names(room, lang=lang)
        for fid in decisions:
            fn = faction_narratives.get(fid, "")
            if fn and fn.strip():
                fname = fnames.get(fid, fid)
                bracket = "[]" if lang == "en" else "【】"
                parts.append(f"{bracket[0]}{fname}{bracket[1]}{fn[:200]}")
        if parts:
            narratives["global"] = "\n\n".join(parts)
        else:
            # Absolute fallback: basic state summary
            season_str = getattr(ws, "current_season", "?")
            yr = getattr(ws, "year", 207)
            summary_parts = []
            for fid in decisions:
                faction = ws.factions.get(fid)
                if faction:
                    troops = getattr(faction, "strength_actual", 0)
                    food = faction.food
                    territory_names = [ws.territories[tid].name for tid in faction.territories if tid in ws.territories]
                    territory_str = "、".join(territory_names[:3]) if territory_names else "无领地"
                    fname = fnames.get(fid, fid)
                    if lang != "en":
                        summary_parts.append(f"{fname}拥兵{troops:,}，积粟{food:,}斛，据{territory_str}")
                    else:
                        summary_parts.append(
                            f"{fname} commands {troops:,} troops, "
                            f"stores {food:,} grain, holds {territory_str}"
                        )
            if lang != "en":
                narratives["global"] = f"【{yr}年{season_str}】天下大势，" + "；".join(summary_parts) + "。"
            else:
                narratives["global"] = f"[{yr} {season_str}] " + "; ".join(summary_parts) + "."

    # Backward-compat: copy global to each faction
    global_text = narratives.get("global", "")
    for fid in decisions:
        narratives[fid] = global_text

    # Build battle summary for NPC reference
    battle_events = []
    for fid in decisions:
        dr = decisions.get(fid)
        if dr and dr.commands:
            for cmd in dr.commands:
                if isinstance(cmd, dict) and cmd.get("type") == "attack":
                    target = cmd.get("params", {}).get("target_territory", "?")
                    battle_events.append(f"{fid}→{target}")
    v1_battles = v1_result.get("battles", [])
    if v1_battles:
        for b in v1_battles[:3]:
            battle_events.append(f"{b.get('attacker','?')}⚔{b.get('defender','?')}@{b.get('location','')}")
    v1_events = v1_result.get("events", [])
    if v1_events and not battle_events:
        evt = v1_events[0]
        if isinstance(evt, str) and len(evt) < 60:
            battle_events.append(evt[:40])
    ts = v1_result.get("turn_summary", {})
    if isinstance(ts, dict):
        key_evt = ts.get("key_event", "")
        if key_evt and key_evt not in battle_events:
            battle_events.append(str(key_evt)[:40])
    battle_str = " | ".join(battle_events[:3]) if battle_events else ""

    season_str = getattr(ws, "current_season", "?")
    v1_summary = {
        "quarter": room.quarter_number + 1,
        "engine": "v1",
        "outcome_summary": (
            f"[{ws.year}年{season_str}] {battle_str or '各方休整'}"
            if battle_str
            else f"[{ws.year}年{season_str}] 各方休整，蓄力待发"
        ),
    }

    # Extract territory ownership from world state
    territory_owners = {}
    if hasattr(ws, "territories") and ws.territories:
        for tid, t in ws.territories.items():
            if hasattr(t, "owner_id"):
                territory_owners[tid] = t.owner_id or ""
            elif isinstance(t, dict):
                territory_owners[tid] = t.get("owner_id", "") or ""

    # Fallback: if ws.territories is empty (WorldState lost territory objects
    # during DB round-trip), rebuild territory_owners from faction territory lists.
    if not territory_owners:
        for fid in ws.factions:
            faction = ws.factions[fid]
            for tid in getattr(faction, "territories", []) or []:
                territory_owners[tid] = fid

    # Extract per-faction stats (population, troops, food, treasury, morale, navy)
    # Include ALL active factions (major from decisions + minor NPC factions)
    faction_stats = {}
    for fid in ws.factions:
        faction = ws.factions[fid]
        if not faction.is_active:
            continue
        stats = {
            "population": getattr(faction, "population", 0),
            "troops": getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0,
            "food": getattr(faction, "food", 0),
            "treasury": getattr(faction, "treasury", 0),
            "morale": getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50,
        }
        navy = getattr(faction, "navy", 0) or getattr(faction, "naval_strength", 0) or 0
        stats["navy"] = navy
        territories_list = getattr(faction, "territories", []) or []
        stats["territories"] = territories_list
        faction_stats[fid] = stats

    state_changes = {
        "territory_owners": territory_owners,
        "faction_stats": faction_stats,
    }

    return _V1Result(
        narratives=narratives,
        state_changes=state_changes,
        turn_summary=v1_summary,
        faction_decisions=fd,
    )


# ── DB Save Helpers ─────────────────────────────────────────────


def _safe_int(val, default=0):
    """Coerce value to int, returning default on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    """Coerce value to float, returning default on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _territories_to_list(ws, faction) -> list[dict]:
    """Serialize faction territories to [{id, name}] list."""
    result = []
    for tid in faction.territories:
        t = ws.territories.get(tid)
        result.append({"id": tid, "name": t.name if t else tid})
    return result


def _save_v3_state_to_db(room, ws, decisions, result, old_state: dict):
    """将 V3 仿真结果写入 game_state + policy_state + turn_delta 表。

    使用逐势力 try/except 保障：单个势力故障不影响其他势力持久化。
    """
    from histrategy.db.models import save_game_state, save_policy_state, save_turn_delta

    success_count = 0
    error_count = 0

    # quarter_number 策略：resolve 在 advance_quarter() 之前执行（见 resolve() line ~1014）。
    # room.quarter_number 是「即将过去的季度」。写入时使用 +1 表示「刚产出的新季度」。
    # 与 V1 save_v1_state_to_db 的 room.quarter_number + 1 策略一致。
    next_quarter = room.quarter_number + 1

    for fid, faction in ws.factions.items():
        try:
            if not faction.is_active:
                continue

            # ── 城池列表 ──
            territories_list = _territories_to_list(ws, faction)

            # ── 政策字典（输入验证） ──
            policies = getattr(faction, "policies", {}) or {}
            if not isinstance(policies, dict):
                logger.warning(
                    f"V3 DB save: policies is not a dict for {fid} "
                    f"(type={type(policies).__name__}), falling back to empty dict. "
                    f"room={room.id}"
                )
                policies = {}

            # ── 保存完整状态快照 (game_state) ──
            # 使用 quarter_number + 1：V1 一致策略。
            # resolve 在 advance_quarter() 之前执行，当前 quarter 尚未递增。
            # 写入的 quarter 是「这个 resolve 产出的数据对应的新季度」。
            next_quarter = room.quarter_number + 1

            # Compute population from territory objects (FactionState has no
            # native population field — it's derived from Territory.population)
            computed_population = _safe_int(getattr(faction, "population", 0))
            if computed_population == 0 and ws:
                computed_population = sum(
                    ws.territories[tid].population
                    for tid in getattr(faction, "territories", [])
                    if tid in ws.territories
                )

            save_game_state(
                room_id=room.id,
                quarter_number=next_quarter,
                faction_id=fid,
                population=computed_population,
                troops=_safe_int(getattr(faction, "strength_actual", 0)),
                food=_safe_float(faction.food),
                treasury=_safe_float(faction.treasury),
                morale=_safe_int(getattr(faction, "morale_actual", 50)),
                territories=territories_list if isinstance(territories_list, list) else [],
                policies=policies,
                is_active=bool(faction.is_active),
            )

            # ── 保存政策变更 (policy_state) ──
            if policies:
                for policy_name, policy_info in policies.items():
                    try:
                        if isinstance(policy_info, dict):
                            save_policy_state(
                                room_id=room.id,
                                quarter_number=next_quarter,
                                faction_id=fid,
                                policy_type=policy_info.get("type", "law"),
                                policy_name=policy_name,
                                policy_level=policy_info.get("level", 1),
                                params=policy_info.get("params", {}),
                                status=policy_info.get("status", "active"),
                            )
                    except Exception as policy_err:
                        logger.warning(
                            f"V3 DB save: policy_state failed for {fid}/{policy_name}: {policy_err}",
                            exc_info=True,
                        )

            # ── 保存五项增量 (turn_delta) ──
            if fid in old_state:
                try:
                    old = old_state[fid]
                    delta_map = [
                        (
                            "population",
                            _safe_int(old.get("population", 0)),
                            _safe_int(getattr(faction, "population", 0)),
                        ),
                        ("troops", _safe_int(old.get("troops", 0)), _safe_int(getattr(faction, "strength_actual", 0))),
                        ("food", _safe_float(old.get("food", 0)), _safe_float(faction.food)),
                        ("treasury", _safe_float(old.get("treasury", 0)), _safe_float(faction.treasury)),
                        ("morale", _safe_int(old.get("morale", 50)), _safe_int(getattr(faction, "morale_actual", 50))),
                    ]
                    for delta_type, old_val, new_val in delta_map:
                        if old_val == new_val:
                            continue
                        save_turn_delta(
                            room_id=room.id,
                            quarter_number=next_quarter,
                            faction_id=fid,
                            delta_type=delta_type,
                            old_value=old_val,
                            new_value=new_val,
                            reason="V3 hybrid simulation",
                            source="v3_hybrid",
                        )
                except Exception as delta_err:
                    logger.warning(
                        f"V3 DB save: turn_delta failed for {fid}: {delta_err}",
                        exc_info=True,
                    )

            success_count += 1

        except Exception as faction_err:
            error_count += 1
            logger.warning(
                f"V3 DB save failed for faction '{fid}': {faction_err}",
                exc_info=True,
            )

    if error_count > 0:
        logger.warning(
            f"V3 DB save: {success_count} factions saved, {error_count} failed. room={room.id} q={room.quarter_number}"
        )
    elif success_count > 0:
        logger.info(f"V3 DB save: {success_count} factions saved successfully. room={room.id} q={room.quarter_number}")


def _get_llm():
    try:
        from histrategy.llm.adapter import LLMAdapter

        return LLMAdapter()
    except Exception:
        return None


def _advance_season(ws):
    """Advance season by one step. Supports both WorldState versions.

    v2 (histrategy_engine): season is a Season enum member.
    v1 (histrategy.state):  season_index int + current_season property.
    """
    # Try v2 WorldState first (Season enum)
    try:
        from histrategy_engine.world import Season

        seasons = list(Season)
        idx = seasons.index(ws.season)
        ws.season = seasons[(idx + 1) % len(seasons)]
        if ws.season == seasons[0]:
            ws.year += 1
        ws.turn_number += 1
        return
    except (ValueError, IndexError, AttributeError):
        pass

    # Fallback: v1 WorldState (season_index + advance_turn)
    if hasattr(ws, "advance_turn"):
        ws.advance_turn()
    elif hasattr(ws, "season_index"):
        # Manual advance — advance_turn() does this but make it explicit
        ws.turn = getattr(ws, "turn", 0) + 1
        ws.season_index = (getattr(ws, "season_index", 0) + 1) % 4
        if ws.season_index == 0:
            ws.year = getattr(ws, "year", 207) + 1


def _save_quarter(room, decisions, result):
    try:
        from histrategy.db.models import save_quarter_turn

        fd = {
            fid: {"decision": dr.decision_text, "commands": dr.commands, "source": dr.source}
            for fid, dr in decisions.items()
        }
        # Fallback: if _resolve_v1 attached faction_decisions to result,
        # use it to backfill any empty human decisions (V1 pass-through fix)
        v1_fd = getattr(result, "faction_decisions", None)
        if v1_fd:
            for fid, entry in fd.items():
                if not entry["decision"] and fid in v1_fd:
                    entry["decision"] = v1_fd[fid].get("decision", "")
                    if not entry["commands"]:
                        entry["commands"] = v1_fd[fid].get("commands", [])
        # Collect per-turn token usage from llm_call_log
        token_usage = _collect_quarter_tokens(room.id, room.quarter_number)
        save_quarter_turn(
            room.id,
            room.quarter_number,
            room.year,
            room.season,
            faction_decisions=fd,
            narratives=result.narratives,
            state_changes=result.state_changes,
            token_usage=token_usage,
        )
    except Exception as e:
        logger.warning(f"Quarter save failed: {e}")


def _collect_quarter_tokens(room_id: str, quarter_number: int) -> dict | None:
    """Aggregate total_tokens from llm_call_log for a specific quarter."""
    try:
        from histrategy.db.connection import execute

        rows = execute(
            "SELECT SUM(total_tokens) as total, "
            "SUM(prompt_tokens) as prompt, "
            "SUM(completion_tokens) as completion, "
            "COUNT(*) as calls "
            "FROM llm_call_log "
            "WHERE room_id = ? AND quarter_number = ?",
            (room_id, quarter_number),
        )
        if rows and rows[0]["total"]:
            return {
                "total_tokens": rows[0]["total"],
                "prompt_tokens": rows[0]["prompt"],
                "completion_tokens": rows[0]["completion"],
                "llm_calls": rows[0]["calls"],
            }
    except Exception:
        pass
    return None


def _get_faction_names(room, lang: str = "zh") -> dict[str, str]:
    """Build {internal_id: display_name} for active room slots only.

    Only returns names for factions that are actually in the room's slots
    (human + active AI). Dead npc_only factions are excluded.
    When lang="en", returns English names (name_en) with Chinese fallback.
    """
    names: dict[str, str] = {}
    # Try scenario faction data first
    try:
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(room.scenario)
        all_factions = loader.load_factions()
        for fid in getattr(room, "slots", {}):
            f = all_factions.get(fid, {})
            if lang == "en":
                names[fid] = f.get("name_en", f.get("name", fid))
            else:
                names[fid] = f.get("name", f.get("name_en", fid))
    except Exception:
        pass
    # Fallback: derive from room slots + world_state
    ws = getattr(room, "world_state", None)
    if ws:
        for fid in getattr(room, "slots", {}):
            if fid not in names:
                faction = ws.factions.get(fid) if hasattr(ws, "factions") else None
                if faction:
                    names[fid] = getattr(faction, "name", fid)
    # Ensure all room slots have names
    for fid in getattr(room, "slots", {}):
        if fid not in names:
            names[fid] = fid
    return names


def _write_backup(room, ws_dict):
    try:
        from histrategy.db.file_backup import cleanup_old_backups, write_room_snapshot

        write_room_snapshot(room, ws_dict, "quarter_complete")
        cleanup_old_backups(room.id, keep=20)
    except Exception:
        pass


# ── Single-Player API Helpers ────────────────────────────────────
# Shared between single_player.py and api.py.
# These operate on GameRoom + WorldState, producing the response shape
# expected by the frontend (GameCreatedResponse / CommandResponse format).



def _compute_navy(ws, faction_id: str) -> int:
    """Compute total navy (trireme/naval) units for a faction from WorldState armies."""
    navy = 0
    try:
        for army in getattr(ws, "armies", {}).values():
            if getattr(army, "faction_id", "") == faction_id:
                for unit_type, count in getattr(army, "units", {}).items():
                    unit_str = str(unit_type).lower() if hasattr(unit_type, "lower") else str(unit_type)
                    if "trireme" in unit_str or "navy" in unit_str or "naval" in unit_str:
                        navy += count
    except Exception:
        pass  # Old WorldState may not have armies
    return navy

def build_faction_status_for_api(room, faction_id: str) -> dict:
    """Build faction_status dict from GameRoom for API responses."""
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
        if ws and hasattr(ws, "territories"):
            t_obj = ws.territories.get(tid_str)
            if t_obj:
                pop_sum += getattr(t_obj, "population", 0) or 0

    # Fallback: if territories dict is empty (old WorldState doesn't
    # survive to_dict/from_dict round-trip), read population from game_state table.
    # Also triggers when faction has territories in WS but no population sum
    # (territories survived but population field is 0).
    # AND triggers when faction has NO territories (pop_sum==0, territories==[])
    # — use the last known population from game_state.
    if pop_sum == 0:
        try:
            from histrategy.db.models import get_latest_game_states

            raw_states = get_latest_game_states(room.id, room.quarter_number)
            for row in raw_states:
                if row.get("faction_id") == faction_id:
                    pop_sum = row.get("population", 0) or 0
                    break
        except Exception:
            pass

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
        "navy": _compute_navy(ws, faction_id),
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
    }


def build_aftermath_text(faction_status: dict, lang: str = "zh") -> str:
    """Build aftermath summary string from faction status."""
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


def extract_turn_events(room) -> list[str]:
    """Extract historical events from the room's turn summaries."""
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


# ── I18n: generic suggestion strings (no longer inline) ────────────
_GENERIC_SUGGESTIONS = {
    "zh": {
        "low_food": "粮草不足，宜发展农业、推行屯田",
        "low_treasury": "资金短缺，宜降低开支、发展商业",
        "low_morale": "民心不稳，宜减轻赋税、安抚百姓",
        "low_strength": "兵力薄弱，宜招募新兵、训练士卒",
        "small_territory": "领地狭小，宜伺机扩张",
        "defaults": [
            "召开朝会听取谋士建议",
            "派遣细作探查邻国动向",
            "发展科技树解锁新政",
        ],
        "intro_choices": ["发展内政", "对外用兵", "广纳贤才", "休养生息"],
    },
    "en": {
        "low_food": "Low food — develop agriculture, establish supply lines",
        "low_treasury": "Low treasury — cut spending, develop trade",
        "low_morale": "Low morale — reduce taxes, appease the people",
        "low_strength": "Low troops — recruit soldiers, train forces",
        "small_territory": "Small territory — seek expansion opportunities",
        "defaults": [
            "Hold council for strategic advice",
            "Send spies to assess rivals",
            "Develop new technologies",
        ],
        "intro_choices": ["Develop Economy", "Military Action", "Recruit Talent", "Consolidate"],
    },
}


def _try_early_suggestions(scenario: str, faction_id: str, turn: int, lang: str) -> list[str]:
    """Try to resolve per-scenario early-turn suggestions, silences all errors."""
    try:
        from histrategy.engine.intro_plan import _resolve_early_suggestions  # noqa: F811
        return _resolve_early_suggestions(scenario, faction_id, turn, lang) or []
    except Exception:
        return []


def build_strategic_suggestions(room, faction_id: str, lang: str = "zh") -> list[str]:
    """Generate strategic suggestions based on faction state.

    Turns 1-4: deterministic per-scenario suggestions from EARLY_TURNS_SUGGESTIONS.
    Turn 5+: heuristic based on faction resources.
    """
    i18n = _GENERIC_SUGGESTIONS.get(lang, _GENERIC_SUGGESTIONS["zh"])
    # Use NEXT turn number (quarter_number is the last COMPLETED turn)
    turn = (room.quarter_number or 0) + 1
    scenario = getattr(room, "scenario", "three-kingdoms")

    if 1 <= turn <= 4:
        early = _try_early_suggestions(scenario, faction_id, turn, lang)
        if early:
            return early[:4]

    # ── Heuristic fallback (turn 5+) ──
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None
    suggestions = []

    if faction:
        checks = [
            ("low_food", lambda f: (getattr(f, "food", 0) or 0) < 5000),
            ("low_treasury", lambda f: (getattr(f, "treasury", 0) or 0) < 5000),
            ("low_morale", lambda f: (getattr(f, "morale_actual", 50) or 50) < 40),
            ("low_strength", lambda f: (getattr(f, "strength_actual", 0) or 0) < 5000),
        ]
        for key, check in checks:
            if check(faction):
                suggestions.append(i18n[key])

        territories = len(getattr(faction, "territories", []) or [])
        if territories <= 1:
            suggestions.append(i18n["small_territory"])

    # Fill with generic defaults if short
    defaults = i18n["defaults"]
    for d in defaults:
        if d not in suggestions:
            suggestions.append(d)
        if len(suggestions) >= 3:
            break

    return suggestions[:3]


def build_single_player_intro(room, faction_id: str, language_style: str, lang: str = "zh") -> dict:
    """Build the intro scene for a single-player game.

    Returns the old IntroScene format expected by the frontend.
    """
    from histrategy.server.intro_narratives import INTRO_NARRATIVES_EN, INTRO_NARRATIVES_ZH

    if lang == "en" and faction_id in INTRO_NARRATIVES_EN:
        narrative = INTRO_NARRATIVES_EN[faction_id]
    else:
        faction_narratives = INTRO_NARRATIVES_ZH.get(faction_id, {})
        narrative = faction_narratives.get(language_style, faction_narratives.get("vernacular", ""))
        if not narrative:
            narrative = f"历史进入了关键的时刻。你将以{faction_id}势力的身份，在这乱世中书写自己的篇章。"

    scenario = getattr(room, "scenario", "three-kingdoms")
    new_choices = _try_early_suggestions(scenario, faction_id, 1, lang)
    if not new_choices:
        i18n = _GENERIC_SUGGESTIONS.get(lang, _GENERIC_SUGGESTIONS["zh"])
        new_choices = i18n["intro_choices"]

    return {
        "narrative": narrative,
        "npc_actions": [],
        "new_choices": new_choices[:4],
        "state_changes": {},
        "events_occurred": [],
    }
