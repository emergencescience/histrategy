"""histrategy.db — Database persistence layer.

Usage:
    from histrategy.db import init_db, save_room, load_room
    from histrategy.db.connection import get_connection
    from histrategy.db.models import save_quarter_turn, log_llm_call
"""

from .connection import init_db
from .models import load_room, save_room
