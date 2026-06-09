import pytest
import random
from histrategy_engine import (
    Army,
    Character,
    Command,
    DomesticEngine,
    FactionState,
    MapEngine,
    MilitaryEngine,
    Season,
    TerrainType,
    Territory,
    TurnController,
    UnitType,
    WorldState,
)
from histrategy_engine.character import CharacterEngine
from histrategy_engine.ai import DecisionEngine


def test_food_consumption_calculation():
    # Test food consumption calculations with troops and population
    dom_eng = DomesticEngine()
    
    t1 = Territory(id="t1", name="新野", population=30000)
    
    # 1. 0 troops, normal season multiplier (1.0)
    # civilian: 30000 * 0.02 = 600. troop: 0 * 0.5 * 1.0 = 0. total = 600.
    assert dom_eng.calculate_food_consumption(t1, troops=0, supply_multiplier=1.0) == 600

    # 2. 5000 troops, normal season multiplier (1.0)
    # civilian: 600. troop: 5000 * 0.5 * 1.0 = 2500. total = 3100.
    assert dom_eng.calculate_food_consumption(t1, troops=5000, supply_multiplier=1.0) == 3100

    # 3. 5000 troops, winter season multiplier (1.5)
    # civilian: 600. troop: 5000 * 0.5 * 1.5 = 3750. total = 4350.
    assert dom_eng.calculate_food_consumption(t1, troops=5000, supply_multiplier=1.5) == 4350


def test_turn_controller_famine_and_legitimacy():
    # Setup Engines
    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    
    # Setup world state
    t1 = Territory(id="t1", name="新野", owner_id="shu", population=30000, development=25)
    map_eng.load_territories({"t1": t1})
    
    factions = {
        "shu": FactionState(
            id="shu", name="刘备军", ruler_id="liubei",
            capital="t1", territories=["t1"],
            strength_actual=5000, treasury=3000, food=1000, # Not enough to cover winter deficit
            tax_rate=0.2, morale_actual=70, prestige=35, legitimacy=50
        )
    }
    
    armies = {
        "army_shu_1": Army(
            id="army_shu_1", faction_id="shu", location="t1",
            units={UnitType.INFANTRY: 5000}
        )
    }
    
    world = WorldState(
        year=207, season=Season.WINTER, turn_number=1,
        scenario="207", player_faction_id="shu",
        territories={"t1": t1}, characters={}, factions=factions, armies=armies
    )
    
    # Run turn
    # Winter production for xinye = 6 * 1000 * 1.25 * 0.05 (winter) = 375.
    # Winter consumption = 30000 * 0.02 + 5000 * 0.5 * 1.5 = 600 + 3750 = 4350.
    # Delta = 375 - 4350 = -3975.
    # Food is 1000, so food becomes 1000 - 3975 = -2975 -> drops below 0 -> Famine!
    
    result = tc.execute_turn(world, player_commands=[], year=207, turn_number=1)
    
    # Assert famine was triggered
    assert world.factions["shu"].food == 0
    assert world.factions["shu"].morale_actual == 70 - 5
    assert world.factions["shu"].legitimacy == 50 - 10
    # Population lost 5%: 30000 * 0.95 = 28500. Since calculate_population_growth runs, let's verify it is around 28500 (less than 29000).
    assert world.territories["t1"].population < 29000
    assert result.resource_changes["shu"].get("famine_occurred") is True


def test_turn_controller_heavy_tax_legitimacy():
    # Setup Engines
    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    
    t1 = Territory(id="t1", name="新野", owner_id="shu", population=30000, development=25)
    map_eng.load_territories({"t1": t1})
    
    factions = {
        "shu": FactionState(
            id="shu", name="刘备军", ruler_id="liubei",
            capital="t1", territories=["t1"],
            strength_actual=5000, treasury=3000, food=100000, # Plenty of food, no famine
            tax_rate=0.45, # Heavy tax! (rate >= 0.4)
            morale_actual=70, prestige=35, legitimacy=50
        )
    }
    
    world = WorldState(
        year=207, season=Season.SPRING, turn_number=1,
        scenario="207", player_faction_id="shu",
        territories={"t1": t1}, characters={}, factions=factions, armies={}
    )
    
    tc.execute_turn(world, player_commands=[], year=207, turn_number=1)
    
    # Assert legitimacy dropped due to heavy tax (-10)
    assert world.factions["shu"].legitimacy == 40


def test_winter_loyalty_and_defection():
    # Setup Engines
    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    
    t1 = Territory(id="t1", name="新野", owner_id="shu", population=30000, development=25)
    map_eng.load_territories({"t1": t1})
    
    factions = {
        "shu": FactionState(
            id="shu", name="刘备军", ruler_id="liubei",
            capital="t1", territories=["t1"],
            strength_actual=5000, treasury=3000, food=100000,
            tax_rate=0.2, morale_actual=70, prestige=35, legitimacy=10 # Very low legitimacy!
        )
    }
    
    characters = {
        "liubei": Character(id="liubei", name="刘备", faction_id="shu", location="t1", alive=True, birth=161, death=223),
        # Officer with high politics and low loyalty
        "mihe": Character(id="mihe", name="糜芳", faction_id="shu", location="t1", alive=True, politics=85, loyalty=18, birth=165, death=220)
    }
    char_eng.load_characters(characters)
    
    armies = {
        "army_shu_1": Army(id="army_shu_1", faction_id="shu", location="t1", commander_id="mihe", units={UnitType.INFANTRY: 1000})
    }
    
    world = WorldState(
        year=207, season=Season.WINTER, turn_number=1, # WINTER season triggers annual loyalty change
        scenario="207", player_faction_id="shu",
        territories={"t1": t1}, characters=characters, factions=factions, armies=armies
    )
    
    # We want to force a defection in character engine check
    # Let's seed random or monkeypatch random.random to return 0.0 to ensure defection is triggered
    orig_random = random.random
    random.random = lambda: 0.0
    
    try:
        result = tc.execute_turn(world, player_commands=[], year=207, turn_number=1)
    finally:
        random.random = orig_random
        
    # mihe loyalty: starts at 18
    # legitimacy is 10 -> delta = (10-50)/10 = -4. politics is 85 > 80 -> -2. total delta = -6.
    # mihe loyalty becomes 18 - 6 = 12.
    # Since loyalty is 12 < 20 and random.random returned 0.0, defection is triggered!
    assert characters["mihe"].loyalty == 12
    assert characters["mihe"].faction_id == ""
    assert characters["mihe"].is_commanding is False
    # Army commander should be cleared
    assert armies["army_shu_1"].commander_id == ""
    
    # Defection event should be recorded in turn result
    defections = [e for e in result.character_events if e.get("type") == "defection"]
    assert len(defections) > 0
    assert defections[0]["character_id"] == "mihe"
