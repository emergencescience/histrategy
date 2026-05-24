# SKILL.md — Agent Instructions for 三國志略

Instructions for AI coding agents (Claude Code, Hermes, Cursor, etc.) contributing to this project.

## Project Identity

**三國志略 (Histrategy)** — An open-source, AI-powered text-based Three Kingdoms strategy game. The LLM is the game engine, not a narrator over pre-computed results.

## Agent Workflow

### Before Writing Code

1. Read `CLAUDE.md` for critical architecture context and current priorities
2. Read `docs/PRD.md` and `docs/tech-design.md` for product vision and architecture
3. Understand the Plan/Command two-tier architecture before touching engine code
4. Check `histrategy/knowledge/data/schema.json` before editing any JSON data file

### While Writing Code

- **Test-first**: Write or update tests alongside code changes
- **LLM-first**: All advisor speeches, suggestions, consequences, and NPC actions come from the LLM layer — never write Python string templates for game content
- **State-first**: Use `WorldState` dataclasses. All state is serializable via `to_dict()` / `from_dict()`
- **Minimal changes**: Don't refactor or add abstractions beyond what the task requires. No half-finished implementations.

### Before Submitting

```bash
# 1. Run full test suite
pytest tests/ -v

# 2. Validate knowledge base (if data files changed)
python histrategy/knowledge/scripts/validate_data.py

# 3. Smoke test dev mode
histrategy --dev --new
```

## What to Avoid

- **DO NOT** write hardcoded template functions (`_generate_*`, `_format_*`, `_compute_*`) for game narrative
- **DO NOT** add comments explaining what code does — well-named identifiers do that
- **DO NOT** add error handling for scenarios that can't happen — trust internal code and framework guarantees
- **DO NOT** create documentation files unless explicitly requested
- **DO NOT** use backwards-compatibility shims or keep unused code — delete it

## Project Layout (Quick Reference)

```
histrategy/engine/       # Game engine (game.py, advisors.py, command.py)
histrategy/llm/          # LLM layer (game_master.py, adapter.py, prompts.py)
histrategy/state/        # Game state (world_state.py)
histrategy/cli/          # Terminal UI (app.py for Rich TUI, dev_cli.py for --dev)
histrategy/knowledge/    # Historical data (data/*.json, scripts/validate_data.py)
docs/                    # Design docs (PRD.md, tech-design.md)
tests/                   # Pytest suite (test_engine.py, test_e2e.py)
```

## Module Purposes

| Module | Purpose |
|---|---|
| `engine/game.py` | Game orchestrator — turn loop, Plan/Command mode dispatch |
| `engine/advisors.py` | Plan Mode: advisor generation, 4 strategic suggestions |
| `engine/command.py` | Command Mode: bureaucracy execution, seed system |
| `engine/offline_sim.py` | Rule-based fallback when no LLM API key |
| `llm/game_master.py` | LLM-powered Game Master — generates plan mode, command mode, NPC moves |
| `llm/adapter.py` | Multi-provider LLM client (DeepSeek, OpenAI, Tongyi, OpenRouter) |
| `llm/prompts.py` | System prompt templates for LLM calls |
| `state/world_state.py` | `WorldState` / `FactionState` dataclasses with JSON persistence |
| `cli/app.py` | Rich terminal UI (colors, panels, layout) |
| `cli/dev_cli.py` | Plain-text dev mode for testing (--dev flag) |

## Commit Style

Follow the existing commit convention: short Chinese + English prefix describing the change (e.g. `H24a: Rich TUI refactor — unified LLM GameMaster display`). Commits are co-authored with the AI agent that produced them.
