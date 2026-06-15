# histrategy 重构计划：消除冗余 + 引擎统一 + 多场景复用

> **状态**: 草案，等待 Claude Sonnet 审阅
> **日期**: 2026-06-15（更新：新增《凯撒余烬》场景 + 跨文明发现）
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
│   ├── scenarios/            ← 场景数据 + loader（与引擎解耦）
│   │   ├── three-kingdoms/   三国 207-280
│   │   ├── caesar/           罗马内战 44-30 BC
│   │   └── shanhe-dingge/    明末清初 1644-1662
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

## 三、同仓库多场景策略（替代独立 repo 方案）

### 3.1 架构决策变更

> **⚠️ 2026-06-15 更新**: 原计划《山河鼎革》独立 repo → 改为全部场景在 histrategy 仓库内作为 `scenarios/` 子目录。

**变更理由**：
1. 场景包（`scenarios/{id}/`）已经证明了完全的数据-引擎分离。knowledge JSON + TOML 配置 + prompt 模板 = 完整场景，不需要独立 repo。
2. 独立 repo 会制造版本漂移——场景 A 依赖 engine v0.3，场景 B 依赖 engine v0.4，协调升级成本高。
3. 跨文明场景（三国 vs 罗马）在同仓库内可以激励引擎抽象层的成熟——如果一个抽象层在两个完全不同的时代都能工作，它就是真正场景无关的。
4. 运维简化：一个 Railway 服务托管所有场景，API 路由 `/api/scenarios/{id}/...` 统一。

### 3.2 当前场景矩阵

| 场景 ID | 名称 | 时代 | 状态 | 势力数 | 特殊机制 |
|---------|------|------|------|--------|----------|
| `three-kingdoms` | 《三國志略》 | 207-280 东汉末 | **生产** | 8 | 陆战为主、三国鼎立 |
| `caesar` | 《凯撒余烬》 | 44-30 BC 罗马内战 | **骨架** | 8 | 海战体系、宣传战、元老院政治 |
| `shanhe-dingge` | 《山河鼎革》 | 1644-1662 明末 | **骨架** | TBD | 多民族势力、火炮火器 |

### 3.3 复用分析

每个场景需要编写的内容（占总量 ~35-45%）：
```
scenarios/{id}/
├── scenario.toml         ← 100行配置
├── knowledge/
│   ├── factions.json     ← 势力定义
│   ├── characters.json   ← 角色（含 traits）
│   ├── events.json       ← 历史事件链（18-25个）
│   ├── initial_state.json← 起始状态
│   ├── territories.json  ← 领土地图
│   ├── regions.json      ← 地理区域
│   ├── timeline.json     ← 历史时间线
│   ├── roster.json       ← 势力-角色映射
│   ├── arc_goals.json    ← 剧情弧线
│   └── schema.json       ← 场景自定义字段schema
├── prompts/              ← LLM system prompt（场景特有叙事风格）
├── rules/                ← YAML 政策规则（场景特有机制）
├── web/                  ← SVG地图 + CSS主题
└── cli/                  ← CLI入口/品牌
```

引擎核心（`histrategy-engine/`）**完全复用，0% 场景代码**。

### 3.4 场景参数化框架

`ScenarioLoader` 已实现（H16c, `histrategy/engine/scenario_loader.py`, 345行），支持：
- `scenario.toml` 元数据解析
- knowledge JSON 自动加载和校验
- BC 年份支持（负数年份 → 显示「公元前X年」）
- 场景自定义字段在 factions 上扩展（如 `legions`, `ships`, `government`）
- 默认值回退机制（新字段不破坏旧场景）

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

### Phase 2: 场景充实

| # | 任务 |
|---|---|
| P2.1 | 《凯撒余烬》prompt 模板编写（罗马史诗叙事风格） |
| P2.2 | 《凯撒余烬》policy rules YAML（海战、宣传战、元老院机制） |
| P2.3 | 《山河鼎革》knowledge 数据充实 + prompt 模板 |
| P2.4 | ScenarioLoader 增强：BC 年份渲染、schema 校验、自定义字段回退 |

### Phase 3: 前端多场景支持

| # | 任务 |
|---|---|
| P3.1 | `/mp` UI 支持 `?scenario=caesar` 等场景参数 |
| P3.2 | 每个场景独立 SVG 地图 + CSS 主题 |
| P3.3 | 场景选择器 UI（游戏大厅） |

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

4. **场景优先级** — 用户已指示暂停《山河鼎革》，先完成《凯撒余烬》的场景骨架（✅ 已完成）和 prompt/rules 填充。

---

## 七、决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 引擎统一 | `histrategy-engine` 为唯一引擎 | 消除维护两套代码的成本 |
| 场景分离 | `histrategy/scenarios/{id}/` 独立目录 | 三国/罗马/明清 场景数据隔离，便于新场景开发 |
| 持久化 | SDK + SQLite reload 优先 | OpenClaw 无服务模式最佳适配 |
| 多场景部署 | 同仓库 monorepo | 避免版本漂移，统一 API 路由，跨文明场景激励引擎抽象 |
| v1 保留 | 渐进式删除，V3 稳定后再删 | 避免生产中断 |

---

## 八、《凯撒余烬》跨文明场景设计发现

> **2026-06-15 新增** — 创建罗马内战场景过程中发现的关键设计洞察。

### 8.1 三国 vs 罗马：引擎抽象的压力测试

将公元前44年的罗马内战映射到为三国设计的引擎上，是一次天然的抽象层压力测试：

| 维度 | 三国 (207 AD) | 罗马 (44 BC) | 引擎抽象建议 |
|------|--------------|-------------|-------------|
| 冲突结构 | 三角均势（曹/刘/孙） | 两极对抗（屋大维/安东尼）+ 第三方摇摆 | 支持 N 方任意格局，不预设三方 |
| 军事核心 | 陆战、骑兵、攻城 | **海战为主**（亚克兴海战）、军团制 | 添加 `naval_power` 维度和海战结算 |
| 政治维度 | 合法性强弱（挟天子） | **元老院政治、宣传战、公民投票** | 添加 `political_influence` 和 `propaganda` 维度 |
| 经济基础 | 农业税、屯田 | 埃及粮仓、海上贸易封锁 | 添加 `trade_blockade` 机制 |
| 外部威胁 | 南蛮、山越 | **帕提亚帝国**（独立外部势力） | 支持 `external_threat` 势力类型 |
| 角色关系 | 君臣、父子、结义 | **情人、养子、政治联姻** | 关系系统支持更复杂的动态联盟 |
| 时间单位 | 季度/年 | 季度/年（BC 需要负数年） | 支持负数年份渲染 |

### 8.2 发现的引擎缺口

1. **海军体系缺失**：三国的赤壁之战虽然是水战，但引擎中没有 `ships` 字段和海战结算公式。《凯撒余烬》的核心战役（瑙洛库斯、亚克兴）都是海战——这迫使引擎必须支持海军。

2. **宣传/政治资本系统**：罗马内战中的「公敌宣告」「亚历山大里亚赠礼」「遗嘱公布」都是非军事行为，但对战争结果有决定性影响。三国中「挟天子以令诸侯」是类似概念，但未被建模为独立系统。

3. **两极对抗 + 第三方的博弈模式**：三国预设了三方均势，但罗马内战本质是 1v1（屋大维 vs 安东尼），克利奥帕特拉、塞克斯图斯、雷必达都是被卷进去的第三方。引擎需要支持非对称的多方博弈。

4. **客户端王国模式**：希律、各东方王国在罗马与帕提亚之间摇摆——这是三国中不存在的「附庸国」概念。

### 8.3 场景自定义字段策略

`scenarios/caesar/knowledge/factions.json` 引入了三国场景不存在的字段：
- `legions`: 军团数量（罗马制）
- `ships`: 战舰数量
- `government`: 政府类型（heir/consul/republic/pharaoh/triumvir/senate/renegade/empire）

策略：**引擎核心只认通用字段（strength/food/treasury/morale），场景自定义字段通过 `schema.json` 声明，由场景特定的 rules YAML 解释。ScenarioLoader 加载时自动合并，引擎运行时只传递到 rules 层。**

### 8.4 叙事风格的差异化

| 场景 | 语言 | 叙事基调 | 参考作品 |
|------|------|---------|---------|
| 三国 | zh-CN，文白相间 | 史诗谋略、群雄逐鹿 | 《三国演义》《大军师司马懿》 |
| 凯撒余烬 | zh-CN，史诗叙事 | 阴谋野心、帝国命运 | HBO《罗马》《奥古斯都》 |
| 山河鼎革 | zh-CN，文白相间 | 末世挣扎、多族冲突 | 《南明史》《康熙王朝》 |

每个场景的 LLM system prompt 独立编写在 `prompts/system.md`。

---

## 九、讨论邀请

这份重构计划覆盖了引擎、场景、持久化三个维度的改进，并新增了跨文明场景设计洞察。欢迎 Claude Sonnet 审阅以下关键问题：

1. **WorldState 统一**：是否需要保留 v1 兼容的序列化格式，还是直接 breaking change？
2. **海军体系**：《凯撒余烬》要求的海战结算，应该在引擎核心实现（供所有场景使用）还是作为场景 rule YAML？（个人倾向：引擎核心添加 generic naval framework，具体结算公式在 rule YAML）
3. **跨文明引擎压力测试**：8.1 中发现的三国 vs 罗马差异，是否需要在 Phase 1（引擎瘦身）之前先做引擎抽象层设计？
4. **v1 退役时间表**：生产环境的 d4a512fb 房间还在用 v1，如何处理迁移？
5. **场景优先级**：《凯撒余烬》和《山河鼎革》哪个先填充 prompt + rules 达到可玩状态？
6. **BC 年份支持**：ScenarioLoader 的负数年渲染方案是否合理？

---

*计划维护在 `docs/design/refactor-engine-unification.md`*
*推送到 `feat/engine-merge-v3-macro` 分支*
