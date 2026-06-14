---
name: histrategy-sdk
description: "Use when an agent (OpenClaw, Hermes) needs to install and play 三國志略 via pip-installed SDK with SQLite persistence. No server, no PostgreSQL — just pip install + play."
version: 1.0.0
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
metadata:
  openclaw:
    category: gaming
    min_version: "1.0.0"
    clawhub_id: histrategy-sdk
  hermes:
    tags: [gaming, strategy, three-kingdoms, sdk, sqlite, cli]
    related_skills: [histrategy]
platforms: [linux, macos, windows]
---

# 三國志略 SDK — Pip-Install & Play

Zero-service Three Kingdoms strategy game. `pip install` the SDK, play via Python or CLI. All state lives in a single SQLite file at `~/.histrategy/histrategy.db`. No server to maintain, no port to occupy, no PostgreSQL credentials to manage.

## When to Use

- Agent (OpenClaw/Hermes) receives a game command: `/histrategy`, `/三国`, `新游戏`, faction name, or turn decision
- Agent needs to create/load/save game state for an IM chat
- Agent needs multiplayer (multiple factions in one chat)
- Human player wants CLI: `histrategy new shu` → `histrategy play "联吴抗曹"`

**Do NOT use when:**
- The task doesn't involve playing the game (use `rule-contribution` skill for modifying YAML rules)

## Architecture

```
pip install histrategy-agent
        │
        ▼
┌───────────────────────────────┐
│       histrategy-agent        │  ← pip package
│  ┌─────────────────────────┐  │
│  │  GameSessionManager     │  │  ← session CRUD
│  │  TurnProcessor          │  │  ← game logic
│  │  MultiplayerSession     │  │  ← lobby/turn mgmt
│  │  FormatEngine           │  │  ← markdown output
│  └──────────┬──────────────┘  │
│             │                  │
│  ┌──────────▼──────────────┐  │
│  │  SQLite                  │  │
│  │  ~/.histrategy/          │  │
│  │  histrategy.db           │  │
│  └─────────────────────────┘  │
└───────────────────────────────┘
```

- **No server** — all game logic runs in the agent's Python process
- **No PostgreSQL** — SQLite file at `~/.histrategy/histrategy.db`
- **No credentials** — file permissions are the only access control
- **Multiplayer on same VM** — SQLite WAL mode handles concurrent readers + serialized writers

## Installation

```bash
pip install histrategy-agent
```

Requires Python ≥ 3.11. The SDK depends on `histrategy-engine` which is pulled automatically.

Verify:
```bash
python -c "from histrategy_agent.session import GameSessionManager; print('OK')"
```

## Quick Start

### SDK Mode (for Agents)

Agents import the SDK and call functions — no subprocess, no stdin/stdout, just Python:

```python
from histrategy_agent.session import GameSessionManager
from histrategy_agent.turn_processor import TurnProcessor
from histrategy_agent.format_engine import FormatEngine

manager = GameSessionManager()
processor = TurnProcessor()
engine = FormatEngine()

# Start a new game (player as Liu Bei)
session = manager.get_or_create("feishu", chat_id, faction_id="shu")
intro = engine.render_onboarding(session)
# → send intro to chat

# Process a turn
result = processor.process(session, "联吴抗曹，攻打襄阳")
manager.save_session(session)
output = engine.render_turn_result(result, "feishu")
# → send output to chat

# Load existing game
session = manager.get_session("feishu", chat_id)
if session:
    status = engine.render_state_summary(session)
```

### CLI Mode (for Humans)

```bash
# Start a new game
histrategy new shu

# Submit a turn decision
histrategy play "赤壁之战，与周瑜合攻曹操水寨"

# View current state
histrategy status

# List saved games
histrategy list

# Delete a save
histrategy delete
```

The CLI is a thin wrapper around the SDK. Every CLI command maps to one or two SDK calls.

## Storage: SQLite at ~/.histrategy/

| Path | Purpose |
|------|---------|
| `~/.histrategy/histrategy.db` | Single SQLite database with all game state |
| `~/.histrategy/sessions/` | Legacy JSON files (migrated to SQLite on first access) |

### Tables

| Table | Row per | Key |
|-------|---------|-----|
| `sessions` | Active game | `(platform, chat_id)` |
| `world_state` | World snapshot | `session_id` |
| `multiplayer` | Group chat lobby | `session_id` |
| `turns` | Turn history | `(session_id, turn_number)` |

### Why SQLite Instead of PostgreSQL

| Concern | SQLite Answer |
|---------|---------------|
| "DB server goes down" | No server to go down |
| "Need to configure credentials" | No credentials — it's a file |
| "Cross-VM multiplayer" | Not the 90% case; add PostgreSQL only when needed |
| "Concurrent writes" | WAL mode: concurrent reads, serialized writes |
| "Backup" | `cp ~/.histrategy/histrategy.db backup.db` |

### Migration from JSON Files

On first access, `GameSessionManager` auto-migrates:
1. Checks if `~/.histrategy/sessions/` has JSON files
2. Reads each JSON session into SQLite
3. Marks sessions as migrated
4. Subsequent reads go to SQLite

## Agent Dispatch Pattern

When handling a message, agents follow this dispatch:

```
1. Is it a command? (/histrategy, /三国, 新游戏, etc.)
   → route to command handler
2. Is it a faction selection? (刘备, shu, 曹操, cao, etc.)
   → create new game with that faction
3. Is there an active session for this chat?
   → process as game turn
4. Otherwise
   → prompt user to start a game
```

### OpenClaw Agent Pattern

```python
def handle_message(message: dict) -> dict:
    platform = message["platform"]
    chat_id = message["chat_id"]
    text = message["text"].strip()

    manager = GameSessionManager()
    processor = TurnProcessor()
    engine = FormatEngine()

    # Commands
    if text in ("/histrategy new", "新游戏"):
        return {"text": FACTION_SELECTION_PROMPT}

    if text in ("/histrategy status", "状态"):
        session = manager.get_session(platform, chat_id)
        if not session:
            return {"text": "⚠️ No game active."}
        return {"text": engine.render_state_summary(session)}

    # Faction selection
    faction = FACTION_MAP.get(text)
    if faction and not manager.get_session(platform, chat_id):
        session = manager.get_or_create(platform, chat_id, faction_id=faction)
        return {"text": engine.render_onboarding(session)}

    # Game turn
    session = manager.get_session(platform, chat_id)
    if not session:
        return {"text": "⚠️ Type '/histrategy new' to start."}

    result = processor.process(session, text)
    manager.save_session(session)
    return {"text": engine.render_turn_result(result, platform)}
```

### Hermes Agent Pattern

Same SDK calls, but routed through `commands.py` handler functions. See `hermes/SKILL.md` for the slash-command dispatch table.

## Output Format

Game results are Markdown, suitable for Feishu/Telegram/Discord:

```
🎌 **建安13年 · 秋** | 回合 #3

> 曹军南下，号称八十万大军压境长江。周瑜力主抗曹，与诸葛亮定下火攻之计...

🗺️ **天下大势**
| 势力 | 领地 | 兵力 |
|------|------|------|
| 曹操 | 许昌宛城洛阳邺城下邳蓟县 | 150,000 |
| 孙权 | 建业柴桑吴郡 | 60,000 |
| 刘备 | 新野 | 5,000 |

⚔️ **我军态势**
| 兵力 | 5,000 |
| 粮草 | 2,000 |
| 金库 | 3,000 |
| 声望 | 35 |

📋 **可选行动**
1. 联吴抗曹 — 派诸葛亮出使江东，说服孙权共同对抗曹操
2. 固守新野 — 加固城防，囤积粮草，以逸待劳
3. 南迁避战 — 放弃新野，向南撤退保存实力
```

## Common Pitfalls

1. **Relying on in-memory state.** Agents must assume context resets between turns. Always call `manager.get_session()` to load from SQLite, never cache session objects in memory.

2. **Forgetting to call `save_session()`.** After `processor.process()`, always call `manager.save_session(session)`. The processor modifies the session in-place but doesn't auto-save.

3. **Installing without `histrategy-engine`.** If you get `ModuleNotFoundError: histrategy_engine`, the engine dependency wasn't installed. Run `pip install histrategy-engine` or reinstall with `pip install --force-reinstall histrategy-agent`.

4. **Assuming PostgreSQL.** The SDK uses SQLite by default. No `DB_URL` env var needed. If you want PostgreSQL (for cross-VM multiplayer), set `HISTRATEGY_DB_URL=postgres://...`.

5. **Platform mismatch in session key.** Sessions are keyed by `(platform, chat_id)`. A game started in Feishu won't be found by a Telegram query — the `platform` prefix must match.

## Verification Checklist

- [ ] `pip install histrategy-agent` succeeds
- [ ] `python -c "from histrategy_agent.session import GameSessionManager; print('OK')"` prints OK
- [ ] Creating a session writes to `~/.histrategy/histrategy.db`
- [ ] Loading a session reads back the same data
- [ ] Processing a turn updates the session
- [ ] Multiplayer: join + start + advance_turn works on the same VM
