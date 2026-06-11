---
name: rule-contribution
description: "三國志略 — 指引 AI 代理 (如 Claude Code, Trae 等) 与开发者贡献/修改游戏 YAML 规则规范。"
version: 1.0.0
author: Emergence Science
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [rules, yaml, modding, simulation, physics-engine]
    category: configuration
---

# Game Rules Contribution Guide — 三國志略

Use this skill to guide AI agents and external contributors on how to define, configure, and modify game simulation rules and historical event parameters in the `histrategy-engine` module.

## YAML Configuration Structure

All core game simulation rules are modularized as YAML specifications located under:
[histrategy-engine/src/histrategy_engine/rules/](histrategy-engine/src/histrategy_engine/rules/)

### 1. General Game Rules (e.g., `economy.yaml`)
These rules define deterministic updates (e.g., food production, tax rates, military upkeep).
Each rule must define constants and formulas.

Example:
```yaml
food_production:
  constants:
    base_yield: 1.2
    population_factor: 0.05
  formula: "base_yield * economy + population * population_factor * season_multiplier"
```

### 2. Historical/Non-linear Event Rules (e.g., `historical_events.yaml`)
These rules govern non-linear events triggered by physical thresholds, random chance, or historical narrative drift.

Fields:
- `preconditions` (str): Python-evaluable expression evaluating to a boolean.
- `probability_formula` (str): Python-evaluable math formula producing a float probability ($0.0 \le p \le 1.0$).
- `base_gravity` (float): The default likelihood or weights of this event when preconditions are met.
- `desc` (str): Narrative description of the event.

Example:
```yaml
caocao_captures_xinye:
  preconditions: "cao_strength > 2.0 * liubei_strength and xinye_owner == 'shu' and xinye_garrison < 5000"
  probability_formula: "0.85 * (1.0 - player_deviation * 0.5)"
  base_gravity: 0.8
  desc: "曹军大军压境新野，刘备守军不支，城池陷落"
```

---

## Expression Syntax and Allowed Functions

The `RuleInterpreter` evaluates YAML formulas inside a restricted sandbox environment. Only mathematical functions and specific local variables are supported.

### Supported Functions
The following mathematical functions from Python's standard `math` module are imported:
- `min(a, b)`
- `max(a, b)`
- `abs(x)`
- `round(x, n)`
- `pow(x, y)`

### Dynamic Variable Injection

At runtime, the engine injects variables into the interpreter context depending on the rule context.

For general economy/territory rules:
- `economy`: Current territory development/economy score.
- `population`: Current population in the territory.
- `morale`: Faction morale.
- `season_multiplier`: A multiplier based on the current season (e.g., Summer = 1.0, Winter = 0.05).

For historical event triggers (e.g., `historical_events.yaml` checks):
- `{faction}_strength` (e.g., `cao_strength`, `liubei_strength`): Total army strength of the faction.
- `{territory}_owner` (e.g., `xinye_owner`): Faction ID owning the territory.
- `{territory}_garrison` (e.g., `xinye_garrison`): Number of defensive troops stationed.
- `player_deviation`: Current history deviation factor ($0.0 \le d \le 1.0$).
- `{event}_won` or `{state}_active` (e.g., `sunliu_alliance`): Boolean flags representing game milestones.

---

## Procedure for Contributing New Rules

### 1. File Changes
- Add/modify the YAML specification in `histrategy-engine/src/histrategy_engine/rules/`.
- Ensure preconditions or formulas only reference variables that are projected or computed in `histrategy_engine/rules/interpreter.py`.

### 2. Validation
- Run validation tests on the rule interpreter to catch python parsing or syntax errors:
  ```bash
  ./venv/bin/pytest histrategy-engine/tests/test_rules_interpreter.py
  ```

### 3. Verification of Logging
- Run a turn or test room session.
- Check the rule execution log located in the active session's room directory under `logs/rules_execution.log` to verify that your formula was interpreted correctly and produced the expected numeric outputs.
