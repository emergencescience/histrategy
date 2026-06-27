"""
三國志略 — Structured World State System

The world state is the single source of truth for the game world.
Each turn, the LLM receives the full world state and produces an updated one.
This ensures emergent gameplay where every decision has real consequences.

State files stored in ~/.histrategy/ by default.
Set HISTRATEGY_DATA_DIR to override this for development, tests, or portable saves.

  - world_state.json        — Main game world state
  - player_memory.json      — Player's past decisions
  - relationships.json      — Faction relationship matrix
  - event_history.json      — Full chronological event log
  - character_profiles.json — Dynamic character traits
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

# Phase 1: Re-export WorldState/FactionState from unified engine
from histrategy_engine.world import FactionState, WorldState  # noqa: F401

from .npc_state import NPCState, load_npc_states, save_npc_states


class HistoricalMode(Enum):
    HISTORICAL = "historical"
    DIVERGENT = "divergent"
    FREEFORM = "freeform"


# ─── File paths ─────────────────────────────────────────────


def get_data_dir() -> Path:
    """Return the active save directory.

    Defaults to ~/.histrategy for normal installed play. Tests and local
    development can set HISTRATEGY_DATA_DIR to keep saves isolated.
    """
    override = os.environ.get("HISTRATEGY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".histrategy"


DATA_DIR = get_data_dir()


def _world_state_file() -> Path:
    return get_data_dir() / "world_state.json"


def _player_memory_file() -> Path:
    return get_data_dir() / "player_memory.json"


def _relationships_file() -> Path:
    return get_data_dir() / "relationships.json"


def _event_history_file() -> Path:
    return get_data_dir() / "event_history.json"


def _character_profiles_file() -> Path:
    return get_data_dir() / "character_profiles.json"


WORLD_STATE_FILE = _world_state_file()
PLAYER_MEMORY_FILE = _player_memory_file()
RELATIONSHIPS_FILE = _relationships_file()
EVENT_HISTORY_FILE = _event_history_file()
CHARACTER_PROFILES_FILE = _character_profiles_file()


# ─── Data structures ───────────────────────────────────────


@dataclass
class FactionState:  # noqa: F811 — shadowed by re-export at L28
    """State of a single faction at a point in time."""

    id: str
    name: str
    ruler_id: str
    capital: str
    strength: int = 5000  # troops
    economy: int = 50  # 0-100
    morale: int = 50  # 0-100
    treasury: int = 5000  # gold
    food: int = 3000  # grain
    territories: list[str] = field(default_factory=list)
    is_active: bool = True
    personality_applied: str = ""  # last personality-driven narrative tag

    # ── V2/V3 compatibility ─────────────────────────────────────────
    # V2/V3 engine accesses faction.strength_actual / morale_actual.
    # V1 uses strength / morale. Provide aliases.
    @property
    def strength_actual(self) -> int:
        return self.strength

    @strength_actual.setter
    def strength_actual(self, value: int) -> None:
        self.strength = value

    @property
    def morale_actual(self) -> int:
        return self.morale

    @morale_actual.setter
    def morale_actual(self, value: int) -> None:
        self.morale = value


@dataclass
class CharacterState:
    """Dynamic state of a character (may change over game)."""

    id: str
    name: str
    faction_id: str
    loyalty: int = 80  # 0-100
    alive: bool = True
    location: str = ""
    role: str = "general"  # general, advisor, spy, governor
    recent_actions: list[str] = field(default_factory=list)


# ── V2/V3 engine compatibility helper ──────────────────────────────
# V2/V3 code expects ws.season to be an object with .value and .cn
# attributes (like a Season enum). V1 WorldState uses season_index (int).
# This adapter bridges the gap when V3 engine operates on V1 WorldState.


class _SeasonCompat:
    """Lightweight Season-enum-compatible object for V1 → V3 bridging."""

    def __init__(self, value: str, cn: str):
        self.value = value
        self.cn = cn

    def __str__(self) -> str:
        return self.value


@dataclass
class TerritoryState:
    """State of a territory/region."""

    id: str
    name: str
    owner_id: str  # faction id
    economy: int = 50  # 0-100
    population: int = 10000
    garrison: int = 1000
    fortification: int = 20  # 0-100
    unrest: int = 0  # 0-100
    resources: dict = field(default_factory=lambda: {"grain": 1000, "gold": 500, "iron": 200})


@dataclass
class EventEntry:
    """A single event in the timeline."""

    year: int
    season: str
    turn: int
    description: str
    type: str = "event"  # event, battle, decision, diplomatic, natural
    faction_id: str = ""
    is_historical: bool = False
    player_involved: bool = False
    player_decision: str = ""


@dataclass
class WorldState:  # noqa: F811 — shadowed by re-export at L28
    """
    Complete game world state.

    The LLM receives this and produces an updated version each turn.
    This enables truly emergent gameplay where every decision has
    visible consequences.
    """

    # Time
    year: int = 207
    season_index: int = 0  # 0=spring, 1=summer, 2=autumn, 3=winter
    turn: int = 0

    # Player
    player_faction_id: str = ""
    scenario: str = "three-kingdoms"  # scenario identifier

    # World
    factions: dict[str, FactionState] = field(default_factory=dict)
    characters: dict[str, CharacterState] = field(default_factory=dict)
    territories: dict[str, TerritoryState] = field(default_factory=dict)
    npc_states: dict[str, NPCState] = field(default_factory=dict)

    # Events & history
    event_log: list = field(default_factory=list)
    completed_events: list[str] = field(default_factory=list)

    # Historical guidance
    next_major_historical_event: str = "207年：刘备三顾茅庐，诸葛亮出山"
    player_deviation: float = 0.0  # how much history has diverged (0.0 = pure historical)

    SEASONS = ["spring", "summer", "autumn", "winter"]
    SEASON_CN = {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}

    # ── V2/V3 engine compatibility ──────────────────────────────────
    # V2/V3 expect ws.turn_number (int) and ws.season (obj with .cn).
    # V1 uses turn (int) and season_index (int). Provide aliases so
    # the V3 engine (quarterly_resolver, turn_controller, etc.) can
    # operate on V1 WorldState without crashing.

    @property
    def turn_number(self) -> int:
        return self.turn

    @property
    def season(self):
        """Compatibility: return an object with .value and .cn for V2/V3."""
        return _SeasonCompat(self.current_season, self.current_season_cn)

    @property
    def current_season(self) -> str:
        return self.SEASONS[self.season_index % 4]

    @property
    def current_season_cn(self) -> str:
        return self.SEASON_CN.get(self.current_season, self.current_season)

    @property
    def historical_mode(self) -> HistoricalMode:
        if self.player_deviation < 0.15:
            return HistoricalMode.HISTORICAL
        elif self.player_deviation < 0.40:
            return HistoricalMode.DIVERGENT
        else:
            return HistoricalMode.FREEFORM

    def advance_turn(self):
        """Advance by one turn (one season)."""
        self.turn += 1
        self.season_index += 1
        if self.season_index % 4 == 0:
            self.year += 1

    def get_player_faction(self) -> FactionState | None:
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
            "factions": {fid: asdict(fs) for fid, fs in self.factions.items() if fs.is_active},
            "player_faction_id": self.player_faction_id,
            "completed_events": self.completed_events,
            "npc_states": {cid: ns.to_dict() for cid, ns in self.npc_states.items()},
        }

    def from_dict(self, data: dict) -> WorldState:
        """Reconstruct from a dict (e.g. from LLM output or disk)."""
        self.year = data.get("year", self.year)
        self.season_index = data.get("season_index", self.season_index)
        self.turn = data.get("turn", self.turn)
        self.scenario = data.get("scenario", self.scenario)
        self.player_faction_id = data.get("player_faction_id", self.player_faction_id)
        self.next_major_historical_event = data.get("next_major_historical_event", self.next_major_historical_event)
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

        if "npc_states" in data:
            self.npc_states = {cid: NPCState.from_dict(nsd) for cid, nsd in data["npc_states"].items()}

        return self


# ─── Historical knowledge for LLM context ──────────────────

HISTORICAL_TIMELINE_207 = [
    # ── 207: 三顾茅庐 ──
    "207年 冬季：刘备三顾茅庐，诸葛亮出山，献《隆中对》",
    # ── 208: 赤壁之战 ──
    "208年 春季：曹操南征，刘表病逝，刘琮降曹",
    "208年 夏季：刘备携民渡江，赵云长坂坡救阿斗",
    "208年 秋季：诸葛亮使吴，孙刘联军抗曹",
    "208年 冬季：赤壁之战大捷，曹操败走华容道",
    # ── 209-210: 取荆州 ──
    "209年 春季：刘备取荆南四郡（零陵、武陵、长沙、桂阳）",
    "209年 夏季：孙刘联姻，刘备娶孙尚香",
    "210年 冬季：周瑜病逝，刘备借荆州",
    # ── 211-214: 入蜀 ──
    "211年 冬季：刘备入蜀，留诸葛亮关羽守荆州",
    "212年 夏季：刘备与刘璋决裂，庞统中箭身亡",
    "214年 夏季：刘备攻克成都，领益州牧",
    # ── 215-219: 汉中之战 ──
    "215年 夏季：孙刘湘水划界，平分荆州",
    "217年 冬季：刘备发动汉中战役",
    "219年 春季：黄忠斩夏侯渊，刘备取汉中",
    "219年 夏季：刘备自立为汉中王",
    "219年 秋季：关羽北伐，水淹七军擒于禁斩庞德",
    # ── 219-220: 荆州陷落 ──
    "219年 冬季：吕蒙白衣渡江，关羽失荆州败走麦城被杀",
    "220年 春季：曹操病逝于洛阳",
    "220年 冬季：曹丕篡汉，东汉灭亡",
    # ── 221-223: 夷陵之战与托孤 ──
    "221年 夏季：刘备称帝，国号汉（蜀汉）",
    "221年 秋季：刘备发动夷陵之战伐吴",
    "222年 夏季：陆逊火烧连营七百里，刘备大败",
    "223年 春季：刘备白帝城托孤诸葛亮，驾崩",
]


def get_historical_context(year: int) -> str:
    """Get the historical timeline for a given year and around it."""
    relevant = []
    for entry in HISTORICAL_TIMELINE_207:
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
    get_data_dir().mkdir(parents=True, exist_ok=True)


def save_world(state: WorldState):
    """Save the world state to disk."""
    ensure_dir()
    data = state.to_dict()
    # Add extra data
    data["saved_at"] = datetime.now().isoformat()
    with open(_world_state_file(), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if state.npc_states:
        save_npc_states(state.npc_states)


def load_world() -> WorldState | None:
    """Load the world state from disk."""
    path = _world_state_file()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        state = WorldState()
        state.from_dict(data)
        npc_data = load_npc_states()
        if npc_data:
            state.npc_states.update(npc_data)
        return state
    except (json.JSONDecodeError, OSError):
        return None


def save_relationships(rels: dict[str, dict[str, int]]):
    """Save inter-faction relationships."""
    ensure_dir()
    with open(_relationships_file(), "w") as f:
        json.dump(rels, f, ensure_ascii=False, indent=2)


def load_relationships() -> dict[str, dict[str, int]]:
    """Load inter-faction relationships."""
    path = _relationships_file()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def add_event_to_history(event: EventEntry):
    """Append an event to the history log file."""
    ensure_dir()
    history = load_event_history()
    history.append(asdict(event))
    with open(_event_history_file(), "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_event_history() -> list[dict]:
    """Load full event history."""
    path = _event_history_file()
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def get_recent_history(n: int = 5) -> list[dict]:
    """Get the n most recent events."""
    history = load_event_history()
    return history[-n:]


def has_existing_game() -> bool:
    """Check if there's a saved game to resume."""
    return _world_state_file().exists()
