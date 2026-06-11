# 三國志略 v2 — 完整技术设计

> **Multi-Engine Architecture · Modular Repositories · Community Knowledge Base**

**作者**: Prometheus (Hermes Agent)
**日期**: 2026-06-07
**版本**: v2.0 — 技术设计审查稿

---

## 目录

1. [设计参考：光荣三国志系列引擎分析](#1-设计参考光荣三国志系列引擎分析)
2. [七引擎架构](#2-七引擎架构)
3. [引擎间通信协议](#3-引擎间通信协议)
4. [仓库拆分方案](#4-仓库拆分方案)
5. [历史知识库设计与获取策略](#5-历史知识库设计与获取策略)
6. [RAG 系统设计](#6-rag-系统设计)
7. [社区贡献模型](#7-社区贡献模型)
8. [LLM 叙事层的定位](#8-llm-叙事层的定位)
9. [实施路线图](#9-实施路线图)
10. [附录：数据源参考](#10-附录数据源参考)

---

## 1. 设计参考：光荣三国志系列引擎分析

光荣（Koei）的《三国志》系列历经 30 年、14 代迭代，其底层引擎架构是一套高度解耦的多层系统。我们不是要复制它，而是理解其设计模式后做面向 LLM 时代的重新设计。

### 1.1 光荣引擎模型

```
┌─────────────────────────────────────────────────────────┐
│                    MAP ENGINE                            │
│  六角格/方格地图 · 地形影响 · 移动消耗 · ZOC            │
│  关隘/港口 · 攻城 · 视野/谍报范围                       │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
    ┌──────▼──────┐        ┌──────▼──────┐
    │ CHARACTER   │        │  DOMESTIC   │
    │ ENGINE      │        │  ENGINE     │
    │             │        │             │
    │ 武将五维     │◄──────►│ 城市开发     │
    │ 忠诚/关系    │ 太守   │ 农业/商业    │
    │ 技能/特技    │ 任命   │ 征兵/税收    │
    │ 寿命/伤病    │        │ 技术研发    │
    └──────┬──────┘        └──────┬──────┘
           │                      │
    ┌──────▼──────────────────────▼──────┐
    │          MILITARY ENGINE           │
    │  兵种相克 · 战法 · 阵型 · 士气     │
    │  单挑 · 计略 · 攻城 · 水战        │
    └──────────┬─────────────────────────┘
               │
    ┌──────────▼──────────┐
    │   DECISION ENGINE   │
    │   NPC 战略 AI       │
    │   势力目标评估       │
    │   进攻/防守/外交决策 │
    └──────────┬──────────┘
               │
    ┌──────────▼──────────┐
    │   HISTORY ENGINE    │
    │   事件条件触发       │
    │   历史推进/偏离      │
    │   if-then 逻辑       │
    └─────────────────────┘
```

**关键洞察**：

1. **Map Engine 是最底层的** — 一切战略行为都经由地图。地形决定移动，移动决定交战，交战决定胜负。
2. **Character Engine 与 Domestic Engine 双向耦合** — 太守的政治值影响城市产出，城市的富裕程度影响武将忠诚。
3. **Military Engine 是 Character + Map 的消费者** — 战斗结算 = 将领能力(Character) × 地形(Map) × 兵种
4. **History Engine 是"导演"** — 它不直接修改状态，而是创建"事件提案"让其他引擎执行
5. **Decision Engine 给 NPC 赋予意图** — 让 NPC 表现得像有战略思维的对手

### 1.2 我们的重新设计

```
光荣模式                    三國志略 v2
─────────────────────────────────────────────
Map Engine        →    Map Engine (保留核心逻辑)
Character Engine  →    Character Engine (扩展关系网+技能树)
Domestic Engine   →    Domestic Engine (资源/人口/税收/开发)
Military Engine   →    Military Engine (兵种/补给/战斗)
Decision Engine   →    Decision Engine (NPC AI 个性权重)
History Engine    →    History Engine (事件触发+蝴蝶效应+RAG)
(N/A)             →    Narrative Engine (LLM 驱动，只读叙事)  ← 新增
```

**第七引擎 — Narrative Engine**：这是光荣没有的东西。它不参与游戏逻辑，但在**所有其他引擎结算完成后**，将结算结果转化为沉浸式叙事。

---

## 2. 七引擎架构

### 2.1 架构全景

```
                          ┌─────────────────────┐
                          │   GAME CONTROLLER    │
                          │   回合生命周期管理     │
                          └──────────┬──────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
    ┌───────▼───────┐       ┌───────▼───────┐       ┌───────▼───────┐
    │  MAP ENGINE   │       │  CHARACTER    │       │  DOMESTIC     │
    │               │       │  ENGINE       │       │  ENGINE       │
    │ 领土拓扑       │◄─────►│               │◄─────►│               │
    │ 地形/移动      │ 领地  │ 武将五维       │ 太守  │ 粮食/人口      │
    │ 关隘/ZOC      │ 归属  │ 忠诚/关系      │ 任命  │ 税收/开发      │
    │ 视野/谍报      │       │ 寿命/伤病      │       │ 贸易/科技      │
    └───────┬───────┘       └───────┬───────┘       └───────┬───────┘
            │                       │                       │
            └───────────────────────┼───────────────────────┘
                                    │
                          ┌─────────▼─────────┐
                          │  MILITARY ENGINE  │
                          │  兵种/阵型/补给    │
                          │  战斗结算公式      │
                          └─────────┬─────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
            ┌───────▼───────┐ ┌─────▼─────┐ ┌──────▼──────┐
            │  DECISION     │ │ HISTORY   │ │ NARRATIVE   │
            │  ENGINE       │ │ ENGINE    │ │ ENGINE      │
            │               │ │           │ │             │
            │ NPC 战略 AI   │ │ 事件触发   │ │ LLM 叙事     │
            │ 威胁/机会评估  │ │ 蝴蝶效应   │ │ 只读         │
            │ 个性权重决策   │ │ 历史重力   │ │ RAG 注入     │
            └───────────────┘ └───────────┘ └─────────────┘
```

### 2.2 各引擎详解

#### 2.2.1 Map Engine (地图引擎)

**职责**：定义世界物理空间 — 这个世界"长什么样"

```python
class MapEngine:
    """
    地图引擎。
    
    设计原则：
    - 领土是顶层实体，关隘/港口是领土的"战略点"
    - 地形决定移动消耗和战斗修正
    - ZOC (Zone of Control) 限制敌军自由通过
    """
    
    # ── 领土数据 ──
    territories: dict[str, Territory]
    
    # ── 地形数据 ──
    terrain_grid: dict[tuple[int,int], TerrainCell]
    
    # ── 路径计算 ──
    def find_path(self, origin: str, destination: str, 
                  faction_id: str) -> PathResult:
        """
        A* 寻路。
        - 只能经过友好/中立领土
        - 关隘驻军会阻断路径（除非攻下）
        - 返回: 路径 + 所需回合数 + 粮食消耗
        """
    
    def get_terrain_modifier(self, location: str, unit_type: str) -> float:
        """平原骑兵×1.3 / 森林弓兵×1.2 / 城池守军×1.5"""
    
    def get_visibility(self, faction_id: str) -> set[str]:
        """
        视野范围。
        - 己方领土: 完全可见
        - 邻接领土: 部分可见（兵力估计有误差）
        - 间谍驻扎: +1 格视野
        """
    
    def get_strategic_points(self, territory_id: str) -> list[StrategicPoint]:
        """
        关隘/渡口/城池。
        控制关隘 = 阻断敌军的必经之路
        """
```

**领土属性（扩展现有 regions.json）**：

```python
@dataclass
class Territory:
    id: str                    # "jizhou"
    name: str                  # "冀州"
    owner_id: str              # faction id 或 None
    
    # 地理属性（不变）
    fertility: int             # 1-10 粮食系数
    terrain_type: str          # "plains" / "hills" / "mountain" / "wetland"
    climate_zone: str          # "north" / "central" / "south"
    has_river: bool
    has_coast: bool
    
    # 资源属性
    horse_resource: bool       # 产马 → 可招募骑兵
    iron_resource: bool        # 产铁 → 武器质量+
    salt_resource: bool        # 产盐 → 商业收入+
    
    # 战略点
    strategic_points: list[str]  # 关隘/港口 IDs
    
    # 相邻
    neighbors: list[str]       # 相邻领土 IDs
    neighbor_crossings: dict[str, str]  # {邻居ID: 关隘ID}
    
    # 动态
    development: int           # 0-100
    population: int
    garrison: int
    fortification: int         # 0-100 城防等级
```

#### 2.2.2 Character Engine (角色引擎)

**职责**：管理所有历史人物 — 他们是谁、能做什么、和谁有关系

```python
class CharacterEngine:
    """
    角色引擎。
    
    设计原则：
    - 五维属性是"信号" — 高统率 = 战斗力强
    - 关系网是"约束" — 杀关羽 = 张飞忠诚暴跌
    - 寿命是"时钟" — 郭嘉活不到赤壁
    """
    
    def get_character(self, char_id: str) -> Character
    def get_faction_officers(self, faction_id: str) -> list[Character]
    def get_governor_bonus(self, territory_id: str) -> DomesticBonus
    def get_commander_bonus(self, army_id: str) -> MilitaryBonus
    
    def check_natural_death(self, char_id: str, current_year: int) -> bool:
        """
        自然死亡判定。
        - 到寿命年份有大概率死亡
        - 但允许"演义模式"延长寿命（如果偏离度足够高）
        """
    
    def update_loyalty(self, char_id: str, delta: int, reason: str):
        """
        忠诚度变化。
        - 封赏 +1~5
        - 战败 -3~8  
        - 结义兄弟被杀 -30
        """
    
    def get_relationship_network(self, faction_id: str) -> RelationshipGraph:
        """
        关系网。
        - 结义/婚姻/同乡/师徒
        - 影响忠诚、外交成功率、叛变概率
        """
```

**角色五维（扩展）**：

```python
@dataclass
class Character:
    id: str
    name: str
    alias: str                    # 字
    
    # 五维 (1-100)
    leadership: int               # 统率 — 带兵上限、战斗全局加成
    might: int                    # 武力 — 单挑、突袭、士气冲击
    intelligence: int             # 智力 — 计谋、科技研究、谍报
    politics: int                 # 政治 — 内政、外交、税收效率
    charisma: int                 # 魅力 — 征兵、民心、外交亲和
    
    # 技能/特技
    skills: list[str]             # ["骑兵指挥", "火攻", "屯田", "人德"]
    
    # 关系
    sworn_brothers: list[str]     # 结义兄弟
    spouse: str | None            # 配偶
    mentor: str | None            # 师徒
    hometown: str                 # 同乡
    
    # 动态
    faction_id: str
    loyalty: int                  # 0-100
    location: str
    alive: bool
    birth: int
    death: int                    # 历史死亡年份（可被偏离度延长）
    age: int                      # computed
    
    # 状态
    is_wounded: bool
    is_captured: bool
    is_governor: bool
    is_commanding: bool
```

#### 2.2.3 Domestic Engine (内政引擎)

**职责**：经济基础 — 粮食从哪来、人口如何增长、城市如何发展

```python
class DomesticEngine:
    """
    内政引擎 — 纯粹的数值计算，零 LLM 参与。
    
    设计原则：
    - 所有公式是确定性的
    - 气候用种子伪随机（不可注入）
    - 太守的政治值作为修正乘数
    - 领土属性（fertility, resources）是基础
    """
    
    def calculate_food_production(self, territory: Territory, 
                                   season: Season) -> int:
        """
        粮食产量。
        
        base = fertility × 1000 × (1 + development / 100)
        season_mod = {春:0.3, 夏:1.0, 秋:1.2, 冬:0.05}
        gov_bonus = 1 + governor.politics / 200
        tech_bonus = 1 + tech_level.agriculture * 0.1
        
        food = base × season_mod × gov_bonus × tech_bonus × climate_mod
        """
    
    def calculate_population_growth(self, territory: Territory) -> int:
        """
        人口增长。
        
        surplus_ratio = (food - consumption) / consumption
        if surplus_ratio > 0:
            rate = 0.015 × (1 + morale/100) × (1 + development/200)
        else:
            rate = -0.02 × (1 - surplus_ratio)  # 饥荒
        
        new_pop = max(100, population × (1 + rate))
        """
    
    def calculate_tax_revenue(self, territory: Territory, tax_rate: float) -> int:
        """
        税收。
        
        base = population × tax_rate × 0.05
        gov_bonus = 1 + governor.politics / 200
        return base × gov_bonus
        
        税负 > 0.3 时每季民心 -1~3
        """
    
    def calculate_development_cost(self, territory: Territory, 
                                     target_level: int) -> int:
        """
        开发成本递增。
        cost = 500 × (target_level - current_level) × population / 10000
        """
    
    def process_season(self, all_territories: list[Territory], 
                        season: Season, climate_events: dict) -> SeasonResult:
        """
        季度结算 — 对所有领土执行：
        1. 粮食生产
        2. 人口增长
        3. 税收征收
        4. 开发度自然变化
        5. 民心自然变化
        返回: {territory_id: {food_delta, pop_delta, gold_delta, ...}}
        """
```

#### 2.2.4 Military Engine (军事引擎)

**职责**：军队怎么组建、怎么移动、怎么打仗

```python
class MilitaryEngine:
    """
    军事引擎。
    
    设计原则：
    - 兵种有相克关系（骑克步→步克弓→弓克骑）
    - 战斗结算用兰彻斯特方程变体
    - 补给线用地图引擎的路径计算
    - 将领加成来自角色引擎
    """
    
    def recruit(self, faction_id: str, territory_id: str, 
                unit_type: str, amount: int) -> RecruitResult:
        """征兵 — 消耗人口+金库"""
    
    def move_army(self, army_id: str, destination: str) -> MoveResult:
        """移动 — 消耗粮食+时间，途经关隘被阻断"""
    
    def resolve_battle(self, attacker: Army, defender: Army, 
                        location: str) -> BattleResult:
        """
        战斗结算（确定性公式）：
        
        atk_power = Σ(unit.count × unit.attack × unit.morale × unit.training)
        def_power = Σ(unit.count × unit.defense × unit.morale × unit.training)
        
        atk_power ×= terrain.attack_mod × commander.leadership_bonus
        def_power ×= terrain.defense_mod × fortification_bonus
        
        ratio = atk_power / def_power
        if ratio > 2.0: decisive_victory
        elif ratio > 1.3: victory
        elif ratio > 0.7: draw
        elif ratio > 0.5: defeat
        else: decisive_defeat
        """
    
    def calculate_supply(self, army: Army) -> SupplyStatus:
        """
        补给状态。
        - 在友方领土: 自动补满
        - 在敌方领土: 消耗 ×2，超出补给线距离=损耗
        - 冬季: 消耗 ×1.5
        - 断粮: 每季 20% 减员
        """
```

#### 2.2.5 Decision Engine (决策引擎)

**职责**：NPC 的战略意图 — 他们想干嘛

```python
class DecisionEngine:
    """
    NPC AI 决策引擎。
    
    设计原则：
    - 不使用 LLM（保证一致性和可预测性）
    - 基于个性权重 + 当前状态的多维度评估
    - 每个 NPC 的输出是 Command 列表（与玩家命令格式相同）
    - 这让物理引擎能公平对待所有势力
    """
    
    def evaluate_threats(self, faction_id: str) -> dict[str, float]:
        """
        威胁评估。
        for each neighbor:
            military_ratio = neighbor.strength / self.strength
            border_tension = self.has_border_dispute(neighbor)
            historical_hostility = self.get_relation(neighbor) < 0
            threat = military_ratio × border_tension × historical_hostility
        """
    
    def evaluate_opportunities(self, faction_id: str) -> list[Opportunity]:
        """
        机会评估。
        - 邻国兵力 < 我方 60% → 进攻机会
        - 无主领土邻接 → 占领机会
        - 邻国内乱（民心<30）→ 干预机会
        - 外交孤立势力 → 吞并机会
        """
    
    def generate_commands(self, faction_id: str) -> list[Command]:
        """
        生成本回合命令。
        
        决策流程：
        1. 威胁评估 → 是否需要防御/外交
        2. 机会评估 → 是否可以进攻/扩张
        3. 资源评估 → 内政/征兵优先级
        4. 个性加权 → aggressive×attack + cautious×defend + cunning×scheme
        5. 输出 Command[]
        """
```

**个性档案（模型权重）**：

```python
PERSONALITY_PROFILES = {
    "caocao": {
        "aggression": 0.8, "cunning": 0.9, "caution": 0.3,
        "diplomacy": 0.5, "development": 0.6, "mercy": 0.2,
        "decision_style": "机会主义 — 趁你病要你命"
    },
    "liubei": {
        "aggression": 0.3, "cunning": 0.3, "caution": 0.7,
        "diplomacy": 0.8, "development": 0.8, "mercy": 0.95,
        "decision_style": "仁德优先 — 先安民再图天下"
    },
    "sunjian/sunquan": {
        "aggression": 0.85, "cunning": 0.4, "caution": 0.2,
        "diplomacy": 0.4, "development": 0.5, "mercy": 0.5,
        "decision_style": "猛虎 — 先下手为强"
    },
    "yuanshao": {
        "aggression": 0.5, "cunning": 0.6, "caution": 0.7,
        "diplomacy": 0.7, "development": 0.5, "mercy": 0.6,
        "decision_style": "好谋无断 — 机会来了犹豫，错过又后悔"
    },
    "dongzhuo": {
        "aggression": 0.9, "cunning": 0.5, "caution": 0.1,
        "diplomacy": 0.1, "development": 0.2, "mercy": 0.05,
        "decision_style": "暴虐 — 谁敢不服就杀谁"
    },
}
```

#### 2.2.6 History Engine (历史引擎)

**职责**：让历史事件"发生"或"不发生" — 事件的导演

```python
class HistoryEngine:
    """
    历史引擎 — 事件的条件触发与蝴蝶效应管理。
    
    设计原则：
    - 事件 = 触发条件 + 重力 + 偏离度修正
    - 事件不触发时，下游事件被标记为 blocked
    - 蝴蝶效应通过事件依赖图追踪
    - 不直接修改状态，生成 EventProposal 让其他引擎执行
    """
    
    def check_events(self, year: int, season: str, 
                      world_state: WorldState) -> list[EventProposal]:
        """
        检查所有可触发事件。
        
        for each event in event_catalog:
            if event.year_range covers current time:
                if event.preconditions_met(world_state):
                    effective_prob = event.gravity × (1 - deviation × 0.5)
                    if random() < effective_prob:
                        proposals.append(event.create_proposal(world_state))
                    else:
                        self.mark_averted(event.id, reason="butterfly")
                        self.block_downstream(event.id)
        """
    
    def mark_averted(self, event_id: str, reason: str):
        """事件未触发 → 下游事件被阻断 → 替代历史分支启动"""
    
    def get_alternative_chain(self, blocked_event_id: str) -> EventChain:
        """
        当一个 major 事件被阻断时，生成替代历史链。
        例: 官渡未触发 → 袁绍继续统治河北 → 袁曹持续对峙 → 孙坚趁机北上
        """
    
    def get_historical_context_for_llm(self, year: int, deviation: float) -> str:
        """
        供 RAG 使用 — 检索当前时间窗口的历史事件。
        高偏离度时减少检索范围（因为历史已经不可靠了）
        """
```

**事件定义格式**：

```json
{
  "id": "guandu_200",
  "title": "官渡之战",
  "year_range": [199, 201],
  "category": "major_battle",
  "description": "曹操与袁绍在官渡展开战略决战",
  "preconditions": {
    "required": [
      {"type": "character_alive", "char_id": "caocao"},
      {"type": "character_alive", "char_id": "yuanshao"},
      {"type": "faction_active", "faction_id": "cao"},
      {"type": "faction_active", "faction_id": "yuanshao"},
      {"type": "territory_controlled", "faction_id": "cao", "territory": "yuzhou"},
      {"type": "territory_controlled", "faction_id": "yuanshao", "territory": "jizhou"}
    ],
    "optional": [
      {"type": "character_in_faction", "char_id": "xuyou", "faction_id": "yuanshao"}
    ]
  },
  "gravity": 0.85,
  "outcomes": [
    {
      "id": "cao_wins",
      "probability": 0.55,
      "description": "曹操火烧乌巢，大败袁绍",
      "effects": {
        "faction_changes": {
          "cao": {"strength_delta": "+5000", "morale_delta": "+20", "prestige_delta": "+30"},
          "yuanshao": {"strength_delta": "-30000", "morale_delta": "-30", "prestige_delta": "-20"}
        },
        "character_effects": [
          {"char_id": "xuyou", "new_faction": "cao", "reason": "叛逃投曹"},
          {"char_id": "zhanghe", "new_faction": "cao", "reason": "战败投降"}
        ]
      }
    },
    {
      "id": "stalemate",
      "probability": 0.25,
      "description": "双方相持不下，各自退兵",
      "effects": {...}
    },
    {
      "id": "yuan_wins",
      "probability": 0.20,
      "description": "袁绍采纳许攸奇袭许昌之计，曹操被迫回援",
      "effects": {...}
    }
  ],
  "butterfly_effects": {
    "if_averted": {
      "blocked_downstream": ["cao_unifies_north", "battle_of_chibi"],
      "alternative_chain": ["yuan_expands_south", "cao_defensive_central_plains"]
    }
  }
}
```

#### 2.2.7 Narrative Engine (叙事引擎)

**职责**：将游戏世界的变化转化为沉浸式故事 — **只读，不修改状态**

```python
class NarrativeEngine:
    """
    叙事引擎 — LLM 驱动，纯文本生成。
    
    核心原则:
    - 接收 TurnResult (所有其他引擎的结算结果)
    - 生成叙事文本
    - **绝不**修改任何游戏状态
    - 通过 RAG 注入历史参考
    
    该引擎是唯一调用 LLM 的引擎。
    """
    
    def generate_turn_narrative(self, turn_result: TurnResult) -> NarrativeOutput:
        """
        回合叙事生成。
        
        输入: TurnResult (物理引擎输出)
        - 气候事件
        - 资源变化
        - 战斗结果
        - NPC 行动
        - 历史事件触发
        
        输出: NarrativeOutput
        - court_scene: 内政会议场景
        - battle_descriptions: 战斗叙事
        - npc_flavor: NPC 动向描述  
        - chronicle_entry: 史书体条目
        - advisor_suggestions: 战略建议
        """
    
    def generate_intro(self, scenario: str, player_faction: FactionState) -> str:
        """开局叙事 — 天下大势 + 主公处境"""
    
    def generate_event_narrative(self, event: HistoricalEvent, 
                                  outcome: str) -> str:
        """重大历史事件的叙事"""
```

---

## 3. 引擎间通信协议

### 3.1 Event Bus 模式

```
                    ┌─────────────┐
                    │  EVENT BUS  │
                    │ (消息总线)   │
                    └──────┬──────┘
         ┌─────────┬───────┼───────┬─────────┐
         │         │       │       │         │
    [Map Eng] [Char Eng] [Dom Eng] [Mil Eng] [Decision Eng] [Hist Eng]
         │         │       │       │       │         │         │
         └─────────┴───────┴───────┴───────┴─────────┴─────────┘
                                    │
                            [Narrative Eng]
                             (最后执行, 只读)
```

### 3.2 回合执行顺序

```python
class TurnController:
    """
    回合控制器 — 编排所有引擎的执行顺序。
    
    关键: 所有势力 (玩家+NPC) 的命令在 step 2 统一收集,
         然后在 step 3-6 统一结算。物理引擎不知道谁是玩家。
    """
    
    def execute_turn(self) -> TurnResult:
        # ── Step 1: 环境更新 ──
        climate_events = self.climate_system.roll()           # 纯函数
        season_result = self.domestic_engine.process_season() # 粮食/人口/税收
        
        # ── Step 2: 命令收集 ──
        all_commands = {}
        all_commands["player"] = self.parser.parse(player_input)
        for faction in self.npc_factions:
            all_commands[faction.id] = self.decision_engine.generate_commands(faction.id)
        
        # ── Step 3: 命令验证 ──
        for faction_id, commands in all_commands.items():
            all_commands[faction_id] = self.validator.validate(commands)
        
        # ── Step 4: 移动结算 (所有人同时移动) ──
        moves = self.military_engine.resolve_all_moves(all_commands)
        
        # ── Step 5: 战斗结算 (所有交战同时结算) ──
        battles = self.military_engine.resolve_all_battles(moves)
        
        # ── Step 6: 内政开发 (招兵/建设/研究) ──
        domestic_actions = self.domestic_engine.resolve_actions(all_commands)
        
        # ── Step 7: 外交结算 ──
        diplomacy = self.diplomacy_engine.resolve(all_commands)
        
        # ── Step 8: 历史事件触发 ──
        history_events = self.history_engine.check_events(self.year, self.season)
        self.history_engine.apply_events(history_events)
        
        # ── Step 9: 角色更新 (忠诚/伤病/死亡) ──
        char_updates = self.character_engine.update_all()
        
        # ── Step 10: 状态持久化 ──
        self.save_world_state()
        
        # ── Step 11: 叙事生成 (最后, 只读) ──
        turn_result = TurnResult(
            climate=climate_events,
            season=season_result,
            battles=battles,
            diplomacy=diplomacy,
            history=history_events,
            characters=char_updates,
        )
        narrative = self.narrative_engine.generate_turn_narrative(turn_result)
        
        return TurnResult(narrative=narrative, ...)
```

### 3.3 引擎依赖图

```
Map Engine        → 无依赖（纯空间数据）
Character Engine  → 依赖 Map (角色位置)
Domestic Engine   → 依赖 Map + Character (太守)
Military Engine   → 依赖 Map + Character + Domestic (补给来自Domestic)
Decision Engine   → 依赖以上所有（读取状态做决策）
History Engine    → 依赖以上所有（检测事件条件）
Narrative Engine  → 依赖以上所有（读取结果讲故事，但不修改）
```

---

## 4. 仓库拆分方案

### 4.1 三仓库架构

```
emergencescience/
├── histrategy-engine/        ← Repo #1: 物理引擎 (纯Python, 零LLM)
├── histrategy-knowledge/     ← Repo #2: 历史知识库 (纯数据, 社区贡献)
└── histrategy/               ← Repo #3: 主游戏 (依赖上面两个)
```

### 4.2 Repo #1: `histrategy-engine`

```
histrategy-engine/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── src/histrategy_engine/
│   ├── __init__.py
│   ├── map/
│   │   ├── __init__.py
│   │   ├── territory.py          # 领土模型
│   │   ├── terrain.py            # 地形/移动代价
│   │   ├── pathfinding.py        # A* 寻路
│   │   └── visibility.py         # 视野/谍报
│   ├── character/
│   │   ├── __init__.py
│   │   ├── character.py          # 五维/技能/关系
│   │   ├── loyalty.py            # 忠诚度变化
│   │   └── relationships.py      # 关系网
│   ├── domestic/
│   │   ├── __init__.py
│   │   ├── resources.py          # 粮食/人口/税收
│   │   ├── development.py        # 开发度
│   │   └── climate.py            # 气候系统
│   ├── military/
│   │   ├── __init__.py
│   │   ├── units.py              # 兵种
│   │   ├── combat.py             # 战斗结算
│   │   ├── supply.py             # 补给系统
│   │   └── formations.py         # 阵型
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── personality.py        # 个性档案
│   │   ├── evaluator.py          # 威胁/机会评估
│   │   └── decision_tree.py      # 决策树
│   ├── history/
│   │   ├── __init__.py
│   │   ├── triggers.py           # 条件检测
│   │   ├── butterfly.py          # 蝴蝶效应链
│   │   └── event_catalog.py      # 事件目录
│   ├── turn/
│   │   ├── __init__.py
│   │   └── controller.py         # 回合控制器
│   └── world/
│       ├── __init__.py
│       └── world_state.py        # 全局状态容器
├── tests/
│   ├── test_map.py
│   ├── test_character.py
│   ├── test_domestic.py
│   ├── test_military.py
│   ├── test_ai.py
│   ├── test_history.py
│   └── test_turn.py
└── docs/
    └── engine-architecture.md
```

**依赖**: 仅 Python stdlib + dataclasses。零外部依赖。

**发布**: `pip install histrategy-engine` (内部 PyPI 或公开 PyPI)

### 4.3 Repo #2: `histrategy-knowledge`

```
histrategy-knowledge/
├── README.md
├── CONTRIBUTING.md              # 社区贡献指南
├── LICENSE                      # CC-BY-SA 4.0 (开放数据许可证)
├── schema/
│   ├── event.schema.json        # 历史事件 JSON Schema
│   ├── character.schema.json    # 人物 Schema
│   ├── territory.schema.json    # 领土 Schema
│   └── tech.schema.json         # 科技 Schema
├── timeline/
│   ├── 180s.json                # 184-189 黄巾之乱~董卓入京
│   ├── 190s.json                # 190-199 讨董~官渡前夕
│   ├── 200s.json                # 200-209 官渡~赤壁
│   ├── 210s.json                # 210-219 刘备入蜀~汉中
│   ├── 220s.json                # 220-229 三国鼎立
│   └── 230s.json                # 230-234 诸葛亮北伐~五丈原
├── characters/
│   ├── wei.json                  # 魏国武将
│   ├── shu.json                  # 蜀国武将
│   ├── wu.json                   # 吴国武将
│   └── others.json               # 群雄
├── geography/
│   ├── territories.json          # 十三州+关隘数据
│   ├── climate_zones.json        # 气候区划分
│   └── map_adjacency.json        # 领土邻接关系
├── scenarios/
│   ├── 184_yellow_turban.json    # 黄巾之乱剧本
│   ├── 190_anti_dongzhuo.json    # 讨董联盟剧本
│   ├── 200_guandu.json           # 官渡之战剧本
│   └── 208_chibi.json            # 赤壁之战剧本
├── tech/
│   └── tech_tree.json            # 科技树定义
├── scripts/
│   ├── validate.py               # CI 校验所有 JSON
│   └── generate_rag_index.py     # 生成 RAG 索引文件
└── .github/
    └── workflows/
        └── validate.yml          # CI: 每个 PR 跑 validate.py
```

### 4.4 Repo #3: `histrategy` (主游戏)

```
histrategy/
├── pyproject.toml                # 依赖 histrategy-engine + histrategy-knowledge
├── src/histrategy/
│   ├── parser/
│   │   ├── intent.py             # Intent Parser
│   │   └── validator.py          # Command Validator
│   ├── llm/
│   │   ├── narrative.py          # Narrative Engine (只读LLM)
│   │   ├── rag_retriever.py      # RAG 检索器
│   │   └── adapter.py            # LLM 多provider适配
│   ├── cli/
│   │   ├── app.py                # TUI
│   │   ├── api.py                # FastAPI
│   │   └── openclaw_bridge.py    # OpenClaw 集成
│   └── web/                      # Web 客户端 (后续)
├── tests/
└── docs/
```

---

## 5. 历史知识库设计与获取策略

### 5.1 数据获取策略

**核心决策：预爬取 + 本地索引，不使用运行时网络查询。**

理由：
1. **运行时查询太慢** — LLM 调用本身已需数秒，再加网络查询是不可接受的延迟
2. **公网数据不可靠** — 爬虫被封、页面改版、数据不结构化
3. **数据量可控** — 三国时期 184-280 年共 96 年，按年索引的事件总量 < 1000 条
4. **质量需要人类审查** — 从公网爬取的原始数据需要校对

**数据获取流程：**

```
Phase 1: 基线构建 (一次性)
  1. 从 Wikipedia 时间线页面爬取 184-280 年所有条目
  2. 从《后汉书》、《三国志》、《资治通鉴》白话语译版提取事件
  3. 人工审查 + LLM 辅助结构化
  4. 存储为 JSON → histrategy-knowledge repo
  
Phase 2: 增量补充 (持续)
  1. 社区通过 PR 提交新事件或修订
  2. CI 自动校验 JSON Schema
  3. 维护者审查合并
  
Phase 3: 运行时使用
  1. histrategy-engine 从 histrategy-knowledge 包加载 JSON
  2. RAG 检索器按年份索引快速查询
  3. 无需网络请求
```

### 5.2 气候/灾害数据

你提到的干旱、洪水、瘟疫、蝗灾等，三国时期的精确气候记录非常有限。我们的策略：

**方案 A**: 基于《后汉书·五行志》等史料提取（有记录但稀疏）
- 例: "建安二年（197年），蝗虫起，百姓大饥" — 可录入为 197 年蝗灾事件
- 例: "建安十三年（208年），大疫" — 可录入为 208 年瘟疫事件
- 这些是**已知的历史事实**，可以硬编码到事件系统中

**方案 B**: 对于无记录年份，使用气候概率模型（现有设计中已覆盖）
- 每季每领地独立掷骰: 正常 60% / 干旱 8% / 洪涝 8% / 蝗灾 4% / 大丰 5%
- 概率受地理和季节影响（北方多干旱、沿河多洪涝）
- 玩家不可注入（种子哈希）

**两者关系**：
- 史书有明确记录的灾年 → 高 gravity 事件（大概率触发）
- 史书无记录的年份 → 概率模型自由模拟
- 两个系统互补，不冲突

### 5.3 知识库数据流

```
histrategy-knowledge (Git仓库)
    │
    ├─ CI 校验 (validate.py)
    │   └─ 所有 JSON 必须通过 Schema 验证
    │
    ├─ 版本发版 (GitHub Release)
    │   └─ 每次内容更新打 tag
    │
    └─ 被 histrategy-engine 引用
        │
        ├─ pip install histrategy-knowledge (未来)
        └─ 或 git submodule (开发阶段)
            │
            ▼
        histrategy-engine
            │
            ├─ Map Engine 加载 geography/*.json
            ├─ Character Engine 加载 characters/*.json
            ├─ History Engine 加载 timeline/*.json + scenarios/*.json
            └─ Domestic Engine 加载 tech/*.json
                │
                ▼
            histrategy (主游戏)
                │
                └─ Narrative Engine (LLM)
                    └─ RAG 检索器从 History Engine 获取当前时间窗口事件
```

---

## 6. RAG 系统设计

### 6.1 轻量级实现（无向量数据库）

```python
class HistoricalRAG:
    """
    基于年份索引的轻量级 RAG。
    
    不需要 Milvus/Chroma/Pinecone 等向量数据库。
    因为检索维度单一（时间），年份哈希索引即可。
    """
    
    def __init__(self, knowledge_path: Path):
        # 加载所有时间线 JSON
        self._year_index: dict[int, list[EventEntry]] = {}
        for decade_file in sorted(knowledge_path.glob("timeline/*.json")):
            data = json.loads(decade_file.read_text())
            for event in data["events"]:
                year = event["year"]
                if year not in self._year_index:
                    self._year_index[year] = []
                self._year_index[year].append(event)
    
    def retrieve(self, current_year: int, deviation: float, 
                 max_events: int = 8) -> list[dict]:
        """
        检索当前时间窗口的历史事件。
        
        - 低偏离度 (deviation < 0.3): ±3 年窗口（历史价值高）
        - 中偏离度 (0.3-0.6): ±2 年窗口
        - 高偏离度 (>0.6): ±1 年窗口（历史已不可靠）
        """
        window = 3
        if deviation > 0.3: window = 2
        if deviation > 0.6: window = 1
        
        candidates = []
        for year in range(current_year - window, current_year + window + 1):
            candidates.extend(self._year_index.get(year, []))
        
        # 过滤已发生或不可能的事件
        candidates = [e for e in candidates if self._is_relevant(e)]
        
        # 按 gravity 排序，限制数量
        candidates.sort(key=lambda e: e.get("gravity", 0.5), reverse=True)
        return candidates[:max_events]
    
    def build_llm_context(self, events: list[dict]) -> str:
        """格式化为 LLM prompt 中的上下文"""
        lines = ["## 📜 历史参考（供叙事参考，可不严格遵循）"]
        lines.append(f"以下为{events[0]['year'] if events else '当前'}年前后的真实历史事件：")
        lines.append("")
        for ev in events:
            lines.append(f"- **{ev['title']}** ({ev['year']}年): {ev['description']}")
        lines.append("")
        lines.append("你可以参考以上历史走向，但不必被束缚。当前游戏的实际情况以游戏数据为准。")
        return "\n".join(lines)
```

### 6.2 RAG 注入 LLM 的位置

```
LLM System Prompt
    ├── Game Master 角色定义
    ├── 输出格式要求
    ├── [RAG 注入] ← 历史事件上下文
    ├── 当前 World State (物理引擎输出)
    └── 回合执行结果 (TurnResult)
```

**关键**：RAG 上下文在 system prompt 中，是"参考信息"而非"指令"。LLM 不能因为知道"历史上官渡之战曹操赢了"就在叙事中强行让曹操赢。战斗结果已经由物理引擎决定了。

---

## 7. 社区贡献模型

### 7.1 贡献方式

```
histrategy-knowledge 仓库:

1. Fork → 编辑 JSON → PR → CI 校验 → 人工 Review → Merge
2. 也可以直接提 Issue（不懂 JSON 的玩家可以写中文描述，由 maintainer 录入）
```

### 7.2 贡献内容类型

| 贡献类型 | 难度 | 示例 |
|----------|------|------|
| **历史事件补充** | ⭐ 低 | 添加一个史书上记载但知识库缺失的事件 |
| **人物数据完善** | ⭐ 低 | 补充某武将的生卒年/技能 |
| **事件分支设计** | ⭐⭐ 中 | 为一个现有事件设计 2-3 个 alternative outcomes |
| **蝴蝶效应链** | ⭐⭐ 中 | 设计"如果 A 事件不发生，下游哪些事件会变化" |
| **新剧本** | ⭐⭐⭐ 高 | 设计一个完整的 starting scenario |
| **气候/地理数据** | ⭐⭐⭐ 高 | 基于史料补充某年的旱涝灾害记录 |

### 7.3 CI 校验

```yaml
# .github/workflows/validate.yml
name: Validate Knowledge
on: [pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/validate.py
        # 检查:
        # 1. 所有 JSON 格式正确
        # 2. 所有引用的人物/势力/领土 ID 存在
        # 3. 年份范围合理 (184-280)
        # 4. 事件效果的数据类型正确
        # 5. no duplicate IDs
```

### 7.4 激励模型

```
贡献者 → 计入 CONTRIBUTORS.md → 游戏内"鸣谢"页面
       → 优秀贡献者获得 emergence.science credits
       → 核心贡献者成为 repo maintainer
```

---

## 8. LLM 叙事层的定位

### 8.1 什么归 LLM，什么不归

| 系统 | 实现 | 原因 |
|------|------|------|
| 气候掷骰 | 种子伪随机 | 必须可复现 |
| 粮食产量 | 确定性公式 | 必须可审计 |
| 战斗结果 | 确定性公式 | 必须公平 |
| NPC 决策 | 个性权重决策树 | 必须可预测 |
| 事件触发 | 条件 + 概率 | 必须可测试 |
| **叙事生成** | **LLM** | 需要创意 |
| **谋臣对话** | **LLM** | 需要多样化 |
| **史书编写** | **LLM** | 需要风格变化 |

### 8.2 LLM 调用预算

```
每次回合的 LLM 调用:
  1. Plan Mode (内政会议 + 建议):   ~800 input + ~1500 output = ~2300 tokens
  2. Command Mode (执行叙事):       ~1200 input + ~2000 output = ~3200 tokens
  
  每回合合计: ~5500 tokens
  40 回合一局: ~220K tokens ≈ $0.05 (DeepSeek 价格)
```

---

## 9. 实施路线图

### Phase 1: Engine Foundation (2 周)

```
Week 1-2:
  □ 创建 histrategy-engine 仓库
  □ Map Engine: 领土/地形/寻路/视野
  □ Character Engine: 五维/技能/关系网/忠诚度
  □ Domestic Engine: 粮食/人口/税收/开发/气候
  □ 单元测试 ≥ 80% 覆盖
  □ CI/CD setup (pytest + ruff)
```

### Phase 2: Military + Decision (1.5 周)

```
Week 3-4:
  □ Military Engine: 兵种/招募/补给/战斗结算
  □ Decision Engine: 个性档案/威胁评估/决策树
  □ Turn Controller: 回合编排
  □ 集成测试: 完整回合自动运行
```

### Phase 3: History + Knowledge (1.5 周)

```
Week 4-5:
  □ 创建 histrategy-knowledge 仓库
  □ 预爬取 Wikipedia 时间线 → JSON
  □ 补充三国志史料 → JSON
  □ History Engine: 事件触发/蝴蝶效应
  □ RAG 检索器
  □ 社区贡献模板 (CONTRIBUTING.md + CI)
```

### Phase 4: Narrative + Integration (2 周)

```
Week 6-7:
  □ Narrative Engine (只读 LLM)
  □ Intent Parser + Validator
  □ 与 histrategy-engine 集成
  □ TUI 客户端改造
  □ 完整 E2E 测试
```

### Phase 5: Clients + Operations (持续)

```
Week 8+:
  □ REST API (FastAPI)
  □ Web 客户端 MVP (React)
  □ OpenClaw 客户端
  □ 自动 AAR 生成
  □ 运营飞轮启动
```

---

## 10. 附录：数据源参考

### 10.1 现有数据源

| 数据源 | 覆盖范围 | 获取方式 |
|--------|----------|----------|
| Wikipedia Timeline | 184-280 完整时间线 | 已爬取 184-219 |
| 现有 events.json | 190-199 关键事件 | 已有 |
| 现有 characters.json | ~240 个人物 | 已有（需补全五维） |
| 现有 factions.json | 8 个主要势力 | 已有 |
| 现有 regions.json | 13 州 | 已有（需补全关隘数据） |

### 10.2 待获取数据源

| 数据源 | 内容 | 优先级 |
|--------|------|--------|
| 《后汉书·五行志》 | 灾害记录（旱涝蝗疫） | 高 |
| 《三国志》白话语译 | 人物五维基准值 | 高 |
| 《资治通鉴·汉纪》 | 编年事件补充 | 中 |
| 谭其骧《中国历史地图集》 | 关隘/渡口位置 | 中 |
| 《三国演义》 | 演义事件分支（供 alternative outcomes） | 低 |

### 10.3 数据获取方法

```
1. Wikipedia API (已可用)
   - curl "https://en.wikipedia.org/w/api.php?action=parse&page=Timeline_of_the_Three_Kingdoms_period&prop=text&format=json&section=N"

2. 《后汉书》等中文史料
   - 使用 guoxue/http 等网站的爬虫
   - 或使用已有的结构化数据集（如 cbdb.fas.harvard.edu 中国历代人物传记数据库）

3. 社区贡献
   - 三国爱好者社区（百度贴吧、知乎三国话题）
   - 邀请历史爱好者贡献人物五维评分
```

---

**文档状态**: 审查中
**下一步**: 等你的审阅和反馈，然后从 Phase 1 开始实施
