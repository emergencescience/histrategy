"""
histrategy-engine — Deterministic physics engine for historical strategy games.

Seven-engine architecture (Map, Character, Domestic, Military, Decision,
History, Narrative) — no LLM dependency in the core engines.
"""

from .ai import DecisionEngine
from .character import CharacterEngine
from .domestic import ClimateSystem, DomesticEngine, TerritoryResult
from .history import HistoryEngine
from .history.rag import HistoricalRAG
from .map import MapEngine, PathResult
from .military import MilitaryEngine, MoveResult, RecruitResult, SupplyStatus
from .turn import TurnController
from .world import (
    Army,
    Character,
    ClimateEvent,
    CombatResult,
    Command,
    EventProposal,
    FactionState,
    HistoricalEvent,
    HistoricalMode,
    Season,
    StrategicPoint,
    TerrainType,
    Territory,
    TurnResult,
    UnitType,
    WorldState,
)

__all__ = [
    # World
    "WorldState",
    "Territory",
    "Character",
    "FactionState",
    "Army",
    "StrategicPoint",
    "CombatResult",
    "Command",
    "TurnResult",
    "HistoricalEvent",
    "EventProposal",
    # Enums
    "Season",
    "ClimateEvent",
    "TerrainType",
    "UnitType",
    "HistoricalMode",
    # Engines
    "MapEngine",
    "CharacterEngine",
    "DomesticEngine",
    "ClimateSystem",
    "MilitaryEngine",
    "DecisionEngine",
    "TurnController",
    "HistoryEngine",
    "HistoricalRAG",
    # Results
    "PathResult",
    "TerritoryResult",
    "RecruitResult",
    "MoveResult",
    "SupplyStatus",
]
__version__ = "0.1.0"
