# Histrategy (三國志略)

**An open-source, AI-powered historical strategy game.**

> *In 207 AD, the Han dynasty crumbles. Warlords vie for control of the realm. You take command — write your own chapter in history. Or re-live the chaos of 44 BC Rome, where Octavian, Antony, and Cleopatra struggle for supremacy.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Made by Emergence Science](https://img.shields.io/badge/Made%20by-Emergence%20Science-8A2BE2)](https://emergence.science)

<p align="center">
  <img src="publications/2026-05-25-introduction/assets/2026-05-25-histrategy-yuan-shao.png" alt="Histrategy CLI" width="720">
</p>

---

## Scenarios

| Scenario | Year | Factions | Language |
|----------|------|----------|----------|
| **Three Kingdoms** | 207 AD | Cao Cao, Liu Bei, Sun Quan | English, 中文 |
| **Rome Triumvirate** | 44 BC | Octavian, Antony, Cleopatra, Senate | English, 中文 |
| **Southern Ming (山河鼎革)** | 1645 AD | Southern Ming, Qing, Peasant Army, Zheng Clan | 中文 |

> 🏠 **《山河鼎革》已停止云端服务** — 自建即可继续游玩（scenario id: `nanming`）。
> 云端（emergence.science）不再接受新房间，但源码完全开放：克隆本仓库后本地运行即可体验全部 4 个势力。安装见下方 Quick Start。

## Quick Start

### Recommended: V1 Engine

```bash
pip install histrategy-sdk
export HISTRATEGY_ENGINE=v1
export DEEPSEEK_API_KEY="sk-..."
```

```python
from histrategy_sdk import Room

# Three Kingdoms — English
room = Room.create("my-game", faction="cao", lang="en")
result = room.play("Attack Xinye with 50,000 troops")
print(result["narrative"])

# Rome Triumvirate — English
room = Room.create("rome", faction="octavian", scenario="rome-triumvirate", lang="en")
result = room.play("Secure the Senate's support against Antony")

# Southern Ming / 山河鼎革 — 中文（自建部署专用，需 LLM API key）
room = Room.create("my-ming", faction="nanming", scenario="nanming", lang="zh")
result = room.play("整军备战，坚守扬州，联结郑氏水师")
```

### From Source

```bash
git clone https://github.com/emergencescience/histrategy
cd histrategy
python3 -m venv .venv
source .venv/bin/activate

# Install SDK + engine
pip install -e histrategy-engine/
pip install -e histrategy-sdk/

# Optional: full game with CLI and server
pip install -e .
histrategy
```

## Engines

| Engine | Description | LLM | Best For |
|--------|-------------|-----|----------|
| **V1** | Single LLM call per turn with rich narrative | Yes | Production play, immersion |
| V2 | Pure deterministic formulas, zero LLM | No | Testing, offline, balance tuning |
| V3 | Hybrid: deterministic base + LLM nonlinear layer | Yes | Advanced simulation |

Set via `HISTRATEGY_ENGINE=v1` (or `v2`, `v3`). V1 is recommended.

## Architecture

```
histrategy/              # Full game: FastAPI server, CLI, web UI
histrategy-sdk/          # SDK for players: Room, DirectEngine (file-based)
histrategy-agent/        # Agent integration: TurnProcessor, IM adapters
histrategy-engine/       # Core engine: WorldState, TurnController, formulas
```

**Dependency chain**: `histrategy-engine` → `histrategy-sdk` / `histrategy-agent` → `histrategy`

## Key Features

- **File-based state**: Game survives agent context resets. `Room.load(name)` restores everything.
- **Multi-scenario**: Three Kingdoms and Rome Triumvirate supported. Extensible design.
- **Bilingual**: English and Chinese supported at the SDK level. Pass `lang="en"` or `lang="zh"`.
- **AI NPCs**: Opposing warlords make their own decisions based on personality and situation.
- **Agent-native**: Designed for Hermes, OpenClaw, and other AI agents to host multiplayer games.

## For AI Agents

Install the skill to let your agent host strategy games in any chat:

```bash
# OpenClaw
cp histrategy-agent/skills/openclaw/SKILL.md ~/.openclaw/skills/histrategy.md

# Hermes Agent
hermes skills install https://raw.githubusercontent.com/emergencescience/histrategy/main/histrategy-agent/skills/hermes/SKILL.md
```

## Documentation

- [Game Manual](https://emergence.science/en/games/histrategy)
- [SDK Reference](https://github.com/emergencescience/histrategy/blob/main/histrategy-sdk/README.md)
- [Engine Design](https://github.com/emergencescience/histrategy/blob/main/docs/design/)

## License

MIT © [Emergence Science](https://emergence.science)
