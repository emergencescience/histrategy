# Histrategy v2 — 物理引擎驱动的三国策略游戏

**作者**: Prometheus (Hermes Agent)
**日期**: 2026-06-07
**状态**: 设计阶段

---

## 0. 核心问题诊断

### 当前架构的根本缺陷

```
当前: 玩家自由文本 → LLM (既当裁判又当运动员) → 修改游戏状态 → 生成叙事
                                    ↑
                            幻觉注入 + 偏向玩家
```

**三个致命问题：**

1. **LLM 幻觉污染游戏状态** — 玩家可以说"191年风调雨顺"，LLM 可能在叙事中采纳，从而改变粮食产出
2. **玩家偏向** — LLM 知道谁是玩家，天然倾向让玩家的决策"成功"，NPC 被不公平对待
3. **不可复现** — 同样输入不同输出，无法测试、无法平衡

### v2 核心思路

```
物理引擎（确定性）→ 游戏状态 → LLM 叙事层（只读）
       ↑                            ↓
  所有势力平等            根据物理结果生成故事
  不区分人类/NPC              绝不修改游戏状态
```

**参考灵感：**
- 《历史模拟器：崇祯》Steam 版的数值系统
- 桌游《三国杀》的回合制设计
- 《三国志》系列（光荣）的大地图资源系统
- Paradox 大战略游戏的事件驱动引擎

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────┐
│                      CLIENTS                              │
│    TUI (Rich)  │  Web (React)  │  OpenClaw  │  API       │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                  GAME CONTROLLER                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Intent Parser (LLM-assisted NLP)                │    │
│  │  自由文本 → 结构化命令                             │    │
│  └───────────────────┬─────────────────────────────┘    │
│                      ▼                                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Validation Layer                                │    │
│  │  拒绝不可行命令 / 过滤幻觉注入 / 数值上限检查       │    │
│  └───────────────────┬─────────────────────────────┘    │
│                      ▼                                    │
│              [PHYSICS ENGINE]                             │
│                      │                                    │
│              [GAME STATE]                                 │
│                      │                                    │
│                      ▼                                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │  LLM Narrative Layer (READ-ONLY)                 │    │
│  │  接收物理结果 → 生成叙事/对话/史书                 │    │
│  │  ✗ 禁止修改 game state                            │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 物理引擎 (Physics Engine)

物理引擎是**确定性**的、**回合制**的、**所有势力平等**的核心系统。

### 2.1 领土与资源系统

#### 2.1.1 领土属性

每个州（territory）具有以下属性：

```python
@dataclass
class Territory:
    id: str                    # e.g. "jizhou"
    name: str                  # e.g. "冀州"
    owner_id: str              # faction id
    
    # 自然属性（不变）
    fertility: int             # 1-10 粮食产量系数
    terrain: str               # plains/mountains/forest/river/coast
    climate_zone: str          # north/central/south
    horse_resource: bool       # 是否产马
    iron_resource: bool        # 是否产铁
    salt_resource: bool        # 是否产盐
    
    # 社会经济（动态）
    population: int            # 当前人口
    development: int           # 0-100 开发度
    garrison: int              # 驻军数量
    
    # 邻居
    neighbors: list[str]       # 相邻领土 ID
```

#### 2.1.2 粮食生产公式

```
base_yield = fertility × 1000 × (1 + development / 100)

season_multiplier:
  春 (Spring):  0.3   ← 播种季
  夏 (Summer):  1.0   ← 生长季
  秋 (Autumn):  1.2   ← 收获季
  冬 (Winter):  0.05  ← 休耕

climate_modifier:
  风调雨顺 (normal):        1.0
  干旱 (drought):           0.4
  洪涝 (flood):             0.6
  蝗灾 (pestilence):        0.3
  大丰 (bumper_harvest):    1.5

food_produced = base_yield × season_multiplier × climate_modifier
```

**气候事件概率（每领地每季）：**

| 事件 | 概率 | 受影响因素 |
|------|------|-----------|
| 正常 | 60% | - |
| 干旱 | 8% | 北方 +3%, 灌溉开发 -2% |
| 洪涝 | 8% | 沿河 +5%, 水利开发 -2% |
| 蝗灾 | 4% | 高温干旱区 +3% |
| 大丰 | 5% | 高开发 +2% |
| 寒灾 | 5% | 北方冬季 +10% |

**关键：气候使用种子的伪随机数，玩家无法通过输入影响。**

#### 2.1.3 人口增长公式

```
food_consumption = population × 0.5  (每人每季消耗0.5粮)
food_surplus = food - food_consumption

if food > food_consumption:
    growth_rate = 0.015 × (1 + morale/100) × (1 + development/200)
elif food > food_consumption × 0.5:
    growth_rate = 0.005 × (1 + morale/100)
else:
    growth_rate = -0.02 × (1 - food/food_consumption)  # 饥荒减员

new_population = max(100, population × (1 + growth_rate))
```

#### 2.1.4 税收与经济

```
tax_revenue = population × tax_rate × (economy/100) × 0.05
              
tax_rate 范围: 0.1 (轻徭薄赋) ~ 0.5 (横征暴敛)
税负影响: 税率 > 0.3 时每季民心 -1~3

military_upkeep = total_troops × 0.02  (每100兵耗2金)

gold_change = tax_revenue - military_upkeep - development_cost
```

### 2.2 军事系统

#### 2.2.1 兵种

| 兵种 | 招募费(金) | 人口消耗 | 攻击 | 防御 | 速度 | 地形加成 | 特殊需求 |
|------|-----------|---------|------|------|------|----------|---------|
| 步兵 | 3/兵 | 1 | 10 | 10 | 1 | 城池+5防 | 无 |
| 骑兵 | 10/兵 | 1 | 14 | 7 | 2 | 平原+5攻 | 需产马地 |
| 弓兵 | 6/兵 | 1 | 8 | 13 | 1 | 森林+3防 | 需铁 |
| 水军 | 8/兵 | 1 | 9 | 10 | 1.5 | 河流+8攻 | 需沿水 |

#### 2.2.2 招募规则

```
最大征兵数 = min(population × 0.05, available_gold / recruitment_cost)
训练时间: 新兵第一季战斗力 = 50%，第二季 = 100%
```

#### 2.2.3 补给系统

```
supply_range = 2  (从友方领地出发最大2格)
超出补给范围: 每季每格 5% 损耗
冬季: 粮食消耗 × 1.5
断粮: 每季 20% 减员 + 士气 -20
```

#### 2.2.4 战斗结算公式

```python
def resolve_combat(attacker, defender, terrain, weather, commanders):
    """决定性战斗结算 — 不再由 LLM 驱动"""
    
    # 基础战力
    atk_power = sum(unit.count × unit.attack × unit.training for unit in attacker)
    def_power = sum(unit.count × unit.defense × unit.training for unit in defender)
    
    # 地形修正
    atk_power *= terrain.attack_modifier(attacker.unit_types)
    def_power *= terrain.defense_modifier(defender.unit_types)
    
    # 将领加成 (统帅值 0-100)
    atk_power *= (1 + attacker_commander.leadership / 200)
    def_power *= (1 + defender_commander.leadership / 200)
    
    # 阵型加成
    atk_power *= formation_bonus
    def_power *= fortification_bonus
    
    # 天气影响
    if weather == "rain":     atk_power *= 0.8; def_power *= 0.9
    if weather == "snow":     atk_power *= 0.6
    
    ratio = atk_power / max(def_power, 1)
    
    # 结算
    if ratio > 2.0:    result = "decisive_victory"
    elif ratio > 1.3:  result = "victory"
    elif ratio > 0.7:  result = "draw"
    elif ratio > 0.5:  result = "defeat"
    else:              result = "decisive_defeat"
    
    return CombatResult(result, casualties_atk, casualties_def, ...)
```

### 2.3 NPC AI 决策引擎

每个 NPC 势力每回合执行决策树，**不使用 LLM**。

#### 2.3.1 个性档案

```python
PERSONALITIES = {
    "caocao": {
        "aggression": 0.8,       # 进攻倾向
        "cunning": 0.9,          # 诡计倾向（离间、假情报）
        "caution": 0.3,          # 谨慎度（低=敢冒险）
        "diplomacy": 0.5,        # 外交倾向
        "development": 0.6,      # 内政倾向
        "mercy": 0.2,            # 仁德（影响民心变化）
    },
    "liubei": {
        "aggression": 0.3,
        "cunning": 0.3,
        "caution": 0.7,
        "diplomacy": 0.8,
        "development": 0.8,
        "mercy": 0.95,           # 极高仁德 → 民心易涨
    },
    "sunjian": {
        "aggression": 0.85,
        "cunning": 0.4,
        "caution": 0.2,
        "diplomacy": 0.4,
        "development": 0.5,
        "mercy": 0.5,
    },
    "yuanshao": {
        "aggression": 0.5,
        "cunning": 0.6,
        "caution": 0.7,          # 好谋无断
        "diplomacy": 0.7,
        "development": 0.5,
        "mercy": 0.6,
    },
    "dongzhuo": {
        "aggression": 0.9,
        "cunning": 0.5,
        "caution": 0.1,          # 极低谨慎 → 残暴
        "diplomacy": 0.1,
        "development": 0.2,
        "mercy": 0.05,           # 极低仁德 → 民心跌
    },
    # ... 其他势力
}
```

#### 2.3.2 决策流程

```
每个势力每回合:

1. 威胁评估
   for each 相邻势力:
       if 对方兵力 > 我方 × 1.5:        threat_level = HIGH
       elif 对方兵力 > 我方 × 0.8:       threat_level = MEDIUM
       else:                            threat_level = LOW

2. 机会评估
   for each 相邻弱势力 (兵力 < 我方 × 0.6):
       opportunity_score += 对方领土价值 × aggression

3. 资源需求
   if 粮食 < 警戒线:  priority = FOOD
   elif 金库 < 警戒线: priority = GOLD
   elif 兵力 < 目标:  priority = TROOPS
   else:              priority = EXPAND

4. 决策（权重制）
   - 进攻弱邻:      aggression × opportunity_score × (1 - caution)
   - 发展内政:      development × (1 - opportunity_score)
   - 外交结盟:      diplomacy × (1 - aggression)
   - 征兵备战:      aggression × threat_level
   - 休整观望:      caution × (1 - threat_level)
```

### 2.4 玩家输入处理（防注入）

```
玩家自由文本输入
        │
        ▼
┌────────────────────────────────────┐
│  Intent Parser (小模型 LLM 调用)     │
│  System prompt:                    │
│  "你是一个命令解析器。从玩家文本中   │
│   提取游戏操作。只输出有效操作。     │
│   不支持的操作：修改天气、凭空造兵、 │
│   修改他人忠诚度、改动历史。"        │
│                                    │
│  输出格式: JSON                    │
│  {"actions": [                     │
│    {"type": "recruit"|"move"|      │
│            "attack"|"develop"|     │
│            "diplomacy"|"tax"|      │
│            "train"|"spy"|          │
│            "trade"|"rest",         │
│     "params": {...}}               │
│  ]}                                │
└───────────────┬────────────────────┘
                ▼
┌────────────────────────────────────┐
│  Validation Layer (纯代码, 无LLM)   │
│  - recruit: 征兵数 ≤ 人口×5%        │
│  - attack: 目标存在 + 可达          │
│  - develop: 领土属于玩家            │
│  - 任何非游戏操作 → 丢弃            │
│  - 任何注入企图 → 丢弃 + 记录        │
│  - "风调雨顺" → 匹配不到操作 → 丢弃  │
└───────────────┬────────────────────┘
                ▼
         [PHYSICS ENGINE]
```

---

## 3. 回合结构

```
═══════════════════════════════════
  第 N 回合 · 190年 春 (所有势力同时执行)
═══════════════════════════════════

Step 1. 气候掷骰      → 每个领地独立掷气候事件
Step 2. 资源结算      → 粮食/税收/人口增长
Step 3. 所有势力下达命令
        玩家: 自由文本 → Intent Parser → Validation → Commands
        NPCs: NPC AI 决策树 → Commands
Step 4. 移动结算      → 所有部队同时移动（冲突时按速度判定）
Step 5. 战斗结算      → 所有交战同时结算（确定性公式）
Step 6. 外交结算      → 同盟/宣战/纳贡/和亲
Step 7. 事件触发      → 叛乱/流民/祥瑞/天灾/领地叛乱
Step 8. 状态持久化    → save to ~/.histrategy/
Step 9. 叙事生成      → LLM 接收最终状态 → 生成故事
Step 10. 呈现给玩家   → 任何客户端
```

---

## 4. LLM 叙事层（只读）

```python
class NarrativeGenerator:
    """从物理引擎结果生成叙事 — 绝不修改游戏状态"""
    
    def generate_turn_narrative(self, turn_result: TurnResult) -> str:
        """
        turn_result 包含:
          - climate_events: 每个领地气候
          - resource_changes: 粮/金/人口变化
          - battles: 战斗结果（兵力变化、将领伤亡）
          - diplomacy: 外交事件
          - npc_decisions: NPC 做了什么（但不透露 AI 逻辑）
        """
        context = self._build_narrative_context(turn_result)
        # LLM 只生成叙事文本
        narrative = self.llm.chat(context, max_tokens=2000)
        return narrative
    
    def _build_narrative_context(self, tr: TurnResult) -> str:
        """构建叙事上下文 — 只有结果，没有内部逻辑"""
        # 示例:
        # "190年春。冀州遭遇蝗灾，粮食减产60%。
        #  刘备在平原招募了2000步兵。曹操从陈留出兵攻打徐州。
        #  曹操军与陶谦军在彭城交战。曹操军获胜，损失500人，
        #  陶谦军损失3000人，退守下邳。
        #  请用文白相间的史书风格描述这一季的天下大势。"
```

**LLM 绝不接触：**
- 天气掷骰的随机种子
- NPC 决策树的内部权重
- 战斗结算的原始公式
- 未对玩家揭示的密探情报
- 其他势力的内部资源数据（除非通过间谍获得）

---

## 5. 客户端架构

### 5.1 服务端 API（新增）

```python
# 核心 API 端点
GET  /api/game/state          # 当前游戏状态（玩家可见部分）
POST /api/game/command        # 提交玩家命令
GET  /api/game/narrative      # 本回合叙事
GET  /api/game/map            # 地图数据
GET  /api/game/history        # 历史事件日志
```

### 5.2 TUI 客户端（现有，保留）

- Rich 渲染 → 保留
- 修复：ASCII_TITLE 不重复显示
- 增加：战斗结果面板、地图小图

### 5.3 Web 客户端（新增）

- React + Canvas 地图渲染
- 十三州交互地图
- 人物卡牌 UI
- 响应式设计（桌面+平板）

### 5.4 OpenClaw 客户端（新增）

- IM 频道内文字交互
- 命令：`/plan` `/act` `/map` `/state` `/history`
- Memory 系统存储游戏上下文
- 适合碎片时间异步游玩

---

## 6. 实施路线图

### Phase 1: Physics Engine Core (预计 2 周)
```
□ 1.1 Define data models (Territory, Army, Battle, Climate)
□ 1.2 Implement resource system (food, population, gold formulas)
□ 1.3 Implement climate/season system with seeded RNG
□ 1.4 Implement military system (recruit, move, supply, combat)
□ 1.5 Implement NPC AI decision trees for all major factions
□ 1.6 Implement turn lifecycle controller
□ 1.7 Unit tests for all physics systems (≥ 80% coverage)
```

### Phase 2: Player Integration (预计 1 周)
```
□ 2.1 Intent Parser (LLM-assisted command extraction)
□ 2.2 Validation layer (reject impossible/injected commands)
□ 2.3 Command execution pipeline
□ 2.4 TUI integration with physics engine backend
□ 2.5 E2E tests for full game turns
```

### Phase 3: Narrative Refactor (预计 1 周)
```
□ 3.1 NarrativeGenerator (read-only, takes TurnResult)
□ 3.2 Context builder (only exposes visible information)
□ 3.3 Advisor court scene generation
□ 3.4 Battle narrative generation
□ 3.5 Historical chronicle writer
```

### Phase 4: Game Depth (预计 2 周)
```
□ 4.1 Diplomacy system (alliance, tribute, vassal, marriage)
□ 4.2 Character skill trees (governors improve development, generals improve combat)
□ 4.3 Technology tree (irrigation → food+, metallurgy → weapon+, etc.)
□ 4.4 Espionage system (spy on neighbors, sabotage, counter-intel)
□ 4.5 Additional scenarios (194, 200, 208 starting dates)
□ 4.6 Victory conditions (unification, hegemony, legacy)
```

### Phase 5: Clients (预计 3 周)
```
□ 5.1 REST API server (FastAPI)
□ 5.2 Web client MVP (React + map rendering)
□ 5.3 OpenClaw skill integration
□ 5.4 Save/load across clients
□ 5.5 Session persistence and replay
```

---

## 7. 测试策略

```
单元测试:
  - 资源生产公式: 给定输入 → 验证输出
  - 战斗结算: 兵力比 → 损失率
  - 气候系统: 10000次掷骰 → 统计分布
  - NPC AI: 给定状态 → 验证决策合理性
  - Validation: 非法命令 → 拒绝
  
集成测试:
  - 完整回合: climate → production → orders → combat → state
  - 多势力并行: 5个NPC + 玩家 → 无状态污染
  - 存档/读档: save → load → 数值一致
  
回归测试:
  - Intent Parser: 已知输入 → 预期命令
  - 防注入: "风调雨顺" → 不产生命令
  - LLM 不修改状态: narrative 输出 ≠ state 变化
```

---

## 8. 关键设计原则

1. **物理引擎是圣经** — 所有数值从这里产生，LLM 只能读取
2. **所有势力平等** — 玩家只是一个"恰好输入来源不同的势力"
3. **确定性优先** — 同一状态 + 同一命令 = 同一结果（便于测试和平衡）
4. **LLM 为叙事服务** — 它让故事好看，但不决定故事走向
5. **防注入是强制性的** — Parser → Validator 双保险
6. **渐进式交付** — 每个 Phase 产出可玩、可测的增量
