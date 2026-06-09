# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

三國志略 (Histrategy) is an AI-powered Three Kingdoms strategy game where the LLM acts as the game engine — generating advisor speeches, strategic suggestions, consequences, and NPC actions based on actual world state. Offline/fallback mode uses a rule-based simulation.

## Commands

```bash
# Install in dev mode
pip install -e .

# Run the game (auto-detects API key, falls back to offline mode)
histrategy
histrategy --dev             # plain-text dev mode
histrategy --dev --faction 2 --new  # skip faction select, force new game

# Run all tests
pytest tests/ -v

# Run a specific test file or class
pytest tests/test_engine.py -v
pytest tests/test_engine.py::TestSimulation -v

# Lint and format (ruff)
ruff check .
ruff format .

# Validate knowledge base JSON data
python histrategy/knowledge/scripts/validate_data.py

# Pre-push hooks (ruff lint+format, then pytest unit tests)
pre-commit run --hook-stage pre-push
```

## Architecture

### Game Flow (Plan/Command two-phase)

```
Plan Mode (LLM)  →  Player decision (free text)  →  Command Mode (LLM)
```

- **Plan Mode** — `GameMaster.generate_plan_mode()` generates advisor court + 4 strategic suggestions from LLM
- **Player** types free-text decision (or `plan` to re-enter plan, `state` to view world, `exit` to quit)
- **Command Mode** — `GameMaster.generate_command_mode()` generates bureaucracy execution, consequences, NPC reactions, updated world state

### Key Layers

| Layer | Key Files | Responsibility |
|-------|-----------|----------------|
| **CLI** | `cli/app.py`, `cli/dev_cli.py` | Rich TUI / plain-text I/O, orchestrates game loop |
| **Engine** | `engine/game.py`, `engine/offline_sim.py` | GameEngine orchestrator, offline fallback simulation |
| **LLM** | `llm/game_master.py`, `llm/adapter.py` | GameMaster (Intro/Plan/Command), multi-provider API client |
| **State** | `state/world_state.py` | `WorldState` dataclass with JSON persistence |
| **Knowledge** | `knowledge/data/*.json` | Characters, factions, regions, events as structured JSON |

### Two Game Engines

- **`GameEngine`** (in `engine/game.py`) — the primary orchestrator. Uses `GameMaster` (LLM) when an API key is available, otherwise falls back to `offline_sim`.
- **`GameWorld`** (in `engine/world.py`) — legacy class used only by `offline_sim`. Not used in LLM mode.

### LLM Integration

- **`GameMaster`** (in `llm/game_master.py`) — current unified implementation with game intro, Plan Mode, and Command Mode. Used by `cli/app.py` and `cli/dev_cli.py`.

### LLM Provider Detection

`LLMAdapter` in `llm/adapter.py` auto-detects the best available provider via a three-path design:

1. **Provider-specific key** — Set ONE of `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `TONGYI_API_KEY`, or `OPENROUTER_API_KEY`. URL and model are auto-configured.
2. **Generic endpoint** — Set `LLM_API_BASE` + `LLM_API_KEY`. Use `LLM_MODEL` to override the model.
3. **No key** → offline (rule-based) mode.

### State Persistence

`WorldState` dataclasses save to `~/.histrategy/` (or `$HISTRATEGY_DATA_DIR`) as JSON. Multiple files track world state, player memory, faction relationships, event history, and character profiles.

### Key Design Rules

- **LLM is the game engine** — advisor speeches, suggestions, consequences, NPC actions come from LLM, not Python templates. Templates only as offline fallback.
- **State is serializable** — `WorldState` with `to_dict()`/`from_dict()` for persistence and LLM context building.
- **Plan/Command separation** — Plan = council meeting (what to do). Command = execution (how it goes).
- **Knowledge lives in JSON** — characters, factions, regions, events are data, not code.
- **Tests use isolated save dirs** — `HISTRATEGY_DATA_DIR` is monkeypatched to `tmp_path` in tests.
- **Rules-as-Data (rules in YAML)** — Formula configuration is externalized in YAML templates, parsed by the rules interpreter (supporting diverse era settings).
- **Asymmetric NPC AI (Fog of War)** — NPCs evaluate threats and plan strategies using projected LocalWorldStates, Heuristics, and LLM Monarch Planners.
- **AI Playtesting** — Automated multi-agent headless simulations verify game balance and tuning statistics.
