# Show HN 投稿草稿

**Title**: Show HN: Histrategy – Open-source AI history strategy game (Three Kingdoms, 190 AD)

**URL**: https://github.com/emergencescience/histrategy

**Text** (optional):

I built an open-source, AI-powered history strategy game that runs in your terminal.

You play as a warlord in 190 AD China (Three Kingdoms era). Each turn, you make strategic decisions in natural language — the AI generates consequences, NPC factions react, and historical events unfold.

```
pip install histrategy
# or just:
git clone https://github.com/emergencescience/histrategy
cd histrategy && pip install -e .
histrategy  # offline mode (no API key needed)
```

**Try the AI mode** (if you have an API key):
```bash
export DEEPSEEK_API_KEY='sk-...'
histrategy
```

Supports: OpenAI, DeepSeek, Tongyi (Qwen), OpenRouter — auto-detects from env vars.

Features:
- AI-generated narrative that adapts to your decisions
- Historical events (讨董联盟, 迁都长安, and more)
- NPC factions with personality-driven behavior
- Offline mode with event-chain narratives
- Knowledge-driven simulation (20+ historical characters with personalities)
- Memory system (game remembers your past decisions)

Tech stack: Python, Rich CLI, httpx, Pydantic. MIT licensed.

---
