# PRD: OpenClaw / Hermes Integration

> **Status**: Draft v0.1 — Design Phase
> **Owner**: Symbol Science
> **Date**: 2026-05-24

---

## 1. Executive Summary

### 1.1 一句话定位

> **将三國志略游戏引擎包装为 OpenClaw/Hermes Agent Skill，玩家通过 Discord、飞书等 IM 渠道与 AI 游戏主持实时互动，在聊天中运筹帷幄、改变历史。**

### 1.2 核心价值

目前三國志略是一个单机 CLI 应用 — 玩家打开终端、运行命令、在本地交互。这限制了受众和社交属性。

通过接入 OpenClaw/Hermes，游戏变为：

| Before (CLI) | After (Agent Skill) |
|---|---|
| 本地终端运行 | 任何 IM 渠道可玩 |
| 单人、无社交 | 群聊围观、多人协作决策 |
| 需要安装 Python | 零安装（加入频道即玩） |
| 无持久在线 | Agent 保持世界运行，可定时推送 |
| 文本仅本地显示 | 可渲染为 Rich card、图片、Markdown |

### 1.3 设计原则

- **Engine first, Channel second** — 游戏引擎与渠道解耦，引擎提供统一 API，渠道适配层做格式转换
- **Headless by default** — 游戏核心逻辑不依赖任何 CLI/TUI 库
- **Session-per-chat** — 每个 IM 会话/频道 = 一个独立游戏存档
- **Human-in-loop** — Plan/Command 双阶段天然适配异步消息交互

---

## 2. User Experience

### 2.1 玩家旅程 (via Discord)

```
1. 玩家加入 Discord 服务器
   └── 看到 #histrategy-lobby 频道，有使用说明

2. 开局
   玩家: /new-game 曹操
   Agent: 🎌 初平元年（190 AD），汉室倾颓，群雄逐鹿。
          [展示曹操势力初始状态卡片]
          [4个开局选项按钮]

3. 内政会议 (Plan Mode)
   Agent: 🏛️ 190年春季 · 内政会议
          荀彧（军师）🛡: "主公，董卓虽暴，但西凉铁骑..."
          夏侯惇（将军）⚔: "末将愿率精兵北上！"
          [1. 派使者结交袁绍] [2. 先发制人北上] [3. 发展内政] [4. 搜集情报]

4. 玩家决策
   玩家: 我选择方案1，派简雍去邺城稳住袁绍。
         同时命令曹仁加固许昌城防，务必在秋收前完工。
   Agent: ⚡ 政令执行中...
         [执行报告卡片]
         [后果：兵力+500，经济+2，民心+3]

5. 循环进行，异步推送
   第二天上午10:00:
   Agent: ☀️ 新的一天！190年夏季已至。
          昨夜军报：董卓焚烧洛阳，迁都长安！
          请主公速速决断。
```

### 2.2 IM 渠道适配

| 渠道 | 消息格式 | 交互方式 | 优先级 |
|------|---------|---------|--------|
| **Discord** | Embed/Card + Button | Slash command + 按钮点击 + 自由文本 | P0 |
| **飞书 (Feishu)** | 富文本卡片 + 按钮 | 机器人消息 + 按钮交互 + 自由文本 | P0 |
| **Telegram** | Markdown + Inline Keyboard | 指令 + 按钮 + 自由文本 | P1 |
| **Slack** | Block Kit | Slash command + Interactive Blocks | P1 |
| **微信企业** | Markdown + 模板卡片 | 文本指令 + 按钮 | P2 |

### 2.3 围观模式

群聊中的一个独特体验：**多人围观一人决策**。

```
玩家A（主公）: 我选择北伐！
围观者B: 🍿 刺激！袁绍八十万大军可不是吃素的
围观者C: 我觉得该选发展经济...
围观者D: 信主公，得永生 🙏

Agent 只接受玩家A的决策输入，但围观者的消息
增加了社交乐趣和「朝廷议政」的氛围。
```

---

## 3. Installation Model

### 3.1 作为 OpenClaw Skill 安装

```bash
# 从 ClawHub 安装 (推荐)
openclaw skill install histrategy

# 或从 GitHub 直接安装
openclaw skill install github.com/emergencescience/histrategy

# 配置
openclaw skill config histrategy set DEEPSEEK_API_KEY=sk-...
openclaw skill config histrategy set DATA_DIR=.openclaw/histrategy
```

**Skill 包结构**:
```
histrategy-skill/
├── SKILL.md              # OpenClaw skill 声明
├── package.json          # OpenClaw extensions 声明
├── openclaw.json         # Gateway channel 配置
├── histrategy/           # 游戏引擎（Python 包）
│   ├── engine/           # 头less 版游戏引擎
│   ├── llm/              # LLM 适配层
│   ├── state/            # 世界状态
│   └── channel/          # ★ 新增：渠道适配层
│       ├── base.py       # 抽象渠道接口
│       ├── discord.py    # Discord Embed/Button 渲染
│       ├── feishu.py     # 飞书卡片渲染
│       └── telegram.py   # Telegram Markdown+Keyboard 渲染
└── scripts/
    └── headless_server.py  # headless 引擎入口
```

### 3.2 作为 Hermes Agent Skill 安装

```bash
# Hermes CLI 安装
hermes skill install github.com/emergencescience/histrategy

# Hermes 使用 ACP (Agent Communication Protocol) 与引擎通信
```

---

## 4. Human-in-Loop Interaction Model

### 4.1 核心交互模式

三國志略天然是一个 Human-in-loop 游戏 — 每个回合需要玩家决策。这在 Agent Skill 框架中完美映射：

```
┌────────────────────────────────────────────────────────┐
│                   OpenClaw Gateway                      │
│  (Discord / Feishu / Telegram 消息收发)                 │
└────────────┬───────────────────────────────────────────┘
             │ message
             ▼
┌────────────────────────────────────────────────────────┐
│               Agent Core (OpenClaw / Hermes)             │
│  - 路由消息到 histrategy skill                          │
│  - 会话管理 (每个 channel = 一个 session)                │
│  - 权限控制 (谁可以决策 vs 谁只能围观)                    │
└────────────┬───────────────────────────────────────────┘
             │ dispatch
             ▼
┌────────────────────────────────────────────────────────┐
│              histrategy Headless Engine                  │
│  - GameEngine (无 CLI 依赖)                             │
│  - Plan Mode → 返回 Advisors + Suggestions              │
│  - Command Mode → 返回 Bureaucracy + Aftermath           │
│  - State persistence per session                        │
└────────────┬───────────────────────────────────────────┘
             │ structured result
             ▼
┌────────────────────────────────────────────────────────┐
│              Channel Adapter                             │
│  将结构化 game result 渲染为渠道适配的 UI 格式            │
└────────────────────────────────────────────────────────┘
```

### 4.2 回合状态机

```
          ┌──────────┐
          │  IDLE    │  等待玩家开始新游戏
          └─────┬────┘
                │ /new-game <faction>
                ▼
          ┌──────────┐
          │  INTRO   │  展示开局叙事
          └─────┬────┘
                │ 自动前进
                ▼
    ┌──────────────────────────────┐
    │          PLAN MODE            │
    │  - 展示季节摘要                │
    │  - 展示顾问发言                │
    │  - 展示4个战略选项（含按钮）     │  ◄── 玩家可回复 "plan" 重新进入
    │  - 等待玩家决策               │
    └──────────────┬───────────────┘
                   │ 玩家发送决策文本
                   ▼
    ┌──────────────────────────────┐
    │        COMMAND MODE           │
    │  - 显示 "政令执行中..."       │
    │  - LLM 推演后果               │
    │  - 展示官僚执行报告            │
    │  - 展示后果板 + 数值变化       │
    │  - 展示天下动向               │
    │  - 展示种子（长期影响）        │
    └──────────────┬───────────────┘
                   │ 自动前进
                   ▼
              回到 PLAN MODE (下一回合)

    任何时刻：
      /state  →  查看世界状态
      /history → 查看决策历史
      /plan   →  重新进入 Plan Mode
      /quit   →  退出游戏（保存存档）
```

### 4.3 决策授权模型

```
┌─────────────────────────────────────────┐
│ 决策权利模型（群聊场景）                   │
│                                         │
│  主公 (Player):                          │
│    - 唯一可以做出战略决策的人              │
│    - 通过 /new-game 成为主公             │
│    - 可以 /abdicate 禅让给他人            │
│                                         │
│  谋臣 (Advisors):                        │
│    - 可以发送消息但不会被当作命令          │
│    - Agent 会回复但不执行游戏指令          │
│    - 增加社交深度（模拟朝廷议事）           │
│                                         │
│  围观者 (Spectators):                     │
│    - 纯只读，可以看所有游戏内容             │
│    - 发消息被 Agent 忽略（关于游戏指令）    │
└─────────────────────────────────────────┘
```

---

## 5. New Features Unlocked by IM Integration

### 5.1 定时推送 (Cron / Scheduled Turns)

```
Agent 可以在设定时间主动推送：

"陛下，卯时已到。军师府已将昨夜军报整理完毕：
 - 袁绍使者已在驿馆等候三日
 - 许昌粮仓储备不足三月
 - 夏侯惇将军求见，言有要事相商

请陛下主持今日朝会。"
```

### 5.2 多人势力模式 (Multi-Faction)

```
同一服务器中，不同频道的不同玩家扮演不同势力：

#cao-cao-camp     → 玩家A 扮演曹操
#liu-bei-camp     → 玩家B 扮演刘备
#sun-jian-camp    → 玩家C 扮演孙坚

Agent 协调三个势力在同一世界中的互动：
外交、战争、联盟...一切都是玩家之间的博弈。
```

### 5.3 世界事件广播

```
#world-news 频道（所有玩家可见）:

⚡ 天下大事：
  - 董卓军焚烧洛阳，迁都长安
  - 曹操发布讨董檄文
  - 孙坚获得传国玉玺
  - 袁绍集结关东联军
```

---

## 6. MVP Scope

### Phase 0: Headless Engine (2-3 weeks)

- [ ] 从 `cli/app.py` 中剥离 game loop 到 `engine/game_loop.py`
- [ ] 所有 Rich TUI 代码保留在 `cli/` 中，引擎不再 import `rich`
- [ ] GameEngine 提供同步 API：`start_game()`, `process_turn(decision)`, `get_state()`
- [ ] 输出为结构化 dict（无任何格式化），渠道适配层负责渲染
- [ ] 现有 CLI 和测试套件不受影响（引擎 API 向后兼容）

### Phase 1: OpenClaw Skill Package (1-2 weeks)

- [ ] 编写 `SKILL.md` 和 `openclaw.json`
- [ ] 实现 Discord channel adapter
- [ ] 实现飞书 channel adapter
- [ ] Session-per-channel 状态管理
- [ ] 主公/谋臣/围观者权限模型
- [ ] Slash commands: `/new-game`, `/state`, `/history`, `/quit`

### Phase 2: Polish (1-2 weeks)

- [ ] 定时推送（Cron integration）
- [ ] 多人势力模式（cross-channel game state）
- [ ] 世界事件广播 channel
- [ ] Telegram / Slack adapters
- [ ] 安装文档 + 演示视频

---

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Discord 服务器安装 | 50+ servers in first month |
| 飞书机器人安装 | 30+ orgs in first month |
| 单局平均回合数 | 15+ turns |
| 围观/决策比 | 3+ 围观者 per active player |
| LLM 延迟 (Plan Mode) | <10s |
| LLM 延迟 (Command Mode) | <15s |
