"""Game world state and simulation engine for 三國志略."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).parent.parent / "knowledge" / "data"


@dataclass
class Character:
    id: str
    name: str
    alias: str
    title: str
    faction: str
    personality: list[str]
    skills: list[str]
    description: str
    birth: Optional[int] = None
    death: Optional[int] = None
    is_alive: bool = True
    loyalty: int = 70  # 0-100


@dataclass
class Faction:
    id: str
    name: str
    ruler_id: Optional[str]
    color: str
    description: str
    capital: str
    territories: list[str]
    strength: int       # 兵力
    economy: int        # 经济 0-100
    morale: int         # 民心 0-100
    intel_level: int    # 情报 0-100
    aggression: int     # 侵略性 0-100
    diplomacy_tendency: str
    is_active: bool = True
    treasury: int = 10000  # 资金
    food: int = 5000      # 粮草


@dataclass
class Region:
    id: str
    name: str
    capital: str
    description: str
    strategic_value: int
    resources: list[str]
    neighbors: list[str]
    owner: str = ""
    development: int = 50  # 0-100
    garrison: int = 0
    loyalty: int = 60  # 0-100


@dataclass
class HistoricalEvent:
    year: int
    season: str
    title: str
    description: str
    trigger: str
    effects: dict
    is_historical: bool
    has_occurred: bool = False


class GameWorld:
    """The game world state."""

    def __init__(self, scenario: str = "190"):
        self.scenario = scenario
        self.current_year = 190
        self.current_season = "spring"
        self.season_index = 0
        self.seasons = ["spring", "summer", "autumn", "winter"]
        self.turn_count = 0
        self.player_faction_id: Optional[str] = None

        self.characters: dict[str, Character] = {}
        self.factions: dict[str, Faction] = {}
        self.regions: dict[str, Region] = {}
        self.events: list[HistoricalEvent] = []
        self.completed_events: list[str] = []
        self.history_log: list[str] = []

        self._load_all_data()

    def _load_all_data(self):
        """Load knowledge base data."""
        with open(DATA_DIR / "characters.json") as f:
            for c in json.load(f):
                self.characters[c["id"]] = Character(
                    id=c["id"],
                    name=c["name"],
                    alias=c["alias"],
                    title=c["title"],
                    faction=c["faction"],
                    personality=c["personality"],
                    skills=c["skills"],
                    description=c["description"],
                    birth=c.get("birth"),
                    death=c.get("death"),
                )

        with open(DATA_DIR / "factions.json") as f:
            for fa in json.load(f):
                self.factions[fa["id"]] = Faction(
                    id=fa["id"],
                    name=fa["name"],
                    ruler_id=fa["ruler_id"],
                    color=fa["color"],
                    description=fa["description"],
                    capital=fa["capital"],
                    territories=list(fa["starting_territories"]),
                    strength=fa["strength"],
                    economy=fa["economy"],
                    morale=fa["morale"],
                    intel_level=fa["intel_level"],
                    aggression=fa["aggression"],
                    diplomacy_tendency=fa["diplomacy_tendency"],
                )

        with open(DATA_DIR / "regions.json") as f:
            for r in json.load(f):
                # Find owner by checking which faction lists this region in territories
                owner_id = "other"
                for fa in self.factions.values():
                    if r["id"] in fa.territories:
                        owner_id = fa.id
                        break

                self.regions[r["id"]] = Region(
                    id=r["id"],
                    name=r["name"],
                    capital=r["capital"],
                    description=r["description"],
                    strategic_value=r["strategic_value"],
                    resources=r["resources"],
                    neighbors=r["neighbors"],
                    owner=owner_id,
                )

        with open(DATA_DIR / "events.json") as f:
            for e in json.load(f):
                self.events.append(HistoricalEvent(
                    year=e["year"],
                    season=e["season"],
                    title=e["title"],
                    description=e["description"],
                    trigger=e["trigger"],
                    effects=e["effects"],
                    is_historical=e["is_historical"],
                ))

    def get_available_events(self) -> list[HistoricalEvent]:
        """Get events that should occur this turn (deduplicated)."""
        seen = set()
        available = []
        for event in self.events:
            if event.has_occurred:
                continue
            match = False
            if event.year == self.current_year and event.season == self.current_season:
                match = True
            if event.trigger == "game_start" and self.turn_count == 0:
                match = True
            if match and event.title not in seen:
                seen.add(event.title)
                available.append(event)
        return available

    def mark_event_occurred(self, event_title: str):
        for e in self.events:
            if e.title == event_title and not e.has_occurred:
                e.has_occurred = True
                self.completed_events.append(event_title)
                self.history_log.append(f"[{self.current_year} {self.current_season}] {event_title}")
                break

    def advance_turn(self):
        """Advance to next season."""
        self.season_index = (self.season_index + 1) % 4
        self.current_season = self.seasons[self.season_index]
        if self.season_index == 0:
            self.current_year += 1
        self.turn_count += 1

    def get_player_faction(self) -> Optional[Faction]:
        if self.player_faction_id:
            return self.factions.get(self.player_faction_id)
        return None

    def get_faction_characters(self, faction_id: str) -> list[Character]:
        return [c for c in self.characters.values() if c.faction == faction_id and c.is_alive]

    def get_faction_regions(self, faction_id: str) -> list[Region]:
        return [r for r in self.regions.values() if r.owner == faction_id]

    def get_state_summary(self) -> dict:
        """Get a summary of the game world for the LLM prompt."""
        player = self.get_player_faction()
        all_factions = [f for f in self.factions.values() if f.is_active]

        world_summary = {
            "date": f"{self.current_year} AD, {self.current_season}",
            "turn": self.turn_count,
            "player_faction": {
                "id": player.id if player else None,
                "name": player.name if player else None,
                "ruler": self.characters[player.ruler_id].name if player and player.ruler_id else None,
                "strength": player.strength if player else 0,
                "economy": player.economy if player else 0,
                "morale": player.morale if player else 0,
                "treasury": player.treasury if player else 0,
                "food": player.food if player else 0,
                "territories": [self.regions[t].name for t in (player.territories if player else [])],
            } if player else None,
            "all_factions": [
                {
                    "id": f.id,
                    "name": f.name,
                    "ruler": self.characters[f.ruler_id].name if f.ruler_id and f.ruler_id in self.characters else "无主",
                    "strength": f.strength,
                    "economy": f.economy,
                    "territory_count": len(f.territories),
                    "relation_to_player": "unknown",
                }
                for f in all_factions if f.id != self.player_faction_id
            ],
            "player_characters": [
                {"name": c.name, "alias": c.alias, "skills": c.skills, "loyalty": c.loyalty}
                for c in self.get_faction_characters(self.player_faction_id)
            ] if self.player_faction_id else [],
            "recent_history": self.history_log[-5:],
            "completed_events": self.completed_events,
        }
        return world_summary

    def get_regions_table(self) -> list[dict]:
        """Get region ownership overview."""
        regions_data = []
        for r in self.regions.values():
            owner_name = self.factions[r.owner].name if r.owner in self.factions else "无主"
            regions_data.append({
                "name": r.name,
                "owner": owner_name,
                "owner_id": r.owner,
                "development": r.development,
                "garrison": r.garrison,
                "value": r.strategic_value,
            })
        return regions_data

    def apply_effects(self, player_decision: str, narrative: str, state_changes: dict):
        """Apply state changes from the LLM's decision processing."""
        player = self.get_player_faction()
        if not player:
            return

        if "strength" in state_changes:
            player.strength = max(0, state_changes["strength"])
        if "economy" in state_changes:
            player.economy = max(0, min(100, state_changes["economy"]))
        if "morale" in state_changes:
            player.morale = max(0, min(100, state_changes["morale"]))
        if "treasury" in state_changes:
            player.treasury = max(0, state_changes["treasury"])
        if "food" in state_changes:
            player.food = max(0, state_changes["food"])

        # NPC faction simulation
        for fa_id, changes in state_changes.get("npc_changes", {}).items():
            if fa_id in self.factions:
                fa = self.factions[fa_id]
                if "strength" in changes:
                    fa.strength = max(0, changes["strength"])
                if "economy" in changes:
                    fa.economy = max(0, min(100, changes["economy"]))

    def get_territory_info(self, territory_id: str) -> Optional[Region]:
        return self.regions.get(territory_id)
