# Agent Contribution Guide — 三國志略

Short-form guide for AI coding agents (Hermes, Claude Code, etc.) working on this project. See root `CONTRIBUTING.md` for the human version.

## Quick-Start for Agents

```bash
# Install
pip install -e .

# Run tests (must pass before submitting)
pytest tests/ -v

# Play-test dev mode
histrategy --dev
```

## What Goes Where

| Concern | Location |
|---|---|
| LLM integration (prompts, API calls, Game Master) | `histrategy/llm/` |
| Game engine (turn logic, Plan/Command modes) | `histrategy/engine/` |
| State management (WorldState, persistence) | `histrategy/state/` |
| Terminal UI (Rich TUI, dev CLI) | `histrategy/cli/` |
| Historical knowledge (characters, factions, events) | `histrategy/knowledge/data/` |
| Tests | `tests/` |

## Code Conventions

- Python 3.10+, type hints on all public functions
- Google-style docstrings on public API only
- No comments unless the WHY is non-obvious
- Imports: stdlib → third-party → first-party, blank line between groups
- Use `ruff` for linting
- Use `dict[str, int]` not `Dict[str, int]`

## Architecture Constraints

**DO NOT:**
- Write Python string templates for advisor speeches, suggestions, consequences, or NPC actions — those come from the LLM
- Hardcode game data in Python — it lives in `histrategy/knowledge/data/*.json`
- Skip tests — `pytest tests/` must pass before every commit

**DO:**
- Use `WorldState` dataclass for all state, with `to_dict()` / `from_dict()` for persistence
- Keep Plan Mode (council/what-to-do) and Command Mode (execution/how-it-goes) separate
- Reference `schema.json` before editing any data file
- Validate data changes: `python histrategy/knowledge/scripts/validate_data.py`

## Data File Editing

When adding to `histrategy/knowledge/data/`:

1. Read `histrategy/knowledge/data/schema.json` first — it defines required fields, types, and allowed values
2. Use snake_case IDs (e.g. `cao_cao`, `guan_yu`)
3. Ensure cross-file references are consistent: `characters.faction` → `factions.id`, `factions.ruler_id` → `characters.id`, `regions.neighbors` → `regions.id`

## Key Files to Read Before Starting

- `CLAUDE.md` — project context and architecture requirements
- `docs/PRD.md` — product vision
- `docs/tech-design.md` — architecture and data flow
- `histrategy/llm/game_master.py` — LLM-powered Game Master
- `histrategy/state/world_state.py` — state data structures
- `README.md` — overview and quick-start
