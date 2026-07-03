"""
Knowledge data loader for v2 engine integration.

Maps scenarios/{id}/knowledge/ JSON data to histrategy_engine.world dataclasses.

.. deprecated::
    Prefer :class:`histrategy.engine.scenario_loader.ScenarioLoader` for new code.
    The module-level functions are kept for backward compatibility and delegate
    to ScenarioLoader internally.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

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

# ─── scenario ID ─────────────────────────────────────────────────────────────
# Only canonical scenario IDs are accepted: "three-kingdoms" | "rome-triumvirate".
# Legacy numeric IDs (e.g. "207" for three-kingdoms) are
# no longer mapped — callers must use the canonical names.
_CANONICAL_SCENARIO_IDS: frozenset[str] = frozenset({"three-kingdoms", "rome-triumvirate", "nanming"})


TERRAIN_MAP: dict[str, TerrainType] = {
    "plains": TerrainType.PLAINS,
    "hills": TerrainType.HILLS,
    "mountain": TerrainType.MOUNTAIN,
    "forest": TerrainType.FOREST,
    "wetland": TerrainType.WETLAND,
    "river": TerrainType.RIVER,
    "coast": TerrainType.COAST,
}


def resolve_knowledge_path(scenario_id: str = "three-kingdoms") -> str:
    """Find the knowledge directory for a given scenario.

    Resolves to scenarios/{scenario_id}/knowledge/ (canonical).
    The histrategy-knowledge/ symlink at repo root points here for
    backward compatibility.
    """
    loader_dir = Path(__file__).resolve().parent
    candidates = [
        loader_dir / ".." / ".." / "scenarios" / scenario_id / "knowledge",
        loader_dir / ".." / ".." / ".." / "scenarios" / scenario_id / "knowledge",
        loader_dir / ".." / ".." / "histrategy-knowledge",   # legacy symlink
        loader_dir / ".." / ".." / ".." / "histrategy-knowledge",
    ]
    for p in candidates:
        norm = os.path.abspath(str(p))
        if os.path.isdir(norm):
            return norm
    raise FileNotFoundError(f"Cannot locate scenarios/{scenario_id}/knowledge/")


def _find_scenarios_root() -> Path:
    """Find the scenarios/ directory relative to the project root."""
    loader_dir = Path(__file__).resolve().parent
    candidates = [
        loader_dir.parent / "scenarios",
        loader_dir.parent.parent / "scenarios",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    raise FileNotFoundError("Cannot locate scenarios/")


def _territory_from_json(td: dict) -> Territory:
    """Build a Territory from a JSON dict, supporting both TK and Caesar field names."""
    terrain_str = td.get("terrain", "plains")
    terrain = TERRAIN_MAP.get(terrain_str, TerrainType.PLAINS)

    # Support both `population`/`development` (TK) and `base_population`/`base_development` (Caesar)
    population = td.get("population", td.get("base_population", 50000))
    development = td.get("development", td.get("base_development", 30))
    climate_zone = td.get("climate_zone", td.get("region", "central"))

    return Territory(
        id=td["id"],
        name=td["name"],
        owner_id=td.get("owner_id", ""),
        fertility=td.get("fertility", 5),
        terrain_type=terrain,
        climate_zone=climate_zone,
        has_river=td.get("has_river", False),
        has_coast=td.get("has_coast", td.get("has_port", False)),
        horse_resource=td.get("horse_resource", False),
        iron_resource=td.get("iron_resource", False),
        salt_resource=td.get("salt_resource", False),
        neighbors=td.get("neighbors", []),
        population=population,
        development=development,
    )


def load_territories(
    scenario_id: str = "three-kingdoms",
    knowledge_path: str | None = None,
) -> dict[str, Territory]:
    """Load territory data from scenarios/{scenario_id}/knowledge/territories.json.

    Delegates to :class:`~histrategy.engine.scenario_loader.ScenarioLoader`.

    Args:
        scenario_id: Scenario directory name (e.g. "three-kingdoms", "rome-triumvirate").
        knowledge_path: Deprecated fallback; ignored unless the scenarios/ file is missing.

    Returns:
        Dict of territory_id -> Territory objects.
    """
    from .scenario_loader import ScenarioLoader

    loader = ScenarioLoader(scenario_id)

    try:
        return loader.load_territories()
    except FileNotFoundError:
        pass

    # ── fully-inline legacy fallback ────────────────────────────────────
    try:
        scenarios_root = _find_scenarios_root()
    except FileNotFoundError:
        scenarios_root = None

    territory_path = None
    if scenarios_root:
        candidate = scenarios_root / scenario_id / "knowledge" / "territories.json"
        if candidate.is_file():
            territory_path = candidate

    if territory_path is None and knowledge_path:
        candidate = Path(knowledge_path) / "territories.json"
        if candidate.is_file():
            territory_path = candidate

    if territory_path is None and scenarios_root and scenario_id != "three-kingdoms":
        territory_path = scenarios_root / "three-kingdoms" / "knowledge" / "territories.json"
        if not territory_path.is_file():
            territory_path = None

    if territory_path is None:
        raise FileNotFoundError(
            f"Cannot find territories.json for scenario '{scenario_id}' in scenarios/ or knowledge_path"
        )

    with open(territory_path, encoding="utf-8") as f:
        data = json.load(f)

    territories: dict[str, Territory] = {}
    for td in data:
        t = _territory_from_json(td)
        territories[t.id] = t

    return territories


def load_characters(knowledge_path: str | None = None, scenario_id: str = "three-kingdoms") -> dict[str, Character]:
    """Load character data from knowledge base.

    Reads from scenarios/{scenario_id}/knowledge/roster.json or falls back
    to the default 207 character set.
    """
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path(scenario_id)

    # Try roster.json first (new scenario format), then 207_roster.json (legacy)
    for fname in ("roster.json", "207_roster.json"):
        char_path = os.path.join(knowledge_path, fname)
        if os.path.isfile(char_path):
            break
    else:
        # Try characters subdirectory (old format)
        char_path = os.path.join(knowledge_path, "characters", "207_roster.json")
        if not os.path.isfile(char_path):
            # Also try legacy path from old histrategy-knowledge/
            legacy = os.path.join(knowledge_path, "..", "..", "histrategy-knowledge", "characters", "207_roster.json")
            if os.path.isfile(legacy):
                char_path = os.path.abspath(legacy)
            else:
                return _default_characters()

    with open(char_path) as f:
        data = json.load(f)

    characters: dict[str, Character] = {}
    for cd in data.get("characters", []):
        stats = cd.get("stats", {})
        char = Character(
            id=cd["id"],
            name=cd["name"],
            alias=cd.get("alias", ""),
            leadership=stats.get("leadership", 50),
            might=stats.get("might", 50),
            intelligence=stats.get("intelligence", 50),
            politics=stats.get("politics", 50),
            charisma=stats.get("charisma", 50),
            skills=cd.get("skills", []),
            sworn_brothers=cd.get("sworn_brothers", []),
            spouse=cd.get("spouse", ""),
            mentor=cd.get("mentor", ""),
            faction_id=cd.get("faction", ""),
            location=cd.get("location", ""),
            loyalty=cd.get("loyalty", 80),
            birth=cd.get("birth", 150),
            death=cd.get("death", 200),
            is_governor=cd.get("role") == "governor",
            is_commanding=cd.get("role") in ("general", "commander"),
        )
        characters[cd["id"]] = char

    return characters if characters else _default_characters()


def _default_characters() -> dict[str, Character]:
    """Minimal character set for 207 scenario."""
    return {
        "liubei": Character(
            id="liubei",
            name="刘备",
            alias="玄德",
            leadership=80,
            might=70,
            intelligence=72,
            politics=82,
            charisma=99,
            faction_id="shu",
            location="xinye",
            loyalty=100,
            birth=161,
            death=223,
        ),
        "guanyu": Character(
            id="guanyu",
            name="关羽",
            alias="云长",
            leadership=95,
            might=98,
            intelligence=75,
            politics=62,
            charisma=88,
            faction_id="shu",
            location="xinye",
            loyalty=100,
            is_commanding=True,
            sworn_brothers=["liubei", "zhangfei"],
            birth=160,
            death=220,
        ),
        "zhangfei": Character(
            id="zhangfei",
            name="张飞",
            alias="翼德",
            leadership=85,
            might=98,
            intelligence=45,
            politics=30,
            charisma=50,
            faction_id="shu",
            location="xinye",
            loyalty=98,
            sworn_brothers=["liubei", "guanyu"],
            birth=165,
            death=221,
        ),
        "zhugeliang": Character(
            id="zhugeliang",
            name="诸葛亮",
            alias="孔明",
            leadership=92,
            might=32,
            intelligence=100,
            politics=98,
            charisma=90,
            faction_id="",
            location="longzhong",
            loyalty=50,
            birth=181,
            death=234,
        ),
        "zhaoyun": Character(
            id="zhaoyun",
            name="赵云",
            alias="子龙",
            leadership=89,
            might=95,
            intelligence=76,
            politics=67,
            charisma=82,
            faction_id="shu",
            location="xinye",
            loyalty=95,
            birth=168,
            death=229,
        ),
        "caocao": Character(
            id="caocao",
            name="曹操",
            alias="孟德",
            leadership=98,
            might=72,
            intelligence=93,
            politics=94,
            charisma=92,
            faction_id="cao",
            location="xuchang",
            loyalty=100,
            birth=155,
            death=220,
        ),
        "sunquan": Character(
            id="sunquan",
            name="孙权",
            alias="仲谋",
            leadership=75,
            might=60,
            intelligence=82,
            politics=88,
            charisma=85,
            faction_id="wu",
            location="jianye",
            loyalty=100,
            birth=182,
            death=252,
        ),
        "zhouyu": Character(
            id="zhouyu",
            name="周瑜",
            alias="公瑾",
            leadership=95,
            might=65,
            intelligence=94,
            politics=80,
            charisma=85,
            faction_id="wu",
            location="chaisang",
            loyalty=90,
            is_commanding=True,
            birth=175,
            death=210,
        ),
        "liubiao": Character(
            id="liubiao",
            name="刘表",
            alias="景升",
            leadership=55,
            might=30,
            intelligence=68,
            politics=75,
            charisma=70,
            faction_id="liubiao",
            location="xiangyang",
            loyalty=100,
            birth=142,
            death=208,
        ),
    }


def load_scenario(
    scenario_id: str,
    knowledge_path: str | None = None,
) -> dict | None:
    """Load a scenario definition from knowledge base.

    Reads from scenarios/{scenario_id}/knowledge/ directory.
    """
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path(scenario_id)

    # New format: scenarios/<id>/knowledge/<id>_*.json or any .json
    scenario_dir = os.path.join(knowledge_path, "..", "..", "scenarios", scenario_id, "knowledge")
    if not os.path.isdir(scenario_dir):
        # Try the knowledge_path directly (it may already be the scenario knowledge dir)
        scenario_dir = knowledge_path

    if not os.path.isdir(scenario_dir):
        return None

    # Legacy alias: "three-kingdoms" → "207" for old filename compatibility
    search_ids = [scenario_id]
    if scenario_id == "three-kingdoms":
        search_ids.append("207")

    for sid in search_ids:
        for fname in os.listdir(scenario_dir):
            if fname.endswith(".json") and sid in fname:
                fpath = os.path.join(scenario_dir, fname)
                with open(fpath) as f:
                    return json.load(f)

    return None


def build_world_state(
    player_faction_id: str,
    scenario_id: str = "three-kingdoms",
    knowledge_path: str | None = None,
) -> WorldState:
    """Build a complete WorldState for a new game.

    Delegates to :class:`~histrategy.engine.scenario_loader.ScenarioLoader`
    for all data loading.  The ``knowledge_path`` argument is kept for backward
    compatibility but is only used as a fallback when the scenario does not yet
    have its own data files.

    Args:
        player_faction_id: The faction the player controls ("shu", "cao", "wu")
        scenario_id: Scenario identifier (e.g. "three-kingdoms")
        knowledge_path: Deprecated; path to scenario knowledge

    Returns:
        Fully initialized WorldState ready for engine use.
    """
    from .scenario_loader import ScenarioLoader

    loader = ScenarioLoader(scenario_id)

    try:
        return loader.build_world_state(player_faction_id)
    except FileNotFoundError:
        # If the scenario loader can't find data, fall back to the
        # fully-inline legacy path below.
        pass

    # ── fully-inline legacy fallback ──
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path()

    territories = load_territories(scenario_id=scenario_id, knowledge_path=knowledge_path)
    characters = load_characters(knowledge_path)
    scenario = load_scenario(scenario_id, knowledge_path)

    # Override territory attributes from scenario if defined
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

    season = Season.SPRING
    if scenario:
        season_str = scenario.get("season", "winter")
        season_map = {
            "spring": Season.SPRING,
            "summer": Season.SUMMER,
            "autumn": Season.AUTUMN,
            "winter": Season.WINTER,
        }
        season = season_map.get(season_str, Season.WINTER)

    factions: dict[str, FactionState] = {}
    if scenario and "factions" in scenario:
        for fid, fd in scenario["factions"].items():
            personality = fd.get("personality", {})
            factions[fid] = FactionState(
                id=fid,
                name=fd["name"],
                ruler_id=fd.get("ruler", ""),
                capital=fd.get("capital", ""),
                territories=list(fd.get("territories", [])),
                is_active=fd.get("is_active_manually", True),
                prestige=fd.get("prestige", 50),
                legitimacy=fd.get("legitimacy", 50),
                strength_actual=fd.get("strength", 5000),
                economy_actual=50,
                morale_actual=fd.get("morale_actual", 50),
                treasury=fd.get("treasury", 5000),
                food=fd.get("food", 3000),
                tax_rate=fd.get("tax_rate", 0.3),
                tech_levels=fd.get("tech_levels", {}),
                relations=fd.get("relations", {}),
                allies=[],
                enemies=[],
                strength_estimated=fd.get("strength", 5000),
                economy_estimated=50,
                morale_estimated=fd.get("morale_actual", 50),
                aggression=personality.get("aggression", 0.5),
                cunning=personality.get("cunning", 0.5),
                caution=personality.get("caution", 0.5),
                diplomacy=personality.get("diplomacy", 0.5),
                development_focus=personality.get("development", 0.5),
                mercy=personality.get("mercy", 0.5),
            )
    else:
        factions = _default_factions()

    for fid, faction in factions.items():
        for tid in faction.territories:
            if tid in territories:
                territories[tid].owner_id = fid

    for _cid, char in characters.items():
        if char.faction_id and char.faction_id in factions:
            pass

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

    return WorldState(
        year=scenario.get("year", 207) if scenario else 207,
        season=season,
        turn_number=1,
        scenario=scenario_id,
        player_faction_id=player_faction_id,
        territories=territories,
        characters=characters,
        factions=factions,
        armies=armies,
        player_deviation=0.0,
    )


def _default_factions() -> dict[str, FactionState]:
    """Default faction configurations for 207 scenario."""
    return {
        "shu": FactionState(
            id="shu",
            name="刘备军",
            ruler_id="liubei",
            capital="xinye",
            territories=["xinye"],
            strength_actual=5000,
            treasury=3000,
            food=2000,
            tax_rate=0.2,
            morale_actual=70,
            prestige=35,
            relations={"cao": -80, "wu": 20, "liubiao": 40},
            aggression=0.3,
            cunning=0.3,
            caution=0.7,
            diplomacy=0.8,
            development_focus=0.8,
            mercy=0.95,
        ),
        "cao": FactionState(
            id="cao",
            name="曹操军",
            ruler_id="caocao",
            capital="xuchang",
            territories=["xuchang", "wancheng", "luoyang", "ye"],
            strength_actual=150000,
            treasury=50000,
            food=30000,
            tax_rate=0.4,
            morale_actual=80,
            prestige=90,
            relations={"shu": -80, "wu": -30, "liubiao": -20},
            aggression=0.8,
            cunning=0.9,
            caution=0.3,
            diplomacy=0.5,
            development_focus=0.6,
            mercy=0.2,
        ),
        "wu": FactionState(
            id="wu",
            name="孙权军",
            ruler_id="sunquan",
            capital="jianye",
            territories=["jianye", "wu", "kuaiji", "chaisang"],
            strength_actual=60000,
            treasury=15000,
            food=10000,
            tax_rate=0.3,
            morale_actual=75,
            prestige=60,
            relations={"cao": -30, "shu": 20, "liubiao": -10},
            aggression=0.6,
            cunning=0.6,
            caution=0.5,
            diplomacy=0.6,
            development_focus=0.6,
            mercy=0.5,
        ),
        "liubiao": FactionState(
            id="liubiao",
            name="刘表军",
            ruler_id="liubiao",
            capital="xiangyang",
            territories=["xiangyang", "jiangling", "jiangkou"],
            strength_actual=40000,
            treasury=10000,
            food=8000,
            tax_rate=0.3,
            morale_actual=50,
            prestige=50,
            relations={"cao": -20, "shu": 40, "wu": -10},
            aggression=0.3,
            cunning=0.3,
            caution=0.8,
            diplomacy=0.6,
            development_focus=0.7,
            mercy=0.5,
        ),
    }
