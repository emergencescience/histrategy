---
name: histrategy
description: "三國志略 / Histrategy — AI-powered historical strategy game. Supports Three Kingdoms and Rome Triumvirate scenarios. Command armies through natural language. Multiplayer via IM."
version: 2.0.1
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
platforms: [linux, macos, windows]
triggers:
  - 三国
  - 三国志略
  - histrategy
  - /histrategy
  - /sanguo
  - rome
  - rome-triumvirate
  - triumvirate
metadata:
  openclaw:
    category: gaming
    min_version: "1.0.0"
    clawhub_id: histrategy
    requires: histrategy-sdk>=0.3.2
  tags: [gaming, strategy, three-kingdoms, rome, multiplayer, history, feishu, im]
---

# 三國志略 (Histrategy)

An AI-powered historical strategy game. The LLM plays advisors, generals, and NPC warlords. Players command with natural language. Supports **two scenarios** and **two languages**.

## Scenarios

| Scenario | Setting | Factions |
|----------|---------|----------|
| `three-kingdoms` | 207 AD, Jian'an 12th year | 曹操军 (Cao Cao), 刘备军 (Liu Bei), 孙权军 (Sun Quan) |
| `rome-triumvirate` | 44 BC, Ides of March | Octavian, Antony, Cleopatra, Senate |

## Language Support

Both **English** and **Chinese** (中文) are fully supported. Pass `lang="en"` or `lang="zh"` when creating a room:

```python
# English game
room = Room.create("my-game", faction="cao", lang="en")

# Chinese game (default)
room = Room.create("my-game", faction="cao", lang="zh")
```

## Recommended Engine

**Use V1 engine for best narrative quality.** V1 runs a single LLM call per turn with rich historical storytelling. V2 is deterministic (no LLM) for testing.

```bash
export HISTRATEGY_ENGINE=v1
export DEEPSEEK_API_KEY="sk-..."
```

| Engine | Description | LLM Calls | Best For |
|--------|-------------|-----------|----------|
| **V1** (recommended) | Single LLM simulation per turn | 1 | Narrative immersion, production play |
| V2 | Pure deterministic formulas | 0 | Testing, offline play |

## Installation

```bash
pip install histrategy-sdk
```

- `histrategy-sdk` — Game SDK (`Room`, `MultiplayerRoom`, `DirectEngine`)
- `histrategy-engine` — Auto-installed as dependency
- `histrategy-agent` — Optional: IM bot integration (`TurnProcessor`, IM adapters)

### From GitHub

```bash
git clone https://github.com/emergencescience/histrategy
cd histrategy
pip install -e histrategy-sdk/
```

### Configure LLM

```bash
export DEEPSEEK_API_KEY="sk-..."   # Recommended — best value
# or
export OPENAI_API_KEY="sk-..."
# or
export TONGYI_API_KEY="sk-..."
```

Without an API key, games run in offline rule-based mode (no LLM narrative).

## Quick Start

### Single-Player

```python
from histrategy_sdk import Room

# Create an English Three Kingdoms game as Cao Cao
room = Room.create("my-campaign", faction="cao", lang="en")

# Get the intro scene
intro = room.intro()
print(intro["narrative"])

# Play a turn
result = room.play("Attack Xinye with 50,000 troops from Wancheng")
print(result["narrative"])
print(f"Morale: {result['faction_status']['morale']}")

# Resume after agent context reset
room = Room.load("my-campaign", lang="en")
result = room.play("Consolidate territories and lower taxes to 20%")
```

### Rome Triumvirate

```python
from histrategy_sdk import Room

room = Room.create("rome-campaign", faction="octavian", scenario="rome-triumvirate", lang="en")
result = room.play("Secure the Senate's support and isolate Antony politically")
```

## Core Design: File-Based State

Game state lives entirely on disk. Agent context resets don't lose progress:

```
~/.histrategy/rooms/
  <room-name>/
    world_state.json    # Full game world state
    turns.jsonl         # Append-only turn log
    metadata.json       # Room metadata
```

Every turn: read state → execute → write back. Survives restarts.

## API Reference

### Room

| Method | Description |
|--------|-------------|
| `Room.create(name, faction, scenario, lang)` | Create new game |
| `Room.load(name, lang)` | Load from disk |
| `room.play(decision)` | Execute turn → auto-save |
| `room.plan()` | Get advisor suggestions |
| `room.intro()` | Get opening scene |
| `room.status()` | Get resource snapshot |
| `room.get_turn_history()` | Read all past turns |

### Room.create() Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Room name (unique ID) |
| `faction` | `str` | `"shu"` | Player faction |
| `scenario` | `str` | `"three-kingdoms"` | `"three-kingdoms"` or `"rome-triumvirate"` |
| `lang` | `str` | `"zh"` | `"zh"` or `"en"` |
| `llm_api_key` | `str` | auto | Override API key |
| `llm_provider` | `str` | auto | `"deepseek"`, `"openai"`, `"tongyi"` |

### Available Factions

**Three Kingdoms:** `cao` (曹操), `shu` (刘备), `wu` (孙权)

**Rome Triumvirate:** `octavian`, `antony`, `cleopatra`, `senate`

## Game Rules

- **Turn-based**: Each turn = one season. Spring → Summer → Autumn → Winter
- **Resources**: Troops, Food, Treasury, Morale
- **Domestic**: Develop commerce, reclaim farmland, recruit militia
- **Military**: Attack, defend, ambush, siege
- **Diplomacy**: Alliance, estrangement, persuasion, tribute
- **NPCs**: AI-controlled factions act autonomously and war with each other

## Formatting Turn Results

```python
def format_turn(result: dict, lang: str = "en") -> str:
    fs = result["faction_status"]
    if lang == "en":
        lines = [
            f"## {result['year']} · {result['season']} | Turn {result['turn']}",
            result["narrative"],
            f"\n⚔️Troops:{fs['strength']} 🍚Food:{fs['food']} 💰Gold:{fs['treasury']} ❤️Morale:{fs['morale']}",
        ]
    else:
        lines = [
            f"## {result['year']}年{result['season']} · 第{result['turn']}回合",
            result["narrative"],
            f"\n⚔️兵力:{fs['strength']} 🍚粮草:{fs['food']} 💰库金:{fs['treasury']} ❤️士气:{fs['morale']}",
        ]
    if result.get("new_suggestions"):
        label = "Advisor Suggestions" if lang == "en" else "谋士献策"
        lines.append(f"\n**{label}**:")
        for s in result["new_suggestions"][:3]:
            lines.append(f"  • {s}")
    return "\n".join(lines)
```

## FAQ

| Issue | Solution |
|-------|----------|
| **Turns are slow (60-90s)** | LLM generation. Show "Advisors are deliberating..." |
| **Progress lost after context reset** | Not possible. `Room.load(name)` restores from disk |
| **No API key** | Auto-falls back to offline rule-based mode |
| **Chinese output when I want English** | Pass `lang="en"` to `Room.create()` or `Room.load()` |
| **Multiplayer** | Use `MultiplayerRoom` with a histrategy server |

## Source & Community

- GitHub: https://github.com/emergencescience/histrategy
- PyPI: https://pypi.org/project/histrategy-sdk/
- Web: https://emergence.science/en/games/histrategy
