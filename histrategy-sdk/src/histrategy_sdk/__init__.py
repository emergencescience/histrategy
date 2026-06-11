"""histrategy-sdk — Python SDK for 三國志略 (Histrategy).

三國志略 is an AI-powered Three Kingdoms strategy game engine.
The SDK is purely file-based: every turn reads from and writes to
~/.histrategy/rooms/<room>/ on disk. No network, no server, no
in-memory state — designed for AI agents that reset context daily.

Quick Start
-----------

    from histrategy_sdk import Room

    # Create a new game room
    room = Room.create("my-game", faction="shu")

    # Play a turn (reads state from disk, executes, writes back)
    result = room.play("联吴抗曹，攻打襄阳")
    print(result.narrative)

    # Come back tomorrow — state survives agent context reset
    room2 = Room.load("my-game")
    result2 = room2.play("休养生息")

    # Multiplayer: each faction has its own room
    room_shu = Room.create("three-kingdoms/shu", faction="shu")
    room_cao = Room.create("three-kingdoms/cao", faction="cao")
    room_wu  = Room.create("three-kingdoms/wu", faction="wu")
"""

from ._engine import DirectEngine
from ._room import Room
from .exceptions import (
    APIError,
    ConnectionError,
    EngineNotAvailableError,
    GameNotFoundError,
    HistrategyError,
    TurnExecutionError,
)
from .types import (
    FactionStatus,
    GameIntro,
    PlanData,
    RestoreResult,
    TokenUsage,
    TurnResult,
)

__all__ = [
    # Core API
    "Room",
    "DirectEngine",
    # Types
    "FactionStatus",
    "GameIntro",
    "PlanData",
    "RestoreResult",
    "TokenUsage",
    "TurnResult",
    # Exceptions
    "HistrategyError",
    "GameNotFoundError",
    "ConnectionError",
    "APIError",
    "EngineNotAvailableError",
    "TurnExecutionError",
]
__version__ = "0.2.0"
