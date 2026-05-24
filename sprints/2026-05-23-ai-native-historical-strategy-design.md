# AI 原生文本历史战略游戏：PRD 与 Tech Design 优化

> Status: Draft v0.1
> Date: 2026-05-23
> Scope: 不改代码，沉淀下一阶段产品、技术、运营、测试设计
> Related: `docs/PRD.md`, `docs/tech-design.md`, `logs/2026-05-23-caocao.txt`

## 1. 类型定位

推荐对外定位：

**AI-powered text-based historical grand strategy game**

中文可以写作：

**AI 驱动的文本历史大战略游戏**，或更短的 **AI 文本历史策略游戏**。

它不是传统文字冒险，也不是纯数值大战略，而是三类经验的交叉：

- **AI 文本冒险 / LLM RPG**：类似 AI Dungeon，核心卖点是玩家可以用自然语言自由行动。
- **大战略 / grand strategy**：类似 Crusader Kings、Total War 战略层，核心是多势力、长期目标、外交、战争、资源和历史惯性。
- **涌现叙事 / emergent narrative simulation**：类似 RimWorld、Dwarf Fortress、Crusader Kings，故事不是作者线性写完，而是从系统交互中长出来。

Histrategy 的最佳差异化不是“AI 帮我写三国故事”，而是：

> 玩家以自然语言提出政治、军事、经济、外交战略；AI 幕府理解战略意图；规则世界模型约束与推演；历史事件在惯性与偏离之间演化。

## 2. 外部经验摘要

调研来源：

- RimWorld Steam 页面将自己定位为由 AI Storyteller 驱动的故事生成器，强调事件由叙事导演调度，而非只做胜负挑战：https://store.steampowered.com/app/294100/RimWorld/
- Game Developer 对 Crusader Kings II 的 GDC 2014 介绍强调“让玩家讲述自己的独特故事”，而不是复述游戏预写故事：https://www.gamedeveloper.com/design/video-designing-i-crusader-kings-ii-i-to-generate-strange-emergent-stories
- AI Dungeon 代表了 AI 文本冒险的自由输入范式，但长期一致性、记忆和可控性是核心挑战：https://apps.apple.com/us/app/ai-dungeon/id1491268416
- LLM 游戏设计讨论普遍建议将 LLM 用于开放表达、规划和叙事，但将权威世界状态留给结构化模拟与校验：https://sites.uci.edu/kolbynottingham/2024/05/07/llms-and-games/
- 互动小说社区对 AI GM 的实践经验指出：世界模型应作为系统输入和结构化状态存在，不能只靠聊天上下文维持长期一致性：https://intfiction.org/t/does-anyone-use-ai-game-masters-for-solo-storytelling-curious-about-long-term-coherence/77309

可学习的成熟经验：

- **RimWorld**：玩家喜欢的不是随机灾难，而是“紧张曲线”。系统应知道什么时候给玩家喘息、什么时候制造危机。
- **Crusader Kings**：玩家会爱上人物、家族、背叛和偶然性。大战略不能只有国家数值，还要有人物关系和可记忆事件。
- **Dwarf Fortress**：世界即使没有玩家也应运转。玩家介入的是一个已有历史和内部因果的世界。
- **AI Dungeon**：自由输入是强卖点，但必须有记忆、边界、重试和纠错机制，否则会变成“会聊天但不成游戏”。
- **Total War / Paradox 系列**：长期目标要清晰，短期反馈要具体。玩家需要知道“我为什么赢/输”，而不是只看一段漂亮文本。

## 3. 当前问题诊断

参考 `logs/2026-05-23-caocao.txt`：

玩家输入包含复杂战略：

- 以皇帝旗帜重建合法性
- 识别诸侯各怀鬼胎
- 争取民众力量
- 用统一市场叙事说服百姓和商旅

当前反馈却被压扁为：

- 减免赋税
- 兴修水利
- 民心/经济/兵力数值变化

核心问题：

1. **玩家意图没有被充分解析**：一段战略文本被归入单一模板。
2. **缺少即时反馈**：玩家输入后直接进入季度结算，没有“军师理解/建议/风险提示”。
3. **LLM 与规则边界不清**：AI 模式中 LLM 可直接输出完整世界状态，长期容易数值漂移。
4. **世界模型维度偏薄**：兵力、经济、民心、资金、粮草不足以承载历史政治战略。
5. **NPC 行动动机不足**：NPC 像新闻播报，不像有目标、恐惧、记忆和机会判断的势力。

## 4. 产品目标

### 4.1 北极星体验

玩家输入一句复杂战略后，应获得这样的感受：

> 游戏真的理解了我的政治意图，并把它转化成了历史世界中的制度、人物、资源、风险和连锁反应。

### 4.2 核心玩家承诺

- 你可以用自然语言治理国家、发动战争、劝降诸侯、改革制度。
- 世界不是模板回复，而是带着历史惯性持续运转。
- 每个季度都会告诉你：你的战略被如何理解、为什么产生这些后果、谁因此受益或受损。
- 你不是在选 A/B/C，而是在与一个 AI 幕府共同推演历史。

### 4.3 MVP 成功标准

在 AI 模式下，玩家连续游玩 10 个季度后：

- 能指出至少 3 个“我上次的决策影响了现在局势”的例子。
- 能感受到至少 2 个 NPC 势力有连续目标，而不是随机行动。
- 愿意截图或复制一段军师反馈/天下大事分享给别人。
- 不需要阅读代码或文档，就能理解当前局势和可行战略。

## 5. PRD 优化方案

### 5.1 新增核心模块：军议反馈

在每次玩家输入后、世界推演前，展示一个 `Advisor Feedback` 区块。

中文标题建议：

- `军议反馈`
- `幕府参议`
- `军师进言`

内容结构：

```json
{
  "advisor_feedback": {
    "understanding": "模型如何理解玩家战略",
    "strategic_read": ["政治含义", "经济含义", "外交含义"],
    "risks": ["可能激怒袁绍", "财政短期承压"],
    "recommended_execution": ["先在许昌试点市令", "遣使安抚士族"],
    "clarifying_question": null
  }
}
```

CLI 展示建议：

1. Header
2. `军议反馈`
3. Narrative
4. Aftermath
5. NPC Actions
6. Events
7. Choices

设计原则：

- 反馈不是复述玩家原话，而是解释其战略层次。
- 必须指出至少一个风险或代价。
- 必须给出本季度可执行落点。
- 不应每次都问玩家确认；只有输入含糊或过大时才追问。

### 5.2 玩家输入解析

新增 `ParsedOrders`，将自然语言拆为多个行动，而不是单 intent。

示例：

```json
{
  "orders": [
    {
      "domain": "legitimacy",
      "action": "use_emperor_as_unifying_symbol",
      "target": "common_people_and_warlords",
      "intensity": 0.7
    },
    {
      "domain": "economy",
      "action": "promote_unified_market_narrative",
      "target": "merchants_refugees_local_elites",
      "intensity": 0.6
    },
    {
      "domain": "intelligence",
      "action": "investigate_warlord_intentions",
      "target": "coalition_warlords",
      "intensity": 0.5
    }
  ]
}
```

领域枚举建议：

- `military`
- `economy`
- `diplomacy`
- `legitimacy`
- `governance`
- `intelligence`
- `personnel`
- `propaganda`
- `infrastructure`
- `law_and_order`

### 5.3 增强世界状态

当前玩家状态：

- strength
- economy
- morale
- treasury
- food
- territories

建议新增：

- `legitimacy`: 合法性，影响称帝、奉天子、联盟号召。
- `elite_support`: 士族/豪强支持，影响治理效率和征粮。
- `merchant_support`: 商旅支持，影响贸易、情报和财政。
- `administration`: 行政能力，影响政策执行上限。
- `public_order`: 治安，影响流民、叛乱、税收。
- `refugees`: 流民数量或压力，既是风险也是兵源/劳力。
- `intel`: 情报能力，决定玩家看到的 NPC 信息质量。
- `war_exhaustion`: 战争疲惫，限制连续征战。

领地状态建议新增：

- population
- farmland
- trade_routes
- local_elites
- unrest
- tax_efficiency
- recruitment_pool
- supply_capacity

人物状态建议新增：

- ambition
- loyalty
- relationship_edges
- current_assignment
- faction_preference
- reputation_tags

### 5.4 历史事件设计

不要把“历史事件 50% 发生”写死为随机概率。改成：

```json
{
  "event_id": "dong_zhuo_moves_capital",
  "historical_date": "190_autumn",
  "historical_gravity": 0.9,
  "triggers": [
    "dongzhuo_controls_luoyang",
    "coalition_pressure_high",
    "dongzhuo_not_defeated"
  ],
  "mutation_conditions": [
    "player_blocks_hangu_pass",
    "sun_jian_captures_luoyang_early",
    "emperor_rescued"
  ],
  "possible_outcomes": [
    "historical",
    "delayed",
    "prevented",
    "worse_massacre",
    "emperor_seized_by_player"
  ]
}
```

这会把“历史真实性”变成系统惯性，而不是模板时间表。

### 5.5 NPC 势力模型

每个 NPC 应有战略目标栈：

```json
{
  "faction_id": "yuanshao",
  "grand_goal": "dominate_north_china",
  "current_objectives": [
    "secure_ji_province",
    "avoid_direct_loss_against_dongzhuo",
    "keep_coalition_leadership"
  ],
  "fears": ["caocao_controls_emperor", "gongsunzan_expands_south"],
  "attitude_to_player": {
    "trust": 35,
    "threat": 50,
    "respect": 60
  }
}
```

NPC 每回合行动应由以下因素决定：

- 自身目标
- 当前资源
- 对玩家威胁评估
- 历史性格
- 近期事件记忆
- 可见情报，而非全知

### 5.6 玩家可控性与透明度

玩家喜欢“复杂”，但不喜欢“黑箱”。每次回合报告应有清晰因果链：

```text
因为你提出“统一市场”：
- 商旅支持 +6：许昌商贾愿意资助驿道修复
- 士族支持 -2：部分豪强担心郡县权力被削弱
- 资金 -300：设市令、护商队需要初始开销
- 情报 +3：商旅开始回报道路与诸侯动向
```

## 6. Tech Design 优化方案

### 6.1 推荐架构

```text
Player Input
  -> Intent Parser (LLM, structured)
  -> Advisor Feedback (LLM, non-mutating)
  -> Action Validator (rules)
  -> Simulation Kernel (rules + stochastic)
  -> NPC Planner (rules/LLM hybrid)
  -> Narrative Renderer (LLM)
  -> State Validator
  -> Save
```

关键原则：

- LLM 擅长理解、解释、叙事、规划候选项。
- 规则引擎拥有最终世界状态写入权。
- 所有 state delta 必须可验证、可裁剪、可回放。

### 6.2 新增数据对象

```python
class ParsedOrder(BaseModel):
    domain: Literal[
        "military", "economy", "diplomacy", "legitimacy",
        "governance", "intelligence", "personnel",
        "propaganda", "infrastructure", "law_and_order"
    ]
    action: str
    target: str | None
    intensity: float
    expected_cost: dict[str, int] = {}
    expected_benefit: dict[str, int] = {}

class AdvisorFeedback(BaseModel):
    understanding: str
    strategic_read: list[str]
    risks: list[str]
    recommended_execution: list[str]
    clarifying_question: str | None = None

class StateDelta(BaseModel):
    faction_id: str
    changes: dict[str, int | float | str | list]
    causes: list[str]
    confidence: float
```

### 6.3 LLM 调用分层

MVP 可先用 2 次调用：

1. `analyze_player_decision`
   - 输入：当前世界状态、最近记忆、玩家输入。
   - 输出：`ParsedOrders` + `AdvisorFeedback`。
   - 不修改状态。

2. `generate_turn_report`
   - 输入：世界状态、已验证 orders、规则引擎 delta、NPC actions。
   - 输出：叙事、后果说明、下一步选项。
   - 不直接覆盖核心状态。

后续高级模式可加：

3. `npc_planner`
   - 为主要 NPC 生成候选行动。
   - 规则层评估并采样。

4. `event_mutation_judge`
   - 判断历史事件是否延迟、变体或取消。

### 6.4 防止 LLM 失控

必须做：

- Pydantic 校验所有结构化输出。
- 对数值变化设置上限，例如单季度经济最多 +/-8，兵力最多按人口/粮草裁剪。
- 保存 `pre_state`, `orders`, `deltas`, `post_state`，方便复盘和测试。
- LLM 不允许直接删除势力、吞并领土、杀死重要人物；必须通过事件或战役 resolver。
- 长文本叙事不可作为状态来源，只能展示。

### 6.5 记忆系统

记忆分三层：

- **短期记忆**：最近 5-8 回合，给 LLM 原文。
- **中期摘要**：每年总结，记录玩家战略倾向、盟友/敌人、关键承诺。
- **结构化长期记忆**：人物关系、条约、仇恨、改革、历史偏离。

示例：

```json
{
  "player_doctrine": ["奉天子重建合法性", "安置流民", "以商贸整合民心"],
  "promises": [
    {"to": "refugees", "content": "授田与农闲教育", "status": "partially_fulfilled"}
  ],
  "rival_perceptions": {
    "yuanshao": "曹操有挟天子野心，需防范",
    "dongzhuo": "曹操正在争夺民心，威胁渐增"
  }
}
```

### 6.6 CLI 体验变更

新增面板：

```text
╭─ 幕府参议 ─────────────────────────╮
│ 荀彧以为：主公此策不止安民，实为以天子名义重建秩序... │
│ 风险：袁绍或疑主公欲夺盟主之名；许昌豪强或反对统一市令。 │
│ 本季可行：先设护商道、平粮价、招流民屯田。             │
╰────────────────────────────────────╯
```

命令建议：

- `/state`: 查看完整状态。
- `/why`: 解释上一回合数值变化原因。
- `/undo`: AI 模式可回滚上一回合，降低 LLM 错误挫败感。
- `/retry`: 重新生成叙事，不改状态。
- `/save-note`: 玩家自定义战略笔记，进入记忆。

## 7. 运营策略

### 7.1 冷启动人群

优先级：

1. 开发者/AI 产品爱好者：喜欢 CLI、开源、可 hack。
2. 三国策略玩家：关心真实历史、势力平衡、人物性格。
3. 文本 RPG / solo RPG 玩家：关心自由输入和 AI GM。
4. 历史内容创作者：适合直播、战报、二创。

### 7.2 内容包装

核心传播语：

- “在终端里和一个 AI 幕府一起改写三国。”
- “不是选择 A/B/C，而是用自然语言治国、用制度影响历史。”
- “开源的 AI 文本历史大战略。”

适合传播的内容形式：

- 战报帖：`曹操不挟天子，改走商贸统一路线会怎样？`
- 对比视频：`模板式历史游戏 vs AI 原生世界模型`
- 开发日志：展示一次玩家长文本如何被解析成 orders、反馈、delta。
- 社区挑战：`不用屠徐州，曹操能不能统一北方？`

### 7.3 社区机制

- GitHub Issues 使用模板：bug / historical accuracy / scenario idea / prompt issue。
- 每周发布一个“玩家战报精选”。
- 支持玩家贡献历史事件 JSON、人物 profile、地方资源数据。
- 后续支持 mod scenarios：春秋、战国、楚汉、安史、明末、罗马。

### 7.4 商业化建议

短期不要强调 token 收费。对开源用户最友好的路线：

- CLI 核心免费，用户自带 API key。
- 后续 Web 托管版提供可选订阅：云存档、多设备、内置模型额度。
- 剧本 DLC 可商业化，但核心三国 190 剧本保持免费。
- Steam 版卖打包体验，不卖“抽卡式 token”。

## 8. 测试计划

### 8.1 单元测试

新增测试：

- `test_parse_player_orders.py`
  - 长文本可拆出多个 orders。
  - 输入含糊时能给 clarifying_question。
  - 不把所有政策都归类为 economy。

- `test_advisor_feedback.py`
  - 必须引用或概括玩家核心意图。
  - 必须包含风险。
  - 不修改世界状态。

- `test_state_delta_limits.py`
  - 单季度数值变化不超上限。
  - 粮草不足时不能无限征兵。
  - 民心、经济等保持 0-100。

- `test_historical_event_conditions.py`
  - 董卓迁都在默认条件下发生。
  - 玩家提前控制关键关隘时事件变体。
  - 历史偏离被记录。

### 8.2 Golden Transcript 测试

维护一组固定输入和预期结构，不要求叙事完全一致，但要求：

- 识别出的战略领域一致。
- 数值变化方向合理。
- NPC 反应符合人物目标。
- 事件触发条件可解释。

建议文件：

- `tests/fixtures/transcripts/caocao_legitimacy_market.json`
- `tests/fixtures/transcripts/liubei_refugee仁政.json`
- `tests/fixtures/transcripts/sunjian_aggressive_luoyang.json`

### 8.3 模拟回归测试

每天或每次 release 前跑自动模拟：

- 4 个势力，各 20 回合。
- 随机生成但有主题的玩家策略。
- 检查：
  - 无崩溃。
  - 无负数资源。
  - 无一年内统一天下。
  - 关键人物不无因死亡。
  - 历史偏离曲线不突然爆炸。

### 8.4 LLM 质量评测

人工/半自动打分维度：

- 意图理解：1-5
- 历史可信度：1-5
- 因果解释：1-5
- 玩家掌控感：1-5
- 叙事可读性：1-5
- 重复度：1-5，越低越好

每个版本至少收集 20 段玩家输入做回归。

### 8.5 玩家测试

首轮 10 人测试：

- 3 名开发者
- 3 名三国/历史策略玩家
- 2 名 AI 文本游戏玩家
- 2 名普通玩家

观察指标：

- 第一次输入是否知道该说什么。
- 是否理解“军议反馈”和“季度结算”的区别。
- 是否觉得 AI 真正回应了自己。
- 是否愿意继续玩到第 5 回合。
- 哪些输出被认为“像模板”。

## 9. 分阶段实施计划

### Sprint 1: 军议反馈 MVP

目标：

- 新增 `advisor_feedback` 结构。
- CLI 展示 `幕府参议` 面板。
- LLM 模式先支持；离线模式可用规则模板生成简版。

验收：

- 曹操“皇帝旗帜 + 统一市场”输入能得到政治/经济/风险反馈。
- 不改变现有存档格式或提供迁移默认值。

### Sprint 2: Parsed Orders

目标：

- 玩家输入拆为 2-5 条 orders。
- Aftermath 从 orders 和 delta 生成，减少模板化。

验收：

- 复杂输入不再被压成单一内政行动。
- `/why` 可以解释每个 delta 的来源。

### Sprint 3: 世界状态扩展

目标：

- 增加 legitimacy、elite_support、merchant_support、administration、public_order、intel、war_exhaustion。
- 更新存档迁移和显示。

验收：

- 政治合法性路线与军事扩张路线有不同反馈。
- 商贸、流民、士族支持能影响后续事件。

### Sprint 4: NPC 目标与历史事件条件化

目标：

- NPC 有目标栈和对玩家态度。
- 历史事件从时间表升级为条件触发。

验收：

- 袁绍会连续追求冀州和盟主权威。
- 董卓迁都可延迟、恶化或被玩家改变。

## 10. 关键决策

建议现在就定下：

1. **产品类型**：AI-powered text-based historical grand strategy game。
2. **AI 职责**：理解、建议、叙事、候选规划；不直接拥有最终状态写入权。
3. **体验优先级**：先让玩家觉得“被理解”，再追求更大世界。
4. **世界模型策略**：逐步扩维，不一次性做 Paradox 级模拟。
5. **运营路线**：开源 CLI 获取开发者和 AI 玩家，战报内容获取三国玩家。

## 11. Open Questions

Resolved 2026-05-24:

- 是否允许玩家在军议反馈后修改命令，再正式推演？
  - **Decision: Yes.** 下一步应支持“先军议、后确认执行”的两段式回合。玩家可以接受、修改或取消幕僚理解后的命令。
- 是否需要设定不同军师人格，例如荀彧稳健、郭嘉冒险、贾诩阴狠，让反馈风格可选？
  - **Decision: Yes.** 后续可把 advisor persona 做成可选幕僚：荀彧偏稳健治理，郭嘉偏奇谋冒险，贾诩偏保命与阴谋。
- 是否要为新玩家提供“短令模式”，例如一句话输入即可，不强迫长文本？
  - **Decision: Yes.** 保留自然语言长令，同时支持一句话短令和编号选项，降低新玩家门槛。
- AI 成本目标是多少？每回合 1 次、2 次、还是高级模式 4 次调用？
  - **Decision: 当前每回合 1 次。** 以后再区分幕僚讨论的 `planning` 和对外落地的 `execution`。
- 是否要保留纯离线模式作为完整可玩游戏，还是定位为 demo/fallback？
  - **Decision: 纯离线模式作为 fallback。** 它适合无 Key、网络失败和自动测试，但不应被包装成主要吸引点；核心体验应围绕 AI 模式。

New follow-up:

- 如何在“每回合 1 次 AI 调用”的成本目标下实现“先军议、后确认执行”？候选方案：一次调用同时产出 advisor_feedback 和 proposed_orders，玩家确认后规则层执行；若玩家修改，则本回合用规则解析修改文本，下一 sprint 再做第二次 AI 精修。
