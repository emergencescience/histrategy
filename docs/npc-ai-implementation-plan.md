# Integration Plan: Asymmetric NPC AI & Fog of War (FOW) Decision Loop

This plan outlines the integration of asymmetric Fog of War (FOW) and LLM-based planning into the active game loop for NPC factions, bridging the gap between the implemented `NPCPlanner`/`StrategicAdvisor` classes and the deterministic execution engine.

## Context & Architecture Analysis

Our repository has a highly modular and reusable architecture:
1. **Core Logic Reuse**: The core engine code is housed in `histrategy-engine` (numerical simulation, physics, rules, and tactical heuristics) and `histrategy` (LLM-based flow, game master, CLI, server, and web app). The CLI, server, and SDK all import and reuse `GameEngine` to drive the game. The web app is a single-page HTML client that communicates with the server API.
2. **NPC AI & Fog of War Status**:
   - **Fog of War Projection**: We have a working FOW projection mechanism (`LocalWorldStateProjector` in `fog_of_war.py`) that filters global state to create faction-specific `LocalWorldState` views.
   - **Strategic Advisor**: We have a `StrategicAdvisor` class in `histrategy/llm/advisor.py` that can generate natural language advice for human players and structured JSON recommendations/weights for NPCs using LLMs.
   - **NPC Planner**: We have an `NPCPlanner` class in `npc_planner.py` that computes strategic intent based on `LocalWorldState`. However, it currently uses pure Python heuristics as an "LLM placeholder" and is **not wired into the active game loop**.
   - **Omniscient NPCs**: The game loop in `TurnController` currently generates NPC actions using the raw `DecisionEngine`, which has a perfect "god-eye" view of all enemy strengths and resources.

---

## Proposed Changes

### Component 1: Engine Layer (`histrategy-engine`)

We will modify `TurnController` and `NPCPlanner` to construct perceived FOW states and run decisions through the asymmetric FOW planning loop.

#### [MODIFY] [__init__.py](file:///Users/julian/gitbubble/histrategy/histrategy-engine/src/histrategy_engine/turn/__init__.py)
- Update `TurnController.__init__` to accept `npc_planner: NPCPlanner | None = None`.
- In `execute_turn()`, replace the call to `self.decision_engine.generate_commands(fid, world_state, self.map_engine)` with `self.npc_planner.generate_commands_local(fid, world_state, self.map_engine)` for active NPC factions when `self.npc_planner` is present. Fallback gracefully to the raw `decision_engine` if `self.npc_planner` is None.

#### [MODIFY] [npc_planner.py](file:///Users/julian/gitbubble/histrategy/histrategy-engine/src/histrategy_engine/ai/npc_planner.py)
- Update `NPCPlanner.__init__` to accept an optional `advisor` parameter (e.g., `StrategicAdvisor`).
- In `_evaluate_from_local()`, add logic to check if `self._advisor` is present and active. If so, invoke `self._advisor.evaluate_strategy()`, parse its recommendations, and map them to `StrategicIntent`. If the LLM is offline or fails, fallback gracefully to the existing rule-based heuristic.
- In `generate_commands_local()`, instead of passing the global `world_state` to `self._engine.generate_commands(...)`, reconstruct a perceived `WorldState` containing only information visible in `LocalWorldState` (midpoints of border strength ranges, own accurate parameters, and hidden/masked far territories). This ensures that even the tactical heuristics operate under the Fog of War.

---

### Component 2: Game Master Layer (`histrategy`)

We will instantiate the unified advisor and wire it up during engine execution.

#### [MODIFY] [game.py](file:///Users/julian/gitbubble/histrategy/histrategy/engine/game.py)
- Import `NPCPlanner` and `StrategicAdvisor`.
- In `_init_v2()` and `from_dict()` methods, instantiate `self.npc_planner = NPCPlanner(self.decision_engine, advisor=StrategicAdvisor(self.llm) if self.llm else None)`.
- Pass `self.npc_planner` into `TurnController` when initializing it.

---

## Verification Plan

### Automated Tests
- Run tests using the virtual environment:
  ```bash
  ./venv/bin/pytest -v tests/test_advisor.py
  ./venv/bin/pytest -v histrategy-engine/tests/test_npc_planner.py
  ```
- Write a new test suite `tests/test_npc_fow.py` to verify that:
  - NPC factions do not react to hidden/ambushing enemy armies in non-border regions.
  - NPC factions use midpoint estimates when making decisions against border forces.
  - LLM-based `StrategicAdvisor` is invoked and modulates the command generation weights correctly during turn execution.

### Manual Verification
- Run a sandbox simulation run using the CLI:
  ```bash
  histrategy --dev --faction 2 --new
  ```
- Verify in the session logs (`~/.histrategy/logs/simulation_history.jsonl` or console output) that NPC actions reflect their restricted FOW knowledge and strategic personality shifts.
