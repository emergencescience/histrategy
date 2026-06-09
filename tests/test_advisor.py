"""Tests for StrategicAdvisor — unified player/NPC strategy interface."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.llm.advisor import (
    ADVISOR_SYSTEM_PROMPT,
    StrategicAdvisor,
    AdvisorRecommendation,
)


class FakeLLM:
    """Fake LLM for testing."""
    def __init__(self, response=""):
        self.response = response
        self.is_available = True

    def chat(self, messages, temperature=0.7, max_tokens=512):
        return self.response


def make_local_state():
    """Create a realistic LocalWorldState dict (from projector output)."""
    return {
        "my": {
            "treasury": 3000,
            "food": 2000,
            "strength": 5000,
            "economy": 30,
            "morale": 70,
            "territories": ["xinye"],
        },
        "perceived": {
            "cao": {
                "name": "曹操军",
                "strength": "127,500~172,500",
                "territories": 9,
                "is_border": True,
                "is_allied": False,
            },
            "wu": {
                "name": "孙权军",
                "strength": "60,000",
                "territories": 7,
                "is_border": False,
                "is_allied": True,
            },
        },
        "visible_armies": {
            "army_cao_1": {
                "faction_id": "cao",
                "location": "wancheng",
                "estimated_troops": "17,000~23,000",
            },
        },
        "border_garrisons": {
            "wancheng": {
                "territory_name": "宛城",
                "estimated_troops": "17,000~23,000",
            },
        },
    }


class TestStrategicAdvisor:
    """Tests for StrategicAdvisor."""

    def test_offline_advice(self):
        """Offline advice should work without LLM."""
        advisor = StrategicAdvisor(None)
        local = make_local_state()
        advice = advisor.advise_player(local, query="进攻宛城？")
        assert len(advice) > 10
        # Should contain some strategic content
        assert any(word in advice for word in ["粮草", "发展", "防守", "审慎", "曹操", "边境"])

    def test_offline_strategy(self):
        """Offline strategy should return structured data."""
        advisor = StrategicAdvisor(None)
        local = make_local_state()
        result = advisor.evaluate_strategy(local)
        assert "analysis" in result
        assert "recommendations" in result
        assert "risk_assessment" in result

    def test_offline_strategy_detects_low_food(self):
        """Low food should trigger develop recommendation."""
        advisor = StrategicAdvisor(None)
        local = make_local_state()
        local["my"]["food"] = 500  # very low
        result = advisor.evaluate_strategy(local)
        assert any(r["action"] == "develop" for r in result["recommendations"])

    def test_llm_advisor_handles_json(self):
        """LLM response should be parsed correctly."""
        llm = FakeLLM(json.dumps({
            "analysis": "当前局势险恶",
            "recommendations": [
                {"action": "defend", "target": "曹操", "priority": 0.9, "reason": "曹军势大"}
            ],
            "risk_assessment": "极高风险",
        }))
        advisor = StrategicAdvisor(llm)
        local = make_local_state()
        result = advisor.evaluate_strategy(local)

        assert result["analysis"] == "当前局势险恶"
        assert len(result["recommendations"]) == 1
        assert result["recommendations"][0]["action"] == "defend"

    def test_llm_advice_with_query(self):
        """Player query should return natural language advice."""
        llm = FakeLLM("亮观之，曹军虽众，然新得宛城民心未附。若我军速战，三成胜算；若能诱其出城合围，则有七成胜算。")
        advisor = StrategicAdvisor(llm)
        local = make_local_state()
        result = advisor.evaluate_strategy(local, query="进攻宛城胜算几何？")

        assert "advice" in result
        assert "胜算" in result["advice"]

    def test_advisor_is_available(self):
        advisor = StrategicAdvisor(FakeLLM())
        assert advisor.is_available

        advisor2 = StrategicAdvisor(None)
        assert not advisor2.is_available

    def test_system_prompt(self):
        """System prompt should contain key instructions."""
        assert "诸葛亮" in ADVISOR_SYSTEM_PROMPT or "军师" in ADVISOR_SYSTEM_PROMPT
        assert "局部情报" in ADVISOR_SYSTEM_PROMPT or "有限" in ADVISOR_SYSTEM_PROMPT
