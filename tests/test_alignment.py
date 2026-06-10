"""Tests for AlignmentEngine — LLM-driven non-linear friction layer."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.llm.alignment import (
    ALIGNMENT_SYSTEM_PROMPT,
    MAX_ADJUSTMENT_PCT,
    MAX_RETRIES,
    AlignmentEngine,
    FrictionEvent,
)


class FakeLLM:
    """Fake LLM adapter for testing alignment pipeline."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self._idx = 0
        self.is_available = True
        self.last_call_stats = None

    @property
    def is_available(self):
        return True

    @is_available.setter
    def is_available(self, val):
        pass

    def chat(self, messages, temperature=0.7, max_tokens=2048):
        if self._idx < len(self.responses):
            resp = self.responses[self._idx]
            self._idx += 1
            return resp
        return json.dumps({"friction_events": []})


class TestAlignmentEngine:
    """Tests for AlignmentEngine."""

    def make_engine(self, responses=None):
        return AlignmentEngine(FakeLLM(responses))

    def make_turn_result(self):
        """Create a realistic turn result with battles and resources."""
        from collections import namedtuple

        Battle = namedtuple("Battle", "attacker_id defender_id location result attacker_casualties defender_casualties")
        BattleResult = namedtuple("BattleResult", "value")

        return {
            "battles": [
                Battle("cao", "shu", "wancheng", "victory", 5000, 15000),
            ],
            "resource_changes": {
                "cao": {"food_delta": -8000, "tax_revenue": 5000, "treasury_spent": 2000},
                "shu": {"food_delta": -3000, "tax_revenue": 800, "treasury_spent": 0},
            },
            "character_events": [
                {
                    "type": "loyalty_change",
                    "character_id": "guanyu",
                    "character_name": "关羽",
                    "delta": -2,
                    "new_loyalty": 78,
                },
            ],
        }

    def test_no_llm_returns_empty(self):
        """When LLM is unavailable, return empty approved result."""
        engine = AlignmentEngine(None)
        result = engine.align({})
        assert result.approved
        assert len(result.friction_events) == 0

    def test_empty_response_is_valid(self):
        """Empty friction_events array is a valid response."""
        engine = self.make_engine([json.dumps({"friction_events": []})])
        result = engine.align(self.make_turn_result())
        assert result.approved
        assert result.attempt_count == 1
        assert len(result.friction_events) == 0

    def test_valid_event_is_approved(self):
        """A valid friction event within bounds should be approved."""
        valid_response = json.dumps(
            {
                "friction_events": [
                    {
                        "type": "weather",
                        "title": "大雾弥漫",
                        "description": "宛城之战遭遇大雾，曹操军追击受阻，额外损失500人",
                        "affected_faction": "cao",
                        "affected_stat": "casualties",
                        "original_value": 10000,
                        "adjusted_value": 9500,
                        "adjustment_pct": -5.0,
                    }
                ]
            }
        )
        engine = self.make_engine([valid_response])
        result = engine.align(self.make_turn_result())

        assert result.approved
        assert len(result.friction_events) == 1
        assert result.friction_events[0].type == "weather"
        assert result.friction_events[0].title == "大雾弥漫"

    def test_excessive_adjustment_triggers_retry(self):
        """An event exceeding 25% adjustment should trigger retry."""
        invalid_response = json.dumps(
            {
                "friction_events": [
                    {
                        "type": "weather",
                        "title": "天降陨石",
                        "description": "陨石摧毁全军",
                        "affected_faction": "cao",
                        "affected_stat": "casualties",
                        "original_value": 10000,
                        "adjusted_value": 2000,  # 80% reduction
                        "adjustment_pct": -80.0,
                    }
                ]
            }
        )
        # First response is invalid, second is empty
        engine = self.make_engine([invalid_response, json.dumps({"friction_events": []})])
        result = engine.align(self.make_turn_result())

        assert result.approved
        # After max retries, should fall back
        assert result.attempt_count == 2  # first attempt failed, second succeeded

    def test_three_retries_fallback(self):
        """After 3 invalid attempts, fall back to empty."""
        invalid = json.dumps(
            {
                "friction_events": [
                    {
                        "type": "weather",
                        "title": "核爆",
                        "description": "核弹毁灭一切",
                        "affected_faction": "cao",
                        "affected_stat": "casualties",
                        "original_value": 10000,
                        "adjusted_value": 0,
                        "adjustment_pct": -100.0,
                    }
                ]
            }
        )
        engine = self.make_engine([invalid, invalid, invalid])
        result = engine.align(self.make_turn_result())

        assert result.approved
        assert result.fallback_used
        assert result.attempt_count == MAX_RETRIES

    def test_malformed_json_is_handled(self):
        """Malformed LLM output should not crash."""
        engine = self.make_engine(["not valid json at all"])
        result = engine.align(self.make_turn_result())
        assert result.approved
        assert len(result.friction_events) == 0

    def test_friction_event_dataclass(self):
        event = FrictionEvent(
            type="weather",
            title="暴雨",
            description="测试",
            affected_faction="cao",
            affected_stat="casualties",
            original_value=10000,
            adjusted_value=11000,
            adjustment_pct=10.0,
        )
        d = event.to_dict()
        assert d["type"] == "weather"
        assert d["original_value"] == 10000

    def test_system_prompt_exists(self):
        """Alignment system prompt should be non-empty."""
        assert len(ALIGNMENT_SYSTEM_PROMPT) > 100
        assert "±20%" in ALIGNMENT_SYSTEM_PROMPT or "20" in ALIGNMENT_SYSTEM_PROMPT

    def test_max_adjustment_constant(self):
        """MAX_ADJUSTMENT_PCT should be 25%."""
        assert MAX_ADJUSTMENT_PCT == 0.25
