"""
Database models — thin ORM wrappers for histrategy's SQL tables.

All models use TEXT for UUIDs (SQLite/PostgreSQL compatible).
JSON fields are serialized/deserialized via json.dumps/loads.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .connection import _IS_SQLITE, execute, execute_one, execute_write, json_dumps, json_loads

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom


# ── GameRoom DB Model ────────────────────────────────────


def _serialize_world_state(ws) -> dict | None:
    """Serialize a WorldState to a JSON-safe dict for DB persistence.

    Two WorldState flavors exist:
    - local `histrategy.state.world_state.WorldState` — has `to_dict()`
    - engine `histrategy_engine.world.WorldState` (dataclass) — has NO
      `to_dict()`, contains enum fields (Season, TerrainType, UnitType,
      HistoricalMode) that json.dumps cannot handle directly.
    This helper handles both, recursively converting enums to `.value`.
    """
    if ws is None:
        return None
    if hasattr(ws, "to_dict"):
        return ws.to_dict()
    # Engine dataclass flavor — serialize via dataclasses.asdict + enum unwrap
    from dataclasses import asdict

    return _json_safe_deep_convert(asdict(ws))


def _json_safe_deep_convert(obj):
    """Recursively convert Enum keys/values to strings for JSON serialization.

    Handles dataclass objects, dicts with Enum keys (e.g. UnitType in army
    units), lists, tuples, and individual Enum values.
    """
    from dataclasses import asdict, is_dataclass
    from enum import Enum

    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return {k: _json_safe_deep_convert(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _json_safe_deep_convert(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe_deep_convert(v) for v in obj]
    return obj


def save_room(room: GameRoom, world_state_dict: dict | None = None):
    """INSERT or UPDATE a GameRoom in the database.

    Args:
        room: GameRoom to save
        world_state_dict: WorldState serialized to dict. If None, it is
            auto-extracted from ``room.world_state`` (handles both local and
            engine WorldState flavors) — so a bare ``save_room(room)`` can
            never accidentally NULL out the persisted world state.
    """
    if world_state_dict is None and room.world_state is not None:
        world_state_dict = _serialize_world_state(room.world_state)

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
                is_public = ?, engine_version = ?, updated_at = ?
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
                os.environ.get("HISTRATEGY_ENGINE", ""),
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
                 turn_summaries, engine_version, created_at, updated_at, host_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                os.environ.get("HISTRATEGY_ENGINE", ""),
                now,
                now,
                getattr(room, "host_user_id", ""),
            ),
        )
        # If metadata column exists, set it
        with contextlib.suppress(Exception):
            execute_write(
                "UPDATE game_room SET metadata = ? WHERE id = ?",
                (metadata_json, room.id),
            )






def deserialize_world_state(ws_data: dict) -> "WorldState":
    """Rebuild a full engine WorldState from a DB-persisted dict.

    NOTE: engine WS.from_dict() only restores factions + basic fields —
    it DROPS territories/armies/characters. We rebuild them manually so
    Rome V3 rooms keep their land/armies across reloads (else resolve
    degrades to empty world state).

    Raises ValueError on missing/corrupt data instead of silently falling
    back to Three Kingdoms defaults (207 AD is wrong for e.g.
    rome-triumvirate).
    """
    from histrategy_engine.world import (
        Army,
        Character,
        FactionState,
        Season,
        StrategicPoint,
        Territory,
        WorldState as WS,
    )
    from histrategy.engine.scenario_loader import _coerce_factions_to_dict as _cfd

    # Map season string → season_index (to_dict uses "spring", from_dict expects int)
    _SEASON_MAP = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
    _SEASON_NAMES = ["spring", "summer", "autumn", "winter"]
    if "season" in ws_data and "season_index" not in ws_data:
        season_str = ws_data["season"]
        if season_str not in _SEASON_MAP:
            raise ValueError(f"invalid season in world_state: {season_str!r}")
        ws_data["season_index"] = _SEASON_MAP[season_str]
    elif "season_index" not in ws_data and "season" not in ws_data:
        raise ValueError("world_state missing required field 'season'")

    ws = WS()
    if "year" not in ws_data:
        raise ValueError("world_state missing required field 'year' (refusing to fall back to 207)")
    ws.year = ws_data["year"]
    ws.turn_number = ws_data.get("turn_number", ws_data.get("turn", 1))
    si = ws_data.get("season_index", 0)
    try:
        ws.season = Season(_SEASON_NAMES[si % 4])
    except Exception:
        try:
            ws.season = Season(ws_data.get("season", "spring"))
        except Exception:
            raise ValueError(f"invalid season in world_state: {ws_data.get('season')!r}")
    if "scenario" not in ws_data:
        raise ValueError("world_state missing required field 'scenario'")
    ws.scenario = ws_data["scenario"]
    ws.player_faction_id = ws_data.get("player_faction_id", "")
    ws.player_deviation = ws_data.get("player_deviation", 0.0)
    ws.completed_events = list(ws_data.get("completed_events", []) or [])
    ws.event_history = list(ws_data.get("event_history", ws_data.get("event_log", [])) or [])

    # Rebuild factions
    for fid, fd in (ws_data.get("factions") or {}).items():
        try:
            ws.factions[fid] = FactionState(**{k: v for k, v in fd.items() if k in FactionState.__dataclass_fields__})
        except Exception:
            ws.factions[fid] = FactionState(id=fid, name=fd.get("name", fid), ruler_id=fd.get("ruler_id", fid))

    # Rebuild territories (with enum terrain_type)
    from enum import Enum as _Enum
    from histrategy_engine.world import TerrainType

    def _enum(cls, val):
        if val is None:
            return None
        if isinstance(val, cls):
            return val
        try:
            return cls(val)
        except Exception:
            return None

    for tid, td in (ws_data.get("territories") or {}).items():
        try:
            td2 = dict(td)
            td2["terrain_type"] = _enum(TerrainType, td.get("terrain_type"))
            sps = td.get("strategic_points") or []
            td2["strategic_points"] = [
                StrategicPoint(**sp) if isinstance(sp, dict) else sp for sp in sps
            ]
            ws.territories[tid] = Territory(**{k: v for k, v in td2.items() if k in Territory.__dataclass_fields__})
        except Exception:
            pass  # skip corrupt territory

    # Rebuild characters
    for cid, cd in (ws_data.get("characters") or {}).items():
        try:
            ws.characters[cid] = Character(**{k: v for k, v in cd.items() if k in Character.__dataclass_fields__})
        except Exception:
            pass

    # Rebuild armies (units dict keyed by UnitType enum)
    from histrategy_engine.world import UnitType

    for aid, ad in (ws_data.get("armies") or {}).items():
        try:
            ad2 = dict(ad)
            units = ad.get("units") or {}
            ad2["units"] = {_enum(UnitType, k): v for k, v in units.items()}
            ws.armies[aid] = Army(**{k: v for k, v in ad2.items() if k in Army.__dataclass_fields__})
        except Exception:
            pass

    return ws


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
        host_user_id=row.get("host_user_id", ""),
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
        # NOTE: propagate deserialize errors — a missing/corrupt world_state
        # must NOT silently degrade to Three Kingdoms defaults (207 AD is
        # wrong for e.g. rome-triumvirate). Callers can decide how to handle.
        room.world_state = deserialize_world_state(ws_data)

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
    """Get all factions' latest game states for a quarter.

    Deduplicates by (room_id, quarter_number, faction_id) using the most
    recent created_at row when duplicates exist (defense against race
    conditions or multi-path saves producing stale records).
    """
    from histrategy.db.connection import _IS_SQLITE as _IS_SQLITE

    if _IS_SQLITE:
        # SQLite: use subquery (no DISTINCT ON support)
        return execute(
            """SELECT gs.* FROM game_state gs
            INNER JOIN (
                SELECT faction_id, MAX(created_at) as max_created
                FROM game_state
                WHERE room_id = ? AND quarter_number = ?
                GROUP BY faction_id
            ) latest ON gs.faction_id = latest.faction_id AND gs.created_at = latest.max_created
            WHERE gs.room_id = ? AND gs.quarter_number = ?""",
            (room_id, quarter_number, room_id, quarter_number),
        )
    else:
        # PostgreSQL: use DISTINCT ON
        return execute(
            """SELECT DISTINCT ON (faction_id) *
            FROM game_state
            WHERE room_id = ? AND quarter_number = ?
            ORDER BY faction_id, created_at DESC""",
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
    """Save a policy/tech state. Returns the policy ID.

    Sets activated_at to now when status='active'. Revoked policies
    should use revoke_policy() which sets revoked_at.
    """
    policy_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Serialize params safely: if already a string, use as-is;
    # if a dict, json_dumps once; otherwise default to "{}"
    if params is None:
        params_json = "{}"
    elif isinstance(params, str):
        # Already serialized — use directly to avoid double-escaping
        params_json = params
    elif isinstance(params, dict):
        params_json = json_dumps(params)
    else:
        params_json = json_dumps(params)

    activated = now if status == "active" else ""

    if _IS_SQLITE:
        execute_write(
            """INSERT OR REPLACE INTO policy_state
                (id, room_id, quarter_number, faction_id, policy_type,
                 policy_name, policy_level, params, status, activated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                policy_id,
                room_id,
                quarter_number,
                faction_id,
                policy_type,
                policy_name,
                policy_level,
                params_json,
                status,
                activated,
            ),
        )
    else:
        execute_write(
            """INSERT INTO policy_state
                (id, room_id, quarter_number, faction_id, policy_type,
                 policy_name, policy_level, params, status, activated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (room_id, faction_id, policy_name, status) DO UPDATE SET
                quarter_number = EXCLUDED.quarter_number,
                policy_type = EXCLUDED.policy_type,
                policy_level = EXCLUDED.policy_level,
                params = EXCLUDED.params,
                activated_at = EXCLUDED.activated_at""",
            (
                policy_id,
                room_id,
                quarter_number,
                faction_id,
                policy_type,
                policy_name,
                policy_level,
                params_json,
                status,
                activated,
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


def advance_policies(room_id: str, current_quarter: int) -> int:
    """Auto-expire policies that have exceeded their duration.

    Policies without an explicit duration last 4 turns (quarters) by default.
    Looks at active policies' quarter_number (activated quarter) and expires
    any that are more than DEFAULT_POLICY_DURATION quarters old.

    Returns the number of policies expired.
    """
    from datetime import datetime, timezone

    DEFAULT_POLICY_DURATION = 4  # quarters

    active_policies = execute(
        """SELECT id, faction_id, policy_name, quarter_number
        FROM policy_state
        WHERE room_id = ? AND status = 'active'""",
        (room_id,),
    )

    now = datetime.now(timezone.utc).isoformat()
    expired_count = 0

    for p in active_policies:
        activated_q = p.get("quarter_number", 0)
        age = current_quarter - activated_q
        if age > DEFAULT_POLICY_DURATION:
            execute_write(
                """UPDATE policy_state
                SET status = 'expired', revoked_at = ?
                WHERE id = ? AND status = 'active'""",
                (now, p["id"]),
            )
            expired_count += 1

    return expired_count
