# Contributing to 三國志略 (Histrategy)

Thank you for contributing! This guide covers everything you need to get started.

---

## Ways to Contribute

| Type | Description | Skill Needed |
|---|---|---|
| [Code](#how-to-contribute-code) | Engine features, bug fixes, new engines | Python |
| [History Data](#how-to-contribute-data) | Characters, events, regions, arc goals | History knowledge |
| [World Engine Plugin](#how-to-contribute-a-world-engine-plugin) | Rome, Red Alert, custom simulation | Python + Game Design |
| [Knowledge Plugin](#how-to-contribute-a-knowledge-plugin) | New historical settings | Python + History |
| [UI Plugin](#how-to-contribute-a-ui-plugin) | Web, Voice, Discord | Frontend/API |
| [Game Logs](#how-to-contribute-game-logs) | Share your alternate history | Playing the game |
| [Game Sense Reports](#how-to-submit-game-sense-reports) | Report LLM quality issues | Playing + observation |

---

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

## How to Contribute/Modify Rules (YAML)

Game mechanics (like food production, taxation, and non-linear historical events) are externalized as YAML specifications in `histrategy-engine/src/histrategy_engine/rules/`.

If you are using an AI agent (such as Claude Code, Trae, etc.) to modify these rules, please instruct the agent to refer to the custom Agent Skill:
- [rule-contribution SKILL.md](histrategy-agent/skills/rule-contribution/SKILL.md)

This skill documents the rule schema, preconditions, math expression syntax, and variable injection.

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
- **Headless core**: The engine never imports UI libraries. `SimResult` is always a plain dataclass.
- **Lazy simulation**: Time only advances on player input. No cron jobs. No background threads.
- **Plugin-first extensibility**: New engines and knowledge bases register via Python entry points. No core changes needed.

---

## How to Contribute a World Engine Plugin

World engine plugins let you replace the simulation engine entirely — for example:
- A Rome-era strategic simulation engine
- A Red Alert Cold War engine
- A full LLM-agent NPC engine (Tier 3)
- A cron-driven engine with push notifications

**Step 1**: Subclass `WorldEnginePlugin` from `histrategy.plugins.interface`:

```python
# my_engine/engine.py
from histrategy.plugins.interface import WorldEnginePlugin
from histrategy.engine.world_sim_interface import SimResult
from histrategy.state.world_state import WorldState

class MyCustomEngine(WorldEnginePlugin):
    plugin_id = "my-custom-engine"
    description = "My custom world simulation engine"

    def simulate(self, state: WorldState, action: str) -> SimResult:
        # Your simulation logic here
        return SimResult(
            narrative="...",
            aftermath="...",
            world_state=state,
            engine_id=self.plugin_id,
        )

    @property
    def requires_llm(self) -> bool:
        return False
```

**Step 2**: Register in `pyproject.toml`:

```toml
[project.entry-points."histrategy.plugins"]
my_engine = "my_engine.engine:MyCustomEngine"
```

**Step 3**: Install and test:

```bash
pip install -e my_engine/
histrategy --dev  # engine is auto-discovered
pytest tests/plugins/ -v
```

**Step 4**: Open a PR or publish to PyPI as `histrategy-my-engine`.

> Note: When multiple WorldEnginePlugin implementations exist, they may move to a separate repo: `github.com/emergencescience/histrategy-world`.

---

## How to Contribute a Knowledge Plugin

Knowledge plugins provide alternate historical settings (Rome, WWII, other Three Kingdoms eras, custom scenarios).

**Step 1**: Subclass `KnowledgePlugin`:

```python
from histrategy.plugins.interface import KnowledgePlugin

class RomeKnowledgePlugin(KnowledgePlugin):
    plugin_id = "rome-knowledge"

    def get_characters(self) -> list[dict]:
        # Return list matching characters.json schema
        ...

    def get_factions(self) -> list[dict]: ...
    def get_regions(self) -> list[dict]: ...
    def get_events(self) -> list[dict]: ...
```

**Step 2**: Register and validate:

```bash
python histrategy/knowledge/scripts/validate_data.py --plugin rome-knowledge
```

> Note: When multiple KnowledgePlugin implementations exist, they may move to: `github.com/emergencescience/histrategy-history`.

---

## How to Contribute a UI Plugin

UI plugins decorate the headless engine with a rendering layer (Web, Voice, Discord, etc.).

```python
from histrategy.plugins.interface import UIPlugin
from histrategy.engine.world_sim_interface import SimResult

class DiscordUIPlugin(UIPlugin):
    plugin_id = "discord-ui"

    def render(self, sim_result: SimResult) -> None:
        # Send SimResult content to Discord channel
        ...

    def get_player_input(self, prompt: str) -> str:
        # Wait for Discord message and return it
        ...
```

---

## How to Contribute Game Logs

Sharing your game logs helps the project in three ways:
1. Dataset for LLM narrative quality research
2. Community alternate history gallery
3. Edge cases and prompt failures for developers to fix

**Export your log**:
```bash
histrategy --export-log
# Saved to: ~/.histrategy/logs/YYYY-MM-DD-{faction}.json
```

**Share options**:
- Post as a GitHub Gist and link in [Discussions](https://github.com/emergencescience/histrategy/discussions)
- (Future) Submit to the community log gallery at `histrategy.emergencescience.com/logs`

Log files are anonymous by default. Your player ID is `"anonymous"` unless you opt in with attribution in `~/.histrategy/config.json`.

---

## How to Submit Game Sense Reports

If you notice the LLM generating anachronistic, inconsistent, or dramatically weak content, open an issue with label **`game-sense`**:

```markdown
**Turn**: 8 | **Faction**: 曹操 | **Model**: deepseek-v3
**Decision**: "派使者联合袁绍"
**Observed**: 袁绍 immediately agreed without showing 好谋无断 hesitation
**Expected**: 袁绍 should deliberate for at least one NPC reaction before responding
**Suggested prompt fix**: Add "NPC must reflect personality traits before major decisions" to COMMAND prompt
**Log file**: [attach ~/.histrategy/logs/YYYY-MM-DD-caocao.json]
```

Game sense reports are the training signal for future DevOps LLM agents to auto-improve the system prompts in `game_master.py`.

---

## Need Help?

- Found a bug? [Open an issue](https://github.com/emergencescience/histrategy/issues)
- Have an idea? Start a [discussion](https://github.com/emergencescience/histrategy/discussions)
- Read [ROADMAP](docs/ROADMAP.md), [PRD](docs/PRD.md), and [Tech Design](docs/tech-design.md)
- Read [Design Iterations](docs/design-iterations.md) for the philosophy evolution
- Read [Operations Guide](docs/OPERATIONS.md) for DevOps workflows
