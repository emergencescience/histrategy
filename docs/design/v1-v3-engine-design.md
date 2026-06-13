# V1 & V3 引擎设计文档

## 概述

同时开发两套引擎用于 A/B 对比：
- **V1**: 纯 LLM 仿真引擎（deepseek-v4-pro 直接推演）
- **V3**: 混合引擎（确定性基线 + LLM 非线性调整）

两者共享同一数据库 schema (`game_state` / `turn_delta` / `policy_state`)，
前端通过 `engine_mode` 参数切换，方便对比体验。

---

## V1: 纯 LLM 仿真引擎

### 设计哲学

"LLM = Game Engine"。不做任何确定性计算，所有状态变化由 deepseek-v4-pro 推理得出。
适合快速原型、叙事质量优先的场景。

### 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                      V1 Turn Pipeline                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Q0 (开局):                                                   │
│  ┌──────────────────┐                                        │
│  │ 初始状态 (JSON)   │ ──→ game_state 表 (quarter_number=0)    │
│  │ 城池/人口/兵力/粮 │                                        │
│  │ 政策/科技树状态   │                                        │
│  └──────────────────┘                                        │
│           ↓                                                   │
│  ┌──────────────────┐                                        │
│  │ AI NPC 立即下命令 │  每个 NPC 独立 LLM 调用                │
│  │ (非结构化文本)    │  存入 faction_slot.pending_decision     │
│  └──────────────────┘                                        │
│           ↓                                                   │
│  ┌──────────────────┐                                        │
│  │ 等待人类玩家      │  前端轮询 GET /api/rooms/{id}/status    │
│  │ 提交决策          │  存入 faction_slot.pending_decision     │
│  └──────────────────┘                                        │
│           ↓                                                   │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ deepseek-v4-pro 推演仿真 (单次 LLM 调用)              │    │
│  │                                                        │    │
│  │ System Prompt:                                         │    │
│  │   "你是一个三国历史推演引擎。根据以下输入，推演本季度   │    │
│  │    的世界变化..."                                       │    │
│  │                                                        │    │
│  │ Input:                                                 │    │
│  │   - 上一轮 game_state (所有势力的完整状态)              │    │
│  │   - 所有玩家的指令 (非结构化文本)                       │    │
│  │   - 当前政策/科技树状态                                  │    │
│  │                                                        │    │
│  │ Output (JSON):                                          │    │
│  │   {                                                     │    │
│  │     "factions": {                                       │    │
│  │       "cao": {                                          │    │
│  │         "population": 520000,                           │    │
│  │         "troops": 145000,    // 兵力增减                 │    │
│  │         "food": 18500,       // 粮食增减                 │    │
│  │         "treasury": 61000,   // 库金变化                 │    │
│  │         "morale": 73,        // 民心增减                 │    │
│  │         "territories": [...] // 城池易手                 │    │
│  │       },                                                │    │
│  │       "shu": { ... },                                   │    │
│  │       "wu": { ... }                                     │    │
│  │     },                                                  │    │
│  │     "events": [                                         │    │
│  │       "曹操采纳荀彧建议，在许昌推行屯田制...",           │    │
│  │       "刘备三顾茅庐，诸葛亮出山..."                       │    │
│  │     ],                                                  │    │
│  │     "narrative": "建安十二年春..."  // 本季解说           │    │
│  │   }                                                     │    │
│  └──────────────────────────────────────────────────────┘    │
│           ↓                                                   │
│  ┌──────────────────┐                                        │
│  │ 写入 game_state   │  新一行 (quarter_number += 1)          │
│  │ 写入 turn_delta   │  每项变化记录增量行                    │
│  │ 写入 policy_state │  政策如有变化                          │
│  └──────────────────┘                                        │
│           ↓                                                   │
│  ┌──────────────────┐                                        │
│  │ 返回叙事给前端    │  包含解说文本 + 状态摘要               │
│  └──────────────────┘                                        │
│           ↓                                                   │
│  AI NPC 立即为下一轮下命令 (回到顶部)                          │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### V1 简化原则

1. **不做战争迷雾** — 所有势力信息完全公开
2. **不做分步仿真** — 一次 LLM 调用完成所有势力状态更新
3. **状态是 JSON blob** — 不固定 schema，LLM 自由输出
4. **不做 Guardrail 验证** — 信任 LLM 输出（V1 就是用来测试 LLM 靠谱程度的）
5. **不做 Battle 子系统** — 战争结果由 LLM 直接叙述
6. **max_tokens=16384** — 给够空间，V1 的单次 LLM 调用上下文最大

### V1 API 端点

```
POST /api/v1/rooms                    # 创建 V1 房间（engine_mode=v1）
POST /api/v1/rooms/{id}/start         # 开始游戏（触发 NPC 首轮决策）
POST /api/v1/rooms/{id}/decide        # 人类提交决策（同 V3 API）
GET  /api/v1/rooms/{id}/status        # 获取房间状态（同 V3 API）
```

### V1 LLM 调用规格

| 调用点 | 模型 | max_tokens | 预计延迟 |
|--------|------|-----------|---------|
| NPC 决策 (每势力) | deepseek-chat | 2048 | ~5s × N |
| 推演仿真 (单次) | deepseek-v4-pro | 16384 | ~30-60s |
| **总计** | | | ~45-80s/轮 |

---

## V3: 混合引擎（确定性基线 + LLM 调整）

### 设计哲学

"确定性引擎做该做的事，LLM 做它擅长的事"。
数值计算由 Python 保证公平性和可审计性，LLM 只做非线性调整（战役叙事、外交博弈、黑天鹅事件）。

### V3 当前状态

V3 引擎已经在 `feat/symmetric-multiplayer` 分支中实现（`_process_turn_macro`），当前架构：

```
QuarterlyEngine (确定性基线)
    ↓  计算 tax/food/pop/morale 变化
BlackSwanInjector (历史事件触发)
    ↓  检查是否符合触发条件
MacroPolicyEngine (LLM 非线性层)
    ↓  综合所有指令 + 确定性基线 + 触发事件
    ↓  生成 narrative + morale_events + territory_capture
    ↓
输出: narrative + state_changes + knowledge_cards
```

### V3 数据流（用户描述的版本）

```
a. 初始状态: 数值+非数值状态存入 game_state 表
     ↓
b. AI NPC 马上下命令: 
   - 非结构化文本（决策意图："联吴抗曹，发展荆州水军"）
   - 结构化命令（PolicyCommand: [{type: diplomacy, target: wu, action: ally}, ...]）
   - 预计 20-30s（每个 NPC 独立 LLM 调用，并行）
     ↓
c. 人类下非结构化命令 → LLM 翻译成结构化命令
   - IntentParser: "在许昌招兵买马，准备南下" 
     → [{type: conscript, params: {amount: 5000, territory: xuchang}}, ...]
     ↓
d. 全员提交 → 代码仿真:
   - QuarterlyEngine: 数值计算（tax revenue, food consumption, pop growth, morale drift）
   - PolicyEvaluator: Rule Spec 计算（屯田制→food×1.05, 盐铁专营→treasury+20%）
     ↓
e. LLM 综合所有玩家的结构化+非结构化命令 + 代码仿真结果 → 推理调整
   - 检查代码仿真是否有明显偏差（如：10万大军攻城，代码说只死了500人 → LLM 修正）
   - 生成战役叙事、外交博弈、黑天鹅事件
   - 必要时微调数值（在 guardrail 范围内）
     ↓
f. 最终状态 + 解说 → 写入 game_state 表
   - 每家势力一行: {population, troops, food, treasury, morale, territories, policies}
   - turn_delta: 每项变化的增量记录
   - policy_state: 政策生效/撤销记录
```

### V3 与当前代码的差距

| 功能 | 当前状态 | 需要做什么 |
|------|---------|-----------|
| NPC 非结构化+结构化命令 | ✅ NPCDecisionEngine 已支持 | 无需改动 |
| 人类 LLM 翻译成结构化命令 | ✅ IntentParser 已支持 | 无需改动 |
| 确定性数值基线 | ✅ QuarterlyEngine 已支持 | 无需改动 |
| Rule Spec (政策效果计算) | ❌ 未实现 | **需要新建 PolicyEvaluator** |
| LLM 综合调整 | ✅ MacroPolicyEngine 已支持 | 增强上下文（传入所有玩家的命令） |
| Guardrail 验证 | ✅ GuardrailValidator 已支持 | 增强规则（更多约束类型） |
| 状态写入 DB | ✅ game_state/turn_delta 表已建 | 实现 writeback 逻辑 |
| 战争迷雾 | ❌ 未实现 | V3 不做（用户说 "V1 暂时不做战争迷雾"，V3 也暂缓） |

---

## V1 vs V3 对比矩阵

| 维度 | V1 纯 LLM | V3 混合 |
|------|----------|---------|
| **仿真器** | deepseek-v4-pro (单次调用) | QuarterlyEngine + LLM 调整 |
| **公平性** | 低（LLM 可能偏袒某方） | 高（Python 保证公平） |
| **可审计性** | 低（黑盒） | 高（turn_delta 精确记录每次变化原因） |
| **叙事质量** | 高（V4-pro 自由发挥） | 中高（结构化+非结构化混合） |
| **延迟** | ~45-80s/轮 | ~30-50s/轮 |
| **成本** | 高（单次大上下文 LLM） | 中（确定性部分免费） |
| **NPC 行为多样性** | 高（V4-pro 自由决策） | 中（受限于命令类型枚举） |
| **蝴蝶效应** | 天然支持（LLM 记忆上下文） | 需 TurnMemory 模块辅助 |
| **生产就绪度** | 低（未验证边界情况） | 中（已有 Guardrail） |
| **适合场景** | 叙事驱动、快速原型 | 策略深度、公平竞技 |

---

## 实施计划

### Phase 1: V1 Engine (2-3 天)
1. `histrategy/engine/v1_simulator.py` — V1Simulator 类
2. V1 系统提示词 `histrategy/llm/prompts/v1_simulator.md`
3. V1 API 路由 `histrategy/server/api_v1.py`
4. V1 E2E 测试 `scripts/e2e_v1.py`

### Phase 2: V3 Engine 增强 (2-3 天)
1. `histrategy/engine/policy_evaluator.py` — Rule Spec 计算
2. 增强 `MacroPolicyEngine` — 传入所有玩家的命令（当前只传了玩家自己的）
3. V3 DB writeback — 状态写入 game_state/turn_delta
4. V3 E2E 测试增强

### Phase 3: 对比测试 (1 天)
1. 同一场景分别跑 V1 和 V3
2. 对比：延迟、成本、叙事质量、状态一致性
3. 用户决策：V1 还是 V3 上线
