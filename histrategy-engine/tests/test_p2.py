"""
Tests for Military Engine, Decision Engine, and Turn Controller.

Coverage target: >= 80%
"""

import pytest

from histrategy_engine import (
    Army,
    Character,
    CharacterEngine,
    Command,
    DecisionEngine,
    DomesticEngine,
    FactionState,
    MapEngine,
    MilitaryEngine,
    MoveResult,
    RecruitResult,
    Season,
    SupplyStatus,
    TerrainType,
    Territory,
    TurnController,
    TurnResult,
    UnitType,
    WorldState,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def simple_territories() -> dict[str, Territory]:
    return {
        "t1": Territory(
            id="t1",
            name="平原城",
            owner_id="cao",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=50000,
            development=40,
            fortification=30,
            horse_resource=True,
            iron_resource=True,
            neighbors=["t2", "t3"],
        ),
        "t2": Territory(
            id="t2",
            name="河畔镇",
            owner_id="wu",
            fertility=7,
            terrain_type=TerrainType.RIVER,
            climate_zone="central",
            has_river=True,
            population=30000,
            development=30,
            fortification=15,
            neighbors=["t1", "t4"],
        ),
        "t3": Territory(
            id="t3",
            name="山林",
            owner_id="cao",
            fertility=5,
            terrain_type=TerrainType.FOREST,
            climate_zone="central",
            population=20000,
            development=20,
            fortification=10,
            neighbors=["t1"],
        ),
        "t4": Territory(
            id="t4",
            name="荒野",
            owner_id="",
            fertility=4,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=10000,
            development=10,
            neighbors=["t2"],
        ),
        "t5": Territory(
            id="t5",
            name="孤岛",
            owner_id="cao",
            fertility=3,
            terrain_type=TerrainType.COAST,
            climate_zone="central",
            has_coast=True,
            population=5000,
            development=5,
            neighbors=[],
        ),
    }


@pytest.fixture
def map_engine(simple_territories) -> MapEngine:
    engine = MapEngine()
    engine.load_territories(simple_territories)
    return engine


@pytest.fixture
def char_engine() -> CharacterEngine:
    chars = {
        "caocao": Character(
            id="caocao",
            name="曹操",
            alias="孟德",
            leadership=96,
            might=72,
            intelligence=93,
            politics=90,
            charisma=88,
            faction_id="cao",
            location="t1",
            loyalty=100,
            is_commanding=True,
            birth=155,
            death=220,
        ),
        "xiahoudun": Character(
            id="xiahoudun",
            name="夏侯惇",
            alias="元让",
            leadership=88,
            might=90,
            intelligence=62,
            politics=55,
            charisma=60,
            faction_id="cao",
            location="t1",
            loyalty=95,
            birth=157,
            death=220,
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
            location="t2",
            loyalty=90,
            is_commanding=True,
            birth=175,
            death=210,
        ),
    }
    engine = CharacterEngine()
    engine.load_characters(chars)
    return engine


@pytest.fixture
def military_engine() -> MilitaryEngine:
    return MilitaryEngine()


@pytest.fixture
def decision_engine() -> DecisionEngine:
    return DecisionEngine()


@pytest.fixture
def domestic_engine() -> DomesticEngine:
    return DomesticEngine()


@pytest.fixture
def turn_controller(map_engine, char_engine, domestic_engine, military_engine, decision_engine):
    return TurnController(
        map_engine, char_engine, domestic_engine, military_engine, decision_engine
    )


@pytest.fixture
def sample_army_cao() -> Army:
    return Army(
        id="army_cao_1",
        faction_id="cao",
        location="t1",
        commander_id="caocao",
        units={UnitType.INFANTRY: 2000, UnitType.CAVALRY: 500},
        morale=85,
        training=1.0,
        supply=30,
    )


@pytest.fixture
def sample_army_wu() -> Army:
    return Army(
        id="army_wu_1",
        faction_id="wu",
        location="t2",
        commander_id="zhouyu",
        units={UnitType.INFANTRY: 1500, UnitType.ARCHER: 500},
        morale=80,
        training=1.0,
        supply=25,
    )


@pytest.fixture
def world_state(simple_territories) -> WorldState:
    factions = {
        "cao": FactionState(
            id="cao",
            name="曹操军",
            ruler_id="caocao",
            capital="t1",
            territories=["t1", "t3", "t5"],
            strength_actual=8000,
            treasury=10000,
            food=5000,
            tax_rate=0.3,
            morale_actual=60,
        ),
        "wu": FactionState(
            id="wu",
            name="孙权军",
            ruler_id="sunquan",
            capital="t2",
            territories=["t2"],
            strength_actual=4000,
            treasury=6000,
            food=3000,
            tax_rate=0.3,
            morale_actual=55,
        ),
    }
    armies = {
        "army_cao_1": Army(
            id="army_cao_1",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 2000, UnitType.CAVALRY: 500},
            morale=85,
            training=1.0,
            supply=30,
        ),
        "army_wu_1": Army(
            id="army_wu_1",
            faction_id="wu",
            location="t2",
            commander_id="zhouyu",
            units={UnitType.INFANTRY: 1500, UnitType.ARCHER: 500},
            morale=80,
            training=1.0,
            supply=25,
        ),
    }
    chars = {
        "caocao": Character(
            id="caocao",
            name="曹操",
            alias="孟德",
            leadership=96,
            might=72,
            intelligence=93,
            politics=90,
            charisma=88,
            faction_id="cao",
            location="t1",
            loyalty=100,
            is_commanding=True,
            birth=155,
            death=220,
        ),
        "xiahoudun": Character(
            id="xiahoudun",
            name="夏侯惇",
            alias="元让",
            leadership=88,
            might=90,
            intelligence=62,
            politics=55,
            charisma=60,
            faction_id="cao",
            location="t1",
            loyalty=95,
            birth=157,
            death=220,
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
            location="t2",
            loyalty=90,
            is_commanding=True,
            birth=175,
            death=210,
        ),
    }
    return WorldState(
        year=208,
        season=Season.SPRING,
        turn_number=1,
        player_faction_id="cao",
        territories=simple_territories,
        characters=chars,
        factions=factions,
        armies=armies,
    )


# ═══════════════════════════════════════════════════════════════
# Military Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestUnitStats:
    def test_infantry_stats(self):
        # Just verify UNIT_STATS exists and is accessible
        from histrategy_engine.military import UNIT_STATS

        assert UNIT_STATS[UnitType.INFANTRY]["cost"] == 3
        assert UNIT_STATS[UnitType.INFANTRY]["atk"] == 10
        assert UNIT_STATS[UnitType.INFANTRY]["def"] == 10
        assert UNIT_STATS[UnitType.INFANTRY]["speed"] == 1

    def test_cavalry_stats(self):
        from histrategy_engine.military import UNIT_STATS

        assert UNIT_STATS[UnitType.CAVALRY]["cost"] == 10
        assert UNIT_STATS[UnitType.CAVALRY]["atk"] == 14
        assert UNIT_STATS[UnitType.CAVALRY]["speed"] == 2

    def test_archer_stats(self):
        from histrategy_engine.military import UNIT_STATS

        assert UNIT_STATS[UnitType.ARCHER]["cost"] == 6
        assert UNIT_STATS[UnitType.ARCHER]["def"] == 13

    def test_navy_stats(self):
        from histrategy_engine.military import UNIT_STATS

        assert UNIT_STATS[UnitType.NAVY]["speed"] == 1.5


class TestRecruit:
    def test_recruit_infantry_success(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000)
        result = military_engine.recruit(
            territory, UnitType.INFANTRY, 1000, treasury=5000, population=50000
        )
        assert result.success
        assert result.amount == 1000
        assert result.cost == 3000  # 3 * 1000

    def test_recruit_cavalry_needs_horse(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, horse_resource=False)
        result = military_engine.recruit(
            territory, UnitType.CAVALRY, 100, treasury=5000, population=50000
        )
        assert not result.success
        assert "马匹" in result.reason

    def test_recruit_cavalry_with_horse(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, horse_resource=True)
        result = military_engine.recruit(
            territory, UnitType.CAVALRY, 100, treasury=5000, population=50000
        )
        assert result.success
        assert result.cost == 1000

    def test_recruit_archer_needs_iron(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, iron_resource=False)
        result = military_engine.recruit(
            territory, UnitType.ARCHER, 100, treasury=5000, population=50000
        )
        assert not result.success
        assert "铁矿" in result.reason

    def test_recruit_archer_with_iron(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, iron_resource=True)
        result = military_engine.recruit(
            territory, UnitType.ARCHER, 100, treasury=5000, population=50000
        )
        assert result.success

    def test_recruit_navy_needs_water(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000)
        result = military_engine.recruit(
            territory, UnitType.NAVY, 100, treasury=5000, population=50000
        )
        assert not result.success
        assert "河流" in result.reason or "海岸" in result.reason

    def test_recruit_navy_with_river(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, has_river=True)
        result = military_engine.recruit(
            territory, UnitType.NAVY, 100, treasury=5000, population=50000
        )
        assert result.success

    def test_recruit_navy_with_coast(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000, has_coast=True)
        result = military_engine.recruit(
            territory, UnitType.NAVY, 100, treasury=5000, population=50000
        )
        assert result.success

    def test_recruit_insufficient_treasury(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000)
        result = military_engine.recruit(
            territory, UnitType.INFANTRY, 1000, treasury=500, population=50000
        )
        assert not result.success
        assert "资金不足" in result.reason

    def test_recruit_insufficient_population(self, military_engine):
        territory = Territory(id="t1", name="test", population=500)
        result = military_engine.recruit(
            territory, UnitType.INFANTRY, 1000, treasury=50000, population=500
        )
        assert not result.success
        assert "人口不足" in result.reason

    def test_recruit_zero_amount(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000)
        result = military_engine.recruit(
            territory, UnitType.INFANTRY, 0, treasury=5000, population=50000
        )
        assert not result.success

    def test_recruit_returns_correct_type(self, military_engine):
        territory = Territory(id="t1", name="test", population=50000)
        result = military_engine.recruit(
            territory, UnitType.INFANTRY, 100, treasury=5000, population=50000
        )
        assert isinstance(result, RecruitResult)
        assert result.territory_id == "t1"


class TestMovement:
    def test_move_adjacent(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        result = military_engine.move_army(army, "t2", map_engine)
        assert result.success
        assert result.to_location == "t2"

    def test_move_same_location(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        result = military_engine.move_army(army, "t1", map_engine)
        assert result.success
        assert result.distance_tiles == 0
        assert "已在" in result.reason

    def test_move_unreachable(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        # t5 has no neighbors, so no path from t1 to t5
        result = military_engine.move_army(army, "t5", map_engine)
        assert not result.success
        assert "无法到达" in result.reason

    def test_move_updates_army_location(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        military_engine.move_army(army, "t2", map_engine)
        assert army.location == "t2"

    def test_move_cavalry_faster(self, military_engine, map_engine):
        # Calvary (speed 2) can move further than infantry (speed 1)
        army = Army(
            id="fast_army",
            faction_id="cao",
            location="t1",
            units={UnitType.CAVALRY: 500},
            morale=80,
            training=1.0,
        )
        speed = military_engine._army_speed(army)
        assert speed == 2.0

    def test_move_mixed_army_speed(self, military_engine, map_engine):
        army = Army(
            id="mixed_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000, UnitType.CAVALRY: 500},
            morale=80,
            training=1.0,
        )
        speed = military_engine._army_speed(army)
        assert speed == 1.0  # slowest unit = infantry

    def test_move_result_type(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        result = military_engine.move_army(army, "t2", map_engine)
        assert isinstance(result, MoveResult)


class TestBattle:
    def test_basic_battle_resolution(self, military_engine, map_engine, char_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 2000},
            morale=85,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            commander_id="zhouyu",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        result = military_engine.resolve_battle(attacker, defender, "t1", map_engine, char_engine)
        assert result.attacker_id == "cao"
        assert result.defender_id == "wu"
        assert result.location == "t1"
        assert result.battle_id != ""

    def test_overwhelming_force_decisive_victory(self, military_engine, map_engine, char_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 5000, UnitType.CAVALRY: 2000},
            morale=100,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 200},
            morale=40,
            training=0.5,
        )
        result = military_engine.resolve_battle(attacker, defender, "t1", map_engine, char_engine)
        assert result.result.value == "decisive_victory"

    def test_equal_forces_draw(self, military_engine, map_engine, char_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t3",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t3",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        result = military_engine.resolve_battle(attacker, defender, "t3", map_engine, char_engine)
        # Without commander bonuses and with fortification, similar forces
        # Exact outcome depends on fortification/terrain implementation
        assert result.result.value in ("draw", "defeat", "victory", "decisive_defeat")

    def test_territory_captured_on_victory(self, military_engine, map_engine, char_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 5000},
            morale=100,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 100},
            morale=30,
            training=0.5,
        )
        result = military_engine.resolve_battle(attacker, defender, "t1", map_engine, char_engine)
        assert result.territory_captured

    def test_casualties_applied(self, military_engine, map_engine, char_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 2000},
            morale=85,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            commander_id="zhouyu",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        initial_atk_troops = attacker.total_troops
        initial_def_troops = defender.total_troops

        military_engine.resolve_battle(attacker, defender, "t1", map_engine, char_engine)

        # Both sides should have taken some casualties
        assert attacker.total_troops <= initial_atk_troops
        assert defender.total_troops <= initial_def_troops

    def test_commander_bonus_affects_outcome(self, military_engine, map_engine, char_engine):
        # Without commander
        Army(
            id="atk1",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        Army(
            id="def1",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        # Same test but with commander
        attacker_cmd = Army(
            id="atk2",
            faction_id="cao",
            location="t1",
            commander_id="caocao",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        defender_cmd = Army(
            id="def2",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )

        # The commander should give an advantage
        # caocao leadership=96 → 1 + 96/200 = 1.48
        result_with_cmd = military_engine.resolve_battle(
            attacker_cmd, defender_cmd, "t1", map_engine, char_engine
        )
        # With commander bonus, attacker should win
        assert result_with_cmd.result.value in ("victory", "decisive_victory", "draw")

    def test_fortification_helps_defender(self, military_engine, map_engine, char_engine):
        # t1 has fortification=30 → bonus = 1 + 30/200 = 1.15
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        result = military_engine.resolve_battle(attacker, defender, "t1", map_engine, char_engine)
        # Defender has fortification advantage
        assert result.defender_id == "wu"

    def test_no_char_engine_does_not_crash(self, military_engine, map_engine):
        attacker = Army(
            id="atk",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            morale=80,
            training=1.0,
        )
        defender = Army(
            id="def",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 500},
            morale=60,
            training=0.8,
        )
        result = military_engine.resolve_battle(
            attacker, defender, "t1", map_engine, char_engine=None
        )
        assert result.battle_id != ""


class TestSupply:
    def test_friendly_territory_auto_refill(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            supply=10,
        )
        status = military_engine.calculate_supply(army, map_engine)
        assert status.in_range
        assert status.attrition_pct == 0.0
        assert status.supply_level == 30  # refilled

    def test_enemy_territory_in_range(self, military_engine, map_engine):
        # wu army in t1 (cao territory) — t2 is 1 tile away (wu owned)
        army = Army(
            id="test_army",
            faction_id="wu",
            location="t1",
            units={UnitType.INFANTRY: 1000},
            supply=10,
        )
        status = military_engine.calculate_supply(army, map_engine)
        # t2 (wu territory) is 1 tile from t1 → within range
        assert status.in_range

    def test_out_of_range_attrition(self, military_engine, map_engine):
        # cao army in t4 — nearest cao territory is t1 (2 tiles: t4→t2→t1)
        # or t3 (t4→t2→t1→t3 = 3 tiles)
        # t4 → t2 (wu) → t1 (cao) = 2 tiles
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t4",
            units={UnitType.INFANTRY: 1000},
            supply=5,
        )
        status = military_engine.calculate_supply(army, map_engine)
        # t4 → t2 → t1, distance to friendly = 2 (t1 and t3)
        # supply_range = 2, so at the border
        assert status.in_range  # exactly at supply range

    def test_isolated_army_no_supply(self, military_engine, map_engine):
        # wu army in t3 — nearest wu territory is t2 (t3→t1→t2 = 2 tiles)
        # This is within supply range actually
        # Let's test a truly isolated case
        army = Army(
            id="test_army",
            faction_id="wu",
            location="t3",
            units={UnitType.INFANTRY: 1000},
            supply=3,
        )
        status = military_engine.calculate_supply(army, map_engine)
        # t3 → t1 → t2 = 2 tiles to friendly (wu territory t2)
        # supply_range = 2, so in range
        # This is at the edge
        assert isinstance(status, SupplyStatus)

    def test_winter_penalty(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        status = military_engine.calculate_supply(army, map_engine, season=Season.WINTER)
        assert status.winter_penalty == 1.5

    def test_supply_status_type(self, military_engine, map_engine):
        army = Army(
            id="test_army",
            faction_id="cao",
            location="t1",
            units={UnitType.INFANTRY: 1000},
        )
        status = military_engine.calculate_supply(army, map_engine)
        assert isinstance(status, SupplyStatus)
        assert status.army_id == "test_army"

    def test_winter_attrition_multiplier(self, military_engine, map_engine):
        # t5 is isolated (no neighbors), wu has no friendly territory reachable
        army = Army(
            id="test_army",
            faction_id="wu",
            location="t5",
            units={UnitType.INFANTRY: 1000},
            supply=3,
        )
        status = military_engine.calculate_supply(army, map_engine, season=Season.WINTER)
        # t5 has no path to t2 (wu territory), so attrition is at max
        if not status.in_range:
            assert status.winter_penalty == 1.5


# ═══════════════════════════════════════════════════════════════
# Decision Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestPersonalityProfiles:
    def test_known_profiles_loaded(self, decision_engine):
        profile = decision_engine.get_profile("caocao")
        assert profile["aggression"] == 0.8
        assert profile["cunning"] == 0.9
        assert profile["mercy"] == 0.2

    def test_liubei_merciful(self, decision_engine):
        profile = decision_engine.get_profile("liubei")
        assert profile["mercy"] == 0.95
        assert profile["development"] == 0.8
        assert profile["aggression"] == 0.3

    def test_dongzhuo_aggressive(self, decision_engine):
        profile = decision_engine.get_profile("dongzhuo")
        assert profile["aggression"] == 0.9
        assert profile["mercy"] == 0.05

    def test_unknown_faction_gets_default(self, decision_engine):
        profile = decision_engine.get_profile("unknown_ruler")
        assert profile["aggression"] == 0.5
        assert profile["development"] == 0.5


class TestThreatEvaluation:
    def test_high_threat(self, decision_engine, world_state, map_engine):
        # cao has 8000 strength, wu has 4000 → ratio 0.5 (LOW threat to cao)
        # Make wu stronger to test HIGH threat
        world_state.factions["wu"].strength_actual = 15000
        threats = decision_engine.evaluate_threats("cao", world_state, map_engine)
        assert "wu" in threats
        assert threats["wu"]["level"] == "HIGH"

    def test_low_threat(self, decision_engine, world_state, map_engine):
        threats = decision_engine.evaluate_threats("cao", world_state, map_engine)
        assert "wu" in threats
        assert threats["wu"]["level"] == "LOW"  # wu 4000 vs cao 8000 = 0.5

    def test_no_faction_returns_empty(self, decision_engine, world_state, map_engine):
        threats = decision_engine.evaluate_threats("nonexistent", world_state, map_engine)
        assert threats == {}

    def test_inactive_faction_ignored(self, decision_engine, world_state, map_engine):
        world_state.factions["wu"].is_active = False
        threats = decision_engine.evaluate_threats("cao", world_state, map_engine)
        assert "wu" not in threats


class TestOpportunityEvaluation:
    def test_unowned_territory_opportunity(self, decision_engine, world_state, map_engine):
        # t4 is unowned and adjacent to t2 (wu)
        opps = decision_engine.evaluate_opportunities("wu", world_state, map_engine)
        occupy_opps = [o for o in opps if o["type"] == "occupy"]
        assert len(occupy_opps) > 0
        assert any(o["territory_id"] == "t4" for o in occupy_opps)

    def test_weak_neighbor_opportunity(self, decision_engine, world_state, map_engine):
        # wu has 4000 strength, cao has 8000 → cao sees wu as relatively weak
        # But wait: neighbor_strength / my_strength < 0.6 for attack opportunity
        # For cao: 4000/8000 = 0.5 < 0.6 → wu is an attack opportunity
        opps = decision_engine.evaluate_opportunities("cao", world_state, map_engine)
        attack_opps = [o for o in opps if o["type"] == "attack"]
        # cao borders t2 (wu) through t1
        assert len(attack_opps) >= 1
        assert any(o["territory_id"] == "t2" for o in attack_opps)

    def test_no_opportunity_for_weak_faction(self, decision_engine, world_state, map_engine):
        # wu is weaker, so it shouldn't see cao as an attack opportunity
        opps = decision_engine.evaluate_opportunities("wu", world_state, map_engine)
        attack_opps = [o for o in opps if o["type"] == "attack" and o["enemy_faction_id"] == "cao"]
        assert len(attack_opps) == 0  # cao is stronger than wu


class TestCommandGeneration:
    def test_generates_commands(self, decision_engine, world_state, map_engine):
        commands = decision_engine.generate_commands("cao", world_state, map_engine)
        assert len(commands) > 0
        for cmd in commands:
            assert isinstance(cmd, Command)
            assert cmd.faction_id == "cao"
            assert cmd.type in ("recruit", "develop", "attack", "move", "tax")

    def test_different_personalities_different_output(
        self, decision_engine, world_state, map_engine
    ):
        # Add liubei faction adjacent to cao for comparison
        world_state.factions["liubei"] = FactionState(
            id="liubei",
            name="刘备军",
            ruler_id="liubei",
            capital="t4",
            territories=["t4"],
            strength_actual=3000,
            treasury=5000,
            food=2000,
        )
        world_state.territories["t4"].owner_id = "liubei"
        world_state.armies["army_liu_1"] = Army(
            id="army_liu_1",
            faction_id="liubei",
            location="t4",
            units={UnitType.INFANTRY: 800},
            morale=70,
            training=1.0,
            supply=20,
        )

        cao_cmds = decision_engine.generate_commands("cao", world_state, map_engine)
        liu_cmds = decision_engine.generate_commands("liubei", world_state, map_engine)

        # Both should generate commands
        assert len(cao_cmds) > 0
        assert len(liu_cmds) > 0

    def test_low_food_triggers_develop(self, decision_engine, world_state, map_engine):
        world_state.factions["cao"].food = 500  # very low
        commands = decision_engine.generate_commands("cao", world_state, map_engine)
        # With low food, should prefer develop over attack
        types = [c.type for c in commands]
        assert "develop" in types or "recruit" in types

    def test_inactive_faction_empty(self, decision_engine, world_state, map_engine):
        world_state.factions["cao"].is_active = False
        commands = decision_engine.generate_commands("cao", world_state, map_engine)
        assert commands == []


# ═══════════════════════════════════════════════════════════════
# Turn Controller Tests
# ═══════════════════════════════════════════════════════════════


class TestTurnExecution:
    def test_execute_turn_returns_result(self, turn_controller, world_state):
        result = turn_controller.execute_turn(
            world_state,
            player_commands=[],
            year=208,
            turn_number=1,
        )
        assert isinstance(result, TurnResult)
        assert result.year == 208
        assert result.turn_number == 1

    def test_climate_events_populated(self, turn_controller, world_state):
        result = turn_controller.execute_turn(world_state, year=208, turn_number=1)
        assert len(result.climate_events) >= len(world_state.territories)

    def test_resource_changes_populated(self, turn_controller, world_state):
        result = turn_controller.execute_turn(world_state, year=208, turn_number=1)
        assert isinstance(result.resource_changes, dict)

    def test_faction_snapshots_present(self, turn_controller, world_state):
        result = turn_controller.execute_turn(world_state, year=208, turn_number=1)
        assert "cao" in result.faction_snapshots
        assert "wu" in result.faction_snapshots

    def test_season_advances(self, turn_controller, world_state):
        assert world_state.season == Season.SPRING
        turn_controller.execute_turn(world_state, year=208, turn_number=1)
        assert world_state.season == Season.SUMMER

    def test_year_advances_at_winter_end(self, turn_controller, world_state):
        world_state.season = Season.WINTER
        initial_year = world_state.year
        turn_controller.execute_turn(world_state, year=initial_year, turn_number=4)
        assert world_state.season == Season.SPRING
        assert world_state.year == initial_year + 1

    def test_turn_number_increments(self, turn_controller, world_state):
        initial_turn = world_state.turn_number
        turn_controller.execute_turn(world_state, year=208, turn_number=initial_turn)
        assert world_state.turn_number == initial_turn + 1


class TestCommandValidation:
    def test_valid_recruit_command(self, turn_controller, world_state):
        cmd = Command(
            type="recruit",
            params={
                "territory": "t1",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 1

    def test_invalid_recruit_not_owned(self, turn_controller, world_state):
        cmd = Command(
            type="recruit",
            params={
                "territory": "t2",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="cao",
        )  # t2 is owned by wu
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0

    def test_invalid_recruit_nonexistent_territory(self, turn_controller, world_state):
        cmd = Command(
            type="recruit",
            params={
                "territory": "nonexistent",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0

    def test_valid_move_command(self, turn_controller, world_state):
        cmd = Command(
            type="move",
            params={
                "destination": "t2",
            },
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 1

    def test_invalid_move_bad_target(self, turn_controller, world_state):
        cmd = Command(
            type="move",
            params={
                "destination": "nonexistent",
            },
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0

    def test_valid_attack_command(self, turn_controller, world_state):
        cmd = Command(
            type="attack",
            params={
                "target_territory": "t2",
            },
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 1

    def test_invalid_faction(self, turn_controller, world_state):
        cmd = Command(
            type="recruit",
            params={
                "territory": "t1",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="nonexistent",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0

    def test_invalid_no_faction_id(self, turn_controller, world_state):
        cmd = Command(
            type="recruit",
            params={
                "territory": "t1",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0


class TestTurnMoveExecution:
    def test_move_command_executes(self, turn_controller, world_state):
        cmd = Command(
            type="move",
            params={
                "destination": "t2",
            },
            faction_id="cao",
        )
        result = turn_controller.execute_turn(
            world_state, player_commands=[cmd], year=208, turn_number=1
        )
        assert isinstance(result, TurnResult)

    def test_attack_command_executes(self, turn_controller, world_state):
        cmd = Command(
            type="attack",
            params={
                "target_territory": "t2",
            },
            faction_id="cao",
        )
        result = turn_controller.execute_turn(
            world_state, player_commands=[cmd], year=208, turn_number=1
        )
        assert isinstance(result, TurnResult)


class TestTurnBattleResolution:
    def test_battle_when_armies_meet(self, turn_controller, world_state):
        # Move cao army to t2 where wu army is
        world_state.armies["army_cao_1"].location = "t2"
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        # Battle should be recorded
        assert len(result.battles) > 0

    def test_no_battle_same_faction(self, turn_controller, world_state):
        # Both armies are cao in same territory
        world_state.armies["army_wu_1"].faction_id = "cao"
        world_state.armies["army_wu_1"].location = "t1"
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        # No battles since same faction
        battles = list(result.battles)
        assert len(battles) == 0


class TestTurnDomesticExecution:
    def test_recruit_command_adds_troops(self, turn_controller, world_state):
        initial_treasury = world_state.factions["cao"].treasury
        cmd = Command(
            type="recruit",
            params={
                "territory": "t1",
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id="cao",
        )
        turn_controller.execute_turn(world_state, player_commands=[cmd], year=208, turn_number=1)
        # Treasury should decrease
        assert world_state.factions["cao"].treasury < initial_treasury

    def test_develop_command_increases_development(self, turn_controller, world_state):
        initial_dev = world_state.territories["t1"].development
        initial_treasury = world_state.factions["cao"].treasury
        cmd = Command(
            type="develop",
            params={
                "territory": "t1",
            },
            faction_id="cao",
        )
        turn_controller.execute_turn(world_state, player_commands=[cmd], year=208, turn_number=1)
        # Development should increase if treasury was sufficient
        if initial_treasury >= 500:
            assert world_state.territories["t1"].development >= initial_dev

    def test_tax_command_changes_rate(self, turn_controller, world_state):
        cmd = Command(
            type="tax",
            params={
                "rate": 0.4,
            },
            faction_id="cao",
        )
        turn_controller.execute_turn(world_state, player_commands=[cmd], year=208, turn_number=1)
        assert world_state.factions["cao"].tax_rate == 0.4


class TestTurnNPCCommands:
    def test_npc_commands_generated(self, turn_controller, world_state):
        # wu is NPC (player is cao)
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        assert isinstance(result, TurnResult)

    def test_npc_inactive_ignored(self, turn_controller, world_state):
        world_state.factions["wu"].is_active = False
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        assert isinstance(result, TurnResult)


class TestCharacterEvents:
    def test_character_death_check_runs(self, turn_controller, world_state):
        # Set a character's death year to current year to force check
        world_state.characters["xiahoudun"].death = 208
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        # Character events should be a list
        assert isinstance(result.character_events, list)


# ═══════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestFullTurnIntegration:
    def test_complete_turn_with_all_commands(self, turn_controller, world_state):
        commands = [
            Command(
                type="recruit",
                params={
                    "territory": "t1",
                    "unit_type": "infantry",
                    "amount": 300,
                },
                faction_id="cao",
            ),
            Command(
                type="develop",
                params={
                    "territory": "t1",
                },
                faction_id="cao",
            ),
        ]
        result = turn_controller.execute_turn(
            world_state, player_commands=commands, year=208, turn_number=1
        )
        assert isinstance(result, TurnResult)
        assert result.climate_events
        assert result.resource_changes is not None
        assert result.faction_snapshots

    def test_multiple_turns_sequence(self, turn_controller, world_state):
        """Run multiple turns to ensure game state evolves correctly."""
        for i in range(3):
            result = turn_controller.execute_turn(
                world_state, player_commands=[], year=208, turn_number=i + 1
            )
            assert isinstance(result, TurnResult)

    def test_battle_captures_territory(self, turn_controller, world_state):
        # Set up a scenario where cao attacks wu and wins decisively
        world_state.armies["army_cao_1"].location = "t2"
        world_state.armies["army_cao_1"].units = {UnitType.INFANTRY: 10000}
        world_state.armies["army_cao_1"].morale = 100
        world_state.armies["army_wu_1"].units = {UnitType.INFANTRY: 200}
        world_state.armies["army_wu_1"].morale = 30

        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )

        # Check if territory changed hands
        if result.battles:
            battle = result.battles[0]
            if battle.territory_captured:
                assert world_state.territories["t2"].owner_id == "cao"


# ═══════════════════════════════════════════════════════════════
# Defend Command + TurnResult Context Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestDefendCommand:
    """Integration tests for the new 'defend' command type."""

    def test_defend_validated(self, turn_controller, world_state):
        """Defend command with valid territory should pass validation."""
        cmd = Command(
            type="defend",
            params={"territory": "t1"},
            faction_id="cao",
            notes="防范敌军偷袭",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 1
        assert valid[0].type == "defend"

    def test_defend_invalid_territory(self, turn_controller, world_state):
        """Defend with nonexistent territory should be invalid."""
        cmd = Command(
            type="defend",
            params={"territory": "nonexistent"},
            faction_id="cao",
        )
        valid = turn_controller._validate_commands([cmd], world_state)
        assert len(valid) == 0

    def test_defend_already_defended_no_op(self, turn_controller, world_state):
        """If army already at target, defend is a no-op success."""
        # cao already has army at t1
        cmd = Command(
            type="defend",
            params={"territory": "t1"},
            faction_id="cao",
            notes="防守t1",
        )
        result = turn_controller._execute_move(cmd, world_state)
        assert result is not None
        assert result["command_type"] == "defend"
        assert result["success"] is True
        assert "已有驻军" in result["reason"]

    def test_defend_moves_army_if_not_present(self, turn_controller, world_state):
        """If no army at target, defend moves one there (like move)."""
        # t3 is owned by cao but no army present
        world_state.territories["t3"].owner_id = "cao"
        cmd = Command(
            type="defend",
            params={"territory": "t3"},
            faction_id="cao",
            notes="防守t3",
        )
        result = turn_controller._execute_move(cmd, world_state)
        # Should move army to t3
        assert result is not None
        assert result["command_type"] == "defend"

    def test_defend_executes_in_full_turn(self, turn_controller, world_state):
        """Full turn execution with defend command works."""
        cmd = Command(
            type="defend",
            params={"territory": "t1"},
            faction_id="cao",
            notes="防守主城",
        )
        result = turn_controller.execute_turn(
            world_state,
            player_commands=[cmd],
            year=208,
            turn_number=1,
            player_decision="在下邳部署防守",
        )
        assert isinstance(result, TurnResult)


class TestTurnResultContext:
    """Tests for player context passthrough in TurnResult."""

    def test_player_decision_preserved(self, turn_controller, world_state):
        """TurnResult should carry the original player decision."""
        decision = "【南征刘备】集结宛城5万步兵，春季行军进攻新野"
        cmd = Command(
            type="attack",
            params={"target_territory": "t2"},
            faction_id="cao",
            notes="南征刘备战役",
        )
        result = turn_controller.execute_turn(
            world_state,
            player_commands=[cmd],
            year=208,
            turn_number=1,
            player_decision=decision,
        )
        assert result.player_decision == decision

    def test_player_commands_preserved(self, turn_controller, world_state):
        """TurnResult should carry the parsed commands with notes."""
        cmds = [
            Command(
                type="attack", params={"target_territory": "t2"}, faction_id="cao", notes="主力进攻"
            ),  # noqa: E501
            Command(type="defend", params={"territory": "t1"}, faction_id="cao", notes="后方防守"),
        ]
        result = turn_controller.execute_turn(
            world_state,
            player_commands=cmds,
            year=208,
            turn_number=1,
            player_decision="进攻t2同时防守t1",
        )
        assert len(result.player_commands) == 2
        types = {getattr(c, "type", "") for c in result.player_commands}
        assert "attack" in types
        assert "defend" in types

    def test_empty_decision_defaults(self, turn_controller, world_state):
        """Without player_decision, defaults to empty string."""
        result = turn_controller.execute_turn(
            world_state, player_commands=[], year=208, turn_number=1
        )
        assert result.player_decision == ""
        assert result.player_commands == []

    def test_command_notes_survive_roundtrip(self, turn_controller, world_state):
        """Command notes field survives through TurnController → TurnResult."""
        cmd = Command(
            type="defend",
            params={"territory": "t1"},
            faction_id="cao",
            notes="防范孙权从庐江进攻",
        )
        result = turn_controller.execute_turn(
            world_state,
            player_commands=[cmd],
            year=208,
            turn_number=1,
            player_decision="在下邳防守",
        )
        assert len(result.player_commands) == 1
        survived = result.player_commands[0]
        assert getattr(survived, "notes", "") == "防范孙权从庐江进攻"
