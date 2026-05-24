# Operations Guide
> 三國志略 (Histrategy) — DevOps & Contributor Operations
> Last updated: 2026-05-24

---

## Local Development Setup

```bash
# Clone
git clone https://github.com/emergencescience/histrategy
cd histrategy

# Install in dev mode
pip install -e ".[dev]"

# Copy env and add your API key
cp .env.example .env
# Edit .env: set DEEPSEEK_API_KEY or OPENAI_API_KEY

# Verify setup
histrategy --dev --faction 1 --new
```

## Running Tests

```bash
# Full test suite (must pass before any PR)
pytest tests/ -v

# With isolated save dir (prevents polluting ~/.histrategy)
HISTRATEGY_DATA_DIR=/tmp/histrategy-test pytest tests/ -v

# Single file
pytest tests/test_e2e.py -v -s

# With coverage
pytest tests/ --cov=histrategy --cov-report=term-missing
```

## Dev Mode (No API Key Needed)

```bash
# Play with offline_sim fallback
histrategy --dev

# Specific faction (1=曹操, 2=刘备, 3=孙坚, 4=袁绍)
histrategy --dev --faction 2 --new

# Export game log after session
histrategy --export-log

# Show token cost estimate (v0.4+)
histrategy --show-cost
```

## LLM Provider Configuration

Set in `.env` or `~/.histrategy/config.json`:

```bash
# DeepSeek (recommended — cheapest)
DEEPSEEK_API_KEY=sk-...

# OpenAI
OPENAI_API_KEY=sk-...

# Alibaba Qwen
DASHSCOPE_API_KEY=sk-...

# OpenRouter (access any model)
OPENROUTER_API_KEY=sk-...
OPENROUTER_MODEL=deepseek/deepseek-v3
```

Adapter auto-selects first available provider. Override model:
```bash
histrategy --model deepseek-v4-pro
```

## Cost Control

```bash
# Check estimated cost before starting
histrategy --estimate-cost

# Use compressed context (40% cheaper, slight accuracy loss)
histrategy --context-mode compressed

# Use offline mode (free)
histrategy --offline
```

Runtime cost reference:
- `full` context: ~$0.007/turn (DeepSeek-V3 with rich context)
- `compressed`: ~$0.001/turn
- Reasoning LLM: ~$0.05/turn (player tolerance ceiling)

---

## Releasing

```bash
# Bump version in pyproject.toml
# Update CHANGELOG.md

# Run full test suite
pytest tests/ -v

# Build
pip install build
python -m build

# Publish to PyPI
twine upload dist/*
```

---

## CI/CD

Pre-commit hooks (`.pre-commit-config.yaml`):
- `ruff` — linting
- `pytest tests/ -x` — fast fail on first error

GitHub Actions (add `.github/workflows/ci.yml`):
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -e ".[dev]"
      - run: HISTRATEGY_DATA_DIR=/tmp/test pytest tests/ -v
```

---

## Game Sense Reports (Developer Feedback)

When you notice the LLM generating anachronistic, inconsistent, or dramatically weak content, open a GitHub issue with label `game-sense`:

```markdown
**Turn**: 8 | **Faction**: 曹操 | **Model**: deepseek-v3
**Decision**: "派使者联合袁绍"
**Observed**: NPC袁绍 reacted as if he already knew about the alliance
**Expected**: 袁绍 should show 好谋无断 hesitation first
**Suggested prompt fix**: Add "NPC must reflect personality traits before agreeing" to COMMAND system prompt
**Log file**: [attach ~/.histrategy/logs/YYYY-MM-DD-caocao.json]
```

These reports feed the prompt improvement pipeline. Future DevOps LLM agents will auto-process `game-sense` issues to improve `game_master.py` system prompts.

---

## Publishing Game Logs

To share your alternate history playthrough:

1. Export: `histrategy --export-log`
2. Find log: `~/.histrategy/logs/YYYY-MM-DD-{faction}.json`
3. (Future) Submit to: `histrategy.emergencescience.com/logs`
4. Or share as a GitHub Gist for community discussion

Log privacy: player IDs are anonymous by default. Opt-in attribution via `config.json`.

---

## Contributing History Facts

See `CONTRIBUTING.md` → "How to Contribute Data".

Quick reference:
```bash
# Edit knowledge files
vim histrategy/knowledge/data/events.json

# Validate schema
python histrategy/knowledge/scripts/validate_data.py

# Test
pytest tests/ -v
```

Arc goals (narrative pacing) live in `histrategy/knowledge/data/arc_goals.json`.

---

## Adding a New Engine Plugin

See `CONTRIBUTING.md` → "How to Contribute a World Engine Plugin".

Minimal example:
```python
# my_engine/engine.py
from histrategy.plugins.interface import WorldEnginePlugin, SimResult
from histrategy.state.world_state import WorldState

class MyCustomEngine(WorldEnginePlugin):
    plugin_id = "my-custom-engine"

    def simulate(self, state: WorldState, action: str) -> SimResult:
        # Your simulation logic here
        ...

    @property
    def requires_llm(self) -> bool:
        return False
```

```toml
# my_engine/pyproject.toml
[project.entry-points."histrategy.plugins"]
my_engine = "my_engine.engine:MyCustomEngine"
```

```bash
pip install -e my_engine/
histrategy --engine my-custom-engine
```

---

## Monitoring (Future)

For self-hosted deployments:
- Log LLM calls with `turn`, `model`, `input_tokens`, `output_tokens`, `cost_usd`
- Alert if cost/session exceeds threshold
- Track `player_deviation` distribution across community logs to tune historical weight
