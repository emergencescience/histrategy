# 三國志略·宏观历史模拟引擎 — 技术设计文档

> 版本: 0.1 | 2026-06-12 | Prometheus
> 状态: 草案 — 待用户审阅

---

## 一、与 feat/v3-llm-simulation 的差异分析

### 1.1 架构差异

```
feat/v3-llm-simulation (战役级)       macro-historical-engine (宏观级)
══════════════════════════════        ═══════════════════════════════
IntentParser (战斗指令)               PolicyParser (策令解析)
    ↓                                      ↓
CommandValidator                          PolicyValidator
    ↓                                      ↓
auto_mobilize (调兵)                      —
    ↓                                      
TurnController (战斗+经济)               QuarterlyEngine (经济+人口+民心)
    ↓                                      ↓
HistoryEngine                            HistoryEngine + BlackSwanInjector
    ↓                                      ↓
WorldSimulator (LLM 战斗覆盖)            MacroPolicyEngine (LLM 季度推演)
    ↓                                      ↓
GuardrailValidator                       GuardrailValidator (新约束)
    ↓                                      ↓
StateApplier                             StateApplier (略修改)
    ↓                                      ↓
NarrativeEngine                          ChronicleEngine + KnowledgeLayer
```

### 1.2 复用 vs 重写

| 组件 | 复用? | 说明 |
|------|------|------|
| `LLMAdapter` | ✅ 完全复用 | 不变 |
| `WorldState` (v2) | ✅ 复用 + 扩展 | 加 policy_effects 字段 |
| `FactionState` | ✅ 复用 | 不变 |
| `Territory` | ✅ 复用 + 扩展 | 加 population_growth_rate |
| `Character` | ✅ 复用 | 不变 |
| `TurnMemory` | ✅ 复用 | 改名为 EpochMemory |
| `StateApplier` | ✅ 复用 | 约束集更新 |
| `GuardrailValidator` | ✅ 复用 | 约束集重写 |
| `HistoryEngine` | ✅ 复用 + 扩展 | 加 BlackSwanInjector |
| `IntentParser` | 🔄 重写 | → `PolicyParser` |
| `CommandValidator` | 🔄 重写 | → `PolicyValidator` |
| `TurnController` | 🔄 重写 | → `QuarterlyEngine` |
| `WorldSimulator` | 🔄 重写 | → `MacroPolicyEngine` |
| `NarrativeEngine` | 🔄 重写 | → `ChronicleEngine` |
| `_auto_mobilize_for_attack` | ❌ 删除 | 宏观引擎无需调兵 |
| 前端 UI | 🔄 重写 | chat → dashboard + chat |

---

## 二、命令系统重新设计

### 2.1 PolicyCommand 类型

从 battle commands 转为 policy commands：

```python
@dataclass
class PolicyCommand:
    type: str           # tax_rate | law | appoint | diplomacy | war | sue_peace | 
                        # relocate_capital | intelligence | develop | trade
    params: dict        # 类型特定参数
    notes: str          # 原始文本备注 (保留上下文)
    source_text: str    # 原始文本片段
```

### 2.2 命令类型详解

| type | params 示例 | LLM 推演内容 |
|------|------------|-------------|
| `tax_rate` | `{territory: "all", rate: 0.30}` | 税收变化→民心→人口增长→长期税基 |
| `law` | `{name: "屯田制", scope: "all"}` | 制度变革的经济/社会影响 |
| `appoint` | `{character: "xunyu", position: "尚书令"}` | 行政效率变化、派系影响 |
| `diplomacy` | `{target: "wu", action: "alliance"}` | 关系变化、可能的背叛/接受 |
| `war` | `{target: "liubiao", reason: "..."}` | LLM 模拟战役结果 |
| `sue_peace` | `{target: "cao", terms: "称臣纳贡"}` | 谈判结果 |
| `relocate_capital` | `{from: "xuchang", to: "luoyang"}` | 行政中心迁移的影响 |
| `intelligence` | `{target: "wu", scope: "military"}` | 情报准确度提升 |
| `develop` | `{territory: "ye", focus: "agriculture"}` | 区域开发效果 |
| `trade` | `{target: "wu", goods: "grain"}` | 贸易收益 |

### 2.3 PolicyParser (替代 IntentParser)

系统 prompt 的变化：不再要求输出 `attack/move/recruit` 等战斗指令，而是输出宏观策令。

关键约束：
- 鼓励用户写"解释性的策令"——"屯田制怎么做"的细节
- Parser 需要从自由文本中提取：政策名称、参数值、目标
- 保留完整的 notes 字段给下游 LLM 使用

---

## 三、MacroPolicyEngine (替代 WorldSimulator)

### 3.1 输入上下文

```yaml
时间: 208年春 | 第5季度
玩家势力: cao (曹操)
玩家策令:
  - type: tax_rate, params: {rate: 0.30}, notes: "降低税率..."
  - type: law, params: {name: "屯田制"}, notes: "在全部领地推行..."
  - type: war, params: {target: "liubiao"}, notes: "趁刘表病危取荆州..."

势力状态:
  cao: 兵力150000, 资金74437, 粮草34970, 民心44, 领地9
  shu: 兵力5000, 资金3576, 粮草0, 民心60, 领地1
  wu: 兵力60000, 资金13158, 粮草10576, 民心61, 领地7
  ...

确定性基线:
  经济变化: cao税收-2000/季(因税率下调), 粮草+3000/季(屯田)
  人口变化: cao +0.8%, shu -2%(粮草耗尽)
  民心变化: cao +5(因减税)

历史记忆:
  T1: 曹操屯兵宛城, 新野战败
  T2: 曹操再攻新野, 又败; 刘备粮草耗尽
  ...

黑天鹅候选:
  - 208年3月: 刘表病亡 (历史引力 0.90)
  - 208年9月: 长坂坡之战 (历史引力 0.85)
```

### 3.2 LLM 输出 Schema

```json
{
  "quarterly_outcomes": {
    "economic": {
      "cao": {"tax_delta": -2000, "food_delta": +3000, "trade_delta": 0},
      "shu": {"tax_delta": -500, "food_delta": -2000, "trade_delta": 0}
    },
    "population": {
      "cao": {"growth_rate": 0.008, "migration_from": ["shu"]},
      "shu": {"growth_rate": -0.02, "migration_to": ["cao"]}
    },
    "morale": {
      "cao": {"delta": +5, "reason": "减税政策深得民心"},
      "shu": {"delta": -8, "reason": "粮草耗尽，百姓恐慌"}
    }
  },
  "battle_results": [
    {
      "location": "xiangyang",
      "attacker": "cao",
      "defender": "liubiao",
      "result": "attack_win",
      "casualties": {"attacker": {"infantry": 3000}, "defender": {"infantry": 8000}},
      "territory_captured": true,
      "narrative": "刘表病亡消息传到襄阳，刘琮畏战，举州投降曹操"
    }
  ],
  "black_swan_events": [
    {
      "event_id": "liubiao_death_208",
      "triggered": true,
      "outcome": "刘表病亡，次子刘琮继位。刘琮在蒯越劝说下举荆州投降曹操。",
      "effects": {
        "liubiao_dead": true,
        "jingzhou_owner": "cao",
        "liubei_location": "dangyang",
        "liucong_faction": "cao"
      }
    }
  ],
  "diplomatic_reactions": [
    {
      "faction": "wu",
      "reaction": "alarmed",
      "action": "孙权紧急召见周瑜、鲁肃商议对策，决定联刘抗曹",
      "relation_delta": {"cao": -10, "shu": +15}
    }
  ],
  "narrative_seeds": [
    "曹操不战而得荆州，天下震动",
    "刘备仓皇南逃，百姓十余万跟随",
    "孙权在赤壁集结水军，大战一触即发"
  ],
  "knowledge_cards": [
    {
      "topic": "屯田制",
      "era": "建安元年(196)",
      "source": "《三国志·魏书·武帝纪》",
      "quote": "是岁，乃兴屯田...",
      "modern_scholarship": "田余庆认为屯田制的核心是人口控制..."
    },
    {
      "topic": "刘表之死与荆州投降",
      "era": "建安十三年(208)",
      "source": "《三国志·魏书·刘表传》",
      "quote": "太祖征表，未至，表病死...",
      "modern_scholarship": "何兹全认为荆州世族的集体投降反映了..."
    }
  ]
}
```

### 3.3 模型策略

| 组件 | 模型 | 理由 |
|------|------|------|
| PolicyParser | `deepseek-v4-flash` | 简单解析任务，快 |
| MacroPolicyEngine | `deepseek-chat` (或 `claude-sonnet-4`) | 核心创造力，需要深度推理 |
| ChronicleEngine | `deepseek-v4-pro` | 叙事质量要求最高 |
| KnowledgeCards | `deepseek-chat` | 需要引用准确，不能幻觉 |

---

## 四、BlackSwanInjector (新增)

### 4.1 设计

扩展现有 `HistoryEngine`，在确定性事件（preconditions 必须全部满足）之上，增加**概率性黑天鹅注入**。

```python
class BlackSwanInjector:
    """Inject stochastically-triggered historical events."""
    
    def check_events(self, year, season, world_state, deviation):
        """
        1. Query events near the current year from knowledge base
        2. For each event: check preconditions (faction alive, territory owned, etc.)
        3. If preconditions met, apply probability based on:
           - history_gravity (历史引力)
           - deviation (玩家偏离度 — 越偏离越可能 avert)
        4. Return triggered events
        """
```

### 4.2 事件定义

```yaml
# knowledge/events/208_red_cliffs.yaml
event_id: red_cliffs_208
year: 208
season: winter
history_gravity: 0.95
preconditions:
  - faction_alive: cao
  - faction_alive: wu
  - faction_alive: shu  
  - territory_owned_by: {territory: xiangyang, owner: cao}
  # 如果曹操没有占领襄阳，赤壁不会发生
effects:
  battle_red_cliffs: 
    default_outcome: "wu_shu_win"
    cao_casualties: {infantry: 20000, cavalry: 5000}
    narrative: "周瑜火攻曹军..."
    territory_effects:
      - {territory: xiangyang, owner: cao}  # 曹操保留襄阳
      - {territory: jiangling, owner: cao}
```

### 4.3 黑天鹅触发后的注

当 LLM 决定触发黑天鹅时，同时生成 knowledge_cards，解释：
- 正史中这个事件是如何发生的
- 游戏中触发条件与正史的异同
- 现代学者对这个事件的解读

---

## 五、QuarterlyEngine (替代 TurnController)

### 5.1 确定性基线计算

不再计算战斗，而是计算经济/人口/民心基线：

```python
class QuarterlyEngine:
    def execute_quarter(self, world_state, policy_commands, year, quarter):
        """
        1. Tax: 税收 = Σ(territory.population × tax_rate × commerce_tech)
        2. Food: 粮草消耗 = Σ(army_size × 0.1) + population × 0.02
                 粮草产出 = Σ(territory.population × agriculture_tech × fertility × 0.05)
        3. Population: 增长率 = base_growth × morale_modifier × tax_modifier
        4. Morale: 民心变化 = tax_effect + food_effect + war_effect + policy_effect
        5. Development: 开发度缓慢增长（与投资成正比）
        
        Returns QuarterlyResult (类似 TurnResult)
        """
```

### 5.2 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| base_population_growth | 0.005/季 | 2%/年 |
| tax_morale_penalty | -(rate-0.2)×50 | 税率每高10%扣5民心 |
| food_per_soldier | 0.1/季 | 每兵每季消耗粮草 |
| food_per_population | 0.02/季 | 每人每季消耗粮草 |
| development_decay | 0.99 | 每季开发度衰减系数 |

---

## 六、知识层 (KnowledgeLayer)

### 6.1 数据模型

```python
@dataclass
class KnowledgeCard:
    topic: str                # "屯田制"
    trigger_event: str        # 哪个游戏事件触发了这张卡
    historical_source: str    # 史料引用
    source_text: str          # 原文
    modern_scholarship: str   # 现代学者观点
    scholar_name: str         # 学者名
    scholar_work: str         # 著作名
    engine_logic: str         # 引擎把这个事件建模成了什么
    related_topics: list[str] # 相关知识点
```

### 6.2 知识库构建

初始从 knowledge/data/ 目录下的 JSON 数据中提取基础信息，然后用 LLM 批量生成 knowledge card 内容。人工审核后纳入游戏。

---

## 七、前端架构

### 7.1 技术栈

- **后端**: FastAPI + SQLModel (已有)
- **前端**: 纯 HTML + vanilla JS + SVG + Chart.js（或轻量替代）
  - 不使用 React/Vue（保持简单，2人团队可维护）
- **地图**: 简化 SVG 地图（静态），用 CSS 着色表示势力
- **图表**: 轻量 charting library（如 uPlot 或纯 Canvas）

### 7.2 页面结构

```
/games/histrategy        → 游戏大厅 (已有)
/play/histrategy         → 游戏主界面 (重写)
  ├── 左侧面板: 势力看板 + 趋势图
  ├── 中央面板: 廷议对话 + 策令输入
  ├── 右侧面板: 知识弹窗区域
  └── 底部: 时间轴导航
/manual                  → 玩家手册 (已有，需更新)
/encyclopedia            → 百科系统 (新增)
```

### 7.3 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/game/new` | POST | 创建新游戏 |
| `/api/game/{id}/quarter` | POST | 提交策令，推进季度 |
| `/api/game/{id}/state` | GET | 获取当前游戏状态 |
| `/api/game/{id}/history` | GET | 获取历史回合 |
| `/api/encyclopedia/{topic}` | GET | 查询百科条目 |
| `/api/encyclopedia/search?q=` | GET | 搜索百科 |

---

## 八、分支策略建议

### 推荐：先合并 feat/v3-llm-simulation，再开新分支

```
main ─────────────────────────────────────
  │                                       
  ├── feat/v3-llm-simulation ──→ [MERGE]  
  │   (保留基础设施: TurnMemory,            
  │    StateApplier, Guardrail)            
  │                                       
  └── feat/macro-historical-engine ← [NEW]
      (宏观引擎完整实现)
```

**理由**：

1. **feat/v3-llm-simulation 有大量可复用基础设施** — TurnMemory、StateApplier、GuardrailValidator、LLM adapter 改进。合并到 main 后所有分支都能用。

2. **宏观引擎的改动太大** — 如果在 feat/v3 上继续改，git diff 会极其混乱（大量删除战斗代码 + 新增政策代码），review 几乎不可能。

3. **feat/v3-llm-simulation 本身没有线上价值** — 它是战役级引擎，我们已决定不做。但它包含的 infrastructure 是干净的、可独立合并的。

4. **主分支保持可工作** — main 上有可玩的 histrategy（战斗引擎），同时 macro 分支独立开发。不阻塞玩家使用现有版本。

### 操作步骤

```bash
# 1. 提交 feat/v3 当前状态（已推）
cd /opt/data/repos/histrategy
git checkout feat/v3-llm-simulation
git add -A && git commit -m "chore: archive v3 battle-engine work before macro pivot"

# 2. 创建 PR 并合并到 main
# (通过 gh CLI 创建 PR，描述清楚合并的是 infrastructure 而非战斗引擎)

# 3. 从 main 创建新分支
git checkout main && git pull
git checkout -b feat/macro-historical-engine

# 4. 在新分支上清理和重构
# - 删除 auto_mobilize、battle override 逻辑
# - 重写 WorldSimulator → MacroPolicyEngine
# - 重写前端 UI
```

---

## 九、开发路线图

### Phase 1: 核心引擎 (2-3 周)

- [ ] PolicyParser（替换 IntentParser）
- [ ] PolicyValidator
- [ ] QuarterlyEngine（替换 TurnController）
- [ ] MacroPolicyEngine（替换 WorldSimulator）
- [ ] BlackSwanInjector
- [ ] ChronicleEngine（替换 NarrativeEngine，含 knowledge_cards 输出）
- [ ] 新 API 端点

### Phase 2: 前端重建 (2-3 周)

- [ ] 游戏主界面 HTML/CSS/JS
- [ ] SVG 势力地图
- [ ] 势力看板（数据卡片）
- [ ] 廷议对话面板
- [ ] 知识弹窗系统
- [ ] 时间轴导航

### Phase 3: 内容与打磨 (1-2 周)

- [ ] Knowledge card 内容生成 (LLM 辅助)
- [ ] 百科系统
- [ ] E2E 测试（5+ 剧本跑通）
- [ ] 平衡性调优（经济参数、民心曲线）
- [ ] 玩家手册更新

### Phase 4: 上线 (1 周)

- [ ] 部署到 Railway
- [ ] 监控与告警
- [ ] 初始用户邀请

---

## 十、风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 宏观引擎"不够好玩" | 中 | 强化知识层和教育价值，用"学到东西"弥补"操作快感"缺失 |
| LLM 成本过高 | 中 | 每个季度 1 次 LLM 调用（不是每队兵），成本可控 |
| LLM 数值幻觉 | 高 | Guardrail + 确定性基线 + 数值范围约束 |
| 知识层内容质量 | 中 | 初始 LLM 生成 + 人工审核，逐步积累 |
| 玩家觉得"AI 在玩，不是我在玩" | 中 | 确保每个策令的影响可见、可追溯、可学习 |
