# Tech Design: 三國志略 (Histrategy)

> **Status**: Draft v0.2 — Plan/Command Architecture
> **Owner**: Prometheus (Hermes Agent)
> **Date**: 2026-05-23

---

## 1. Architecture Overview

### 1.1 Component Architecture

```
histrategy/
├── engine/
│   ├── advisors.py     # ★ Plan Mode: 顾问生成 + 4建议
│   ├── command.py      # ★ Command Mode: 官僚执行 + 种子系统
│   ├── game.py         # Game orchestrator (新Engine)
│   ├── world.py        # Legacy GameWorld (离线模式)
│   └── offline_sim.py  # 模板引擎 (含CAPITAL_NAMES等)
├── llm/
│   ├── world_model.py  # ★ LLM世界模型
│   ├── adapter.py      # 多Provider客户端
│   └── prompts.py      # 系统提示
├── state/
│   ├── world_state.py  # ★ 结构化世界状态(JSON持久化)
│   └── __init__.py
├── cli/
│   ├── app.py          # Rich终端界面
│   └── dev_cli.py      # 纯文本Dev模式(--dev)
├── knowledge/data/
│   ├── characters.json # 20+人物性格
│   ├── factions.json   # 8+势力
│   ├── regions.json    # 19个地域
│   └── events.json     # 历史事件表
├── docs/
│   ├── PRD.md          # 产品需求
│   └── tech-design.md  # 技术设计
├── tests/
│   ├── test_engine.py  # 引擎单元测试
│   └── test_e2e.py     # E2E集成测试
└── scripts/
    ├── record_demo.py  # SVG demo录制
    └── e2e_experience.py # E2E自动化测试
```

### 1.2 Data Flow

```
Player ──→ Plan Mode ──→ 4 suggestions ──→ Pick or Type ──→ Command Mode
  ↑                         + advisors                        ↓
  │                                                Bureaucracy Simulation
  │                                                Short-term effects
  │                                                Long-term seeds planted
  │                                                ↓
  └──────── World State Update ──────────── NPC Reactions ──┘
```

### 1.3 Key Design Decisions

1. **Plan/Command Separation**: Different concerns require different UX. Plan Mode is a council meeting; Command Mode is an execution dashboard.

2. **Advisor Templates**: Each faction has hardcoded advisors with template voices. This ensures:
   - Faction-specific flavor without LLM cost
   - Consistent personality across playthroughs
   - Fast response (no LLM call needed for offline mode)

3. **Seed System**: Long-term consequences are explicitly tracked in `pending_seeds.json`. Each seed has a `trigger_after` count and type. This makes "your decision matters" visible and trackable.

4. **Layered Context**: For LLM mode, context is divided into ALWAYS (system+state+last 3), RETRIEVED (bios+relations+seeds), and LONG_TERM (full history, never in prompt).

---

## 2. Module Specifications

### 2.1 advisors.py: Plan Mode

**Input**: `WorldState` (year, season, faction state)
**Output**: `dict` with `advisors` (list of dicts) and `suggestions` (list of strings)

**Advisor template format**:
```python
{
    "id": "xunyu",
    "name": "荀彧",
    "title": "军师",
    "perspective": "strategy",
    "temperament": "cautious",
    "voice": ["模板1 {situation_short}...", "模板2 {economy_status}..."]
}
```

**Template variables** filled at runtime:
- `{situation_short}` — 当前形势简述
- `{suggestion_cautious}` — 稳健建议
- `{suggestion_aggressive}` — 激进建议
- `{suggestion_scheme}` — 谋略建议
- `{suggestion_economy}` — 经济建议
- `{economy_status}` — 经济状况
- `{target_area}` — 目标区域

### 2.2 command.py: Command Mode

**Input**: `WorldState` + plan text
**Output**: `dict` with:
- `bureaucracy` — 各部门执行报告
- `short_term` — 本季数值变化
- `seeds` — 长期后果种子
- `npc_reactions` — 其他势力反应

**Seed format**:
```python
{
    "title": "边境紧张",
    "description": "军事调动引起周边势力警惕",
    "trigger_after": 3,  # 3 turns later
    "type": "diplomatic",
}
```

### 2.3 state/world_state.py

**WorldState dataclass**:
```python
@dataclass
class WorldState:
    year: int = 190
    season_index: int = 0
    turn: int = 0
    player_faction_id: str = ""
    factions: dict[str, FactionState]
    player_deviation: float = 0.0  # 0.0=historical, 1.0=alternate
```

**FactionState**:
```python
@dataclass
class FactionState:
    id: str
    name: str
    ruler_id: str
    strength: int     # troops
    economy: int      # 0-100
    morale: int       # 0-100
    treasury: int     # gold
    food: int         # grain
    territories: list[str]
```

---

## 3. Test Coverage

### 3.1 Current (43 tests)

| Module | Tests | Coverage |
|--------|-------|----------|
| WorldModel | 3 | Creation, stats, personality |
| Simulation | 5 | Narrative, state changes, military, NPC, turns |
| Faction Specificity | 4 | Correct intro per faction |
| Aftermath | 3 | Free text referenced in response |
| Intent Classification | 3 | Military/economy/diplomacy detection |
| No Premature Victory | 2 | Game balance (12+ turns) |
| Choices | 3 | Generated, state-dependent |
| Memory | 2 | File creation, persistence |
| Capital Names | 2 | Chinese names, no English IDs |
| Turn Progression | 1 | Legacy + world_state sync |
| E2E (CLI) | 15 | Title, factions, turns, memory, providers |
| Knowledge Base | 2 | Data integrity |

### 3.2 E2E Quality Gates

```
1. All 4 factions playable
2. Advisors present per faction
3. Bureaucracy execution visible
4. No English capital names
5. No raw numbers in narrative
6. Seeds generated for long-term consequences
7. 0 errors in stderr
```
