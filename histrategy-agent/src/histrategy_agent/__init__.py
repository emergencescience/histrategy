"""
histrategy-agent — Shared core for OpenClaw and Hermes Agent game skills.

Bridges IM chat messages to the histrategy-engine deterministic engines.
"""

from .session import GameSession, GameSessionManager
from .turn_processor import TurnProcessor, TurnResult as ProcessorTurnResult
from .state_bridge import StateBridge
from .format_engine import FormatEngine
from .multiplayer import GamePhase, MultiplayerSession, PlayerSlot

__all__ = [
    "GameSession",
    "GameSessionManager",
    "TurnProcessor",
    "ProcessorTurnResult",
    "StateBridge",
    "FormatEngine",
    "GamePhase",
    "MultiplayerSession",
    "PlayerSlot",
]
__version__ = "0.1.0"
