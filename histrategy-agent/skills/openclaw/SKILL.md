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
  tags: [gaming, strategy, three-kingdoms, multiplayer, history, feishu]
---

# 三國志略 (Histrategy)

## Trigger
When a user sends `/histrategy`, `/三国`, `/sanguo`, or any message containing 「三国志略」「三国」in a chat where this skill is active.

## Quick Start
- `/histrategy new` — Start a new campaign (pick your faction)
- `/histrategy load` — Load saved game
- `/histrategy status` — View current world state
- `/histrategy join` — Join a multiplayer session (group chat)
- `/histrategy help` — Show help
- Direct input — Natural language commands like "Attack Luoyang", "Recruit cavalry"

## Core Loop
1. Player inputs natural language command
2. AI processes the turn: intent parsing → engine execution → narrative generation
3. Returns: narrative + map + status cards + suggestions
4. World evolves continuously; NPC factions act autonomously

## Multiplayer Mode
In group chats, the first player to start a game becomes the host. Others join via `/histrategy join`.
Turn-based: each player commands their faction in sequence.

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
