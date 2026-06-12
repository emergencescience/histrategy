# Histrategy v3 — LLM-Driven Simulation with Deterministic Guardrails

> 设计文档 · 2026-06-11
> 前置阅读: `docs/architecture-philosophy.md`, `docs/design-iterations.md`

---

## 1. 为什么需要 v3

v2 的七引擎架构在**可验证性**上成功（459 tests, zero hallucination in core loop），但在**真实性**上有三个盲区：

### 盲区 1: 非线性系统表达无能

攻城、围城、劝降、哗变、宫廷政变——这些不是 `attacker_power / defender_power > 1.5` 能表达的。真实的军事冲突是士气、补给、情报、政治、天气的涌现结果，LLM 天然适合做这种多因素非线性推理。

### 盲区 2: 状态遗忘

引擎记得 `tax_rate=0.15`，但不记得「玩家已经仁政了三个季度」。没有「政策积累」的概念——每回合都是独立的公式计算，看不到历史决策的持续性影响。

### 盲区 3: 蝴蝶效应不可见

玩家输入「开仓赈济邺城百姓」，引擎算出 `food -= 20000, morale += 3`。但玩家期望的是「因为我赈济了邺城，所以后来邺城百姓自发献粮支援北伐」——这是因果叙事，不是数值计算。v2 的 LLM 只做文学润色，不做因果推理。

---

## 2. v3 核心架构

```
                        ┌─────────────────────┐
  Player Natural Lang   │   Intent Parser      │  (v2, unchanged)
        └──────────────→│   structured commands│
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
  WorldState JSON       │   Deterministic Base │  (v2, trimmed)
  + commands            │   • food production  │
                        │   • tax revenue      │
                        │   • base combat      │
                        │   • climate (RNG)    │
                        │   • natural death    │
                        └──────────┬──────────┘
                                   │ baseline TurnResult
                        ┌──────────▼──────────┐
  baseline + memory     │   LLM Simulation     │  ★ NEW
  + personalities       │   • siege resolution │
                        │   • morale cascades  │
                        │   • political events │
                        │   • butterfly effects│
                        │   • NPC reactions    │
                        └──────────┬──────────┘
                                   │ structured delta
                        ┌──────────▼──────────┐
  delta + constraints   │   Guardrail Validator│  ★ NEW
                        │   • troop ≤ actual   │
                        │   • food ≥ 0         │
                        │   • morale 0-100     │
                        │   • territory check  │
                        │   • tax 0.1-0.5      │
                        └──────────┬──────────┘
                                   │ validated delta
                        ┌──────────▼──────────┐
  validated delta       │   State Applier      │  (new module)
                        │   → writes WorldState│
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
  final state           │   Narrative Engine   │  (v2, enhanced)
                        │   generates story    │
                        └─────────────────────┘
```

**核心原则: LLM 做主模拟，Python 做护栏。不是 LLM 替代引擎，是 LLM 做引擎做不到的事。**

---

## 3. LLM Simulation Engine 设计

### 3.1 输入 (Prompt Context)

```
=== WORLD STATE (current) ===
Year: 208, Season: 夏, Turn: 3
Player: 曹操 (cao)
Territories: xuchang(许昌), wancheng(宛城), luoyang(洛阳), ye(邺城), ...
Strength: 150000, Treasury: 74437, Food: 32470, Morale: 44

Armies:
  army_cao_wancheng: location=wancheng, infantry=50000, cavalry=10000
  army_cao_xuchang: location=xuchang, infantry=30000

=== PLAYER COMMANDS (parsed) ===
- attack(xinye), notes="南征刘备: 集结6万大军进攻"
- defend(xiapi), notes="防范孙权从庐江进攻"

=== DETERMINISTIC BASELINE ===
Food production: xuchang +1200, ye +1500, ...
Tax revenue: +3200
Climate: central=normal, northern=drought
Natural death: none
Base combat: wancheng→xinye: attacker_power=8500 vs defender_power=1800
  → VICTORY predicted (baseline only, LLM may override)

=== HISTORICAL MEMORY (last 5 turns) ===
Turn 2 (208春): 「曹操下令在许昌开垦农田，提升开发度。邺城税率从40%降至30%...」
Turn 1 (207冬): 「建安十二年冬，曹操坐拥中原九郡...」

=== NPC PERSONALITIES ===
刘备: mercy=0.95, caution=0.7, aggression=0.3
孙权: aggression=0.5, caution=0.5, diplomacy=0.8
```

### 3.2 输出 (Structured Delta)

```json
{
  "battle_overrides": [
    {
      "location": "xinye",
      "baseline_result": "victory",
      "llm_result": "defender_surrendered",
      "casualties": {"attacker": 200, "defender": 0},
      "reasoning": "刘备见曹军势大，自知5000兵不敌6万，为保全百姓和将领性命，主动弃城撤退至江陵方向。关羽张飞护送百姓南撤。",
      "territory_captured": true,
      "captured_characters": [],
      "escaped_characters": ["liu_bei", "guan_yu", "zhang_fei"]
    }
  ],
  "morale_events": [
    {
      "faction": "cao",
      "territory": "ye",
      "change": +5,
      "reason": "邺城百姓感念三季仁政（税率30%→20%），自发献粮劳军",
      "persistent_note": "邺城民心基础已稳固，未来暴乱概率-30%"
    }
  ],
  "political_events": [
    {
      "type": "faction_internal",
      "faction": "wu",
      "description": "孙权帐下张昭等文官主张暂缓北伐，与周瑜等主战派发生争执。孙权倾向周瑜，但内部裂痕初现。",
      "effect": {"wu_morale": -2, "wu_diplomacy_willingness": +10}
    }
  ],
  "npc_actions": [
    {
      "faction": "shu",
      "action": "strategic_retreat",
      "from": "xinye",
      "to": "jiangling",
      "reasoning": "刘备判断新野不可守，率军民南迁"
    },
    {
      "faction": "wu",
      "action": "military_buildup",
      "location": "lujiang",
      "reasoning": "孙权察觉曹操东线威胁，加强庐江防御"
    }
  ],
  "butterfly_effects": [],
  "narrative_seeds": [
    "邺城父老言: '曹公仁政，我等当以死报之。'",
    "刘备弃新野南走，百姓扶老携幼相随，号泣而行。"
  ]
}
```

### 3.3 护栏验证规则

```python
GUARDRAILS = {
    # 硬约束: 违反直接拒绝，改用确定性引擎结果
    "hard": {
        "troop_casualties ≤ actual_troops": True,
        "food ≥ 0 after all changes": True,
        "morale in [0, 100]": True,
        "treasury ≥ 0": True,
        "territory_capture requires adjacent army": True,
        "tax_rate in [0.1, 0.5]": True,
        "no_creating_characters": True,       # 不能凭空创造武将
        "no_killing_historical_characters": True,  # 不能提前杀历史人物
    },
    # 软约束: 违反时记录 warning，但仍接受
    "soft": {
        "single_turn_morale_change ≤ 15": True,
        "single_turn_food_change ≤ 50%": True,
        "battle_casualty_ratio ≥ 0.1": True,  # 至少 10% 伤亡
        "no_faction_destroyed_in_one_turn": True,  # 不会一回合灭国
    },
    # 偏差检测: 与 baseline 的差距
    "deviation": {
        "battle_outcome_may_override": True,         # LLM 可改战斗结果
        "battle_casualties_may_differ_±50%": True,   # 伤亡可偏离 ±50%
        "food_production_may_not_override": True,     # LLM 不能改粮食产量
        "tax_revenue_may_not_override": True,         # LLM 不能改税收
    }
}
```

---

## 4. Memory System（防状态遗忘）

### 4.1 三层记忆架构

| 层级 | 存储内容 | 持久化 | 注入 LLM Context |
|------|----------|--------|------------------|
| **WorldState** | 领土、兵力、粮草、税率等数值 | ✅ JSON | ✅ 每回合 |
| **TurnMemory** | 最近 5 回合的叙事 + 决策 + 结果 | ✅ JSONL | ✅ 最近 N 回合 |
| **EpochMemory** | 长期叙事摘要（「邺城仁政三季」） | ✅ JSON | ✅ 摘要注入 |

### 4.2 TurnMemory 格式

```json
{
  "turn": 3,
  "year": 208,
  "season": "夏",
  "player_decision": "南征刘备，集结6万大军攻新野...",
  "outcome_summary": "新野不战而下。刘备率军民南撤。邺城百姓自发献粮。",
  "key_events": ["新野归曹", "刘备南迁", "邺城献粮"],
  "state_snapshot": {"morale": 44, "territories": 10, "strength": 150000},
  "persistent_effects": [
    {"type": "policy_accumulation", "id": "ye_benevolence", "turns": 3, "note": "邺城仁政三季"}
  ]
}
```

### 4.3 Persistent Effects（政策积累）

LLM 每回合可以输出 `persistent_note` 字段，这些会累积到 EpochMemory 中。例如：

```
Turn 2: "邺城税率降至30%" → persistent_note: "邺城减税第一季"
Turn 3: "邺城开仓赈济" → persistent_note: "邺城仁政两季，百姓感恩"
Turn 4: "邺城继续低税" → persistent_note: "邺城仁政三季，民心基础稳固，暴乱概率-30%"
```

这个效果不会自动触发——只有在 LLM 判断「政策积累到阈值」时才会产生质变。

---

## 5. Anti-Bias 设计

v1 发现 LLM 天然偏向玩家。v3 用四层机制对抗：

### 5.1 NPC 也是「玩家」

NPC 命令和玩家命令格式完全相同——都是 `Command(type, params, notes)`。LLM 在模拟时不对玩家和 NPC 做区分处理。

### 5.2 System Prompt 显式偏向纠正

```
你是三國志略的 World Simulator。你的职责是公正地模拟历史演进。

核心原则:
1. 你不偏袒任何势力。NPC 和玩家一视同仁。
2. 你的输出必须符合物理定律（兵力不能凭空增加，粮草不能负值）。
3. 你应该让历史走向「最合理」的方向，而不是「玩家最想看到」的方向。
4. 玩家可能失败、国家可能覆灭、英雄可能战死——这才是真实的历史。
5. 历史上的弱势方（刘备 5000 兵）不应该因为他们是「主角」就获得不合理的优势。
```

### 5.3 Baseline 锚定

确定性引擎先算一个 baseline。LLM 可以偏离 baseline，但偏离方向不受限——LLM 可以让 NPC 获得比 baseline 更好的结果。

### 5.4 第三方审计日志

每回合 LLM 的输出和最终状态变化都写入日志。如果某个 AI 代理审查日志时发现「曹操（玩家）的胜率显著高于孙权（NPC）」，可以回溯分析是 baseline 偏差还是 LLM 偏差。

---

## 6. Fallback Strategy

如果 LLM 输出违反硬约束，或者 LLM API 不可用：

```
LLM 输出 → Guardrail Validator
  ├── 通过 → 写入 WorldState
  ├── 软约束违反 → 写入 + warning 日志
  └── 硬约束违反 → 丢弃 LLM 输出，使用 Deterministic Baseline
```

**关键设计**: 确定性引擎永远是 fallback。v3 是 v2 + LLM 增强层，不是 v2 的替代。

---

## 7. 与 v2 的对比

| 维度 | v2 | v3 |
|------|-----|-----|
| 攻城 | 兰彻斯特方程，永远一个模式 | LLM 推演围城/强攻/劝降/弃城 |
| 民心 | 税率公式 + 固定衰减 | LLM 理解政策积累 + 涌现效应 |
| NPC | 权重决策树 | LLM 根据全局态势推理 |
| 蝴蝶效应 | 手工编程事件链 | LLM 生成因果链 |
| 可验证性 | ✅ 全部可测 | ⚠️ 护栏可测，LLM 输出不可测 |
| 成本 | ~$0.02/turn | ~$0.06/turn (estimate) |
| 状态遗忘 | ❌ 存在 | ✅ Persistent Effects |
| 玩家偏向 | ✅ 无 (确定性) | ⚠️ 需要 Anti-Bias 对抗 |

---

## 8. 开发计划

### Phase A: v3 核心（1 周）

| Task | Est. | Description |
|------|------|-------------|
| A.1 | 3h | `WorldSimulator` LLM prompt + structured output schema |
| A.2 | 2h | `GuardrailValidator` — 硬约束 + 软约束 + deviation 检测 |
| A.3 | 2h | `StateApplier` — 安全写入 WorldState |
| A.4 | 2h | `TurnMemory` + `PersistentEffects` 持久化 |
| A.5 | 3h | `_process_turn_v3()` 管线集成到 GameEngine |
| A.6 | 4h | 单元测试 (GuardrailValidator + StateApplier + Memory) |

### Phase B: 质量保障（3 天）

| Task | Est. | Description |
|------|------|-------------|
| B.1 | 3h | Anti-bias 回归测试 — 跑 20 回合，统计玩家 vs NPC 胜率 |
| B.2 | 2h | LLM 输出质量评估 — 人工审查 10 回合的 simulation 输出 |
| B.3 | 2h | Fallback 测试 — 强制 LLM 不可用/返回非法值 |

### Phase C: 部署（1 天）

| Task | Est. | Description |
|------|------|-------------|
| C.1 | 1h | LLM_PROVIDER_V3 环境变量（允许 v3 使用不同的 LLM） |
| C.2 | 1h | Feature flag: `GameEngine(version="v3")` vs `version="v2"` |
| C.3 | 1h | 灰度发布 — 新游戏用 v3，已有游戏保持 v2 |

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM 幻觉破坏游戏状态 | 中 | 高 | 硬约束护栏 + deterministic fallback |
| LLM 偏向玩家 | 高 | 中 | Anti-bias prompt + NPC 同等待遇 + 审计日志 |
| LLM 叙事前后矛盾 | 中 | 中 | TurnMemory + PersistentEffects 提供跨回合一致性 |
| 成本过高 | 中 | 中 | 用小模型 (deepseek-v4-flash) 做 simulation，大模型仅做 narrative |
| API 延迟影响体验 | 低 | 低 | 异步处理 + loading state "天下正在推演..." |
| v2 用户不满改变 | 低 | 低 | Feature flag，v2 和 v3 共存 |

---

## 10. 开放问题

1. **LLM 应该看到完整的 WorldState 还是精简版？** 完整版约 3000 tokens，可能太长。精简版可能遗漏关键信息。建议从精简版（800 tokens）开始，逐步扩展。

2. **NPC LLM 调用是否并行？** 每个 NPC 独立调用 LLM 可以并行，但成本高（3 个 NPC × 每回合）。建议一个 LLM 调用处理所有 NPC。

3. **记忆窗口多长？** 建议最近 5 回合全量 + 长期摘要。5 回合覆盖一个游戏年（春→冬），足够 LLM 感知趋势。

4. **Architecture 变更历史怎么处理？** `docs/design-iterations.md` 记录设计演化。v3 设计文档归档到此序列。
