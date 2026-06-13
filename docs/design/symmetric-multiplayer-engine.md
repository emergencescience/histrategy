# 对称多人引擎 技术设计文档

> 版本: 1.0 | 日期: 2026-06-11 | 状态: Draft for Review
>
> 将 histrategy 从"单人+AI背景NPC"重构为"多人+多AI NPC对称架构"。
> 所有势力（无论人类还是AI）在状态机、数据模型、持久化上完全对称。

---

## 0. 决策摘要

| 决策 | 选项 | 理由 |
|------|------|------|
| 回合模型 | **A: 全员等待** | 所有 faction 提交决策后才推进季度。标准多人策略模型。 |
| NPC AI | **A: 独立 LLM 调用** | 每个 NPC faction 一次独立 LLM call，真正对称。 |
| orchestrator 改动 | **不碰** | gamesession/gameturn 等表留在 orchestrator 不动，histrategy 有自己的 DB。 |
| 数据库 | **SQLite (本地) / PostgreSQL (Railway)** | Python 标准库自带 sqlite3，零安装成本。 |
| 文件 | **只写不读** | 写 JSON 用于调试/备份；状态恢复全部从 SQL 读取。 |
| histrategy 连 DB | **直连** | 不再通过 orchestrator HTTP 中继。 |

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────┐
│                      histrategy Server                    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │Slot: cao │  │Slot: shu │  │Slot: wu  │  ... (N)      │
│  │ human    │  │ human    │  │ ai_npc   │               │
│  │ user_A   │  │ user_B   │  │ llm       │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       │             │             │                      │
│       ▼             ▼             ▼                      │
│  ┌─────────────────────────────────────────────────┐    │
│  │           Decision Bus (决策总线)                │    │
│  │  - 收集所有 slot 的本季度 decision              │    │
│  │  - human: 等待 HTTP/WebSocket 提交             │    │
│  │  - ai_npc: ThreadPoolExecutor 并行 LLM 调用    │    │
│  │  - 全部就绪 → fire Quarterly Engine            │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │        Quarterly Resolution Engine              │    │
│  │  1. 确定性基线 (TurnController)                 │    │
│  │  2. LLM 宏观模拟 (MacroPolicyEngine)            │    │
│  │  3. 黑天鹅注入 (BlackSwanInjector)              │    │
│  │  4. 状态应用 (StateApplier)                     │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │       Per-Slot Narrative Engine                 │    │
│  │  - 每个 slot 独立生成叙事（该势力的视角）       │    │
│  │  - 并行 ThreadPoolExecutor                     │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │              SQL Database                       │    │
│  │  SQLite (local) / PostgreSQL (Railway)          │    │
│  │  所有状态存 SQL，文件只写不读                   │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 关键原则

1. **FactionSlot 是一等公民**：所有势力（人类/AI）完全对称——相同的状态机、相同的数据结构、相同的持久化。
2. **Decision Bus 是核心抽象**：引擎不关心决策来源（人类打字 vs LLM 生成），只关心"本季度所有 faction 的决策是否收集完毕"。
3. **SQL 是单一真相源**：`world_state`、`slots`、`turns`、`llm_call_log` 全部在 histrategy 自己的数据库里。文件只写 JSON 备份。

---

## 2. 数据库 Schema

### 2.1 数据库选择

| 环境 | 数据库 | 连接方式 |
|------|--------|----------|
| 本地 (pip install) | **SQLite3** | `sqlite3:///~/.histrategy/histrategy.db` |
| Railway | **PostgreSQL** | `postgresql://$HISTRATEGY_DATABASE_URL` |

**SQLite3 零成本证明**：
- Python 标准库自带 `import sqlite3`（CPython 编译时默认开启）
- Linux: `libsqlite3` 几乎所有发行版预装
- macOS: 系统自带
- Windows: Python 安装包内置
- **不需要用户做任何额外安装**

### 2.2 表设计

所有表使用 `TEXT` 存 UUID（兼容 SQLite/PostgreSQL），`JSON` 列在 SQLite 中存为 `TEXT`。

```sql
-- ═══════════════════════════════════════════════════════════
-- game_room: 一局游戏的会话（symmetry: 没有 player_faction_id）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE game_room (
    id              TEXT PRIMARY KEY,        -- UUID
    host_user_id    TEXT,                    -- 创建者 user_id（可空）
    scenario        TEXT DEFAULT '207',
    year            INTEGER DEFAULT 207,
    season          TEXT DEFAULT '春',
    quarter_number  INTEGER DEFAULT 0,       -- 当前季度序号
    phase           TEXT DEFAULT 'lobby',    -- lobby | waiting | resolving | finished
    world_state     TEXT,                    -- JSON: 完整 WorldState 快照
    slots           TEXT,                    -- JSON: [Slot, ...] 
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════
-- faction_slot: 每个势力槽位（对称：人类/AI 同一张表）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE faction_slot (
    id              TEXT PRIMARY KEY,        -- UUID
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    faction_id      TEXT NOT NULL,           -- "cao" | "shu" | "wu" | ...
    occupant_type   TEXT NOT NULL DEFAULT 'open',  -- "human" | "ai_npc" | "open"
    occupant_id     TEXT,                    -- user_id (human) | NULL (ai/open)
    
    -- AI 配置（仅 occupant_type='ai_npc' 时有效）
    ai_model        TEXT,                    -- LLM model for this NPC
    ai_personality  TEXT,                    -- JSON: aggression/caution/mercy 覆盖
    
    -- 当前季度决策
    pending_decision TEXT,                   -- 本季度已提交的原始决策文本
    pending_commands TEXT,                   -- JSON: 解析后的结构化命令
    
    -- 状态
    is_active       INTEGER DEFAULT 1,
    
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    
    UNIQUE(room_id, faction_id)
);

-- ═══════════════════════════════════════════════════════════
-- quarter_turn: 每个季度的完整记录（对称：所有 faction 的决策）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE quarter_turn (
    id              TEXT PRIMARY KEY,        -- UUID
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    season          TEXT NOT NULL,
    
    -- 所有 faction 的决策（对称存储）
    faction_decisions TEXT,                  -- JSON: {"cao": {"decision":"...", "commands":[...]}, "shu": {...}, ...}
    
    -- 确定性引擎结果
    baseline_result  TEXT,                   -- JSON: TurnResult
    
    -- LLM 宏观模拟结果
    macro_delta      TEXT,                   -- JSON: MacroPolicyEngine output
    
    -- 叙事结果（per-faction）
    narratives       TEXT,                   -- JSON: {"cao": "曹操视角叙事...", "shu": "...", ...}
    
    -- 状态变更
    state_changes    TEXT,                   -- JSON: 所有 faction 的资源变化
    
    -- Token 消耗
    token_usage      TEXT,                   -- JSON: {"intent_parse": 0, "npc_cao": 0, "npc_shu": 0, ...}
    
    created_at       TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════
-- llm_call_log: 每个 LLM 调用的完整记录（从 orchestrator 迁移到 histrategy DB）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE llm_call_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    
    call_type       TEXT NOT NULL,           -- "intent_parse" | "npc_decision" | "macro_simulate" | "narrative"
    faction_id      TEXT,                    -- 哪个 faction 的调用（NULL = 全局）
    provider        TEXT,
    model           TEXT,
    
    prompt_tokens       INTEGER DEFAULT 0,
    completion_tokens   INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER,
    latency_ms          INTEGER DEFAULT 0,
    
    system_prompt   TEXT,
    user_prompt     TEXT,
    response        TEXT,
    error           TEXT,
    
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════
-- simulation_event_log: 确定性引擎事件
-- ═══════════════════════════════════════════════════════════
CREATE TABLE simulation_event_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    
    event_type      TEXT NOT NULL,           -- "black_swan" | "baseline" | "policy_cmd" | "state_mutation"
    event_data      TEXT,                    -- JSON
    
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX idx_faction_slot_room ON faction_slot(room_id);
CREATE INDEX idx_quarter_turn_room ON quarter_turn(room_id, quarter_number);
CREATE INDEX idx_llm_call_log_room ON llm_call_log(room_id, quarter_number);
CREATE INDEX idx_sim_event_room ON simulation_event_log(room_id, quarter_number);
```

### 2.3 SQLite vs PostgreSQL 兼容性

- `TEXT` 存 UUID：两种数据库都支持，无需 PG_UUID 类型
- `JSON` 列：SQLite 存为 `TEXT`，读写时 `json.dumps/loads`
- `datetime('now')`：SQLite 默认值；PostgreSQL 用 `CURRENT_TIMESTAMP`
- 所有查询使用标准 SQL，不依赖方言特性
- 用环境变量 `HISTRATEGY_DATABASE_URL` 切换：
  - 本地: `sqlite:///~/.histrategy/histrategy.db`
  - Railway: `postgresql://user:pass@histrategy-postgres.railway.internal:5432/histrategy`

---

## 3. Python 数据模型

### 3.1 FactionSlot（对称核心）

```python
from dataclasses import dataclass, field
from enum import Enum

class OccupantType(Enum):
    HUMAN = "human"
    AI_NPC = "ai_npc"
    OPEN = "open"  # 等待人类加入

@dataclass
class FactionSlot:
    """对称的势力槽位——人类和AI使用完全相同的数据结构。"""
    
    faction_id: str              # "cao" | "shu" | "wu" | ...
    occupant_type: OccupantType  # human / ai_npc / open
    occupant_id: str | None = None  # user_id (human) | None (ai/open)
    
    # AI NPC 配置
    ai_model: str | None = None       # LLM model override
    ai_temperature: float = 0.7       # NPC 创造度
    
    # 当前季度决策
    pending_decision: str | None = None      # 原始文本
    pending_commands: list | None = None     # 解析后结构化命令
    
    # 状态
    is_active: bool = True
    
    def is_human(self) -> bool:
        return self.occupant_type == OccupantType.HUMAN
    
    def is_ai(self) -> bool:
        return self.occupant_type == OccupantType.AI_NPC
    
    def is_open(self) -> bool:
        return self.occupant_type == OccupantType.OPEN
    
    def has_submitted(self) -> bool:
        """本季度是否已提交决策。"""
        return self.pending_decision is not None
    
    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "occupant_type": self.occupant_type.value,
            "occupant_id": self.occupant_id,
            "ai_model": self.ai_model,
            "ai_temperature": self.ai_temperature,
            "is_active": self.is_active,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FactionSlot":
        return cls(
            faction_id=data["faction_id"],
            occupant_type=OccupantType(data.get("occupant_type", "open")),
            occupant_id=data.get("occupant_id"),
            ai_model=data.get("ai_model"),
            ai_temperature=data.get("ai_temperature", 0.7),
            is_active=data.get("is_active", True),
        )
```

### 3.2 GameRoom（替代 GameSession）

```python
from enum import Enum

class RoomPhase(Enum):
    LOBBY = "lobby"          # 等待玩家加入
    WAITING = "waiting"      # 等待所有 faction 提交本季度决策
    RESOLVING = "resolving"  # 正在执行季度引擎（拒绝新提交）
    FINISHED = "finished"    # 游戏结束

@dataclass
class GameRoom:
    """一局游戏——拥有 N 个对称的 FactionSlot。"""
    
    id: str                          # UUID
    host_user_id: str | None = None
    scenario: str = "207"
    year: int = 207
    season: str = "春"
    quarter_number: int = 0
    phase: RoomPhase = RoomPhase.LOBBY
    slots: dict[str, FactionSlot] = field(default_factory=dict)  # faction_id → slot
    world_state: "WorldState | None" = None
    
    # 等待超时配置（秒）
    decision_timeout: int = 300       # 人类玩家提交决策的超时
    
    def all_slots_submitted(self) -> bool:
        """本季度所有活跃 slot 是否都已提交决策。"""
        active = [s for s in self.slots.values() if s.is_active]
        return all(s.has_submitted() for s in active)
    
    def pending_slots(self) -> list[str]:
        """本季度尚未提交决策的 faction_id 列表。"""
        return [
            fid for fid, s in self.slots.items()
            if s.is_active and not s.has_submitted()
        ]
    
    def human_slots(self) -> list[FactionSlot]:
        return [s for s in self.slots.values() if s.is_human()]
    
    def ai_slots(self) -> list[FactionSlot]:
        return [s for s in self.slots.values() if s.is_ai()]
    
    def active_slots(self) -> list[FactionSlot]:
        return [s for s in self.slots.values() if s.is_active]
    
    def advance_quarter(self):
        """推进到下一季度，清空所有 pending。"""
        self.quarter_number += 1
        for slot in self.slots.values():
            slot.pending_decision = None
            slot.pending_commands = None
        self.phase = RoomPhase.WAITING
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "host_user_id": self.host_user_id,
            "scenario": self.scenario,
            "year": self.year,
            "season": self.season,
            "quarter_number": self.quarter_number,
            "phase": self.phase.value,
            "slots": {fid: s.to_dict() for fid, s in self.slots.items()},
            "decision_timeout": self.decision_timeout,
        }
```

---

## 4. 季度处理流程

### 4.1 完整时序

```
                     ┌──────────┐
                     │  LOBBY   │  玩家加入 / AI NPC 自动就位
                     └────┬─────┘
                          ▼
              ┌─────────────────────┐
              │      WAITING        │
              │                     │
              │  Human A 提交决策 ──┤
              │  Human B 提交决策 ──┤
              │  AI NPC ① LLM 决策─┤  ← ThreadPoolExecutor 并行
              │  AI NPC ② LLM 决策─┤
              │  AI NPC ③ LLM 决策─┤
              │                     │
              │  全部就绪？ ────────┼──→ 是: 进入 RESOLVING
              │  或超时（300s）─────┼──→ 未提交 human = AI 自动
              └─────────────────────┘
                          ▼
              ┌─────────────────────┐
              │     RESOLVING       │
              │                     │
              │  1. IntentParser    │  ← 解析所有决策
              │  2. TurnController  │  ← 确定性基线
              │  3. MacroSimulate   │  ← 一个 LLM 调用（全局）
              │  4. StateApplier    │  ← 应用结果
              │  5. Narratives      │  ← per-faction 并行
              │  6. Persist to SQL  │
              │                     │
              │  推进季度 ──────────┼──→ WAITING (下一季度)
              └─────────────────────┘
```

### 4.2 阶段 1: 收集决策（WAITING）

```python
async def collect_decisions(room: GameRoom, llm: LLMAdapter) -> dict[str, tuple[str, list]]:
    """收集所有 faction 的本季度决策。
    
    Returns:
        {faction_id: (decision_text, parsed_commands)}
    """
    decisions = {}
    
    # 1. 人类玩家：从 pending_decision 读取（已通过 API 提交）
    for slot in room.human_slots():
        if slot.has_submitted():
            decisions[slot.faction_id] = (slot.pending_decision, None)
    
    # 2. AI NPC：并行 LLM 调用
    ai_slots = [s for s in room.ai_slots() if not s.has_submitted()]
    
    async def generate_npc_decision(slot: FactionSlot) -> tuple[str, list]:
        """为一个 NPC faction 生成独立决策。"""
        from histrategy.llm.npc_decision_engine import NPCDecisionEngine
        
        engine = NPCDecisionEngine(llm, slot.faction_id)
        decision_text, commands = engine.generate(
            world_state=room.world_state,
            turn_memory=room.get_recent_turns(8),
            slot=slot,
        )
        slot.pending_decision = decision_text
        slot.pending_commands = commands
        return decision_text, commands
    
    # 并行执行所有 NPC LLM 调用
    tasks = [generate_npc_decision(s) for s in ai_slots]
    results = await asyncio.gather(*tasks)
    for slot, (decision, commands) in zip(ai_slots, results):
        decisions[slot.faction_id] = (decision, commands)
    
    return decisions
```

### 4.3 阶段 2: 解析 + 执行（RESOLVING）

```python
def resolve_quarter(room: GameRoom, decisions: dict, engine: GameEngine) -> QuarterResult:
    """执行季度模拟。"""
    
    all_commands = {}
    for faction_id, (decision_text, pre_parsed) in decisions.items():
        if pre_parsed:
            all_commands[faction_id] = pre_parsed
        else:
            # IntentParser 解析人类决策
            all_commands[faction_id] = engine.intent_parser.parse(
                decision_text, faction_id
            )
    
    # 确定性基线（TurnController 按 faction 顺序执行）
    baseline = engine.turn_controller.execute_multi_faction_turn(
        room.world_state, all_commands
    )
    
    # LLM 宏观模拟（一个调用包含所有 faction 的决策上下文）
    macro_delta = engine.macro_policy_engine.simulate_multi_faction(
        room.world_state, all_commands, decisions, baseline
    )
    
    # 应用结果到 WorldState
    engine.state_applier.apply(baseline, macro_delta)
    
    # Per-faction 叙事生成（并行）
    narratives = {}
    with ThreadPoolExecutor(max_workers=len(room.active_slots())) as executor:
        futures = {
            faction_id: executor.submit(
                engine.narrative_engine.generate_faction_narrative,
                room.world_state, faction_id, baseline, macro_delta
            )
            for faction_id in all_commands
        }
        for faction_id, future in futures.items():
            narratives[faction_id] = future.result(timeout=30)
    
    return QuarterResult(
        baseline=baseline,
        macro_delta=macro_delta,
        narratives=narratives,
        state_changes=extract_state_changes(room.world_state),
    )
```

---

## 5. API 设计

### 5.1 完全向后兼容

现有 API 不变，**新增** multiplayer 端点。单人模式自动创建 1 human + 2 AI NPC 的 room。

```
现有（不变）:
POST /api/games           → 创建单人游戏（内部: 1 human + 2 ai_npc）
POST /api/games/command   → 提交决策 + 立即执行（单人模式）
GET  /api/games/plan      → 获取建议

新增:
POST /api/rooms           → 创建多人房间
POST /api/rooms/{id}/join → 加入房间（选择 faction）
POST /api/rooms/{id}/start→ 开始游戏（锁定 slots，未填充的 → ai_npc）
POST /api/rooms/{id}/decide → 提交本季度决策（不立即执行，等待全员）
GET  /api/rooms/{id}/status → 房间状态（谁提交了，谁在等）
POST /api/rooms/{id}/execute → 手动触发执行（host 可强制推进）
GET  /api/rooms/{id}/narrative/{faction_id} → 获取某势力视角的叙事
```

### 5.2 关键端点详情

```python
# POST /api/rooms/{id}/decide
class DecideRequest(BaseModel):
    faction_id: str       # 你控制哪个势力
    decision: str         # 自然语言决策
    user_id: str          # 玩家身份（JWT sub 或临时 ID）

# Response:
{
    "status": "waiting",           # waiting | ready | resolving
    "submitted_factions": ["cao"], # 已提交的 faction
    "pending_factions": ["shu", "wu"],  # 还在等的 faction
    "timeout_seconds": 240,
}
```

### 5.3 单人模式兼容（零破坏）

`POST /api/games` 内部逻辑：

```python
@router.post("/api/games")
def create_game(req: CreateGameRequest):
    # 创建 room，自动填充 slots:
    # - req.faction → human (当前用户)
    # - 其他主要势力 (shu/wu 或 cao/wu) → ai_npc
    room = create_single_player_room(req.faction, req.scenario)
    
    # 单人模式：立即执行第一回合
    # （AI NPC 的决策在后台并行生成，然后自动推进）
    
    return format_single_player_response(room)
```

---

## 6. NPC 独立决策引擎

### 6.1 NPCDecisionEngine

```python
class NPCDecisionEngine:
    """为一个 NPC faction 生成独立季度决策。
    
    每个 NPC 有独立的 LLM 调用——不是"顺便"在 MacroPolicyEngine 里生成。
    """
    
    def __init__(self, llm: LLMAdapter, faction_id: str):
        self.llm = llm
        self.faction_id = faction_id
        self.prompt = load_prompt("npc_decision.md")
    
    def generate(
        self,
        world_state: WorldState,
        turn_memory: list[dict],
        slot: FactionSlot,
    ) -> tuple[str, list]:
        """生成 NPC 的本季度决策。
        
        Returns:
            (decision_text, parsed_commands)
        """
        faction = world_state.factions.get(self.faction_id)
        if not faction or not faction.is_active:
            return "休整", []
        
        context = self._build_context(world_state, turn_memory, faction)
        
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": context},
        ]
        
        response = self.llm.chat_structured(
            messages,
            response_format={"type": "json_object"},
            temperature=slot.ai_temperature or 0.7,
            max_tokens=1024,
            metadata={
                "category": "npc_decision",
                "faction_id": self.faction_id,
            },
        )
        
        decision = response.get("decision", "")
        commands = response.get("commands", [])
        
        # 记录到 llm_call_log
        log_npc_call(self.faction_id, decision, commands)
        
        return decision, commands
    
    def _build_context(self, ws, memory, faction) -> str:
        """构建 NPC 决策上下文。
        
        关键：NPC 基于 FOW (Fog of War) 做决策，
        看不到非相邻势力的真实兵力。
        """
        from histrategy_engine.ai.fog_of_war import LocalWorldStateProjector
        
        projector = LocalWorldStateProjector(ws)
        local_ws = projector.project(self.faction_id)
        
        lines = []
        lines.append(f"## 当前时间\n{ws.year}年{ws.season.cn} | 第{ws.turn_number}季度\n")
        lines.append(f"## 你的势力\n势力: {faction.name} ({self.faction_id})")
        lines.append(f"兵力: {faction.strength_actual:,}")
        lines.append(f"资金: {faction.treasury:,} | 粮草: {faction.food:,}")
        lines.append(f"民心: {faction.morale_actual} | 税率: {faction.tax_rate:.0%}")
        lines.append(f"领地: {list(faction.territories)}")
        
        # FOW-aware 周边势力
        lines.append("\n## 周边情报（基于斥候探报）")
        for fid, f in local_ws.factions.items():
            if fid == self.faction_id:
                continue
            lines.append(f"- {f.name}: 兵力≈{f.strength_estimated}, 民心≈{f.morale_estimated}")
        
        # 历史记忆
        if memory:
            lines.append("\n## 近期大事")
            for mem in memory[-5:]:
                lines.append(f"- {mem.get('outcome_summary', '')}")
        
        lines.append("\n## 你的个性")
        lines.append(f"侵略性: {faction.aggression:.1f} | 谨慎: {faction.caution:.1f}")
        lines.append(f"外交倾向: {faction.diplomacy:.1f} | 仁慈: {faction.mercy:.1f}")
        
        lines.append("\n请制定本季度的战略决策。")
        return "\n".join(lines)
```

### 6.2 NPC Decision Prompt

每个 NPC 使用专属 prompt（含个性配置）：

```markdown
# npc_decision.md

你是《三國志略》中的一位诸侯。你将根据当前天下形势和你的个性，
制定本季度（三个月）的战略决策。

## 输出格式
{
  "decision": "你的战略决策自然语言描述（作为史书记载）",
  "commands": [
    {"type": "attack|defend|recruit|develop|diplomacy|tax|wait", "params": {...}, "reasoning": "..."}
  ]
}

## 决策原则
1. 基于你的个性参数（侵略性/谨慎/外交倾向/仁慈）做决策
2. 你只能看到相邻势力的估算兵力（斥候探报），不能看到全局信息
3. 优先保全自己，其次扩张
4. 综合考虑兵力、粮草、民心、外交关系
```

---

## 7. 数据持久化

### 7.1 Database 连接管理

```python
# histrategy/db/connection.py

import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get(
    "HISTRATEGY_DATABASE_URL",
    f"sqlite:///{os.path.expanduser('~/.histrategy/histrategy.db')}"
)

def get_connection():
    """获取数据库连接（SQLite 或 PostgreSQL）。
    
    自动检测 URL 前缀：
    - sqlite:///path → sqlite3.connect(path)
    - postgresql://... → psycopg2.connect(...) 或 asyncpg
    """
    if DATABASE_URL.startswith("sqlite"):
        path = DATABASE_URL.replace("sqlite:///", "")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    else:
        # PostgreSQL
        import psycopg2
        return psycopg2.connect(DATABASE_URL)


def init_db():
    """首次运行时创建所有表。"""
    conn = get_connection()
    schema = load_schema_sql()  # 从 schema.sql 读取
    conn.executescript(schema)
    conn.commit()
    conn.close()
```

### 7.2 文件只写策略

```python
# histrategy/db/file_backup.py

def write_backup(room: GameRoom, reason: str = "quarter_complete"):
    """写入 JSON 备份文件（仅用于调试/灾难恢复）。
    
    文件路径: ~/.histrategy/backups/{room_id}/{quarter_number:04d}_{reason}.json
    
    ⚠️ 此函数只写不读。所有状态恢复从 SQL 进行。
    """
    backup_dir = os.path.expanduser(f"~/.histrategy/backups/{room.id}")
    os.makedirs(backup_dir, exist_ok=True)
    
    filename = f"{room.quarter_number:04d}_{reason}.json"
    filepath = os.path.join(backup_dir, filename)
    
    data = {
        "room": room.to_dict(),
        "world_state": room.world_state.to_dict() if room.world_state else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
```

### 7.3 状态恢复（从 SQL 加载）

```python
def load_room(room_id: str) -> GameRoom | None:
    """从 SQL 恢复完整的 GameRoom + WorldState。
    
    ⚠️ 不从文件读取。
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM game_room WHERE id = ?", (room_id,)
    ).fetchone()
    
    if not row:
        return None
    
    # 恢复 WorldState
    world_state = WorldState.from_dict(json.loads(row["world_state"]))
    
    # 恢复 Slots
    slot_rows = conn.execute(
        "SELECT * FROM faction_slot WHERE room_id = ?", (room_id,)
    ).fetchall()
    slots = {}
    for sr in slot_rows:
        slot = FactionSlot.from_dict({
            "faction_id": sr["faction_id"],
            "occupant_type": sr["occupant_type"],
            "occupant_id": sr["occupant_id"],
            "ai_model": sr["ai_model"],
            "is_active": bool(sr["is_active"]),
        })
        slots[sr["faction_id"]] = slot
    
    room = GameRoom(
        id=row["id"],
        host_user_id=row["host_user_id"],
        scenario=row["scenario"],
        year=row["year"],
        season=row["season"],
        quarter_number=row["quarter_number"],
        phase=RoomPhase(row["phase"]),
        slots=slots,
        world_state=world_state,
    )
    return room
```

---

## 8. 部署变更

### 8.1 Railway: 新增 histrategy-postgres

```bash
# 在 Railway 项目里新增一个 PostgreSQL 服务
railway add --name histrategy-postgres

# 获取连接 URL
railway variables get DATABASE_URL --service histrategy-postgres

# 在 histrategy 服务设置环境变量
railway variables set \
  HISTRATEGY_DATABASE_URL="$DATABASE_URL" \
  --service histrategy
```

### 8.2 Dockerfile 变更

```dockerfile
# 新增 psycopg2 (PostgreSQL 驱动) 和 aiosqlite (异步 SQLite)
RUN pip install "psycopg2-binary>=2.9" "aiosqlite>=0.20"
```

### 8.3 启动时自动建表

```python
# histrategy/server/api.py → create_app()

def create_app():
    app = FastAPI()
    
    @app.on_event("startup")
    async def startup():
        from histrategy.db.connection import init_db
        init_db()  # 首次运行自动创建所有表
    
    # ... routes ...
```

---

## 9. 迁移策略

### Phase 1: Engine 对称化（本周）

- [ ] 创建 `FactionSlot` 数据类
- [ ] 创建 `GameRoom` 数据类（替代 `GameSession`）
- [ ] 创建 `NPCDecisionEngine`（独立 NPC LLM 调用）
- [ ] 重构 `_process_turn_macro` → `resolve_quarter`（多 faction 决策）
- [ ] 单人模式兼容适配（自动 1 human + 2 ai_npc）

**验收**: 单人模式功能完全不变，但底层已使用对称架构。

### Phase 2: SQL 持久化（本周）

- [ ] 创建 `histrategy/db/` 模块（connection, schema, models, file_backup）
- [ ] `pyproject.toml` 添加 `psycopg2-binary`, `aiosqlite`
- [ ] `Dockerfile` 添加依赖
- [ ] `create_app()` 启动时自动建表
- [ ] `save_room()` / `load_room()` 实现
- [ ] 文件改为只写备份
- [ ] 状态恢复改为从 SQL 加载

**验收**: 重启 histrategy 服务后游戏状态完整恢复。

### Phase 3: 多人 API + 前端（下周）

- [ ] `POST /api/rooms` 等新端点
- [ ] WebSocket 或轮询等待状态
- [ ] 前端多人 UI（房间大厅、等待状态、per-faction 叙事切换）
- [ ] 超时自动 AI 决策逻辑

**验收**: 两人分别选 cao 和 shu，在同一局游戏中交替决策。

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| SQLite 并发写入 | 多 worker 同时写可能锁 | uvicorn 单 worker（或 WAL 模式 + 重试） |
| NPC 独立 LLM 调用成本 | 4 NPC × 2000 tokens = 8000 tokens/季度 | 次要 NPC（刘璋等）跳过决策 = 只消耗资源公式 |
| 人类玩家 AFK | 其他人永远等待 | 300s 超时→AI 自动决策 |
| PostgreSQL 冷启动 | Railway 首次建 Pod 需要 30-60s | 健康检查 + 重试 |
| 历史事件多个 NPC 触发 | 同一事件被多个 NPC 独立触发 | BlackSwanInjector 全局单例，去重 |

---

## 11. 开放问题（待讨论）

1. **WebSocket vs 轮询**：多人等待状态用 WebSocket 推送还是前端轮询？WebSocket 更实时但增加复杂度。
2. **观战模式**：是否允许非玩家进入房间观看？
3. **存档槽位**：多人房间的存档槽位是否每人独立？
4. **host 迁移**：host 退出房间后谁继任？
5. **信用系统**：每季度 token 消耗如何分摊？目前是每人独立付费还是共用？

---

## 附录 A: 目录结构

```
histrategy/
├── histrategy/
│   ├── db/                          # 新增
│   │   ├── __init__.py
│   │   ├── connection.py            # SQLite/PostgreSQL 连接管理
│   │   ├── schema.sql               # DDL
│   │   ├── models.py                # GameRoom, FactionSlot ORM
│   │   ├── file_backup.py           # 只写 JSON 备份
│   │   └── migrations/              # 未来迁移
│   ├── engine/
│   │   ├── game.py                  # 重构：GameRoom 替代单人 GameEngine
│   │   ├── decision_bus.py          # 新增：决策收集 + 超时
│   │   ├── quarterly_engine.py      # 重构：多 faction 季度模拟
│   │   └── macro_policy_engine.py   # 重构：接受多 faction 决策
│   ├── llm/
│   │   ├── npc_decision_engine.py   # 新增：独立 NPC LLM 决策
│   │   └── prompts/
│   │       └── npc_decision.md      # 新增：NPC 决策 prompt
│   └── server/
│       ├── api.py                   # 新增 multiplayer 端点
│       └── room_manager.py          # 新增：多房间管理
```

## 附录 B: 与 emergence-orchestrator 的接口

histrategy 不再通过 orchestrator 存储游戏状态。但保留以下调用：

| 接口 | 用途 | 是否保留 |
|------|------|----------|
| `POST /games/histrategy/sessions` | 创建会话 | ✅ 保留（orchestrator portal 需要知道 session 存在） |
| `PUT /games/histrategy/saves` | 保存 world_state | ⚠️ 改为只写备份（orchestrator 不再读取） |
| `GET /games/histrategy/sessions/{id}/turns` | 读取回合历史 | ❌ 删除（histrategy 从自己的 DB 读） |

前端 `surprisal-portal` 的 API 调用改为直接指向 histrategy 服务（通过 orchestrator proxy 或直连）。
