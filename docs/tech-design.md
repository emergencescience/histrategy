# Tech Design: 三國志略 (Histrategy)

> **Status**: Draft v0.1
> **Owner**: Prometheus (Hermes Agent)
> **Date**: 2026-05-23
> **Based on**: PRD v0.1

---

## 1. Architecture Overview

### 1.1 System Context

```
┌─────────────────────────────────────────────────────────────┐
│                         Player                              │
│              (Terminal / Browser / Steam)                    │
└──────────┬──────────────────────────────────────┬──────────┘
           │ 自然语言 / 选项选择                      │
           ▼                                        ▼
┌──────────────────────┐              ┌──────────────────────┐
│    CLI (Rich)         │              │  Web UI (Phase 2)    │
│  - ASCII art 界面     │              │  - 地图渲染           │
│  - 交互式选择器       │              │  - 操作面板           │
│  - 历史日志滚动       │              │  - 势力关系图         │
└──────────┬───────────┘              └──────────┬───────────┘
           │                                      │
           └──────────────┬───────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                    Game Engine (Core)                        │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │ Game World   │  │ Game Loop     │  │ Offline Simulator │   │
│  │ (State Mgmt) │  │ (Orchestrator)│  │ (Rule-based)      │   │
│  └──────┬──────┘  └──────┬───────┘  └───────────────────┘   │
│         │                │                                    │
│         ▼                ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               LLM Adapter Layer                       │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │    │
│  │  │ OpenAI   │ │ DeepSeek │ │ Tongyi   │ │OpenRouter│ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                     │
│                         ▼                                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Knowledge Base (Structured)               │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │    │
│  │  │Characters│ │ Factions │ │ Regions  │ │ Events  │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 Layered Architecture

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **Interface** | `cli/` | 用户交互 (Rich terminal / Web) |
| **Orchestration** | `engine/game.py` | 游戏循环、回合管理、模式选择 |
| **State** | `engine/world.py` | 世界模型 (Character/Faction/Region/Event) |
| **Simulation** | `engine/offline_sim.py` | 离线规则引擎 (无 AI) |
| **AI** | `llm/` | LLM Adapter + Prompt 工程 |
| **Knowledge** | `knowledge/` | 结构化历史数据 (JSON) |

---

## 2. Data Model

### 2.1 Core Entities (Current)

```python
@dataclass
class Character:
    id: str
    name: str                    # 中文名 (e.g., "曹操")
    alias: str                   # 字 (e.g., "孟德")
    title: str                   # 官职 (e.g., "丞相")
    faction: str                 # faction_id
    personality: list[str]       # ["枭雄", "多疑", "知人善任"]
    skills: list[str]            # ["军事", "政治", "文学"]
    description: str
    birth: Optional[int]
    death: Optional[int]
    is_alive: bool = True
    loyalty: int = 70            # 0-100

@dataclass
class Faction:
    id: str
    name: str                    # e.g., "曹魏"
    ruler_id: Optional[str]      # character id
    color: str                   # terminal color
    capital: str                 # region id
    territories: list[str]       # region ids
    strength: int                # 兵力 0-100
    economy: int                 # 经济 0-100
    morale: int                  # 民心 0-100
    intel_level: int             # 情报 0-100
    aggression: int              # 侵略性 0-100
    diplomacy_tendency: str      # e.g., "扩张", "守成"
    treasury: int = 10000
    food: int = 5000

@dataclass
class Region:
    id: str
    name: str
    capital: str
    description: str
    strategic_value: int         # 1-10
    resources: list[str]
    neighbors: list[str]
    owner: str = ""              # faction_id
    development: int = 50        # 0-100
    garrison: int = 0
    loyalty: int = 60            # 0-100

@dataclass
class HistoricalEvent:
    year: int
    season: str
    title: str
    description: str
    trigger: str                 # "game_start" | "year_season" | "faction_condition"
    effects: dict                # state mutations
    is_historical: bool          # True=fixed timeline, False=AI-generated
    has_occurred: bool = False
```

### 2.2 State Machine

```
GameWorld
├── scenario: str (e.g., "190")
├── current_year: int (190 start)
├── current_season: str ("spring" | "summer" | "autumn" | "winter")
├── season_index: int (0-3)
├── turn_count: int
├── player_faction_id: Optional[str]
├── characters: dict[str, Character]
├── factions: dict[str, Faction]
├── regions: dict[str, Region]
├── events: list[HistoricalEvent]
├── completed_events: list[str]
└── history_log: list[str]        # AI-generated narrative log
```

---

## 3. LLM Integration

### 3.1 Multi-Provider Adapter

```python
class LLMAdapter:
    """OpenAI-compatible API adapter with multi-provider support."""
    
    # Priority: DeepSeek > OpenAI > Custom API Base > Tongyi
    PROVIDER_CONFIGS = {
        "deepseek": {
            "env_key": "DEEPSEEK_API_KEY",
            "env_base": None,  # defaults
            "default_base": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
        },
        "openai": {
            "env_key": "OPENAI_API_KEY",
            "env_base": "OPENAI_API_BASE",
            "default_base": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
        },
        "tongyi": {
            "env_key": "TONGYI_API_KEY",
            "env_base": None,
            "default_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "default_model": "qwen-max",
        },
        "openrouter": {
            "env_key": "OPENROUTER_API_KEY",
            "env_base": None,
            "default_base": "https://openrouter.ai/api/v1",
            "default_model": "deepseek/deepseek-r1",
        },
    }
```

**Auto-detect flow**:
1. Scan env vars in priority order
2. First provider with a valid-looking key wins
3. User can override with `LLM_PROVIDER=deepseek` env var
4. README provides setup instructions for each provider

### 3.2 API Call Modes

| Mode | API Calls per Turn | Cost Profile | Quality |
|------|-------------------|--------------|---------|
| **Offline** | 0 | Free | Basic templates |
| **Narrative** | 1 (narrative generation) | Low | Good storytelling |
| **Full AI** | 3-5 (NPC actions × N + narrative + state updates) | Medium-High | Best immersion |

### 3.3 Prompt Architecture

#### System Prompt Template
```
你是{game_name}的AI游戏主持人，负责模拟{scenario}历史时期。

【当前世界状态】
{world_state_summary}

【你的职责】
1. 作为游戏主持人，生成身临其境的历史叙事
2. 模拟NPC势力的战略决策
3. 评估玩家决策的后果
4. 确保历史准确性，但允许"what-if"偏离

【输出格式】
你必须以JSON格式输出：
{
  "narrative": "叙事文本...",
  "state_changes": { "strength": 85, "economy": 60, ... },
  "npc_actions": [
    { "faction": "袁绍", "action": "攻占许昌", "reason": "..." }
  ],
  "events_triggered": ["讨董联盟"],
  "next_options": ["选项1", "选项2", "选项3"]
}
```

### 3.4 Structured Output Guarantee

Using OpenAI-compatible `response_format` (JSON mode) + Pydantic validation:

```python
class AIOutput(BaseModel):
    narrative: str = Field(..., min_length=20, max_length=2000)
    state_changes: dict = Field(default_factory=dict)
    npc_actions: list[dict] = Field(default_factory=list)
    events_triggered: list[str] = Field(default_factory=list)
    next_options: list[str] = Field(..., min_length=2, max_length=5)
```

Fallback: if JSON mode unavailable (some providers), use regex extraction + Pydantic validation with retry.

---

## 4. Game Loop (Detailed)

```
1. SEASON_START
   ├── Load/validate game state
   ├── Check historical events for trigger
   ├── AI: Generate season report (world state + narrative)
   └── Display to player

2. PLAYER_INPUT
   ├── Show options (numbered) + free-text input
   ├── Parse: AI interprets natural language → structured action
   └── Validate against game rules

3. SIMULATION
   ├── AI: Generate narrative consequences
   ├── Engine: Apply state changes (numerical effects)
   ├── AI: Generate NPC actions (for each active faction)
   ├── Engine: Check event triggers
   └── Log to history

4. SEASON_END
   ├── Update all faction states
   ├── Check win/loss conditions
   ├── Check AI NPC wars/diplomacy
   ├── Auto-save
   └── Advance turn → loop to step 1
```

### State Validation Constraints

```python
# All state values must pass validation
STATE_CONSTRAINTS = {
    "strength": (0, 100),     # 兵力
    "economy": (0, 100),      # 经济
    "morale": (0, 100),       # 民心
    "treasury": (0, None),    # 资金 (无上限)
    "food": (0, None),        # 粮草
    "loyalty": (0, 100),      # 人物忠诚
    "development": (0, 100),  # 区域开发度
    "garrison": (0, None),    # 驻军
}
```

AI returning values outside bounds → clamped silently, logged as `[WARN] AI returned out-of-bounds value`.

---

## 5. Knowledge Base Design

### 5.1 Current State

| Dataset | Count | Format |
|---------|-------|--------|
| Characters | 20 | JSON |
| Factions | 8 | JSON |
| Regions | 19 | JSON |
| Events | 5 | JSON |

### 5.2 Phase 1 Target

| Dataset | Target | Notes |
|---------|--------|-------|
| Characters | 50+ | Add 荀彧, 郭嘉, 周瑜, 鲁肃, 法正, 庞统, 张飞, 赵云... |
| Factions | 12+ | Split 张绣, 张鲁, 吕布, 刘璋, 马腾, 陶谦... |
| Regions | 30+ | More granular: 汝南, 新野, 襄阳, 江陵, 合肥... |
| Events | 20+ | Key historical milestones through 220 AD |
| Relationships | 30+ | Character affinity/loyalty/trust matrix |

### 5.3 Data Quality Rules

- Historical accuracy: cross-referenced with《三国志》《资治通鉴》
- AI prompt context: knowledge JSON is injected into system prompt at each turn
- Player-facing locale: character descriptions and event narratives in Chinese
- Extensibility: schema should support adding new scenarios without breaking existing ones

---

## 6. Save/Load System

### 6.1 Design

```python
@dataclass
class SaveGame:
    version: str = "1.0"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    scenario: str
    player_faction: str
    turn: int
    world_state: GameWorld    # serialized as dict
    history_log: list[str]
    metadata: dict = field(default_factory=dict)
```

- Format: JSON (human-readable, debuggable)
- Location: `~/.histrategy/saves/<scenario>-<timestamp>.json`
- Auto-save: after each turn (keep last 5)
- Compression: optional gzip for large saves (Phase 2)

---

## 7. Multi-Provider LLM Strategy

### 7.1 Smart Model Routing

| Task | Recommended Model | Rationale |
|------|------------------|-----------|
| Narrative generation | DeepSeek V4 / GPT-4o-mini | Good storytelling, low cost |
| NPC strategy simulation | GPT-4o / Claude Sonnet | Complex reasoning needed |
| State calculation | Offline engine | Deterministic, zero cost |
| Event generation | DeepSeek V4 | Creative, medium cost |

### 7.2 Cost Optimization

```python
# Tiered approach
if self.mode == "offline":
    return offline_simulate()          # $0
elif self.mode == "narrative":
    return llm_chat(cheap_model=True)  # ~$0.001/turn
elif self.mode == "full_ai":
    return llm_chat(full_pipeline=True) # ~$0.01/turn
```

### 7.3 Provider Detection

Auto-detection at startup:
1. Check `DEEPSEEK_API_KEY` → use DeepSeek
2. Check `OPENAI_API_KEY` → use OpenAI
3. Check `TONGYI_API_KEY` → use 通义千问
4. Check `OPENROUTER_API_KEY` → use OpenRouter
5. None → Offline mode

---

## 8. Directory Structure (Phase 1)

```
histrategy/
├── histrategy/
│   ├── __init__.py
│   ├── __main__.py            # Entry point
│   ├── cli/
│   │   ├── __init__.py
│   │   └── app.py             # Rich terminal UI
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── world.py           # Game state model
│   │   ├── game.py            # Game orchestrator
│   │   ├── offline_sim.py     # Rule-based fallback
│   │   └── save.py            # Save/Load system (NEW)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── adapter.py         # Multi-provider adapter (UPDATED)
│   │   └── prompts.py         # System prompts
│   ├── knowledge/
│   │   ├── __init__.py
│   │   └── data/
│   │       ├── characters.json
│   │       ├── factions.json
│   │       ├── regions.json
│   │       └── events.json
│   └── utils/
│       ├── __init__.py
│       └── config.py          # Env config + provider detection (NEW)
├── docs/
│   ├── PRD.md                 # ✅ (this)
│   ├── tech-design.md         # (you are here)
│   └── marketing-growth.md    # (forthcoming)
├── data/                      # Game data (not code)
├── tests/                     # Pytest (Phase 1)
├── pyproject.toml
└── README.md
```

---

## 9. DeepSeek API Compatibility

### 9.1 Current State

The existing LLM adapter already supports DeepSeek via OpenAI-compatible endpoints:

```bash
export OPENAI_API_KEY='sk-deepseek-key'
export OPENAI_API_BASE='https://api.deepseek.com/v1'
export LLM_MODEL='deepseek-chat'
```

### 9.2 Enhanced Support (Phase 1)

```python
# env vars (priority order)
# 1. LLM_PROVIDER=deepseek  → explicit selection
# 2. DEEPSEEK_API_KEY       → auto-detect DeepSeek
# 3. OPENAI_API_KEY + base  → OpenAI compatible
# 4. TONGYI_API_KEY         → 通义千问
# 5. OPENROUTER_API_KEY     → OpenRouter

# DeepSeek specifics
# - Default model: deepseek-chat (V4)
# - Supports JSON mode
# - Supports streaming
# - Context window: 128K
# - Pricing: ~1/20 of GPT-4o
```

### 9.3 JSON Mode Fallback

DeepSeek supports JSON mode (`response_format={"type": "json_object"}`). For providers that don't:
- Parse with regex
- Fall back to simple text generation + instruction "respond in JSON"
- Pydantic validation on all outputs

---

## 10. Testing Strategy

### 10.1 Test Types

| Type | Tool | Coverage |
|------|------|----------|
| Unit tests | pytest | Game state validation, data loading, LLM output parsing |
| Integration | pytest + httpx mock | Full game loop with mocked AI |
| E2E | Subprocess | Full CLI game from start to 5+ turns |
| Knowledge validation | pytest + JSON schema | Data integrity (no orphaned refs) |

### 10.2 Key Test Cases

```python
def test_world_initialization():
    """GameWorld loads all data without errors."""
    world = GameWorld("190")
    assert len(world.characters) >= 20
    assert len(world.factions) >= 8
    assert all(f.ruler_id in world.characters for f in world.factions.values())

def test_offline_game_loop():
    """Offline mode runs 5 turns without crashing."""
    game = Game(world, mode="offline")
    for _ in range(5):
        game.play_turn("发展经济")
    assert game.world.turn_count == 5

def test_llm_output_validation():
    """AI output is parsed and validated correctly."""
    adapter = LLMAdapter()
    output = adapter.chat_structured(messages, response_format=AIOutput)
    assert isinstance(output, dict)
    assert "narrative" in output

def test_multi_provider_detection():
    """Provider auto-detection works correctly."""
    with mock_env({"DEEPSEEK_API_KEY": "sk-test"}):
        adapter = LLMAdapter()
        assert adapter.provider == "deepseek"
```
