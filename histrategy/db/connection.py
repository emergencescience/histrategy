"""
Database connection manager — SQLite (local) or PostgreSQL (Railway).

Detects database type from HISTRATEGY_DATABASE_URL:
    - sqlite:///path/to/db  → SQLite3 (Python stdlib, zero install)
    - postgresql://...       → psycopg2
    - Not set                → defaults to ~/.histrategy/histrategy.db

Auto-creates the database file and tables on first use.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("histrategy.db")

# ── Database URL Resolution ─────────────────────────


def _resolve_database_url() -> str:
    """Resolve HISTRATEGY_DATABASE_URL or default to SQLite."""
    url = os.environ.get("HISTRATEGY_DATABASE_URL", "")
    if url:
        return url

    data_dir = os.environ.get(
        "HISTRATEGY_DATA_DIR",
        os.path.expanduser("~/.histrategy"),
    )
    db_path = os.path.join(data_dir, "histrategy.db")
    return f"sqlite:///{db_path}"


DATABASE_URL = _resolve_database_url()
_IS_SQLITE = DATABASE_URL.startswith("sqlite")


# ── Connection Factory ─────────────────────────────


def get_connection():
    """Get a database connection (SQLite3 or psycopg2).

    Returns:
        A DB-API 2.0 connection object.
    """
    if _IS_SQLITE:
        return _get_sqlite_connection()
    else:
        return _get_postgres_connection()


def _get_sqlite_connection():
    """Create SQLite3 connection with WAL mode and foreign keys."""
    import sqlite3

    path = DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _get_postgres_connection():
    """Create PostgreSQL connection via psycopg2."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(DATABASE_URL)
    # Register UUID adapter
    psycopg2.extras.register_uuid()
    return conn


# ── Schema Initialization ──────────────────────────


_SCHEMA_LOADED = False


def init_db():
    """Initialize the database schema (idempotent — safe to call every startup)."""
    global _SCHEMA_LOADED
    if _SCHEMA_LOADED:
        return

    conn = get_connection()
    try:
        schema = _load_schema()
        if _IS_SQLITE:
            conn.executescript(schema)
        else:
            # PostgreSQL: execute statements individually
            with conn.cursor() as cur:
                cur.execute(schema)
        conn.commit()
        _SCHEMA_LOADED = True
        logger.info("Database schema initialized (type=%s)", "sqlite" if _IS_SQLITE else "postgres")
    finally:
        conn.close()


def _load_schema() -> str:
    """Load schema SQL from file."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    try:
        with open(schema_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("schema.sql not found at %s, using embedded schema", schema_path)
        return _EMBEDDED_SCHEMA


# ── Query Helpers ──────────────────────────────────


def execute(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as dicts."""
    conn = get_connection()
    try:
        if _IS_SQLITE:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        else:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(columns, row, strict=False)) for row in rows]
    finally:
        conn.close()


def execute_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a query and return a single row as dict, or None."""
    rows = execute(sql, params)
    return rows[0] if rows else None


def execute_write(sql: str, params: tuple = ()) -> int:
    """Execute a write query (INSERT/UPDATE/DELETE) and return rowcount."""
    conn = get_connection()
    try:
        if _IS_SQLITE:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount
        else:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_many(sql: str, params_list: list[tuple]) -> int:
    """Execute a write query with multiple parameter sets."""
    conn = get_connection()
    try:
        if _IS_SQLITE:
            cur = conn.executemany(sql, params_list)
            conn.commit()
            return cur.rowcount
        else:
            with conn.cursor() as cur:
                cur.executemany(sql, params_list)
                conn.commit()
                return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def json_dumps(obj: Any) -> str:
    """Serialize to JSON string for DB storage."""
    return json.dumps(obj, ensure_ascii=False, default=str)


def json_loads(text: str | None) -> Any:
    """Deserialize from JSON string."""
    if not text:
        return None
    return json.loads(text)


# ── Embedded Schema (fallback if schema.sql not found) ──

_EMBEDDED_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_room (
    id              TEXT PRIMARY KEY,
    host_user_id    TEXT,
    scenario        TEXT DEFAULT '207',
    year            INTEGER DEFAULT 207,
    season          TEXT DEFAULT '春',
    quarter_number  INTEGER DEFAULT 0,
    phase           TEXT DEFAULT 'lobby',
    world_state     TEXT,
    slots           TEXT,
    decision_timeout INTEGER DEFAULT 300,
    turn_summaries  TEXT DEFAULT '[]',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faction_slot (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    faction_id      TEXT NOT NULL,
    occupant_type   TEXT NOT NULL DEFAULT 'open',
    occupant_id     TEXT,
    ai_model        TEXT,
    ai_temperature  REAL DEFAULT 0.7,
    pending_decision TEXT,
    pending_commands TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(room_id, faction_id)
);

CREATE TABLE IF NOT EXISTS quarter_turn (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    season          TEXT NOT NULL,
    faction_decisions TEXT,
    baseline_result  TEXT,
    macro_delta      TEXT,
    narratives       TEXT,
    state_changes    TEXT,
    token_usage      TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_call_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    call_type       TEXT NOT NULL,
    faction_id      TEXT,
    provider        TEXT,
    model           TEXT,
    prompt_tokens       INTEGER DEFAULT 0,
    completion_tokens   INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER,
    latency_ms          INTEGER DEFAULT 0,
    system_prompt_type  TEXT,
    user_prompt     TEXT,
    response        TEXT,
    error           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS simulation_event_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    event_type      TEXT NOT NULL,
    event_data      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS room_player (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    user_id         TEXT NOT NULL,
    role            TEXT DEFAULT 'player',
    display_name    TEXT DEFAULT '',
    joined_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(room_id, user_id)
);

-- 世界状态快照表：每个势力在当前季度的完整状态
-- 一张表存储所有数值+非数值状态（城池/人口/兵力/粮草/政策/科技树）
CREATE TABLE IF NOT EXISTS game_state (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    faction_id      TEXT NOT NULL,
    -- 数值状态
    population      INTEGER DEFAULT 0,
    troops          INTEGER DEFAULT 0,
    food            REAL DEFAULT 0,
    treasury        REAL DEFAULT 0,
    morale          INTEGER DEFAULT 50,
    -- 城池控制（JSON: [{"territory_id": "xuchang", "population": 50000, "development": 60}, ...]）
    territories     TEXT DEFAULT '[]',
    -- 非数值状态（政策/科技树/法律/外交等 — JSON blob）
    policies        TEXT DEFAULT '{}',
    -- 额外元数据
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(room_id, quarter_number, faction_id)
);

-- 增量表：记录每个轮次各势力的数值变化（人口增减/粮草消耗/兵力变化等）
CREATE TABLE IF NOT EXISTS turn_delta (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    faction_id      TEXT NOT NULL,
    delta_type      TEXT NOT NULL,  -- 'population' | 'troops' | 'food' | 'treasury' | 'morale'
    old_value       REAL,
    new_value       REAL,
    delta           REAL,
    reason          TEXT,           -- 变化原因（如 "屯田制+5%", "战争伤亡-2000", "征税+1500"）
    source          TEXT DEFAULT 'deterministic',  -- 'deterministic' | 'llm' | 'black_swan'
    created_at      TEXT DEFAULT (datetime('now'))
);

-- 策略/科技状态表：存储每个势力的政策法令和科技树进展
-- 每次仿真时读取此表，用来影响数值计算
CREATE TABLE IF NOT EXISTS policy_state (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,  -- 政策生效的季度
    faction_id      TEXT NOT NULL,
    policy_type     TEXT NOT NULL,    -- 'law' | 'diplomacy' | 'economic' | 'military' | 'tech'
    policy_name     TEXT NOT NULL,    -- '科举制' | '盐铁专营' | '屯田制' | '九品中正制'
    policy_level    INTEGER DEFAULT 1, -- 政策等级（科技树层级）
    params          TEXT DEFAULT '{}', -- 政策参数（JSON）
    status          TEXT DEFAULT 'active', -- 'active' | 'revoked' | 'expired'
    activated_at    TEXT DEFAULT (datetime('now')),
    revoked_at      TEXT,
    UNIQUE(room_id, faction_id, policy_name, status)
);

CREATE INDEX IF NOT EXISTS idx_faction_slot_room ON faction_slot(room_id);
CREATE INDEX IF NOT EXISTS idx_quarter_turn_room ON quarter_turn(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_room ON llm_call_log(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_sim_event_room ON simulation_event_log(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_game_state_room ON game_state(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_turn_delta_room ON turn_delta(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_policy_state_room ON policy_state(room_id, faction_id);
"""
