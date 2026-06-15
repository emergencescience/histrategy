# histrategy 引擎重构：技术设计文档

> **状态**: 最终版，准备实现
> **日期**: 2026-06-15
> **作者**: Prometheus (Hermes Agent) + Claude Sonnet 4.6 审阅
> **目标**: `game.py` 从 2,866 行 → ~800 行，消除 ~2,400 行冗余，场景真正数据驱动

---

## 一、执行总结

### 问题
1. 三套 WorldState 并存 → 桥接代码膨胀
2. `game.py` 中 `_init_v2` 和 `from_dict` 有 ~200 行完全重复
3. `FACTION_CONFIGS` 硬编码（~80行）与 JSON 知识库重复
4. `load_territories()` 硬编码三国数据，忽略 `scenarios/` 目录
5. `ScenarioLoader` 类不存在——`loader.py` 是函数集合

### 方案
按 4 个 Phase 执行，每个 Phase 独立可验证、可回滚。

### 关键原则
- **Pre-Phase 优先**：先消除代码重复（零风险），再迁移
- **每 Phase 后 `pytest tests/ -q`**：确保无回归
- **渐进式删除**：先让新代码跑通，再删旧代码，不先删后写

---

## 二、Pre-Phase: 代码去重（1-2天，零风险）

### 目标
`game.py` 从 2,866 → ~2,400 行，无破坏性变更。

### P0.1: 提取 `_build_engine_stack()`

**当前问题**：`_init_v2()` 和 `from_dict()` 各独立初始化 7 个引擎 + NPC Planner + parser——约 200 行完全重复。

**方案**：
```python
# histrategy/engine/game.py

def _build_engine_stack(self, llm: LLMAdapter | None = None):
    """Initialize all sub-engines. Called from both __init__ and from_dict."""
    self.map_engine = MapEngine(self.scenario_id)
    self.char_engine = CharacterEngine()
    self.domestic_engine = DomesticEngine()
    self.military_engine = MilitaryEngine()
    self.governance_engine = GovernanceEngine()
    self.turn_controller = TurnController()
    self.rules_interpreter = RulesInterpreter(self.scenario_id)
    self.npc_planner = NPCPlanner(llm or self.llm)
    self.narrative_engine = NarrativeEngine()
    self.intent_parser = IntentParser()
    self.policy_engine = PolicyEngine()
    self.macro_stack = MacroPolicyStack() if self.engine_version == "v3" else None

def __init__(self, scenario_id: str = "three-kingdoms", ...):
    # ... other init ...
    self._build_engine_stack(llm)

@classmethod
def from_dict(cls, data: dict, llm=None):
    engine = cls.__new__(cls)
    # ... restore state from dict ...
    engine._build_engine_stack(llm)
    return engine
```

**验证**: 运行 `HISTRATEGY_ENGINE=v2 pytest tests/ -q` 和 `HISTRATEGY_ENGINE=v3 pytest tests/ -q`

### P0.2: 删除 `FACTION_CONFIGS` 和 `NPC_FACTION_CONFIGS`

**当前问题**：`game.py:66-142` 有 ~80 行硬编码的 faction dict，与 `scenarios/three-kingdoms/knowledge/factions.json` 重复。

**方案**：
1. 删除两个 dict
2. 所有引用改为 `ScenarioLoader.load_factions()`
3. 检查 `_init_v2()` 中 `for fid, cfg in FACTION_CONFIGS.items()` 的循环——改为从 `self.factions` dict 遍历

**验证**: 确认 `game.py` 中无 `FACTION_CONFIGS` 引用。

### P0.3: 删除 `load_territories()` 硬编码

**当前问题**：`loader.py:load_territories()` 返回硬编码的三国城市数据（~300行），完全忽略 `scenarios/` 目录。

**方案**：
1. 在 `scenarios/three-kingdoms/knowledge/territories.json` 中写入三国领地数据
2. 重写 `load_territories()` → 从 `scenarios/{scenario_id}/knowledge/territories.json` 读取
3. 为 `scenarios/caesar-44bc/knowledge/territories.json` 提供数据

**验证**: 用 `scenario_id="three-kingdoms"` 和 `"caesar-44bc"` 分别调用，确认返回不同数据。

---

## 三、Phase 1: WorldState 统一（本周，高风险）

### 目标
删除 `state/world_state.py` (391行) 和 `engine/world.py` (348行)，统一到 `histrategy_engine.world.WorldState`。

### P1.1: 迁移 `state/world_state.py` 调用方

**调用方清单**：
- `cli/app.py` — 使用 `WorldState.to_dict()`/`from_dict()`
- `cli/dev_cli.py` — 同上
- `engine/game.py` — v1 路径引用
- `engine/v1_simulator.py` — 使用旧 WorldState

**方案**：
1. 为 `histrategy_engine.world.WorldState` 添加 `to_dict()` 兼容层（如果字段名不同）
2. 逐文件替换 `from histrategy.state.world_state import WorldState` → `from histrategy_engine.world import WorldState`
3. 写迁移脚本 `scripts/migrate_saves.py` 转换旧存档 JSON 格式

**验证**: 每个文件替换后运行相关测试。

### P1.2: 迁移 `engine/world.py` → 同上

`GameWorld` 类（348行）只被 `offline_sim.py` 引用。迁移后删除。

### P1.3: 迁移 `offline_sim.py` 规则仿真

`offline_sim.py` (1029行) 使用自己的仿真逻辑（非 `DomesticEngine`/`MilitaryEngine`）。

**方案**：
1. 将 `offline_sim.py` 的规则转为调用 `DomesticEngine` + `MilitaryEngine`
2. 如果某些规则是 `histrategy-engine` 中没有的，添加到 engine 或 YAML rules
3. 删除 `offline_sim.py` 旧实现

### P1.4: 删除 `offline_sim_engine.py` + `resilient_sim_engine.py`

P1.3 完成后，这两个文件的唯一调用方（`game.py:898-903` v2 fallback）消失，可以安全删除。

---

## 四、Phase 2: ScenarioLoader 类（低风险，纯新增）

### 目标
实现真正的 `ScenarioLoader` 类，替代 `loader.py` 的函数式接口。

### P2.1: 实现 ScenarioLoader 类

```python
# histrategy/engine/scenario_loader.py

from pathlib import Path
from histrategy_engine.world import WorldState, FactionState, Territory

class ScenarioLoader:
    """Load scenario data from scenarios/{id}/ directory."""
    
    def __init__(self, scenario_id: str, scenarios_root: Path | None = None):
        self.scenario_id = scenario_id
        self._root = scenarios_root or self._find_scenarios_root()
        self._scenario_dir = self._root / scenario_id
        self._toml = self._load_toml()
    
    @staticmethod
    def _find_scenarios_root() -> Path:
        """Find scenarios/ directory relative to repo root."""
        ...
    
    def load_factions(self) -> dict[str, FactionState]:
        """Read scenarios/{id}/knowledge/factions.json → dict of FactionState."""
        ...
    
    def load_territories(self) -> dict[str, Territory]:
        """Read scenarios/{id}/knowledge/territories.json → dict of Territory."""
        ...
    
    def load_characters(self) -> dict[str, Character]:
        ...
    
    def load_events(self) -> list[dict]:
        ...
    
    def load_prompt(self, name: str = "system") -> str:
        """Read scenarios/{id}/prompts/{name}.md."""
        ...
    
    def build_world_state(self, player_faction_id: str) -> WorldState:
        """Assemble complete WorldState from scenario data."""
        ...
```

### P2.2: 替换 GameEngine 中的 loader 调用

```python
# game.py:__init__
self.loader = ScenarioLoader(scenario_id)
world_state = self.loader.build_world_state(player_faction_id)
```

### P2.3: 删除 loader.py 旧接口

保留 `resolve_knowledge_path()` 作为路径辅助工具。删除其他函数（如果 P2.1 的 ScenarioLoader 覆盖了全部功能）。

### P2.4: 清理 scenarios/caesar-44bc/knowledge/

已完成 ✅：
- `factions.json` — 4 主势力 + 4 NPC（npc_only 标记）
- `initial_state.json` — 44 BC 起始状态（4 主势力 + Brutus NPC）
- `territories.json` — 16 罗马领地

---

## 五、Phase 3: Scenario Config 增强

### P3.1: `scenario.toml` 新字段

```toml
[engine]
year_direction = "negative"    # "positive" | "negative" — BC 年份支持

[factions]
npc_only = ["cleopatra", "brutus", "parthia", "senate"]  # 不可扮演势力
```

### P3.2: BC 年份渲染

```python
# ScenarioLoader
def format_year(self, year: int) -> str:
    direction = self._toml.get("engine", {}).get("year_direction", "positive")
    if direction == "negative":
        return f"公元前{abs(year)}年"
    return f"公元{year}年"
```

---

## 六、验证清单

每个 Phase 完成后执行：

```bash
# 1. 单元测试
HISTRATEGY_ENGINE=v2 pytest tests/ -q
HISTRATEGY_ENGINE=v3 pytest tests/ -q

# 2. lint
ruff check . && ruff format --check .

# 3. 场景加载（新增）
python -c "
from histrategy.engine.scenario_loader import ScenarioLoader
for sid in ['three-kingdoms', 'caesar-44bc']:
    loader = ScenarioLoader(sid)
    ws = loader.build_world_state('octavian' if sid == 'caesar-44bc' else 'shu')
    print(f'{sid}: {len(ws.factions)} factions, {len(ws.territories)} territories')
"
```

---

## 七、不变更事项

1. **不开发《山河鼎革》scenario** — 仅保留骨架
2. **不碰 `v1_simulator.py`** — V3 稳定后再退役
3. **不修改 `room_manager.py`** — 持久化改造在 Phase 4
4. **不修改 `api.py`** — API 路由已在 Phase 2 中参数化
5. **不新建独立 repo** — 所有场景在 monorepo 内

---

## 九、回滚与安全策略

### 每 Phase 独立 commit
```
Pre-Phase: 3 commits (P0.1, P0.2, P0.3 — 每个可独立 revert)
Phase 1:   4 commits (P1.1, P1.2, P1.3, P1.4 — 逐文件迁移，不批量)
Phase 2:   4 commits (P2.1 新文件先行，P2.2 切换引用，P2.3 删旧，P2.4 清理)
```

### Phase 1 高风险缓解
1. **P1.1 先验证兼容层**：在替换 import 前，确认 `histrategy_engine.world.WorldState` 的 `to_dict()`/`from_dict()` 输出与旧 `state/world_state.py` 兼容
2. **存档迁移先于代码删除**：`scripts/migrate_saves.py` 在删 `state/world_state.py` 之前写好并验证
3. **保留 v1 路径不动**：`v1_simulator.py` 仍用旧 WorldState，Phase 1 只迁移 v2/v3

### 迁移脚本关键映射
```python
# 旧 state/world_state.py → 新 histrategy_engine.world
# 字段映射（需在 P1.1 前确认）：
#   WorldState.year          → 同
#   WorldState.season        → 同
#   WorldState.factions: dict → 同，但 FactionState 字段可能不同
#   WorldState.territories   → 同
#   FactionState.troops      → FactionState.strength（注意字段名差异！）
#   FactionState.gold        → FactionState.treasury
```

### 测试基线
每次 Phase 开始前运行：
```bash
pytest tests/ -q --tb=short 2>&1 | tee test-baseline-$(date +%Y%m%d-%H%M).log
```
Phase 完成后对比基线，确认无新增失败。

---

## 八、参考

- `docs/design/refactor-engine-unification.md` — 原始重构计划（已 Claude 审阅更新）
- `docs/design/multi-scenario-architecture.md` — 多场景架构设计
- `docs/decisions/h15m-shanhe-dingge-repo-decision.md` — Monorepo 决策记录
- `docs/decisions/h15n-sdk-reload-vs-http-server.md` — 持久化架构决策
- `CLAUDE.md` — 项目架构和命令参考
