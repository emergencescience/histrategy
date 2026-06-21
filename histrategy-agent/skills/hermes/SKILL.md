---
name: histrategy
description: "三國志略 / Histrategy — AI 驱动的历史策略游戏。支持三國和罗马双剧本。在飞书/Discord/Telegram 中用自然语言指挥千军万马。"
version: 2.0.0
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gaming, strategy, three-kingdoms, rome, multiplayer, history, feishu]
    related_skills: []
    category: gaming
    requires: histrategy-agent>=0.2.2,histrategy-sdk>=0.3.1
    slash_commands:
      - /histrategy
      - /三国
      - /sanguo
      - /rome
---

# Histrategy — 三國志略

## When to Use
- User sends `/histrategy`, `/三国`, `/sanguo`, or `/rome`
- User mentions "三国志略", "histrategy", "罗马", "rome"
- User has an active game state on disk

## Supported Scenarios

| Scenario | Setting | Playable Factions |
|----------|---------|-------------------|
| `three-kingdoms` | 207 AD | 曹操(cao), 刘备(shu), 孙权(wu) |
| `rome-triumvirate` | 44 BC | Octavian, Antony, Cleopatra, Senate |

**Language**: Pass `lang="zh"` or `lang="en"`. Default is `zh`.

## Installation

```bash
pip install histrategy-agent histrategy-sdk
```

- `histrategy-agent` — Agent integration (TurnProcessor, StateBridge, IM adapters)
- `histrategy-sdk` — Game SDK (Room, MultiplayerRoom, DirectEngine)
- `histrategy-engine` — Auto-installed dependency

Configure API key:

```bash
export DEEPSEEK_API_KEY="sk-..."  # Recommended
# or OPENAI_API_KEY / TONGYI_API_KEY
```

**Without an API key, games run in offline rule-based mode (no LLM narrative).**

## Quick Start

- `/histrategy new [faction] [scenario]` — Start single-player game (e.g. `senate rome-triumvirate`)
- `/histrategy host faction=player ...` — Create multiplayer room
- `/histrategy join <room_id> <faction>` — Join multiplayer game
- `/histrategy play <decision>` — Submit turn decision
- `/histrategy status` — View current state
- `/histrategy turns` — View turn history
- `/histrategy help` — Show help

## Procedure

### 1. Single-Player Mode (`/histrategy new [faction] [scenario]`)

Uses `histrategy_sdk.Room` (file-based state, survives restarts):

```python
from histrategy_sdk import Room

# Three Kingdoms as Liu Bei
room = Room.create("my-game", faction="shu")

# Rome Triumvirate as Senate
room = Room.create("rome-game", faction="senate", scenario="rome-triumvirate", lang="zh")

# Submit decision
result = room.play("联吴抗曹")

# Check status
room.status()
```

### 2. Multiplayer Mode ⚠️ REQUIRES SERVER

Multiplayer uses `histrategy_sdk.ServerClient` calling a **running histrategy HTTP server**.
Single-player (file-based) does NOT work for multiplayer — you MUST have a server instance.

```bash
# Start the server (required for multiplayer)
HISTRATEGY_ENGINE=v1 uvicorn 'histrategy.server.api:create_app' --factory --host 0.0.0.0 --port 8080
```

```python
from histrategy_sdk import ServerClient, MultiplayerRoom

client = ServerClient(base_url="http://localhost:8080")

# Host creates room with 3 humans + 1 AI NPC (Antony)
room = MultiplayerRoom.create(client, {
    "octavian": "Player1",
    "senate": "Player2",
    "cleopatra": "Player3"
    # Antony NOT assigned → AI NPC (auto-submits decisions)
}, scenario="rome-triumvirate", lang="zh")

# Players join
room = MultiplayerRoom.join(client, room_id, faction, token)

# Submit decision — NPC auto-submit is handled by server
room.decide("Attack Rome")
room.wait_for_resolve()
```

**Important: NPC auto-submission** — AI-controlled factions submit their own decisions automatically. After all humans submit, the server resolves the turn. If a room seems stuck, check status — NPCs may still be generating (LLM takes 30-60s).

### 3. State Management

Game state is stored in `HISTRATEGY_DATA_DIR` (default `~/.histrategy/`):

```
~/.histrategy/
  rooms/{room-name}/
    world_state.json    # Full world state
    turns.jsonl         # Turn history
    metadata.json       # Room config
  sessions/{platform}/{chat_id}/
```

Every turn: read state → execute → write back. Survives restarts and context resets.

## Output Format

Turn results rendered as Markdown:

```
🎌 Year {year} · {season} | Turn #{turn}

> {LLM-generated narrative}

⚔️ Status
| Territory | {territories} |
| Troops | {strength} |
| Food | {food} |
| Treasury | {treasury} |
| Morale | {morale} |
```

## Pitfalls

- **Multiplayer needs a server**: Single-player (Room) ≠ Multiplayer (MultiplayerRoom + ServerClient). File-based doesn't work for multiplayer.
- **NPC auto-submit is slow**: LLM calls take 30-90s. Show "Advisors deliberating..." status.
- **No API key → offline mode**: Rule-based, no LLM narrative. Set DEEPSEEK_API_KEY.
- **Room ID persists**: Use `Room.load(name)` after restart — state is on disk.
- **Faction IDs for Rome**: `octavian`, `antony`, `cleopatra`, `senate` (not Chinese names).
