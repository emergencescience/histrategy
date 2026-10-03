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

### Programmatic use: histrategy-sdk

> 想直接跑起来玩？最快的自建方式是下面的 **Self-host with Docker Compose**（一个容器、SQLite、不需要 Postgres）。
> 本节是**编程接口**用法。

```bash
pip install histrategy-sdk
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

### Self-host with Docker Compose（推荐自建方式）

One container, zero external dependencies — 默认用 SQLite，**不需要 Postgres**。

```bash
# 1) 提供 LLM key —— 只走环境变量 / .env，不经过浏览器
cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-xxxxxxxx
EOF

# 2) 构建并启动
docker compose up -d --build

# 3) 打开 http://localhost:8080
```

- **引擎**：V3（生产引擎：确定性基线 + LLM 非线性层）—— **无需任何引擎环境变量**。
- **存档**：游戏存档与 SQLite 落在 `./.histrategy-data`，整个目录删掉即重置。
- **任意 OpenAI 兼容端点**：设 `LLM_API_BASE` + `LLM_API_KEY` + `LLM_MODEL` 即可。
- **想用 Postgres**：设 `HISTRATEGY_DATABASE_URL=postgresql://user:pass@host:5432/db`。

> ✅ **V1 引擎已下线（2026-10-03）**：V1（一次 LLM 调用推演全世界）的失效模式是**幻觉**——
> 让 LLM 凭空产出十几个势力的精确数值，必然与确定性基线打架。现在 **V3 是默认且唯一的生产引擎**，
> 且 **`HISTRATEGY_ENGINE` 环境变量不再需要**（不设置即为 v3；`v2` 仅作离线/测试覆盖）。

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
| **V3** (default) | Hybrid: deterministic base + LLM nonlinear layer + guardrails | Yes | **Production play** |
| V2 | Pure deterministic formulas, zero LLM (the base layer of V3) | No | Offline, testing, balance tuning |
| ~~V1~~ | ~~Single LLM call per turn simulating the whole world~~ | — | **Removed 2026-10-03** (hallucinated numbers) |

V3 is the default — **no environment variable required**. Set `HISTRATEGY_ENGINE=v2`
only to force the deterministic engine (offline/testing).

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
