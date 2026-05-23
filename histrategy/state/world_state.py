"""
三國志略 — Structured World State System

The world state is the single source of truth for the game world.
Each turn, the LLM receives the full world state and produces an updated one.
This ensures emergent gameplay where every decision has real consequences.

State files stored in ~/.histrategy/:
  - world_state.json        — Main game world state
  - player_memory.json      — Player's past decisions
  - relationships.json      — Faction relationship matrix
  - event_history.json      — Full chronological event log
  - character_profiles.json — Dynamic character traits
"""

from __future__ import annotations

import json
import os
import copy
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─── File paths ─────────────────────────────────────────────

DATA_DIR = Path.home() / ".histrategy"

WORLD_STATE_FILE = DATA_DIR / "world_state.json"
PLAYER_MEMORY_FILE = DATA_DIR / "player_memory.json"
RELATIONSHIPS_FILE = DATA_DIR / "relationships.json"
EVENT_HISTORY_FILE = DATA_DIR / "event_history.json"
CHARACTER_PROFILES_FILE = DATA_DIR / "character_profiles.json"


# ─── Data structures ───────────────────────────────────────


@dataclass
class FactionState:
    """State of a single faction at a point in time."""
    id: str
    name: str
    ruler_id: str
    capital: str
    strength: int = 5000           # troops
    economy: int = 50              # 0-100
    morale: int = 50               # 0-100
    treasury: int = 5000           # gold
    food: int = 3000               # grain
    territories: list[str] = field(default_factory=list)
    is_active: bool = True
    personality_applied: str = ""  # last personality-driven narrative tag


@dataclass
class CharacterState:
    """Dynamic state of a character (may change over game)."""
    id: str
    name: str
    faction_id: str
    loyalty: int = 80             # 0-100
    alive: bool = True
    location: str = ""
    role: str = "general"         # general, advisor, spy, governor
    recent_actions: list[str] = field(default_factory=list)


@dataclass
class TerritoryState:
    """State of a territory/region."""
    id: str
    name: str
    owner_id: str                  # faction id
    economy: int = 50              # 0-100
    population: int = 10000
    garrison: int = 1000
    resources: dict = field(default_factory=lambda: {"grain": 1000, "gold": 500, "iron": 200})


@dataclass
class EventEntry:
    """A single event in the timeline."""
    year: int
    season: str
    turn: int
    description: str
    type: str = "event"           # event, battle, decision, diplomatic, natural
    faction_id: str = ""
    is_historical: bool = False
    player_involved: bool = False
    player_decision: str = ""


@dataclass
class WorldState:
    """
    Complete game world state.

    The LLM receives this and produces an updated version each turn.
    This enables truly emergent gameplay where every decision has
    visible consequences.
    """
    # Time
    year: int = 190
    season_index: int = 0          # 0=spring, 1=summer, 2=autumn, 3=winter
    turn: int = 0

    # Player
    player_faction_id: str = ""
    scenario: str = "190"          # scenario identifier

    # World
    factions: dict[str, FactionState] = field(default_factory=dict)
    characters: dict[str, CharacterState] = field(default_factory=dict)
    territories: dict[str, TerritoryState] = field(default_factory=dict)

    # Events & history
    event_log: list = field(default_factory=list)
    completed_events: list[str] = field(default_factory=list)

    # Historical guidance
    next_major_historical_event: str = "190年：董卓之乱，曹操发矫诏讨董"
    player_deviation: float = 0.0  # how much history has diverged (0.0 = pure historical)

    SEASONS = ["spring", "summer", "autumn", "winter"]
    SEASON_CN = {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}

    @property
    def current_season(self) -> str:
        return self.SEASONS[self.season_index % 4]

    @property
    def current_season_cn(self) -> str:
        return self.SEASON_CN.get(self.current_season, self.current_season)

    def advance_turn(self):
        """Advance by one turn (one season)."""
        self.turn += 1
        self.season_index += 1
        if self.season_index % 4 == 0:
            self.year += 1

    def get_player_faction(self) -> Optional[FactionState]:
        return self.factions.get(self.player_faction_id)

    def to_dict(self) -> dict:
        """Serialize to dict for LLM prompt."""
        return {
            "year": self.year,
            "season": self.current_season,
            "season_cn": self.current_season_cn,
            "turn": self.turn,
            "scenario": self.scenario,
            "next_major_historical_event": self.next_major_historical_event,
            "player_deviation": round(self.player_deviation, 2),
            "factions": {
                fid: asdict(fs)
                for fid, fs in self.factions.items()
                if fs.is_active
            },
            "player_faction_id": self.player_faction_id,
            "completed_events": self.completed_events,
        }

    def from_dict(self, data: dict) -> WorldState:
        """Reconstruct from a dict (e.g. from LLM output or disk)."""
        self.year = data.get("year", self.year)
        self.season_index = data.get("season_index", self.season_index)
        self.turn = data.get("turn", self.turn)
        self.scenario = data.get("scenario", self.scenario)
        self.player_faction_id = data.get("player_faction_id", self.player_faction_id)
        self.next_major_historical_event = data.get(
            "next_major_historical_event", self.next_major_historical_event
        )
        self.player_deviation = data.get("player_deviation", self.player_deviation)

        if "factions" in data:
            for fid, fsd in data["factions"].items():
                self.factions[fid] = FactionState(**fsd)

        if "events" in data:
            for ev in data["events"]:
                if isinstance(ev, dict):
                    self.event_log.append(EventEntry(**ev))
                else:
                    self.event_log.append(ev)

        if "completed_events" in data:
            self.completed_events = data["completed_events"]

        return self


# ─── Historical knowledge for LLM context ──────────────────

HISTORICAL_TIMELINE_190 = [
    "190年 春季：曹操发矫诏，号召天下诸侯讨伐董卓",
    "190年 夏季：关东诸侯推袁绍为盟主，联军讨董",
    "190年 秋季：董卓迁都长安，火烧洛阳",
    "190年 冬季：诸侯联军内讧，孙坚攻入洛阳得传国玉玺",
    "191年 春季：袁绍夺韩馥冀州，公孙瓒与袁绍冲突",
    "191年 夏季：曹操击败青州黄巾军，收编降卒",
    "191年 秋季：孙坚与刘表交战，战死于襄阳",
    "191年 冬季：曹操在兖州站稳脚跟，招贤纳士",
    "192年 春季：袁术与袁绍决裂，公孙瓒与刘备结盟",
    "192年 夏季：董卓被吕布所杀，李傕郭汜反攻长安",
    "192年 秋季：曹操收编青州兵三十万",
    "192年 冬季：李傕郭汜把持朝政，献帝颠沛流离",
    "193年 春季：曹操父亲曹嵩被陶谦部将所杀",
    "193年 夏季：曹操攻打徐州，沿途屠杀百姓",
    "193年 秋季：吕布趁虚袭取兖州，曹操回师",
    "193年 冬季：曹操与吕布在濮阳大战",
    "194年 春季：陶谦病逝，刘备领徐州牧",
    "194年 夏季：长安大旱，人相食",
    "194年 秋季：吕布败走徐州，投奔刘备",
    "194年 冬季：孙策借兵渡江，开拓江东",
    "195年 春季：曹操收复兖州，吕布投刘备",
    "195年 夏季：献帝出逃长安，辗转至洛阳",
    "195年 秋季：曹操迎献帝于许昌，挟天子以令诸侯",
    "195年 冬季：曹操灭吕布于下邳",
]


def get_historical_context(year: int) -> str:
    """Get the historical timeline for a given year and around it."""
    relevant = []
    for entry in HISTORICAL_TIMELINE_190:
        year_str = entry.split("年")[0]
        try:
            entry_year = int(year_str)
            if abs(entry_year - year) <= 3:
                relevant.append(entry)
        except ValueError:
            continue
    return "\n".join(relevant) if relevant else "暂无已知历史记录"


# ─── Save/Load ─────────────────────────────────────────────


def ensure_dir():
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_world(state: WorldState):
    """Save the world state to disk."""
    ensure_dir()
    data = state.to_dict()
    # Add extra data
    data["saved_at"] = datetime.now().isoformat()
    with open(WORLD_STATE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_world() -> Optional[WorldState]:
    """Load the world state from disk."""
    if not WORLD_STATE_FILE.exists():
        return None
    try:
        with open(WORLD_STATE_FILE) as f:
            data = json.load(f)
        state = WorldState()
        state.from_dict(data)
        return state
    except (json.JSONDecodeError, OSError):
        return None


def save_relationships(rels: dict[str, dict[str, int]]):
    """Save inter-faction relationships."""
    ensure_dir()
    with open(RELATIONSHIPS_FILE, "w") as f:
        json.dump(rels, f, ensure_ascii=False, indent=2)


def load_relationships() -> dict[str, dict[str, int]]:
    """Load inter-faction relationships."""
    if not RELATIONSHIPS_FILE.exists():
        return {}
    try:
        with open(RELATIONSHIPS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def add_event_to_history(event: EventEntry):
    """Append an event to the history log file."""
    ensure_dir()
    history = load_event_history()
    history.append(asdict(event))
    with open(EVENT_HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_event_history() -> list[dict]:
    """Load full event history."""
    if not EVENT_HISTORY_FILE.exists():
        return []
    try:
        with open(EVENT_HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def get_recent_history(n: int = 5) -> list[dict]:
    """Get the n most recent events."""
    history = load_event_history()
    return history[-n:]


def has_existing_game() -> bool:
    """Check if there's a saved game to resume."""
    return WORLD_STATE_FILE.exists()
