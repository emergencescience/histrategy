# CLAUDE.md for 三國志略 (histrategy)

## Critical Project Context

This is an AI-powered Three Kingdoms strategy game. The user is frustrated because:
1. The game engine uses Python string templates instead of LLM-generated content
2. Advisors, suggestions, consequences, and NPC actions are all hardcoded Python templates
3. The user wants the LLM to be the GAME ENGINE, not just a narrator over pre-computed results

## Architecture Requirements

### MUST: LLM-Driven (not template-driven)
- All advisor speeches come from LLM, not from Python f-strings
- All suggestions are LLM-generated based on actual game state
- All consequences are LLM-generated based on player input
- ALL NPC actions come from LLM
- Templates ONLY as fallback when no API key is available (offline mode)

### Plan/Command Mode Design
- `state = "plan"` → LLM generates advisor court (council meeting)
  - Each advisor gives their opinion (from LLM, based on world state)
  - 4 strategic suggestions (from LLM)
  - Player types their decision (free text)
- `state = "command"` → LLM generates execution results
  - Bureaucracy execution narrative
  - Short-term consequences (state changes)
  - Long-term seeds
  - Updated world state
- Player can explicitly switch: type "plan" to re-enter plan mode

### Key Files to Read
- histrategy/llm/adapter.py — LLM adapter (multi-provider)
- histrategy/state/world_state.py — World state data structures
- histrategy/llm/world_model.py — Current (broken) world model
- histrategy/engine/game.py — Game engine
- histrategy/cli/dev_cli.py — Dev mode CLI

### What to Remove
- histrategy/engine/advisors.py — DELETE entirely (hardcoded templates)
- histrategy/engine/command.py — DELETE entirely (hardcoded templates)
- histrategy/engine/offline_sim.py — REDUCE to offline fallback only
- All `_generate_*`, `_format_*`, `_compute_*` template functions

### What to Build
- histrategy/llm/game_master.py — LLM-powered game master
  - generate_plan_mode(state) → advisors, suggestions
  - generate_command_mode(state, decision) → narrative, consequences, seeds
  - generate_npc_moves(state) → NPC actions
- Clean separation: Plan mode (council) → player decision → Command mode (execution)
