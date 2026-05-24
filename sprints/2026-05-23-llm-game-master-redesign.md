# LLM Game Master Redesign — Architecture Summary

**Date:** 2026-05-24
**Branch:** main

## Problem

The game engine used Python string templates instead of LLM-generated content:
- `histrategy/engine/advisors.py` — hardcoded advisor speeches with `.format()` templates
- `histrategy/engine/command.py` — hardcoded bureaucracy simulation with `random.choice()`
- Advisor voices were pre-written, suggestions were picked from lists, consequences were formulaic

## Solution

The LLM is now the **game engine** — all game content is generated at runtime.

### New Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Game Loop                          │
│                                                      │
│  Plan Mode ──→ Player Input ──→ Command Mode ──→    │
│  (LLM)         (free text)      (LLM)               │
│      ↑                                       │       │
│      └───────────────────────────────────────┘       │
│                  (repeat each turn)                   │
└─────────────────────────────────────────────────────┘
```

### New File: `histrategy/llm/game_master.py`

**GameMaster** class with two modes:

1. **`generate_plan_mode(world_state)`** — Council meeting
   - LLM receives full world state (faction stats, territories, history, NPC states)
   - Returns: advisor speeches (per advisor: name, title, temperament, speech), 4 strategic suggestions, season summary
   - System prompt instructs LLM to roleplay as each advisor with appropriate personality

2. **`generate_command_mode(world_state, player_decision)`** — Execution
   - LLM receives world state + player's free-text decision
   - Returns: bureaucracy execution report, short-term state changes, long-term seeds, NPC reactions, updated faction states, aftermath summary
   - System prompt enforces causality — every consequence must relate to the specific decision

### Updated File: `histrategy/cli/dev_cli.py`

- Imports `GameMaster` from `histrategy.llm.game_master` instead of `generate_plan_mode` from `histrategy.engine.advisors`
- Clean Plan → Decision → Command flow
- Type `plan` to re-enter Plan Mode
- Type `state` to view world state
- Type `exit` to quit
- Offline fallback: when no API key, uses `engine.process_turn()` with `offline_sim`

### Deleted Files

- `histrategy/engine/advisors.py` — 379 lines of hardcoded templates
- `histrategy/engine/command.py` — 306 lines of hardcoded simulation

### Preserved Files

- `histrategy/engine/offline_sim.py` — retained as offline fallback when no API key
- `histrategy/llm/world_model.py` — retained (still used by engine.game GameEngine for intro generation)
- `histrategy/state/world_state.py` — unchanged (still the single source of truth for game state)
- `histrategy/llm/adapter.py` — unchanged (multi-provider LLM adapter)

## Key Design Decisions

1. **Two-phase per turn** — Plan (council) and Command (execution) are separate LLM calls with different system prompts. This gives the player space to think between hearing advice and making a decision.

2. **Free-text input only** — No numbered menu choices. The player types their decision in natural language. The LLM interprets intent and generates appropriate consequences.

3. **Full world state in prompt** — Every LLM call receives the complete current world state, ensuring consequences and advisor advice are grounded in actual game data.

4. **No templates for game content** — All advisor speeches, suggestions, narratives, and consequences come from the LLM. The only fallback strings are minimal error messages (displayed when API fails).

5. **Offline fallback preserved** — When no API key is configured, the game still functions using `offline_sim.py`. This ensures the game is always playable.

## System Prompts

Two specialized system prompts in `game_master.py`:

- `GAMEMASTER_PLAN_SYSTEM` — instructs LLM to generate a council meeting with character-appropriate advisor speeches and strategic suggestions based on current world state
- `GAMEMASTER_COMMAND_SYSTEM` — instructs LLM to process the player's decision through bureaucracy, compute consequences with proper causality, and update world state
