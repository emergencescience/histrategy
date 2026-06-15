# H15m: 《山河鼎革》Repo 决策

**日期**: 2026-06-15
**状态**: 建议 → 新 repo

## 一、现有可复用资产盘点

| 模块 | 包 | LOC | 复用率 | 说明 |
|------|-----|-----|--------|------|
| **确定性仿真引擎** | `histrategy-engine` | 4,705 | **90%** | 已独立 pip 包 (v0.2.0)。Map/Character/Domestic/Military/Decision/Turn/AI — 全部可直接复用 |
| **知识库** | `histrategy/knowledge/` | JSON | **95%** | characters.json, factions.json, regions.json, events.json — 同三国时代 |
| **LLM 适配器** | `histrategy/llm/adapter.py` | 684 | **95%** | 多 provider 自动检测，纯工具层 |
| **WorldState** | `histrategy/state/world_state.py` | ~400 | **70%** | 核心数据结构，需按新游戏扩展字段 |
| **Rules YAML** | `histrategy-engine/rules/` | YAML | **100%** | economy.yaml, historical_events.yaml — 参数化，换时代只需改 YAML |
| **Narrative 引擎** | `histrategy/llm/narrative.py` | 549 | **30%** | 文白相间风格可复用，叙事模板需重写 |
| **游戏引擎逻辑** | `histrategy/engine/` | 9,190 | **15%** | 回合流/Plan-Command 架构可参考，业务逻辑大量不同 |
| **CLI / Server / Agent / SDK** | 多个 | ~6,000 | **0%** | 游戏专属 UI/API，不可复用 |

### 综合复用率估算

| | LOC | 可复用 LOC |
|---|---|---|
| 可复用资产 | ~15,000 | **~6,500** |
| 全新代码 | ~7,000 | 0 |
| **总计** | **~22,000** | **~30%** |

> 注：不含 tests（4,508 LOC），测试需全部重写。

## 二、两方案对比

### 方案 A: 在 histrategy repo 内开发

| 优点 | 缺点 |
|------|------|
| 零设置成本，即刻开工 | repo 膨胀至 70K+ LOC |
| 共享 CI / lint / pre-commit | 两个游戏逻辑耦合，改一个可能破坏另一个 |
| 共享 knowledge base 更新 | 版本混乱：`v2.0` 是 histrategy 还是 山河鼎革？ |
| | 命名空间污染 (`histrategy.engine.game` → GameEngine 指哪个？) |
| | CI 矩阵爆炸（每次 PR 跑两个游戏的测试） |
| | 部署目标不同但共享 Dockerfile |

### 方案 B: 新 repo，依赖 histrategy-engine（推荐）

| 优点 | 缺点 |
|------|------|
| 清晰关注点分离 | 初始设置 ~2h |
| 独立 CI/CD pipeline | histrategy-engine 可能需要增强以适配新游戏 |
| 独立版本、独立发布 | 两个 repo 间协调 knowledge base 更新 |
| 独立社区/文档/Issue | |
| histrategy-engine 成为真正的共享层 | |
| 可独立部署、独立 scaling | |

## 三、推荐架构

```
shanhe-dingge/                    ← 新 repo
├── shanhe/                       ← 游戏专属代码
│   ├── engine/                   ← 新游戏引擎（~3,000 LOC）
│   ├── llm/                      ← 复用 adapter，重写 prompts
│   ├── state/                    ← 继承 WorldState，扩展字段
│   ├── server/                   ← 新 FastAPI server
│   ├── cli/                      ← 新 CLI
│   └── knowledge/                ← symlink 或 submodule histrategy-knowledge
├── tests/
└── pyproject.toml                ← depends: histrategy-engine>=0.2.0

histrategy-engine/                ← 共享层（继续在当前 repo 维护或独立 repo）
├── src/histrategy_engine/
│   ├── world/                    ← WorldState, TurnResult
│   ├── map/                      ← 地图/地形
│   ├── character/                ← 角色/忠诚度
│   ├── domestic/                 ← 经济/粮草
│   ├── military/                 ← 军事/破坏
│   ├── ai/                       ← NPC AI / 战争迷雾
│   ├── history/                  ← 历史 RAG
│   ├── rules/                    ← 规则解释器 + YAML
│   └── turn/                     ← 回合控制器
└── pyproject.toml
```

## 四、复用率提升路线

1. **Phase 1**（初期）: 直接 `pip install histrategy-engine`，复用 30%
2. **Phase 2**（开发中）: 将 histrategy 中更多通用逻辑提取到 histrategy-engine:
   - LLM adapter → 独立 `llm-adapter` 包
   - WorldState 基类 → `histrategy_engine.world.WorldStateBase`
   - Knowledge loader → `histrategy_engine.knowledge.KnowledgeBase`
3. **Phase 3**（成熟期）: 两个游戏共享 50%+ 代码，histrategy-engine 成为开源三国策略游戏引擎

## 五、最终建议

**新 repo：`shanhe-dingge`**

- histrategy-engine 已经为这个架构做好了准备（独立 pip 包）
- 30% 复用率说明大部分是新代码，不应强行塞入旧 repo
- 两个游戏 → 两个消费者 → 强化共享层的抽象质量（这是好事）
- 初期投入 ~2h 建 repo 骨架，长期收益远超成本
