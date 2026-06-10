"""histrategy-sdk — Python SDK for 三國志略 (Histrategy).

三國志略 is an AI-powered Three Kingdoms strategy game where the LLM acts
as the game engine — generating advisor speeches, strategic suggestions,
consequences, and NPC actions based on actual world state.

Quick Start
-----------

**Option A: Remote Server (lightweight, no engine deps)**

    from histrategy_sdk import ServerClient

    client = ServerClient()
    game = client.create_game(faction="shu")
    result = client.execute_command(game["game_id"], "联吴抗曹，攻打襄阳")
    print(result["narrative"])

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
"""

from ._client import ServerClient
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
__version__ = "0.1.0"
