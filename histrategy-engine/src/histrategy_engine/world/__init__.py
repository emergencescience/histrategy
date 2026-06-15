"""
World state container — all engine data models.

This module defines the canonical data structures shared across all engines.
No game logic here — just types and serialization.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import Enum

# ─── Enums ────────────────────────────────────────────────────


class Season(Enum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"

    @property
    def cn(self) -> str:
        return {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}[self.value]

    @property
    def food_multiplier(self) -> float:
        return {"spring": 0.3, "summer": 1.0, "autumn": 1.2, "winter": 0.05}[self.value]

    @property
    def supply_multiplier(self) -> float:
        """Winter requires 1.5x food for troops."""
        return 1.5 if self == Season.WINTER else 1.0


class ClimateEvent(Enum):
    NORMAL = "normal"
    DROUGHT = "drought"
    FLOOD = "flood"
    PESTILENCE = "pestilence"
    BUMPER_HARVEST = "bumper_harvest"
    COLD_WAVE = "cold_wave"

    @property
    def food_modifier(self) -> float:
        return {
            "normal": 1.0,
            "drought": 0.4,
            "flood": 0.6,
            "pestilence": 0.3,
            "bumper_harvest": 1.5,
            "cold_wave": 0.7,
        }[self.value]


class TerrainType(Enum):
    PLAINS = "plains"
    HILLS = "hills"
    MOUNTAIN = "mountain"
    FOREST = "forest"
    WETLAND = "wetland"
    RIVER = "river"
    COAST = "coast"


class UnitType(Enum):
    INFANTRY = "infantry"
    CAVALRY = "cavalry"
    ARCHER = "archer"
    NAVY = "navy"


class BattleResult(Enum):
    DECISIVE_VICTORY = "decisive_victory"
    VICTORY = "victory"
    DRAW = "draw"
    DEFEAT = "defeat"
    DECISIVE_DEFEAT = "decisive_defeat"


class HistoricalMode(Enum):
    HISTORICAL = "historical"
    DIVERGENT = "divergent"
    FREEFORM = "freeform"


# ─── Territory ───────────────────────────────────────────────


@dataclass
class StrategicPoint:
    """A chokepoint within a territory — pass, ford, or city."""

    id: str
    name: str
    point_type: str  # "pass", "ford", "city"
    fortification: int = 0  # 0-100
    garrison: int = 0
    owner_id: str = ""


@dataclass
class Territory:
    """A province / state in the game world."""

    id: str
    name: str
    owner_id: str = ""

    # ── Natural attributes (static) ──
    fertility: int = 5  # 1-10
    terrain_type: TerrainType = TerrainType.PLAINS
    climate_zone: str = "central"  # "north" | "central" | "south"
    has_river: bool = False
    has_coast: bool = False

    # ── Resource flags ──
    horse_resource: bool = False
    iron_resource: bool = False
    salt_resource: bool = False

    # ── Neighbors ──
    neighbors: list[str] = field(default_factory=list)
    # {neighbor_id: strategic_point_id} — must control the point to cross
    neighbor_crossings: dict[str, str] = field(default_factory=dict)

    # ── Dynamic attributes ──
    population: int = 50000
    development: int = 30  # 0-100
    garrison: int = 1000
    fortification: int = 20  # 0-100
    unrest: int = 0  # 0-100

    # ── Strategic points within this territory ──
    strategic_points: list[StrategicPoint] = field(default_factory=list)

    @property
    def is_occupied(self) -> bool:
        return bool(self.owner_id)

    def __hash__(self) -> int:
        return hash(self.id)


# ─── Character ────────────────────────────────────────────────


@dataclass
class Character:
    """A historical figure — officer, advisor, ruler."""

    id: str
    name: str
    alias: str = ""  # 字

    # ── Five-dimensional stats (1-100) ──
    leadership: int = 50  # 统率
    might: int = 50  # 武力
    intelligence: int = 50  # 智力
    politics: int = 50  # 政治
    charisma: int = 50  # 魅力

    # ── Skills ──
    skills: list[str] = field(default_factory=list)

    # ── Relationships ──
    sworn_brothers: list[str] = field(default_factory=list)
    spouse: str = ""
    mentor: str = ""
    hometown: str = ""

    # ── Dynamic state ──
    faction_id: str = ""
    loyalty: int = 80  # 0-100
    location: str = ""
    alive: bool = True
    birth: int = 150
    death: int = 200  # historical death year

    # ── Status flags ──
    is_wounded: bool = False
    is_captured: bool = False
    is_governor: bool = False
    is_commanding: bool = False

    @property
    def age(self) -> int:
        """Placeholder — caller should pass current_year."""
        return 0  # computed at runtime

    def leadership_bonus(self) -> float:
        return 1.0 + self.leadership / 200.0

    def might_bonus(self) -> float:
        return 1.0 + self.might / 200.0

    def intelligence_bonus(self) -> float:
        return 1.0 + self.intelligence / 200.0

    def politics_bonus(self) -> float:
        return 1.0 + self.politics / 200.0

    def charisma_bonus(self) -> float:
        return 1.0 + self.charisma / 200.0


# ─── Faction ──────────────────────────────────────────────────


@dataclass
class FactionState:
    """Full state of a faction at a point in time."""

    id: str
    name: str
    ruler_id: str

    # ── Public (visible to all) ──
    capital: str = ""
    territories: list[str] = field(default_factory=list)
    is_active: bool = True
    prestige: int = 50
    legitimacy: int = 50

    # ── Estimated (visible with intel) ──
    strength_estimated: int = 0
    economy_estimated: int = 50
    morale_estimated: int = 50

    # ── Private (only this faction sees) ──
    strength_actual: int = 5000
    economy_actual: int = 50
    morale_actual: int = 50
    treasury: int = 5000
    food: int = 3000
    tax_rate: float = 0.3  # 0.1 - 0.5
    tech_levels: dict[str, int] = field(default_factory=dict)

    # ── Diplomacy ──
    allies: list[str] = field(default_factory=list)
    enemies: list[str] = field(default_factory=list)
    relations: dict[str, int] = field(default_factory=dict)  # faction_id → -100 to 100

    # ── Espionage ──
    spy_network: dict[str, int] = field(default_factory=dict)  # faction_id → intel_level
    intel_level: int = 50  # 0-100, this faction's counter-intel

    # ── Active plans (hidden from other factions) ──
    active_plans: list[str] = field(default_factory=list)

    # ── NPC personality (only for NPC factions) ──
    aggression: float = 0.5
    cunning: float = 0.5
    caution: float = 0.5
    diplomacy: float = 0.5
    development_focus: float = 0.5
    mercy: float = 0.5

    # ── Backward-compat init vars (map old field names to new) ──
    strength: InitVar[int | None] = None
    economy: InitVar[int | None] = None
    morale: InitVar[int | None] = None

    def __post_init__(self, strength, economy, morale):
        if strength is not None:
            self.strength_actual = strength
        if economy is not None:
            self.economy_actual = economy
        if morale is not None:
            self.morale_actual = morale


# ─── Backward-compat properties on FactionState ────────────────


def _make_bc_prop(target_attr: str):
    return property(
        lambda self, attr=target_attr: getattr(self, attr),
        lambda self, v, attr=target_attr: setattr(self, attr, v),
    )


FactionState.strength = _make_bc_prop("strength_actual")  # type: ignore[attr-defined]
FactionState.economy = _make_bc_prop("economy_actual")  # type: ignore[attr-defined]
FactionState.morale = _make_bc_prop("morale_actual")  # type: ignore[attr-defined]

FactionState.personality_applied = property(  # type: ignore[attr-defined]
    lambda self: {
        "aggression": self.aggression,
        "cunning": self.cunning,
        "caution": self.caution,
        "diplomacy": self.diplomacy,
        "development_focus": self.development_focus,
        "mercy": self.mercy,
    }
)


# ─── Military ─────────────────────────────────────────────────


@dataclass
class Army:
    """A military force at a specific location."""

    id: str
    faction_id: str
    location: str  # territory_id
    commander_id: str = ""

    units: dict[UnitType, int] = field(default_factory=dict)
    morale: int = 80  # 0-100
    training: float = 1.0  # 0.5 (raw) → 1.0 (trained)
    supply: int = 30  # turns of supply remaining

    @property
    def total_troops(self) -> int:
        return sum(self.units.values())


@dataclass
class CombatResult:
    """Output of a battle resolution."""

    battle_id: str
    location: str
    attacker_id: str
    defender_id: str
    result: BattleResult

    attacker_casualties: dict[UnitType, int] = field(default_factory=dict)
    defender_casualties: dict[UnitType, int] = field(default_factory=dict)

    attacker_commander_casualty: bool = False
    defender_commander_casualty: bool = False
    attacker_commander_captured: bool = False
    defender_commander_captured: bool = False

    territory_captured: bool = False


# ─── Events ────────────────────────────────────────────────────


@dataclass
class HistoricalEvent:
    """A scripted historical event with trigger conditions."""

    id: str
    title: str
    year_range: tuple[int, int]
    category: str = "general"  # major_battle, character_death, diplomatic, etc.
    description: str = ""
    gravity: float = 0.7
    preconditions: dict = field(default_factory=dict)
    outcomes: list[dict] = field(default_factory=list)
    butterfly_effects: dict = field(default_factory=dict)

    completed: bool = False
    averted: bool = False
    actual_outcome: str = ""


@dataclass
class EventProposal:
    """Proposal from History Engine to other engines."""

    event_id: str
    title: str
    effects: dict = field(default_factory=dict)  # engine-specific effects
    narrative_hint: str = ""


# ─── Commands ──────────────────────────────────────────────────


@dataclass
class Command:
    """A validated game command from a faction."""

    type: str  # "recruit", "move", "attack", "develop", "tax", "defend", etc.
    params: dict = field(default_factory=dict)
    faction_id: str = ""
    notes: str = ""  # LLM-provided context: reasoning, campaign name, risk notes, etc.


# ─── Turn Result ───────────────────────────────────────────────


@dataclass
class TurnResult:
    """Complete output of a turn — consumed by Narrative Engine."""

    year: int = 190
    season: Season = Season.SPRING
    turn_number: int = 1

    climate_events: dict[str, ClimateEvent] = field(default_factory=dict)
    resource_changes: dict = field(default_factory=dict)
    battles: list[CombatResult] = field(default_factory=list)
    diplomatic_events: list[dict] = field(default_factory=list)
    character_events: list[dict] = field(default_factory=list)
    history_events: list[dict] = field(default_factory=list)

    faction_snapshots: dict[str, FactionState] = field(default_factory=dict)

    # Context passthrough: original player decision + parsed commands
    # for narrative engine to generate richer, more accurate stories
    player_decision: str = ""
    player_commands: list = field(default_factory=list)


# ─── World State ───────────────────────────────────────────────


@dataclass
class WorldState:
    """Complete game world snapshot."""

    year: int = 207
    season: Season = Season.WINTER
    turn_number: int = 1

    scenario: str = "207"
    player_faction_id: str = ""

    territories: dict[str, Territory] = field(default_factory=dict)
    characters: dict[str, Character] = field(default_factory=dict)
    factions: dict[str, FactionState] = field(default_factory=dict)
    armies: dict[str, Army] = field(default_factory=dict)

    historical_mode: HistoricalMode = HistoricalMode.HISTORICAL
    player_deviation: float = 0.0

    event_history: list[dict] = field(default_factory=list)
    completed_events: list[str] = field(default_factory=list)
    averted_events: list[str] = field(default_factory=list)


# ─── Backward-compat properties on WorldState ──────────────────


WorldState.turn = property(  # type: ignore[attr-defined]
    lambda self: self.turn_number,
    lambda self, v: setattr(self, "turn_number", v),
)

WorldState.event_log = property(  # type: ignore[attr-defined]
    lambda self: self.event_history,
    lambda self, v: setattr(self, "event_history", v),
)

WorldState.season_index = property(  # type: ignore[attr-defined]
    lambda self: {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}.get(
        str(self.season.value), 0
    ),
    lambda self, v: setattr(
        self,
        "season",
        {0: Season.SPRING, 1: Season.SUMMER, 2: Season.AUTUMN, 3: Season.WINTER}[v % 4],
    ),
)


# ─── Backward-compat from_dict / to_dict on WorldState ─────────


def _worldstate_from_dict(self, data: dict) -> None:
    """Restore WorldState from dict (backward-compat with old JSON format)."""
    self.turn = data.get("turn", data.get("turn_number", 1))
    self.year = data.get("year", 207)
    si = data.get("season_index", 0)
    self.season_index = si
    self.player_faction_id = data.get("player_faction_id", "")
    self.scenario = data.get("scenario", "three-kingdoms")
    self.player_deviation = data.get("player_deviation", 0.0)
    self.completed_events = data.get("completed_events", [])
    self.event_history = data.get("event_log", data.get("event_history", []))

    # Restore factions
    factions_data = data.get("factions", {})
    for fid, fd in factions_data.items():
        fs = FactionState(
            id=fid,
            name=fd.get("name", fid),
            ruler_id=fd.get("ruler_id", ""),
            capital=fd.get("capital", ""),
            territories=fd.get("territories", []),
            strength=fd.get("strength", fd.get("strength_actual", 0)),
            economy=fd.get("economy", fd.get("economy_actual", 0)),
            morale=fd.get("morale", fd.get("morale_actual", 50)),
            food=fd.get("food", 0),
            treasury=fd.get("treasury", 0),
            is_active=fd.get("is_active", True),
            tax_rate=fd.get("tax_rate", 0.3),
            prestige=fd.get("prestige", 50),
            aggression=fd.get("aggression", fd.get("personality", {}).get("aggression", 0.5)),
            cunning=fd.get("cunning", fd.get("personality", {}).get("cunning", 0.5)),
            caution=fd.get("caution", fd.get("personality", {}).get("caution", 0.5)),
            diplomacy=fd.get("diplomacy", fd.get("personality", {}).get("diplomacy", 0.5)),
            development_focus=fd.get("development", fd.get("personality", {}).get("development", 0.5)),
            mercy=fd.get("mercy", fd.get("personality", {}).get("mercy", 0.5)),
        )
        self.factions[fid] = fs


WorldState.from_dict = _worldstate_from_dict  # type: ignore[attr-defined]


def _worldstate_get_player_faction(self) -> "FactionState | None":
    """Backward-compat: return the player's faction."""
    return self.factions.get(self.player_faction_id)


WorldState.get_player_faction = _worldstate_get_player_faction  # type: ignore[attr-defined]
