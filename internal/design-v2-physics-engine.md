# Histrategy v2 — 完整架构设计

> 物理引擎驱动 × 角色深度绑定 × LLM 叙事渲染 × 运营飞轮

**作者**: Prometheus (Hermes Agent)
**日期**: 2026-06-07 (v2 更新)
**状态**: 设计审查中

---

## 0. 设计哲学：宏观历史唯物主义 × 人物驱动

### 0.1 调研结论

对市面上成功的历史策略游戏分析：

| 游戏 | 核心驱动力 | 玩家粘性来源 | 对三國志略的启示 |
|------|-----------|-------------|-----------------|
| **光荣三国志** (11/14) | 人物养成 | 收集名将、培养数值、触发历史事件 | 人物属性系统是三国 IP 的核心价值 |
| **Total War: TK** | 人物+战斗 | Romance 模式销量远超 Records 模式 | 玩家要的是"关羽温酒斩华雄"，不是"步兵方阵推进" |
| **Crusader Kings 3** | 人物关系网 | 家族传承、阴谋、角色扮演 | 人物驱动 + 宏观推演可以并存 |
| **文明系列** | 科技树+版图 | "再来一回合"的正反馈循环 | 科技树的递进式奖励机制值得借鉴 |
| **历史模拟器：崇祯** | 人物+叙事 | 沉浸式历史体验、AI 对话 | LLM 让角色"活过来"是差异化优势 |

### 0.2 三國志略的设计定位

**结论：宏观物理引擎 + 人物作为"修正因子" + LLM 叙事渲染**

```
          ┌──────────────────────────┐
          │    PHYSICS ENGINE        │  ← 宏观：粮食、人口、领土、气候
          │   (What happens)         │     确定性公式，所有势力平等
          └──────────┬───────────────┘
                     │
                     ▼
          ┌──────────────────────────┐
          │    CHARACTER SYSTEM      │  ← 中观：人物属性修正物理结果
          │   (Who makes it happen)  │     关羽统率高 → 战斗加成
          └──────────┬───────────────┘     诸葛亮智高 → 科技加速
                     │
                     ▼
          ┌──────────────────────────┐
          │    LLM NARRATIVE         │  ← 微观：生成故事，不改变结果
          │   (How it's told)        │     "关羽温酒斩华雄"的叙事
          └──────────────────────────┘
```

**为什么走这条路：**
1. 三国 IP 的核心是**人物**—玩家玩三国是为了关羽、诸葛亮、曹操，不是为了一块地的产量
2. 但人物的作用必须经由**客观系统**来体现—否则就是 LLM 拍脑袋说谁赢谁赢
3. 物理引擎提供公平性，人物系统提供策略深度，LLM 提供沉浸感
4. 这个架构也兼容你提到的"历史唯物主义"视角：物质基础（粮/金/人口）决定上层建筑（战争/外交），但杰出人物可以加速或延缓历史进程

---

## 1. 模块化架构总览

### 1.1 核心原则：物理引擎作为可插拔独立包

```
histrategy-engine/          ← 独立的 Python 包，零依赖 LLM
├── pyproject.toml
├── src/histrategy_engine/
│   ├── __init__.py
│   ├── core/               ← 纯函数，无副作用
│   │   ├── resources.py    ← 粮食/税收/人口增长
│   │   ├── climate.py      ← 季节/天气掷骰
│   │   ├── military.py     ← 招募/补给/战斗结算
│   │   └── formulas.py     ← 共享数学公式
│   ├── world/              ← 世界状态
│   │   ├── territory.py    ← 领土模型
│   │   ├── faction.py      ← 势力模型
│   │   ├── character.py    ← 人物模型（属性/技能/关系）
│   │   └── world_state.py  ← 全局状态容器
│   ├── ai/                 ← NPC 决策引擎
│   │   ├── personality.py  ← 个性档案
│   │   ├── decision_tree.py← 决策树
│   │   └── evaluator.py    ← 威胁/机会评估
│   ├── events/             ← 事件系统
│   │   ├── triggers.py     ← 条件触发器
│   │   ├── historical.py   ← 历史事件定义
│   │   └── random_events.py← 随机事件
│   ├── tech/               ← 科技系统
│   │   ├── tech_tree.py    ← 科技定义
│   │   └── diffusion.py    ← 科技传播
│   └── turn/               ← 回合控制
│       └── controller.py   ← 回合生命周期
│
histrategy/                 ← 主游戏（依赖 histrategy-engine）
├── llm/                    ← LLM 叙事层
│   ├── narrative.py        ← 叙事生成器（只读）
│   ├── context_builder.py  ← RAG 上下文构建
│   └── adapter.py          ← 多 provider 适配
├── parser/                 ← 玩家输入处理
│   ├── intent.py           ← Intent Parser
│   └── validator.py        ← 命令验证
├── knowledge/              ← 知识库
│   ├── rag/                ← RAG 系统
│   │   ├── index.py        ← 事件索引
│   │   └── retriever.py    ← 检索器
│   └── data/               ← 结构化知识
│       ├── timeline_190.json  ← 190-200年事件时间线
│       ├── timeline_200.json  ← 200-210年
│       ├── timeline_210.json  ← 210-220年
│       └── characters.json    ← 人物数据库
└── cli/                    ← 客户端
    ├── app.py              ← TUI
    ├── api.py              ← REST API
    └── openclaw_bridge.py  ← OpenClaw 集成
```

### 1.2 可插拔接口

```python
from abc import ABC, abstractmethod

class PhysicsEngine(ABC):
    """物理引擎接口 — 可替换实现"""
    
    @abstractmethod
    def process_turn(self, world: WorldState, commands: dict[str, list[Command]]) -> TurnResult:
        """处理一个完整回合 — 所有势力命令 → 结算 → 新状态"""
        ...

class NarrativeEngine(ABC):
    """叙事引擎接口 — 可替换实现"""
    
    @abstractmethod
    def generate(self, turn_result: TurnResult) -> Narrative:
        """接收结算结果 → 生成叙事文本（只读）"""
        ...

class CommandParser(ABC):
    """命令解析器接口"""
    
    @abstractmethod
    def parse(self, raw_text: str, faction_id: str) -> list[Command]:
        """自由文本 → 已验证的结构化命令"""
        ...
```

**为什么这样设计：**
- `histrategy-engine` 可以独立测试、独立版本、独立发布
- 物理引擎可以用纯 Python 实现，也可以后续用 Rust 重写（性能）
- 叙事引擎可以切换 LLM provider 或使用本地模型
- 未来可以做多人游戏：物理引擎完全不知道哪个 faction 是 AI 哪个是人

---

## 2. 角色系统：人物的"修正因子"角色

### 2.1 五维属性

```python
@dataclass
class Character:
    id: str
    name: str
    
    # 核心五维 (1-100)
    leadership: int    # 统率 — 影响带兵上限、战斗加成
    might: int         # 武力 — 影响单挑、突袭
    intelligence: int  # 智力 — 影响计谋、科技研究、谍报
    politics: int      # 政治 — 影响内政、外交、税收效率
    charisma: int      # 魅力 — 影响征兵效率、民心、外交成功率
    
    # 技能
    skills: list[str]  # e.g. ["骑兵指挥", "火攻", "屯田"]
    
    # 动态
    faction_id: str
    loyalty: int       # 0-100
    location: str
    alive: bool
    age: int
```

### 2.2 属性如何影响物理引擎

```
粮食产量 = base_formula × (1 + 太守政治 / 200)
         = 冀州 10 × 1.0 × 1.2 × 1.0 × (1 + 荀彧政治95 / 200)
         = 冀州粮食 × 1.475

战斗伤害 = base_formula × (1 + 主将统率 / 200) × (1 + 副将武力 / 400)

外交成功率 = base_probability × (1 + 使者魅力 / 200)

征兵效率 = base_recruitment × (1 + 太守魅力 / 200)

科技研究速度 = base_speed × (1 + 研究者智力 / 200)
```

**关键**：角色属性是**乘法修正**而非加法，这意味着：
- 诸葛亮的智力 100 → 科技速度 ×1.5
- 普通文官智力 50 → 科技速度 ×1.25
- 但基础速度来源于物理引擎的 development 等级，角色不能无中生有

### 2.3 忠诚度与关系

```
忠诚度变化：
  - 封赏（给钱给官）        +1~5
  - 战败                    -3~8
  - 长期不发俸禄            每季 -2
  - 亲密度高的同僚被杀       -10~20
  - 君主魅力高              +0~2/季

关系网（影响忠诚的群体效应）：
  - 结义兄弟被杀            忠诚 -30
  - 配偶在敌对势力          忠诚 -5/季
  - 同乡在麾下              忠诚 +1/季
```

---

## 3. RAG 历史知识库系统

### 3.1 设计思路

LLM 没有精确的三国历史知识——它知道"赤壁之战发生在208年"但不精确。RAG 系统在每次 LLM 调用时，将**当前时间窗口的历史事件**注入上下文，让 LLM 有"历史参考"但不受历史束缚。

### 3.2 数据结构

```json
{
  "year": 200,
  "events": [
    {
      "id": "guandu_200",
      "title": "官渡之战",
      "month": 10,
      "description": "曹操与袁绍在官渡对峙。曹操以少胜多，火烧乌巢，大败袁绍。",
      "participants": ["曹操", "袁绍", "许攸", "张郃", "高览"],
      "faction_changes": {
        "cao": {"strength_delta": "+5000", "morale_delta": "+20"},
        "yuan_shao": {"strength_delta": "-30000", "morale_delta": "-30"}
      },
      "territory_changes": {},
      "preconditions": [
        "cao.faction.alive",
        "yuan_shao.faction.alive", 
        "cao.controls('yuzhou')",
        "yuan_shao.controls('jizhou')"
      ],
      "gravity": 0.85,
      "butterfly_effect": "许攸叛逃事件可能不发生或后果不同",
      "type": "major_battle"
    },
    {
      "id": "sun_ce_death_200",
      "title": "孙策遇刺",
      "month": 4,
      "description": "孙策在丹徒狩猎时为许贡门客所伤，不久身亡。孙权继位。",
      "participants": ["孙策", "孙权", "周瑜", "张昭"],
      "faction_changes": {
        "wu": {"ruler_change": "孙策→孙权", "morale_delta": "-10"}
      },
      "type": "character_death"
    }
  ]
}
```

### 3.3 RAG 检索策略

```python
class HistoricalRAG:
    """基于年份的轻量级检索 — 不需要向量数据库"""
    
    def retrieve(self, current_year: int, deviation: float) -> list[dict]:
        """
        检索当前时间窗口的历史事件。
        
        - 时间窗口: current_year ± 3年
        - 但若 deviation > 0.5，仅检索 ±1年（历史已偏离，参考价值降低）
        - 返回: 排序后的事件列表（gravity 高的优先）
        """
        window = 1 if deviation > 0.5 else 3
        events = []
        for year in range(current_year - window, current_year + window + 1):
            events.extend(self._index.get(year, []))
        
        # 按 gravity 排序，限制数量（控制 token 消耗）
        events.sort(key=lambda e: e["gravity"], reverse=True)
        return events[:8]  # 最多 8 个事件
    
    def build_context(self, events: list[dict]) -> str:
        """将历史事件格式化为 LLM 上下文"""
        lines = ["## 历史参考（供叙事参考，可不严格遵循）"]
        for ev in events:
            lines.append(f"- {ev['year']}年{ev.get('month','')}月: {ev['description']}")
        return "\n".join(lines)
```

**RAG 注入位置：**
1. **Plan Mode**: 注入当前±3年的历史事件 → LLM 的谋臣建言可以"参考"历史走向
2. **Command Mode**: 注入当前±1年的历史事件 → LLM 叙事可以"呼应"真实历史
3. **Intro**: 注入开局年的历史背景

**RAG ≠ 强制历史**：事件只在上下文中作为"参考"，LLM 的 system prompt 明确说"可参考但不必须遵循"。物理引擎的结算结果才是最终权威。

---

## 4. 科技树：有机扩散模型

### 4.1 为什么不用 Civilization 线性树

Civ 的科技树是"玩家选择 → 解锁"的主动模式。更适合三国的模式是 **Paradox 式的有机扩散**：

- 科技在**所有势力中自然传播**（如印刷术从洛阳传到各州）
- 玩家可以**加速**特定方向的研发（派高智力文官研究）
- 但不可能"跳过时代"或"完全不发展农业"
- 这更符合历史唯物主义：生产力发展有自身规律

### 4.2 科技分类

```python
TECH_CATEGORIES = {
    "agriculture": {  # 农业科技
        "irrigation": {"prereq": None, "era": 1, "effect": {"food_output": 1.15}},
        "crop_rotation": {"prereq": "irrigation", "era": 2, "effect": {"food_output": 1.25}},
        "improved_plow": {"prereq": "crop_rotation", "era": 3, "effect": {"food_output": 1.40}},
        "granary": {"prereq": "irrigation", "era": 2, "effect": {"food_storage": 1.30}},
    },
    "military": {
        "improved_forge": {"prereq": None, "era": 1, "effect": {"weapon_quality": 1.10}},
        "crossbow": {"prereq": "improved_forge", "era": 2, "effect": {"ranged_damage": 1.20}},
        "heavy_cavalry": {"prereq": "improved_forge", "era": 2, "effect": {"cavalry_defense": 1.15}, "requires_resource": "horses"},
        "siege_weapons": {"prereq": "crossbow", "era": 3, "effect": {"siege_speed": 1.50}},
        "formations": {"prereq": None, "era": 2, "effect": {"unit_morale": 1.10}},
        "fire_attack": {"prereq": None, "era": 2, "effect": {"special_attack": "fire"}, "requires_intelligence": 80},
    },
    "administration": {
        "bureaucracy": {"prereq": None, "era": 1, "effect": {"tax_efficiency": 1.15}},
        "legal_code": {"prereq": "bureaucracy", "era": 2, "effect": {"corruption_reduction": 0.20}},
        "imperial_exams": {"prereq": "legal_code", "era": 3, "effect": {"officer_quality": 1.10}},
    },
    "commerce": {
        "markets": {"prereq": None, "era": 1, "effect": {"trade_income": 1.15}},
        "currency": {"prereq": "markets", "era": 2, "effect": {"trade_income": 1.25}},
        "trade_routes": {"prereq": "currency", "era": 3, "effect": {"trade_range": 2}},
    },
    "culture": {
        "academies": {"prereq": None, "era": 2, "effect": {"tech_spread_rate": 1.15}},
        "historiography": {"prereq": "academies", "era": 3, "effect": {"legitimacy": 1.10}},
    },
}
```

### 4.3 科技传播机制

```python
def calculate_tech_progress(faction, world):
    """每回合计算科技进展"""
    for category, techs in TECH_CATEGORIES.items():
        for tech_id, tech in techs.items():
            # 基础传播速度
            spread_rate = 0.02  # 2% per turn base
            
            # 修正因子
            if faction.development > 50:
                spread_rate *= (1 + faction.development / 200)  # 开发度高加速
            
            # 相邻势力已拥有该科技 → 加速传播
            neighbor_has_tech = any(
                n.has_tech(tech_id) for n in world.get_neighbors(faction)
            )
            if neighbor_has_tech:
                spread_rate *= 1.5  # 邻国已有 → 传播加速
            
            # 贸易路线加速
            trade_partners_with_tech = sum(
                1 for p in faction.trade_partners if p.has_tech(tech_id)
            )
            spread_rate *= (1 + trade_partners_with_tech * 0.1)
            
            # 主动研究加速（如果玩家或 NPC AI 指定了研究方向）
            if tech_id in faction.research_focus:
                researcher = faction.get_best_officer("intelligence")
                if researcher:
                    spread_rate *= (1 + researcher.intelligence / 200)
            
            # 累积进度
            faction.tech_progress[tech_id] += spread_rate
            
            # 解锁
            if faction.tech_progress[tech_id] >= 1.0:
                faction.unlock_tech(tech_id)
```

**关键洞察**：科技是有机扩散的，不是线性解锁的。这符合"历史唯物主义"——生产力发展是整体社会进程，不是某个君主的个人选择。

---

## 5. 蝴蝶效应与事件触发系统

### 5.1 核心问题

你提的问题非常精准：

> "历史事件有很多非线性的——一个领导人的死亡、一则情报、一次战役都可能完全改写历史"

现有游戏对这个问题的处理都不完美。我们的方案：

### 5.2 事件触发：条件 + 重力 + 偏离度

```python
@dataclass
class HistoricalEvent:
    id: str
    title: str
    year_range: tuple[int, int]     # 可能发生的年份范围
    
    preconditions: dict              # 触发条件
    # 例: {"cao.controls": ["yuzhou"], "yuanshao.alive": True, "caocao.alive": True}
    
    gravity: float                   # 0-1 历史"引力"强度
    # 官渡之战=0.9, 赤壁之战=0.95, 三顾茅庐=0.7
    
    possible_outcomes: list[dict]    # 可能的结果分支
    # [
    #   {"condition": "default", "result": "曹操胜利", "prob": 0.6},
    #   {"condition": "yuanshao.uses_xuyou", "result": "袁绍采纳许攸", "prob": 0.3},
    #   {"condition": "yuanshao.loses_wuchao", "result": "乌巢被烧", "prob": 0.1}
    # ]
    
    butterfly_effects: list[str]     # 如果事件不发生/结果不同，下游事件的变化
    # ["袁绍未败 → 曹操无法统一北方 → 赤壁之战不会发生 → ..."]
```

### 5.3 事件驱动流程

```
每个回合结束时：

1. 检查所有历史事件的 preconditions
   - 条件满足 → 进入候选池
   - 条件不满足 → 跳过（事件可能永远不会发生）

2. 对候选事件计算生效概率
   effective_prob = gravity × (1 - player_deviation × 0.5)
   
   示例:
   - 官渡之战 gravity=0.9, deviation=0.1 → prob = 0.9 × 0.95 = 0.855
   - 官渡之战 gravity=0.9, deviation=0.6 → prob = 0.9 × 0.7 = 0.63
   
   高偏离度 = 历史越来越不可能按原轨道走

3. 掷骰决定是否触发
   - 触发 → 从 possible_outcomes 中按概率选择一个结果
   - 不触发 → 记录为 averted（可能影响下游事件）

4. 物理引擎执行事件后果
   - 兵力变化、领土转移、将领死亡、关系变动
   - 所有后果通过物理引擎结算（确定性）

5. LLM 生成事件叙事
   - RAG 注入真实历史版本作为对比
   - 如发生偏离，LLM 在叙事中体现"史官将此记为建安异录"
```

### 5.4 蝴蝶效应链

```json
{
  "id": "guandu_200",
  "butterfly_effects": [
    {
      "if_averted": "曹操无法统一北方",
      "downstream_events_blocked": ["liubei_flees_jingzhou", "battle_of_chibi"],
      "alternative_chain": [
        "袁绍趁胜南下 → 曹操退守兖州 → 袁绍与孙坚争霸中原 → 刘备趁乱取益州"
      ]
    },
    {
      "if_outcome": "draw",
      "description": "曹操与袁绍两败俱伤",
      "alternative_chain": [
        "河北诸侯趁机反叛袁绍 → 中原出现权力真空 → 刘表北上"
      ]
    }
  ]
}
```

**蝴蝶效应的边界**：我们不试图模拟"全部可能"，而是为每个 major event 预定义 2-3 种可能的分支结果。这保持了可测试性，同时提供了足够的变化。

---

## 6. 玩家输入安全：Intent Parser + Validator

```
玩家自由文本
    │
    ▼
┌───────────────────────────────────────┐
│  Intent Parser (LLM, 小模型, 低成本)    │
│                                       │
│  System Prompt:                       │
│  "你是一个命令解析器。                  │
│   从以下文本中提取可执行的操作。         │
│   支持的操作类型:                       │
│     recruit, move, attack, develop,    │
│     tax, train, spy, trade, rest,      │
│     appoint, dismiss, negotiate,       │
│     research                           │
│   不支持的操作（直接忽略）:              │
│     - 修改天气或气候                    │
│     - 凭空增加资源                     │
│     - 改变他人忠诚度（除封赏外）         │
│     - 修改历史或时间线                  │
│     - 瞬移部队                         │
│   输出: JSON                           │
│   {'actions': [{'type': ...,           │
│     'params': {...}}]}                 │
└───────────────┬───────────────────────┘
                ▼
┌───────────────────────────────────────┐
│  Validator (纯代码, 零LLM)             │
│                                       │
│  recruit: 数量 ≤ 人口×5%, 花费 ≤ 金库  │
│  move: 目标在补给范围内                │
│  attack: 目标存在 + 不相邻则需移动到邻  │
│  appoint: 人物存在 + 忠诚度 > 30       │
│  tax: 税率 0.1-0.5                    │
│                                       │
│  任何非法命令 → 丢弃 + 返回合法命令     │
│  "风调雨顺" → 匹配不到操作 → 丢弃       │
│  "让关羽忠诚度变成100" → appoint可加    │
│     但appoint效果由物理引擎决定          │
└───────────────────────────────────────┘
```

---

## 7. 运营飞轮

### 7.1 飞轮模型

```
优质游戏体验
    ↓
玩家自发传播（B站/知乎/Reddit/Steam）
    ↓
新玩家涌入 + GitHub Star 增长
    ↓
社区反馈 → 改进游戏 → 更优质体验
    ↓                    ↓
emergence.science 品牌曝光   Mod/扩展生态
    ↓                    ↓
平台引流（bounty marketplace）   UGC 内容
    ↓
商业化变现
```

### 7.2 传播基础设施

| 阶段 | 目标 | 行动 |
|------|------|------|
| **冷启动** | 100 GitHub Stars | 技术文章（知乎/Show HN）、开源社区推广 |
| **社区建设** | 500 Discord 成员 | 每日开发日志、开放 Mod API、征集历史事件 |
| **内容裂变** | B站 10 万播放 | 游戏实况（脚本录制 → LLM 生成解说 → 自动上传） |
| **平台联动** | 100 emergence.science 注册 | 游戏内"一键发布 bounty"按钮 |
| **商业化** | 月活 1000+ | Steam 发布、DLC（新剧本）、Token 内购（LLM 成本） |

### 7.3 内容自动化

利用现有的 Hermes Agent + emergence 基础设施：
- **每日游戏日志** → 自动生成 AAR 文章 → 发布到知乎/Medium
- **脚本化录屏** → `headless_cli.py` 运行 → SVG 录像 → 裁剪为短视频
- **社区监控** → 监控 B站/Reddit 关于三国策略游戏的讨论 → 针对性回复
- **版本更新日志** → 自动生成 changelog → 推送到 Discord/GitHub

---

## 8. 实施路线图 (更新)

### Phase 1: Engine Core (2 周)
```
□ 1.1 histrategy-engine 独立包骨架
□ 1.2 领土资源系统（粮食/人口/税收/开发）
□ 1.3 气候系统（季节 + 历史气候数据种子）
□ 1.4 军事系统（兵种/招募/补给/战斗公式）
□ 1.5 角色系统（五维属性/技能/忠诚关系）
□ 1.6 科技传播系统
□ 1.7 单元测试覆盖 ≥ 80%
```

### Phase 2: RAG + Events (1 周)
```
□ 2.1 历史事件知识库（184-234年完整时间线）
□ 2.2 RAG 检索器（年份索引 + 上下文构建）
□ 2.3 事件触发系统（preconditions + gravity + deviation）
□ 2.4 蝴蝶效应链（每个 major event 的 2-3 分支）
```

### Phase 3: NPC AI + Player Integration (1.5 周)
```
□ 3.1 NPC 个性档案 × 决策树
□ 3.2 Intent Parser（小模型 LLM）
□ 3.3 Validator（纯代码验证层）
□ 3.4 回合控制器（所有势力同时结算）
□ 3.5 TUI 集成
```

### Phase 4: Narrative + Clients (2 周)
```
□ 4.1 叙事引擎（只读 LLM）
□ 4.2 上下文构建器（物理结果 + RAG 历史）
□ 4.3 REST API（FastAPI）
□ 4.4 Web 客户端 MVP（React + Canvas 地图）
□ 4.5 OpenClaw 客户端
```

### Phase 5: Operations (持续)
```
□ 5.1 自动 AAR 生成 + 发布
□ 5.2 游戏实况录制 + 自动上传 B站
□ 5.3 社区管理（Discord + GitHub Issues）
□ 5.4 emergence.science 平台联动
```

---

## 9. 关键指标

| 指标 | 目标 (Phase 3 完成时) | 目标 (Phase 5 完成时) |
|------|----------------------|----------------------|
| 可玩回合数 | 40+ 回合 | 100+ 回合 |
| 势力数 | 8+ 可操控 | 15+ |
| 剧本 | 1 (190) | 4 (184/190/200/208) |
| LLM 每次调用 token | < 3000 input | < 2000 input |
| 测试覆盖率 | ≥ 80% | ≥ 85% |
| GitHub Stars | 50 | 500 |
| Discord 成员 | 100 | 500 |
| B站视频播放 | 1 万 | 10 万 |

---

*本设计文档会持续演进。每个 Phase 完成后更新状态。*
