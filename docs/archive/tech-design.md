# Histrategy Technical Design
> 三國志略 v0.3 — LLM-Native Historical Strategy Engine
> Last updated: 2026-05-24

---

## 1. Design Philosophy

### 1.1 Core Principles

1. **LLM as Game Master, not narrator** — The LLM drives consequences, not just prose. Templates are offline fallback only.
2. **Plan/Command separation** — Strategic thinking (WHAT) is separate from execution (HOW). Prevents blank-input paralysis.
3. **Offline-first, LLM-enhanced** — Always playable via `offline_sim.py`. Better with API key.
4. **Headless core** — The engine is UI-agnostic. Any UI (Rich TUI, Web, Voice, Discord) decorates the same `SimResult`.
5. **History + agency** — Real history creates weight. Player choices create meaning. Deviation is tracked and acknowledged.
6. **Lazy/responsive simulation** — Time only passes when the player acts. No cron jobs. Simulation runs inside the request handler.

### 1.2 AntiGravity Experience
> Players are strategists, not operators. Plan Mode = strategic council (what to do). Command Mode = bureaucracy execution (how it unfolds). Players should never feel like they are filling out a form.

### 1.3 Lessons from 《历史模拟器·崇祯》 (2026-05-08)
- Free-form natural language edicts work — but cause blank-box paralysis for new players → Plan Mode solves this
- Token-credit monetization causes community backlash → bring-your-own-API-key is our moat
- Single-era, single-LLM-provider limits reach → plugin architecture enables multi-era, multi-provider

---

## 2. Architecture

### 2.1 Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                   Decoration Layer (UIPlugin)              │
│   Rich TUI │ Web UI │ Voice │ Discord │ API Server         │
└────────────────────────┬──────────────────────────────────┘
                         │ SimResult (plain dataclass, JSON-serializable)
┌────────────────────────▼──────────────────────────────────┐
│               Game Engine (Orchestrator)                   │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Plan Mode  │  │ Command Mode│  │  WorldState Mgr  │  │
│  │ (GM + NPC   │  │ (GM + Seeds │  │  (load/save/     │  │
│  │  Interpreter│  │  + NPC      │  │   migrate)       │  │
│  │  + Arc Dir) │  │  reactions) │  │                  │  │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  │
│         │                │                  │             │
│  ┌──────▼──────────────────▼──────────────────▼─────────┐  │
│  │              WorldSimEngine (pluggable)               │  │
│  │   ResilientSimEngine                                  │  │
│  │     ├── LLMSimEngine (primary, requires API key)      │  │
│  │     └── OfflineSimEngine (fallback, always works)     │  │
│  └───────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼──────────────────────────────────┐
│                   LLM Layer                                │
│   GameMaster │ NPCInterpreter │ NarrativeDirector          │
│   PlayerProfiler │ RetrospectiveNarrator                   │
│   LLMAdapter (DeepSeek │ OpenAI │ Qwen │ OpenRouter)       │
└────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼──────────────────────────────────┐
│                   Knowledge Layer                          │
│   characters.json │ factions.json │ regions.json           │
│   events.json │ arc_goals.json │ npc_states.json (runtime) │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Turn Cycle

```
Player message received
         ↓
1. NarrativeDirector.get_pressure_hint(state)   # steer toward arc goals
         ↓
2. NPCInterpreter.update_npc_states(state, last_action)  # mood shifts
         ↓
3. GameMaster.generate_plan_mode(state, pressure_hint, npc_moods)
   → advisor speeches + 4 suggestions (LLM)
         ↓
4. Player input (choose suggestion or free-text)
         ↓
5. WorldSimEngine.simulate(state, player_decision)
   → ResilientSimEngine tries LLMSimEngine first
   → Falls back to OfflineSimEngine if LLM unavailable
         ↓
6. SimResult applied to WorldState → save to disk
         ↓
7. Check for: NPC drastic events, milestone retrospective, game over
         ↓
8. Return SimResult to UI layer for rendering
```

---

## 3. Key Data Structures

### 3.1 WorldState (`state/world_state.py`)

```python
@dataclass
class WorldState:
    year: int                          # 190 CE start
    season_index: int                  # 0-3 (spring/summer/autumn/winter)
    turn: int
    player_faction_id: str
    scenario: str                      # "190" = Yellow Turban era
    factions: dict[str, FactionState]
    characters: dict[str, CharacterState]
    territories: dict[str, TerritoryState]
    event_log: list
    completed_events: list[str]
    player_deviation: float            # 0.0 = pure historical, >0.40 = freeform
    schema_version: str = "0.3"       # for save migration
```

### 3.2 SimResult (`engine/world_sim_interface.py`)

```python
@dataclass
class SimResult:
    narrative: str                     # Main story text
    bureaucracy: list[dict]            # Execution report per department
    short_term: dict                   # Numeric state changes this turn
    seeds: list[dict]                  # Long-term consequences planted
    npc_reactions: list[str]           # Other factions' actions
    aftermath: str                     # 1-3 sentence consequence summary
    state_changes: dict                # Applied changes (for UI display)
    world_state: WorldState            # Updated state
    game_over: dict | None
```

### 3.3 NPCState (`state/npc_state.py`)

```python
class NPCMood(Enum):
    CONTENT = "content"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"
    LOYAL = "loyal"
    SCHEMING = "scheming"
    PLOTTING = "plotting"

@dataclass
class NPCState:
    character_id: str
    loyalty: int = 80              # 0-100
    mood: NPCMood = NPCMood.CONTENT
    grievance: str = ""            # One sentence: why they are unhappy
    key_events: list[str] = field(default_factory=list)  # ["turn_3_ignored"]
    is_plotting: bool = False
    turns_at_current_mood: int = 0
```

### 3.4 SimConfig (`config.py`)

```python
@dataclass
class SimConfig:
    context_mode: Literal["full", "compressed", "rag"] = "full"
    max_context_tokens: int = 4000
    historical_weight: float = 0.5    # 0.0 = ignore history, 1.0 = strict
    llm_model: str = ""               # "" = use adapter default
    show_token_cost: bool = False
    language: Literal["zh", "en"] = "zh"
```

---

## 4. LLM Integration

### 4.1 LLM Calls Per Turn

| Call | Class | Input Tokens | Output Tokens | Temp | Purpose |
|---|---|---|---|---|---|
| Plan Mode | `GameMaster` | ~2,000 | ~800 | 0.85 | Advisors + suggestions |
| Command Mode | `GameMaster` | ~1,800 | ~1,200 | 0.80 | Execution + seeds + NPC reactions |
| NPC Batch | `NPCInterpreter` | ~800 | ~400 | 0.60 | Mood updates for all NPCs |
| Arc Pressure | `NarrativeDirector` | ~400 | ~100 | 0.50 | Steering hint (cached 3 turns) |
| **Total/turn** | | **~5,000** | **~2,500** | | |

At DeepSeek-V3 pricing: **~$0.007/turn** with full richer context.
At reasoning LLM pricing: **~$0.05/turn** ceiling (player tolerance threshold).

### 4.2 Context Strategy

```
ALWAYS layer (~2,000 tokens):
  - System prompt
  - Current state digest: faction stats, season, turn
  - Last 3 player decisions

RETRIEVED layer (~1,500 tokens):
  - Relevant characters (mentioned in decision)
  - Active seeds (pending consequences)
  - NPC mood states
  - Historical timeline ±3 years

LONG_TERM (never in context, queryable):
  - Full event history → event_history.json
  - Full relationship graph → relationships.json
  - All decisions → player_memory.json
```

The RETRIEVED layer uses keyword matching (v0.3) and optional vector search (v0.5+).

### 4.3 JSON Output Enforcement

All LLM calls use `response_format={"type": "json_object"}` with explicit JSON schema in the system prompt. Fallback: retry once, then use offline result if parse fails.

---

## 5. Plugin Architecture

### 5.1 Plugin Types

```python
class PluginType(Enum):
    WORLD_ENGINE = "world_engine"   # Alternate simulation engine
    KNOWLEDGE    = "knowledge"      # Alternate history knowledge base
    NPC_AGENT    = "npc_agent"      # Alternate NPC behavior engine
    UI           = "ui"             # Alternate UI/rendering layer
    NARRATIVE    = "narrative"      # Alternate narrative director
```

### 5.2 Registration (pyproject.toml entry points)

```toml
# In a third-party plugin's pyproject.toml:
[project.entry-points."histrategy.plugins"]
rome = "histrategy_rome:RomePlugin"
```

### 5.3 Future Separate Repos

- **github.com/emergencescience/histrategy-history** — when >3 knowledge bases contributed
- **github.com/emergencescience/histrategy-world** — when >2 engine implementations contributed

---

## 6. File Layout

```
histrategy/
├── engine/
│   ├── game.py                    # Orchestrator (uses WorldSimEngine interface)
│   ├── world_sim_interface.py     # [NEW v0.3] Abstract WorldSimEngine + SimResult
│   ├── offline_sim_engine.py      # [NEW v0.3] OfflineSimEngine(WorldSimEngine)
│   ├── resilient_sim_engine.py    # [NEW v0.3] LLM→offline auto-fallback
│   ├── offline_sim.py             # Rule-based simulation (unchanged, used by OfflineSimEngine)
│   ├── narrative_director.py      # [NEW v0.3] Arc goal steering
│   ├── npc_events.py              # [NEW v0.3] Drastic NPC event triggers
│   ├── log_exporter.py            # [NEW v0.3] Game log export
│   └── plugin_registry.py         # [NEW v0.3] Plugin discovery
├── llm/
│   ├── game_master.py             # LLM Game Master (Plan + Command modes)
│   ├── llm_sim_engine.py          # [NEW v0.3] LLMSimEngine(WorldSimEngine) wrapper
│   ├── npc_interpreter.py         # [NEW v0.3] Tier 1 NPC batch interpreter
│   ├── player_profiler.py         # [NEW v0.4] Player style classifier
│   ├── retrospective.py           # [NEW v0.4] End-game historian narrator
│   ├── context_builder.py         # [NEW v0.4] Layered context construction
│   ├── cost_estimator.py          # [NEW v0.4] Token cost display
│   ├── adapter.py                 # Multi-provider LLM client (unchanged)
│   └── world_model.py             # Legacy (kept for intro generation)
├── state/
│   ├── world_state.py             # WorldState + FactionState + save/load
│   ├── npc_state.py               # [NEW v0.3] NPCState + mood enum
│   └── player_profile.py          # [NEW v0.4] PlayerProfile + playstyle
├── plugins/
│   ├── __init__.py                # [NEW v0.3] PluginType + base ABCs
│   ├── interface.py               # [NEW v0.3] WorldEnginePlugin, KnowledgePlugin
│   └── registry.py                # [NEW v0.3] discover_plugins()
├── config.py                      # [NEW v0.4] SimConfig dataclass
├── cli/
│   ├── app.py                     # Rich TUI
│   └── dev_cli.py                 # Plain-text dev mode
└── knowledge/
    ├── data/
    │   ├── arc_goals.json         # [NEW v0.3] Narrative arc goals (historical beats)
    │   ├── characters.json
    │   ├── factions.json
    │   ├── regions.json
    │   └── events.json
    └── scripts/
        └── validate_data.py
```

### Runtime Save Files (`~/.histrategy/`)

```
~/.histrategy/
├── world_state.json          # Complete game state (schema_version tracked)
├── npc_states.json           # [NEW v0.3] NPC emotional states
├── player_memory.json        # Player decisions history
├── relationships.json        # Faction relationship matrix
├── event_history.json        # Full chronological event log
├── pending_seeds.json        # Long-term consequence seeds
├── player_profile.json       # [NEW v0.4] Inferred playstyle
├── config.json               # [NEW v0.4] SimConfig overrides
└── logs/
    └── YYYY-MM-DD-{faction}.json  # [NEW v0.3] Exported game logs
```

---

## 7. Save Migration

Schema versions are tracked in `world_state.json`:
```json
{"schema_version": "0.3", ...}
```

Migration handlers in `state/migrations.py`:
```python
MIGRATIONS = {
    "0.1": migrate_v0_1_to_v0_2,
    "0.2": migrate_v0_2_to_v0_3,
}
```

On load, `load_world()` applies all pending migrations before returning.

---

## 8. Testing Strategy

| Layer | Test File | Coverage Target |
|---|---|---|
| WorldSimEngine interface | `tests/test_world_sim_engine.py` | Interface contract, resilient fallback |
| NPC state machine | `tests/test_npc_state.py` | Mood transitions, warning surface |
| Narrative director | `tests/test_narrative_director.py` | Pressure hint, arc completion |
| Historical mode | `tests/test_historical_mode.py` | Transition thresholds, prompt selection |
| Log exporter | `tests/test_log_exporter.py` | JSON schema, markdown output |
| Plugin registry | `tests/test_plugins.py` | Discovery, interface compliance |
| E2E (all factions) | `tests/test_e2e.py` | 5+ turns, no crash, offline mode works |

Run all tests: `pytest tests/ -v`
