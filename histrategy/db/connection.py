"""
数据库连接管理 — SQLite（本地）/ PostgreSQL（Railway）自动切换。

入口函数 init_db() 在应用启动时调用，自动建表。
所有 DML 操作通过 get_db() 获取连接。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path

logger = logging.getLogger("histrategy.db")

# 全局数据库文件路径
DB_PATH: str | None = None
DB_TYPE: str = "sqlite"  # "sqlite" | "postgresql"


def _resolve_db_path() -> str:
    """解析数据库路径。优先使用环境变量，否则默认 ~/.histrategy/histrategy.db。"""
    global DB_PATH, DB_TYPE

    # PostgreSQL 优先（Railway 生产环境）
    pg_url = os.environ.get("HISTRATEGY_DATABASE_URL", "")
    if pg_url:
        DB_TYPE = "postgresql"
        DB_PATH = pg_url
        return pg_url

    # SQLite 本地
    data_dir = os.environ.get("HISTRATEGY_DATA_DIR", "")
    if data_dir:
        db_path = os.path.join(data_dir, "histrategy.db")
    else:
        db_path = os.path.expanduser("~/.histrategy/histrategy.db")

    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        Path(db_dir).mkdir(parents=True, exist_ok=True)

    DB_TYPE = "sqlite"
    DB_PATH = db_path
    return db_path


def init_db(db_path: str | None = None) -> None:
    """初始化数据库：创建所有表（幂等）。

    首次启动时在 ~/.histrategy/histrategy.db 创建 SQLite 数据库。
    如果设置了 HISTRATEGY_DATABASE_URL，则连接 PostgreSQL。

    幂等安全：使用 CREATE TABLE IF NOT EXISTS。
    """
    db_path = db_path or _resolve_db_path()

    if DB_TYPE == "postgresql":
        _init_postgresql(db_path)
    else:
        _init_sqlite(db_path)

    logger.info(f"Database initialized: {DB_TYPE} @ {db_path}")


def _init_sqlite(db_path: str) -> None:
    """初始化 SQLite 数据库。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")  # 更好的并发支持
    conn.execute("PRAGMA foreign_keys=ON")

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()

    # 替换 SQLite 不兼容的语法
    # datetime('now') 替换 PostgreSQL 的 NOW()
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()


def _init_postgresql(dsn: str) -> None:
    """初始化 PostgreSQL 数据库。"""
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed, falling back to SQLite")
        _init_sqlite(_resolve_db_path())
        return

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()

    # Replace SQLite-specific syntax with PostgreSQL
    schema_sql = schema_sql.replace(
        "datetime('now')", "NOW()"
    )

    cur.execute(schema_sql)
    conn.commit()
    cur.close()
    conn.close()


def get_db() -> sqlite3.Connection:
    """获取数据库连接（SQLite）。

    调用者负责在完成后关闭连接。
    使用 WAL 模式和 foreign_keys=ON。
    """
    if DB_PATH is None:
        _resolve_db_path()

    if DB_TYPE == "postgresql" and DB_PATH:
        try:
            import psycopg2
            pg_conn = psycopg2.connect(DB_PATH)
            return pg_conn  # type: ignore[return-value]
        except ImportError:
            # Fallback to SQLite
            pass

    conn = sqlite3.connect(DB_PATH or ":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    """返回 ISO 8601 格式的当前时间字符串。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── GameRoom 持久化 ──────────────────────────────


def save_game_room(room_dict: dict, world_state_json: str | None = None) -> None:
    """将 GameRoom 保存到数据库（UPSERT）。

    Args:
        room_dict: GameRoom.to_dict() 的输出
        world_state_json: WorldState 的 JSON 序列化（可选）
    """
    conn = get_db()
    try:
        now = now_iso()
        conn.execute(
            """INSERT INTO game_room (id, host_user_id, scenario, year, season,
               quarter_number, phase, world_state, slots, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               host_user_id=excluded.host_user_id,
               year=excluded.year, season=excluded.season,
               quarter_number=excluded.quarter_number,
               phase=excluded.phase,
               world_state=excluded.world_state,
               slots=excluded.slots,
               updated_at=excluded.updated_at""",
            (
                room_dict["id"],
                room_dict.get("host_user_id"),
                room_dict.get("scenario", "207"),
                room_dict.get("year", 207),
                room_dict.get("season", "春"),
                room_dict.get("quarter_number", 0),
                room_dict.get("phase", "lobby"),
                world_state_json,
                _json_dumps(room_dict.get("slots", {})),
                now,
                now,
            ),
        )

        # Save faction slots
        slots = room_dict.get("slots", {})
        for fid, slot_data in slots.items():
            slot_id = f"{room_dict['id']}_{fid}"
            conn.execute(
                """INSERT INTO faction_slot (id, room_id, faction_id,
                   occupant_type, occupant_id, ai_model, ai_personality,
                   pending_decision, pending_commands, is_active,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(room_id, faction_id) DO UPDATE SET
                   occupant_type=excluded.occupant_type,
                   occupant_id=excluded.occupant_id,
                   pending_decision=excluded.pending_decision,
                   pending_commands=excluded.pending_commands,
                   is_active=excluded.is_active,
                   updated_at=excluded.updated_at""",
                (
                    slot_id,
                    room_dict["id"],
                    fid,
                    slot_data.get("occupant_type", "open"),
                    slot_data.get("occupant_id"),
                    slot_data.get("ai_model"),
                    slot_data.get("ai_personality"),
                    slot_data.get("pending_decision"),
                    _json_dumps(slot_data.get("pending_commands")),
                    1 if slot_data.get("is_active", True) else 0,
                    now,
                    now,
                ),
            )

        conn.commit()
        logger.debug(f"Saved GameRoom {room_dict['id']} to DB")
    finally:
        conn.close()


def load_game_room(room_id: str) -> dict | None:
    """从数据库加载 GameRoom。

    Returns:
        room_dict (with 'slots' populated) or None if not found.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_room WHERE id = ?", (room_id,)
        ).fetchone()
        if not row:
            return None

        room_dict = dict(row)

        # Load faction slots
        slot_rows = conn.execute(
            "SELECT * FROM faction_slot WHERE room_id = ?", (room_id,)
        ).fetchall()

        slots = {}
        for sr in slot_rows:
            sd = dict(sr)
            fid = sd["faction_id"]
            # Parse JSON fields
            if sd.get("pending_commands") and isinstance(sd["pending_commands"], str):
                try:
                    sd["pending_commands"] = json.loads(sd["pending_commands"])
                except (json.JSONDecodeError, TypeError):
                    pass
            slots[fid] = sd

        room_dict["slots"] = slots
        return room_dict
    finally:
        conn.close()


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
    """保存一个季度的完整记录。

    Returns:
        turn_id (UUID)
    """
    turn_id = uuid.uuid4().hex
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO quarter_turn (id, room_id, quarter_number, year, season,
               faction_decisions, baseline_result, macro_delta, narratives,
               state_changes, token_usage, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn_id,
                room_id,
                quarter_number,
                year,
                season,
                _json_dumps(faction_decisions),
                _json_dumps(baseline_result),
                _json_dumps(macro_delta),
                _json_dumps(narratives),
                _json_dumps(state_changes),
                _json_dumps(token_usage),
                now_iso(),
            ),
        )
        conn.commit()
        return turn_id
    finally:
        conn.close()


def list_game_rooms(status: str | None = None) -> list[dict]:
    """列出所有游戏房间。

    Args:
        status: 过滤阶段 (lobby/waiting/resolving/finished)，None 返回全部
    """
    conn = get_db()
    try:
        if status:
            rows = conn.execute(
                "SELECT id, host_user_id, scenario, phase, quarter_number, "
                "year, season, created_at, updated_at "
                "FROM game_room WHERE phase = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, host_user_id, scenario, phase, quarter_number, "
                "year, season, created_at, updated_at "
                "FROM game_room ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Helpers ─────────────────────────────────────


def _json_dumps(obj) -> str | None:
    """安全地 JSON 序列化，失败时返回 None。"""
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
