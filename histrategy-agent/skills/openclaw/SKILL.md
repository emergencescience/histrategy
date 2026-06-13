---
name: histrategy
description: "三國志略 — AI-powered Three Kingdoms strategy game. Command armies through natural language in any IM chat. Group chat = battlefield."
version: 1.0.0
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
platforms: [linux, macos, windows]
triggers:
  - 三国
  - 三国志略
  - histrategy
  - /histrategy
  - /三国
  - /sanguo
metadata:
  openclaw:
    category: gaming
    min_version: "1.0.0"
    clawhub_id: histrategy
    requires: histrategy-sdk>=0.2.0
  tags: [gaming, strategy, three-kingdoms, multiplayer, history, feishu]
---

# 三國志略 (Histrategy)

## Trigger
When a user sends `/histrategy`, `/三国`, `/sanguo`, or any message containing 「三国志略」「三国」in a chat where this skill is active.

## Quick Start
- `/histrategy new [faction]` — Start single-player game (optionally specify faction)
- `/histrategy host caocao=Alice liubei=Bob` — Create multiplayer room
- `/histrategy join <room_id> <faction> [token]` — Join multiplayer game
- `/histrategy play <decision>` — Submit turn decision
- `/histrategy status` — View current state
- `/histrategy turns` — View turn history
- `/histrategy help` — Show help

## Core Loop

### Single-Player (`/histrategy new [faction]`)

Uses `histrategy_sdk.Room` (file-based state management):

```python
from histrategy_sdk import Room

# Create a room (supports shu / wei / wu / neutral)
room = Room.create("my-game", faction="shu")

# Submit a decision
result = room.play("Ally with Wu against Cao")

# View status
room.status()
```

Workflow:
1. On room creation, display faction intro + starting state + map
2. Player submits decision via `/histrategy play <decision>` → `room.play(decision_text)`
3. Engine executes game logic, LLM generates narrative
4. Render result: narrative + map + status cards + suggested actions
5. Repeat steps 2-4 until game ends

### Multiplayer

Uses `histrategy_sdk.MultiplayerRoom`:

#### Host creates room (`/histrategy host caocao=Alice liubei=Bob`)

```python
from histrategy_sdk import MultiplayerRoom

client = get_client()  # platform client
room = MultiplayerRoom.create(client, {
    "caocao": "Alice",
    "liubei": "Bob",
})
# Share room.player_links with respective players
```

#### Player joins (`/histrategy join <room_id> <faction> [token]`)

```python
room = MultiplayerRoom.join(client, room_id, faction, token)
```

#### Turn decisions (`/histrategy play <decision>`)

```python
# Submit decision
room.decide("Attack Xiangyang")

# Wait for resolution
room.wait_for_resolve()

# View results
status = room.status()
```

### State Management
- `/histrategy status` — View current state (`room.status()`)
- `/histrategy turns` — View turn history
- `/histrategy save` — Save progress
- `/histrategy load` — Load saved game
- `/histrategy delete` — Delete save

## Output Format (Feishu Markdown)

```
🎌 **Jian'an Year {year} · {season}** | Turn #{turn}

> {narrative}

🗺️ **Realm Overview**
{ASCII map}

⚔️ **Faction Status**
{stat table}

📋 **Suggested Actions**
1. {suggestion}
2. {suggestion}
3. {suggestion}
```

## Platform Support
- **Feishu (飞书)**: Full support (native IM bridge)
- **Telegram**: Coming soon
- **Discord**: Coming soon
- **WeChat**: Coming soon

## Technical Notes
- Game state stored in `~/.histrategy/sessions/{platform}/{chat_id}/`
- Zero external dependencies beyond Python stdlib + histrategy-engine
- LLM-driven narrative; offline fallback for no-API-key scenarios
- All game logic is deterministic — same input always produces same output
