# Histrategy Roadmap
> 三國志略 — Open-Source Physics-Driven Historical Strategy Game
> Last updated: 2026-06-07

---

## Vision

An open-source, extensible LLM-native historical strategy game engine.
- **For players**: Planning + execution (AntiGravity experience) with real historical weight
- **For developers**: A plugin architecture usable for any strategic game era (Rome, Red Alert, etc.)
- **For researchers**: A documented experiment in LLM narrative game design
- **For learners**: History for kids, strategy for adults

Differentiator vs 《历史模拟器·崇祯》: Open-source, bring-your-own-API-key, multi-provider, multi-era, offline-first.

---

## Epic Overview

| Epic | Description | Status | Phase |
|---|---|---|---|
| **E1** | WorldSimEngine plugin interface + resilient failover | 🔴 Not started | v0.3 |
| **E2** | NPC emotional state + Tier 1 LLM NPC interpreter | 🔴 Not started | v0.3 |
| **E3** | Narrative Arc Director (goal-oriented steering) | 🔴 Not started | v0.3 |
| **E4** | Historical mode switching + deviation acknowledgment | 🔴 Not started | v0.3 |
| **E5** | Game log export + community contribution pipeline | 🟡 Partial | v0.3 |
| **E6** | SimConfig: context mode, token tuning, cost display | 🔴 Not started | v0.4 |
| **E7** | Player style profiling + personalized advisors | 🔴 Not started | v0.4 |
| **E8** | Retrospective narrator (end-of-game historian) | 🔴 Not started | v0.4 |
| **E9** | Extensibility: plugin discovery, CONTRIBUTING update | 🔴 Not started | v0.4 |
| **E10** | Web UI (headless core decoration) | 🔴 Not started | v0.5 |
| **E11** | Voice interaction layer | 🔴 Not started | v0.6 |
| **E12** | Multiplayer / async turn architecture | 🔴 Not started | v0.6 |
| **E13** | histrategy-history separate repo | 🔴 Not started | v0.6+ |
| **E14** | histrategy-world separate repo | 🔴 Not started | v0.6+ |
| **E15** | Academic paper: design-iterations.md | 🔴 Not started | Ongoing |

---

## v0.3 Sprint (Current — P0/P1)

**Goal**: Solid engine foundation with NPC drama and narrative steering.

### E1: WorldSimEngine Plugin Interface

**Why first**: Everything else (NPC plugins, Rome plugin, custom engines) requires this interface to exist.

| Task | File | Est. | Notes |
|---|---|---|---|
| E1.1 | Create `histrategy/engine/world_sim_interface.py` — abstract `WorldSimEngine` + `SimResult` | `engine/world_sim_interface.py` | 1h | ABC with `simulate()`, `requires_llm` |
| E1.2 | Wrap `game_master.py` as `LLMSimEngine(WorldSimEngine)` | `llm/llm_sim_engine.py` | 1h | Thin wrapper |
| E1.3 | Wrap `offline_sim.py` as `OfflineSimEngine(WorldSimEngine)` | `engine/offline_sim_engine.py` | 30m | Thin wrapper |
| E1.4 | Create `ResilientSimEngine` — LLM → offline fallback at engine level | `engine/resilient_sim_engine.py` | 30m | Transparent to game loop |
| E1.5 | Update `engine/game.py` to use `WorldSimEngine` interface | `engine/game.py` | 30m | Decouple from concrete impl |
| E1.6 | Plugin discovery via `importlib.metadata` entry points | `engine/plugin_registry.py` | 1h | |
| E1.7 | Tests for engine interface + resilient fallback | `tests/test_world_sim_engine.py` | 1h | |

**Total E1 estimate**: 5.5h dev, ~50K tokens (claude dev)

---

### E2: NPC Emotional State + Tier 1 Interpreter

**Why now**: Enables advisor loyalty, betrayal arcs, court drama — highest player drama ROI.

| Task | File | Est. | Notes |
|---|---|---|---|
| E2.1 | Design `NPCState` dataclass: `loyalty`, `mood` (enum 6), `grievance`, `key_events`, `is_plotting` | `state/npc_state.py` | 30m | |
| E2.2 | Add `npc_states.json` to `~/.histrategy/` save format | `state/world_state.py` | 30m | load/save hooks |
| E2.3 | `NPCInterpreter` class — one batch LLM call covers all NPCs | `llm/npc_interpreter.py` | 1.5h | System prompt + JSON output |
| E2.4 | Mood shift rules: max 1 level/turn, warning at danger threshold | `llm/npc_interpreter.py` | 30m | |
| E2.5 | Warning surfacing in Plan Mode — advisors hint at dissatisfied NPCs | `llm/game_master.py` | 30m | Inject NPC mood context |
| E2.6 | Drastic NPC events: defection, betrayal, self-action | `engine/npc_events.py` | 1h | Triggered when mood hits bottom |
| E2.7 | Tests: mood transitions, warning surface, betrayal trigger | `tests/test_npc_state.py` | 1h | |

**Total E2 estimate**: 5.5h dev, ~60K tokens

---

### E3: Narrative Arc Director

**Why now**: Prevents "aimless world" — history should feel inevitable without railroading.

| Task | File | Est. | Notes |
|---|---|---|---|
| E3.1 | `ArcGoal` dataclass: event name, deadline turn, gravity weight | `engine/narrative_director.py` | 30m | |
| E3.2 | `NarrativeDirector` class: track arc goals, compute pressure hint | `engine/narrative_director.py` | 1h | |
| E3.3 | Define default Three Kingdoms arc goals from `events.json` | `knowledge/data/arc_goals.json` | 30m | Red Cliffs by turn 25, etc. |
| E3.4 | Inject pressure hint into GameMaster Plan prompt | `llm/game_master.py` | 30m | One sentence steering hint |
| E3.5 | Tests: pressure hint generation, arc completion tracking | `tests/test_narrative_director.py` | 45m | |

**Total E3 estimate**: 3.25h dev, ~25K tokens

---

### E4: Historical Mode Switching

| Task | File | Est. | Notes |
|---|---|---|---|
| E4.1 | `HistoricalMode` enum: HISTORICAL / DIVERGENT / FREEFORM | `state/world_state.py` | 15m | |
| E4.2 | Mode transition logic based on `player_deviation` thresholds (0.15 / 0.40) | `state/world_state.py` | 30m | |
| E4.3 | Mode-specific GameMaster prompt framing (three system prompt variants) | `llm/game_master.py` | 45m | |
| E4.4 | Divergence acknowledgment: "史官将把这记为'建安异录'" | `llm/game_master.py` | 30m | Trigger on mode change |
| E4.5 | Tests: mode transitions, prompt selection | `tests/test_historical_mode.py` | 30m | |

**Total E4 estimate**: 2.5h dev, ~20K tokens

---

### E5: Game Log Export

| Task | File | Est. | Notes |
|---|---|---|---|
| E5.1 | `--export-log` CLI flag | `cli/app.py`, `__main__.py` | 30m | |
| E5.2 | `GameLogExporter` — structured JSON + Markdown formats | `engine/log_exporter.py` | 1h | |
| E5.3 | Log schema: version, faction, turns[], outcome, final_score | `engine/log_exporter.py` | 30m | |
| E5.4 | Auto-save log every 10 turns (periodic checkpoint) | `engine/game.py` | 30m | |
| E5.5 | Tests: log output format validation | `tests/test_log_exporter.py` | 30m | |

**Total E5 estimate**: 3h dev, ~20K tokens

---

## v0.4 Sprint (Next)

### E6: SimConfig — Context Mode + Token Tuning

| Task | File | Est. | Notes |
|---|---|---|---|
| E6.1 | `SimConfig` dataclass: `context_mode` (full/compressed/rag), `max_context_tokens`, `historical_weight`, `llm_model` | `config.py` | 45m | |
| E6.2 | `~/.histrategy/config.json` load/save | `config.py` | 30m | |
| E6.3 | `histrategy --config` interactive config command | `cli/app.py` | 1h | |
| E6.4 | Token cost estimator: display estimated $/turn before each session | `llm/cost_estimator.py` | 1h | |
| E6.5 | Compressed context mode: digest world state to ~200 tokens | `llm/context_builder.py` | 1.5h | |
| E6.6 | Tests: config load/save, cost estimation | `tests/test_config.py` | 45m | |

**Total E6 estimate**: 5.5h dev, ~40K tokens

---

### E7: Player Style Profiling

| Task | File | Est. | Notes |
|---|---|---|---|
| E7.1 | `PlayerProfile` dataclass: `playstyle` enum, `decision_history_summary`, `turn_count` | `state/player_profile.py` | 30m | |
| E7.2 | Classification call every 5 turns — LLM infers playstyle from decision history | `llm/player_profiler.py` | 1h | |
| E7.3 | Inject profile into Plan Mode prompt — adapt advisor tone | `llm/game_master.py` | 30m | |
| E7.4 | Tests | `tests/test_player_profile.py` | 30m | |

**Total E7 estimate**: 2.5h dev, ~15K tokens

---

### E8: Retrospective Narrator

| Task | File | Est. | Notes |
|---|---|---|---|
| E8.1 | `RetrospectiveNarrator` — single LLM call at game end | `llm/retrospective.py` | 1h | |
| E8.2 | Historian persona prompt: references player deviation, specific decisions | `llm/retrospective.py` | 30m | |
| E8.3 | Milestone retrospectives (every 10 turns, on major events) | `llm/retrospective.py` | 30m | |
| E8.4 | Tests | `tests/test_retrospective.py` | 30m | |

**Total E8 estimate**: 2.5h dev, ~15K tokens

---

### E9: Extensibility + CONTRIBUTING

| Task | File | Est. | Notes |
|---|---|---|---|
| E9.1 | `histrategy/plugins/__init__.py` — `PluginType` enum, base classes | `plugins/interface.py` | 1h | |
| E9.2 | Plugin registry: `discover_plugins()` via entry points | `plugins/registry.py` | 30m | |
| E9.3 | Update `CONTRIBUTING.md` — WorldEngine plugin, Knowledge plugin sections | `CONTRIBUTING.md` | 1h | |
| E9.4 | Example plugin: `examples/rome_knowledge_plugin/` stub | `examples/` | 1h | |
| E9.5 | Tests: plugin discovery, interface compliance | `tests/test_plugins.py` | 45m | |

**Total E9 estimate**: 4.25h dev, ~30K tokens

---

## v0.5+ (Future)

### E10: Web UI
- Next.js app wrapping headless `GameMaster` via REST API
- Plan Mode: advisor cards, suggestion chips
- Command Mode: bureaucracy execution stream
- Historical deviation timeline visualization
- **Est**: 2 weeks, separate repo `histrategy-web`

### E11: Voice Interaction Layer
- TTS (Chinese) for advisor speeches and narration
- STT for player decisions (kids mode)
- `UIPlugin` ABC for all decoration layers
- **Est**: 1 week after E10

### E12: Multiplayer / Async Turns
- Each player controls one faction
- Lazy simulation: all factions commit decisions, then world advances once
- No new engine changes needed (lazy design is already multiplayer-compatible)
- **Est**: 1 week

### E13: histrategy-history (Separate Repo)
- When `knowledge/data/` grows beyond Three Kingdoms (Rome, other eras)
- `KnowledgePlugin` interface already defined in E9
- **Trigger**: > 3 contributed knowledge bases

### E14: histrategy-world (Separate Repo)
- When multiple `WorldEnginePlugin` implementations exist (Agent-NPC engine, Cron engine)
- `WorldSimEngine` interface already defined in E1
- **Trigger**: > 2 contributed engine implementations

### E15: Academic Paper
- Ongoing: maintain `docs/design-iterations.md`
- Target venue: AIIDE, FDG, or CHI (games track)
- Draft: 3 months after v0.4 ships

---

## Token & Time Cost Estimates

### Development Cost (claude --model deepseek-v4-pro)

| Epic | Dev Hours | Est. Tokens | Est. $ (deepseek-v4-pro) |
|---|---|---|---|
| E1: WorldSimEngine interface | 5.5h | 50K | ~$0.15 |
| E2: NPC emotional state | 5.5h | 60K | ~$0.18 |
| E3: Narrative arc director | 3.25h | 25K | ~$0.08 |
| E4: Historical mode switching | 2.5h | 20K | ~$0.06 |
| E5: Game log export | 3h | 20K | ~$0.06 |
| E6: SimConfig + token tuning | 5.5h | 40K | ~$0.12 |
| E7: Player profiling | 2.5h | 15K | ~$0.05 |
| E8: Retrospective narrator | 2.5h | 15K | ~$0.05 |
| E9: Plugin extensibility | 4.25h | 30K | ~$0.09 |
| **v0.3 total (E1-E5)** | **19.75h** | **175K** | **~$0.53** |
| **v0.4 total (E6-E9)** | **14.75h** | **100K** | **~$0.31** |

### Runtime Cost Per Game Session

| Context Mode | Tokens/Turn | Cost/Turn (DeepSeek-V3) | 50-turn game |
|---|---|---|---|
| `full` (current) | ~2,600 | $0.002 | ~$0.10 |
| `full` + richer context | ~8,000 | $0.007 | ~$0.35 |
| `full` + reasoning LLM (DeepSeek-R2 class) | ~8,000 | $0.05 | ~$2.50 |
| `compressed` | ~1,600 | $0.001 | ~$0.06 |

Players tolerate ~$0.05/turn for reasoning LLMs — this is the target ceiling per SimConfig docs.

---

## Milestone Summary

| Version | Key Features | ETA |
|---|---|---|
| **v0.3** | WorldSimEngine interface, NPC drama, Narrative arc, Log export | 1 week |
| **v0.4** | Token config, player profiling, retrospective, plugins | 2 weeks |
| **v0.5** | Web UI | +2 weeks |
| **v0.6** | Voice, multiplayer | +2 weeks |
| **paper** | Academic preprint | +3 months from v0.4 |
