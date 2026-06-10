# histrategy-sdk

Python SDK for [三國志略 (Histrategy)](https://emergence.science/play/histrategy) — AI-powered Three Kingdoms strategy game.

**Fully file-based. No network, no server, no in-memory state.**
Every turn reads from and writes to `~/.histrategy/rooms/<name>/` on disk.
Designed for AI agents (OpenClaw, Hermes, Codex) that reset context daily.

```bash
pip install histrategy-sdk
```

## Quick Start

```python
from histrategy_sdk import Room

# Create a new game
room = Room.create("my-campaign", faction="shu")

# Play a turn — reads state from disk, executes, writes back
result = room.play("联吴抗曹，攻打襄阳")
print(result["narrative"])

# Agent context resets overnight? No problem:
room2 = Room.load("my-campaign")
result2 = room2.play("休养生息，发展内政")
print(f"Year {result2['year']}, {result2['season']}, Turn {result2['turn']}")
print(f"⚔️{result2['faction_status']['strength']} 🍚{result2['faction_status']['food']}")
```

## File Layout

```
~/.histrategy/rooms/
  my-campaign/
    world_state.json    # Full game state (engine.to_dict())
    turns.jsonl          # Append-only turn history
    metadata.json        # Room metadata
  multiplayer/shu/
    world_state.json
    turns.jsonl
    metadata.json
  multiplayer/cao/
    ...
  multiplayer/wu/
    ...
```

## API

### `Room`

| Method | Description |
|--------|-------------|
| `Room.create(name, faction)` | Create new room + save initial state |
| `Room.load(name)` | Load room from disk |
| `room.play(decision)` | Execute turn → auto-save to disk |
| `room.plan()` | Get advisor suggestions |
| `room.intro()` | Get intro scene |
| `room.status()` | Get current faction resources |
| `room.get_turn_history()` | Read all past turns from disk |

### `DirectEngine`

Low-level in-process engine (used internally by Room):

| Method | Description |
|--------|-------------|
| `DirectEngine(faction)` | Create new engine |
| `engine.execute(decision)` | Process turn |
| `engine.to_dict()` | Serialize state |
| `DirectEngine.from_dict(data)` | Restore from saved state |

### `TurnResult`

| Field | Type | Description |
|-------|------|-------------|
| `narrative` | `str` | AI-generated historical chronicle |
| `aftermath` | `str` | Resource changes summary |
| `state_changes` | `dict` | Numerical state deltas |
| `new_suggestions` | `list[str]` | Next-turn strategy suggestions |
| `events_occurred` | `list[str]` | Character events |
| `npc_actions` | `list[str]` | NPC faction actions |
| `game_over` | `dict \| None` | Victory/defeat |
| `faction_status` | `FactionStatus` | Resources and territories |
| `token_usage` | `TokenUsage` | LLM tokens consumed |

## Multiplayer

One room per faction. The world_state.json contains ALL factions,
so any player can load the state and execute their turn:

```python
# Three players, three rooms, shared game world
shu = Room.create("three-kingdoms/shu", faction="shu")
cao = Room.create("three-kingdoms/cao", faction="cao")
wu  = Room.create("three-kingdoms/wu",  faction="wu")

# Player 1 (Shu)
r = shu.play("联吴抗曹")
# → saves to three-kingdoms/shu/world_state.json

# Player 2 (Cao) — loads the world state that includes Shu's move
# (Note: each room has its own world_state.json copy;
#  for true shared state, all rooms should point to the same file
#  or the orchestrator should sync after each turn)
r = cao.play("南征刘备")
```

## License

MIT — Emergence Science
