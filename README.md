# 三國志略 (Histrategy)

**An open-source, AI-powered text-based history strategy game.**

> 初平元年，汉室倾颓，群雄逐鹿。你将扮演一方诸侯，在这个风云激荡的时代书写你的传奇。
> 
> *In 190 AD, the Han dynasty crumbles. Warlords vie for control. You will take command of a faction and write your own chapter in history.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Made by Emergence Science](https://img.shields.io/badge/Made%20by-Emergence%20Science-8A2BE2)](https://emergence.science)

<p align="center">
  <img src="demo/histrategy-demo.svg" alt="三國志略 Demo" width="720">
</p>

---

## 🎮 Quick Start

### Install (macOS / Linux)

```bash
# Option 1: pip (once published to PyPI)
pip install histrategy

# Option 2: local install from source (recommended for now)
git clone https://github.com/emergencescience/histrategy.git
cd histrategy
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Play offline (rule-based simulation — no API key needed)
histrategy
```

### Supported AI Providers

| Provider | Env Variable | Default Model | Price vs GPT-4o |
|----------|-------------|---------------|-----------------|
| **DeepSeek** (recommended) | `DEEPSEEK_API_KEY` | deepseek-chat | ~1/20x |
| **OpenAI** | `OPENAI_API_KEY` | gpt-4o-mini | baseline |
| **通义千问 (Tongyi)** | `TONGYI_API_KEY` | qwen-max | ~1/3x |
| **OpenRouter** | `OPENROUTER_API_KEY` | deepseek/deepseek-r1 | varies |
| **Custom** | `OPENAI_API_BASE` + `OPENAI_API_KEY` | configurable | — |

No API key? No problem. Offline mode uses a rule-based engine — play immediately.

---

## 🏛️ Choose Your Era

### Available Now

**190 AD — Three Kingdoms (三国)**
- 8+ playable factions (曹操, 刘备, 孙坚, 袁绍, 董卓...)
- 20+ historical characters with personalities and skills
- 19 regions with strategic value, resources, and geography
- Key historical events (讨董联盟, 迁都长安, 孙坚得玉玺...)

### Coming Soon

- **770 BC — Spring and Autumn (春秋)**
- **453 BC — Warring States (战国)**
- **69 AD — Year of the Four Emperors (Roman Empire)**
- **User-created scenarios via mod system**

---

## 🎲 How It Works

```
1. Choose your faction ──→ 2. Receive season report (AI-generated)
                               ↓
3. Make strategic decisions ──→ AI simulates consequences
  (natural language or menu)      NPC factions react
                                  Historical events trigger
                               ↓
4. See the world change ────→ Loop back to step 2
```

Each turn represents one season (3 months). Your decisions ripple through:
- **Military**: Fortify, attack, recruit, defend
- **Economy**: Tax, trade, develop infrastructure
- **Diplomacy**: Ally, betray, marry, threaten
- **Governance**: Edicts, appointments, reforms

---

## 🧠 AI vs Offline Mode

| Feature | Offline (Rule-based) | AI-powered |
|---------|---------------------|------------|
| Narrative | Template-based | Dynamic LLM generation |
| NPC actions | Random + rule-based | Strategic AI simulation |
| Historical events | Fixed timeline | Adaptive + emergent |
| Requirements | None | API key (any provider) |
| Cost | Free | ~$0.001-0.01/turn |

---

## 🏗️ Architecture

```
histrategy/
├── engine/
│   ├── world.py         # Game state (factions, characters, regions)
│   ├── game.py          # Game orchestrator
│   └── offline_sim.py   # Rule-based fallback
├── llm/
│   ├── adapter.py       # Multi-provider API client (OpenAI/DeepSeek/Tongyi/OpenRouter)
│   └── prompts.py       # System prompts for AI narrative
├── knowledge/data/
│   ├── characters.json  # Historical figures with personalities
│   ├── factions.json    # Playable factions with starting conditions
│   ├── regions.json     # Provinces with geography & resources
│   └── events.json      # Historical event timeline
├── cli/
│   └── app.py           # Rich terminal interface
└── docs/
    ├── PRD.md
    ├── tech-design.md
    └── marketing-growth.md
```

---

## 🔮 Roadmap

- [x] Core game engine (offline mode)
- [x] Three Kingdoms knowledge base (190 AD)
- [x] Rich terminal CLI
- [x] Multi-provider AI support (OpenAI, DeepSeek, Tongyi, OpenRouter)
- [ ] Save/load game system
- [ ] Web UI (map + controls)
- [ ] Steam release
- [ ] Modding system (custom scenarios)
- [ ] Multiplayer

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- 🐛 Found a bug? [Open an issue](https://github.com/emergencescience/histrategy/issues)
- 💡 Have an idea? Start a [discussion](https://github.com/emergencescience/histrategy/discussions)
- 🔧 Want to contribute? PRs are welcome!

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

*Built with ❤️ by [Emergence Science](https://emergence.science) — The Agent Economy Platform*
