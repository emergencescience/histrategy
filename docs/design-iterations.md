# Design Iterations
> 三國志略 — LLM Narrative Game Design Evolution
> Maintained for academic paper source material

---

## Why This Document Exists

This log records *why* the design changed, not just *what* changed. It is the raw material for:
1. The planned academic paper on extensible LLM narrative strategy engines
2. Future contributors understanding architectural decisions
3. The community understanding our design philosophy experiments

---

## Iteration Log

### v0.1 — Template Engine + LLM Narration (2026-05-22)

**Architecture**: Python string templates + `random.choice()` → LLM writes pretty text over pre-computed outcomes.

**Problem observed**:
- Player input classified into 5 buckets (economy/military/diplomacy/spy/domestic)
- Template response regardless of specific words used
- Players reported: "I couldn't feel my decisions mattered"
- Advisor speeches: hardcoded `.format()` strings in `advisors.py`
- Consequences: formulaic `command.py` with hardcoded effects tables

**Key insight**: LLM was narrating *over* the simulation, not *driving* it. The template-vs-LLM conflict produced generic outcomes even when the LLM wrote beautiful prose.

**Source validation**: Gallotta et al. (2024) — "Hybrid architecture (rules + LLM) outperforms pure LLM on coherence" — but this only holds when the rules system is rich enough to generate meaningful state. Our rule system was too shallow.

---

### v0.2 — LLM IS the Engine (2026-05-23)

**Architecture**: Delete `advisors.py` (379 lines of templates), delete `command.py` (306 lines). LLM generates all advisor speeches, suggestions, consequences, NPC reactions at runtime.

**Changes**:
- New: `llm/game_master.py` — `GameMaster` with `generate_plan_mode()` and `generate_command_mode()`
- New: Plan/Command two-phase architecture (see below)
- Preserved: `offline_sim.py` as fallback when no API key

**Plan/Command split rationale** (from Nottingham 2024):
- Single input box ("你的战略决策：") caused player choice paralysis
- "Too many choices feels like work" — Nottingham on AI NPC overload
- Solution: Plan Mode = structured council (guided), Command Mode = free execution (open)

**Key design decision**: Free-text input only in Command Mode. No numbered menus at execution stage. LLM interprets intent from natural language.

**Problem remaining**: World simulation is reactive but not *steered*. Nothing ensures historically interesting events occur. Risk of "aimless world."

---

### v0.3 — Plugin Architecture + NPC Drama + Narrative Steering (2026-05-24)

**Architecture**: `WorldSimEngine` abstract interface → `LLMSimEngine` + `OfflineSimEngine` + `ResilientSimEngine`. NPC emotional state JSON. `NarrativeDirector` arc steering.

**Key additions**:

**WorldSimEngine interface** — Enables any game (Rome, Red Alert) to use the engine. Separates the simulation contract from the implementation. Inspired by: user request to make this reusable for other historical games.

**Lazy/responsive simulation** — Drop cron jobs. Simulate only on player message. Time is paused between player interactions.
- Rationale: No race conditions, trivially testable, multiplayer-compatible by design
- Precedent: AI Dungeon, Civilization PBEM, roguelikes

**NPC emotional state (Tier 1)** — Stateful profiles (`loyalty`, `mood` enum, `grievance`) + single batch LLM call per turn covers all NPCs. Max 1 mood level change per turn + warning before drastic action.
- Rationale: Full LLM agent loops for NPCs are too expensive (~$0.10/NPC/turn) and inconsistent. Stateful profiles + LLM interpretation gives 80% of the drama at 5% of the cost.
- Concern addressed: "I worry the LLM agent NPC is too complicated" — bounded mood enums + slow change + warnings prevent surprise betrayals.

**Historical modes** — HISTORICAL (deviation < 0.15) / DIVERGENT (0.15-0.40) / FREEFORM (>0.40). Historical events as "gravity wells." Player divergence is explicitly acknowledged ("史官将把这记为'建安异录'").
- Rationale: The 50/20 ratio (50% historical events occur, 20%+ player divergence possible) is a tunable starting point, not a fixed rule. Dynamic modes replace the static ratio.

**Token cost analysis**:
- File-based (current): ~2,600 tokens/turn → $0.002/turn (DeepSeek-V3)
- Rich context target: ~8,000 tokens/turn → $0.007/turn
- Reasoning LLM ceiling: ~$0.05/turn (player tolerance threshold)
- Recommendation: Make `context_mode` a player-tunable parameter

**Extensibility design**:
- Plugin types: WORLD_ENGINE, KNOWLEDGE, NPC_AGENT, UI, NARRATIVE
- Discovery: Python entry points (`importlib.metadata`)
- Future repos: `histrategy-history` (when >3 knowledge bases), `histrategy-world` (when >2 engine implementations)
- Inspired by: user request to support Rome strategic game, Red Alert, etc.

**Game log contribution**:
- `--export-log` dumps structured JSON session log
- Community log gallery (future website) for sharing alternate histories
- Developer "sense reports" via GitHub Issues `game-sense` label → DevOps LLM agent training signal

**Educational positioning** (new):
- History learner (kids): historical footnotes, guided mode, voice narration
- Strategy thinker (adults): deviation analytics, expert mode, replay/compare
- Inspired by: 《历史模拟器·崇祯》 success on Steam showing the market exists

**Headless core**:
- `SimResult` is a plain dataclass, JSON-serializable
- Any UI (Rich TUI, Web, Voice, Discord) decorates the same interface
- `UIPlugin` ABC defined for future decoration layers

---

## Open Research Questions

These are the unresolved questions that would make good paper contributions:

1. **Optimal context window strategy**: At what game turn does file-based context exceed quality, and what's the accuracy loss from compression? (Needs playtesting data)

2. **Historical deviation calibration**: What `deviation_discount` makes historical events feel inevitable but not forced? (Needs A/B testing with different player groups)

3. **NPC mood change rate**: Is 1 level/turn too slow (boring) or too fast (jarring)? (Needs playtesting)

4. **Plan Mode suggestion quality**: Do 4 suggestions reduce player agency or enhance it? Do expert players use free-text more than novices? (Needs analytics)

5. **Narrative arc pressure**: How much steering hint is enough vs. railroading? (Needs qualitative player feedback)

6. **Educational effectiveness**: Does the historical footnote mode improve historical knowledge retention vs. no-game control group? (Needs study design)

---

## References

- Nottingham, K. (2024). "A Closer Look at LLMs and Games." UCI Blog.
- Gallotta et al. (2024). "Large Language Models and Games: A Survey and Roadmap." Malta/NYU.
- 青干工作室 (2026). "历史模拟器：崇祯." Steam. (Commercial LLM-native historical strategy reference)
- AI Dungeon (Latitude, 2019-present). (Ungrounded open-world LLM narrative reference)
- Orkin, J. (2003). "Applying Goal-Oriented Action Planning to Games." GDC.
