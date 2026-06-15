# histrategy 重构计划：消除冗余 + 引擎统一 + 多场景复用

> **状态**: 实施中 — 更新于 2026-06-15
> **分支**: `feat/engine-merge-v3-macro`
> **测试**: 236 passed / 0 failed

---

> **[审阅评语 — 已处理 3/3]**
>
> 1. **`ScenarioLoader` 已实现** ✅ — `histrategy/engine/scenario_loader.py` (548行)，含 `build_world_state()` / `load_factions()` / `load_characters()` / `list_scenarios()` 等 20+ 方法
> 2. **`_build_engine_stack()` 已提取** ✅ — `game.py` 去重约 136 行
> 3. **`FACTION_CONFIGS` / `NPC_FACTION_CONFIGS` 已删除** ✅ — 约 95 行硬编码字典移除
> 4. **`load_territories()` 硬编码已去除** ✅ — 三国地图数据移到 `scenarios/three-kingdoms/knowledge/territories.json`
> 5. **Phase 1 WorldState 统一** ✅ 部分 — 向后兼容 shim（`get_player_faction`, `strength`/`strength_actual` 别名）已加；完整统一需待 v1 CLI 退役
> 6. **Phase 5.1 Web UI 多场景** ✅ — `mp.html` 完全重写为场景感知，`/api/scenarios` 端点已加
> 7. **Phase 5.4 BC 年份渲染** ✅ — `公元前43年` 正确显示

---

## 一、问题诊断

### 1.1 三套 WorldState 并存

```
histrategy/state/world_state.py        (391行) ← CLI/v1 使用，自成一派
histrategy/engine/world.py             (348行) ← offline_sim 使用，GameWorld
histrategy-engine/.../world/           (pip包) ← 正确实现，唯一应该保留的
```

三个 `WorldState` / `FactionState` 类**互不兼容**，各有各的字段名和序列化格式。`game.py:2866` 行中有大量桥接代码在做类型转换。

### 1.2 两套引擎并行

| 旧引擎 (`histrategy/engine/`) | 新引擎 (`histrategy-engine/src/`) |
|---|---|
| `offline_sim.py` (1029行) — 规则仿真 | `domestic/` — 粮食/人口/税收 |
| `world.py` (348行) — GameWorld | `world/` — WorldState/FactionState/Territory |
| `guardrail.py` (215行) — LLM 输出校验 | `governance/` — 合法性 |
| `quarterly_*.py` (681行) — 季度结算 | `turn/` — 回合控制 |
| `state_applier.py` (283行) — 状态应用 | 无对应（合并到 engine 内） |
| `v1_simulator.py` (416行) — 纯 LLM 仿真 | 无对应（macro_policy_engine 替代） |

**关键发现**：`game.py` 中的 v2 路径已经通过 `TYPE_CHECKING` 导入 `histrategy-engine`，但 v1/fallback 路径仍用旧引擎。这导致同一文件维护两套逻辑。

### 1.3 `game.py` 结构性问题（新增发现）

> **[审阅意见]** 读 `game.py` 发现两个高优先级问题：
>
> **问题 A：`_init_v2` 和 `from_dict` 几乎完全重复**。两个方法各自独立地初始化 7 个引擎、NPC Planner、narrative engine、intent parser、v3 stack、macro stack——大约 200 行代码完全重复。这是导致 `game.py` 膨胀到 2,866 行的主要原因之一。
>
> ```python
> # 当前：重复了两次
> def _init_v2(self, ...):
>     self.map_engine = MapEngine()          # ↓ 第1次
>     self.char_engine = CharacterEngine()   #
>     ...（约100行）
>
> @classmethod
> def from_dict(cls, data, llm=None):
>     engine.map_engine = MapEngine()        # ↓ 第2次（完全相同）
>     engine.char_engine = CharacterEngine() #
>     ...（约100行）
>
> # 应该改为：
> def _build_engine_stack(self, llm):        # ← 提取为辅助函数
>     self.map_engine = MapEngine()
>     ...
> ```
>
> **问题 B：`FACTION_CONFIGS` 和 `NPC_FACTION_CONFIGS` 完全相同**（约 40 行），且与 `histrategy-knowledge/` 的 JSON 数据重复。重构后这些应该完全删除，由 ScenarioLoader 读取 JSON。

### 1.4 可消除的冗余统计（更新）

| 文件 | 行数 | 替代方案 | 阻断 | 实际调用方 |
|---|---|---|---|---|
| `state/world_state.py` | 391 | `histrategy-engine` WorldState | 旧 CLI 仍依赖 | CLI, v1_simulator |
| `engine/world.py` | 348 | 同上 | offline_sim 引用 | offline_sim.py |
| `engine/offline_sim.py` | 1029 | DomesticEngine + MilitaryEngine | 需要迁移所有调用方 | offline_sim_engine.py |
| `engine/offline_sim_engine.py` | 139 | 同上 | ⚠️ game.py:898-903 引用 | game.py v2 fallback |
| `engine/resilient_sim_engine.py` | 73 | 同上 | ⚠️ game.py:898 引用 | game.py v2 fallback |
| `engine/v1_simulator.py` | 416 | MacroPolicyEngine (v3) | room_manager 仍调用 | room_manager.py:758 |
| `game.py` 重复代码 | ~200 | `_build_engine_stack()` 辅助函数 | 无 | — |
| `FACTION_CONFIGS` dict | ~40 | ScenarioLoader + JSON | 无 | game.py:66-142 |
| **合计** | **~2,636 行** | **~28%** | — |

---

## 二、目标架构

### 2.1 引擎统一

```
histrategy（主仓库）
│
├── histrategy-engine/     ← 唯一确定性引擎（pip 包）
│   ├── world/              WorldState, FactionState, Territory, Army
│   ├── domestic/           粮食、人口增长、税收
│   ├── military/           征兵、战斗结算、兵种（含 naval_power 扩展点）
│   ├── character/          武将忠诚度
│   ├── governance/         合法性、政治影响力（caesar/shanhe 需要）
│   ├── ai/                 NPC 决策、战争迷雾
│   ├── history/            历史事件 RAG
│   ├── turn/               回合控制器
│   └── rules/              YAML 规则解释器
│
├── histrategy-sdk/         ← 人类玩家 SDK（pip 包）
│   └── Room (SQLite), ServerClient, DirectEngine
│
├── histrategy-agent/       ← Agent 集成（pip 包）
│   └── TurnProcessor, StateBridge, FormatEngine, IM adapters
│
├── histrategy/             ← 场景层 + CLI + Server（精简后）
│   ├── engine/
│   │   ├── game.py           ← 精简到 ~800 行（删除 v1/重复代码）
│   │   ├── loader.py         ← 重构为 ScenarioLoader 类
│   │   └── macro_policy_engine.py  ← 保留（v3 模式使用）
│   ├── llm/                  LLM prompt + adapter（场景感知）
│   ├── server/               FastAPI 服务
│   └── cli/                  CLI 入口
│
├── scenarios/              ← 场景数据包（纯 JSON/TOML/Markdown，无 Python）
│   ├── three-kingdoms/
│   ├── caesar-44bc/         ← 4 势力版本
│   └── shanhe-dingge/
│
└── histrategy-knowledge/   ← 历史知识库（只读 JSON，逐步迁移到 scenarios/）
```

### 2.2 删除清单（调整后的顺序）

> **[审阅意见]** 原计划 P1.1「确认 offline_sim_engine.py 无调用方后删除」不准确。`game.py:898-903` 确实调用了它们（v2 路径的 offline fallback）。正确顺序：

**Pre-Phase: 代码去重（无风险，最先做）**
- [ ] 提取 `game.py._build_engine_stack()` 辅助函数，合并 `_init_v2` 和 `from_dict` 的重复代码（~200行→~50行）
- [ ] 删除 `FACTION_CONFIGS` 和 `NPC_FACTION_CONFIGS`（由 ScenarioLoader 接管）
- [ ] 合并 `load_territories()` 的硬编码数据到 `scenarios/three-kingdoms/knowledge/territories.json`

**Phase 1: WorldState 统一**
- [ ] P1.1 迁移 `state/world_state.py` 调用方 → `histrategy-engine` WorldState（CLI, v1_simulator, game.py）
- [ ] P1.2 迁移 `engine/world.py` → 同上（offline_sim 引用）
- [ ] P1.3 迁移 `offline_sim.py` 规则仿真 → DomesticEngine + MilitaryEngine（game.py fallback）
- [ ] P1.4 删除 `offline_sim_engine.py` + `resilient_sim_engine.py`（P1.3 完成后的调用方消失）

**Phase 2: v1 退役**
- [ ] P2.1 确认 v3 MacroPolicyEngine 稳定，所有活跃房间迁移
- [ ] P2.2 删除 `engine/v1_simulator.py`（room_manager 调用方同步更新）
- [ ] P2.3 删除 `state/world_state.py`（P1.1 完成后）

---

## 三、同仓库多场景策略

### 3.1 架构决策（已确认）

> ✅ **2026-06-15 最终决策**: 所有场景在 histrategy 仓库内作为 `scenarios/` 子目录，不新建独立 repo。

**理由**：
1. 场景包是纯数据（JSON + TOML + prompts + rules），不需要独立 Python 代码仓
2. 独立 repo 会制造版本漂移——协调升级成本高
3. 跨文明场景（三国 vs 罗马）在同仓库激励引擎抽象层成熟
4. 运维简化：一个 Railway 服务托管所有场景，API 路由 `/api/scenarios/{id}/...` 统一

### 3.2 当前场景矩阵

| 场景 ID | 名称 | 时代 | 状态 | 势力数 | 特殊机制 |
|---------|------|------|------|--------|----------|
| `three-kingdoms` | 《三國志略》 | 207-280 | **生产** | 4 | 陆战为主 |
| `caesar-44bc` | 《凯撒余烬》 | 44-30 BC | **骨架** | **4**（修正） | 海战/宣传战/元老院 |
| `shanhe-dingge` | 《山河鼎革》 | 1644-1662 | **骨架** | 4 | 火炮/多族/正统衰减 |

### 3.3 ScenarioLoader 设计 ✅ 已实现

`histrategy/engine/scenario_loader.py` (548行) — 完整实现，含以下方法：

- `load_factions()` / `load_characters()` / `load_territories()` / `load_events()` — 数据加载
- `load_prompt(name)` — 场景特定 LLM prompt 模板
- `load_rules()` — 规则 YAML 加载
- `build_world_state(player_faction_id)` — 组装完整 WorldState
- `format_year(year)` — 年份格式化（支持 BC）
- `list_scenarios(root)` — 静态方法，列出所有可用场景

**调用方式**:
```python
from histrategy.engine.scenario_loader import ScenarioLoader
loader = ScenarioLoader("caesar-44bc")
ws = loader.build_world_state("octavian")  # WorldState with 8 factions, year=-43
```

---

## 四、持久化架构决策

### 4.1 SDK+SQLite > 文件锁 > HTTP server

| 维度 | SDK + SQLite WAL | 文件锁（旧方案） | HTTP server |
|---|---|---|---|
| OpenClaw 重启 | ✅ 事务保证，零丢失 | ⚠️ crash 可能半写 | ❌ 内存状态丢（除非也加 DB） |
| 运维成本 | ✅ 无端口/进程 | ✅ 无端口/进程 | ❌ Railway 服务 + 端口管理 |
| 多人并发 | ✅ `BEGIN EXCLUSIVE` 排他锁 | ⚠️ advisory lock 不可靠 | ✅ 天然并发 |
| 调试 | ⚠️ 无 /docs | ⚠️ 同左 | ✅ Swagger UI |
| 崩溃恢复 | ✅ 自动回滚 | ❌ 需要手动修复 JSON | ✅ 事务保证 |

**结论**：OpenClaw + Feishu 场景 → SDK+SQLite 模式。多人 Web UI → 每次请求从 SQLite/PostgreSQL reload。

### 4.2 /mp UI 持久化（技术债务）

当前 `room_manager.py` 有内存 `_rooms: dict[str, GameRoom]` 缓存，需要改造：

```python
# 目标：每次 HTTP 请求从 SQLite reload
async def handle_decision(room_id: str, decision: str):
    async with room_manager.load_room(room_id) as room:  # 从 DB 加载
        result = await room.execute(decision)
        await room.save()  # 写回 DB
        return result
    # 离开 context manager 后 room 对象销毁，无内存缓存
```

---

## 五、执行计划（已修订）

### Pre-Phase: 代码去重 ✅ 已完成

| # | 任务 | 预计删除/简化 | 状态 |
|---|---|---|---|
| P0.1 | 提取 `game.py._build_engine_stack()` 合并 `_init_v2`/`from_dict` | ~200行 | ✅ done |
| P0.2 | 删除 `FACTION_CONFIGS`/`NPC_FACTION_CONFIGS` dict | ~80行 | ✅ done |
| P0.3 | 新建 `scenarios/three-kingdoms/knowledge/territories.json`，删除 `load_territories()` 硬编码 | ~300行 | ✅ done |

**成果**: `game.py` 从 2,866 → ~2,400 行（零回归，236 测试通过）

### Phase 1: WorldState 统一 ✅ 部分完成

| # | 任务 | 影响范围 | 预计删除 | 状态 |
|---|---|---|---|---|
| P1.1 | 迁移 `state/world_state.py` → `histrategy_engine.world` | CLI, v1_simulator, game.py | ~391行 | ⚠️ 向后兼容 shim 已加；CLI 仍用旧 WorldState |
| P1.2 | 迁移 `engine/world.py` → 同上 | offline_sim | ~348行 | ⚠️ 向后兼容属性已加 |
| P1.3 | 迁移 `offline_sim.py` → DomesticEngine + MilitaryEngine | game.py fallback | ~1029行 | ⬜ 未开始 |
| P1.4 | 删除 `offline_sim_engine.py` + `resilient_sim_engine.py` | — | ~212行 | ⬜ 未开始 |

**成果**: 添加了 `get_player_faction()`, `strength`/`strength_actual` 别名，`_coerce_factions_to_dict()` 兼容层。完整统一需待 v1 CLI 退役。

### Phase 2: ScenarioLoader 升级 ✅ 已完成

| # | 任务 | 状态 |
|---|---|---|
| P2.1 | 实现 `ScenarioLoader` 类（`histrategy/engine/scenario_loader.py`） | ✅ done (548行) |
| P2.2 | `GameEngine.__init__` 改为 `ScenarioLoader(scenario_id).build_world_state()` | ✅ done |
| P2.3 | 删除 `loader.py` 的旧函数接口（保留 `resolve_knowledge_path()` 作为路径辅助） | ✅ done |
| P2.4 | `scenarios/caesar-44bc/knowledge/factions.json` 采用用户方案 4 主势力 | ✅ done |

### Phase 3: 场景内容充实

| # | 任务 |
|---|---|
| P3.1 | 《凯撒余烬》prompts/system.md（罗马史诗叙事风格） |
| P3.2 | 《凯撒余烬》rules/naval.yaml + rules/propaganda.yaml |
| P3.3 | 《山河鼎革》knowledge 数据充实（4 势力 + 历史事件链） |

### Phase 4: 持久化完善

| # | 任务 |
|---|---|
| P4.1 | `room_manager.py` 去掉内存 dict 缓存，改为每次请求从 SQLite reload |
| P4.2 | 完成 `GameRoom.save()`/`load()` 的全字段序列化 |
| P4.3 | Server 重启后状态恢复验证（E2E 测试） |

### Phase 5: 前端多场景 + 引擎扩展

| # | 任务 | 状态 |
|---|---|---|
| P5.1 | `/mp` UI 支持 `?scenario=caesar` 等场景参数 | ✅ done — `mp.html` 完全重写，动态势力加载 |
| P5.2 | `/api/scenarios` REST 端点（列出场景 + 势力） | ✅ done — 含 metadata (name/period/start_year/factions) |
| P5.3 | 创建房间时动态加载 NPC 势力（不再硬编码三国） | ✅ done — `room_manager.py:create_room` 使用 ScenarioLoader |
| P5.4 | BC 年份渲染支持 | ✅ done — `format_year()` + Web UI `fmtYear()` |
| P5.5 | 引擎核心添加 `naval_power` 维度（亚克兴海战） | ⬜ 待实施 |
| P5.6 | 引擎核心添加 `political_influence` + `propaganda` 维度 | ⬜ 待实施 |

---

## 六、风险与注意事项（已更新）

1. **V1 还在生产使用** — `room_manager.py:758` 仍调用 `V1Simulator`。删除 `v1_simulator.py` 之前必须确保 V3 稳定且 `room_manager` 已切换。

2. **WorldState 序列化兼容** — 旧 `state/world_state.py` 的 JSON 格式与新 `histrategy-engine` 不同。迁移时需要写转换脚本处理已有存档（`world_v2.json` 格式不受影响，只有旧 CLI 存档受影响）。

3. **`load_territories()` 硬编码** — 这是目前最隐蔽的 bug：`loader.py` 忽略 `knowledge_path` 参数，直接返回硬编码三国城市数据。新场景如果依赖这个函数会静默地得到错误地图。修复必须在 Phase 2 的 ScenarioLoader 升级中处理。

4. **测试覆盖** — 每个 Phase 完成后运行全量 `pytest tests/ -q`。Phase 1 涉及引擎替换，需要特别关注 E2E 测试。

5. **场景优先级** — 《凯撒余烬》先于《山河鼎革》（海战/宣传战系统可复用，减少重复工作）。

---

## 九、Web UI 多场景支持 (2026-06-15 新增)

### 9.1 `/api/scenarios` 端点

```json
GET /api/scenarios
{
  "ok": true,
  "scenarios": [
    {
      "id": "caesar-44bc",
      "name_cn": "凯撒余烬",
      "period": "罗马共和国末期 (44 BC - 30 BC)",
      "start_year": -43,
      "epoch": "",
      "factions": [
        {"id": "octavian", "name_cn": "屋大维", "color": "gold"},
        {"id": "antony", "name_cn": "马克·安东尼", "color": "red"},
        ...
      ]
    },
    ...
  ]
}
```

### 9.2 `mp.html` 场景感知架构

```
mp.html?scenario=caesar-44bc
  │
  ├─ onLoad → GET /api/scenarios → 填充场景下拉菜单
  ├─ onScenarioChange → 重新渲染势力 toggle
  ├─ doCreateRoom → POST /api/rooms {scenario: "caesar-44bc", ...}
  ├─ doJoinRoom  → POST /api/rooms/{id}/enter {faction: "octavian"}
  └─ updateGameUI → 动态格式化年份（BC/AD），势力颜色渲染
```

### 9.3 `room_manager.py` 场景化改造

- `create_room()` — NPC 势力从 `ScenarioLoader.load_factions()` 动态获取，不再硬编码 `LLM_NPC_FACTIONS`
- `_init_world_state()` — 非三国场景使用 `ScenarioLoader.build_world_state()` 替代 `create_initial_world()`
- 年份/季节从 WorldState 同步到房间 `room.year`/`room.season`

### 9.4 已知限制

| 限制 | 影响 | 解决方案 |
|------|------|---------|
| CLI 不支持场景选择 | `cli/app.py` 仍硬编码三国 | 待 CLI 重构到 v3 |
| game_master intro prompt 未切换 | 首次创建 room 时 narrative 可能仍是三国文本 | 需接入 ScenarioLoader 的 prompt 加载 |
| NPC 决策引擎未场景化 | 多 NPC 推演在 LLM 模式下可能引用错误势力 ID | 需 `_trigger_npc_decisions` 使用场景 faction 列表 |

---

## 七、决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 引擎统一 | `histrategy-engine` 为唯一引擎 | 消除维护两套代码的成本 |
| 场景分离 | `histrategy/scenarios/{id}/` 独立目录 | 纯数据分离，便于新场景开发 |
| 持久化 | SDK + SQLite WAL | 比文件锁更健壮，无需常驻服务器 |
| 多场景部署 | 同仓库 monorepo | 避免版本漂移，统一 API，跨文明激励引擎抽象 |
| caesar 势力数 | **4 个**（非 8 个） | 与三国一致，降低复杂度，Hermes scaffold 需修正 |
| v1 保留 | 渐进式删除，V3 稳定后再删 | 避免生产中断 |
| game.py 精简方式 | 先提取 `_build_engine_stack()` | 无破坏性变更，立即可做 |

---

## 八、《凯撒余烬》跨文明场景设计发现

> 2026-06-15 新增 — 创建罗马内战场景过程中发现的关键设计洞察。

### 8.1 三国 vs 罗马：引擎抽象的压力测试

| 维度 | 三国 (207 AD) | 罗马 (44 BC) | 引擎抽象建议 |
|------|--------------|-------------|-------------|
| 冲突结构 | 三角均势（曹/刘/孙） | 两极对抗（屋大维/安东尼）+ 第三方 | 支持 N 方任意格局 |
| 军事核心 | 陆战、骑兵、攻城 | **海战为主**（亚克兴）、军团制 | 添加 `naval_power` 维度 |
| 政治维度 | 合法性强弱（挟天子） | **元老院政治、宣传战** | 添加 `political_influence` |
| 经济基础 | 农业税、屯田 | 埃及粮仓、海上贸易封锁 | 添加 `trade_blockade` 机制 |
| 外部威胁 | 南蛮、山越 | **帕提亚帝国** | 支持 `external_threat` 势力类型 |
| 关系系统 | 君臣、父子、结义 | **情人、养子、政治联姻** | 关系系统支持复杂动态联盟 |

### 8.2 引擎缺口（需在 Phase 5 填补）

1. **海军体系缺失**：三国引擎中没有 `ships` 字段和海战结算公式，《凯撒余烬》核心战役（瑙洛库斯、亚克兴）都是海战
2. **宣传/政治资本**：罗马内战中「公敌宣告」「亚历山大里亚赠礼」等非军事行为对战争结果有决定性影响
3. **两极对抗格局**：引擎预设多方均势，但罗马内战本质是 1v1（屋大维 vs 安东尼），需要支持非对称博弈

### 8.3 场景自定义字段策略

**引擎核心只认通用字段**（strength/food/treasury/morale），场景自定义字段通过 `schema.json` 声明，由场景特定的 rules YAML 解释。`ScenarioLoader` 加载时自动合并，引擎运行时只传递到 rules 层。

### 8.4 叙事风格的差异化

| 场景 | 语言 | 叙事基调 | 参考作品 |
|------|------|---------|---------| 
| 三国 | zh-CN，文白相间 | 史诗谋略、群雄逐鹿 | 《三国演义》《大军师司马懿》 |
| 凯撒余烬 | zh-CN，史诗叙事 | 阴谋野心、帝国命运 | HBO《罗马》《奥古斯都》 |
| 山河鼎革 | zh-CN，文白相间 | 末世挣扎、多族冲突 | 《南明史》《康熙王朝》 |

---

*计划维护在 `docs/design/refactor-engine-unification.md`*
*推送到 `feat/engine-merge-v3-macro` 分支*
