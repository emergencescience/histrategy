"""
RoomManager — 多人游戏房间管理（v3: 纯势力模型）。

核心简化：
  - histrategy 通过 host_user_id 追踪房间创建者（由 orchestrator 代理层 X-User-Id 注入）。
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





def detect_device_type(user_agent: str) -> str:
    """Parse User-Agent header to classify device type.

    Returns one of: 'mobile', 'tablet', 'desktop', 'unknown'
    """
    ua = user_agent.lower()
    if not ua:
        return "unknown"
    # Tablets
    if any(k in ua for k in ("ipad", "tablet", "playbook", "silk")):
        return "tablet"
    # Mobile
    if any(k in ua for k in ("mobi", "android", "iphone", "ipod", "blackberry", "opera mini", "iemobile")):
        return "mobile"
    # Desktop
    return "desktop"


def detect_browser(user_agent: str) -> str:
    """Parse User-Agent to identify the browser brand.

    Returns one of: 'chrome', 'safari', 'firefox', 'edge', 'wechat', 'unknown'
    """
    ua = user_agent.lower() if user_agent else ""
    if not ua:
        return "unknown"
    if "micromessenger" in ua:
        return "wechat"
    if "edg/" in ua or "edge/" in ua:
        return "edge"
    if "chrome/" in ua and "safari/" in ua:
        return "chrome"
    if "safari/" in ua and "chrome/" not in ua:
        return "safari"
    if "firefox/" in ua:
        return "firefox"
    return "unknown"


# Re-export from db.models — single canonical implementation shared by
# save_room/_try_save/create_room/_resolve_and_advance.
from histrategy.db.models import _serialize_world_state  # noqa: F401


def _try_save(room: GameRoom, ws_dict: dict | None = None):
    """Persist room to DB. Auto-extracts world_state dict if not provided."""
    import time as _t
    _t0 = _t.time()
    if ws_dict is None and room.world_state is not None:
        ws_dict = _serialize_world_state(room.world_state)
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
    host_user_id: str = "",
) -> dict:
    """创建房间并立即开始游戏。

    Host 预分配势力：pre_assigned = {"cao": "张三", "shu": "李四"}
    → 每个玩家获得专属链接 /mp?room=xxx&faction=cao
    → 未分配的势力自动变 AI NPC
    host_user_id 由 orchestrator 代理层的 X-User-Id 注入。

    Returns:
        {"ok": True, "room_id": str, "player_links": [{faction, url}], ...}
    """
    import time as _cr_time
    _cr_t0 = _cr_time.time()
    _cr_timings: dict[str, float] = {}
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
    if host_user_id:
        room.host_user_id = host_user_id
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
    except Exception as e:
        # Fallback to hardcoded defaults
        logger.warning("[create_room] NPC faction resolution failed, using fallback: %s", e)
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
    _cr_t1 = _cr_time.time()
    _init_world_state(room)
    _cr_timings["init_world"] = _cr_time.time() - _cr_t1
    room.phase = RoomPhase.WAITING
    # NPC decisions are deferred to the first turn cycle — no blocking LLM calls during room creation
    ws_dict = _serialize_world_state(room.world_state)
    _cr_t2 = _cr_time.time()
    _try_save(room, ws_dict)  # 传入 ws_dict 防止 DB 中 world_state 被写为 NULL
    _cr_timings["try_save"] = _cr_time.time() - _cr_t2
    _cr_t3 = _cr_time.time()
    _save_initial_state_to_db(room)  # 写入 game_state (quarter=0) — MUST be after _try_save (FK to game_room)
    _cr_timings["init_state"] = _cr_time.time() - _cr_t3

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

    # ── Profiling: log create_room timing breakdown ──
    _cr_total = _cr_time.time() - _cr_t0
    _cr_timings["total"] = _cr_total
    _cr_timings["other"] = _cr_total - sum(v for k, v in _cr_timings.items() if k != "total")
    print(f"DEBUG create_room room={room.id} scenario={scenario} "
          f"timings={_cr_timings} total={_cr_total:.2f}s", flush=True)
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


def _streaming_enabled() -> bool:
    """Whether the server runs in streaming mode (HISTRATEGY_STREAMING=1).

    Streaming mode: command() returns after state settles (skip narrative),
    and narrative-live-stream generates + streams the chronicle afterward.
    Completion mode (default): command() runs the full resolve incl. narrative
    and returns everything at once — backward-compatible for library/CLI use.
    """
    import os as _os

    return _os.environ.get("HISTRATEGY_STREAMING", "").strip() in ("1", "true", "True", "yes")


def submit_decision(room_id: str, faction_id: str, decision: str, skip_narrative: bool = False) -> dict:
    """提交本季度决策。全员提交后自动 resolve。

    histrategy 是内部服务，auth 由 orchestrator 代理层处理。
    身份由 faction_id 识别（不再需要 user_id）。

    Args:
        skip_narrative: 流式模式下跳过叙事生成（见 _streaming_enabled）。
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

    # ── Parse human free-text into structured commands ──
    # The V3 QuarterlyResolver parses commands at resolution time (line 105 of
    # quarterly_resolver.py), but those parsed commands are never persisted back
    # to the slot.  This means the turn API always returns commands=[] for human
    # factions, making it impossible for players to see what the engine understood
    # from their orders.  Parse here at submit time so commands are visible in the
    # API and stored in the quarter_turn record.
    try:
        from histrategy.parser.intent import IntentParser
        llm = _get_llm()  # V3: use LLM for intent parsing; falls back to keyword if unavailable
        parser = IntentParser(llm_adapter=llm, scenario=room.scenario)
        parsed = parser.parse(decision, faction_id)
        if parsed:
            slot.pending_commands = [c.to_dict() if hasattr(c, 'to_dict') else c for c in parsed]
        # ── Log intent parse for debug traceability ──
        try:
            import json as _json
            from histrategy.db.models import log_llm_call
            log_llm_call(
                room_id=room.id,
                quarter_number=room.quarter_number,
                call_type="policy_parse",
                provider="keyword_parser",
                model="keyword",
                prompt_tokens=0,
                completion_tokens=len(_json.dumps(parsed, ensure_ascii=False)) if parsed else 0,
                total_tokens=len(_json.dumps(parsed, ensure_ascii=False)) if parsed else 0,
                latency_ms=0,
                user_prompt=decision,
                response=_json.dumps([c.to_dict() if hasattr(c, 'to_dict') else c for c in parsed], ensure_ascii=False) if parsed else "[]",
                faction_id=faction_id,
            )
        except Exception as _log_err:
            pass  # non-critical
    except Exception as parse_err:
        logger.warning(f"Intent parse failed for {faction_id}: {parse_err}")
    _try_save(room)

    submitted = [fid for fid, s in room.slots.items() if s.is_active and s.has_submitted()]
    pending = [fid for fid, s in room.slots.items() if s.is_active and not s.has_submitted()]

    if not pending:
        # 同步执行（调试用 — 若卡住请检查服务器日志）
        try:
            _resolve_and_advance(room, skip_narrative=skip_narrative)
        except CreditInsufficientError as exc:
            logger.warning("Room %s blocked: insufficient credits", room.id)
            return {"ok": False, "error": str(exc), "code": "insufficient_credits"}
        except RateLimitError as exc:
            logger.warning("Room %s blocked: rate limit", room.id)
            return {"ok": False, "error": str(exc), "code": "rate_limited"}
        except Exception as exc:
            logger.exception("[room=%s] resolve failed: %s", room.id, exc)
            room.phase = type(room.phase).WAITING  # reset on error

    status = "resolving" if not pending else "waiting"
    return {
        "ok": True,
        "status": status,
        "submitted": submitted,
        "pending": pending,
        "is_public": getattr(room, "is_public", False),
    }


def stream_and_persist_narrative(room):
    """Generator: stream the deferred narrative for a room's latest quarter,
    then persist it to the quarter_turn row. Used by narrative-live-stream (SSE).

    Streaming mode flow: command() settled state + stashed narrative context on
    the room (_pending_narrative_ctx). This generator regenerates the chronicle
    via the narrative engine's streaming API, yields chunks as they arrive, and
    on completion writes the full text back to the DB (+ in-memory caches) so
    page reloads and the shared page can replay it.

    Fallbacks:
      - No stash (pod restart / already generated): if the DB already has a
        global narrative, replay it in one chunk; else yield an offline chronicle.
      - LLM failure mid-stream: yield the offline chronicle.
    """
    import json as _json

    stashed = _pop_narrative_context(room.id)
    ctx = stashed.get("ctx") if stashed else None
    quarter = stashed.get("quarter") if stashed else room.quarter_number
    ws = room.world_state
    lang = getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"

    logger.info(
        "[room=%s] narrative-live-stream: stash=%s quarter=%d ws=%s",
        room.id, "AVAILABLE" if ctx else "MISSING", quarter, "AVAILABLE" if ws else "MISSING",
    )

    # ── No stashed context: try to generate narrative from DB data ──
    if not ctx or not ws:
        cached = ""
        faction_decisions = {}
        try:
            from histrategy.db.models import get_quarter_turns as _gqt

            db_turns = _gqt(room.id, limit=1)
            if db_turns:
                nr = db_turns[-1].get("narratives")
                loaded = _json.loads(nr) if isinstance(nr, str) else (nr or {})
                cached = loaded.get("global", "") if isinstance(loaded, dict) else ""
                # Try to extract faction decisions from quarter_turn for fresh generation
                fd_raw = db_turns[-1].get("faction_decisions")
                if fd_raw:
                    fd_loaded = _json.loads(fd_raw) if isinstance(fd_raw, str) else (fd_raw or {})
                    if isinstance(fd_loaded, dict):
                        for fid, data in fd_loaded.items():
                            if isinstance(data, dict):
                                faction_decisions[fid] = data.get("decision", "")
                            elif isinstance(data, str):
                                faction_decisions[fid] = data
        except Exception:
            cached = ""

        # If we have cached narrative, replay it (backward compat)
        if cached and cached.strip():
            for para in cached.split("\n"):
                if para.strip():
                    yield para
            return

        # If we have world_state + faction decisions, try to generate fresh
        if ws and faction_decisions:
            logger.info(
                "[room=%s] narrative-live-stream: stash MISSING, generating from DB data",
                room.id,
            )
            # Build a narrative engine and generate fresh
            llm = _get_llm()
            narrative_engine = None
            try:
                from histrategy.llm.narrative import NarrativeEngine
                narrative_engine = NarrativeEngine(
                    llm_adapter=llm, language=lang, scenario=getattr(room, "scenario", "")
                )
            except Exception as e:
                logger.warning("[room=%s] NarrativeEngine init failed: %s", room.id, e)

            chunks: list[str] = []
            if narrative_engine:
                try:
                    for chunk in narrative_engine.generate_global_narrative_stream(
                        ws=ws,
                        faction_decisions=faction_decisions,
                        baseline=None,
                        macro_delta=None,
                        history_events=None,
                        room_id=room.id,
                        scenario=getattr(room, "scenario", ""),
                    ):
                        if chunk:
                            chunks.append(chunk)
                            yield chunk
                except Exception as e:
                    logger.error(
                        "[room=%s] Fallback narrative stream failed: %s",
                    )

            full = "".join(chunks).strip()
            if not full and narrative_engine:
                try:
                    full = narrative_engine._offline_global_narrative(ws, faction_decisions)
                except Exception:
                    full = ""
                if full:
                    yield full

            # Persist the generated narrative
            if full:
                try:
                    from histrategy.db.models import update_quarter_turn_narratives

                    narratives = {fid: full for fid in faction_decisions}
                    narratives["global"] = full
                    update_quarter_turn_narratives(room.id, quarter, narratives)
                except Exception as e:
                    logger.warning("[room=%s] Narrative DB persist failed: %s", room.id, e)
            return

        # No stashed context, no cached narrative, no world_state to generate from.
        # ── Poll DB: the background thread (_bg_generate_narrative) may still be
        #     generating the narrative. Instead of immediately returning a fallback
        #     that makes the user think the command failed, poll every 2s for up to
        #     30s until the narrative appears in the DB. ──
        poll_attempts = 0
        max_poll_attempts = 15  # 15 × 2s = 30s max
        while poll_attempts < max_poll_attempts:
            poll_attempts += 1
            import time as _poll_t
            _poll_t.sleep(2)
            try:
                from histrategy.db.models import get_quarter_turns as _gqt_poll
                db_turns_poll = _gqt_poll(room.id, limit=1)
                if db_turns_poll:
                    nr_poll = db_turns_poll[-1].get("narratives")
                    loaded_poll = _json.loads(nr_poll) if isinstance(nr_poll, str) else (nr_poll or {})
                    cached_poll = loaded_poll.get("global", "") if isinstance(loaded_poll, dict) else ""
                    if cached_poll and cached_poll.strip():
                        logger.info(
                            "[room=%s] narrative-live-stream: narrative appeared in DB after %d polls (%.1fs)",
                            room.id, poll_attempts, poll_attempts * 2.0,
                        )
                        for para in cached_poll.split("\n"):
                            if para.strip():
                                yield para
                        return
            except Exception:
                pass
        # Exhausted all polls — genuinely no narrative available.
        fallback = (
            "本回合尚未推演完成，请刷新页面查看最新状态。若问题持续，请重新下达政令。"
            if lang == "zh"
            else "This turn has not been resolved yet. Please refresh the page. If the problem persists, please re-issue your command."
        )
        yield fallback
        return

    # ── Build a narrative engine (transient — not stored on room) ──
    llm = _get_llm()
    narrative_engine = None
    try:
        from histrategy.engine.game import GameEngine

        engine = GameEngine(scenario=room.scenario, new_game=True, llm=llm)
        narrative_engine = getattr(engine, "narrative_engine", None)
        if narrative_engine:
            narrative_engine.lang = lang
    except Exception as e:
        logger.warning(f"[room={room.id}] narrative engine init failed: {e}")
        narrative_engine = None

    # Fallback: construct a standalone NarrativeEngine (works offline too — its
    # _offline_global_narrative needs no LLM). Ensures the stream always yields.
    if narrative_engine is None:
        try:
            from histrategy.llm.narrative import NarrativeEngine

            narrative_engine = NarrativeEngine(
                llm_adapter=llm, language=lang, scenario=getattr(room, "scenario", "")
            )
        except Exception as e:
            logger.warning(f"[room={room.id}] standalone NarrativeEngine failed: {e}")
            narrative_engine = None

    chunks: list[str] = []
    if narrative_engine:
        try:
            for chunk in narrative_engine.generate_global_narrative_stream(
                ws=ws,
                faction_decisions=ctx.get("all_decisions", {}) or {},
                baseline=ctx.get("baseline"),
                macro_delta=ctx.get("macro_delta"),
                history_events=ctx.get("history_events"),
                room_id=room.id,
                scenario=getattr(room, "scenario", ""),
            ):
                if chunk:
                    chunks.append(chunk)
                    yield chunk
        except Exception as e:
            logger.warning(f"[room={room.id}] narrative stream failed: {e}")

    full = "".join(chunks).strip()
    if not full and narrative_engine:
        try:
            full = narrative_engine._offline_global_narrative(ws, ctx.get("all_decisions", {}) or {})
        except Exception:
            full = ""
        if full:
            yield full

    # ── Persist the full narrative back to the quarter_turn row + caches ──
    if full:
        try:
            from histrategy.db.models import update_quarter_turn_narratives

            narratives = dict(getattr(room, "_last_narratives", {}) or {})
            narratives["global"] = full
            for fid in room.slots:
                narratives[fid] = full
            room._last_narratives = narratives
            update_quarter_turn_narratives(room.id, quarter, narratives)
            # Update in-memory replay history for the matching quarter
            for h in getattr(room, "_narrative_history", []) or []:
                if h.get("quarter") == quarter:
                    h["narrative"] = full
                    break
        except Exception as e:
            logger.warning(f"[room={room.id}] narrative persist failed: {e}")

    # Stash already popped at the top (_pop_narrative_context) — nothing to clear.


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
        "device_type": (
            (room.metadata or {}).get("device_type", "unknown")
            if getattr(room, "metadata", None) else "unknown"
        ),
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
            except Exception as e:
                logger.debug("[room=%s] NPC actions lookup failed (display only): %s", room.id, e)
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
        except Exception as e:
            logger.debug("[room=%s] Narrative history load failed (display only): %s", room.id, e)
    if history:
        status["turns"] = history

    # ── Power ranking (from game_state table) ──
    try:
        from histrategy.db.models import get_latest_game_states

        raw_states = get_latest_game_states(room_id, room.quarter_number)

        # ── Get npc_only factions to exclude from ranking ──
        npc_only_ids = _get_npc_only_ids(room_id)

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
                    "food": row.get("food", 0),
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
        except Exception as e:
            logger.debug("[room=%s] Territory owners lookup failed (display only): %s", room.id, e)

        status["territory_owners"] = territory_owners
        status["territory_populations"] = territory_populations
    except Exception:
        status["territory_owners"] = {}
        status["territory_populations"] = {}

    return status


# ── Internal ─────────────────────────────────────────


def _load_repo_npc_decisions(scenario: str, quarter: int = 0) -> dict | None:
    """Load pre-baked NPC decisions from repo for a specific quarter.

    Looks for scenarios/{scenario}/npc_decisions_q{quarter}.json.
    Returns the parsed dict or None if not found.
    """
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "scenarios", scenario,
        f"npc_decisions_q{quarter}.json"
    )
    if not os.path.isfile(path):
        return None
    try:
        return _json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"Failed to load repo NPC decisions for {scenario} Q{quarter}")
        return None


def _trigger_npc_decisions(room: GameRoom):
    """在回合开始时立即为所有 AI NPC 生成决策。

    这样当人类玩家提交决策后，不需要等待 NPC LLM 调用——
    NPC 已经提前提交了决策，最后一个人类提交即可立即 resolve。

    Quarter 0 decisions are cached to disk to avoid redundant LLM calls
    on room creation (same initial state for each scenario).

    Thread-safe: uses _NPC_DECISION_LOCK to prevent concurrent generation
    for the same room.  Persists via _try_save() inside this function so
    no window exists between generation and DB write.
    """

    # ── Re-entry guard ──
    if room.id in _NPC_DECISION_LOCK:
        logger.info(f"Room {room.id}: NPC decisions already in-flight, skipping duplicate trigger")
        return

    from histrategy.engine.decision_bus import collect_all_decisions

    ws = room.world_state
    if ws is None:
        return

    llm = _get_llm()

    # 只收集主要 AI NPC 的决策（人类会在自己的时机提交）
    # 使用 major_npc_ids/LLM_NPC_FACTIONS 过滤，排除 npc_only 死势力（liuzhang/liubiao等）
    major_ids = getattr(room, "major_npc_ids", None)
    if not major_ids:
        from histrategy.engine.faction_slot import LLM_NPC_FACTIONS
        major_ids = LLM_NPC_FACTIONS
    ai_only = {
        fid: s for fid, s in room.slots.items()
        if s.is_ai() and s.is_active and fid in major_ids
    }

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

    # ── Quarter 0-1: check for pre-baked repo decisions ──
    # Q2+ skipped: state divergence from Q1 simulation makes pre-baking unreliable
    if room.quarter_number in (0, 1):
        repo_decisions = _load_repo_npc_decisions(room.scenario, quarter=room.quarter_number)
        if repo_decisions:
            # Q0/Q1 format: {"decisions": {faction_id: {lang: {decision_text, commands}}}}
            if "player_paths" in repo_decisions:
                # Q1/Q2: lookup by player's last suggestion choice
                last_sid = getattr(room, "_last_player_suggestion_id", "")
                path_data = repo_decisions["player_paths"].get(last_sid)
                if not path_data:
                    # Try fuzzy match: check if any path_key starts with the suggestion_id
                    for pk in repo_decisions["player_paths"]:
                        if last_sid and (pk.startswith(last_sid) or last_sid.startswith(pk)):
                            path_data = repo_decisions["player_paths"][pk]
                            break
                if path_data:
                    decisions_data = path_data.get("decisions", {})
                else:
                    decisions_data = {}
            else:
                decisions_data = repo_decisions.get("decisions", {})

            all_cached = True
            for fid in ai_only:
                faction_decisions = decisions_data.get(fid, {})
                lang_data = faction_decisions.get(lang)
                if lang_data and lang_data.get("decision_text"):
                    room.slots[fid].submit_decision(
                        lang_data["decision_text"], lang_data.get("commands", [])
                    )
                else:
                    all_cached = False

            if all_cached:
                logger.info(
                    f"Room {room.id}: NPC Q{room.quarter_number} decisions "
                    f"loaded from repo — {list(ai_only.keys())}"
                )
                return

    # ── Acquire lock before LLM generation ──
    _NPC_DECISION_LOCK.add(room.id)
    try:
        # 临时替换 room.slots 为只含 AI 的版本，避免 DecisionBus 等待人类
        # 使用 collect_all_decisions 为 AI 生成决策
        # 90s 超时：每个 NPC LLM 调用 60s 超时 + 30s buffer
        _NPC_TRIGGER_TIMEOUT = 90
        decisions = collect_all_decisions(
            room, ws, llm=llm, turn_memory=room.turn_summaries, lang=lang,
            timeout=_NPC_TRIGGER_TIMEOUT,
        )
        # 将 AI 决策写入对应的 slot
        for fid, dr in decisions.items():
            if fid in room.slots:
                room.slots[fid].submit_decision(dr.decision_text, dr.commands)

        # ── Persist immediately so concurrent _get_room() loads see the decisions ──
        _try_save(room)

        logger.info(f"Room {room.id}: NPC decisions ready — {list(decisions.keys())}")
    except Exception as e:
        logger.error("[room=%s] NPC decision trigger failed: %s", room.id, e)
    finally:
        _NPC_DECISION_LOCK.discard(room.id)


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
    except Exception as e:
        logger.warning("NPC decision persistence failed: %s", e)
    return None


# ── Streaming mode: transient narrative context stash ──
# _get_room() creates a NEW object from DB each call (no in-memory cache, so it
# survives pod restarts), which means in-memory attributes set on the room
# during _resolve_and_advance are lost once command() reloads the room to build
# its response. This module-level dict bridges that gap: keyed by room_id, it
# only needs to survive the submit → reload → response → stream window (~1s).
# stream_and_persist_narrative pops it after generating + persisting the text.
_NARRATIVE_CONTEXT_STASH: dict[str, dict] = {}

# ── NPC decision generation guard (prevents concurrent triggers) ──
# When multiple requests hit _get_room() while _trigger_npc_decisions() is
# running in a background thread, each load sees the stale DB state (NPC
# decisions not yet saved) and triggers a fresh round.  This set tracks
# rooms that currently have an NPC generation in flight so concurrent
# callers skip instead of duplicating LLM work.
_NPC_DECISION_LOCK: set[str] = set()


def _stash_narrative_context(room_id: str, ctx: dict, quarter: int) -> None:
    """Stash deferred narrative context for pickup across _get_room reloads."""
    _NARRATIVE_CONTEXT_STASH[room_id] = {"ctx": ctx, "quarter": quarter}


def _peek_narrative_context(room_id: str) -> dict | None:
    """Return the stashed narrative context without removing it."""
    return _NARRATIVE_CONTEXT_STASH.get(room_id)


def _pop_narrative_context(room_id: str) -> dict | None:
    """Pop (retrieve + remove) the stashed narrative context."""
    return _NARRATIVE_CONTEXT_STASH.pop(room_id, None)


def _bg_generate_narrative(room_id: str, quarter: int, scenario: str, lang: str = "zh") -> None:
    """Background: generate and persist narrative from stashed context.

    Streaming mode defers narrative generation via _stash_narrative_context.
    This function consumes the stash in a daemon thread so the narrative is
    persisted to DB even if the SSE endpoint (narrative-live-stream) is never
    called or the client disconnects mid-stream.

    After generation the stash is popped so the SSE endpoint doesn't double-
    generate — it will find the persisted narrative in DB and replay it.
    """
    import time as _t
    _t0 = _t.time()

    stashed = _peek_narrative_context(room_id)
    if not stashed:
        logger.warning("[room=%s] bg_narrative: no stashed context, skipping", room_id)
        print(f"⏱ [room={room_id}] bg_narrative NO_STASH", flush=True)
        return

    ctx = stashed.get("ctx")
    if not ctx:
        logger.warning("[room=%s] bg_narrative: empty context, skipping", room_id)
        print(f"⏱ [room={room_id}] bg_narrative EMPTY_CTX", flush=True)
        return

    # Build a narrative engine
    llm = _get_llm()
    narrative_engine = None
    try:
        from histrategy.llm.narrative import NarrativeEngine
        narrative_engine = NarrativeEngine(
            llm_adapter=llm, language=lang, scenario=scenario
        )
    except Exception as e:
        logger.warning("[room=%s] bg_narrative: NarrativeEngine init failed: %s", room_id, e)
        print(f"⏱ [room={room_id}] bg_narrative INIT_FAIL {_t.time()-_t0:.1f}s: {e}", flush=True)
        return

    if not narrative_engine:
        return

    # Generate narrative from stashed context
    try:
        all_decisions = ctx.get("all_decisions", {})
        baseline = ctx.get("baseline")
        macro_delta = ctx.get("macro_delta")
        history_events = ctx.get("history_events")

        # Reload room to get WorldState (persisted by _save_v3_state_to_db before this thread runs)
        room = _get_room(room_id)
        ws = room.world_state if room else None

        full_text = narrative_engine.generate_global_narrative(
            ws=ws,
            faction_decisions=all_decisions,
            baseline=baseline,
            macro_delta=macro_delta,
            history_events=history_events,
            room_id=room_id,
            scenario=scenario,
        )
    except Exception as e:
        logger.warning("[room=%s] bg_narrative: generation failed: %s", room_id, e)
        print(f"⏱ [room={room_id}] bg_narrative GEN_FAIL {_t.time()-_t0:.1f}s: {e}", flush=True)
        return

    if not full_text or not full_text.strip():
        logger.warning("[room=%s] bg_narrative: empty output, skipping persist", room_id)
        # Don't pop stash — SSE can still regenerate
        print(f"⏱ [room={room_id}] bg_narrative EMPTY {_t.time()-_t0:.1f}s", flush=True)
        return

    # Persist to DB
    persist_ok = False
    try:
        from histrategy.db.models import update_quarter_turn_narratives
        narratives = {fid: full_text for fid in all_decisions}
        narratives["global"] = full_text
        update_quarter_turn_narratives(room_id, quarter, narratives)
        persist_ok = True
        logger.info(
            "[room=%s] bg_narrative: persisted %d chars in %.1fs",
            room_id, len(full_text), _t.time() - _t0,
        )
        print(f"⏱ [room={room_id}] bg_narrative PERSISTED {len(full_text)} chars {_t.time()-_t0:.1f}s", flush=True)
    except Exception as e:
        logger.warning("[room=%s] bg_narrative: DB persist failed: %s", room_id, e)
        print(f"⏱ [room={room_id}] bg_narrative PERSIST_FAILED {_t.time()-_t0:.1f}s: {e}", flush=True)
        # Don't pop stash — let SSE regenerate and persist
        return

    # Only pop the stash if persist succeeded (so SSE finds cached narrative)
    _pop_narrative_context(room_id)


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
    except Exception as e:
        logger.warning("[room=%s] Scenario year parse failed, keeping existing year: %s", room.id, e)  # Graceful: keep existing year if TOML parse fails

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


def _resolve_and_advance(room: GameRoom, skip_narrative: bool = False):
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
    # skip_narrative 仅对 V3 有意义（V1/V2 无 LLM 叙事引擎）。
    if engine_mode == EngineMode.V1:
        result = _resolve_v1(room, ws, decisions, llm)
    elif engine_mode == EngineMode.V2:
        result = _resolve_v2_or_v3(room, ws, decisions, llm, mode="v2")
    else:
        # V3 (merged V3+Macro)
        result = _resolve_v2_or_v3(room, ws, decisions, llm, mode="v3", skip_narrative=skip_narrative)

    room._last_narratives = result.narratives
    room._last_state_changes = getattr(result, "state_changes", {}) or {}
    npc_actions = []
    # Resolve faction display names with scenario-aware lang support
    fnames = _get_faction_names(room, lang=lang or "zh")
    for fid, dr in decisions.items():
        if room.slots.get(fid) and room.slots[fid].is_ai():
            name = fnames.get(fid, fid)
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

    # ── NPC territory combat resolution ──
    # After LLM generates NPC decisions, run deterministic combat for any
    # military actions. Without this, NPC battles are pure narrative fiction
    # that never changes territory ownership.
    _resolve_npc_territory_combat(room, ws, decisions)

    if result.turn_summary:
        room.turn_summaries.append(result.turn_summary)
        if len(room.turn_summaries) > 8:
            room.turn_summaries = room.turn_summaries[-8:]

    # TurnController.execute_turn() already advances the season internally.
    # Do NOT call _advance_season(ws) here — it would double-advance.
    room.advance_quarter()

    # ── NPC decisions for the new quarter are pre-generated in the
    #     BACKGROUND thread below (H31a-B2). Do NOT add a synchronous
    #     _trigger_npc_decisions() call here — it blocks the /command
    #     response and the background thread handles it correctly.
    #     collect_all_decisions() during resolution serves as a safety
    #     net if the background thread hasn't finished yet.

    # ── Auto-expire stale policies ──
    try:
        from histrategy.db.models import advance_policies
        expired = advance_policies(room.id, room.quarter_number)
        if expired:
            logging.getLogger("histrategy.room").info(
                "[room=%s] Policy auto-expiry: %d policies expired at quarter %d",
                room.id, expired, room.quarter_number,
            )
    except Exception as e:
        logger.warning("[room=%s] Policy auto-expiry check failed: %s", room.id, e)

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
    ws_dict = _serialize_world_state(ws)

    # ── Streaming mode: generate a deterministic offline narrative NOW,
    #    before saving to DB. Without this, the shared page shows empty
    #    narratives until (and unless) the SSE endpoint runs.
    if skip_narrative:
        _ensure_narrative_fallback(room, decisions, result)

    _try_save(room, ws_dict)
    _save_quarter(room, decisions, result)
    _write_backup(room, ws_dict)

    # ── Streaming mode: stash the deferred narrative context (module-level, so
    #    it survives the _get_room reload in command()). Keyed by room_id +
    #    just-produced quarter so narrative-live-stream updates the right row. ──
    if skip_narrative and getattr(result, "narrative_context", None):
        _stash_narrative_context(room.id, result.narrative_context, room.quarter_number)
        print(
            f"⏱ [room={room.id}] STASHED narrative: quarter={room.quarter_number} keys={list(result.narrative_context.keys())}",
            flush=True,
        )
        # ── Background: generate real LLM narrative and persist to DB ──
        # The SSE endpoint (narrative-live-stream) remains the interactive path,
        # but shared pages and page reloads need the real narrative regardless
        # of whether the client called SSE. This background thread guarantees
        # the DB gets a real LLM chronicle within ~30s.
        import threading as _thr

        def _bg_generate_narrative(r, stashed_ctx, stashed_quarter, stashed_lang, stashed_scenario):
            import time as _t
            _t0 = _t.time()
            try:
                llm2 = _get_llm()
                from histrategy.llm.narrative import NarrativeEngine
                eng = NarrativeEngine(
                    llm_adapter=llm2, language=stashed_lang,
                    scenario=stashed_scenario,
                )
                ws_current = r.world_state
                if not ws_current:
                    return
                faction_decisions = stashed_ctx.get("all_decisions", {}) or {}
                if isinstance(faction_decisions, dict):
                    # Convert DecisionResult objects to plain decision text
                    fd_plain = {}
                    for fid, val in faction_decisions.items():
                        if hasattr(val, "decision_text"):
                            fd_plain[fid] = val.decision_text
                        elif isinstance(val, dict):
                            fd_plain[fid] = val.get("decision", str(val))
                        else:
                            fd_plain[fid] = str(val)
                    faction_decisions = fd_plain

                chunks = []
                for chunk in eng.generate_global_narrative_stream(
                    ws=ws_current,
                    faction_decisions=faction_decisions,
                    baseline=stashed_ctx.get("baseline"),
                    macro_delta=stashed_ctx.get("macro_delta"),
                    history_events=stashed_ctx.get("history_events"),
                    room_id=r.id,
                    scenario=stashed_scenario,
                ):
                    if chunk:
                        chunks.append(chunk)
                full = "".join(chunks).strip()
                if full:
                    from histrategy.db.models import update_quarter_turn_narratives
                    narratives = {"global": full}
                    update_quarter_turn_narratives(r.id, stashed_quarter, narratives)
                    logger.info(
                        "[room=%s] bg narrative persisted: %d chars in %.1fs",
                        r.id, len(full), _t.time() - _t0,
                    )
            except Exception as e:
                logger.warning(
                    "[room=%s] bg narrative generation failed: %s",
                    r.id, str(e)[:200],
                )

        _thr.Thread(
            target=_bg_generate_narrative,
            args=(room, result.narrative_context, room.quarter_number,
                  getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh",
                  getattr(room, "scenario", "") or ""),
            daemon=True,
        ).start()
        print(
            f"⏱ [room={room.id}] BG narrative thread started: quarter={room.quarter_number}",
            flush=True,
        )

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



def _apply_deterministic_economy(ws) -> None:
    """Bug H35b: Apply deterministic tax revenue and military upkeep per quarter.

    V1 simulation relies solely on LLM output for economy changes. The LLM
    often ignores or forgets to update treasury and food, causing them to
    stay nearly frozen across turns. This function applies a lightweight
    deterministic economy tick that mirrors the V2/V3 DomesticEngine logic.

    Tax revenue: sum(population * tax_rate * 0.01) per territory
    Military upkeep: 1 food per 100 troops (round up)
    """
    logger = logging.getLogger("histrategy.economy")

    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue

        territories = getattr(faction, "territories", []) or []
        tax_rate = getattr(faction, "tax_rate", 0.3)

        # ── Tax revenue from owned territories ──
        tax_total = 0
        for tid in territories:
            t = ws.territories.get(tid) if hasattr(ws, "territories") else None
            if t:
                pop = getattr(t, "population", 0) or 0
                # Simple per-capita tax: pop * tax_rate * 0.01 gold per head
                tax_total += int(pop * tax_rate * 0.01)

        if tax_total > 0:
            old_treasury = getattr(faction, "treasury", 0) or 0
            faction.treasury = old_treasury + tax_total
            logger.debug(
                "V1 economy: %s tax_revenue=%d treasury %d→%d",
                fid, tax_total, old_treasury, faction.treasury,
            )

        # ── Military food upkeep ──
        troops = (
            getattr(faction, "strength_actual", 0)
            or getattr(faction, "strength", 0)
            or 0
        )
        if troops > 0:
            upkeep = max(1, troops // 100)  # 1 food per 100 troops
            old_food = getattr(faction, "food", 0) or 0
            faction.food = max(0, old_food - upkeep)

            # ── Military gold upkeep ──
            # Each soldier costs ~0.5 gold per quarter
            gold_upkeep = max(1, troops // 200)
            faction.treasury = max(0, faction.treasury - gold_upkeep)


def _capture_faction_state(ws, room=None) -> dict:
    """Capture pre-resolution state for turn_delta calculation.

    Returns {faction_id: {population, troops, food, treasury, morale, territories}}.
    Falls back to game_state DB for troops when world_state serialization rounds
    trip resets strength_actual to the dataclass default (5000).
    """
    # Read authoritative state from game_state DB if available.
    # The WorldState in-memory objects (faction.food, faction.treasury,
    # faction.morale_actual) reset to dataclass defaults (3000, 5000, 50)
    # after every DB round-trip via deserialize_world_state().  We already
    # had a fallback for troops (default 5000); this extends the same
    # fallback to food, treasury and morale so turn-to-turn deltas are
    # computed against the real previous-turn values, not the defaults.
    _DEFAULT_FOOD = 3000
    _DEFAULT_TREASURY = 5000
    _DEFAULT_MORALE = 50
    db_state = {}
    if room:
        try:
            from histrategy.db.models import get_latest_game_states
            rows = get_latest_game_states(room.id, room.quarter_number)
            for gs in rows:
                db_state[gs["faction_id"]] = {
                    "troops": gs.get("troops", 0),
                    "food": gs.get("food", 0),
                    "treasury": gs.get("treasury", 0),
                    "morale": gs.get("morale", _DEFAULT_MORALE),
                }
        except Exception:
            pass

    old_state = {}
    for fid in ws.factions:
        faction = ws.factions[fid]
        db_vals = db_state.get(fid, {})
        ws_troops = getattr(faction, "strength_actual", 0)
        ws_food = getattr(faction, "food", 0)
        ws_treasury = getattr(faction, "treasury", 0)
        ws_morale = getattr(faction, "morale_actual", _DEFAULT_MORALE)

        # Use DB values when WorldState has reverted to dataclass defaults
        _DEFAULT_TROOPS = 5000
        troops = db_vals.get("troops", ws_troops) if ws_troops == _DEFAULT_TROOPS and db_vals.get("troops", _DEFAULT_TROOPS) != _DEFAULT_TROOPS else ws_troops
        food_val = db_vals.get("food", ws_food) if ws_food == _DEFAULT_FOOD and db_vals.get("food", _DEFAULT_FOOD) != _DEFAULT_FOOD else ws_food
        treasury_val = db_vals.get("treasury", ws_treasury) if ws_treasury == _DEFAULT_TREASURY and db_vals.get("treasury", _DEFAULT_TREASURY) != _DEFAULT_TREASURY else ws_treasury
        morale_val = db_vals.get("morale", ws_morale) if ws_morale == _DEFAULT_MORALE and db_vals.get("morale", _DEFAULT_MORALE) != _DEFAULT_MORALE else ws_morale

        # Bug H35a: compute population from territory sum
        pop_val = getattr(faction, "population", 0)
        if not pop_val:
            pop_val = sum(
                getattr(ws.territories.get(tid), "population", 0)
                for tid in getattr(faction, "territories", [])
                if ws.territories.get(tid)
            )
        old_state[fid] = {
            "population": pop_val,
            "troops": troops,
            "food": food_val,
            "treasury": treasury_val,
            "morale": morale_val,
            "territories": list(getattr(faction, "territories", [])),
        }
    return old_state


def _capture_faction_population(ws, faction) -> int:
    """Compute faction population from territory sum (FactionState has no population field)."""
    pop_val = getattr(faction, "population", 0)
    if not pop_val:
        pop_val = sum(
            getattr(ws.territories.get(tid), "population", 0)
            for tid in getattr(faction, "territories", [])
            if ws.territories.get(tid)
        )
    return pop_val


def _resolve_territories_from_delta(faction, delta: dict, ws) -> list[dict]:
    """Apply territory changes from a state_changes delta to the current faction.

    Supports three delta formats:
      - ``territories``: absolute list of territory dicts (overwrites current)
      - ``territories_gained`` + ``territories_lost``: incremental lists
      - absent: keep current territories (fallback)
    """
    current_ids = list(getattr(faction, "territories", []) or [])

    # Format 1: absolute territory list in delta
    if "territories" in delta and isinstance(delta["territories"], list):
        raw = delta["territories"]
        if raw and isinstance(raw[0], dict):
            current_ids = [t.get("id", t.get("name", "")) for t in raw if isinstance(t, dict)]
        else:
            current_ids = [str(t) for t in raw]

    # Format 2: incremental gained/lost
    gained = delta.get("territories_gained", [])
    lost = delta.get("territories_lost", [])
    if gained:
        for t in gained:
            tid = t.get("id", t) if isinstance(t, dict) else str(t)
            if tid and tid not in current_ids:
                current_ids.append(tid)
    if lost:
        for t in lost:
            tid = t.get("id", t) if isinstance(t, dict) else str(t)
            if tid in current_ids:
                current_ids.remove(tid)

    return [
        {"id": t, "name": ws.territories[t].name if t in ws.territories else t}
        for t in current_ids
    ]


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
    old_state = _capture_faction_state(ws, room=room)
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
            # Bug H35a: compute population from territory sum
            pop_val_delta = getattr(faction, "population", 0)
            if not pop_val_delta:
                pop_val_delta = sum(
                    getattr(ws.territories.get(tid), "population", 0)
                    for tid in getattr(faction, "territories", [])
                    if ws.territories.get(tid)
                )
            v1_factions[fid] = {
                "population": pop_val_delta,
                "troops": troops + delta.get("strength_delta", 0),
                "food": faction.food,
                "treasury": faction.treasury + delta.get("treasury_delta", 0),
                "morale": morale + delta.get("morale_delta", 0),
                "territories": _resolve_territories_from_delta(faction, delta, ws),
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
                "population": _capture_faction_population(ws, faction),
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
                    "population": _capture_faction_population(ws, faction),
                    "troops": getattr(faction, "strength_actual", 0),
                    "food": faction.food,
                    "treasury": faction.treasury,
                    "morale": getattr(faction, "morale_actual", 50),
                }

    # 将 V1 结果应用到 WorldState
    _apply_v1_state_to_world(ws, v1_factions)

    # ── Bug H35b fix: deterministic economy tick ──
    # V1 simulation relies on LLM to produce economy changes, but the LLM often
    # ignores tax revenue and military upkeep, resulting in frozen treasuries.
    # Apply deterministic tax + food/upkeep after LLM state application so
    # treasury and food always change each quarter.
    _apply_deterministic_economy(ws)

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


def _resolve_v2_or_v3(room, ws, decisions, llm, mode, skip_narrative: bool = False):
    """Resolve using QuarterlyResolver — V2 (deterministic) or V3 (LLM-augmented).

    V2: TurnController + IntentParser only (zero LLM).
    V3: Full engine stack (MacroPolicy, Narrative, BlackSwan, Guardrail, StateApplier).

    skip_narrative: V3 streaming mode — settle state but defer narrative (see
    QuarterlyResolver.resolve). Ignored for V2 (no narrative engine).
    """
    from histrategy.engine.quarterly_resolver import QuarterlyResolver, _extract_state_changes

    # ── Capture pre-resolution state ──
    old_state = _capture_faction_state(ws, room=room)

    # ── Snapshot territory ownership BEFORE simulation (Bug H35k) ──
    # The V3 baseline engine clears ws.territories during execute_turn.
    # Save the territory→owner mapping now so _save_v3_state_to_db can
    # restore it even if ws.territories is empty after simulation.
    pre_territories: dict[str, list[dict]] = {}
    for tid, t in ws.territories.items():
        owner = getattr(t, "owner_id", "") or ""
        if owner and owner in ws.factions:
            pop = getattr(t, "population", 0)
            pre_territories.setdefault(owner, []).append(
                {"id": tid, "name": getattr(t, "name", tid), "population": pop}
            )
    # Also deep-copy ws.territories dict itself (Territory objects) so we
    # can restore it after simulation for world_state serialization.
    _saved_territories = dict(ws.territories) if ws.territories else {}

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
        result = resolver.resolve(room, ws, decisions, llm=llm, skip_narrative=skip_narrative)
        _clamp_extreme_changes(ws, old_state)
        # Re-extract state_changes AFTER clamping so API returns post-guardrail values.
        # Without this, state_changes in quarter_turn shows PRE-CLAMP values while
        # game_state and turn_delta show POST-CLAMP — inconsistent and confusing.
        from histrategy.engine.quarterly_resolver import _extract_state_changes
        result.state_changes = _extract_state_changes(ws, decisions)
        _save_v3_state_to_db(room, ws, decisions, result, old_state, pre_territories)
        # Restore ws.territories for world_state serialization (Bug H35k)
        if _saved_territories and not ws.territories:
            ws.territories.clear()
            ws.territories.update(_saved_territories)
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

    result = resolver.resolve(room, ws, decisions, llm=llm, skip_narrative=skip_narrative)

    # ── Post-resolve guardrail ──
    _clamp_extreme_changes(ws, old_state)
    # Re-extract state_changes after guardrail mutates faction.food
    result.state_changes = _extract_state_changes(ws, decisions)

    # ── Sync faction.territories from ws.territories[].owner_id ──
    # The baseline (execute_turn) mutates ws.territories[].owner_id but does
    # NOT update faction.territories. Without this sync, _territories_to_list
    # and _serialize_world_state produce empty territory lists, and the next
    # turn loads a WorldState with all factions reset to defaults (Bug H35g).
    _sync_faction_territories(ws)

    _save_v3_state_to_db(room, ws, decisions, result, old_state, pre_territories)
    
    # ── Restore ws.territories after simulation (Bug H35k) ──
    # The V3 engine clears ws.territories during execute_turn. Restore from
    # pre-simulation snapshot so _serialize_world_state (called later in
    # _try_save) saves correct territory data for the next turn's reload.
    if _saved_territories and not ws.territories:
        logger.warning(
            "[room=%s] H35k: restoring ws.territories (%d territories) after simulation cleared them",
            room.id, len(_saved_territories))
        ws.territories.clear()
        ws.territories.update(_saved_territories)
    elif not _saved_territories:
        logger.warning(
            "[room=%s] H35k: _saved_territories was EMPTY at start — world_state already corrupted!",
            room.id)
    
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

    # Extract per-faction stats (population, troops, food, treasury, morale, loyalty)
    # Include ALL active factions (major from decisions + minor NPC factions)
    # EXCEPT npc_only factions (e.g. sextus_pompey) which should not appear in UI
    npc_ids = _get_npc_only_ids(room.id)
    faction_stats = {}
    for fid in ws.factions:
        if fid in npc_ids:
            continue  # Skip npc_only factions
        faction = ws.factions[fid]
        if not faction.is_active:
            continue
        # Bug H35a fix: compute population from territory sum (FactionState has no population field)
        pop_val = getattr(faction, "population", 0)
        if not pop_val:
            pop_val = sum(
                getattr(ws.territories.get(tid), "population", 0)
                for tid in (getattr(faction, "territories", []) or [])
                if ws.territories.get(tid)
            )
        stats = {
            "population": pop_val,
            "troops": getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0,
            "food": getattr(faction, "food", 0),
            "treasury": getattr(faction, "treasury", 0),
            "morale": getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50,
        }
        loyalty = getattr(faction, "loyalty", 50) or 50
        stats["loyalty"] = loyalty
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


def _sync_faction_territories(ws):
    """Sync faction.territories from ws.territories[].owner_id.

    The V2/V3 baseline (execute_turn) mutates ws.territories[].owner_id for
    territory ownership but does NOT update faction.territories. Without this
    sync, _territories_to_list returns [] and _serialize_world_state saves
    factions with empty territory lists — causing every faction to reset to
    dataclass defaults (strength=5000, territories=[]) on the next DB round-trip.
    """
    # Build {faction_id: [territory_ids]} from territory.owner_id
    owner_map: dict[str, list[str]] = {}
    for tid, territory in ws.territories.items():
        owner = getattr(territory, "owner_id", "") or ""
        if owner and owner in ws.factions:
            owner_map.setdefault(owner, []).append(tid)
    for fid, faction in ws.factions.items():
        if fid in owner_map:
            faction.territories = list(owner_map[fid])


def _territories_to_list(ws, faction) -> list[dict]:
    """Serialize faction territories to [{id, name, population}] list."""
    result = []
    for tid in faction.territories:
        t = ws.territories.get(tid)
        pop = getattr(t, "population", 0) if t else 0
        result.append({"id": tid, "name": t.name if t else tid, "population": pop})
    return result


def _territories_from_owner(ws, faction_id: str) -> list[dict]:
    """Build territory list by scanning ws.territories for matching owner_id.

    More robust than _territories_to_list — doesn't depend on faction.territories
    being synced. Used as fallback when faction.territories is stale/empty (Bug H35i).
    """
    result = []
    for tid, t in ws.territories.items():
        owner = getattr(t, "owner_id", "") or ""
        if owner == faction_id:
            pop = getattr(t, "population", 0)
            result.append({"id": tid, "name": getattr(t, "name", tid), "population": pop})
    return result


def _clamp_extreme_changes(ws, old_state: dict):
    """Clamp per-turn faction state changes with proportional scaling.

    V3 QuarterlyResolver has no built-in guardrail for troop/food changes.
    This prevents LLM-hallucinated extreme swings while PRESERVING the
    relative ordering between factions.

    DESIGN: Since all factions start at identical base values (折算数值),
    a per-faction cap (e.g. max 300% each) still makes them identical.
    Instead, we scale ALL factions proportionally so the LARGEST gainer
    hits the cap, and smaller gainers keep their relative position.

    Example: raw gains are +3981%, +6020%, +2960%, +1685%
    Without proportional scaling → all clamped to 20000 (identical)
    With proportional scaling → 14117, 20000, 11384, 7892 (differentiated)
    """
    _MAX_TROOP_LOSS = 0.35   # Max 35% per-quarter troop loss
    _MAX_TROOP_GAIN = 0.50   # Max 50% per-quarter troop gain (was 300%)
    _MAX_FOOD_LOSS = 0.40    # Max 40% per-quarter food loss (preserve 60%)
    _MAX_FOOD_GAIN = 1.00    # Max 100% per-quarter food gain (double at most)

    # ── First pass: collect raw changes ──
    faction_changes: dict[str, dict] = {}
    max_gain_ratio = 1.0

    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        old = old_state.get(fid, {})
        old_troops = old.get("troops", 0)
        new_troops = getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0
        if old_troops > 0 and new_troops != old_troops:
            ratio = new_troops / old_troops
            faction_changes[fid] = {
                "faction": faction,
                "old": old_troops,
                "new": new_troops,
                "ratio": ratio,
                "old_food": old.get("food", 0) or getattr(faction, "food", 0) or 0,
            }
            if ratio > max_gain_ratio:
                max_gain_ratio = ratio

    if max_gain_ratio > (1 + _MAX_TROOP_GAIN):
        # ── Proportional scaling: preserve relative ordering ──
        scale = (1 + _MAX_TROOP_GAIN) / max_gain_ratio
        logger.warning(
            "V3 guardrail: proportional scaling applied, "
            f"max_gain_ratio={max_gain_ratio:.1f}x, scale={scale:.2f}, "
            f"factions={len(faction_changes)}"
        )
        for fid, data in faction_changes.items():
            faction = data["faction"]
            old_troops = data["old"]
            new_troops = data["new"]
            ratio = data["ratio"]

            if ratio > 1:  # gain
                clamped = int(old_troops * ratio * scale)
                logger.warning(
                    f"V3 guardrail: {faction.name} ({fid}) troops "
                    f"{old_troops}->{new_troops} ({ratio:+.0%} raw) "
                    f"→ scaled to {clamped} "
                    f"(proportional, max capped at {int(old_troops * (1 + _MAX_TROOP_GAIN))})"
                )
            else:  # loss
                loss_pct = 1 - ratio
                if loss_pct > _MAX_TROOP_LOSS:
                    clamped = int(old_troops * (1 - _MAX_TROOP_LOSS))
                    logger.warning(
                        f"V3 guardrail: {faction.name} ({fid}) troops "
                        f"{old_troops}->{new_troops} ({ratio:+.0%}) "
                        f"clamped to {clamped} (loss cap: {_MAX_TROOP_LOSS:.0%})"
                    )
                else:
                    clamped = new_troops

            if hasattr(faction, "strength_actual"):
                faction.strength_actual = clamped
            elif hasattr(faction, "strength"):
                faction.strength = clamped

            # Scale food proportionally (always, even if old_food=0 — use baseline minimum)
            old_food = data["old_food"]
            if abs(ratio - 1) > 1.0:
                min_food = 3000  # baseline minimum food for all factions
                effective_old = max(old_food, min_food)
                faction.food = int(effective_old * min(1 + _MAX_TROOP_GAIN, 2.0))
                logger.warning(
                    f"V3 guardrail: {faction.name} ({fid}) food auto-scaled "
                    f"{effective_old}->{faction.food}"
                )

    # ── Dedicated food guardrail (always runs, proportional) ──
    # The old guardrail used a crude absolute floor (3000) that ignored
    # the faction's previous food level. Now we preserve at least 60% of
    # the previous turn's food per faction, with a minimum absolute floor.
    _FOOD_FLOOR_ABSOLUTE = 3000         # Absolute minimum for any faction
    _FOOD_PRESERVATION_RATIO = 1 - _MAX_FOOD_LOSS  # Preserve at least 60%
    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        old_data = old_state.get(fid, {})
        old_food = old_data.get("food", 0) or 0
        current = getattr(faction, "food", 0) or 0
        if old_food > 0:
            # Proportional floor: keep at least 60% of previous turn's food
            proportional_floor = max(int(old_food * _FOOD_PRESERVATION_RATIO), _FOOD_FLOOR_ABSOLUTE)
            if current < proportional_floor:
                was = current
                faction.food = proportional_floor
                logger.warning(
                    f"V3 food guardrail: {getattr(faction, 'name', fid)} ({fid}) "
                    f"food below proportional floor ({was} < {proportional_floor}), "
                    f"clamped (prev={old_food}, preserve={_FOOD_PRESERVATION_RATIO:.0%})"
                )
            # Cap food gain at _MAX_FOOD_GAIN (100%)
            elif current > old_food * (1 + _MAX_FOOD_GAIN):
                capped = int(old_food * (1 + _MAX_FOOD_GAIN))
                logger.warning(
                    f"V3 food guardrail: {getattr(faction, 'name', fid)} ({fid}) "
                    f"food gain capped {current} -> {capped} "
                    f"(max {_MAX_FOOD_GAIN:.0%} gain from {old_food})"
                )
                faction.food = capped
        else:
            # No previous food data — use absolute floor
            if current < _FOOD_FLOOR_ABSOLUTE:
                faction.food = _FOOD_FLOOR_ABSOLUTE


def _save_v3_state_to_db(room, ws, decisions, result, old_state: dict, pre_territories: dict | None = None):
    """将 V3 仿真结果写入 game_state + policy_state + turn_delta 表。

    使用逐势力 try/except 保障：单个势力故障不影响其他势力持久化。
    
    pre_territories: {faction_id: [{id, name, population}]} captured BEFORE
        simulation. Used as fallback when ws.territories is cleared by engine.
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
            # Bug H35i: _territories_to_list depends on faction.territories,
            # which may be stale/empty after simulation. Fall back to scanning
            # ws.territories by owner_id to ensure territories are never lost.
            territories_list = _territories_to_list(ws, faction)
            if not territories_list and ws:
                territories_list = _territories_from_owner(ws, fid)
            # Bug H35k: ws.territories may be entirely empty after simulation.
            # Use pre-simulation snapshot as final fallback.
            if not territories_list and pre_territories and fid in pre_territories:
                territories_list = list(pre_territories[fid])

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
            # native population field — it's derived from Territory.population).
            # Territory.population defaults to 50000. Use getattr for safety
            # against serialized Territory dicts or missing keys after DB round-trip.
            computed_population = _safe_int(getattr(faction, "population", 0))
            if computed_population == 0 and ws:
                computed_population = sum(
                    max(100, _safe_int(getattr(ws.territories.get(tid), "population", 50000)))
                    for tid in getattr(faction, "territories", [])
                    if tid in ws.territories
                )
            # Fallback 1: compute from territories_list (uses owner fallback)
            if not computed_population and territories_list:
                computed_population = sum(
                    max(100, t.get("population", 50000)) for t in territories_list
                    if isinstance(t, dict)
                )
            # Fallback 2: carry forward previous quarter population (Bug H35j)
            # Previously defaulted to max(100, 0*50000)=100 when no territories.
            if not computed_population and fid in old_state:
                computed_population = _safe_int(old_state[fid].get("population", 0))
            # Fallback 3: absolute minimum
            if not computed_population:
                computed_population = 50000  # minimum faction population

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
                            _safe_int(_capture_faction_population(ws, faction)),
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


def _enrich_narratives_with_npc(narratives: dict, decisions: dict, room) -> dict:
    """Add NPC decision text as _npc_actions to narratives for shared page display."""
    enriched = dict(narratives)
    npc_actions = []
    for slot in room.active_slots():
        fid = slot.faction_id
        if slot.is_human():
            continue
        dr = decisions.get(fid)
        if dr and dr.decision_text:
            name = room.factions[fid].name if hasattr(room, "factions") and fid in (room.factions or {}) else fid
            npc_actions.append(f"{name}: {dr.decision_text[:300]}")
    if npc_actions:
        enriched["_npc_actions"] = npc_actions
    return enriched


def _save_quarter(room, decisions, result):
    try:
        from histrategy.db.models import save_quarter_turn

        fd = {}
        for fid, dr in decisions.items():
            # Serialize commands to plain dicts — PolicyCommand / Command objects
            # must be converted before JSON storage, otherwise they become
            # Python repr strings like "Command(type=...)".
            raw_cmds = dr.commands if dr.commands else []
            serialized_cmds = []
            for c in raw_cmds:
                if hasattr(c, 'to_dict'):
                    serialized_cmds.append(c.to_dict())
                elif hasattr(c, '__dataclass_fields__'):
                    # dataclasses.asdict fallback
                    import dataclasses
                    serialized_cmds.append(dataclasses.asdict(c))
                elif isinstance(c, dict):
                    serialized_cmds.append(c)
                else:
                    # Last resort: try dict() constructor
                    try:
                        serialized_cmds.append(dict(c))
                    except (TypeError, ValueError):
                        serialized_cmds.append(str(c))
            
            fd[fid] = {
                "decision": dr.decision_text,
                "commands": serialized_cmds,
                "source": dr.source,
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

        # Serialize baseline TurnResult to dict for DB storage
        baseline_dict = None
        baseline = getattr(result, "baseline", None)
        if baseline is not None:
            from histrategy.db.models import _json_safe_deep_convert
            try:
                import dataclasses
                raw = dataclasses.asdict(baseline)
                baseline_dict = _json_safe_deep_convert(raw)
            except (TypeError, Exception):
                baseline_dict = {"_serialization_error": str(type(baseline))}

        # Serialize macro_delta (already a dict)
        macro_dict = getattr(result, "macro_delta", None) or None

        save_quarter_turn(
            room.id,
            room.quarter_number,
            room.year,
            room.season,
            faction_decisions=fd,
            baseline_result=baseline_dict,
            macro_delta=macro_dict,
            narratives=_enrich_narratives_with_npc(result.narratives or {}, decisions, room),
            state_changes=result.state_changes,
            token_usage=token_usage,
        )
    except Exception as e:
        logger.warning(f"Quarter save failed: {e}")


def _ensure_narrative_fallback(room, decisions, result):
    """Generate a deterministic offline narrative and attach it to result.narratives.

    Called in streaming mode (skip_narrative=True) BEFORE _save_quarter, so the
    DB always has a narrative — even if the SSE endpoint never runs.

    Uses NPC decision texts to build a chronicle paragraph, which is far more
    readable than the old statistics-only fallback.
    """
    try:
        ws = room.world_state
        if ws is None:
            return
        lang = getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"
        scenario = getattr(room, "scenario", "") or ""

        # Collect NPC decision summaries
        npc_summaries: list[str] = []
        for fid, dr in decisions.items():
            if room.slots.get(fid) and room.slots[fid].is_ai():
                fname = room.slots[fid].display_name or fid
                text = dr.decision_text[:120].strip()
                if text:
                    npc_summaries.append(f"**{fname}**：{text}")

        # Build era-aware header
        year = ws.year
        season_val = getattr(ws, "season", None)
        if hasattr(season_val, "cn"):
            season_cn = season_val.cn
        elif hasattr(season_val, "value"):
            season_cn = str(season_val.value)
        else:
            season_cn = str(season_val or "?")

        # Era line
        era_line = f"{year}年{season_cn}，天下纷争未休。"
        # Try scenario-aware era
        if scenario == "nanming":
            # 南明: 1644 winter → 1645 spring
            # 弘光: 1644 → era_year = year - 1643
            era_year = year - 1643
            if era_year < 1:
                era_str = f"崇祯{18 + year - 1644}年" if year <= 1644 else f"弘光前{1 - era_year}年"
            elif era_year == 1:
                era_str = "弘光元年"
            else:
                era_str = f"弘光{era_year}年"
            era_line = f"{era_str}{season_cn}，天下纷争未休。"

        lines = [f"### {year}年{season_cn} · 大事纪", "", era_line, ""]

        # Note: NPC decisions are shown in "天下八方动向" section via npc_reactions.
        # Faction stats are shown in "🏰 势力资源" table via state_changes.
        # The narrative should be a chronicle, not a data dump — keep it clean.

        lines.append("")
        lines.append("_史官记录本季大事。实时战报将在后续回合中由AI生成。_")

        narrative = "\n".join(lines)
        if not getattr(result, "narratives", None):
            result.narratives = {}
        result.narratives["global"] = narrative
        logger.info("[room=%s] Offline narrative generated: %d chars", room.id, len(narrative))
    except Exception as e:
        logger.warning("[room=%s] _ensure_narrative_fallback failed: %s", room.id, e)


def _resolve_npc_territory_combat(room, ws, decisions):
    """After LLM generates NPC decisions, run deterministic combat for any
    military actions that should result in territory transfers.

    The LLM writes dramatic battle narratives but the engine never changes
    territory ownership. This function bridges that gap: it scans NPC decision
    text for keywords, finds valid targets from _FACTION_ATTACK_TARGETS,
    runs _resolve_combat deterministically, and applies territory transfers
    when city_falls.
    """
    try:
        from histrategy.engine.fast_path import (
            _FACTION_ATTACK_TARGETS, _resolve_combat, _YANGTZE_SOUTH,
            _TERRITORY_ZH as _TERR_ZH,
        )
    except ImportError:
        return

    factions = getattr(ws, "factions", {})
    if not factions:
        return

    # ── Q1-Q2 block: only for Three Kingdoms scenario (208 AD timeline
    #    where Cao Cao consolidates north during spring/summer).
    #    Other scenarios (nanming, rome) have different timelines and
    #    should allow combat from Q1 onward.
    quarter = getattr(room, "quarter_number", 0)
    scenario = getattr(room, "scenario", "") or ""
    if quarter <= 1 and scenario in ("three-kingdoms", ""):
        logger.info(
            "[room=%s Q%d] _resolve_npc_territory_combat: SKIPPED (TK Q1-Q2 no combat)",
            room.id, quarter + 1,
        )
        return

    # Build a mutable snapshot of factions for combat resolution
    fstate = {}
    for fid, f in factions.items():
        fstate[fid] = {
            "troops": getattr(f, "strength", 0) or getattr(f, "strength_actual", 0),
            "territories": list(getattr(f, "territories", [])),
            "morale": getattr(f, "morale_actual", 0) or getattr(f, "morale", 0),
            "population": getattr(f, "population", 0),
            "food": getattr(f, "food", 0),
        }

    military_kw = ["攻", "伐", "征", "战", "取", "夺", "击", "袭", "破",
                   "attack", "invade", "strike", "march", "assault",
                   "siege", "raid", "capture", "conquer"]

    for fid, dr in decisions.items():
        if not (room.slots.get(fid) and room.slots[fid].is_ai()):
            continue
        decision_text = dr.decision_text.lower()
        if not any(kw in decision_text for kw in military_kw):
            continue

        fs = fstate.get(fid)
        if not fs or fs["troops"] <= 0:
            continue

        # Find an enemy target from the attack table
        targets_map = _FACTION_ATTACK_TARGETS.get(fid, {})
        best_target = None
        best_enemy = None
        for enemy_fid, targets in targets_map.items():
            for t in targets:
                enemy_fs = fstate.get(enemy_fid)
                if not enemy_fs:
                    continue
                if t not in enemy_fs["territories"]:
                    continue  # Already controlled by someone else
                best_target = t
                best_enemy = enemy_fid
                break
            if best_target:
                break

        if not best_target:
            continue

        enemy_fs = fstate[best_enemy]
        atk_ratio = 0.35
        atk = int(fs["troops"] * atk_ratio)
        def_troops = int(enemy_fs["troops"] / max(len(enemy_fs["territories"]), 1))
        is_south = best_target in _YANGTZE_SOUTH

        result = _resolve_combat(atk, def_troops, is_south, defender_dug_in=False)

        if result["city_falls"]:
            fs["territories"].append(best_target)
            enemy_fs["territories"].remove(best_target)
            fs["troops"] = max(0, fs["troops"] - result["attacker_losses"])
            enemy_fs["troops"] = max(0, enemy_fs["troops"] - result["defender_losses"])
            fs["morale"] = min(100, fs["morale"] + 5)
            enemy_fs["morale"] = max(0, enemy_fs["morale"] - 8)
            # Transfer population
            pop_transfer = min(enemy_fs["population"] // max(len(enemy_fs["territories"]) + 1, 1), 50000)
            fs["population"] += pop_transfer
            enemy_fs["population"] = max(1, enemy_fs["population"] - pop_transfer)
            tname = _TERR_ZH.get(best_target, best_target)
            logger.info(
                f"Room {room.id}: NPC {fid} captured {best_target}({tname}) from {best_enemy}"
            )
        elif result["siege_only"]:
            fs["troops"] = max(0, fs["troops"] - result["attacker_losses"])
            enemy_fs["troops"] = max(0, enemy_fs["troops"] - result["defender_losses"])
            enemy_fs["food"] = max(0, enemy_fs["food"] - int(enemy_fs["food"] * 0.1))
            enemy_fs["morale"] = max(0, enemy_fs["morale"] - 2)
        else:
            fs["troops"] = max(0, fs["troops"] - result["attacker_losses"])
            enemy_fs["troops"] = max(0, enemy_fs["troops"] - result["defender_losses"])

    # Write back to world_state
    for fid, fs in fstate.items():
        f = factions.get(fid)
        if f is None:
            continue
        if hasattr(f, "strength"):
            f.strength = fs["troops"]
        if hasattr(f, "territories"):
            f.territories = list(fs["territories"])
        if hasattr(f, "morale_actual"):
            f.morale_actual = fs["morale"]
        if hasattr(f, "population"):
            f.population = fs["population"]
        if hasattr(f, "food"):
            f.food = fs["food"]


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
    except Exception as e:
        logger.debug("Token usage lookup failed (non-critical): %s", e)
    return None


def _get_npc_only_ids(room_id: str) -> set[str]:
    """Return the set of faction IDs marked npc_only for a room's scenario.

    Tries multiple fallback strategies so that a transient import or disk-read
    error doesn't silently leak npc_only factions into the ranking / UI.
    """
    room = _get_room(room_id)
    if not room:
        return set()

    scenario = getattr(room, "scenario", "three-kingdoms") or "three-kingdoms"

    # Strategy 1: ScenarioLoader → load_factions() (most accurate)
    try:
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(scenario)
        factions_raw = loader.load_factions()
        return {fid for fid, f in factions_raw.items() if f.get("npc_only", False)}
    except Exception as _exc1:
        logger.debug("ScenarioLoader read failed for room=%s scenario=%s: %s", room_id, scenario, _exc1)

    # Strategy 2: Read factions.json directly
    try:
        import json as _json
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[2]  # histrategy repo root
        fp = root / "scenarios" / scenario / "knowledge" / "factions.json"
        if fp.exists():
            data = _json.loads(fp.read_text())
            if isinstance(data, list):
                return {f["id"] for f in data if f.get("npc_only", False)}
            return {fid for fid, f in data.items() if f.get("npc_only", False)}
    except Exception as _exc2:
        logger.debug("factions.json direct read failed for scenario=%s: %s", scenario, _exc2)

    # Strategy 3: Read scenario.toml npc_only list
    try:
        import tomllib as _toml
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[2]
        fp = root / "scenarios" / scenario / "scenario.toml"
        if fp.exists():
            cfg = _toml.loads(fp.read_text())
            return set(cfg.get("factions", {}).get("npc_only", []))
    except Exception as e:
        logger.debug("NPC-only ids lookup failed: %s", e)

    return set()


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
    except Exception as e:
        logger.warning("[room=%s] Faction name resolution failed: %s", room.id, e)
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
    # Final fallback: use fast_path's _FACTION_EN/_FACTION_ZH maps
    if lang == "en":
        try:
            from histrategy.engine.fast_path import _FACTION_EN
            for fid in names:
                if not names[fid] or names[fid] == fid:
                    names[fid] = _FACTION_EN.get(fid, names[fid])
        except Exception as e:
            logger.debug("Faction EN name fallback failed: %s", e)
    return names


def _write_backup(room, ws_dict):
    try:
        from histrategy.db.file_backup import cleanup_old_backups, write_room_snapshot

        write_room_snapshot(room, ws_dict, "quarter_complete")
        cleanup_old_backups(room.id, keep=20)
    except Exception as e:
        logger.warning("[room=%s] Backup write failed: %s", room.id, e)


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
    except Exception as e:
        logger.debug("Navy count failed (non-critical, old WorldState compat): %s", e)  # Old WorldState may not have armies
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
        except Exception as e:
            logger.debug("[room=%s] Population sum lookup failed: %s", room.id, e)

    return {
        "name": getattr(faction, "name", faction_id),
        "faction_id": faction_id,
        "strength": getattr(faction, "strength_actual", 0) or getattr(faction, "strength", 0) or 0,
        "food": int(getattr(faction, "food", 0) or 0),
        "treasury": int(getattr(faction, "treasury", 0) or 0),
        "territories": territories,
        "morale": getattr(faction, "morale_actual", 50) or getattr(faction, "morale", 50) or 50,
        "is_active": getattr(faction, "is_active", True),
        "population": pop_sum,
        "loyalty": getattr(faction, "loyalty", 50) or 50,
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
        # Winter prologue (T0) — historical backstory shown before first spring turn
        winter = faction_narratives.get("winter_prologue", "")
        narrative = faction_narratives.get(language_style, faction_narratives.get("vernacular", ""))
        if winter and narrative:
            narrative = winter + "\n\n---\n\n" + narrative
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
