"""
Database models — thin ORM wrappers for histrategy's SQL tables.

All models use TEXT for UUIDs (SQLite/PostgreSQL compatible).
JSON fields are serialized/deserialized via json.dumps/loads.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .connection import _IS_SQLITE, execute, execute_one, execute_write, json_dumps, json_loads

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom


# ── GameRoom DB Model ────────────────────────────────────


def save_room(room: GameRoom, world_state_dict: dict | None = None):
    """INSERT or UPDATE a GameRoom in the database.

    Args:
        room: GameRoom to save
        world_state_dict: WorldState serialized to dict
    """

    existing = execute_one("SELECT id FROM game_room WHERE id = ?", (room.id,))

    slots_json = json_dumps({fid: s.to_dict() for fid, s in room.slots.items()})
    summaries_json = json_dumps(room.turn_summaries)
    metadata_json = json_dumps(getattr(room, "metadata", {}))
    ws_json = json_dumps(world_state_dict) if world_state_dict else None
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        execute_write(
            """UPDATE game_room SET
                year = ?, season = ?, quarter_number = ?, phase = ?,
                world_state = ?, slots = ?, turn_summaries = ?,
                is_public = ?, updated_at = ?
            WHERE id = ?""",
            (
                room.year,
                room.season,
                room.quarter_number,
                room.phase.value,
                ws_json,
                slots_json,
                summaries_json,
                1 if room.is_public else 0,
                now,
                room.id,
            ),
        )
        # If metadata column exists, update it too
        with contextlib.suppress(Exception):
            execute_write(
                "UPDATE game_room SET metadata = ? WHERE id = ?",
                (metadata_json, room.id),
            )
    else:
        execute_write(
            """INSERT INTO game_room
                (id, scenario, year, season, quarter_number,
                 phase, world_state, slots, decision_timeout,
                 turn_summaries, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                room.id,
                room.scenario,
                room.year,
                room.season,
                room.quarter_number,
                room.phase.value,
                ws_json,
                slots_json,
                room.decision_timeout,
                summaries_json,
                now,
                now,
            ),
        )
        # If metadata column exists, set it
        with contextlib.suppress(Exception):
            execute_write(
                "UPDATE game_room SET metadata = ? WHERE id = ?",
                (metadata_json, room.id),
            )






def load_room(room_id: str) -> GameRoom | None:
    """Load a GameRoom from the database, including world_state.

    Returns None if room not found.
    """
    from histrategy.engine.faction_slot import FactionSlot
    from histrategy.engine.game_room import GameRoom, RoomPhase

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
        scenario=row.get("scenario", "three-kingdoms"),
        year=row.get("year", 207),
        season=row.get("season", "春"),
        quarter_number=row.get("quarter_number", 0),
        phase=RoomPhase(row.get("phase", "lobby")),
        decision_timeout=row.get("decision_timeout", 300),
        turn_summaries=turn_summaries,
        is_public=bool(row.get("is_public", 0)),
    )
    room.slots = slots

    # Restore major_npc_ids from slots (any AI_NPC type = major NPC)
    # This survives DB roundtrip without needing a schema migration
    room.major_npc_ids = {fid for fid, s in slots.items() if s.occupant_type.value == "ai_npc" and s.is_active}

    # Restore metadata (lang, etc.) — survives server restart
    metadata_raw = row.get("metadata")
    if metadata_raw:
        try:
            room.metadata = json_loads(metadata_raw) or {}
        except Exception:
            room.metadata = {}

    # Restore world_state from DB (survives server restart)
    ws_data = json_loads(row.get("world_state"))
    if ws_data:
        try:
            from histrategy_engine.world import WorldState as WS

            ws = WS()
            # Map season string → season_index (to_dict uses "spring", from_dict expects int)
            _SEASON_MAP = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
            if "season" in ws_data and "season_index" not in ws_data:
                ws_data["season_index"] = _SEASON_MAP.get(ws_data["season"], 0)
            ws.from_dict(ws_data)
            room.world_state = ws
        except Exception:
            pass  # Graceful degradation — room loads without world state if corrupt

    return room


def load_world_state_dict(room_id: str) -> dict | None:
    """Load just the world_state JSON from a room (without rebuilding GameRoom)."""
    row = execute_one("SELECT world_state FROM game_room WHERE id = ?", (room_id,))
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
    now = datetime.now(timezone.utc).isoformat()

    execute_write(
        """INSERT INTO quarter_turn
            (id, room_id, quarter_number, year, season,
             faction_decisions, baseline_result, macro_delta,
             narratives, state_changes, token_usage, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            turn_id,
            room_id,
            quarter_number,
            year,
            season,
            json_dumps(faction_decisions),
            json_dumps(baseline_result) if baseline_result else None,
            json_dumps(macro_delta) if macro_delta else None,
            json_dumps(narratives) if narratives else None,
            json_dumps(state_changes) if state_changes else None,
            json_dumps(token_usage) if token_usage else None,
            now,
        ),
    )
    return turn_id


def update_quarter_turn_narratives(room_id: str, quarter_number: int, narratives: dict) -> None:
    """Update the narratives JSON on the existing quarter_turn row(s).

    Used by streaming mode: the row is first written (during settle) with only
    _npc_actions, then the deferred narrative is generated + streamed and
    written back here — avoiding a duplicate INSERT for the same quarter.
    """
    execute_write(
        "UPDATE quarter_turn SET narratives = ? WHERE room_id = ? AND quarter_number = ?",
        (json_dumps(narratives) if narratives else None, room_id, quarter_number),
    )


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
             system_prompt_type, user_prompt, response, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            log_id,
            room_id,
            quarter_number,
            call_type,
            faction_id,
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            reasoning_tokens,
            latency_ms,
            system_prompt_type,
            user_prompt,
            response,
            error,
            datetime.utcnow().isoformat(),
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
            (id, room_id, quarter_number, event_type, event_data, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            room_id,
            quarter_number,
            event_type,
            json_dumps(event_data) if event_data else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return event_id


# ── Game State (world state snapshot) ────────────────────


def save_game_state(
    room_id: str,
    quarter_number: int,
    faction_id: str,
    population: int = 0,
    troops: int = 0,
    food: float = 0,
    treasury: float = 0,
    morale: int = 50,
    territories: list | None = None,
    policies: dict | None = None,
    is_active: bool = True,
) -> str:
    """Save a faction's game state snapshot for a quarter.

    Returns the state ID.
    """
    state_id = str(uuid.uuid4())

    # Cross-DB upsert: SQLite uses INSERT OR REPLACE, PostgreSQL uses ON CONFLICT
    if _IS_SQLITE:
        execute_write(
            """INSERT OR REPLACE INTO game_state
                (id, room_id, quarter_number, faction_id,
                 population, troops, food, treasury, morale,
                 territories, policies, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state_id,
                room_id,
                quarter_number,
                faction_id,
                population,
                troops,
                food,
                treasury,
                morale,
                json_dumps(territories) if territories else "[]",
                json_dumps(policies) if policies else "{}",
                1 if is_active else 0,
            ),
        )
    else:
        execute_write(
            """INSERT INTO game_state
                (id, room_id, quarter_number, faction_id,
                 population, troops, food, treasury, morale,
                 territories, policies, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (room_id, quarter_number, faction_id) DO UPDATE SET
                population = EXCLUDED.population,
                troops = EXCLUDED.troops,
                food = EXCLUDED.food,
                treasury = EXCLUDED.treasury,
                morale = EXCLUDED.morale,
                territories = EXCLUDED.territories,
                policies = EXCLUDED.policies,
                is_active = EXCLUDED.is_active""",
            (
                state_id,
                room_id,
                quarter_number,
                faction_id,
                population,
                troops,
                food,
                treasury,
                morale,
                json_dumps(territories) if territories else "[]",
                json_dumps(policies) if policies else "{}",
                1 if is_active else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return state_id


def get_game_state(room_id: str, quarter_number: int, faction_id: str) -> dict | None:
    """Get a faction's game state for a specific quarter."""
    row = execute_one(
        """SELECT * FROM game_state
        WHERE room_id = ? AND quarter_number = ? AND faction_id = ?""",
        (room_id, quarter_number, faction_id),
    )
    if not row:
        return None
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "quarter_number": row["quarter_number"],
        "faction_id": row["faction_id"],
        "population": row["population"],
        "troops": row["troops"],
        "food": row["food"],
        "treasury": row["treasury"],
        "morale": row["morale"],
        "territories": json_loads(row.get("territories", "[]")),
        "policies": json_loads(row.get("policies", "{}")),
        "is_active": bool(row.get("is_active", 1)),
    }


def get_latest_game_states(room_id: str, quarter_number: int) -> list[dict]:
    """Get all factions' latest game states for a quarter."""
    return execute(
        """SELECT * FROM game_state
        WHERE room_id = ? AND quarter_number = ?
        ORDER BY faction_id""",
        (room_id, quarter_number),
    )


# ── Turn Delta (per-turn incremental changes) ──────────


def save_turn_delta(
    room_id: str,
    quarter_number: int,
    faction_id: str,
    delta_type: str,
    old_value: float,
    new_value: float,
    reason: str = "",
    source: str = "deterministic",
) -> str:
    """Save a per-turn delta record. Returns the delta ID."""
    delta_id = str(uuid.uuid4())
    delta = new_value - old_value
    now = datetime.now(timezone.utc).isoformat()

    execute_write(
        """INSERT INTO turn_delta
            (id, room_id, quarter_number, faction_id, delta_type,
             old_value, new_value, delta, reason, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            delta_id,
            room_id,
            quarter_number,
            faction_id,
            delta_type,
            old_value,
            new_value,
            delta,
            reason,
            source,
            now,
        ),
    )
    return delta_id


def get_turn_deltas(room_id: str, quarter_number: int) -> list[dict]:
    """Get all deltas for a quarter."""
    return execute(
        """SELECT * FROM turn_delta
        WHERE room_id = ? AND quarter_number = ?
        ORDER BY faction_id, delta_type""",
        (room_id, quarter_number),
    )


# ── Policy State (policies / tech tree) ─────────────────


def save_policy_state(
    room_id: str,
    quarter_number: int,
    faction_id: str,
    policy_type: str,
    policy_name: str,
    policy_level: int = 1,
    params: dict | None = None,
    status: str = "active",
) -> str:
    """Save a policy/tech state. Returns the policy ID."""
    policy_id = str(uuid.uuid4())

    if _IS_SQLITE:
        execute_write(
            """INSERT OR REPLACE INTO policy_state
                (id, room_id, quarter_number, faction_id, policy_type,
                 policy_name, policy_level, params, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                policy_id,
                room_id,
                quarter_number,
                faction_id,
                policy_type,
                policy_name,
                policy_level,
                json_dumps(params) if params else "{}",
                status,
            ),
        )
    else:
        execute_write(
            """INSERT INTO policy_state
                (id, room_id, quarter_number, faction_id, policy_type,
                 policy_name, policy_level, params, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (room_id, faction_id, policy_name, status) DO UPDATE SET
                quarter_number = EXCLUDED.quarter_number,
                policy_type = EXCLUDED.policy_type,
                policy_level = EXCLUDED.policy_level,
                params = EXCLUDED.params""",
            (
                policy_id,
                room_id,
                quarter_number,
                faction_id,
                policy_type,
                policy_name,
                policy_level,
                json_dumps(params) if params else "{}",
                status,
            ),
        )
    return policy_id


def get_active_policies(room_id: str, faction_id: str) -> list[dict]:
    """Get all active policies for a faction."""
    return execute(
        """SELECT * FROM policy_state
        WHERE room_id = ? AND faction_id = ? AND status = 'active'
        ORDER BY quarter_number""",
        (room_id, faction_id),
    )


def get_policies_by_quarter(room_id: str, quarter_number: int) -> list[dict]:
    """Get all policies for all factions at a specific quarter."""
    return execute(
        """SELECT * FROM policy_state
        WHERE room_id = ? AND quarter_number = ?
        ORDER BY faction_id, policy_name""",
        (room_id, quarter_number),
    )


def revoke_policy(room_id: str, faction_id: str, policy_name: str) -> bool:
    """Revoke a policy. Returns True if any row was updated."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    result = execute_write(
        """UPDATE policy_state
        SET status = 'revoked', revoked_at = ?
        WHERE room_id = ? AND faction_id = ? AND policy_name = ? AND status = 'active'""",
        (now, room_id, faction_id, policy_name),
    )
    return result > 0
