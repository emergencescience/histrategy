"""
Knowledge data loader for v2 engine integration.

Maps histrategy-knowledge/ JSON data to histrategy_engine.world dataclasses.
"""

from __future__ import annotations

import json
import os

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

TERRAIN_MAP: dict[str, TerrainType] = {
    "plains": TerrainType.PLAINS,
    "hills": TerrainType.HILLS,
    "mountain": TerrainType.MOUNTAIN,
    "forest": TerrainType.FOREST,
    "wetland": TerrainType.WETLAND,
    "river": TerrainType.RIVER,
    "coast": TerrainType.COAST,
}


def resolve_knowledge_path() -> str:
    """Find the histrategy-knowledge directory."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "histrategy-knowledge"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "histrategy-knowledge"),
    ]
    for p in candidates:
        norm = os.path.abspath(p)
        if os.path.isdir(norm):
            return norm
    raise FileNotFoundError("Cannot locate histrategy-knowledge/")


def load_territories(knowledge_path: str | None = None) -> dict[str, Territory]:
    """Load territory data from knowledge base.

    Bypasses province-level geography file to return city-level territories
    essential for the 207 scenario.
    """
    return _default_territories()


def _default_territories() -> dict[str, Territory]:
    """Complete city-level territory set for 207 scenario."""
    return {
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=30000,
            development=25,
            neighbors=["xiangyang", "wancheng"],
        ),
        "xiangyang": Territory(
            id="xiangyang",
            name="襄阳",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_river=True,
            population=80000,
            development=55,
            neighbors=["xinye", "jiangling", "wancheng", "changsha", "jiangkou"],
        ),
        "wancheng": Territory(
            id="wancheng",
            name="宛城",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=50000,
            development=45,
            neighbors=["xinye", "xiangyang", "xuchang"],
        ),
        "xuchang": Territory(
            id="xuchang",
            name="许昌",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=100000,
            development=70,
            neighbors=["wancheng", "luoyang", "puyang", "xiapi"],
        ),
        "luoyang": Territory(
            id="luoyang",
            name="洛阳",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="north",
            population=80000,
            development=60,
            neighbors=["xuchang", "ye", "hanshui"],
        ),
        "ye": Territory(
            id="ye",
            name="邺城",
            owner_id="cao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="north",
            population=120000,
            development=75,
            neighbors=["luoyang", "ji", "puyang", "changshan"],
        ),
        "jiangling": Territory(
            id="jiangling",
            name="江陵",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_river=True,
            population=60000,
            development=50,
            neighbors=["xiangyang", "jiangkou", "nanjun", "jiangzhou"],
        ),
        "jiangkou": Territory(
            id="jiangkou",
            name="江口",
            owner_id="liubiao",
            fertility=5,
            terrain_type=TerrainType.RIVER,
            climate_zone="central",
            has_river=True,
            population=15000,
            development=20,
            neighbors=["xiangyang", "jiangling", "chaisang"],
        ),
        "jianye": Territory(
            id="jianye",
            name="建业",
            owner_id="wu",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            has_river=True,
            has_coast=True,
            population=70000,
            development=55,
            neighbors=["wu", "chaisang", "lujiang", "danyang"],
        ),
        "wu": Territory(
            id="wu",
            name="吴郡",
            owner_id="wu",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            has_coast=True,
            population=50000,
            development=45,
            neighbors=["jianye", "kuaiji"],
        ),
        "kuaiji": Territory(
            id="kuaiji",
            name="会稽",
            owner_id="wu",
            fertility=6,
            terrain_type=TerrainType.COAST,
            climate_zone="south",
            has_coast=True,
            population=40000,
            development=35,
            neighbors=["wu"],
        ),
        "chaisang": Territory(
            id="chaisang",
            name="柴桑",
            owner_id="wu",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            has_river=True,
            population=40000,
            development=40,
            neighbors=["jianye", "jiangkou", "lujiang", "yuzhang"],
        ),
        # New cities for Cao Cao
        "ji": Territory(
            id="ji",
            name="蓟县",
            owner_id="cao",
            fertility=5,
            terrain_type=TerrainType.PLAINS,
            climate_zone="north",
            population=60000,
            development=40,
            neighbors=["ye", "changshan"],
        ),
        "puyang": Territory(
            id="puyang",
            name="濮阳",
            owner_id="cao",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="north",
            population=50000,
            development=45,
            neighbors=["ye", "xuchang", "beihai"],
        ),
        "beihai": Territory(
            id="beihai",
            name="北海",
            owner_id="cao",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="north",
            has_coast=True,
            population=45000,
            development=40,
            neighbors=["puyang", "xiapi"],
        ),
        "xiapi": Territory(
            id="xiapi",
            name="下邳",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_coast=True,
            population=70000,
            development=50,
            neighbors=["beihai", "xuchang", "lujiang"],
        ),
        "changshan": Territory(
            id="changshan",
            name="常山",
            owner_id="cao",
            fertility=5,
            terrain_type=TerrainType.HILLS,
            climate_zone="north",
            population=40000,
            development=30,
            neighbors=["ye", "ji"],
        ),
        # New cities for Wu
        "lujiang": Territory(
            id="lujiang",
            name="庐江",
            owner_id="wu",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            has_river=True,
            population=50000,
            development=40,
            neighbors=["jianye", "chaisang", "danyang", "xiapi"],
        ),
        "yuzhang": Territory(
            id="yuzhang",
            name="豫章",
            owner_id="wu",
            fertility=6,
            terrain_type=TerrainType.HILLS,
            climate_zone="south",
            population=45000,
            development=35,
            neighbors=["chaisang", "changsha"],
        ),
        "danyang": Territory(
            id="danyang",
            name="丹阳",
            owner_id="wu",
            fertility=6,
            terrain_type=TerrainType.HILLS,
            climate_zone="south",
            population=55000,
            development=45,
            neighbors=["jianye", "lujiang"],
        ),
        # New cities for Liubiao
        "changsha": Territory(
            id="changsha",
            name="长沙",
            owner_id="liubiao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            population=50000,
            development=40,
            neighbors=["xiangyang", "yuzhang"],
        ),
        # New cities for Liuzhang
        "chengdu": Territory(
            id="chengdu",
            name="成都",
            owner_id="liuzhang",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            has_river=True,
            population=100000,
            development=60,
            neighbors=["hanshui", "jiangzhou"],
        ),
        "hanshui": Territory(
            id="hanshui",
            name="汉中",
            owner_id="liuzhang",
            fertility=6,
            terrain_type=TerrainType.MOUNTAIN,
            climate_zone="central",
            population=40000,
            development=35,
            neighbors=["chengdu", "luoyang"],
        ),
        "jiangzhou": Territory(
            id="jiangzhou",
            name="江州",
            owner_id="liuzhang",
            fertility=6,
            terrain_type=TerrainType.HILLS,
            climate_zone="south",
            population=45000,
            development=35,
            neighbors=["chengdu", "jiangling", "nanjun"],
        ),
        "nanjun": Territory(
            id="nanjun",
            name="南郡",
            owner_id="liuzhang",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="south",
            population=50000,
            development=45,
            neighbors=["jiangling", "jiangzhou"],
        ),
    }


def load_characters(knowledge_path: str | None = None) -> dict[str, Character]:
    """Load character data from knowledge base."""
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path()

    char_path = os.path.join(knowledge_path, "characters", "207_roster.json")
    if not os.path.isfile(char_path):
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
    """Load a scenario definition from knowledge base."""
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path()

    scenario_dir = os.path.join(knowledge_path, "scenarios")
    if not os.path.isdir(scenario_dir):
        return None

    # Try exact match first
    for fname in os.listdir(scenario_dir):
        if fname.endswith(".json") and scenario_id in fname:
            fpath = os.path.join(scenario_dir, fname)
            with open(fpath) as f:
                return json.load(f)

    return None


def build_world_state(
    player_faction_id: str,
    scenario_id: str = "207",
    knowledge_path: str | None = None,
) -> WorldState:
    """Build a complete WorldState for a new game.

    Args:
        player_faction_id: The faction the player controls ("shu", "cao", "wu")
        scenario_id: Scenario identifier ("207")
        knowledge_path: Path to histrategy-knowledge/

    Returns:
        Fully initialized WorldState ready for engine use.
    """
    if knowledge_path is None:
        knowledge_path = resolve_knowledge_path()

    # Load base territory and character data
    territories = load_territories(knowledge_path)
    characters = load_characters(knowledge_path)

    # Load scenario data for faction configurations
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

    # Determine season
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

    # Build factions
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
        # Fallback to default faction configs
        factions = _default_factions()

    # Assign territory ownership from faction data
    for fid, faction in factions.items():
        for tid in faction.territories:
            if tid in territories:
                territories[tid].owner_id = fid

    # Assign character faction from roster
    for _cid, char in characters.items():
        if char.faction_id and char.faction_id in factions:
            pass  # Already has correct faction_id

    # Create initial armies
    armies: dict[str, Army] = {}
    army_idx = 1
    for fid, faction in factions.items():
        if not faction.is_active or not faction.territories:
            continue
        # Create an army at the capital
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
