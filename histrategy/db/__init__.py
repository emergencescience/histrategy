"""histrategy.db — Database persistence layer.

Usage:
    from histrategy.db import init_db, save_room, load_room, save_quarter_turn
    from histrategy.db.connection import get_connection, execute
    from histrategy.db.models import log_llm_call, log_sim_event
"""

from .connection import execute, execute_many, execute_one, execute_write, init_db
from .models import (
    get_quarter_turns,
    load_room,
    load_world_state_dict,
    log_llm_call,
    log_sim_event,
    save_quarter_turn,
    save_room,
)

__all__ = [
    "execute",
    "execute_many",
    "execute_one",
    "execute_write",
    "get_quarter_turns",
    "init_db",
    "load_room",
    "load_world_state_dict",
    "log_llm_call",
    "log_sim_event",
    "save_quarter_turn",
    "save_room",
]
