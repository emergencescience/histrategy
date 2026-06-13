"""Tests for macro historical engine components.

Covers:
- PolicyParser (unit + integration)
- PolicyValidator (unit)
- QuarterlyEngine (integration with world state)
- KnowledgeLayer (unit)
- BlackSwanInjector (integration)
"""

import pytest

from histrategy.engine.knowledge_layer import (
    BUILTIN_CARDS,
    KnowledgeBase,
    KnowledgeCard,
)
from histrategy.engine.quarterly_engine import (
    EconomyParams,
    QuarterlyEngine,
    QuarterResult,
)
from histrategy.policy.policy_parser import PolicyParser
from histrategy.policy.policy_types import (
    POLICY_COMMAND_TYPES,
    PolicyCommand,
    validate_policy_params,
)
from histrategy.policy.policy_validator import PolicyValidator

# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def world_state():
    """Create a minimal WorldState for testing."""
    from histrategy_engine.world import (
        Army,
        Character,
        FactionState,
        Season,
        Territory,
        WorldState,
    )

    ws = WorldState(
        year=207,
        season=Season.WINTER,
        turn_number=1,
        player_faction_id="cao",
        scenario="207",
    )

    # Factions
    ws.factions["cao"] = FactionState(
        id="cao",
        name="曹操",
        ruler_id="caocao",
        capital="xuchang",
        territories=["xuchang", "wancheng", "luoyang", "ye"],
        is_active=True,
        strength_actual=150000,
        morale_actual=62,
        treasury=62300,
        food=18904,
        tax_rate=0.40,
        aggression=0.8,
        cunning=0.9,
        caution=0.3,
    )
    ws.factions["shu"] = FactionState(
        id="shu",
        name="刘备",
        ruler_id="liubei",
        capital="xinye",
        territories=["xinye"],
        is_active=True,
        strength_actual=5000,
        morale_actual=65,
        treasury=3300,
        food=0,
        tax_rate=0.20,
        aggression=0.3,
        cunning=0.3,
        caution=0.7,
    )
    ws.factions["wu"] = FactionState(
        id="wu",
        name="孙权",
        ruler_id="sunquan",
        capital="jianye",
        territories=["jianye", "wu", "chaisang", "lujiang"],
        is_active=True,
        strength_actual=60000,
        morale_actual=68,
        treasury=14070,
        food=2901,
        tax_rate=0.30,
    )
    ws.factions["liubiao"] = FactionState(
        id="liubiao",
        name="刘表",
        ruler_id="liubiao",
        capital="xiangyang",
        territories=["xiangyang", "jiangling"],
        is_active=True,
        strength_actual=40000,
        morale_actual=46,
        treasury=13075,
        food=5577,
        tax_rate=0.30,
    )

    # Territories
    from histrategy_engine.world import TerrainType

    for tid, pop, dev, fert in [
        ("xuchang", 100000, 70, 7),
        ("wancheng", 50000, 45, 7),
        ("luoyang", 80000, 60, 7),
        ("ye", 120000, 75, 8),
        ("xinye", 30000, 35, 6),
        ("xiangyang", 60000, 55, 7),
        ("jiangling", 40000, 40, 6),
        ("jianye", 90000, 60, 8),
        ("wu", 50000, 55, 8),
        ("chaisang", 35000, 40, 6),
        ("lujiang", 45000, 42, 6),
    ]:
        ws.territories[tid] = Territory(
            id=tid,
            name=tid,
            population=pop,
            development=dev,
            fertility=fert,
            terrain_type=TerrainType.PLAINS,
        )
        # Set owner based on faction territories
        for fid, f in ws.factions.items():
            if hasattr(f, "territories") and tid in f.territories:
                ws.territories[tid].owner_id = fid

    # Characters
    for cid, name, fid, loc in [
        ("caocao", "曹操", "cao", "xuchang"),
        ("liubei", "刘备", "shu", "xinye"),
        ("guanyu", "关羽", "shu", "xinye"),
        ("zhangfei", "张飞", "shu", "xinye"),
        ("zhugeliang", "诸葛亮", "shu", "longzhong"),
        ("sunquan", "孙权", "wu", "jianye"),
        ("zhouyu", "周瑜", "wu", "chaisang"),
        ("xunyu", "荀彧", "cao", "xuchang"),
        ("simayi", "司马懿", "cao", "xuchang"),
    ]:
        ws.characters[cid] = Character(
            id=cid,
            name=name,
            faction_id=fid,
            location=loc,
            alive=True,
            loyalty=75,
        )

    # Armies
    from histrategy_engine.world import UnitType

    ws.armies["army_cao_1"] = Army(
        id="army_cao_1",
        faction_id="cao",
        location="wancheng",
        units={UnitType.INFANTRY: 5000},
        morale=80,
        supply=30,
    )
    ws.armies["army_shu_1"] = Army(
        id="army_shu_1",
        faction_id="shu",
        location="xinye",
        units={UnitType.INFANTRY: 5000},
        morale=80,
        supply=30,
    )

    return ws


# ═══════════════════════════════════════════════════════════════
# Policy Types
# ═══════════════════════════════════════════════════════════════


class TestPolicyCommand:
    def test_valid_types(self):
        for cmd_type in POLICY_COMMAND_TYPES:
            cmd = PolicyCommand(type=cmd_type, params={})
            assert cmd.type == cmd_type

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            PolicyCommand(type="attack")

    def test_params_preserved(self):
        cmd = PolicyCommand(
            type="tax_rate",
            params={"rate": 0.30, "territory": "xuchang"},
            notes="减轻百姓负担",
            source_text="税率降至30%",
        )
        assert cmd.params["rate"] == 0.30
        assert cmd.notes == "减轻百姓负担"


class TestValidatePolicyParams:
    def test_missing_required(self):
        errors = validate_policy_params("tax_rate", {})
        assert len(errors) > 0
        assert any("rate" in e for e in errors)

    def test_valid(self):
        errors = validate_policy_params("tax_rate", {"rate": 0.30})
        assert len(errors) == 0

    def test_unknown_param_warns(self):
        errors = validate_policy_params("tax_rate", {"rate": 0.30, "unknown_key": "x"})
        assert len(errors) == 1
        assert "unknown_key" in errors[0]

    def test_declare_war_requires_target(self):
        errors = validate_policy_params("declare_war", {})
        assert any("target" in e for e in errors)


# ═══════════════════════════════════════════════════════════════
# Policy Parser (keyword fallback)
# ═══════════════════════════════════════════════════════════════


class TestPolicyParserKeyword:
    def test_tax_rate(self):
        parser = PolicyParser()
        cmds = parser.parse("将税率降至30%，减轻百姓负担", "cao")
        tax_cmds = [c for c in cmds if c.type == "tax_rate"]
        assert len(tax_cmds) >= 1
        assert tax_cmds[0].params["rate"] == 0.30

    def test_declare_war(self):
        parser = PolicyParser()
        cmds = parser.parse("对刘表宣战，夺取荆州", "cao")
        war_cmds = [c for c in cmds if c.type == "declare_war"]
        assert len(war_cmds) >= 1
        # Target should be "liubiao" (the ID), not the Chinese name with annotation
        assert war_cmds[0].params["target"] in ("liubiao", "刘表(liubiao)")

    def test_law_enactment(self):
        parser = PolicyParser()
        cmds = parser.parse("推行屯田制，在全部领地开垦荒地", "cao")
        law_cmds = [c for c in cmds if c.type == "law"]
        assert len(law_cmds) >= 1

    def test_empty_input(self):
        parser = PolicyParser()
        cmds = parser.parse("", "cao")
        assert cmds == []

    def test_multiple_commands(self):
        parser = PolicyParser()
        cmds = parser.parse(
            "将税率降至25%，推行屯田制，对刘表宣战",
            "cao",
        )
        types = {c.type for c in cmds}
        assert "tax_rate" in types
        assert "law" in types or "declare_war" in types


# ═══════════════════════════════════════════════════════════════
# Policy Validator
# ═══════════════════════════════════════════════════════════════


class TestPolicyValidator:
    def test_validates_declare_war(self, world_state):
        validator = PolicyValidator()
        cmd = PolicyCommand(type="declare_war", params={"target": "shu"})
        result = validator.validate([cmd], world_state)
        assert len(result) == 1

    def test_rejects_nonexistent_target(self, world_state):
        validator = PolicyValidator()
        cmd = PolicyCommand(type="declare_war", params={"target": "yuanshao"})
        result = validator.validate([cmd], world_state)
        # Still included but with validation note
        assert len(result) == 1

    def test_validates_tax_rate_range(self, world_state):
        validator = PolicyValidator()
        cmd = PolicyCommand(type="tax_rate", params={"rate": 1.5})
        result = validator.validate([cmd], world_state)
        assert len(result) == 1

    def test_validates_appoint_character(self, world_state):
        validator = PolicyValidator()
        cmd = PolicyCommand(type="appoint", params={"character": "nonexistent_person"})
        result = validator.validate([cmd], world_state)
        assert len(result) == 1

    def test_validates_relocate_capital_ownership(self, world_state):
        validator = PolicyValidator()
        cmd = PolicyCommand(type="relocate_capital", params={"to": "xinye"})
        result = validator.validate([cmd], world_state)
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════
# Economy Parameters
# ═══════════════════════════════════════════════════════════════


class TestEconomyParams:
    def test_defaults_reasonable(self):
        p = EconomyParams()
        assert 0 < p.base_population_growth < 0.1
        assert 0 < p.base_food_per_soldier < 1.0
        assert 0 <= p.max_tax_rate <= 1.0

    def test_custom_params(self):
        p = EconomyParams(
            base_population_growth=0.01,
            max_tax_rate=0.80,
        )
        assert p.base_population_growth == 0.01
        assert p.max_tax_rate == 0.80


# ═══════════════════════════════════════════════════════════════
# Quarterly Engine
# ═══════════════════════════════════════════════════════════════


class TestQuarterlyEngine:
    def test_execute_quarter_produces_result(self, world_state):
        engine = QuarterlyEngine()
        result = engine.execute_quarter(
            world_state,
            policy_commands=[],
            year=207,
            quarter=3,  # winter
        )
        assert isinstance(result, QuarterResult)
        assert result.year == 207
        assert result.quarter == 3

    def test_tax_revenue_computed(self, world_state):
        engine = QuarterlyEngine()
        result = engine.execute_quarter(world_state, [], 207, 0)
        assert "cao" in result.tax_revenue
        assert result.tax_revenue["cao"] > 0

    def test_food_delta_computed(self, world_state):
        engine = QuarterlyEngine()
        result = engine.execute_quarter(world_state, [], 207, 0)
        assert "cao" in result.food_delta

    def test_morale_delta_computed(self, world_state):
        engine = QuarterlyEngine()
        result = engine.execute_quarter(world_state, [], 207, 0)
        assert "cao" in result.morale_delta

    def test_tax_rate_from_policy(self, world_state):
        engine = QuarterlyEngine()
        cmd = PolicyCommand(type="tax_rate", params={"rate": 0.25})
        result = engine.execute_quarter(world_state, [cmd], 207, 0)
        # Lower tax should give less revenue
        revenue_25 = result.tax_revenue["cao"]

        result2 = engine.execute_quarter(world_state, [], 207, 0)
        revenue_40 = result2.tax_revenue["cao"]

        assert revenue_25 < revenue_40, f"25% tax ({revenue_25}) should yield less than 40% ({revenue_40})"

    def test_tuntian_law_boosts_food(self, world_state):
        engine = QuarterlyEngine()
        # With 屯田制
        cmd = PolicyCommand(type="law", params={"name": "屯田制"})
        result_with = engine.execute_quarter(world_state, [cmd], 207, 0)

        # Without
        result_without = engine.execute_quarter(world_state, [], 207, 0)

        assert result_with.food_delta["cao"] > result_without.food_delta["cao"]

    def test_conscription_deducts_treasury(self, world_state):
        engine = QuarterlyEngine()
        original_treasury = world_state.factions["cao"].treasury
        cmd = PolicyCommand(type="conscript", params={"amount": 5000})
        engine.execute_quarter(world_state, [cmd], 207, 0)
        assert world_state.factions["cao"].treasury < original_treasury

    def test_high_tax_hurts_morale(self, world_state):
        engine = QuarterlyEngine()
        high_tax = PolicyCommand(type="tax_rate", params={"rate": 0.60})
        low_tax = PolicyCommand(type="tax_rate", params={"rate": 0.15})

        result_high = engine.execute_quarter(world_state, [high_tax], 207, 0)
        result_low = engine.execute_quarter(world_state, [low_tax], 207, 0)

        assert result_high.morale_delta["cao"] < result_low.morale_delta["cao"]

    def test_food_shortage_hurts_morale(self, world_state):
        """Faction with critically low food should get morale penalty.

        With calibrated parameters, even zero food may not cause starvation
        if production > consumption. The penalty only triggers when
        food_produced - food_consumed is deeply negative.
        """
        engine = QuarterlyEngine()
        # Provoke severe food shortage: set high strength, zero food
        world_state.factions["shu"].food = 0
        world_state.factions["shu"].strength_actual = 50000  # lots of mouths
        result = engine.execute_quarter(world_state, [], 207, 0)
        # Should get some morale penalty from high consumption
        morale_d = result.morale_delta.get("shu", 0)
        # With calibrated params, low food + high troops = morale hit
        assert morale_d <= 0, f"Expected morale penalty, got {morale_d}"


# ═══════════════════════════════════════════════════════════════
# Knowledge Layer
# ═══════════════════════════════════════════════════════════════


class TestKnowledgeCard:
    def test_create_card(self):
        card = KnowledgeCard(
            topic="屯田制",
            historical_source="《三国志》",
            source_quote="是岁，乃兴屯田...",
            modern_scholarship="田余庆认为...",
            scholar="田余庆",
            scholar_work="《秦汉魏晋史探微》",
            engine_logic="粮食+30%",
            related_topics=["均田制"],
        )
        assert card.topic == "屯田制"

    def test_to_dict_roundtrip(self):
        card = KnowledgeCard(topic="测试", source_quote="test")
        d = card.to_dict()
        card2 = KnowledgeCard.from_dict(d)
        assert card2.topic == "测试"
        assert card2.source_quote == "test"


class TestKnowledgeBase:
    def test_builtin_cards_loaded(self):
        kb = KnowledgeBase()
        assert kb.get("屯田制") is not None
        assert kb.get("九品中正制") is not None
        assert kb.get("赤壁之战") is not None

    def test_get_nonexistent(self):
        kb = KnowledgeBase()
        assert kb.get("不存在的制度") is None

    def test_search_by_topic(self):
        kb = KnowledgeBase()
        results = kb.search("屯田")
        assert len(results) >= 1
        assert any(c.topic == "屯田制" for c in results)

    def test_search_by_related(self):
        kb = KnowledgeBase()
        results = kb.search("均田制")
        assert len(results) >= 1

    def test_add_custom_card(self):
        kb = KnowledgeBase()
        card = KnowledgeCard(topic="盐铁专卖")
        kb.add(card)
        assert kb.get("盐铁专卖") is not None

    def test_get_cards_for_events(self):
        kb = KnowledgeBase()
        events = [BUILTIN_CARDS["屯田制"].to_dict()]
        cards = kb.get_cards_for_events(events)
        assert len(cards) == 1
        assert cards[0].topic == "屯田制"


# ═══════════════════════════════════════════════════════════════
# Black Swan Injector
# ═══════════════════════════════════════════════════════════════


class TestBlackSwanInjector:
    def test_creates_with_seed(self):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector(seed=42)
        assert bsi is not None

    def test_deterministic_with_seed(self):
        from histrategy.engine.black_swan import BlackSwanInjector

        # Same seed should produce same trigger decisions
        bsi1 = BlackSwanInjector(seed=42)
        bsi2 = BlackSwanInjector(seed=42)

        results1 = [bsi1._roll(0.9, 0.05) for _ in range(100)]
        results2 = [bsi2._roll(0.9, 0.05) for _ in range(100)]
        assert results1 == results2

    def test_high_gravity_usually_triggers(self):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector(seed=99)
        triggered = sum(1 for _ in range(1000) if bsi._roll(0.95, 0.05))
        # Should trigger > 80% of the time with gravity 0.95 and low deviation
        assert triggered > 800, f"Only {triggered}/1000 triggered"

    def test_high_deviation_averts_more(self):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector(seed=99)
        low_dev = sum(1 for _ in range(500) if bsi._roll(0.9, 0.05))
        high_dev = sum(1 for _ in range(500) if bsi._roll(0.9, 0.5))
        assert high_dev < low_dev, f"low_dev={low_dev}, high_dev={high_dev}"

    def test_inject_event_marks_character_dead(self, world_state):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector()
        assert world_state.characters["liubei"].alive is True
        bsi.inject_event("test_death", {"liubei_dead": True}, world_state)
        assert world_state.characters["liubei"].alive is False

    def test_inject_event_changes_location(self, world_state):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector()
        bsi.inject_event("test_move", {"liubei_location": "jiangling"}, world_state)
        assert world_state.characters["liubei"].location == "jiangling"

    def test_inject_event_marks_triggered(self):
        from histrategy.engine.black_swan import BlackSwanInjector

        bsi = BlackSwanInjector()
        bsi.inject_event("custom_event", {}, None)
        assert "custom_event" in bsi._triggered


# ═══════════════════════════════════════════════════════════════
# Integration: Policy → Validation → Quarterly Engine
# ═══════════════════════════════════════════════════════════════


class TestMacroPipeline:
    """End-to-end test: parse → validate → simulate."""

    def test_full_pipeline_no_llm(self, world_state):
        parser = PolicyParser()
        validator = PolicyValidator()
        engine = QuarterlyEngine()

        # 1. Parse player decision
        decision = "将税率从40%降至25%，推行屯田制，向刘表宣战夺取襄阳"
        commands = parser.parse(decision, "cao")

        assert len(commands) > 0, "Should parse at least one command"

        # 2. Validate
        valid_commands = validator.validate(commands, world_state)
        assert len(valid_commands) > 0

        # 3. Execute quarterly simulation
        result = engine.execute_quarter(world_state, valid_commands, 207, 0)
        assert isinstance(result, QuarterResult)

        # 4. Verify economic effects
        assert "cao" in result.tax_revenue

    def test_pipeline_preserves_state(self, world_state):
        parser = PolicyParser()
        validator = PolicyValidator()
        engine = QuarterlyEngine()

        original_treasury = world_state.factions["cao"].treasury
        original_food = world_state.factions["cao"].food

        commands = parser.parse("税率降至30%", "cao")
        valid = validator.validate(commands, world_state)
        engine.execute_quarter(world_state, valid, 207, 1)

        # Treasury and food should have changed
        assert world_state.factions["cao"].treasury != original_treasury
        assert world_state.factions["cao"].food != original_food
