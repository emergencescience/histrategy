"""
Integration tests for NarrativeEngine — verify player context passthrough.

Covers:
- _build_narrative_context includes player_decision
- _build_narrative_context includes parsed commands with notes
- Command notes survive TurnResult → narrative context
"""

import pytest

from histrategy.llm.narrative import NarrativeEngine
from histrategy_engine import (
    Command,
    Season,
    TurnResult,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def narrative_engine():
    """Offline-mode NarrativeEngine (no LLM → tests _build_narrative_context directly)."""
    return NarrativeEngine(llm_adapter=None)


@pytest.fixture
def sample_turn_result_with_context():
    """TurnResult with player decision and commands."""
    return TurnResult(
        year=208,
        season=Season.SPRING,
        turn_number=3,
        player_decision="【南征刘备】集结宛城5万步兵和1万骑兵，春季行军进攻新野。在下邳部署防守。",
        player_commands=[
            Command(
                type="attack",
                params={"target_territory": "xinye"},
                faction_id="cao",
                notes="【南征刘备战役】主力行动：从宛城集结6万大军进攻新野",
            ),
            Command(
                type="defend",
                params={"territory": "xiapi"},
                faction_id="cao",
                notes="【南征刘备战役】东线防御：防范孙权从庐江进攻",
            ),
        ],
    )


@pytest.fixture
def empty_turn_result():
    """TurnResult without player context (backward compat)."""
    return TurnResult(
        year=208,
        season=Season.SPRING,
        turn_number=1,
    )


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════


class TestNarrativeContextWithPlayerDecision:
    """Verify narrative context builder captures player intent."""

    def test_context_includes_player_decision(self, narrative_engine, sample_turn_result_with_context):
        """_build_narrative_context should include the player's original decision text."""
        context = narrative_engine._build_narrative_context(sample_turn_result_with_context)
        assert "君主决策（原文）" in context
        assert "南征刘备" in context
        assert "集结宛城" in context
        assert "春季行军" in context

    def test_context_includes_parsed_commands(self, narrative_engine, sample_turn_result_with_context):
        """_build_narrative_context should include parsed commands with notes."""
        context = narrative_engine._build_narrative_context(sample_turn_result_with_context)
        assert "解析后的军令" in context
        assert "attack" in context
        assert "defend" in context
        assert "xinye" in context
        assert "xiapi" in context
        # Notes should appear in brackets
        assert "南征刘备战役" in context
        assert "防范孙权" in context

    def test_context_backward_compat_empty_decision(self, narrative_engine, empty_turn_result):
        """With empty player_decision, no decision section appears (backward compat)."""
        context = narrative_engine._build_narrative_context(empty_turn_result)
        assert "君主决策（原文）" not in context
        assert "解析后的军令" not in context
        # But basic time info still works
        assert "当前时间" in context
        assert "208年" in context

    def test_context_includes_time(self, narrative_engine, sample_turn_result_with_context):
        """Time section is still present."""
        context = narrative_engine._build_narrative_context(sample_turn_result_with_context)
        assert "当前时间" in context
        assert "208年" in context
        assert "第3回合" in context

    def test_context_player_decision_before_other_sections(self, narrative_engine, sample_turn_result_with_context):
        """Player decision should appear after time but before climate/resources."""
        context = narrative_engine._build_narrative_context(sample_turn_result_with_context)
        time_pos = context.index("当前时间")
        decision_pos = context.index("君主决策（原文）")
        commands_pos = context.index("解析后的军令")
        assert time_pos < decision_pos < commands_pos


class TestCommandNotesInContext:
    """Command notes survive the full round-trip."""

    def test_notes_appear_in_brackets(self, narrative_engine, sample_turn_result_with_context):
        """Notes should be formatted as '[note text]' in the context."""
        context = narrative_engine._build_narrative_context(sample_turn_result_with_context)
        assert "[【南征刘备战役】主力行动" in context
        assert "[【南征刘备战役】东线防御" in context

    def test_no_crash_with_none_notes(self, narrative_engine):
        """Command without notes should not crash the context builder."""
        tr = TurnResult(
            year=208,
            season=Season.SPRING,
            turn_number=1,
            player_decision="进攻",
            player_commands=[
                Command(type="attack", params={"target_territory": "xinye"}, faction_id="cao"),
            ],
        )
        context = narrative_engine._build_narrative_context(tr)
        assert "解析后的军令" in context
        assert "attack" in context
        # No bracket with notes since notes is empty
