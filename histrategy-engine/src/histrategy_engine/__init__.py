"""
histrategy-engine — Deterministic physics engine for historical strategy games.

Seven-engine architecture (Map, Character, Domestic, Military, Decision,
History, Narrative) — no LLM dependency in the core engines.
"""

from .world import (
    Army,
    Character,
    ClimateEvent,
    CombatResult,
    Command,
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
from .map import MapEngine, PathResult
from .character import CharacterEngine
from .domestic import ClimateSystem, DomesticEngine, TerritoryResult
from .military import MilitaryEngine, RecruitResult, MoveResult, SupplyStatus
from .ai import DecisionEngine
from .turn import TurnController

__all__ = [
    # World
    "WorldState", "Territory", "Character", "FactionState", "Army",
    "StrategicPoint", "CombatResult", "Command", "TurnResult",
    "HistoricalEvent",
    # Enums
    "Season", "ClimateEvent", "TerrainType", "UnitType", "HistoricalMode",
    # Engines
    "MapEngine", "CharacterEngine", "DomesticEngine", "ClimateSystem",
    "MilitaryEngine", "DecisionEngine", "TurnController",
    # Results
    "PathResult", "TerritoryResult", "RecruitResult", "MoveResult", "SupplyStatus",
]
__version__ = "0.1.0"
