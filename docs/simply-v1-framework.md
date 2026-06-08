# 混合架构框架：确定性引擎 × LLM 叙事层

**版本**: v1.0
**日期**: 2026-06-08
**作者**: Prometheus (Hermes Agent)
**状态**: 草案 — 待 Julian 审阅

---

## 一、为什么需要这个框架

### 崇祯模拟器的教训

```
崇祯模拟器架构:
  玩家输入 → LLM → 输出文本
              ↑
         数值系统（被忽略）

结果: AI 说「陛下圣明」，赋税已经 90% 了。
      — 55% 好评，1,679 条差评
```

### 纯仿真的局限

```
纯仿真架构:
  玩家输入 → 关键字匹配 → 固定操作映射 → 数值更新 → 模板叙事

结果: 「围魏救赵，联孙权牵制曹操北方」
      → 关键字匹配找不到「围魏救赵」
      → 无法映射到操作
      → 玩家挫败
```

### 我们的答案：双层架构

```
混合架构:
  玩家输入 → LLM 理解意图 → 确定性引擎计算 → LLM 叙事包装 → 输出

  玩家: 「围魏救赵，联孙权牵制曹操北方」
  LLM:  理解了 → intent: {military: 牵制, diplomacy: 联孙, target: 曹操}
  引擎: 算孙权的兵力、曹操被牵制后的减员、行军路径
  LLM:  «刘景升密使至建业，孙权闻之大喜，即令周瑜率水师北上…»
```

**引擎管对错。LLM 管好看。**

---

## 二、框架定义：SimPly（Simulation + LLM Pipeline）

### 2.1 命名

**SimPly** = Simulation + LLM Pipeline

一个开放框架，用于构建「物理正确、叙事生动」的 AI 驱动生成式游戏。

### 2.2 核心架构

```
                           ┌──────────────────────────┐
                           │     SimPly 框架           │
                           │                          │
  ┌──────────┐             │  ┌────────────────────┐  │
  │ 玩家输入  │─────────────▶│  LLM Intent Parser  │  │
  │(自然语言) │             │  │ 理解意图→结构化命令  │  │
  └──────────┘             │  └────────┬───────────┘  │
                           │           │              │
                           │           ▼              │
                           │  ┌────────────────────┐  │
                           │  │  Validation Layer   │  │
                           │  │ 命令校验→参数补全     │  │
                           │  └────────┬───────────┘  │
                           │           │              │
                           │           ▼              │
                           │  ┌────────────────────┐  │
                           │  │  Simulation Layer   │  │
                           │  │ ┌────────────────┐  │  │
                           │  │ │ Physics Engines │  │  │
                           │  │ │ · Map/Geo       │  │  │
                           │  │ │ · Economy       │  │  │
                           │  │ │ · Military      │  │  │
                           │  │ │ · Politics      │  │  │
                           │  │ │ · Population    │  │  │
                           │  │ │ · NPC AI        │  │  │
                           │  │ │ · Climate       │  │  │
                           │  │ └────────────────┘  │  │
                           │  │        │            │  │
                           │  │        ▼            │  │
                           │  │  World State        │  │
                           │  │  (可序列化快照)      │  │
                           │  └────────┬───────────┘  │
                           │           │              │
                           │           ▼              │
                           │  ┌────────────────────┐  │
                           │  │  LLM Narrative Layer│  │
                           │  │  State → Prompt     │  │
                           │  │  → 沉浸式叙事        │  │
                           │  └────────┬───────────┘  │
                           │           │              │
                           └───────────│──────────────┘
                                       ▼
                                  ┌──────────┐
                                  │ 玩家输出  │
                                  │(叙事+地图) │
                                  └──────────┘
```

### 2.3 分层职责

| 层 | 职责 | 确定性 | 举例 |
|---|---|---|---|
| **Intent Parser** | 自然语言 → 结构化命令 | ❌ LLM | 「围魏救赵」→ `{type:attack, target:宛城, strategy:牵制}` |
| **Validation** | 命令合法性检查 | ✅ 规则 | 兵力够不够？目标邻接吗？ |
| **Simulation** | 世界状态更新 | ✅ 纯数学 | 兰彻斯特方程、对数发展公式、威胁评估 |
| **Narrative** | 沉浸式故事 | ❌ LLM | 「曹孟德亲率虎豹骑，旌旗蔽日…」 |
| **World State** | 完整世界快照 | ✅ JSON | 所有领地、人物、军队、外交关系的可序列化表示 |

### 2.4 关键原则

1. **不可变性边界**：LLM 只能读取 World State，不能修改它。所有修改走 Simulation Layer。
2. **可复现性**：同一 World State + 同一 Command → 同一结果。LLM 不参与计算。
3. **API 无关**：框架与具体 LLM provider 解耦。玩家可用自己的 key。
4. **多端一致**：CLI/Web/IM 共享同一条 Simulation → Narrative 管线。差异仅在渲染。

---

## 三、SimPly 游戏循环（形式化定义）

```
TURN LOOP (formal):

1. Climate.roll(world_state)                    → climate_events
2. Economy.produce(world_state)                  → resource_deltas
3. NPC_AI.decide(world_state)                    → npc_commands[]
4. Player.input()                                → natural_language_text
5. LLM.parse_intent(text, world_snapshot)        → intent{action, params}
6. Validator.validate(intent, world_state)       → command (validated)
7. Simulator.execute(command)                    → result{success, deltas}
8. Simulator.execute_all(npc_commands)            → npc_results[]
9. ConflictResolver.resolve(world_state)          → battle_results[]
10. WorldState.advance()                          → next_turn_state
11. LLM.narrate(result, npc_results, battles)    → narrative_text
12. Renderer.render(narrative, world_snapshot)   → player_output
```

步骤 1-4 和 6-10 是**确定性的**。
步骤 5 和 11 是**LLM 驱动的**，但它们的输出不改变世界状态——只改变呈现。

---

## 四、通用性：超越三国

### 4.1 SimPly 不是三国引擎，是世界模拟器

```
SimPly 核心 = 通用游戏框架
histrategy-engine = SimPly 的一个实例（三国皮肤）

未来实例:
  · 崇祯模拟器（明末）
  · 战国七雄
  · 罗马元老院
  · 中世纪领主
  · 科幻星际帝国
```

### 4.2 换皮只需换三样

| 组件 | 三国实例 | 崇祯实例（假设） |
|------|---------|----------------|
| **Knowledge Base** | `histrategy-knowledge/` JSON | `ming-knowledge/` JSON |
| **LLM System Prompt** | 三国世界观 | 明末世界观 |
| **UI 渲染** | 汉风 Feishu 卡片 | 明风 Feishu 卡片 |

**引擎层完全不变。** Map、Economy、Military、NPC AI 是通用的——兰彻斯特方程在三国和明末都适用。

---

## 五、与崇祯模拟器的架构对比

| 维度 | 崇祯模拟器 | SimPly |
|------|-----------|--------|
| **游戏逻辑** | LLM 生成 | 确定性引擎 |
| **数值一致性** | ❌ 与叙事脱节 | ✅ 引擎保证 |
| **可复现性** | ❌ 每次不同 | ✅ 同一输入同一结果 |
| **NPC 行为** | LLM 扮演 | 人格权重 + 威胁评估 |
| **历史数据** | LLM 记忆 | JSON 知识库 |
| **API 依赖** | 锁死内置 | 玩家自带 key |
| **多人** | ❌ | ✅ 群聊共享世界 |
| **平台** | Steam/Windows | Web+Feishu+CLI+更多 |
| **开源** | ❌ 闭源 | ✅ MIT |
| **技术壁垒** | UI 包装 | 引擎数学 |

---

## 六、开发路线图

### Phase 1: 夯实引擎（当前—2026年6月）

- [x] 7 个引擎模块（Map, Military, Economy, Character, AI, Turn, Diplomacy）
- [x] NPC AI 上线（人格权重 + 威胁评估）
- [x] 自动征税
- [x] LLM intent 解析 + 叙事生成
- [x] 351 tests
- [ ] 地图数据完善（关中、西凉、辽东、交州）
- [ ] 角色数据库扩充（黄忠、魏延、诸葛亮、马超…）
- [ ] 世家/民心/正统性指标
- [ ] 屯田/流民/贸易机制

### Phase 2: 多端上线（2026年7月）

- [ ] Web 端统一到 engine 架构（弃用纯 LLM 路径）
- [ ] Feishu 群聊多人模式
- [ ] OpenClaw skill 发布
- [ ] 可分享存档码
- [ ] 主播模式（观战 + 弹幕指令）

### Phase 3: 框架化（2026年8月）

- [ ] `simply-core` pip 包（通用游戏框架）
- [ ] `simply-knowledge` 知识库标准格式
- [ ] 换皮文档：如何基于 SimPly 构建你自己的历史游戏
- [ ] 第二个实例：崇祯模拟器 v2（用 SimPly 重写）

### Phase 4: 社区与生态（2026年9月+）

- [ ] GitHub Discussions + Discord
- [ ] 社区贡献的剧本/角色/事件
- [ ] SimPly 插件市场
- [ ] 学术合作（多智能体行为经济学仿真）

---

## 七、运营传播策略

### 7.1 定位矩阵（看人下菜）

| 受众 | 传播语 | 渠道 |
|------|--------|------|
| **开发者** | 「MIT 开源——确定性引擎 × LLM 叙事，用自然语言构建你自己的历史世界」 | GitHub, Hacker News, V2EX |
| **策略玩家** | 「围魏救赵真的有兵力计算——不是AI随便编的」 |  Steam, B站, 知乎 |
| **历史爱好者** | 「208年的诸葛亮真的在隆中——你可以去请」 |  B站, 小红书, 历史类公众号 |
| **学术** | 「多智能体行为经济学仿真平台——可控实验、可复现结果」 | arXiv, 学术会议 |
| **大众** | 「在飞书群里和朋友一起玩三国」 | 朋友圈, 群聊传播 |

### 7.2 传播飞轮

```
存档码分享 → 主播直播 → 观众试玩 → 生成新存档码 → 更多主播 → …
```

核心载体：**Web 端一键生成分享链接**。「来试试我的刘表存档，曹操已经灭了，看你能不能统一天下」。

### 7.3 定价策略

| 层 | 价格 | 内容 |
|---|---|---|
| 开源版 | 免费 | 完整引擎 + CLI + 自带 API key |
| 托管版 | ¥29/月 | Web 端 + 共享 LLM + 云端存档 |
| 企业/学术 | 定制 | 私有部署 + 定制剧本 + SLA |

**绝不锁 API。绝不赚 Token 差价。** 这是崇祯模拟器踩过的最大坑。

---

## 八、这个框架为什么是「跨时代」的

### 8.1 解决了什么问题

当前所有「AI 游戏」都是同一个模式：

```
玩家输入 → LLM → 输出文本
```

这是**聊天机器人套皮**，不是游戏。SimPly 建立了一条新路：

```
玩家输入 → LLM 理解 → 引擎计算 → LLM 叙事
```

**LLM 是接口层，不是游戏层。** 这是生成式游戏从「玩具」到「产品」的跃迁。

### 8.2 可以成为什么

如果 SimPly 被社区接受：

- 它将成为 **LLM 驱动游戏的 MVC 框架**——就像 Rails 之于 Web 开发
- 任何想用「历史模拟+AI叙事」做游戏的人，不用从零写引擎
- 换皮 = 换知识库 + 换 prompt，三天出原型
- 学术领域：可控实验、可复现的仿真平台

### 8.3 竞争壁垒

| 壁垒 | 为何难复制 |
|------|-----------|
| 7 引擎数学 | 兰彻斯特、对数公式、A*寻路、人格权重——不是调 prompt 能解决的 |
| JSON 知识库 | 数百条历史事件、人物关系、地理数据的结构化和验证 |
| 多人状态同步 | 群聊共享世界的一致性协议 |
| 可复现性 | 「同一输入同一结果」——这是学术和竞技的基础 |

---

## 九、决策记录

- **2026-06-08**: 确定 SimPly 框架方向。命名 = Simulation + LLM Pipeline。
- **核心决策**: 不做纯仿真（太死），不做纯 LLM（太飘），走混合架构。
- **差异化**: 确定性引擎是崇祯模拟器最缺的东西，也是我们最大的壁垒。
- **开源策略**: MIT 协议。API key 由用户自带。不赚 Token 差价。
