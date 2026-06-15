# histrategy 重构计划：消除冗余 + 引擎统一 + 多场景复用

> **状态**: 草案，等待 Claude Opus 审阅
> **日期**: 2026-06-14
> **作者**: Prometheus (Hermes Agent)

---

## 一、问题诊断

### 1.1 三套 WorldState 并存

```
histrategy/state/world_state.py        (391行) ← CLI/v1 使用，自成一派
histrategy/engine/world.py             (348行) ← offline_sim 使用，GameWorld
histrategy-engine/.../world/           (新)    ← pip 包，正确实现
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

### 1.3 可消除的冗余统计

| 文件 | 行数 | 替代方案 | 阻断 |
|---|---|---|---|
| `state/world_state.py` | 391 | `histrategy-engine` WorldState | 旧 CLI 仍依赖 |
| `engine/world.py` | 348 | 同上 | offline_sim 引用 |
| `engine/offline_sim.py` | 1029 | DomesticEngine + MilitaryEngine | 需要迁移所有调用方 |
| `engine/offline_sim_engine.py` | 139 | 同上 | |
| `engine/resilient_sim_engine.py` | 73 | 同上 | |
| `engine/v1_simulator.py` | 416 | MacroPolicyEngine (v3) | v1 还在生产使用 |
| **合计** | **~2,396 行** | **26%** | |

---

## 二、目标架构

### 2.1 引擎统一

```
histrategy（主仓库）
│
├── histrategy-engine/     ← 唯一确定性引擎（pip 包）
│   ├── world/              WorldState, FactionState, Territory, Army
│   ├── domestic/           粮食、人口增长、税收
│   ├── military/           征兵、战斗结算、兵种
│   ├── character/          武将忠诚度
│   ├── governance/         合法性、政策系统
│   ├── ai/                 NPC 决策、战争迷雾
│   ├── history/            历史事件 RAG
│   ├── turn/               回合控制器
│   └── rules/              YAML 规则解释器
│
├── histrategy-sdk/         ← 人类玩家 SDK（pip 包）
│   └── Room, ServerClient, MultiplayerRoom
│
├── histrategy-agent/       ← Agent 集成（pip 包）
│   └── TurnProcessor, StateBridge, FormatEngine, IM adapters
│
├── histrategy/             ← 场景层 + CLI + Server
│   ├── scenario/            ← 新建：场景数据 + loader（与引擎解耦）
│   │   ├── 207/
│   │   │   ├── loader.py   207 年三国剧本
│   │   │   ├── events.py   历史事件链
│   │   │   └── data/       势力/地图/角色 JSON
│   │   └── 1644/            ← 未来：《山河鼎革》
│   ├── llm/                 LLM prompt + adapter（场景感知）
│   ├── server/              FastAPI 服务
│   └── cli/                 CLI 入口
│
└── histrategy-knowledge/    ← 知识库（只读 JSON）
```

### 2.2 删除清单

**Phase 1: 安全删除（无调用方）**
- [ ] `histrategy/engine/offline_sim_engine.py` — 确认无 import 后删除
- [ ] `histrategy/engine/resilient_sim_engine.py` — 同上

**Phase 2: 迁移后删除**
- [ ] `histrategy/state/world_state.py` → 所有调用方改为 `from histrategy_engine.world import WorldState`
- [ ] `histrategy/engine/world.py` → 同上
- [ ] `histrategy/engine/offline_sim.py` → 改为调用 `DomesticEngine` + `MilitaryEngine`

**Phase 3: v1 废弃后删除**
- [ ] `histrategy/engine/v1_simulator.py` → V3 MacroPolicyEngine 稳定后删除

---

## 三、《山河鼎革》1644-1662：新 repo 复用策略

### 3.1 复用分析

```
《山河鼎革》代码组成:
┌──────────────────────────────────────────┐
│ histrategy-engine   (pip install)  ~90%  │  确定性引擎完全复用
│ histrategy-agent    (pip install)  ~85%  │  IM 适配器 + session 管理
│ histrategy-sdk      (pip install)  ~20%  │  Room 模式可参考
├──────────────────────────────────────────┤
│ 新写:                                     │
│   scenario/1644/loader.py              │  势力初始化（南明/满清/大顺/郑成功）
│   scenario/1644/events.py              │  1644-1662 历史事件链
│   llm/prompts/                         │  明末清初叙事 prompt
│   web/                                 │  前端 UI（势力/地图不同）
└──────────────────────────────────────────┘

总体复用率: 55-65%
```

### 3.2 建议 repo 结构

```
emergencescience/shanhedinge/
├── pyproject.toml          depends: histrategy-engine>=0.2.0
├── shanhedinge/
│   ├── scenario/
│   │   └── loader.py        加载 1644 场景
│   ├── llm/
│   │   └── prompts/         明末叙事 prompt
│   ├── server/              FastAPI（复用 histrategy server 模式）
│   └── cli/                 CLI 入口
├── data/
│   └── 1644_reference.md   势力初始数据
└── web/                     前端（/mp UI）
```

### 3.3 场景参数化关键

将 `histrategy/engine/loader.py` (783行) 重构为**场景无关的 loader 框架** + 场景特有的 YAML/JSON 数据：

```yaml
# data/1644_reference.yaml
scenario:
  name: "山河鼎革"
  start_year: 1644
  end_year: 1662
  season: "春"
  factions:
    - id: nanming
      name: "南明"
      ruler: "弘光帝"
      territories: ["nanjing", "yangzhou", ...]
      initial:
        troops: 80000
        food: 50000
        treasury: 40000
        morale: 55
    - id: manqing
      name: "满清"
      ruler: "顺治帝"
      ...
```

这样 loader.py 从 ~800 行精简到 ~200 行，场景数据完全外部化。

---

## 四、持久化架构决策

### 4.1 SDK+SQLite reload > HTTP server

| 维度 | SDK + SQLite reload | HTTP server 模式 |
|---|---|---|
| OpenClaw 重启 | ✅ 从 DB 加载，零丢失 | ❌ 内存状态丢（除非也加 DB） |
| 运维成本 | ✅ 无端口/进程 | ❌ Railway 服务 + 端口管理 |
| 多人并发 | ⚠️ SQLite WAL 串行写 | ✅ 天然并发 |
| 调试 | ⚠️ 无 /docs | ✅ Swagger UI |
| LLM 延迟 | ✅ 60-90s 可容忍 | 同左 |

**结论**：OpenClaw + Feishu 场景 → SDK 模式。多人 Web UI → 每次请求从 SQLite reload。

### 4.2 /mp UI 持久化

当前 `mp.html` 走 server API。改造为：

```
每个 HTTP 请求:
  GET /api/rooms/{id}/status
  → room_manager 从 SQLite 加载 GameRoom
  → 返回当前状态
  → 不依赖内存中的 dict

POST /api/rooms/{id}/decide
  → 加载 GameRoom
  → 执行决策
  → 保存回 SQLite
  → 返回结果
```

`room_manager.py` 已部分实现（`GameRoom.save()`/`load()`），需要完成迁移：去掉内存 dict 缓存，改为每次都从 DB 读。

---

## 五、执行计划

### Phase 1: 引擎瘦身（本周）

| # | 任务 | 影响范围 | 预计删除 |
|---|---|---|---|
| P1.1 | 确认 `offline_sim_engine.py` + `resilient_sim_engine.py` 无调用 | grep 全仓库 | ~210行 |
| P1.2 | 迁移 `state/world_state.py` 调用方 → `histrategy-engine` WorldState | CLI, v1_simulator, game.py | ~391行 |
| P1.3 | 迁移 `engine/world.py` → `histrategy-engine` WorldState | offline_sim | ~348行 |
| P1.4 | 迁移 `offline_sim.py` 规则模拟 → `DomesticEngine` + `MilitaryEngine` | game.py fallback | ~1029行 |
| P1.5 | 删除 `v1_simulator.py`（待 V3 稳定） | game.py v1 路径 | ~416行 |

**Phase 1 目标**: 删除 ~2,400 行冗余，`game.py` 从 2,866 行精简到 ~800 行。

### Phase 2: 场景参数化（下周）

| # | 任务 |
|---|---|
| P2.1 | 将 `loader.py` 重构为场景无关框架 |
| P2.2 | 207 三国数据外部化到 `scenario/207/data/` |
| P2.3 | 1644 场景数据创建（为《山河鼎革》准备） |

### Phase 3: 《山河鼎革》新 repo

| # | 任务 |
|---|---|
| P3.1 | 创建 `emergencescience/shanhedinge` repo |
| P3.2 | 依赖 `histrategy-engine` + 场景 loader |
| P3.3 | 1644 历史事件链 + LLM prompt |
| P3.4 | Feishu bot 集成 |

### Phase 4: 持久化完善

| # | 任务 |
|---|---|
| P4.1 | /mp UI 改为每次请求从 SQLite reload |
| P4.2 | 去掉 room_manager 中的内存 dict 缓存 |
| P4.3 | Server 重启后状态恢复验证 |

---

## 六、风险与注意事项

1. **V1 还在生产使用** — `HISTRATEGY_ENGINE=v1` 是当前 d4a512fb 房间的引擎。删除 v1 之前必须确保 V3 稳定且所有活跃房间迁移完成。

2. **WorldState 序列化兼容** — 旧 `state/world_state.py` 的 JSON 格式与新 `histrategy-engine` 不同。迁移时需要写转换脚本处理已有存档。

3. **测试覆盖** — 每个 Phase 完成后运行全量 `pytest tests/ -q`。Phase 1 涉及引擎替换，需要特别关注 E2E 测试。

4. **《山河鼎革》不急于动手** — 先完成 Phase 1+2（引擎统一+场景参数化），《山河鼎革》自然水到渠成。不要在冗余代码上建新场景。

---

## 七、决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 引擎统一 | `histrategy-engine` 为唯一引擎 | 消除维护两套代码的成本 |
| 场景分离 | `histrategy/scenario/{year}/` 独立目录 | 三国/明清 场景数据隔离，便于新场景开发 |
| 持久化 | SDK + SQLite reload 优先 | OpenClaw 无服务模式最佳适配 |
| 《山河鼎革》 | 新 repo，依赖 engine pip 包 | 代码复用最大化，独立发布周期 |
| v1 保留 | 渐进式删除，V3 稳定后再删 | 避免生产中断 |

---

## 八、讨论邀请

这份重构计划覆盖了引擎、SDK、场景、持久化四个维度的改进。欢迎 Claude Opus 审阅以下关键问题：

1. **WorldState 统一**：是否需要保留 v1 兼容的序列化格式，还是直接 breaking change？
2. **场景参数化**：YAML/JSON 数据文件 vs Python loader 脚本，哪个更适合贡献者？
3. **v1 退役时间表**：生产环境的 d4a512fb 房间还在用 v1，如何处理迁移？
4. **《山河鼎革》**：在 histrategy 内建 `scenario/1644/` 快速原型，还是直接新 repo？

---

*计划维护在 `docs/design/refactor-engine-unification.md`*
*推送到 `feat/engine-merge-v3-macro` 分支*
