# histrategy-sdk

Python SDK for [三國志略 (Histrategy)](https://emergence.science/play/histrategy) — AI-powered Three Kingdoms strategy game.

```bash
pip install histrategy-sdk
```

## Quick Start

### Server Client (HTTP)

```python
from histrategy_sdk import ServerClient

client = ServerClient()

# Create a new game as Shu Han (刘备)
game = client.create_game(faction="shu")
print(game["narrative"])
# → "建安十二年冬，刘备屯兵新野，寄居刘表麾下..."

# Get strategic suggestions
plan = client.get_plan(game["game_id"])
for s in plan["suggestions"]:
    print(f"  • {s}")

# Execute a command
result = client.execute_command(game["game_id"], "联吴抗曹，攻打襄阳")
print(result["narrative"])
print(f"Token usage: {result['token_usage']}")
```

### Direct Engine (In-Process)

```bash
pip install histrategy-sdk[engine]
```

```python
from histrategy_sdk import DirectEngine

engine = DirectEngine(faction="cao")  # Play as 曹操
intro = engine.get_intro()
result = engine.execute("南征刘备，先取新野")

# Save game state
save = engine.to_dict()

# Restore later
engine2 = DirectEngine.from_dict(save)
```

## API Reference

### `ServerClient`

| Method | Description |
|--------|-------------|
| `create_game(faction, scenario)` | Create new game → `GameIntro` |
| `get_plan(game_id)` | Get advisor suggestions → `PlanData` |
| `execute_command(game_id, decision)` | Process turn → `TurnResult` |
| `get_status(game_id)` | Get faction resources → `FactionStatus` |
| `restore_game(world_state)` | Restore from save → `RestoreResult` |
| `health()` | Check server status |

### `DirectEngine`

| Method | Description |
|--------|-------------|
| `DirectEngine(faction, llm_api_key)` | Create new in-process engine |
| `get_intro()` | Get intro scene → `GameIntro` |
| `get_plan()` | Get suggestions → `PlanData` |
| `execute(decision)` | Process turn → `TurnResult` |
| `get_status()` | Get faction status → `FactionStatus` |
| `to_dict()` | Serialize game state |
| `DirectEngine.from_dict(data)` | Restore from saved state |

### `TurnResult`

| Field | Type | Description |
|-------|------|-------------|
| `narrative` | `str` | AI-generated historical chronicle |
| `aftermath` | `str` | Resource changes summary |
| `state_changes` | `dict` | Numerical state deltas |
| `new_suggestions` | `list[str]` | Next-turn strategy suggestions |
| `token_usage` | `TokenUsage` | LLM token consumption |
| `game_over` | `dict \| None` | Victory/defeat message |
| `faction_status` | `FactionStatus` | Current resources and territories |

## License

MIT — Emergence Science
