# Histrategy v2 — 实施计划

> 从三顾茅庐到白帝托孤 · 测试驱动 · 渐进交付 · 可回滚

**日期**: 2026-06-07
**状态**: 待审阅

---

## 1. 剧本路线图

### 1.1 MVP: 207 三顾茅庐 → 223 白帝托孤（首发）

**为什么选这段**：

| 优势 | 说明 |
|------|------|
| **知名度最高** | 三顾茅庐、赤壁之战、借荆州、入蜀、汉中、关羽北伐、夷陵、托孤——中国人最熟悉的一段 |
| **角色最丰富** | 诸葛亮、关羽、张飞、赵云、曹操、孙权、周瑜、鲁肃、司马懿...全员出场 |
| **戏剧性最强** | 从寄人篱下到三分天下到大厦将倾——完整的英雄之旅 |
| **节奏紧凑** | 16 年浓缩了三国所有经典战役 |
| **玩家身份清晰** | 玩家 = 刘备（或诸葛亮），目标明确：帮刘备建立蜀汉 |
| **知识库最少** | 只需 207-223 共 17 年的事件数据，初始爬取量最小 |

**起始状态 (207年冬)**：

| 势力 | 君主 | 领土 | 兵力 | 特点 |
|------|------|------|------|------|
| 刘备 | 刘备 | 新野（寄居刘表） | 5000 | 无根据地，但有关张赵+即将诸葛 |
| 曹操 | 曹操 | 兖豫徐青冀幽并+司隶 | 200000 | 已统一北方，最强势力 |
| 孙权 | 孙权 | 扬州+荆州东部 | 80000 | 据长江天险，周瑜鲁肃辅佐 |
| 刘表 | 刘表 | 荆州（襄阳） | 60000 | 老病将死，二子争位 |
| 刘璋 | 刘璋 | 益州（成都） | 50000 | 暗弱，张鲁在北威胁 |
| 马超 | 马超 | 凉州 | 30000 | 西凉铁骑，与曹操有杀父之仇 |
| 张鲁 | 张鲁 | 汉中 | 20000 | 五斗米教，自守之贼 |

**关键事件链 (207-223)**：

```
207冬  三顾茅庐 → 隆中对 → 诸葛亮加入
208春  刘表死 → 曹操南下 → 刘备携民渡江 → 长坂坡 → 赵云救阿斗
208冬  赤壁之战（火烧连环）→ 曹操败退
209    刘备取荆南四郡 → 娶孙夫人
210    周瑜死 → 鲁肃借南郡
211-214 刘备入蜀 → 庞统死 → 诸葛亮入川 → 取成都
215    孙权索荆州 → 湘水划界
217-219 汉中争夺战 → 黄忠斩夏侯渊 → 刘备称汉中王
219秋  关羽北伐 → 水淹七军 → 吕蒙白衣渡江 → 关羽败走麦城 → 被杀
220    曹操死 → 曹丕篡汉 → 刘备称帝
221-222 夷陵之战 → 陆逊火烧连营 → 刘备败退白帝城
223    白帝托孤 → 刘备死 → 诸葛亮受托
```

### 1.2 v2: 190 讨董 → 210 赤壁后（扩展）

首版发布后 6 个月添加。

**新增内容**：190-206 年时间线、董卓/吕布/袁术/公孙瓒势力、更多剧本选择。

### 1.3 v3: 罗马版（国际市场）

```
三國志略: 三世纪危机
  → 罗马帝国的衰落与分裂
  → 玩法复用七引擎架构
  → 知识库完全替换为罗马历史
  → 面向 Steam/英文玩家
```

---

## 2. TDD + Headless SDK 测试策略

### 2.1 测试金字塔

```
         ┌─────┐
         │ E2E │  ← Headless SDK 完整游戏回放
        ┌┴─────┴┐
        │ 集成   │  ← 七引擎联调测试
       ┌┴───────┴┐
       │  单元    │  ← 每个引擎独立测试
      └──────────┘
```

### 2.2 单元测试（≥80% 覆盖率）

每个引擎的每个公开方法都有单元测试：

```python
# tests/test_domestic.py
def test_food_production_spring_plains():
    """春·平原·开发度50 → 粮食 = fertility×1000×0.3×(1+0.5)"""
    engine = DomesticEngine()
    territory = Territory(fertility=8, terrain="plains", development=50)
    result = engine.calculate_food_production(territory, Season.SPRING)
    assert result == pytest.approx(8 * 1000 * 0.3 * 1.5, rel=1e-2)

def test_food_production_winter_zero():
    """冬 · 粮食应该接近0"""
    result = engine.calculate_food_production(territory, Season.WINTER)
    assert result < 100

def test_governor_bonus_affects_food():
    """太守政治95 → 产量×1.475"""
    ...

def test_population_growth_with_surplus():
    """粮食富余时人口正增长"""
    ...

def test_population_decline_during_famine():
    """饥荒时人口下降"""
    ...

def test_climate_seeded_deterministic():
    """相同种子 → 相同气候（可复现）"""
    ...

# tests/test_military.py
def test_combat_cavalry_advantage_on_plains():
    """平原 骑兵 vs 步兵 → 骑兵优势"""
    ...

def test_combat_defender_fortification_bonus():
    """守城方城防加成"""
    ...

def test_supply_line_attrition():
    """超补给范围 → 损耗"""
    ...

# tests/test_ai.py
def test_caocao_attacks_weak_neighbor():
    """曹操高攻击 → 邻国兵力<60% → 选择进攻"""
    ...

def test_liubei_develops_instead():
    """刘备低攻击 → 即使有机会也优先内政"""
    ...
```

### 2.3 Headless SDK 回归测试

`headless_cli.py` 已存在。改造为：

```python
# tests/headless/test_scenario_207_liubei_historical.py
def test_liubei_follows_history():
    """
    模拟刘备走历史路线：
    1. 三顾茅庐 → 诸葛亮加入 ✓
    2. 携民渡江 → 长坂坡 ✓  
    3. 赤壁之战 → 孙刘联军胜 ✓
    4. 取荆南四郡 ✓
    5. 入蜀 → 取成都 ✓
    6. 汉中争夺 → 称汉中王 ✓
    7. 关羽北伐 → 被杀（验证蝴蝶效应）✓
    8. 夷陵之战 → 败退白帝城 ✓
    
    验证：
    - 每回合游戏不崩溃
    - 关键事件在预期回合触发
    - 物理引擎数值在合理范围
    - LLM 叙事不为空
    """
    config = HeadlessConfig(
        scenario="207",
        faction="liubei",
        decisions=[  # 预定义决策序列（模拟历史走向）
            "三顾茅庐，请诸葛亮出山相助",
            "刘表将死，先稳定新野民心",
            "曹操南下，携百姓渡江暂避锋芒",
            "派诸葛亮去江东联合孙权",
            "赤壁大胜后，趁势取荆南四郡",
            "受刘璋之邀，入蜀相助",
            "取成都，建立蜀汉基业",
            "命关羽北伐襄阳",
            # 关羽被杀的后果自动触发...
            "为关羽报仇，出兵伐吴",
            "夷陵战败，退守白帝城",
        ],
        max_turns=60,
        record=True,  # 记录完整回放
    )
    
    history = run_headless_game(config)
    
    # 验证关键事件
    assert history.has_event("三顾茅庐", by_turn=3)
    assert history.has_event("赤壁之战", by_turn=8)
    assert history.has_event("刘备入蜀", by_turn=20)
    assert history.faction_exists("shu")  # 蜀汉建立了
    
    # 验证物理引擎数值
    assert history.final_state.factions["shu"].strength > 10000
    assert history.final_state.factions["cao"].strength > history.final_state.factions["shu"].strength
```

```python
# tests/headless/test_scenario_207_liubei_alt_1.py
def test_liubei_stays_in_jingzhou():
    """替代历史：刘备不入蜀，全力经营荆州 → 关羽北伐有后援 → 成功"""
    ...

# tests/headless/test_scenario_207_liubei_alt_2.py  
def test_liubei_allies_with_caocao():
    """替代历史：刘备与曹操联合攻孙权 → 三分变两分"""
    ...

# tests/headless/test_scenario_207_caocao.py
def test_caocao_unifies_all():
    """曹操视角：统一天下 → 建立魏朝"""
    ...
```

### 2.4 Headless SDK 回放录制

每次 headless 运行生成：

```
logs/replays/
├── 2026-06-07_207_liubei_historical.json   # 完整游戏状态回放
├── 2026-06-07_207_liubei_historical.md     # 叙事文本回放（可读）
└── 2026-06-07_207_liubei_alt_1.json
```

这些文件：
- 记录每回合的输入/输出/状态快照
- 可作为回归测试的 expected output
- 开发者可以直接阅读叙事文本评估质量
- 玩家可以分享自己的"通关记录"

---

## 3. 回滚策略

### 决策：同一 repo 的 feature branch

```
main ────●────────●────────●────────●─── (v1 保持稳定)
          \        \        \
feat/v2-engine──●──●──●──●──●──●── (v2 开发)
                    \
                     ↓ 如果失败
                   
回滚: git checkout main && git branch -D feat/v2-engine
      → v1 完整保留，零损失
```

**理由**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| **同 repo feature branch** | 共享 git history / CI / issues；回滚就是切回 main | branch 可能很长 |
| **新 repo** | 完全隔离 | 重复 CI 配置；issues 分散；PR 跨 repo；合并时需要手动搬运 |

**回滚条件**（何时判定 v2 失败）：

1. Headless SDK 回归测试中，物理引擎输出与预期偏差 > 20%
2. LLM 叙事质量明显低于 v1（独立评估）
3. 开发 4 周后核心引擎仍未通过所有单元测试
4. 玩家试玩反馈平均分 < v1

**渐进式迁移**：

```
Phase 1 (2周): 在 feat/v2-engine 上构建六引擎核心
  → 不影响 main 分支
  → 单独跑 CI
  
Phase 2 (1.5周): Military + Decision Engine
  → Headless SDK 完整回放对比 v1 vs v2
  
Phase 3 (1.5周): Knowledge + History Engine + RAG
  → E2E 测试通过
  
Phase 4 (2周): Narrative 集成
  → 与 v1 对比试玩
  → 通过则 merge to main
  → 不通过则保留 branch, 分析问题
```

---

## 4. Token 消耗估算

### 4.1 重构前 (v1 当前)

```
每回合 LLM 调用:

Plan Mode (内政会议):
  System prompt: ~3500 tokens
  World context (所有势力完整状态): ~800 tokens  
  LLM output (court dialogue + suggestions + summary): ~1500 tokens
  小计: ~5800 tokens

Command Mode (政令执行):
  System prompt: ~4500 tokens
  Command context (世界状态 + 玩家决策): ~600 tokens
  LLM output (bureaucracy + aftermath + seeds + NPC + factions): ~3000 tokens
  小计: ~8100 tokens

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每回合合计: ~13,900 tokens
40 回合: ~556,000 tokens
成本 (DeepSeek): ~$0.14/局
```

### 4.2 重构后 (v2)

```
每回合 LLM 调用:

Plan Mode:
  System prompt (含RAG): ~2000 tokens  ← 精简
  RAG context (±3年事件): ~400 tokens  ← 新增
  World context (精简, 仅公开数据): ~400 tokens  ← 从800降为400
  LLM output: ~1200 tokens
  小计: ~4,000 tokens (-31%)

Command Mode:
  System prompt: ~1500 tokens  ← 精简
  RAG context: ~300 tokens
  World context (精简): ~300 tokens  ← 从600降为300
  LLM output: ~1500 tokens  ← 减少（物理引擎已处理数值）
  小计: ~3,600 tokens (-56%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每回合合计: ~7,600 tokens (-45%)
40 回合: ~304,000 tokens
成本 (DeepSeek): ~$0.08/局

节省: 45% token / 43% 成本
```

**节省来源**：
1. System prompt 从冗长指令改为精炼的系统定义
2. World context 从全状态 dump 改为结构化精简
3. LLM 不再需要输出数值变化（物理引擎已处理）
4. RAG 历史参考比全量 context 更精准 → 减少 LLM "猜测"

---

## 5. NPC 数据可见性设计

### 5.1 公开 vs 私有数据

```python
@dataclass
class FactionState:
    # ── 公开数据（所有势力可见）──
    id: str
    name: str
    ruler_id: str                     # 君主（已知）
    capital: str                      # 首都（已知）
    territories: list[str]            # 已知领土
    is_active: bool
    
    # ── 估算数据（随谍报等级精准度提升）──
    strength_estimated: int           # 兵力估算（有误差）
    economy_estimated: int            # 经济估算
    morale_estimated: int             # 民心估算
    
    # ── 私有数据（仅本势力 + 高谍报可窥）──
    _strength_actual: int             # 真实兵力
    _economy_actual: int              # 真实经济
    _morale_actual: int               # 真实民心
    _treasury: int                    # 金库
    _food: int                        # 粮草
    _tech_levels: dict                # 科技等级
    _active_plans: list[str]          # 正在执行的密谋
    _spy_network: dict                # 间谍部署
```

### 5.2 存储方案：JSON 文件（默认）+ SQLite（可选）

```
默认 (零依赖):
  ~/.histrategy/
  ├── world_state.json        # 公开状态
  ├── private_state.json      # 私有状态（玩家势力）
  ├── npc_private/            # NPC 私有数据（加密存储，防止玩家窥探）
  │   ├── cao.json
  │   ├── wu.json
  │   └── ...
  ├── player_memory.json
  ├── event_history.json
  └── relationships.json

可选 (pip install histrategy[sqlite]):
  ~/.histrategy/histrategy.db  # SQLite 存储
  → 支持 SQL 查询：SELECT * FROM events WHERE year=208
  → 跨存档统计分析
  → 但需要额外安装 aiosqlite
```

**决策：JSON 文件为主**。

理由：
- 零依赖安装（`pip install histrategy` 不需要其他包）
- JSON 可读、可 git track、可手动编辑
- 私有数据只需简单的文件分离（`npc_private/` 目录）
- SQLite 作为可选增强（`histrategy[sqlite]`）

### 5.3 可选增强

```bash
# 基础安装（零外部依赖）
pip install histrategy

# Web 客户端
pip install histrategy[web]

# SQLite 存储 + 数据分析
pip install histrategy[sqlite]

# 联网搜索增强（Tavily/Brave → 实时历史查询）
pip install histrategy[search]

# 全部
pip install histrategy[web,sqlite,search]
```

---

## 6. 任务拆解

### 6.1 GitHub Issues

```
P1: Engine Foundation (2周)
  Issue #3: 创建 histrategy-engine 仓库 + CI
  Issue #4: Map Engine — 领土/地形/寻路/视野
  Issue #5: Character Engine — 五维/技能/关系网/忠诚度
  Issue #6: Domestic Engine — 粮食/人口/税收/开发/气候

P2: Military + AI (1.5周)
  Issue #7: Military Engine — 兵种/招募/补给/战斗
  Issue #8: Decision Engine — 个性档案/威胁评估/决策树
  Issue #9: Turn Controller — 回合编排

P3: History + Knowledge (1.5周)
  Issue #10: 创建 histrategy-knowledge 仓库 + CI
  Issue #11: 预爬取 207-223 历史事件 → JSON
  Issue #12: History Engine — 事件触发/蝴蝶效应
  Issue #13: RAG 检索器 + Context Builder

P4: Narrative + Integration (2周)
  Issue #14: Narrative Engine — 只读 LLM 叙事层
  Issue #15: Intent Parser + Validator
  Issue #16: 与 histrategy-engine 集成 + TUI 改造
  Issue #17: Headless SDK 回归测试套件

P5: Clients (后续)
  Issue #18: REST API (FastAPI)
  Issue #19: Web 客户端 MVP
  Issue #20: OpenClaw 客户端
```

### 6.2 Hermes Kanban 任务

创建 `histrategy-v2` board：

```bash
hermes kanban boards create histrategy-v2 --title "三國志略 v2 重构"

# P1 任务
hermes kanban create --board histrategy-v2 --title "V2-01: Create histrategy-engine repo + CI/CD"
hermes kanban create --board histrategy-v2 --title "V2-02: Map Engine implementation"
hermes kanban create --board histrategy-v2 --title "V2-03: Character Engine implementation"
hermes kanban create --board histrategy-v2 --title "V2-04: Domestic Engine implementation"

# P2 任务
hermes kanban create --board histrategy-v2 --title "V2-05: Military Engine implementation"
hermes kanban create --board histrategy-v2 --title "V2-06: Decision Engine implementation"
hermes kanban create --board histrategy-v2 --title "V2-07: Turn Controller implementation"

# P3 任务
hermes kanban create --board histrategy-v2 --title "V2-08: Create histrategy-knowledge repo"
hermes kanban create --board histrategy-v2 --title "V2-09: 207-223 timeline data entry"
hermes kanban create --board histrategy-v2 --title "V2-10: History Engine + Butterfly effects"
hermes kanban create --board histrategy-v2 --title "V2-11: RAG retriever + Context builder"

# P4 任务
hermes kanban create --board histrategy-v2 --title "V2-12: Narrative Engine (LLM read-only)"
hermes kanban create --board histrategy-v2 --title "V2-13: Intent Parser + Validator"
hermes kanban create --board histrategy-v2 --title "V2-14: Engine integration + TUI migration"
hermes kanban create --board histrategy-v2 --title "V2-15: Headless SDK regression test suite"

# P5 任务
hermes kanban create --board histrategy-v2 --title "V2-16: REST API server"
hermes kanban create --board histrategy-v2 --title "V2-17: Web client MVP"
hermes kanban create --board histrategy-v2 --title "V2-18: OpenClaw client integration"
```

---

## 7. 文档索引

所有设计文档已整理到 `docs/` 文件夹：

| 文档 | 说明 |
|------|------|
| `docs/design-v2-technical-spec.md` | 七引擎架构 · 模块化设计 · 知识库策略 |
| `docs/design-v2-physics-engine.md` | 物理引擎核心 · 角色系统 · 防注入 |
| `docs/design-v2-implementation-plan.md` | 本文档 — 实施计划 · TDD · 回滚 · Token |
| `docs/ROADMAP.md` | 长期路线图（需更新） |
| `docs/PRD.md` | 产品需求文档 |
| `docs/tech-design.md` | v1 技术设计（存档） |

---

*文档状态: 待审阅*
