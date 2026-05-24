# Contributing to 三國志略 (Histrategy)

Thank you for contributing! This guide covers everything you need to get started.

## How to Contribute Code

1. **Fork** the [repo](https://github.com/emergencescience/histrategy)
2. **Create a branch** from `main`: `git checkout -b feature/your-feature`
3. **Install in dev mode**: `pip install -e .`
4. **Write your changes**, following the conventions below
5. **Self-test** (see [Self-Testing](#self-testing))
6. **Open a PR** against `main` with a clear description

We use squash-merges. Your branch will be squashed into a single commit on `main`.

## How to Contribute Data

The game's knowledge base lives in `histrategy/knowledge/data/`. You can contribute:

- **New characters** — add to `characters.json`
- **New factions** — add to `factions.json`
- **New regions** — add to `regions.json`
- **New historical events** — add to `events.json`
- **New scenarios** — create a `data/<year>/` directory (e.g. `data/208/` for Red Cliffs)

### Schema Reference

All data files follow the schemas defined in [`histrategy/knowledge/data/schema.json`](histrategy/knowledge/data/schema.json). Read that file before making changes. Key requirements:

| Data File | Required Fields |
|---|---|
| `characters.json` | `id`, `name`, `alias`, `title`, `faction`, `personality`, `skills`, `description` |
| `factions.json` | `id`, `name`, `ruler_id`, `color`, `description`, `capital`, `starting_territories`, `strength`, `economy`, `morale`, `intel_level`, `aggression`, `diplomacy_tendency` |
| `regions.json` | `id`, `name`, `capital`, `description`, `strategic_value`, `resources`, `neighbors` |
| `events.json` | `year`, `season`, `title`, `description`, `trigger`, `effects`, `is_historical` |

### ID Naming Convention

- Use **snake_case** for all IDs (e.g. `cao_cao`, `liu_biao`, `guan_yu`)
- No spaces, no special characters
- Cross-reference consistency: character `faction` must match a faction `id`; faction `ruler_id` must match a character `id`

### Validation

After editing data files, run the validation script:

```bash
python histrategy/knowledge/scripts/validate_data.py
```

Fix any errors before submitting.

## Self-Testing

```bash
# Install in dev mode
pip install -e .

# Run the full test suite
pytest tests/ -v

# Run a specific test file
pytest tests/test_engine.py -v

# Play-test in dev mode (plain-text I/O, no API key needed)
histrategy --dev

# Force a new game with a specific faction
histrategy --dev --faction 2 --new
```

All code changes must pass the full test suite before review.

## Code Style

- **Linter**: ruff (`pip install ruff`)
- **Type hints**: Use Python type annotations on all public functions and methods
- **Docstrings**: Google-style docstrings on public API (classes, public methods). Internal helpers don't need them.
- **No comments by default**: Code should be self-documenting. Only comment non-obvious constraints, workarounds, or invariants.
- **Python 3.10+** — no f-strings older than this, use `dict[str, ...]` not `Dict[str, ...]`
- **Imports**: stdlib first, then third-party, then first-party, separated by blank lines

## Project Structure

```
histrategy/
├── engine/                  # Game engine
│   ├── game.py              # Game orchestrator
│   ├── world.py             # Legacy GameWorld (offline mode)
│   ├── advisors.py          # Plan Mode: advisor speeches + suggestions
│   ├── command.py           # Command Mode: bureaucracy execution + seeds
│   └── offline_sim.py       # Rule-based simulation fallback
├── llm/                     # LLM integration layer
│   ├── game_master.py       # LLM-powered Game Master
│   ├── world_model.py       # LLM world model
│   ├── adapter.py           # Multi-provider API client
│   └── prompts.py           # System prompts
├── state/                   # Game state
│   └── world_state.py       # Structured world state (JSON persistence)
├── cli/                     # Terminal interface
│   ├── app.py               # Rich TUI
│   └── dev_cli.py           # Plain-text dev mode (--dev)
├── knowledge/               # Historical knowledge base
│   ├── data/                # Structured game data (JSON)
│   │   ├── schema.json      # JSON Schema definitions
│   │   ├── characters.json  # Historical figures
│   │   ├── factions.json    # Playable factions
│   │   ├── regions.json     # Provinces with geography
│   │   └── events.json      # Historical event timeline
│   └── scripts/             # Data tools
│       └── validate_data.py # Schema validator
├── docs/                    # Design documents
│   ├── PRD.md               # Product Requirements
│   └── tech-design.md       # Technical design
└── tests/                   # Test suite
    ├── test_engine.py       # Engine unit tests
    └── test_e2e.py          # End-to-end tests
```

## Architecture Design Rules

- **LLM as Game Master**: The LLM drives narrative, consequences, and NPC actions — not Python string templates. Templates are offline fallback only.
- **Plan/Command separation**: Plan Mode = council meeting (what to do). Command Mode = execution (how it goes).
- **Data lives in JSON**: Characters, factions, regions, and events are structured data, not hardcoded in Python.
- **State is serializable**: Use `WorldState` dataclasses with `to_dict()` / `from_dict()` for persistence.

## Need Help?

- Found a bug? [Open an issue](https://github.com/emergencescience/histrategy/issues)
- Have an idea? Start a [discussion](https://github.com/emergencescience/histrategy/discussions)
- Read [PRD](docs/PRD.md) and [Tech Design](docs/tech-design.md) for product/architecture context
