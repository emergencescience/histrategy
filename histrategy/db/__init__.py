"""
Database persistence layer for symmetric multiplayer engine.

Uses SQLite (local) or PostgreSQL (production) with the same schema.
Automatic table creation on first use via init_db().
"""

from .connection import (
    DB_PATH,
    DB_TYPE,
    get_db,
    init_db,
    list_game_rooms,
    load_game_room,
    now_iso,
    save_game_room,
    save_quarter_turn,
)

__all__ = [
    "DB_PATH",
    "DB_TYPE",
    "get_db",
    "init_db",
    "list_game_rooms",
    "load_game_room",
    "now_iso",
    "save_game_room",
    "save_quarter_turn",
]
