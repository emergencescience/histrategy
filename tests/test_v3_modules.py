"""
Unit tests for v3 modules: GuardrailValidator, StateApplier, TurnMemory.
"""

import tempfile

import pytest
from histrategy_engine import (
    Army,
    Character,
    FactionState,
    Season,
    TerrainType,
    Territory,
    TurnResult,
    UnitType,
    WorldState,
)
from histrategy_engine.world import BattleResult, CombatResult

from histrategy.engine.guardrail import (
    GuardrailValidator,
)
from histrategy.engine.state_applier import (
    StateApplier,
    TurnMemory,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def guardrail():
    return GuardrailValidator()


@pytest.fixture
def applier():
    return StateApplier()


@pytest.fixture
def memory():
    tmp = tempfile.mkdtemp()
    tm = TurnMemory(data_dir=tmp)
    yield tm
    # cleanup
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def world_state():
    ws = WorldState(year=208, season=Season.SPRING, turn_number=3, player_faction_id="cao")

    ws.territories = {
        "xuchang": Territory(
            id="xuchang",
            name="许昌",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            population=100000,
            development=70,
            neighbors=["wancheng", "luoyang"],
        ),
        "wancheng": Territory(
            id="wancheng",
            name="宛城",
            owner_id="cao",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            population=50000,
            development=40,
            neighbors=["xuchang", "xinye"],
        ),
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            population=30000,
            development=25,
            neighbors=["wancheng"],
        ),
    }

    ws.factions = {
        "cao": FactionState(
            id="cao",
            name="曹操",
            ruler_id="cao_cao",
            capital="xuchang",
            territories=["xuchang", "wancheng"],
            strength_actual=150000,
            treasury=50000,
            food=30000,
            morale_actual=60,
            tax_rate=0.3,
            aggression=0.8,
            is_active=True,
        ),
        "shu": FactionState(
            id="shu",
            name="刘备",
            ruler_id="liu_bei",
            capital="xinye",
            territories=["xinye"],
            strength_actual=5000,
            treasury=3000,
            food=2000,
            morale_actual=65,
            tax_rate=0.2,
            mercy=0.95,
            is_active=True,
        ),
    }

    ws.armies = {
        "army_cao_1": Army(
            id="army_cao_1",
            faction_id="cao",
            location="wancheng",
            units={UnitType.INFANTRY: 50000, UnitType.CAVALRY: 10000},
        ),
        "army_shu_1": Army(
            id="army_shu_1",
            faction_id="shu",
            location="xinye",
            units={UnitType.INFANTRY: 5000},
        ),
    }

    ws.characters = {
        "cao_cao": Character(
            id="cao_cao",
            name="曹操",
            faction_id="cao",
            alive=True,
            loyalty=100,
            leadership=95,
            might=75,
            intelligence=92,
            politics=95,
            location="xuchang",
        ),
        "liu_bei": Character(
            id="liu_bei",
            name="刘备",
            faction_id="shu",
            alive=True,
            loyalty=100,
            leadership=85,
            might=70,
            intelligence=78,
            politics=82,
            location="xinye",
        ),
    }

    return ws


# ═══════════════════════════════════════════════════════════════
# GuardrailValidator Tests
# ═══════════════════════════════════════════════════════════════


class TestGuardrailBattleOverrides:
    """Hard constraint enforcement for battle overrides."""

    def test_valid_override_passes(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "baseline_result": "victory",
                    "llm_result": "defender_surrendered",
                    "casualties": {"attacker": 0, "defender": 0},
                    "reasoning": "刘备主动弃城",
                    "territory_captured": True,
                    "captured_characters": [],
                    "escaped_characters": ["liu_bei"],
                }
            ]
        }
        # Create a minimal baseline with matching battle
        from histrategy_engine.world import BattleResult, CombatResult

        baseline = TurnResult(
            battles=[
                CombatResult(
                    battle_id="b1",
                    location="xinye",
                    attacker_id="cao",
                    defender_id="shu",
                    attacker_casualties={UnitType.INFANTRY: 500},
                    defender_casualties={UnitType.INFANTRY: 1000},
                    result=BattleResult.VICTORY,
                )
            ]
        )
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is True
        assert len(result["violations"]) == 0

    def test_unknown_territory_rejected(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "atlantis",
                    "casualties": {"attacker": 100, "defender": 100},
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False
        assert len(result["violations"]) == 1

    def test_negative_casualties_rejected(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": -500, "defender": 100},
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_same_character_captured_and_escaped_rejected(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 100, "defender": 100},
                    "captured_characters": ["liu_bei"],
                    "escaped_characters": ["liu_bei"],
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_unknown_character_rejected(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 100, "defender": 100},
                    "captured_characters": ["zhuge_liang"],
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_casualty_deviation_too_high_rejected(self, guardrail, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 50000, "defender": 5000},  # 100x baseline
                }
            ]
        }
        baseline = TurnResult(
            battles=[
                CombatResult(
                    battle_id="b1",
                    location="xinye",
                    attacker_id="cao",
                    defender_id="shu",
                    attacker_casualties={UnitType.INFANTRY: 500},
                    defender_casualties={UnitType.INFANTRY: 1000},
                    result=BattleResult.VICTORY,
                )
            ]
        )
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False


class TestGuardrailMoraleEvents:
    """Hard constraint enforcement for morale events."""

    def test_valid_morale_passes(self, guardrail, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "cao",
                    "change": 5,
                    "reason": "邺城仁政三季",
                    "persistent_note": "邺城民心稳固",
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is True

    def test_morale_exceeds_100_rejected(self, guardrail, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "cao",
                    "change": 50,  # 60 + 50 = 110 > 100
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_morale_below_0_rejected(self, guardrail, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "shu",
                    "change": -100,  # 65 - 100 = -35 < 0
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_unknown_faction_rejected(self, guardrail, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "dongzhuo",
                    "change": 5,
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is False

    def test_large_but_valid_morale_generates_warning(self, guardrail, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "cao",
                    "change": 16,  # >15 → soft warning, not hard rejection
                }
            ]
        }
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert result["accepted"] is True  # Not rejected
        assert len(result["warnings"]) > 0  # But warned


class TestGuardrailEmptyDelta:
    """Edge cases for empty/missing delta fields."""

    def test_empty_delta_accepted(self, guardrail, world_state):
        baseline = TurnResult()
        result = guardrail.validate({}, world_state, baseline)
        assert result["accepted"] is True
        assert result["sanitized_delta"]["battle_overrides"] == []

    def test_missing_keys_defaulted(self, guardrail, world_state):
        delta = {"battle_overrides": []}
        baseline = TurnResult()
        result = guardrail.validate(delta, world_state, baseline)
        assert "morale_events" in result["sanitized_delta"]
        assert result["sanitized_delta"]["morale_events"] == []


# ═══════════════════════════════════════════════════════════════
# StateApplier Tests
# ═══════════════════════════════════════════════════════════════


class TestStateApplier:
    """Safe WorldState mutation."""

    def test_applies_morale_change(self, applier, world_state):
        delta = {
            "morale_events": [
                {
                    "faction": "cao",
                    "change": 10,
                    "reason": "大胜提振",
                }
            ]
        }
        original = world_state.factions["cao"].morale_actual
        applier.apply(delta, world_state)
        assert world_state.factions["cao"].morale_actual == original + 10

    def test_morale_clamped_at_100(self, applier, world_state):
        world_state.factions["cao"].morale_actual = 98
        delta = {"morale_events": [{"faction": "cao", "change": 10}]}
        applier.apply(delta, world_state)
        assert world_state.factions["cao"].morale_actual == 100

    def test_battle_casualties_applied(self, applier, world_state):
        initial = world_state.armies["army_cao_1"].total_troops
        # Move cao army to xinye (attacking shu territory)
        world_state.armies["army_cao_1"].location = "xinye"
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 5000, "defender": 2000},
                }
            ]
        }
        applier.apply(delta, world_state)
        assert world_state.armies["army_cao_1"].total_troops <= initial - 4000  # ~5000 with rounding

    def test_territory_capture(self, applier, world_state):
        # Move cao army to xinye so it can capture
        world_state.armies["army_cao_1"].location = "xinye"
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 500, "defender": 2000},
                    "territory_captured": True,
                }
            ]
        }
        applier.apply(delta, world_state)
        assert world_state.territories["xinye"].owner_id == "cao"

    def test_character_captured(self, applier, world_state):
        delta = {
            "battle_overrides": [
                {
                    "location": "xinye",
                    "casualties": {"attacker": 100, "defender": 500},
                    "captured_characters": ["liu_bei"],
                }
            ]
        }
        applier.apply(delta, world_state)
        assert world_state.characters["liu_bei"].faction_id == ""

    def test_empty_delta_noop(self, applier, world_state):
        summary = applier.apply({}, world_state)
        assert summary["battles_modified"] == 0
        assert summary["morale_changes"] == 0


# ═══════════════════════════════════════════════════════════════
# TurnMemory Tests
# ═══════════════════════════════════════════════════════════════


class TestTurnMemory:
    """Append-only memory and persistent effects."""

    def test_records_and_retrieves_turns(self, memory):
        memory.record_turn(
            "test_room",
            1,
            208,
            "春",
            "发展内政",
            "许昌开发度提升",
            ["发展"],
            {"morale": 60, "territories": 3},
            [],
        )
        memory.record_turn(
            "test_room",
            2,
            208,
            "夏",
            "进攻新野",
            "新野攻克",
            ["战斗"],
            {"morale": 65, "territories": 4},
            [{"note": "新野易主"}],
        )

        recent = memory.get_recent_turns("test_room", n=5)
        assert len(recent) == 2
        assert recent[0]["turn"] == 1
        assert recent[1]["turn"] == 2
        assert recent[1]["outcome_summary"] == "新野攻克"

    def test_persistent_effects_accumulate(self, memory):
        memory.record_turn(
            "test_room",
            1,
            208,
            "春",
            "test",
            "summary",
            [],
            {},
            [{"note": "邺城仁政第一季"}],
        )
        memory.record_turn(
            "test_room",
            2,
            208,
            "夏",
            "test",
            "summary",
            [],
            {},
            [{"note": "邺城仁政第二季"}],
        )

        effects = memory.get_persistent_effects("test_room")
        assert len(effects) == 2
        assert effects[0]["note"] == "邺城仁政第一季"

    def test_empty_memory_returns_empty(self, memory):
        assert memory.get_recent_turns("nonexistent") == []
        assert memory.get_persistent_effects("nonexistent") == []

    def test_get_n_turns_respects_limit(self, memory):
        for i in range(10):
            memory.record_turn(
                "test_room",
                i + 1,
                208,
                "春",
                f"turn {i + 1}",
                "ok",
                [],
                {"morale": 50},
                [],
            )
        recent = memory.get_recent_turns("test_room", n=3)
        assert len(recent) == 3
        assert recent[-1]["turn"] == 10

    def test_clean_future_turns(self, memory):
        memory.record_turn(
            "test_room",
            1,
            208,
            "春",
            "decision 1",
            "summary 1",
            [],
            {},
            [{"note": "effect 1", "turn": 1}],
        )
        memory.record_turn(
            "test_room",
            2,
            208,
            "夏",
            "decision 2",
            "summary 2",
            [],
            {},
            [{"note": "effect 2", "turn": 2}],
        )
        memory.record_turn(
            "test_room",
            3,
            208,
            "秋",
            "decision 3",
            "summary 3",
            [],
            {},
            [{"note": "effect 3", "turn": 3}],
        )

        # Truncate to turn 2 (so only turn 1 remains)
        memory.clean_future_turns("test_room", 2)

        recent = memory.get_recent_turns("test_room", n=5)
        assert len(recent) == 1
        assert recent[0]["turn"] == 1

        effects = memory.get_persistent_effects("test_room")
        assert len(effects) == 1
        assert effects[0]["note"] == "effect 1"
