"""
ScenarioLoader — unified scenario data loader for the Scenarios/{id}/ directory.

Replaces the ad-hoc loader functions with a single class that reads from the
standardised scenarios/ directory structure:

    scenarios/{scenario_id}/
        scenario.toml          — engine & faction config
        knowledge/
            territories.json   — map territories
            factions.json      — faction definitions (array or dict)
            characters.json    — character roster
            events.json        — scripted/historical events
            initial_state.json — full initial WorldState snapshot
        prompts/
            system.md          — system prompt template
            ...
        rules/
            *.yaml             — rule configuration files

For backwards compatibility, when a scenario does not yet have its own data
files the loader falls back to the old histrategy-knowledge/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import tomllib
from histrategy_engine.world import (
    Army,
    Character,
    FactionState,
    Season,
    TerrainType,
    Territory,
    UnitType,
    WorldState,
)

from .loader import (
    TERRAIN_MAP,
    _default_characters,
    _default_factions,
    _find_scenarios_root,
    _territory_from_json,
    resolve_knowledge_path,
)
from .loader import (
    load_characters as _legacy_load_characters,
)

# ─── helpers ────────────────────────────────────────────────────────────────

# Canonical scenario directory names.  Any other value is rejected with a
# clear error — legacy numeric IDs (e.g. "207" for three-kingdoms)
# alias must be replaced with the canonical names.


def _validate_scenario_id(scenario_id: str) -> str:
    """Validate and return a canonical scenario ID.

    Raises ValueError if *scenario_id* is not a known canonical name.
    """
    if scenario_id not in ("three-kingdoms", "rome-triumvirate", "nanming"):
        raise ValueError(
            f"Unknown scenario {scenario_id!r}. "
            f"Expected one of: 'three-kingdoms', 'rome-triumvirate'"
        )
    return scenario_id


def _coerce_factions_to_dict(data: list | dict) -> dict:
    """Normalise faction data to a dict keyed by faction id.

    Supports both the array format (rome-triumvirate) and the legacy dict format.
    """
    if isinstance(data, dict):
        return data
    result: dict = {}
    for item in data:
        fid = item.get("id", item.get("name", ""))
        if fid:
            result[fid] = item
    return result


# ─── ScenarioLoader ─────────────────────────────────────────────────────────


class ScenarioLoader:
    """Load scenario data from scenarios/{id}/ directory.

    Usage::

        loader = ScenarioLoader("three-kingdoms")
        ws = loader.build_world_state("shu")

        loader2 = ScenarioLoader("rome-triumvirate")
        ws2 = loader2.build_world_state("octavian")
    """

    def __init__(
        self,
        scenario_id: str = "three-kingdoms",
        scenarios_root: Path | None = None,
    ):
        # Validate scenario ID against known canonical names
        self.scenario_id = _validate_scenario_id(scenario_id)
        self._root = scenarios_root or _find_scenarios_root()
        self._dir = self._root / self.scenario_id
        self._toml = self._load_toml()

    # ── TOML config ─────────────────────────────────────────────────────

    def _load_toml(self) -> dict:
        """Load scenario.toml, returning an empty dict if it doesn't exist."""
        toml_path = self._dir / "scenario.toml"
        if toml_path.is_file():
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        return {}

    @property
    def year_direction(self) -> str:
        """'positive' (AD) or 'negative' (BC)."""
        engine = self._toml.get("engine", {})
        return engine.get("year_direction", "positive")

    @property
    def available_factions(self) -> list[str]:
        """Player-selectable faction IDs from TOML config."""
        factions_cfg = self._toml.get("factions", {})
        return list(factions_cfg.get("available", []))

    @property
    def npc_only_factions(self) -> list[str]:
        """NPC-only faction IDs from TOML config."""
        factions_cfg = self._toml.get("factions", {})
        return list(factions_cfg.get("npc_only", []))

    # ── public data loaders ─────────────────────────────────────────────

    def load_factions(self) -> dict:
        """Read knowledge/factions.json (array or dict format).

        Falls back to initial_state.json factions if factions.json is missing.
        """
        # 1) Try knowledge/factions.json
        factions_path = self._dir / "knowledge" / "factions.json"
        if factions_path.is_file():
            with open(factions_path, encoding="utf-8") as f:
                return _coerce_factions_to_dict(json.load(f))

        # 2) Try initial_state.json factions key
        init = self.load_initial_state()
        if init and "factions" in init:
            return _coerce_factions_to_dict(init["factions"])

        # 3) Try old histrategy-knowledge/ scenario JSON
        try:
            from .loader import load_scenario as _legacy_load_scenario

            scenario = _legacy_load_scenario(self.scenario_id)
            if scenario and "factions" in scenario:
                return scenario["factions"]
        except Exception:
            pass

        # 4) Fall back to hardcoded defaults
        return _default_factions()

    def load_characters(self) -> dict[str, Character]:
        """Read knowledge/characters.json.

        Falls back to the legacy loader when the file is missing.
        """
        char_path = self._dir / "knowledge" / "characters.json"
        if char_path.is_file():
            with open(char_path, encoding="utf-8") as f:
                data = json.load(f)

            # Support both array and {"characters": [...]} formats
            items = data if isinstance(data, list) else data.get("characters", [])

            characters: dict[str, Character] = {}
            for cd in items:
                if isinstance(cd, dict):
                    char = _character_from_dict(cd)
                    characters[char.id] = char
            if characters:
                return characters

        # Fall back to legacy loader (histrategy-knowledge/)
        try:
            return _legacy_load_characters()
        except Exception:
            return _default_characters()

    def load_territories(self) -> dict[str, Territory]:
        """Read knowledge/territories.json.

        Uses the same code path as the P0.3 refactored load_territories().
        """
        territory_path = self._dir / "knowledge" / "territories.json"

        # Fallback: try three-kingdoms if this scenario doesn't have its own
        if not territory_path.is_file() and self.scenario_id != "three-kingdoms":
            fallback = self._root / "three-kingdoms" / "knowledge" / "territories.json"
            if fallback.is_file():
                territory_path = fallback

        if not territory_path.is_file():
            # Last resort: try old knowledge_path
            try:
                kp = resolve_knowledge_path()
                old_path = Path(kp) / "territories.json"
                if old_path.is_file():
                    territory_path = old_path
            except Exception:
                pass

        if not territory_path.is_file():
            raise FileNotFoundError(f"Cannot find territories.json for scenario '{self.scenario_id}'")

        with open(territory_path, encoding="utf-8") as f:
            data = json.load(f)

        territories: dict[str, Territory] = {}
        for td in data:
            t = _territory_from_json(td)
            territories[t.id] = t
        return territories

    def load_initial_state(self) -> dict | None:
        """Read knowledge/initial_state.json."""
        init_path = self._dir / "knowledge" / "initial_state.json"
        if init_path.is_file():
            with open(init_path, encoding="utf-8") as f:
                return json.load(f)
        return None

    def load_prompt(self, name: str = "system") -> str:
        """Read prompts/{name}.md."""
        prompt_path = self._dir / "prompts" / f"{name}.md"
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8")

        # Fallback: try old prompt_loader
        try:
            from histrategy.llm.prompt_loader import load_prompt as _load_prompt

            return _load_prompt(name)
        except Exception:
            pass

        raise FileNotFoundError(f"No prompt '{name}.md' in {self._dir / 'prompts'} and no fallback available")

    def load_rules(self) -> list[Path]:
        """List rules/*.yaml files in the scenario directory."""
        rules_dir = self._dir / "rules"
        if not rules_dir.is_dir():
            return []
        return sorted(rules_dir.glob("*.yaml"))

    # ── world state assembly ────────────────────────────────────────────

    def build_world_state(self, player_faction_id: str) -> WorldState:
        """Assemble a complete WorldState from scenario data.

        For scenarios with an initial_state.json this is the canonical path;
        otherwise falls back to the legacy build_world_state() codepath.
        """
        # Load territories and characters
        territories = self.load_territories()
        characters = self.load_characters()

        # Try initial_state.json first (modern path)
        init = self.load_initial_state()
        if init and "factions" in init:
            return self._build_from_initial_state(init, player_faction_id, territories, characters)

        # Legacy path: use old histrategy-knowledge/ scenario JSON
        from .loader import load_scenario as _legacy_load_scenario

        scenario = _legacy_load_scenario(self.scenario_id)
        knowledge_path = resolve_knowledge_path()

        return self._build_from_legacy_scenario(scenario, player_faction_id, territories, characters, knowledge_path)

    def _build_from_initial_state(
        self,
        init: dict,
        player_faction_id: str,
        territories: dict[str, Territory],
        characters: dict[str, Character],
    ) -> WorldState:
        """Build WorldState from a modern initial_state.json."""
        factions_data = _coerce_factions_to_dict(init.get("factions", {}))
        factions = self._build_factions(factions_data)

        # Override territory ownership from faction data
        for fid, faction in factions.items():
            for tid in faction.territories:
                if tid in territories:
                    territories[tid].owner_id = fid

        # Apply territory overrides from initial_state (population, development, fertility, etc.)
        init_territories = init.get("territories", {})
        if init_territories:
            for tid, td in init_territories.items():
                if tid in territories:
                    t = territories[tid]
                    if "name" in td:
                        t.name = td["name"]
                    if "population" in td:
                        t.population = td["population"]
                    if "development" in td:
                        t.development = td["development"]
                    if "terrain" in td:
                        from ..engine.loader import TERRAIN_MAP

                        t.terrain_type = TERRAIN_MAP.get(td["terrain"], t.terrain_type)
                    if "climate_zone" in td:
                        t.climate_zone = td["climate_zone"]
                    if "fertility" in td:
                        t.fertility = td["fertility"]

        # Determine season
        season_str = init.get("season", "spring")
        season = _parse_season(season_str)

        # Determine year
        year = init.get("year", 207)
        # Apply TOML override
        toml_meta = self._toml.get("meta", {})
        if "start_year" in toml_meta:
            year = toml_meta["start_year"]

        # Create armies
        armies = self._create_armies(factions)

        return WorldState(
            year=year,
            season=season,
            turn_number=1,
            scenario=self.scenario_id,
            player_faction_id=player_faction_id,
            territories=territories,
            characters=characters,
            factions=factions,
            armies=armies,
            player_deviation=0.0,
        )

    def _build_from_legacy_scenario(
        self,
        scenario: dict | None,
        player_faction_id: str,
        territories: dict[str, Territory],
        characters: dict[str, Character],
        knowledge_path: str,
    ) -> WorldState:
        """Build WorldState from legacy histrategy-knowledge/ scenario JSON."""
        # Apply territory overrides from scenario
        if scenario and "territories" in scenario:
            for tid, td in scenario["territories"].items():
                if tid in territories:
                    t = territories[tid]
                    if "name" in td:
                        t.name = td["name"]
                    if "population" in td:
                        t.population = td["population"]
                    if "development" in td:
                        t.development = td["development"]
                    if "terrain" in td:
                        t.terrain_type = TERRAIN_MAP.get(td["terrain"], TerrainType.PLAINS)
                    if "climate_zone" in td:
                        t.climate_zone = td["climate_zone"]
                    if "fertility" in td:
                        t.fertility = td["fertility"]

        # Determine season
        season = Season.SPRING
        if scenario:
            season_str = scenario.get("season", "winter")
            season = _parse_season(season_str)

        # Build factions
        factions: dict[str, FactionState] = {}
        if scenario and "factions" in scenario:
            factions = self._build_factions(scenario["factions"])
        else:
            factions = _default_factions()

        # Assign territory ownership from faction data
        for fid, faction in factions.items():
            for tid in faction.territories:
                if tid in territories:
                    territories[tid].owner_id = fid

        # Create armies
        armies = self._create_armies(factions)

        return WorldState(
            year=scenario.get("year", 207) if scenario else 207,
            season=season,
            turn_number=1,
            scenario=self.scenario_id,
            player_faction_id=player_faction_id,
            territories=territories,
            characters=characters,
            factions=factions,
            armies=armies,
            player_deviation=0.0,
        )

    def _build_factions(self, factions_data: dict) -> dict[str, FactionState]:
        """Build FactionState objects from raw dict data.

        Handles both legacy TK field names and modern rome-triumvirate field names.
        """
        factions: dict[str, FactionState] = {}
        for fid, fd in factions_data.items():
            personality = fd.get("personality", {})

            # Support both `territories` (legacy) and `starting_territories` (caesar)
            faction_territories = list(fd.get("territories", fd.get("starting_territories", [])))

            factions[fid] = FactionState(
                id=fid,
                name=fd.get("name", fid),
                ruler_id=fd.get("ruler", fd.get("ruler_id", "")),
                name_en=fd.get("name_en", ""),
                capital=fd.get("capital", ""),
                territories=faction_territories,
                is_active=fd.get("is_active", fd.get("is_active_manually", True)),
                prestige=fd.get("prestige", 50),
                legitimacy=fd.get("legitimacy", 50),
                strength_actual=fd.get("strength_actual", fd.get("strength", 5000)),
                economy_actual=fd.get("economy_actual", fd.get("economy", 50)),
                morale_actual=fd.get("morale_actual", fd.get("morale", 50)),
                treasury=fd.get("treasury", 5000),
                food=fd.get("food", 3000),
                tax_rate=fd.get("tax_rate", 0.3),
                tech_levels=fd.get("tech_levels", {}),
                relations=fd.get("relations", {}),
                aggression=personality.get("aggression", fd.get("aggression", 0.5)),
                cunning=personality.get("cunning", fd.get("cunning", 0.5)),
                caution=personality.get("caution", fd.get("caution", 0.5)),
                diplomacy=personality.get("diplomacy", fd.get("diplomacy_tendency", 0.5)),
                development_focus=personality.get("development", fd.get("development_focus", 0.5)),
                mercy=personality.get("mercy", fd.get("mercy", 0.5)),
            )
        return factions

    def _create_armies(self, factions: dict[str, FactionState]) -> dict[str, Army]:
        """Create initial armies for active factions."""
        armies: dict[str, Army] = {}
        army_idx = 1
        for fid, faction in factions.items():
            if not faction.is_active or not faction.territories:
                continue
            capital = faction.capital or faction.territories[0]
            army_id = f"army_{fid}_{army_idx}"
            armies[army_id] = Army(
                id=army_id,
                faction_id=fid,
                location=capital,
                commander_id=faction.ruler_id,
                units={UnitType.INFANTRY: min(faction.strength_actual, 5000)},
                morale=80,
                training=1.0,
                supply=30,
            )
            army_idx += 1
        return armies

    # ── utility ─────────────────────────────────────────────────────────

    def format_year(self, year: int) -> str:
        """Render year with BC/AD support.

        - positive year_direction: '公元{year}年'
        - negative year_direction: '公元前{abs(year)}年'
        """
        if self.year_direction == "negative":
            return f"公元前{abs(year)}年"
        return f"公元{year}年"

    def get_timeline_events(self, year: int, season: str) -> list[dict]:
        """Return historical events matching the given year and season.

        Loads knowledge/timeline.json and filters by year+season.
        Returns an empty list if the file doesn't exist or has no match.

        Supports both formats:
        1. Array format (rome-triumvirate): {"year": -43, "season": "spring", ...}
        2. Object format (three-kingdoms): {"events": [{"year": 207, "month": 12, ...}]}
        """
        timeline_path = self._dir / "knowledge" / "timeline.json"
        if not timeline_path.is_file():
            return []

        with open(timeline_path, encoding="utf-8") as f:
            data = json.load(f)

        events: list[dict] = []
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get("events", [])

        # Normalise season to lowercase English
        _SEASON_CN = {"春": "spring", "夏": "summer", "秋": "autumn", "冬": "winter"}
        season_lower = _SEASON_CN.get(season, season.lower())

        # Month → season mapping for three-kingdoms format
        _MONTH_TO_SEASON = {
            3: "spring",
            4: "spring",
            5: "spring",
            6: "summer",
            7: "summer",
            8: "summer",
            9: "autumn",
            10: "autumn",
            11: "autumn",
            12: "winter",
            1: "winter",
            2: "winter",
        }

        matches = []
        for e in events:
            if e.get("year") != year:
                continue
            # Format 1: explicit season field
            if "season" in e:
                ev_season = str(e["season"]).lower()
                if ev_season == season_lower:
                    matches.append(e)
            # Format 2: month field
            elif "month" in e:
                month = int(e["month"])
                if _MONTH_TO_SEASON.get(month) == season_lower:
                    matches.append(e)
            # Format 3: no season or month → match any
            else:
                matches.append(e)

        return matches

    @staticmethod
    def list_scenarios(root: Path | None = None) -> list[str]:
        """List all available scenario IDs (directories containing scenario.toml
        or knowledge/ data)."""
        if root is None:
            root = _find_scenarios_root()
        scenarios: list[str] = []
        if not root.is_dir():
            return scenarios
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            # A valid scenario has either scenario.toml or a knowledge/ subdirectory
            if (entry / "scenario.toml").is_file() or (entry / "knowledge").is_dir():
                scenarios.append(entry.name)
        return scenarios


# ─── character builder ──────────────────────────────────────────────────────


def _character_from_dict(cd: dict) -> Character:
    """Build a Character from a JSON dict.

    Supports both TK field names (stats.leadership, faction, location, loyalty)
    and rome-triumvirate field names (martial, intellect, politics, charisma, faction, role).
    """
    # Stats: TK uses nested stats dict, Caesar uses top-level attributes
    if "stats" in cd:
        stats = cd["stats"]
        leadership = stats.get("leadership", 50)
        might = stats.get("might", 50)
        intelligence = stats.get("intelligence", 50)
        politics_stat = stats.get("politics", 50)
        charisma = stats.get("charisma", 50)
    else:
        # Caesar format: martial, intellect, politics, charisma
        leadership = cd.get("leadership", cd.get("martial", 50))
        might = cd.get("might", cd.get("martial", 50))
        intelligence = cd.get("intelligence", cd.get("intellect", 50))
        politics_stat = cd.get("politics", cd.get("politics", 50))
        charisma = cd.get("charisma", 50)

    # Role detection
    role = cd.get("role", "")
    is_governor = role == "governor"
    is_commanding = role in ("general", "commander", "ruler")

    return Character(
        id=cd["id"],
        name=cd.get("name_cn", cd.get("name", cd["id"])),
        alias=cd.get("alias", cd.get("style", "")),
        leadership=leadership,
        might=might,
        intelligence=intelligence,
        politics=politics_stat,
        charisma=charisma,
        skills=cd.get("skills", cd.get("traits", [])),
        sworn_brothers=cd.get("sworn_brothers", []),
        spouse=cd.get("spouse", ""),
        mentor=cd.get("mentor", ""),
        faction_id=cd.get("faction", ""),
        location=cd.get("location", ""),
        loyalty=cd.get("loyalty", 80),
        birth=cd.get("birth", 150),
        death=cd.get("death", 200),
        is_governor=is_governor,
        is_commanding=is_commanding,
    )


def _parse_season(season_str: str) -> Season:
    """Parse a season string to a Season enum value."""
    season_map = {
        "spring": Season.SPRING,
        "summer": Season.SUMMER,
        "autumn": Season.AUTUMN,
        "winter": Season.WINTER,
    }
    return season_map.get(season_str.lower(), Season.WINTER)
