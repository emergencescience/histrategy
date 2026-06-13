"""histrategy-sdk — Python SDK for 三國志略 (Histrategy).

三國志略 is an AI-powered Three Kingdoms strategy game engine.
The SDK is purely file-based: every turn reads from and writes to
~/.histrategy/rooms/<room>/ on disk. No network, no server, no
in-memory state — designed for AI agents that reset context daily.

Quick Start
-----------

**Option A: Remote Server (lightweight, no engine deps)**

    from histrategy_sdk import ServerClient

    client = ServerClient()
    game = client.create_game(faction="shu")
    result = client.execute_command(game["game_id"], "联吴抗曹，攻打襄阳")
    print(result["narrative"])

    # Multiplayer
    from histrategy_sdk import MultiplayerRoom

    result = MultiplayerRoom.create(
        client, {"caocao": "曹操", "liubei": "刘备"}
    )
    room = MultiplayerRoom.join(
        client, result["room_id"], "caocao",
        result["player_links"][0]["player_token"]
    )
    room.decide("发展农业")

**Option B: Direct Engine (in-process, needs histrategy-engine)**

    pip install histrategy-sdk[engine]

    from histrategy_sdk import DirectEngine

    engine = DirectEngine(faction="shu")
    intro = engine.get_intro()
    result = engine.execute("联吴抗曹")
    print(result["narrative"])

    # Save and restore
    data = engine.to_dict()
    engine2 = DirectEngine.from_dict(data)

**Option C: File-based Room (persistent, no network)**

    from histrategy_sdk import Room

    room = Room.create("my-campaign", faction="shu")
    result = room.play("联吴抗曹，攻打襄阳")
    print(result["narrative"])
"""

from ._client import ServerClient
from ._mp_room import MultiplayerRoom
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
    CreateRoomResult,
    FactionStatus,
    GameIntro,
    PlanData,
    PlayerLink,
    RestoreResult,
    RoomStatus,
    TokenUsage,
    TurnResult,
)

# DirectEngine is optional — import fails gracefully if histrategy not installed
try:
    from ._engine import DirectEngine
except ImportError:
    DirectEngine = None  # type: ignore[assignment]

__all__ = [
    # Client
    "ServerClient",
    # Engine (optional)
    "DirectEngine",
    # File-based Room
    "Room",
    # Multiplayer
    "MultiplayerRoom",
    # Types
    "CreateRoomResult",
    "FactionStatus",
    "GameIntro",
    "PlanData",
    "PlayerLink",
    "RestoreResult",
    "RoomStatus",
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
