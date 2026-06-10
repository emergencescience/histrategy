"""Tests for RuleInterpreter — YAML-based formula engine."""

import math
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the engine package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from histrategy_engine.rules.interpreter import RuleInterpreter


@pytest.fixture
def temp_rules_dir():
    """Create a temporary rules directory with a test YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        economy_path = Path(tmpdir) / "economy.yaml"
        economy_path.write_text("""\
food_consumption:
  civilian_formula: "population * civilian_per_capita"
  troop_formula: "troops * troop_per_capita * supply_multiplier"
  constants:
    civilian_per_capita: 0.02
    troop_per_capita: 0.5
population_growth:
  surplus_threshold_high: 1.2
  surplus_threshold_low: 1.0
  rate_healthy: 0.015
  rate_slow: 0.005
  rate_shortage: -0.01
  rate_famine: -0.03
  formula: "population * rate * (1 + morale/100) * (1 + development/200)"
tax:
  revenue_formula: "population * tax_rate * tax_base_multiplier * gov_mod"
  moral_thresholds:
    - threshold: 0.2
      penalty: 0
    - threshold: 0.3
      penalty: -1
    - threshold: 0.4
      penalty: -2
    - threshold: 999.0
      penalty: -3
  constants:
    tax_base_multiplier: 0.05
development:
  cost_formula: "150 * delta * sqrt(population/1000)"
  constants:
    minimum_cost: 300
modifiers:
  governor_politics: "1 + politics/200"
  tech_agriculture: "1 + agriculture_level * 0.1"
""")
        yield tmpdir


class TestRuleInterpreter:
    """Tests for RuleInterpreter class."""

    def test_load_rules(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        assert "food_consumption" in interp.rules
        assert "population_growth" in interp.rules
        assert "tax" in interp.rules
        assert "development" in interp.rules

    def test_get_constant(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        assert interp.get_constant("food_consumption.constants.civilian_per_capita") == 0.02
        assert interp.get_constant("food_consumption.constants.troop_per_capita") == 0.5
        assert interp.get_constant("tax.constants.tax_base_multiplier") == 0.05
        assert interp.get_constant("development.constants.minimum_cost") == 300

    def test_get_constant_missing(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        with pytest.raises(KeyError):
            interp.get_constant("nonexistent.key")

    def test_evaluate_civilian_food(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "food_consumption.civilian_formula",
            {
                "population": 100000,
                "civilian_per_capita": 0.02,
            },
        )
        assert result == 2000.0  # 100000 * 0.02

    def test_evaluate_troop_food(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "food_consumption.troop_formula",
            {
                "troops": 5000,
                "troop_per_capita": 0.5,
                "supply_multiplier": 1.0,
            },
        )
        assert result == 2500.0  # 5000 * 0.5 * 1.0

    def test_evaluate_troop_food_winter(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "food_consumption.troop_formula",
            {
                "troops": 10000,
                "troop_per_capita": 0.5,
                "supply_multiplier": 2.0,
            },
        )
        assert result == 10000.0  # 10000 * 0.5 * 2.0

    def test_evaluate_tax_revenue(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "tax.revenue_formula",
            {
                "population": 100000,
                "tax_rate": 0.3,
                "tax_base_multiplier": 0.05,
                "gov_mod": 1.0,
            },
        )
        assert result == 1500.0  # 100000 * 0.3 * 0.05 * 1.0

    def test_evaluate_development_cost(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "development.cost_formula",
            {
                "delta": 3,
                "population": 10000,
            },
        )
        # 150 * 3 * sqrt(10000/1000) = 150 * 3 * sqrt(10) ≈ 1423.02
        expected = 150 * 3 * math.sqrt(10)
        assert abs(result - expected) < 0.01

    def test_evaluate_population_growth(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        rate = interp.get_constant("population_growth.rate_healthy")
        result = interp.evaluate(
            "population_growth.formula",
            {
                "population": 100000,
                "rate": rate,
                "morale": 70,
                "development": 50,
            },
        )
        # 100000 * 0.015 * (1 + 70/100) * (1 + 50/200)
        # = 100000 * 0.015 * 1.7 * 1.25 = 3187.5
        expected = 100000 * 0.015 * 1.7 * 1.25
        assert abs(result - expected) < 0.01

    def test_missing_formula(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        with pytest.raises(KeyError):
            interp.evaluate("nonexistent.formula", {})

    def test_safety_no_import(self, temp_rules_dir):
        """Test that dangerous Python code cannot execute."""
        interp = RuleInterpreter(temp_rules_dir)
        # __import__ should not work
        with pytest.raises((ValueError, NameError)):
            interp.evaluate(
                "food_consumption.troop_formula",
                {
                    "troops": "__import__('os').system('ls')",
                    "troop_per_capita": 0.5,
                    "supply_multiplier": 1.0,
                },
            )

    def test_safety_sqrt_works(self, temp_rules_dir):
        """Test that allowed functions work."""
        interp = RuleInterpreter(temp_rules_dir)
        result = interp.evaluate(
            "development.cost_formula",
            {
                "delta": 1,
                "population": 16000,
            },
        )
        # 150 * 1 * sqrt(16) = 150 * 4 = 600
        assert result == 600.0

    def test_get_thresholds(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)
        thresholds = interp.get_thresholds("tax.moral_thresholds")
        assert isinstance(thresholds, list)
        assert len(thresholds) == 4
        assert thresholds[0] == {"threshold": 0.2, "penalty": 0}
        assert thresholds[2] == {"threshold": 0.4, "penalty": -2}


class TestBackwardCompatibility:
    """Verify that new interpreter-based formulas match old hardcoded values."""

    def test_food_consumption_matches_old(self, temp_rules_dir):
        """New YAML-based formula must match old hardcoded formula."""
        interp = RuleInterpreter(temp_rules_dir)

        # Old formula: population * 0.02 + troops * 0.5 * supply_multiplier
        def old_formula(pop, troops, supply):
            return int(pop * 0.02 + troops * 0.5 * supply)

        def new_formula(pop, troops, supply):
            civ = interp.evaluate(
                "food_consumption.civilian_formula",
                {
                    "population": pop,
                    "civilian_per_capita": interp.get_constant(
                        "food_consumption.constants.civilian_per_capita"
                    ),
                },
            )
            troop = interp.evaluate(
                "food_consumption.troop_formula",
                {
                    "troops": troops,
                    "troop_per_capita": interp.get_constant(
                        "food_consumption.constants.troop_per_capita"
                    ),
                    "supply_multiplier": supply,
                },
            )
            return int(civ + troop)

        test_cases = [
            (100000, 0, 1.0),
            (100000, 5000, 1.0),
            (50000, 10000, 2.0),
            (200000, 0, 1.0),
            (0, 15000, 1.0),
        ]
        for pop, troops, supply in test_cases:
            assert new_formula(pop, troops, supply) == old_formula(pop, troops, supply), (
                f"Mismatch: pop={pop}, troops={troops}, supply={supply}"
            )

    def test_tax_revenue_matches_old(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)

        def old_formula(pop, rate, gov_pol):
            return int(pop * rate * 0.05 * (1.0 + gov_pol / 200.0))

        def new_formula(pop, rate, gov_pol):
            return int(
                interp.evaluate(
                    "tax.revenue_formula",
                    {
                        "population": pop,
                        "tax_rate": rate,
                        "tax_base_multiplier": interp.get_constant(
                            "tax.constants.tax_base_multiplier"
                        ),
                        "gov_mod": 1.0 + gov_pol / 200.0,
                    },
                )
            )

        test_cases = [
            (100000, 0.3, 0),
            (50000, 0.2, 50),
            (200000, 0.4, 0),
        ]
        for pop, rate, gov_pol in test_cases:
            assert new_formula(pop, rate, gov_pol) == old_formula(pop, rate, gov_pol), (
                f"Mismatch: pop={pop}, rate={rate}, gov_pol={gov_pol}"
            )

    def test_development_cost_matches_old(self, temp_rules_dir):
        interp = RuleInterpreter(temp_rules_dir)

        def old_formula(pop, delta):
            return max(300, int(150 * delta * math.sqrt(pop / 1000.0)))

        def new_formula(pop, delta):
            cost = interp.evaluate(
                "development.cost_formula",
                {
                    "delta": delta,
                    "population": pop,
                },
            )
            minimum = interp.get_constant("development.constants.minimum_cost")
            return max(minimum, int(cost))

        test_cases = [
            (10000, 3),
            (50000, 5),
            (1000, 1),  # small city → tests minimum cost
            (200000, 10),
        ]
        for pop, delta in test_cases:
            assert new_formula(pop, delta) == old_formula(pop, delta), (
                f"Mismatch: pop={pop}, delta={delta}"
            )
