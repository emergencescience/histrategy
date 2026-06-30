"""
Histrategy — Single-Player API

Thin wrapper over the multiplayer room system:
  1 human + N AI NPCs in a multiplayer room behind the scenes.
  Exposes the legacy GameCreatedResponse / CommandResponse format
  so the frontend experience is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Legacy faction key → internal ID mapping (unified to short codes; kept for compatibility)
from histrategy.engine.faction_slot import FACTION_ID_TO_DISPLAY

logger = logging.getLogger("histrategy.single_player")

FACTION_KEY_TO_ID = {"cao": "cao", "shu": "shu", "wu": "wu"}
FACTION_KEY_TO_DISPLAY = FACTION_ID_TO_DISPLAY

# Polling parameters for async NPC resolution
RESOLVE_POLL_INTERVAL = 2.0  # seconds
RESOLVE_TIMEOUT = 180.0  # seconds (max LLM wait)


# ── Public API ────────────────────────────────────────────────────────────────


def start(
    faction: str, scenario: str = "three-kingdoms", language_style: str = "vernacular", lang: str = "zh"
) -> dict:
    """Create a single-player game.

    Internally: creates 1-human + N-AI room → initializes world → triggers NPCs → returns intro.

    Args:
        faction: Faction key (cao | shu | wu)
        scenario: Scenario ID (default three-kingdoms)
        language_style: Narrative style (classical | vernacular)
        lang: UI language (zh | en)

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
        metadata={"lang": lang},
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


def command(game_id: str, decision: str, lang: str = "zh") -> dict:
    """Execute a player command (blocks until LLM resolution completes).

    Args:
        game_id: Room ID
        decision: Player's natural-language decision
        lang: Language (zh | en). Auto-detected from room metadata if not explicit.
    """
    from histrategy.server.room_manager import (
        _get_room,
        _trigger_npc_decisions,
        build_aftermath_text,
        build_faction_status_for_api,
        build_strategic_suggestions,
        extract_turn_events,
        submit_decision,
    )

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "Game not found"}

    # Auto-detect lang from room metadata if not explicitly passed
    if lang == "zh":
        room_lang = getattr(room, "metadata", {}).get("lang", "zh")
        if room_lang and room_lang != "zh":
            lang = room_lang

    # Find the human faction
    human_slots = list(room.human_slots())
    if not human_slots:
        return {"ok": False, "error": "No human faction found"}
    human_fid = human_slots[0].faction_id

    # Record quarter before submit (must happen BEFORE submit_decision!)
    prev_quarter = room.quarter_number

    # 1. Submit decision → synchronous resolve (submit_decision calls _resolve_and_advance internally)
    submit_result = submit_decision(game_id, human_fid, decision)
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

    if room.quarter_number <= prev_quarter:
        # NPC decisions may not have been generated yet (async thread delay).
        # Attempt synchronous NPC trigger and re-resolve.
        logger.info(f"Room {game_id}: quarter unchanged ({prev_quarter}) — triggering NPC decisions sync")
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
        # Fallback: use the first non-empty narrative
        for n in narratives.values():
            if n:
                narrative = n
                break

    # 4. Build response
    faction_status = build_faction_status_for_api(room, human_fid)
    suggestions = build_strategic_suggestions(room, human_fid, lang)
    room._last_suggestions = suggestions  # persist for status() API

    # Retrieve state_changes from resolution result (stored on room by _resolve_and_advance)
    state_changes = getattr(room, "_last_state_changes", {}) or {}

    return {
        "game_id": game_id,
        "narrative": narrative or "The realm is at peace.",
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
    suggestions = getattr(room, "_last_suggestions", []) or (build_strategic_suggestions(room, human_fid, "zh") if human_fid else [])

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
