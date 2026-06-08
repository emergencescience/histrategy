# SimPly v2: 可拔插规则引擎 × LLM 柔性推理

**日期**: 2026-06-08
**版本**: v2 Draft
**作者**: Prometheus
**前身**: SimPly v1 (hybrid-engine-framework.md)

---

## 零、反思：v1 的问题

v1 框架定义了「引擎算对错，LLM管好看」的双层架构。但有个致命缺陷：

```
每次新规则 → 改 Python 代码 → 跑测试 → 部署
```

政权合法性？改 `FactionState`。粮食系统？改 `DomesticEngine`。分封？改 `state_bridge`。

**这是永无止境的。** 每加一个历史机制，就要改一次引擎源码。崇祯模拟器有 12 个系统模块，我们要做多少个？

更根本的问题：**规则不应该是代码。规则应该是数据。**

---

## 一、核心洞察

### 1.1 崇祯模拟器的真正教训

不是「AI 与数值脱节」——这只是表象。真正的教训是：

> **青干工作室把「游戏规则」和「代码」绑死了。**
> 加一个新系统 = 重写一大块代码 = 引入新 bug = 3 轮内测没修完。

但如果我们把规则从代码中分离出来呢？

### 1.2 我们的机遇

DeepSeek 降价了。但关键不是「用 LLM 替代引擎」——崇祯模拟器已经证明那行不通。

关键是：**用 LLM 来帮助「定义规则」和「解释结果」，而不是「执行规则」。**

```
旧模式（v1）:
  开发者写 Python → 引擎执行 → 输出结果

新模式（v2）:
  开发者写 YAML 规则 ──→ 引擎解释规则 ──→ 输出结果
  玩家写自然语言 ──→ LLM 转规则建议 ──→ 开发者审核 ──→ 纳入规则库
  LLM 读规则结果 ──→ 生成叙事
```

---

## 二、SimPly v2 架构

```
┌─────────────────────────────────────────────────────┐
│                  SimPly v2                          │
│                                                     │
│  ┌─────────────┐   ┌──────────────┐                │
│  │ Rule Store   │   │ Spec Store   │                │
│  │ (YAML/JSON)  │   │ (YAML)       │                │
│  │ ┌─────────┐  │   │ ┌──────────┐ │                │
│  │ │battle   │  │   │ │battle    │ │                │
│  │ │economy  │  │   │ │economy   │ │                │
│  │ │legitimacy│  │   │ │diplomacy │ │                │
│  │ │famine   │  │   │ │...       │ │                │
│  │ │...      │  │   │ └──────────┘ │                │
│  │ └─────────┘  │   └──────────────┘                │
│  └──────┬───────┘         │                         │
│         │                 │                         │
│         ▼                 ▼                         │
│  ┌──────────────┐  ┌──────────────┐                │
│  │ Rule Engine   │  │ Spec Validator│               │
│  │ (解释器)      │  │ (Spec→Test)  │               │
│  └──────┬───────┘  └──────────────┘                │
│         │                                           │
│         ▼                                           │
│  ┌──────────────────────────────────┐              │
│  │     Simulation Runtime           │              │
│  │  · Map/Pathfinding     (hard)    │              │
│  │  · State Management    (hard)    │              │
│  │  · Rule Interpreter    (soft)    │              │
│  │  · NPC Decision Engine (soft)    │              │
│  └──────────────┬───────────────────┘              │
│                 │                                   │
│         ┌───────┴────────┐                          │
│         ▼                ▼                          │
│  ┌──────────┐    ┌──────────────┐                  │
│  │ LLM Intent│    │ LLM Narrative│                  │
│  │ Parser   │    │ Generator    │                  │
│  └──────────┘    └──────────────┘                  │
│                                                     │
└─────────────────────────────────────────────────────┘
         │                               │
         ▼                               ▼
   玩家输入(自然语言)              玩家输出(叙事+数据)
```

### 2.1 关键变化：Hard vs Soft 的分界线

| 层 | 类型 | 含义 |
|---|---|---|
| **Hard Engine** | 不可配置 | 寻路(A*)、状态管理、战斗结算框架、回合循环 — 这些是数学/物理，换了朝代也不变 |
| **Soft Rules** | YAML 可配置 | 战斗公式参数、税收公式、合法性效果、饥荒阈值 — 这些随朝代/设计而变 |
| **LLM Bridge** | 柔性 | 意图理解、叙事生成、规则建议 — LLM 不执行规则，只理解和表达 |

### 2.2 规则即数据

**旧方式** (v1 — 硬编码):

```python
# histrategy-engine/domestic/__init__.py
def calculate_tax_revenue(self, territory, tax_rate):
    return territory.population * tax_rate * 0.05
```

**新方式** (v2 — 可配置):

```yaml
# rules/tax.yaml
tax:
  formula: "population * tax_rate * base_multiplier"
  base_multiplier: 0.05
  morale_impact:
    rate_0_10: +2      # 税率 0-10%: 民心 +2/季
    rate_10_20: +1
    rate_20_30: 0
    rate_30_40: -1
    rate_40_plus: -3
  legitimacy_impact:
    high_rate_penalty: -1  # 税率>40%时合法性每季-1
```

规则引擎读取 YAML，动态构建计算管线。加新规则 = 加一个 YAML 文件。不改 Python。

### 2.3 LLM 的角色（新定义）

```
LLM 不应该:
  ❌ 执行战斗（崇祯的教训）
  ❌ 决定税收金额
  ❌ 判定 NPC 行为

LLM 应该:
  ✅ 理解「围魏救赵」→ 转成引擎命令
  ✅ 把引擎结果「attacker_wins, casualties=1200」→ 写成「曹孟德亲率虎豹骑…」
  ✅ 帮开发者写规则：「我想让水战对东吴有利」→ LLM 生成 YAML 规则草案
  ✅ 解释规则结果：「为什么你输了？」→ LLM 读 battle log → 生成分析
```

---

## 三、Spec-Driven 测试

### 3.1 概念

```
Spec 文档 = 行为定义 = 自动生成测试
```

每个 spec 文件定义一个系统模块的期望行为。CI 自动从 spec 生成测试用例并验证。

### 3.2 示例

```yaml
# specs/battle.spec.yaml
spec: "Battle Resolution — Lanchester Square Law"
version: 2.0

scenarios:
  - id: "equal_forces_plains"
    description: "同等兵力在平原，守方有利"
    given:
      attacker: {troops: 10000, morale: 80, training: 0.9, unit_type: infantry}
      defender: {troops: 10000, morale: 80, training: 0.9, unit_type: infantry}
      terrain: plains
      weather: clear
    then:
      attacker_casualties: "> defender_casualties"  # 攻方损失更大
      battle_duration: "< 5 rounds"
      
  - id: "naval_battle_wu_advantage"
    description: "东吴水军在水域有优势"
    given:
      attacker: {troops: 8000, faction: wu, unit_type: navy}
      defender: {troops: 8000, faction: cao, unit_type: infantry}
      terrain: river
    then:
      attacker_wins: true
      attacker_casualties: "< 2000"
```

### 3.3 三层测试金字塔

```
        ┌──────────┐
        │ Spec Tests│  ← 新层：从 spec 文档自动生成
        │(行为验证) │     验证「产品承诺的行为是否成立」
        ├──────────┤
        │ E2E Tests │  ← 已有：完整游戏流程
        │(集成验证) │
        ├──────────┤
        │Unit Tests │  ← 已有：351 tests
        │(函数验证) │
        └──────────┘
```

---

## 四、社区可拔插架构

### 4.1 规则市场

```
simply-rules/          ← GitHub 仓库（社区贡献）
  ├── three-kingdoms/  ← 官方规则集
  │   ├── battle.yaml
  │   ├── economy.yaml
  │   └── diplomacy.yaml
  ├── warring-states/  ← 社区贡献：战国规则
  ├── roman-empire/    ← 社区贡献：罗马规则
  └── ming-dynasty/    ← 社区贡献：明末规则（崇祯模拟器 v2）
```

每个规则集 = 一组 YAML 文件。引擎不变，换规则 = 换游戏。

### 4.2 分叉不合并

用户要改规则？
- Fork `simply-rules/three-kingdoms/`
- 改 `battle.yaml` — 让骑兵更强
- 改 `economy.yaml` — 让屯田效果翻倍
- 不必提 PR 回主分支
- 在自己的 Agent/Web 端加载自己的规则集
- 觉得好 → 在市场上发布

### 4.3 LLM 辅助规则创作

```
用户（自然语言）:
  「我希望水战中东吴有 50% 的额外优势，
    因为他们的水军训练有素」

LLM（转规则）:
  → 生成 YAML:
    naval_bonus:
      faction: wu
      terrain: [river, lake, ocean]
      multiplier: 1.5
      description: "东吴水军训练有素，在水域作战有50%加成"

用户审核 → 加入规则集 → 引擎加载 → 立即生效
```

**不改一行 Python。**

---

## 五、Phase 1: 从 v1 到 v2 的迁移路径

### 5.1 当前 v1 可合并到 main 的代码

| 组件 | 状态 | 建议 |
|------|------|------|
| `histrategy-engine/` (7 engines) | ✅ 稳定 239 tests | ✅ 合并 |
| `histrategy-agent/` (核心) | ✅ 稳定 112 tests | ✅ 合并 |
| NPC AI (DecisionEngine集成) | ✅ E2E 验证 | ✅ 合并 |
| 自动征税 | ✅ | ✅ 合并 |
| LLM intent 解析 | ⚠️ 复杂指令有失败率 | ⚠️ 合并但标记 experimental |
| Web 客户端 (P5) | ⚠️ 仍用纯 LLM 路径 | ❌ 暂不合并 |
| REST API (P5) | ⚠️ | ❌ 暂不合并 |
| OpenClaw/Hermes skills | ✅ | ✅ 合并 |

**建议**: 将引擎 + agent 核心 + NPC AI 合并到 main，打 tag `v0.2.0-engine-stable`。

### 5.2 v2 迁移步骤

```
Step 1: Rule Extractor (1-2天)
  从现有 engine 代码中提取硬编码规则 → YAML
  战斗公式、税收公式、开发成本、士气系统
  → 不改引擎逻辑，只是把参数外部化

Step 2: Rule Engine (3-5天)
  构建 YAML → Python 的规则解释器
  支持 formula 字段（安全 eval）
  支持 condition 字段（when/then 规则）

Step 3: Spec Validator (2-3天)
  从 spec YAML 自动生成 pytest 用例
  CI 集成

Step 4: LLM Rule Assistant (2-3天)
  自然语言 → YAML 规则生成
  规则冲突检测

Step 5: Rule Marketplace (3-5天)
  GitHub 模板仓库
  一键加载远程规则集
```

---

## 六、预期收益

### 6.1 开发速度

| | v1 (硬编码) | v2 (可配置) |
|---|---|---|
| 加一个新规则 | 改 Python + 测试 ≈ 2-4h | 写 YAML ≈ 15min |
| 换一个朝代 | 重写大量引擎代码 ≈ 数周 | 换规则集 ≈ 1天 |
| 社区贡献 | PR 合并冲突 | Fork 规则集，零冲突 |
| 规则迭代 | 部署新版本 | 热加载 YAML |

### 6.2 传播

| 渠道 | v1 | v2 |
|------|-----|-----|
| 开发者 | 「Star 我们的项目」 | 「用你的规则集玩三国」 |
| 历史爱好者 | 不能改规则 | 「你的明末规则集被 500 人下载」 |
| 学术 | 黑盒系统 | 「修改 YAML 参数 → 对比实验结果」 |

### 6.3 与崇祯模拟器的终极差异

| | 崇祯模拟器 | SimPly v2 |
|---|---|---|
| 规则定义 | Python 硬编码 | YAML 可配置 |
| 规则修改 | 只有开发者能改 | **任何人**都能改 |
| AI 角色 | AI 是游戏（失败） | AI 是**规则助手 + 叙事者** |
| 社区 | 无 | **规则市场** |
| 本质 | 一个游戏 | **一个游戏框架** |

---

## 七、决策待定

1. 是否立即将 engine + agent 核心合并到 main？→ 建议是
2. 是否启动 v2 Rule Extractor？→ 建议是，作为 Phase 1
3. 规则引擎用什么表达式语言？→ 建议 Python safe eval（受限命名空间）+ YAML
4. 规则市场用什么平台？→ 建议 GitHub 仓库 + 简单索引

---

## 八、一个具体的例子

**现在（v1）**: 要加「合法性系统」

```python
# 1. 改 FactionState 加 legitimacy 字段
# 2. 改 DomesticEngine 加 legitimacy_impact()
# 3. 改 state_bridge 加合法性命令处理
# 4. 改 turn_processor 加合法性每回合更新
# 5. 写测试
# 估计: 4-6 小时
```

**未来（v2）**: 要加「合法性系统」

```yaml
# rules/legitimacy.yaml
legitimacy:
  initial: 50
  effects:
    control_luoyang: +20
    hold_emperor: +40
    high_tax_penalty: -1_per_season
    famine_penalty: -15
  thresholds:
    high: {min: 80, diplomacy_bonus: 0.3, recruitment_bonus: 2.0}
    medium: {min: 60, diplomacy_bonus: 0.15, tax_efficiency: 0.1}
    low: {min: 30, rebellion_risk: 0.15}
    critical: {min: 0, defection_risk: 0.05}
```

```yaml
# specs/legitimacy.spec.yaml
scenarios:
  - id: "capture_luoyang_boosts_legitimacy"
    given: {faction: liubiao, legitimacy: 50}
    when: {event: capture_territory, territory: luoyang}
    then: {legitimacy: 70}
```

**引擎代码一行不改。** 写两个 YAML 文件，15 分钟。Spec 自动生成测试。

---

## 九、结论

v1 解决了「引擎 vs LLM 谁算结果」的问题。
v2 要解决「规则归谁管」的问题。

**规则不属于引擎代码。规则属于玩家和社区。**

这不是技术决策，是**生态决策**。崇祯模拟器是一个人的游戏。SimPly v2 是一千个人的框架。
