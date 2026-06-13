"""
Write-only JSON file backup for debugging and disaster recovery.

⚠️ CRITICAL RULE: These files are NEVER read to restore game state.
All state restoration goes through the SQL database.

Files are written to ~/.histrategy/backups/<room_id>/ and organized
by quarter number + event reason.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom


def get_backup_dir(room_id: str) -> str:
    """Get the backup directory for a room."""
    base = os.environ.get(
        "HISTRATEGY_DATA_DIR",
        os.path.expanduser("~/.histrategy"),
    )
    return os.path.join(base, "backups", room_id)


def write_room_snapshot(
    room: GameRoom,
    world_state_dict: dict | None = None,
    reason: str = "quarter_complete",
):
    """Write a full room + world_state snapshot to a JSON file.

    Args:
        room: GameRoom to snapshot
        world_state_dict: WorldState as dict (if available)
        reason: Why this snapshot was taken (quarter_complete, game_start, etc.)
    """
    backup_dir = get_backup_dir(room.id)
    os.makedirs(backup_dir, exist_ok=True)

    qn = str(room.quarter_number).zfill(4)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{qn}_{reason}_{ts}.json"
    filepath = os.path.join(backup_dir, filename)

    data = {
        "room": room.to_dict(),
        "world_state": world_state_dict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def write_quarter_result(
    room_id: str,
    quarter_number: int,
    result: dict,
    reason: str = "quarter_complete",
):
    """Write quarterly result data to a JSON file.

    Args:
        room_id: Room ID
        quarter_number: Quarter number
        result: Result dict to write
        reason: Why this was written
    """
    backup_dir = get_backup_dir(room_id)
    os.makedirs(backup_dir, exist_ok=True)

    qn = str(quarter_number).zfill(4)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{qn}_result_{reason}_{ts}.json"
    filepath = os.path.join(backup_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)


def write_error_dump(
    room_id: str,
    error: str,
    context: dict | None = None,
):
    """Write an error dump for debugging.

    Args:
        room_id: Room ID
        error: Error message
        context: Additional context dict
    """
    backup_dir = get_backup_dir(room_id)
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"error_{ts}.json"
    filepath = os.path.join(backup_dir, filename)

    data = {
        "error": error,
        "context": context or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def list_backups(room_id: str, limit: int = 20) -> list[str]:
    """List recent backup files for a room.

    Args:
        room_id: Room ID
        limit: Max files to return

    Returns:
        List of file paths, most recent first.
    """
    backup_dir = get_backup_dir(room_id)
    if not os.path.isdir(backup_dir):
        return []

    files = sorted(
        [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".json")],
        key=os.path.getmtime,
        reverse=True,
    )
    return files[:limit]


def cleanup_old_backups(room_id: str, keep: int = 50):
    """Remove old backup files, keeping only the most recent N.

    Args:
        room_id: Room ID
        keep: Number of most recent files to keep
    """
    files = list_backups(room_id, limit=999)
    for f in files[keep:]:
        with contextlib.suppress(OSError):
            os.remove(f)
