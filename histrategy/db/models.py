"""
Database models — thin ORM wrappers for histrategy's SQL tables.

All models use TEXT for UUIDs (SQLite/PostgreSQL compatible).
JSON fields are serialized/deserialized via json.dumps/loads.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .connection import execute, execute_one, execute_write, json_dumps, json_loads

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom


# ── GameRoom DB Model ────────────────────────────────────


def save_room(room: GameRoom, world_state_dict: dict | None = None):
    """INSERT or UPDATE a GameRoom in the database.

    Args:
        room: GameRoom to save
        world_state_dict: WorldState serialized to dict
    """
    from histrategy.engine.game_room import RoomPhase

    existing = execute_one(
        "SELECT id FROM game_room WHERE id = ?", (room.id,)
    )

    slots_json = json_dumps({
        fid: s.to_dict() for fid, s in room.slots.items()
    })
    summaries_json = json_dumps(room.turn_summaries)
    ws_json = json_dumps(world_state_dict) if world_state_dict else None
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        execute_write(
            """UPDATE game_room SET
                year = ?, season = ?, quarter_number = ?, phase = ?,
                world_state = ?, slots = ?, turn_summaries = ?,
                updated_at = ?
            WHERE id = ?""",
            (
                room.year, room.season, room.quarter_number,
                room.phase.value, ws_json, slots_json,
                summaries_json, now, room.id,
            ),
        )
    else:
        execute_write(
            """INSERT INTO game_room
                (id, host_user_id, scenario, year, season, quarter_number,
                 phase, world_state, slots, decision_timeout,
                 turn_summaries, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                room.id, room.host_user_id, room.scenario,
                room.year, room.season, room.quarter_number,
                room.phase.value, ws_json, slots_json,
                room.decision_timeout, summaries_json, now, now,
            ),
        )

    # Save individual faction slots
    _save_faction_slots(room)


def _save_faction_slots(room: GameRoom):
    """Save all FactionSlots for a room."""
    now = datetime.now(timezone.utc).isoformat()

    for faction_id, slot in room.slots.items():
        slot_id = f"{room.id}_{faction_id}"
        existing = execute_one(
            "SELECT id FROM faction_slot WHERE id = ?", (slot_id,)
        )

        commands_json = json_dumps(slot.pending_commands) if slot.pending_commands else None

        if existing:
            execute_write(
                """UPDATE faction_slot SET
                    occupant_type = ?, occupant_id = ?,
                    pending_decision = ?, pending_commands = ?,
                    is_active = ?, updated_at = ?
                WHERE id = ?""",
                (
                    slot.occupant_type.value,
                    slot.occupant_id,
                    slot.pending_decision,
                    commands_json,
                    1 if slot.is_active else 0,
                    now,
                    slot_id,
                ),
            )
        else:
            execute_write(
                """INSERT INTO faction_slot
                    (id, room_id, faction_id, occupant_type, occupant_id,
                     ai_model, ai_temperature, pending_decision,
                     pending_commands, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slot_id, room.id, faction_id,
                    slot.occupant_type.value,
                    slot.occupant_id,
                    slot.ai_model,
                    slot.ai_temperature,
                    slot.pending_decision,
                    commands_json,
                    1 if slot.is_active else 0,
                    now, now,
                ),
            )


def load_room(room_id: str) -> GameRoom | None:
    """Load a GameRoom from the database.

    Returns None if room not found.
    """
    from histrategy.engine.game_room import GameRoom, RoomPhase
    from histrategy.engine.faction_slot import FactionSlot

    row = execute_one("SELECT * FROM game_room WHERE id = ?", (room_id,))
    if not row:
        return None

    slots_data = json_loads(row.get("slots", "{}")) or {}
    slots = {}
    for fid, sd in slots_data.items():
        slots[fid] = FactionSlot.from_dict(sd)

    turn_summaries = json_loads(row.get("turn_summaries", "[]")) or []

    room = GameRoom(
        id=row["id"],
        host_user_id=row.get("host_user_id"),
        scenario=row.get("scenario", "207"),
        year=row.get("year", 207),
        season=row.get("season", "春"),
        quarter_number=row.get("quarter_number", 0),
        phase=RoomPhase(row.get("phase", "lobby")),
        decision_timeout=row.get("decision_timeout", 300),
        turn_summaries=turn_summaries,
    )
    room.slots = slots

    return room


def load_world_state_dict(room_id: str) -> dict | None:
    """Load just the world_state JSON from a room (without rebuilding GameRoom)."""
    row = execute_one(
        "SELECT world_state FROM game_room WHERE id = ?", (room_id,)
    )
    if not row:
        return None
    return json_loads(row.get("world_state"))


# ── Quarter Turn DB ──────────────────────────────────────


def save_quarter_turn(
    room_id: str,
    quarter_number: int,
    year: int,
    season: str,
    faction_decisions: dict,
    baseline_result: dict | None = None,
    macro_delta: dict | None = None,
    narratives: dict | None = None,
    state_changes: dict | None = None,
    token_usage: dict | None = None,
) -> str:
    """Save a quarter_turn record. Returns the new record ID."""
    turn_id = str(uuid.uuid4())

    execute_write(
        """INSERT INTO quarter_turn
            (id, room_id, quarter_number, year, season,
             faction_decisions, baseline_result, macro_delta,
             narratives, state_changes, token_usage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            turn_id, room_id, quarter_number, year, season,
            json_dumps(faction_decisions),
            json_dumps(baseline_result) if baseline_result else None,
            json_dumps(macro_delta) if macro_delta else None,
            json_dumps(narratives) if narratives else None,
            json_dumps(state_changes) if state_changes else None,
            json_dumps(token_usage) if token_usage else None,
        ),
    )
    return turn_id


def get_quarter_turns(room_id: str, limit: int = 10) -> list[dict]:
    """Get recent quarter turns for a room."""
    return execute(
        """SELECT * FROM quarter_turn
        WHERE room_id = ?
        ORDER BY quarter_number DESC
        LIMIT ?""",
        (room_id, limit),
    )


# ── LLM Call Log ─────────────────────────────────────────


def log_llm_call(
    room_id: str,
    quarter_number: int,
    call_type: str,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    reasoning_tokens: int | None = None,
    latency_ms: int = 0,
    system_prompt_type: str | None = None,
    user_prompt: str | None = None,
    response: str | None = None,
    error: str | None = None,
    faction_id: str | None = None,
) -> str:
    """Log an LLM call. Returns the log ID."""
    log_id = str(uuid.uuid4())

    execute_write(
        """INSERT INTO llm_call_log
            (id, room_id, quarter_number, call_type, faction_id,
             provider, model, prompt_tokens, completion_tokens,
             total_tokens, reasoning_tokens, latency_ms,
             system_prompt_type, user_prompt, response, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            log_id, room_id, quarter_number, call_type, faction_id,
            provider, model, prompt_tokens, completion_tokens,
            total_tokens, reasoning_tokens, latency_ms,
            system_prompt_type, user_prompt, response, error,
        ),
    )
    return log_id


# ── Simulation Event Log ─────────────────────────────────


def log_sim_event(
    room_id: str,
    quarter_number: int,
    event_type: str,
    event_data: dict | None = None,
) -> str:
    """Log a simulation event. Returns the event ID."""
    event_id = str(uuid.uuid4())

    execute_write(
        """INSERT INTO simulation_event_log
            (id, room_id, quarter_number, event_type, event_data)
        VALUES (?, ?, ?, ?, ?)""",
        (
            event_id, room_id, quarter_number,
            event_type, json_dumps(event_data) if event_data else None,
        ),
    )
    return event_id
