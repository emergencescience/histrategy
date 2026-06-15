# H15m: 《山河鼎革》Repo 决策

**日期**: 2026-06-15
**状态**: ✅ 已决策 → **同仓库 monorepo**（`scenarios/shanhe-dingge/`）
**审阅**: Claude Sonnet 4.6 (2026-06-15)

---

> **[审阅意见]** 原始建议（新 repo）基于独立 pip 包假设，但现在 `scenarios/` 目录已证明场景可以纯数据分离（无需独立代码仓）。同仓库方案已在 `refactor-engine-unification.md` 中确认。本文档更新为记录该决策并补充注意事项。

---

## 一、现有可复用资产盘点（已更新）

| 模块 | 包 | LOC | 复用率 | 实际状态 |
|------|-----|-----|--------|---------|
| **确定性仿真引擎** | `histrategy-engine` | 4,705 | **90%** | ✅ 独立 pip 包，`WorldState`/引擎已解耦 |
| **知识库** | `histrategy-knowledge/` | JSON | **95%** | ✅ 同三国时代，历史人物有重叠 |
| **LLM 适配器** | `histrategy/llm/adapter.py` | 684 | **95%** | ✅ 多 provider，场景无关 |
| **WorldState** | `histrategy_engine.world` | ~400 | **85%** | ✅ 已统一到 engine，`loader.py` 作为场景适配层 |
| **ScenarioLoader** | `histrategy/engine/loader.py` | 784 | **100%** | ✅ `build_world_state()` 已参数化，新场景只需换 JSON |
| **Rules YAML** | `histrategy-engine/rules/` | YAML | **100%** | ✅ 参数化，换时代只需改 YAML |
| **Narrative 引擎** | `histrategy/llm/narrative.py` | 549 | **30%** | ⚠️ 文白相间风格可复用，叙事模板需重写 |
| **游戏引擎逻辑** | `histrategy/engine/game.py` | 2,866 | **15%** | ⚠️ 重构后将降至 ~800 行，复用率提升到 ~60% |
| **CLI / Server** | 多个 | ~6,000 | **70%** | ✅ 场景作为参数，不是 fork 点；`api.py` 已参数化 |

> **关键修正**：原估算「CLI/Server 0% 复用」不准确。现有 `api.py` 和 `room_manager.py` 已经通过 `scenario` 字段参数化，新场景无需修改 server 代码。

### 综合复用率（修正后）

|  | LOC | 可复用 LOC |
|--|-----|-----------|
| 引擎 + SDK + Agent | ~15,000 | **~12,000** |
| 场景专属新代码 | ~3,000 | 0 |
| **总计** | **~18,000** | **~67%** |

> 相较原估算大幅提升，因为 server/CLI 无需 fork，只需新增 `scenarios/shanhe-dingge/` 数据目录。

---

## 二、方案对比（已修订）

### 方案 A: 在 histrategy repo 内 `scenarios/` 子目录（**已选择**）

| 优点 | 缺点 / 注意事项 |
|------|----------------|
| 零设置成本，即刻开工 | `scenarios/` 目录数据体积增长 |
| 共享 CI / lint / pre-commit | 场景 JSON schema 需严格约束，避免污染引擎 |
| 引擎抽象层被两个完全不同的场景"压力测试" | 引擎的 `naval_power` / `political_influence` 字段需要在重构时规划好 |
| 统一 API 路由 `/api/scenarios/{id}/...` | — |
| 无版本漂移（场景和引擎同步演进） | — |
| 一个 Railway 服务托管所有场景 | — |

### 方案 B: 新 repo（**已排除**）

> 排除理由：`scenarios/{id}/` 目录已经证明场景可以是纯数据包（JSON + TOML + prompts + rules），不需要独立 Python 代码。独立 repo 的唯一受益方是引擎 API 的外部消费者——当前不存在这个角色。

---

## 三、最终架构（monorepo 内）

```
histrategy/                         ← 主仓库（不变）
├── histrategy-engine/              ← 场景无关引擎（pip 包）
│   └── src/histrategy_engine/
│       ├── world/                  WorldState, FactionState
│       ├── domestic/               经济/粮草
│       ├── military/               军事/兵种
│       ├── character/              武将忠诚度
│       ├── governance/             合法性/政治资本  ← 山河鼎革需要
│       ├── ai/                     NPC AI
│       ├── turn/                   回合控制器
│       └── rules/                  YAML 规则解释器
│
├── scenarios/                      ← 场景数据包（无独立 Python 代码）
│   ├── three-kingdoms/             ← 三国 207-280
│   │   ├── scenario.toml
│   │   ├── knowledge/              factions/characters/regions/events
│   │   ├── prompts/                LLM system prompt（文白相间）
│   │   └── rules/                  economy.yaml, military.yaml
│   │
│   ├── caesar/                     ← 罗马内战 44-30 BC（骨架已建）
│   │   ├── scenario.toml
│   │   ├── knowledge/
│   │   ├── prompts/
│   │   └── rules/
│   │
│   └── shanhe-dingge/              ← 明末清初 1644-1662（待充实）
│       ├── scenario.toml
│       ├── knowledge/              factions.json（4大势力：南明/清/李自成/郑成功）
│       ├── prompts/                叙事风格：末世挣扎、多族冲突
│       └── rules/                  火炮.yaml, 税收.yaml
│
├── histrategy/                     ← 场景层 + CLI + Server（共享）
│   ├── engine/loader.py            ScenarioLoader（按 scenario_id 加载数据）
│   └── server/api.py               REST API（scenario 作为参数）
│
└── histrategy-knowledge/           ← 共享历史知识库（只读 JSON）
```

---

## 四、《山河鼎革》场景特有工程需求

相较三国和罗马，明末清初场景有以下引擎层新需求：

| 需求 | 优先级 | 实现方式 |
|------|--------|---------|
| **火炮/火器** 兵种 | 高 | `rules/military.yaml` 新增 `gunpowder` UnitType |
| **多民族势力** 政治资本 | 高 | `governance/` 的 `political_influence` 字段（与凯撒共用） |
| **南明正统性** 衰减 | 中 | `legitimacy` 字段已存在，只需配置衰减曲线 |
| **清军入关** 事件链 | 中 | `knowledge/events.json` 历史事件链 |
| **郑成功海战** | 低 | 与凯撒的 `naval_power` 共用（优先实现凯撒海战） |

> **建议**：《山河鼎革》优先级低于《凯撒余烬》。先完成凯撒的海战和政治资本系统，再复用到山河鼎革。

---

## 五、决策记录

**选择：monorepo 内 `scenarios/shanhe-dingge/` 子目录**

1. 场景包已证明是纯数据分离——JSON + TOML + prompts + rules，无需独立 repo
2. 引擎重构完成后，复用率 ~67%（远超原估算的 30%）
3. 跨文明场景（三国/罗马/明清）在同仓库激励引擎抽象层成熟
4. 《山河鼎革》势力应为 **4 个**（南明、清、大顺/李自成残部、郑氏），而非更多
