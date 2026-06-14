# H15g: Game State 核心 vs 可扩展状态参数边界

> **决策文档**: 硬编码 (Python dataclass) vs YAML rules 的职责划分
>
> **前置**: [H15e 人口异常调查] · [H15f 等效兵力+人口分层方案]
>
> **日期**: 2026-06-14
>
> **状态**: ✅ 已决策

---

## 1. 问题陈述

当前游戏状态在两个维度上分裂：

| 维度 | 当前承载 | 问题 |
|------|----------|------|
| **Python dataclass** (`FactionState`) | 17+ 字段：`strength_actual`, `economy_actual`, `morale_actual`, `treasury`, `food`, `tax_rate`, `prestige`, `legitimacy`, `tech_levels`, 6 个性特质 + territory 列表 | 新增字段=改代码+改DB+改LLM prompt，成本高 |
| **DB `game_state` 表** | 5 列：`population`, `troops`, `food`, `treasury`, `morale` | 与 dataclass 不对称，V1/V3 写入路径不同 |
| **LLM prompt** (`v1_simulator.md`) | 也是这5个字段 + policies | LLM 输出的 schema 硬编码在 prompt 里 |
| **YAML rules** (`economy.yaml`) | food_production, population_growth, tax, unrest, etc. | 公式依赖 `fertility`, `development`, `morale`, `tax_rate` 等变量，但变量来源不统一 |

**核心矛盾**: 5 个字段够不够？要不要扩展？怎么扩展？

---

## 2. 历史洞察

### H15e: 孙权人口 "十八万三千" 异常

- **现象**: V1 LLM 输出孙权 `population: 183000`，而史实 207 年江东应有 ~200 万
- **根因**: LLM 看到的是 `strength_actual=60000`（兵力），没有独立的人口字段 → flash 模型把 "兵力" 和 "人口" 混淆
- **修复**: H15e 在 FactionState 添加了 `population` 字段，由 territories 求和计算

### H15f: "等效兵力" 方案

- **结论**: 不追求人口/粮草/金钱的史实精确值，改用 "等效抽象单位"
- 兵力 = 等效兵力（已标准化，方便横向比较）
- 人口 = 核心指标的 "分母"（用于计算税收/征兵/粮食消耗）
- 数值有游戏意义（谁比谁强），无史实比照义务

---

## 3. 三层架构设计

```
┌─────────────────────────────────────────────────┐
│                  LLM Prompt Layer                │
│  v1_simulator.md: 5 核心字段 + policies +        │
│  territories[population, development]            │
├─────────────────────────────────────────────────┤
│               Python Core State                  │
│  FactionState: 5 核心字段 + 扩展字段 + metadata  │
│  DB: game_state (5列) + turn_delta + policy_state│
├─────────────────────────────────────────────────┤
│               YAML Rules Engine                  │
│  economy.yaml: 生产/消耗/增长公式                 │
│  historical_events.yaml: 事件前置/概率            │
│  future: military.yaml, diplomacy.yaml, ...      │
└─────────────────────────────────────────────────┘
```

### 3.1 核心层 (Hardcoded in Python)

**这 5 个字段是「不可去核」的最小状态**，原因：

| 字段 | 必须硬编码的理由 |
|------|------------------|
| `population` | 所有经济公式的分母（税收=人口×税率，粮食消耗=人口×per_capita，征兵=人口×rate） |
| `troops` | 所有军事公式的输入（战斗力=兵力×训练度×士气，战斗伤亡需要精确数值） |
| `food` | 资源消耗类状态，每回合必须 ≥0，低于阈值触发饥荒/民变 |
| `treasury` | 资源类状态，征兵/建设/外交花费需要精确扣除 |
| `morale` | 战斗倍率、税率上限、民变风险的基础乘数 |

**硬编码的好处**:
- **性能**: V3 引擎每回合读 DB 一次，5 列 JOIN 完直接计算
- **LLM 可理解**: 5 个字段 LLM 不会混淆，prompt 简短可靠
- **DB 迁移安全**: 列数固定 = schema 稳定 = 跨版本兼容
- **序列化简单**: `to_dict()` / `from_dict()` 无歧义

### 3.2 扩展层 (YAML rules)

以下字段**不应该**在 dataclass 中硬编码，而应在 YAML rules 中定义并通过公式求值：

| 概念 | YAML 定义位置 | 核心层输入 | 说明 |
|------|--------------|-----------|------|
| 粮食产量 | `economy.yaml → food_production.formula` | population, fertility, development, season_mod, climate_mod, tech_mod | 公式已存在 |
| 税收收入 | `economy.yaml → tax.revenue_formula` | population × tax_rate × gov_mod | 公式已存在 |
| 人口增长 | `economy.yaml → population_growth.formula` | population, food_ratio, morale, development | 公式已存在 |
| 征兵上限 | `military.yaml → recruit_cap` (future) | population × conscription_rate | 需新建 |
| 民心变化 | `economy.yaml → unrest.formula` | tax_rate, food_ratio | 公式已存在 |
| 城市发展成本 | `economy.yaml → development.cost_formula` | delta × sqrt(population/1000) | 公式已存在 |
| 历史事件概率 | `historical_events.yaml` | faction strength ratios, relations, ownership | 公式已存在 |
| 外交好感变化 | `diplomacy.yaml` (future) | relations, gift_value, shared_enemies | 需新建 |
| 战斗伤亡 | `military.yaml → battle_casualties` (future) | attacker_troops, defender_troops, terrain, morale | 需新建 |

### 3.3 元数据层 (Python dataclass, 不参与核心计算)

这些字段存在 FactionState 中，但不是核心状态：

| 字段 | 理由保持在 Python |
|------|-------------------|
| `territories: list[str]` | 城池归属，直接决定核心层 `population`（求和），必须硬编码 |
| `tax_rate: float` | 政策参数，影响税收和民心，YAML 公式的输入，dataclass 存储 |
| `tech_levels: dict` | 科技树，影响 yaml 公式中的 `tech_mod`，dataclass 存储 |
| `policies: dict` | 政策状态，V1/V3 都会读写，DB `policy_state` 表 |
| `prestige, legitimacy` | 外交/继承的长期因子，频率低，dataclass 存储即可 |
| 6 个性特质 | NPC AI 决策权重，不参与 YAML 公式 |
| `relations: dict` | 好感度矩阵，影响外交，频率高但结构简单 |

---

## 4. 边界规则

### 4.1 什么是「核心」— 必须硬编码

> **规则**: 如果该字段**同时满足以下条件**，必须在 Python dataclass + DB 中硬编码：
>
> 1. **每回合变化** — 不是静态配置
> 2. **被 YAML 公式引用** — 作为公式的输入变量
> 3. **LLM 需要感知** — 出现在 v1_simulator.md 的 prompt 中
> 4. **需要持久化** — 跨回合保留，可回放

→ 当前核心集：**population, troops, food, treasury, morale** (5 个)

### 4.2 什么是「可扩展」— 应放在 YAML

> **规则**: 如果该字段**只需在计算时存在**（中间变量）或**纯公式驱动**，应放在 YAML rules：
>
> 1. **派生值** — 从核心字段 + 参数计算得出（如：税收收入 = population × tax_rate × 0.05）
> 2. **临时值** — 只在特定回合/事件时计算（如：攻城伤亡 = 公式(attacker_troops, wall_level)）
> 3. **场景定制** — 不同时代/剧本需要不同公式（如：工业时代税收公式不同于三国农业税）

### 4.3 扩展流程

当需要添加新状态维度时，按此流程图判断：

```
新状态维度
    │
    ├─ 每回合变化？──── 否 ──→ 放入 metadata 层 (dataclass 就够了)
    │
    ├─ 被 YAML 公式引用？── 否 ──→ 放入 metadata 层
    │
    ├─ LLM 需要感知？──── 否 ──→ YAML rules 派生计算即可
    │
    ├─ 需要 DB 持久化？── 否 ──→ YAML rules 派生计算即可
    │
    └─ 全部 YES ──→ 核心层：Python + DB + LLM prompt 三方同步
```

**扩展代价估算**:

| 操作 | 成本 |
|------|------|
| 核心层新增 1 个字段 | 改动 6 处（dataclass + DB migration + prompt + v1_apply + v1_save + context_builder） |
| YAML 新增 1 个公式 | 改动 1 处（YAML 文件）+ 在 evaluator 传入对应变量 |
| metadata 新增 1 个字段 | 改动 1 处（dataclass） |

---

## 5. 具体决策

### 决策 1: 维持 5 核心字段不变

**结论**: 不增加核心字段。`population, troops, food, treasury, morale` 足以支撑 III 世纪三国模拟。扩展需求走 YAML rules。

**理由**:
1. LLM 输出质量与 schema 复杂度成反比（5 字段 → 95% JSON 解析成功；10 字段 → 预计 ~80%）
2. `policy_state` 表已覆盖 "政策效果" 的持久化，不需要新增核心字段
3. 需要更细粒度的资源（如铁、马、战船）时，走 YAML formula + JSON `resources` 字段，不污染核心列
4. Koei《三国志》系列也用 4-6 个核心数值（兵/粮/金/人口/士气/统治），已验证

### 决策 2: YAML rules 作为唯一公式来源

**结论**: 所有数值计算公式**只**存在于 YAML rules。Python 代码不嵌入任何 `treasury += population * 0.05` 这类硬编码。

**当前违规项**（待修复，另开 task）:
- `v1_simulator.md` 第 95-96 行: "每季度自然损耗 3-5%" → 应引用 `economy.yaml`
- `v1_simulator.md` 第 97-98 行: "高税率 >30% 每季度 -3~-5 民心" → 应引用 `economy.yaml`
- `v1_simulator.md` 第 104-105 行: "单季度最大兵力变化不超过 ±30%" → 应引用 guardrail rules

### 决策 3: LLM prompt 与 YAML rules 同步

**结论**: V1 prompt 中的公式和约束从 YAML rules **自动注入**，不重复手写。

**实现**:
```python
# v1_simulator.py 中 build_context() 追加:
rules = RuleInterpreter()
context += f"""
## 数值规则（来自规则引擎）
- 粮食生产: {rules.get('food_production.formula')}
- 税收收入: {rules.get('tax.revenue_formula')}
- 民心变化: {rules.get('unrest.formula')}
- 边界约束: {rules.get('guardrails')}
"""
```

**注意**: 这是后续改进项（H15g 只做决策不做实现），避免 V1 prompt 和 V3 公式分歧。

### 决策 4: FactionState 字段整理

**结论**: FactionState 当前 20+ 字段，分三类标注：

```python
@dataclass
class FactionState:
    # ── 核心层 (5 fields) ──
    population: int = 0          # 总人口（territories 求和）
    strength_actual: int = 5000  # 兵力（等效抽象单位）
    food: int = 3000             # 粮草（等效抽象单位）
    treasury: int = 5000         # 库金（等效抽象单位）
    morale_actual: int = 50      # 民心/士气 (0-100)

    # ── 关联层 (dataclass 存储，YAML 输入) ──
    territories: list[str]       # 城池列表
    tax_rate: float = 0.3        # 税率 (0.0-1.0)
    tech_levels: dict            # 科技等级 {agriculture: 1, ...}
    policies: dict               # 政策状态

    # ── 元数据层 (dataclass 存储，低频) ──
    id: str
    name: str
    ruler_id: str
    capital: str
    is_active: bool = True
    prestige: int = 50
    legitimacy: int = 50
    relations: dict[str, int]
    allies: list[str]
    enemies: list[str]
    # fog-of-war estimates
    strength_estimated: int = 0
    economy_estimated: int = 50
    morale_estimated: int = 50
    # personality
    aggression: float = 0.5
    cunning: float = 0.5
    caution: float = 0.5
    diplomacy: float = 0.5
    development_focus: float = 0.5
    mercy: float = 0.5
```

---

## 6. 与其他任务的关联

| 任务 | 依赖 H15g 决策 |
|------|---------------|
| **H15h**: manual.html 加 "折算数值说明" | 用决策 1 的 "等效抽象单位" 概念 |
| **H15i**: 共享页面展示 turn_delta + policy_state | 展示哪 5 个核心值 + policies |
| **H15k**: 调研 Koei 数值体系 | 验证 5 字段是否与业界对齐 |

---

## 7. 参考

- [H15e] 孙权人口异常调查 — population 字段添加原因
- [H15f] 等效兵力 + 人口分层方案 — 数值抽象化理论
- [design-iterations.md] v0.1 → v0.3 架构演化记录
- Koei《三国志》系列: 兵力/粮草/金钱/人口/统治 五维体系
- Paradox《Crusader Kings 3》: 金/声望/虔诚 + 可 mod 扩展属性
