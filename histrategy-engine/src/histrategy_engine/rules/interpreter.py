"""RuleInterpreter — safe formula evaluation from YAML rule configs.

All formulas are loaded from YAML files and evaluated with restricted
globals to prevent arbitrary code execution. Only basic math operations
and a small set of allowed functions are available.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

# Allowed functions in formula evaluation
_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
}

# Safe globals: __builtins__ is empty to prevent imports and dangerous ops
_SAFE_GLOBALS = {"__builtins__": {}}
_SAFE_GLOBALS.update(_ALLOWED_FUNCTIONS)


import logging

_logger = logging.getLogger("histrategy_engine.rules")


def _resolve_dotted_key(data: dict, key_path: str):
    """Resolve a dotted key path like 'food_consumption.constants.civilian_per_capita'."""
    parts = key_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(key_path)
    return current


class RuleInterpreter:
    """Safe evaluator for YAML-defined game formulas.

    Loads rules from YAML files in a directory and evaluates
    string expressions with injected variables.
    """

    def __init__(self, rules_dir: str | None = None):
        """Load all YAML rules from the given directory.

        Args:
            rules_dir: Path to the rules directory. Defaults to
                the 'rules/' directory adjacent to this module.
        """
        if rules_dir is None:
            rules_dir = str(Path(__file__).parent)
        self._rules: dict = {}
        self._rules_dir = Path(rules_dir)

        for yaml_file in sorted(self._rules_dir.glob("*.yaml")):
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    self._rules.update(data)

    @property
    def rules(self) -> dict:
        """Access the loaded rules dict (for debugging)."""
        return self._rules

    def get_constant(self, key_path: str, default=None):
        """Retrieve a constant value by dotted key path.

        Example:
            interpreter.get_constant("food_consumption.constants.civilian_per_capita")
            → 0.02
        """
        try:
            return _resolve_dotted_key(self._rules, key_path)
        except (KeyError, TypeError, IndexError):
            if default is not None:
                return default
            raise KeyError(f"Constant not found: {key_path}")

    def evaluate(self, formula_key: str, variables: dict | None = None) -> float:
        """Evaluate a named formula with injected variables.

        Args:
            formula_key: Dotted path to the formula, e.g.
                "food_consumption.civilian_formula"
            variables: Dict of variable name → value for substitution

        Returns:
            The evaluated result as a float.

        Raises:
            KeyError: If the formula key is not found.
            ValueError: If the formula fails to evaluate safely.
        """
        try:
            formula_str = _resolve_dotted_key(self._rules, formula_key)
        except (KeyError, TypeError):
            raise KeyError(f"Formula not found: {formula_key}")

        if not isinstance(formula_str, str):
            return float(formula_str)

        # Inject variables into safe eval context
        local_vars = dict(_SAFE_GLOBALS)
        if variables:
            local_vars.update(variables)

        try:
            result = eval(formula_str, {"__builtins__": {}}, local_vars)
            _logger.info(
                "Evaluated rule: %s | Formula: %s | Vars: %s | Result: %f",
                formula_key,
                formula_str,
                variables,
                float(result),
            )
        except Exception as e:
            raise ValueError(
                f"Failed to evaluate formula '{formula_key}': {e}\n"
                f"  Formula: {formula_str}\n"
                f"  Variables: {variables}"
            ) from e

        return float(result)

    def get_thresholds(self, key_path: str) -> list[dict] | None:
        """Retrieve threshold list (e.g., tax morale thresholds)."""
        try:
            return _resolve_dotted_key(self._rules, key_path)
        except (KeyError, TypeError, IndexError):
            return None
