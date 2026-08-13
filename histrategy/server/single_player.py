"""
Histrategy — Single-Player API

Thin wrapper over the multiplayer room system:
  1 human + N AI NPCs in a multiplayer room behind the scenes.
  Exposes the legacy GameCreatedResponse / CommandResponse format
  so the frontend experience is unchanged.
"""

from __future__ import annotations

import logging
import re  # for suggestion_id format matching
import re as _re_strip
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

def _strip_suggestion_tag(text: str) -> str:
    """Strip [suggestion_id] prefix from decision text for display/storage."""
    return _re_strip.sub(r'^\[[a-zA-Z0-9_]+\]\s*', '', text.strip())


def _persist_fast_path_game_state(room, fp_result: dict) -> None:
    """Write per-faction game_state + turn_delta rows after a fast-path turn.

    Args:
        room: GameRoom (already advanced to the new quarter).
        fp_result: the full simulate_fast_path() return dict, containing
            all_factions, old_factions, events_occurred, state_changes.
    """
    all_factions = fp_result.get("all_factions", {})
    if not all_factions:
        return
    from histrategy.db.models import save_game_state, save_turn_delta

    ws = getattr(room, "world_state", None)
    ws_territories = getattr(ws, "territories", {}) if ws else {}
    old_factions = fp_result.get("old_factions", {})
    events = fp_result.get("events_occurred", [])

    # ── Build reason annotations from events ──
    # Parse event strings like "大清围困福建" → type=combat, detail="qing:fujian"
    def _event_reason(event: str) -> str:
        for attacker_zh, attacker_id in [("大清", "qing"), ("南明", "nanming"),
                                          ("农民军", "nongminjun"), ("郑氏", "zheng")]:
            if event.startswith(attacker_zh):
                rest = event[len(attacker_zh):]
                if "攻陷" in rest:
                    target = rest.replace("攻陷", "")
                    return f"combat_city_fell:{attacker_id}:{target}"
                elif "围困" in rest:
                    target = rest.replace("围困", "")
                    return f"combat_siege:{attacker_id}:{target}"
                elif "守住" in rest:
                    target = rest.replace("守住", "")
                    return f"combat_defended:{attacker_id}:{target}"
        return f"combat:{event}"

    quarter = room.quarter_number

    for fid, fd in all_factions.items():
        try:
            # ── Build territory list (same as before) ──
            territories = []
            for t in fd.get("territories", []) or []:
                tid = getattr(t, "id", None) or (t if isinstance(t, str) else str(t))
                t_obj = ws_territories.get(tid) if isinstance(ws_territories, dict) else None
                territories.append({
                    "id": tid,
                    "name": getattr(t_obj, "name", tid) if t_obj else tid,
                    "population": getattr(t_obj, "population", None) if t_obj else None,
                })
            # Compute population: use faction.population as primary source.
            # Territory populations are static scenario data and may be stale.
            # faction.population is the live authoritative value.
            pop = int(fd.get("population", 0) or 0) or sum(t.get("population") or 0 for t in territories)
            if not pop:
                pop = len(territories) * 50000

            # ── Save game_state snapshot ──
            save_game_state(
                room_id=room.id,
                quarter_number=quarter,
                faction_id=fid,
                population=pop,
                troops=int(fd.get("troops", 0) or 0),
                food=float(fd.get("food", 0) or 0),
                treasury=float(fd.get("treasury", 0) or 0),
                morale=int(fd.get("morale", 50) or 50),
                territories=territories,
                policies={},
                is_active=bool(fd.get("is_active", True)),
            )

            # ── Write turn_delta entries ──
            old = old_factions.get(fid, {})
            if not old:
                continue

            # Determine which combat events affected this faction
            faction_events = []
            for evt in events:
                # Events like "大清围困福建" affect specific factions via territory owner change
                faction_events.append(evt)

            # Build composite reason from combat events
            combat_reasons = [_event_reason(e) for e in faction_events]
            combat_reason = "; ".join(combat_reasons) if combat_reasons else ""

            delta_items = [
                ("troops", int(old.get("troops", 0)), int(fd.get("troops", 0)),
                 combat_reason or "natural_attrition"),
                ("food", float(old.get("food", 0)), float(fd.get("food", 0)),
                 combat_reason or "natural_consumption"),
                ("treasury", float(old.get("treasury", 0)), float(fd.get("treasury", 0)),
                 "domestic_economy"),
                ("morale", int(old.get("morale", 50)), int(fd.get("morale", 50)),
                 combat_reason or "domestic_morale"),
            ]

            for delta_type, old_val, new_val, reason in delta_items:
                if old_val == new_val:
                    continue
                save_turn_delta(
                    room_id=room.id,
                    quarter_number=quarter,
                    faction_id=fid,
                    delta_type=delta_type,
                    old_value=float(old_val),
                    new_value=float(new_val),
                    reason=reason,
                    source="fast_path",
                )

        except Exception as e:
            logger.warning(f"Room {room.id}: game_state/turn_delta save failed for {fid} (non-fatal): {e}")

# Legacy faction key → internal ID mapping (unified to short codes; kept for compatibility)
from histrategy.engine.faction_slot import FACTION_ID_TO_DISPLAY

logger = logging.getLogger("histrategy.single_player")

FACTION_KEY_TO_ID = {"cao": "cao", "shu": "shu", "wu": "wu"}
FACTION_KEY_TO_DISPLAY = FACTION_ID_TO_DISPLAY

# Polling parameters for async NPC resolution
RESOLVE_POLL_INTERVAL = 2.0  # seconds
RESOLVE_TIMEOUT = 180.0  # seconds (max LLM wait)

# ── Command progress tracking (for frontend phase display) ──
# Keyed by game_id, stores {"phase": str, "elapsed": float, "detail": str}
# Phases: loading → parsing → simulating → narrating → done
_command_progress: dict[str, dict] = {}


def _set_progress(game_id: str, phase: str, detail: str = "") -> None:
    """Update command progress for frontend polling."""
    import time as _ptime
    _command_progress[game_id] = {
        "phase": phase,
        "elapsed": round(_ptime.time() - _command_progress.get(game_id, {}).get("_start", _ptime.time()), 1),
        "detail": detail,
        "_start": _command_progress.get(game_id, {}).get("_start", _ptime.time()),
    }


def get_command_progress(game_id: str) -> dict:
    """Return current command progress (for GET endpoint)."""
    if game_id not in _command_progress:
        return {"phase": "unknown", "elapsed": 0, "detail": ""}
    p = _command_progress[game_id]
    return {"phase": p["phase"], "elapsed": p["elapsed"], "detail": p["detail"]}


# ── Public API ────────────────────────────────────────────────────────────────


def start(
    faction: str, scenario: str = "three-kingdoms", language_style: str = "vernacular", lang: str = "zh",
    device_type: str = "unknown",
) -> dict:
    """Create a single-player game.

    Internally: creates 1-human + N-AI room → initializes world → triggers NPCs → returns intro.

    Args:
        faction: Faction key (cao | shu | wu)
        scenario: Scenario ID (default three-kingdoms)
        language_style: Narrative style (classical | vernacular)
        lang: UI language (zh | en)
        device_type: Device classification (mobile | tablet | desktop | unknown)

    Returns:
        GameCreatedResponse format:
        {game_id, scenario, faction, intro: {narrative, npc_actions, ...}, faction_status}
    """
    from histrategy.server.room_manager import (
        _get_room,
        build_faction_status_for_api,
        build_single_player_intro,
        create_room,
    )

    internal_fid = FACTION_KEY_TO_ID.get(faction, faction)
    display_fid = FACTION_KEY_TO_DISPLAY.get(faction, faction)

    # 1. Create room: 1 human (via pre_assigned) + AI NPCs auto-filled
    result = create_room(
        scenario=scenario,
        pre_assigned={display_fid: "Player"},
        metadata={"lang": lang, "device_type": device_type},
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Failed to create room")}

    room_id = result["room_id"]
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "Room not found after creation"}

    # 2. Build intro narrative
    intro = build_single_player_intro(room, internal_fid, language_style, lang)

    # 3. Build faction status
    faction_status = build_faction_status_for_api(room, internal_fid)

    return {
        "game_id": room_id,
        "scenario": scenario,
        "faction": faction,
        "intro": intro,
        "faction_status": faction_status,
    }


def command(game_id: str, decision: str, lang: str = "zh", suggestion_id: str | None = None) -> dict:
    """Execute a player command (blocks until LLM resolution completes).

    Args:
        game_id: Room ID
        decision: Player's natural-language decision
        lang: Language (zh | en). Auto-detected from room metadata if not explicit.
        suggestion_id: Optional precompute cache key. When present and cache hit,
            skips intent_parse for instant execution.
    """
    # ── Timing: _get_room
    import time as _dbgt

    from histrategy.engine.fast_path import extract_suggestion_id
    from histrategy.server.room_manager import (
        _get_room,
        _streaming_enabled,
        _trigger_npc_decisions,
        _try_save,
        build_aftermath_text,
        build_faction_status_for_api,
        build_strategic_suggestions,
        extract_turn_events,
        submit_decision,
    )
    _dbgt0 = _dbgt.time()
    room = _get_room(game_id)
    _dbgt_load = _dbgt.time()
    if not room:
        return {"ok": False, "error": "Game not found", "_debug": {"load_s": round(_dbgt_load-_dbgt0, 4)}}

    # Auto-detect lang from room metadata if not explicitly passed
    if lang == "zh":
        room_lang = getattr(room, "metadata", {}).get("lang", "zh")
        if room_lang and room_lang != "zh":
            lang = room_lang

    # Find the human faction
    human_slots = list(room.human_slots())
    if not human_slots:
        return {"ok": False, "error": "No human faction found", "_debug": {"load_s": round(_dbgt_load-_dbgt0, 4)}}
    human_fid = human_slots[0].faction_id

    # ── Fast Path: detect suggestion_id prefix → deterministic simulation ──
    # Only active for turns 1-4 (quarter_number 0-3) AND ONLY for
    # EARLY_TURNS format IDs (e.g. [shu_t1_drill]). Advisor-card IDs
    # (e.g. [sug_1719000000_0]) bypass fast path and go through V3
    # with intent cache — they're LLM-generated strategies that need
    # full simulation, not deterministic resolution.
    sid = extract_suggestion_id(decision)
    _is_early_turns_sid = bool(sid and re.match(r'^[a-z]+_t\d_', sid))
    if sid and _is_early_turns_sid and room.quarter_number < 4:
        try:
            _dbgt1 = _dbgt.time()
            # Track player's suggestion choice for Q1/Q2 NPC pre-baking
            room._last_player_suggestion_id = sid
            # Record decision on slot
            slot = room.slots.get(human_fid)
            if slot:
                slot.submit_decision(decision)

            # Run deterministic simulation
            import time as _fpt

            from histrategy.engine.fast_path import simulate_fast_path
            _fpt0 = _fpt.time()
            fp_result = simulate_fast_path(room, decision, sid, lang)
            _fpt1 = _fpt.time()
            print(f"DEBUG {game_id} fpsim elapsed={_fpt1-_fpt0:.3f}s", flush=True)

            # Store results on room object (same pattern as _resolve_and_advance)
            # Save narrative under BOTH the human faction key AND "global" so the
            # shared page (which reads narratives["global"]) renders it.
            room._last_narratives = {human_fid: fp_result["narrative"], "global": fp_result["narrative"]}
            room._last_npc_actions = fp_result.get("npc_actions", [])
            room._last_state_changes = fp_result.get("state_changes", {})

            # ── Sync faction changes back to room.world_state ──
            # simulate_fast_path modified an in-memory factions dict;
            # write those changes to room.world_state so subsequent
            # _get_room/reloads see the correct state.
            _sync_result = fp_result.get("all_factions", {})
            if _sync_result and room.world_state:
                _ws_factions = getattr(room.world_state, "factions", {})
                for _fid, _fd in _sync_result.items():
                    _wsf = _ws_factions.get(_fid)
                    if _wsf is not None:
                        _wsf.strength_actual = _fd.get("troops", getattr(_wsf, "strength_actual", 5000))
                        _wsf.morale_actual = _fd.get("morale", getattr(_wsf, "morale_actual", 50))
                        _wsf.food = _fd.get("food", getattr(_wsf, "food", 3000))
                        _wsf.treasury = _fd.get("treasury", getattr(_wsf, "treasury", 5000))
                        _wsf.territories = list(_fd.get("territories", getattr(_wsf, "territories", [])))
                        _wsf.is_active = _fd.get("is_active", True)

            # Advance quarter
            prev_quarter = room.quarter_number
            room.advance_quarter()

            # ── Pre-submit AI NPC decisions for next turn ──
            # advance_quarter() clears all slot decisions. Without this,
            # the next _get_room() call sees AI slots as unsubmitted
            # and triggers _trigger_npc_decisions() → LLM call → hang.
            _next_turn = room.quarter_number
            for _fid, _slot in room.slots.items():
                if _slot.is_ai() and _slot.is_active:
                    _slot.submit_decision(f"[{_fid}_t{_next_turn}_fp] fast-path deterministic")

            # Sync year/season from fast-path result
            room.year = fp_result.get("year", room.year)
            room.season = fp_result.get("season", room.season)

            _try_save(room)
            _fpt2 = _fpt.time()
            print(f"DEBUG _try_save elapsed={_fpt2-_fpt1:.3f}s", flush=True)

            # ── Persist per-faction game_state so the sandbox map + power
            #    ranking reflect fast-path combat results. Without this, the
            #    map falls back to the scenario baseline (initial ownership)
            #    and shows stale territory ownership after conquests. ──
            try:
                _persist_fast_path_game_state(room, fp_result)
            except Exception as e:
                logger.warning(f"Room {game_id}: fast-path game_state persist failed (non-fatal): {e}")

            # Persist npc_actions to quarter_turn DB
            # (same pattern as room_manager._save_quarter — embeds _npc_actions
            #  in narratives JSON so status() can recover them after DB reload)
            try:
                import json as _fp_json

                from histrategy.db.models import save_quarter_turn
                # Narrative under BOTH human faction key and "global" (shared page reads global)
                narratives_for_db = {human_fid: fp_result["narrative"], "global": fp_result["narrative"]}
                narratives_for_db["_npc_actions"] = _fp_json.dumps(
                    fp_result.get("npc_actions", []), ensure_ascii=False
                )
                # Build per-faction decisions: human + hard-coded NPC decisions, so the
                # shared page shows each faction's move (not just the human's).
                _fd = {human_fid: {"decision": _strip_suggestion_tag(decision), "commands": [], "source": "fast_path"}}
                for _npc_fid, _npc_text in (fp_result.get("npc_decisions") or {}).items():
                    _fd[_npc_fid] = {"decision": _npc_text, "commands": [], "source": "fast_path"}
                _fpt3 = _fpt.time()
                save_quarter_turn(
                    room.id,
                    room.quarter_number,
                    room.year,
                    room.season,
                    faction_decisions=_fd,
                    narratives=narratives_for_db,
                    state_changes=fp_result.get("state_changes", {}),
                )
                _fpt4 = _fpt.time()
                print(f"DEBUG {game_id} save_quarter_turn elapsed={_fpt4-_fpt3:.3f}s", flush=True)
                logger.info(f"Room {game_id}: quarter_turn saved with {len(fp_result.get('npc_actions', []))} npc_actions")
            except Exception as e:
                logger.warning(f"Room {game_id}: quarter_turn save failed (non-fatal): {e}")

            # Build API response
            fs = fp_result["faction_status"]
            suggestions = fp_result.get("new_suggestions", [])
            room._last_suggestions = suggestions

            # Historical footnote for education
            from histrategy.engine.helpers import get_historical_footnote
            hist_footnote = get_historical_footnote(
                room.scenario or "nanming", fs.get("turn", 1), lang)

            return {
                "game_id": game_id,
                "narrative": fp_result["narrative"],
                "aftermath": fp_result.get("aftermath", ""),
                "state_changes": fp_result.get("state_changes", {}),
                "events_occurred": fp_result.get("events_occurred", []),
                "npc_actions": fp_result.get("npc_actions", []),
                "new_suggestions": suggestions,
                "historical_footnote": hist_footnote,
                "game_over": None,
                "faction_status": fs,
                "year": fs.get("year", room.year),
                "season": fs.get("season", room.season),
                "turn": fs.get("turn", room.quarter_number),
                "_debug": {"fast_path": True, "sid": sid,
                           "load_s": round(_dbgt_load - _dbgt0, 4),
                           "t_entry": round(_dbgt1 - _dbgt0, 4),
                           "t_total": round(_dbgt.time() - _dbgt0, 4)},
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"fast-path exception: {e}",
                "_debug": {"fast_path": False, "sid": sid, "error": str(e)},
            }

    # ── Normal LLM path ──

    # Record quarter before submit (must happen BEFORE submit_decision!)
    prev_quarter = room.quarter_number

    # Streaming mode: settle state now, defer narrative to narrative-live-stream.
    streaming = _streaming_enabled()

    # 1. Submit decision → synchronous resolve (submit_decision calls _resolve_and_advance internally)
    submit_result = submit_decision(game_id, human_fid, decision, skip_narrative=streaming)
    if not submit_result.get("ok"):
        return {"ok": False, "error": submit_result.get("error", "Decision submission failed")}

    # 2. Check if resolve completed (synchronous call, should be done already)
    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "Game lost during resolution"}

    # Restore _last_narratives and _last_state_changes from quarter_turn table — survives DB reload
    if not getattr(room, "_last_narratives", None) or not getattr(room, "_last_state_changes", None) or not getattr(room, "_last_npc_actions", None):
        try:
            from histrategy.db.models import get_quarter_turns

            db_turns = get_quarter_turns(game_id, limit=1)
            if db_turns:
                latest = db_turns[-1]
                import json as _json

                narratives = {}
                if not getattr(room, "_last_narratives", None):
                    narratives_raw = latest.get("narratives")
                    narratives = _json.loads(narratives_raw) if isinstance(narratives_raw, str) else (narratives_raw or {})
                    room._last_narratives = narratives

                if not getattr(room, "_last_state_changes", None):
                    sc_raw = latest.get("state_changes")
                    sc = _json.loads(sc_raw) if isinstance(sc_raw, str) else (sc_raw or {})
                    room._last_state_changes = sc

                if not getattr(room, "_last_npc_actions", None):
                    npc_raw = narratives.get("_npc_actions") if narratives else None
                    if isinstance(npc_raw, str):
                        room._last_npc_actions = _json.loads(npc_raw)
                    elif isinstance(npc_raw, list):
                        room._last_npc_actions = npc_raw
        except Exception:
            pass

    # ⛔ Idempotency: if quarter already advanced, the turn was resolved.
    #    This prevents duplicate resolves when the frontend retries commands.
    if room.quarter_number <= prev_quarter:
        # Check if a quarter_turn already exists for the upcoming quarter
        # (race condition: another request may have resolved while we waited)
        try:
            from histrategy.db.models import get_quarter_turns
            existing = get_quarter_turns(game_id, limit=1)
            if existing and existing[-1].get("quarter_number", 0) > prev_quarter:
                logger.info(
                    f"Room {game_id}: quarter_turn for Q{existing[-1]['quarter_number']} already exists — skipping re-resolve"
                )
                # Reload room to get latest narratives
                room = _get_room(game_id)
            else:
                raise RuntimeError("turn not resolved yet")
        except Exception:
            logger.info(
                f"Room {game_id}: quarter unchanged ({prev_quarter}) — triggering NPC decisions sync"
            )
            try:
                _trigger_npc_decisions(room)
                submit_decision(game_id, human_fid, decision)
            except Exception as e:
                logger.warning(f"Room {game_id}: sync NPC trigger failed: {e}")

            room = _get_room(game_id)
            if not room or room.quarter_number <= prev_quarter:
                return {"ok": False, "error": "Resolution failed, please retry"}

    # 3. Read resolution results
    narratives = getattr(room, "_last_narratives", {})
    npc_actions = getattr(room, "_last_npc_actions", [])

    narrative = narratives.get(human_fid, "")
    if not narrative:
        # Fallback: use the first non-empty narrative. Skip internal keys
        # (e.g. "_npc_actions", which stores a JSON blob, not prose).
        for key, n in narratives.items():
            if key.startswith("_"):
                continue
            if n:
                narrative = n
                break

    # 4. Build response
    faction_status = build_faction_status_for_api(room, human_fid)
    suggestions = build_strategic_suggestions(room, human_fid, lang)
    room._last_suggestions = suggestions  # persist for status() API

    # Retrieve state_changes from resolution result (stored on room by _resolve_and_advance)
    state_changes = getattr(room, "_last_state_changes", {}) or {}

    # Streaming mode: narrative was deferred. Signal the client to open the
    # narrative-live-stream SSE endpoint. State/map/ranking are already final.
    from histrategy.server.room_manager import _peek_narrative_context

    narrative_pending = bool(streaming and _peek_narrative_context(game_id))
    logger.info(
        "[room=%s] command() returning: streaming=%s narrative_pending=%s stash_exists=%s",
        game_id, streaming, narrative_pending, bool(_peek_narrative_context(game_id)),
    )

    return {
        "ok": True,
        "game_id": game_id,
        "narrative": narrative or ("" if narrative_pending else "The realm is at peace."),
        "narrative_pending": narrative_pending,
        "aftermath": build_aftermath_text(faction_status, lang),
        "state_changes": state_changes,
        "events_occurred": extract_turn_events(room),
        "npc_actions": npc_actions,
        "new_suggestions": suggestions,
        "game_over": None,
        "faction_status": faction_status,
        "year": faction_status.get("year", 207),
        "season": faction_status.get("season", "春"),
        "turn": faction_status.get("turn", 0),
        "_debug": {"fast_path": False, "sid": None, "streaming": streaming},
    }


def status(game_id: str) -> dict:
    """Get current game status.

    Args:
        game_id: Room ID

    Returns:
        {game_id, year, season, turn, faction_status, npc_actions, is_waiting}
    """
    from histrategy.server.room_manager import _get_room, build_faction_status_for_api, build_strategic_suggestions

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "Game not found"}

    human_slots = list(room.human_slots())
    human_fid = human_slots[0].faction_id if human_slots else None
    faction_status = build_faction_status_for_api(room, human_fid) if human_fid else {}
    npc_actions = getattr(room, "_last_npc_actions", [])
    if not npc_actions:
        # Fallback: load from quarter_turn DB (survives pod restart / DB reload)
        try:
            from histrategy.db.models import get_quarter_turns as _gqt3
            db_turns = _gqt3(game_id, limit=1)
            if db_turns:
                nr = db_turns[-1].get("narratives")
                import json as _json3
                loaded = _json3.loads(nr) if isinstance(nr, str) else (nr or {})
                na_raw = loaded.get("_npc_actions")
                if isinstance(na_raw, str):
                    npc_actions = _json3.loads(na_raw)
                elif isinstance(na_raw, list):
                    npc_actions = na_raw
                if npc_actions:
                    room._last_npc_actions = npc_actions  # cache
        except Exception:
            pass
    lang = (room.metadata or {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"
    suggestions = getattr(room, "_last_suggestions", []) or (build_strategic_suggestions(room, human_fid, lang) if human_fid else [])

    return {
        "game_id": game_id,
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
        "faction_status": faction_status,
        "npc_actions": npc_actions,
        "new_suggestions": suggestions,
        "is_waiting": room.phase.value == "waiting",
    }
