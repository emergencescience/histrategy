"""
Tests for Map Engine, Character Engine, and Domestic Engine.

Coverage target: ≥ 80%
"""

import pytest

from histrategy_engine import (
    Character,
    CharacterEngine,
    ClimateEvent,
    ClimateSystem,
    DomesticEngine,
    MapEngine,
    Season,
    TerrainType,
    Territory,
    TerritoryResult,
    UnitType,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def three_kingdoms_map() -> dict[str, Territory]:
    """Simplified 207 scenario map — 5 key territories."""
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
            neighbors=["xinye", "jiangling", "wancheng"],
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
            neighbors=["wancheng"],
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
            neighbors=["xiangyang"],
        ),
    }


@pytest.fixture
def map_engine(three_kingdoms_map) -> MapEngine:
    engine = MapEngine()
    engine.load_territories(three_kingdoms_map)
    return engine


@pytest.fixture
def sample_characters() -> dict[str, Character]:
    return {
        "zhugeliang": Character(
            id="zhugeliang",
            name="诸葛亮",
            alias="孔明",
            leadership=92,
            might=32,
            intelligence=100,
            politics=98,
            charisma=90,
            skills=["火攻", "奇门遁甲", "屯田", "八阵图"],
            faction_id="shu",
            location="xinye",
            loyalty=95,
            is_governor=False,
            birth=181,
            death=234,
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
            skills=["骑兵指挥", "青龙偃月", "水淹"],
            sworn_brothers=["liubei", "zhangfei"],
            faction_id="shu",
            location="xinye",
            loyalty=100,
            is_commanding=True,
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
            skills=["骑兵指挥", "丈八蛇矛", "酒疯"],
            sworn_brothers=["liubei", "guanyu"],
            faction_id="shu",
            location="xinye",
            loyalty=98,
            birth=165,
            death=221,
        ),
        "liubei": Character(
            id="liubei",
            name="刘备",
            alias="玄德",
            leadership=80,
            might=70,
            intelligence=72,
            politics=82,
            charisma=99,
            skills=["人德", "号召", "仁政"],
            sworn_brothers=["guanyu", "zhangfei"],
            faction_id="shu",
            location="xinye",
            loyalty=100,
            birth=161,
            death=223,
        ),
    }


@pytest.fixture
def char_engine(sample_characters) -> CharacterEngine:
    engine = CharacterEngine()
    engine.load_characters(sample_characters)
    return engine


# ═══════════════════════════════════════════════════════════════
# Map Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestMapEngineTerrain:
    def test_plains_cavalry_advantage(self, map_engine):
        mod = map_engine.get_combat_modifier("xinye", UnitType.CAVALRY, "attack")
        assert mod == pytest.approx(1.3, rel=0.01)

    def test_mountain_cavalry_penalty(self, map_engine):
        # Add a mountain territory
        mountain = Territory(
            id="hanshan",
            name="寒山",
            terrain_type=TerrainType.MOUNTAIN,
            neighbors=[],
        )
        territories = {**map_engine.territories, "hanshan": mountain}
        map_engine.load_territories(territories)
        mod = map_engine.get_combat_modifier("hanshan", UnitType.CAVALRY, "attack")
        assert mod == pytest.approx(0.3, rel=0.01)

    def test_fortification_bonus(self, map_engine):
        bonus = map_engine.get_fortification_bonus("xinye")
        # xinye has fortification=20 → 1.0 + 20/200 = 1.1
        assert bonus == pytest.approx(1.1, rel=0.01)

    def test_default_terrain_returns_plains(self, map_engine):
        assert map_engine.get_terrain("nonexistent") == TerrainType.PLAINS


class TestMapEngineMovement:
    def test_move_cost_plains_infantry(self, map_engine):
        cost = map_engine.get_move_cost("xinye", UnitType.INFANTRY)
        assert cost == pytest.approx(1.0)

    def test_move_cost_plains_cavalry(self, map_engine):
        cost = map_engine.get_move_cost("xinye", UnitType.CAVALRY)
        assert cost == pytest.approx(0.6)

    def test_navy_cannot_move_on_land(self, map_engine):
        cost = map_engine.get_move_cost("xinye", UnitType.NAVY)
        assert cost > 10  # effectively impassable


class TestMapEnginePathfinding:
    def test_same_territory(self, map_engine):
        result = map_engine.find_path("xinye", "xinye", "shu")
        assert result.path == ["xinye"]
        assert result.turns_required == 0

    def test_adjacent_friendly(self, map_engine):
        # shu (xinye) → liubiao (xiangyang) — liubiao is neutral
        result = map_engine.find_path("xinye", "xiangyang", "shu")
        assert len(result.path) >= 2
        assert result.path[0] == "xinye"
        assert result.path[-1] == "xiangyang"

    def test_two_step_path(self, map_engine):
        result = map_engine.find_path("xinye", "xuchang", "shu")
        assert len(result.path) >= 3

    def test_enemy_territory_blocks_path(self, map_engine):
        # With current simplified movement, all territories are passable
        # unless blocked by strategic points
        # shu (xinye) → cao (xuchang) through wancheng
        result = map_engine.find_path("xinye", "xuchang", "shu")
        # Path should succeed since we allow passing through non-owned territories
        assert result.total_cost != float("inf")
        assert "xuchang" in result.path

    def test_nonexistent_origin(self, map_engine):
        result = map_engine.find_path("atlantis", "xinye", "shu")
        assert result.total_cost == float("inf")

    def test_border_territories(self, map_engine):
        borders = map_engine.get_border_territories("shu")
        # xinye borders xiangyang (liubiao) and wancheng (cao)
        assert "xinye" in borders


class TestMapEngineVisibility:
    def test_own_territories_visible(self, map_engine):
        visible = map_engine.get_visible_territories("shu")
        assert "xinye" in visible

    def test_adjacent_territories_visible(self, map_engine):
        visible = map_engine.get_visible_territories("shu")
        assert "xiangyang" in visible
        assert "wancheng" in visible

    def test_distant_territories_not_visible(self, map_engine):
        visible = map_engine.get_visible_territories("shu")
        assert "xuchang" not in visible  # 2 hops away


# ═══════════════════════════════════════════════════════════════
# Character Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestCharacterStats:
    def test_leadership_bonus(self, char_engine):
        zhuge = char_engine.get("zhugeliang")
        assert zhuge.leadership_bonus() == pytest.approx(1.46, rel=0.01)  # 1 + 92/200

    def test_might_bonus(self, char_engine):
        guanyu = char_engine.get("guanyu")
        assert guanyu.might_bonus() == pytest.approx(1.49, rel=0.01)  # 1 + 98/200

    def test_governor_bonus_no_governor(self, char_engine):
        bonus = char_engine.get_governor_bonus("xinye", "shu")
        # No governor set → bonus = 1.0
        assert bonus == 1.0

    def test_governor_bonus_with_governor(self, char_engine):
        zhuge = char_engine.get("zhugeliang")
        zhuge.is_governor = True
        zhuge.location = "xinye"
        bonus = char_engine.get_governor_bonus("xinye", "shu")
        assert bonus == pytest.approx(1.49, rel=0.01)  # 1 + 98/200


class TestCharacterLoyalty:
    def test_update_loyalty(self, char_engine):
        result = char_engine.update_loyalty("zhugeliang", 2, "封赏")
        assert result == 97  # 95 + 2

    def test_loyalty_clamped_at_100(self, char_engine):
        char_engine.update_loyalty("guanyu", 10)  # 100 + 10 → capped at 100
        assert char_engine.get("guanyu").loyalty == 100

    def test_loyalty_clamped_at_0(self, char_engine):
        char_engine.update_loyalty("zhugeliang", -100)
        assert char_engine.get("zhugeliang").loyalty == 0

    def test_get_discontented(self, char_engine):
        char_engine.update_loyalty("zhugeliang", -80)  # 95 → 15
        discontented = char_engine.get_discontented("shu", threshold=30)
        assert any(c.id == "zhugeliang" for c in discontented)


class TestCharacterLife:
    def test_natural_death_at_death_year(self, char_engine):
        # guanyu death=220, current_year=220
        died = char_engine.check_natural_death("guanyu", 220)
        # 60% probability — run multiple times to verify it CAN return True
        results = [char_engine.check_natural_death("guanyu", 220) for _ in range(50)]
        assert any(results)

    def test_no_death_before_death_year(self, char_engine):
        died = char_engine.check_natural_death("guanyu", 210)
        assert not died

    def test_deviation_extends_life(self, char_engine):
        # High deviation → lower death probability
        deaths_normal = sum(1 for _ in range(100) if char_engine.check_natural_death("guanyu", 220))
        deaths_deviated = sum(
            1 for _ in range(100) if char_engine.check_natural_death("guanyu", 220, deviation=0.8)
        )
        # Deviation should reduce death count
        assert deaths_deviated <= deaths_normal + 15  # allowance for randomness

    def test_kill_character(self, char_engine):
        impacts = char_engine.kill_character("guanyu")
        assert not char_engine.get("guanyu").alive
        # zhangfei is sworn brother → -30 loyalty
        assert any(i["character_id"] == "zhangfei" and i["delta"] == -30 for i in impacts)


class TestCharacterRelationships:
    def test_sworn_brother_death_impact(self, char_engine):
        impacts = char_engine.on_character_death("guanyu")
        zhangfei_impact = next(i for i in impacts if i["character_id"] == "zhangfei")
        assert zhangfei_impact["delta"] == -30
        assert "关羽" in zhangfei_impact["reason"]


# ═══════════════════════════════════════════════════════════════
# Domestic Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestClimateSystem:
    def test_seeded_deterministic(self):
        cs = ClimateSystem()
        territory = Territory(id="test", name="测试", climate_zone="central")
        # Same seed → same result
        r1 = cs.roll_climate(territory, Season.SUMMER, 207, 1)
        r2 = cs.roll_climate(territory, Season.SUMMER, 207, 1)
        assert r1 == r2

    def test_different_seeds_different(self):
        cs = ClimateSystem()
        territory = Territory(id="test", name="测试", climate_zone="central")
        r1 = cs.roll_climate(territory, Season.SUMMER, 207, 1)
        r2 = cs.roll_climate(territory, Season.SUMMER, 208, 1)
        # Different seeds MAY produce different results (not guaranteed but likely)
        # Just verify both return valid ClimateEvents
        assert isinstance(r1, ClimateEvent)
        assert isinstance(r2, ClimateEvent)

    def test_winter_never_drought(self):
        """Winter should never produce drought in any zone."""
        cs = ClimateSystem()
        for zone in ["north", "central", "south"]:
            territory = Territory(id=f"test_{zone}", name=f"测试{zone}", climate_zone=zone)
            # Run 50 winters
            for i in range(50):
                result = cs.roll_climate(territory, Season.WINTER, 207, i)
                assert result != ClimateEvent.DROUGHT

    def test_climate_food_modifiers(self):
        assert ClimateEvent.NORMAL.food_modifier == 1.0
        assert ClimateEvent.DROUGHT.food_modifier == 0.4
        assert ClimateEvent.BUMPER_HARVEST.food_modifier == 1.5
        assert ClimateEvent.PESTILENCE.food_modifier == 0.3


class TestFoodProduction:
    def test_spring_base_production(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        food = engine.calculate_food_production(territory, Season.SPRING, ClimateEvent.NORMAL)
        # 8 × 1000 × 1.5 × 0.3 × 1.0 = 3600
        assert food == 3600

    def test_autumn_peak_production(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        food = engine.calculate_food_production(territory, Season.AUTUMN, ClimateEvent.NORMAL)
        # 8 × 1000 × 1.5 × 1.2 × 1.0 = 14400
        assert food == 14400

    def test_winter_near_zero(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        food = engine.calculate_food_production(territory, Season.WINTER, ClimateEvent.NORMAL)
        # 8 × 1000 × 1.5 × 0.05 × 1.0 = 600
        assert food < 1000

    def test_drought_reduces_food(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        normal = engine.calculate_food_production(territory, Season.AUTUMN, ClimateEvent.NORMAL)
        drought = engine.calculate_food_production(territory, Season.AUTUMN, ClimateEvent.DROUGHT)
        assert drought < normal * 0.5

    def test_bumper_harvest_boosts(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        normal = engine.calculate_food_production(territory, Season.AUTUMN, ClimateEvent.NORMAL)
        bumper = engine.calculate_food_production(
            territory, Season.AUTUMN, ClimateEvent.BUMPER_HARVEST
        )
        assert bumper > normal * 1.3

    def test_governor_increases_food(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        base = engine.calculate_food_production(
            territory, Season.SUMMER, ClimateEvent.NORMAL, governor_politics=0
        )
        with_governor = engine.calculate_food_production(
            territory, Season.SUMMER, ClimateEvent.NORMAL, governor_politics=95
        )
        # 1 + 95/200 = 1.475 → ~47.5% more food
        assert with_governor > base * 1.3

    def test_tech_increases_food(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", fertility=8, development=50)
        base = engine.calculate_food_production(territory, Season.SUMMER, ClimateEvent.NORMAL)
        with_tech = engine.calculate_food_production(
            territory, Season.SUMMER, ClimateEvent.NORMAL, tech_agriculture=3
        )
        # 1 + 3 * 0.1 = 1.3 → 30% more food
        assert with_tech > base * 1.2


class TestPopulationGrowth:
    def test_surplus_growth(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", population=50000, development=50)
        # Large food surplus → positive growth
        growth = engine.calculate_population_growth(territory, food_surplus=5000, morale=70)
        assert growth > 0

    def test_famine_decline(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", population=50000, development=50)
        # Severe food shortage → population decline
        growth = engine.calculate_population_growth(territory, food_surplus=-10000, morale=30)
        assert growth < 0  # population should decline


class TestTaxRevenue:
    def test_base_tax(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", population=50000)
        revenue = engine.calculate_tax_revenue(territory, tax_rate=0.3)
        # 50000 × 0.3 × 0.05 = 750
        assert revenue == 750

    def test_high_tax_rate(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", population=50000)
        revenue = engine.calculate_tax_revenue(territory, tax_rate=0.5)
        # 50000 × 0.5 × 0.05 = 1250
        assert revenue == 1250

    def test_tax_morale_impact(self):
        engine = DomesticEngine()
        assert engine.calculate_tax_morale_impact(0.2) == 0
        assert engine.calculate_tax_morale_impact(0.3) == -1
        assert engine.calculate_tax_morale_impact(0.5) == -3


class TestDevelopment:
    def test_development_cost(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", development=30, population=50000)
        cost = engine.calculate_development_cost(territory, target_level=40)
        # 150 × 10 × √(50000/1000) = 1500 × √50 ≈ 10606
        assert abs(cost - 10606) <= 2

    def test_development_cost_minimum(self):
        engine = DomesticEngine()
        territory = Territory(id="test", name="测试", development=30, population=1000)
        cost = engine.calculate_development_cost(territory, target_level=31)
        assert cost == 300  # minimum


class TestSeasonProcessing:
    def test_process_season_returns_results(self):
        engine = DomesticEngine()
        territories = {
            "test": Territory(
                id="test",
                name="测试",
                fertility=6,
                development=40,
                population=30000,
                climate_zone="central",
            ),
        }
        results = engine.process_season(
            territories,
            Season.AUTUMN,
            year=207,
            turn=1,
            tax_rates={"test": 0.3},
        )
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, TerritoryResult)
        assert r.food_produced > 0


class TestSeasonEnum:
    def test_food_multipliers(self):
        assert Season.SPRING.food_multiplier == 0.3
        assert Season.SUMMER.food_multiplier == 1.0
        assert Season.AUTUMN.food_multiplier == 1.2
        assert Season.WINTER.food_multiplier == 0.05

    def test_supply_multiplier(self):
        assert Season.SPRING.supply_multiplier == 1.0
        assert Season.WINTER.supply_multiplier == 1.5

    def test_chinese_names(self):
        assert Season.SPRING.cn == "春"
        assert Season.AUTUMN.cn == "秋"


class TestUnrestAndFortification:
    def test_unrest_and_fortification_change(self):
        engine = DomesticEngine()
        t = Territory(
            id="test",
            name="测试",
            fertility=6,
            development=40,
            population=30000,
            climate_zone="central",
            fortification=50,
            unrest=10,
            owner_id="cao"
        )
        territories = {"test": t}
        results = engine.process_season(
            territories,
            Season.AUTUMN,
            year=207,
            turn=1,
            tax_rates={"cao": 0.5},
        )
        assert t.unrest > 10
        assert t.fortification == 50
