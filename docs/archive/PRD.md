# PRD: 三國志略 (Histrategy)

> **Status**: Draft v0.2 — Plan/Command Architecture
> **Owner**: Prometheus (Hermes Agent)
> **Strategic Sponsor**: @Host-MY
> **Date**: 2026-05-23

---

## 1. Executive Summary

### 1.1 一句话定位

> **一个开源、AI驱动的历史策略游戏——玩家主持内政会议制定战略方向，通过官僚系统执行政令，AI实时推演世界变化。**

### 1.2 核心创新

**Plan/Command 双模式架构** — 区分"决策什么"和"如何执行"：

| 模式 | 目的 | 输入方式 | AI角色 |
|------|------|---------|--------|
| **Plan Mode (内政会议)** | 确定战略方向 | 顾问建议 + 自由文本可选 | 各顾问给出视角 |
| **Command Mode (政令执行)** | 执行并推演 | 自动（Plan 决定的策略） | 官僚模拟 + 世界推演 |

### 1.3 设计哲学

基于 Nottingham (UCI 2024) 的 LLM-Game 框架和 AI Dungeon 的经验：

- **Guided Freedom**：AI 生成建议选项 + 玩家可自由输入（解决"空白输入框恐惧"）
- **Selective Grounding**：仅相关状态信息进入 LLM 上下文，不 dump 全部
- **Two-tier AI**：结构性决策（菜单）+ 战术执行（自由文本）
- **Seed System**：长期后果种下后在未来回合才触发

---

## 2. 游戏流程

### 2.1 完整回合循环

```
1. 内政会议 (Plan Mode)
   ├── 各顾问发言（荀彧/夏侯惇/郭嘉/荀攸等）
   ├── 4个AI生成的战略建议
   └── 玩家选择建议或输入自由文本

2. 政令执行 (Command Mode)
   ├── 军师府评估可行性
   ├── 各部门执行报告（户部/兵部/鸿胪寺）
   ├── 短期后果（本季数值变化）
   ├── 种子（长期后果，未来触发）
   └── NPC 势力反应

3. 天下动向
   ├── 其他势力行动
   └── 重大历史事件触发（~50%历史对齐）
```

### 2.2 顾问系统

每个势力有4位顾问，各有独特人格：

| 势力 | 军师 | 将军 | 谋士 | 内政官 |
|------|------|------|------|--------|
| 曹操 | 荀彧 🛡 | 夏侯惇 ⚔ | 郭嘉 🕵 | 荀攸 📋 |
| 刘备 | 简雍 🤝 | 关羽 🐉 | 张飞 ⚔ | 孙乾 📋 |
| 孙坚 | 程普 🛡 | 黄盖 ⚔ | — | 朱治 📋 |
| 袁绍 | 田丰 🛡 | 颜良 ⚔ | 许攸 🕵 | 审配 📜 |

---

## 3. 技术架构

### 3.1 组件图

```
CLI Layer
├── Rich TUI (histrategy)
└── Dev CLI (histrategy --dev)

Game Engine
├── Plan Mode → advisors.py (顾问生成 + 建议)
├── Command Mode → command.py (官僚执行 + 种子)
├── World State → state/world_state.py (JSON持久化)
└── Offline Fallback → offline_sim.py (模板引擎)

LLM Layer
├── LLM World Model → llm/world_model.py
└── Multi-Provider → llm/adapter.py

Knowledge Base
├── characters.json (人物+性格)
├── factions.json (势力+倾向)
├── regions.json (地域+资源)
└── events.json (历史事件)
```

### 3.2 状态存储

```
~/.histrategy/
├── world_state.json        # 当前世界状态
├── player_memory.json      # 决策历史
├── relationships.json      # 势力关系图谱
├── event_history.json      # 事件日志
└── pending_seeds.json      # 待触发的长期后果
```

### 3.3 LLM 调用模式

| 阶段 | 温度 | 输入 | 输出 |
|------|------|------|------|
| 顾问生成 | 0.7 | 当前状态 | JSON: advisors, suggestions |
| 后果模拟 | 0.8 | 玩家决策 | JSON: state_changes, narrative |
| NPC行动 | 0.6 | 世界状态 | JSON: npc_actions |

---

## 4. MVP 范围 (Phase 0)

### 已实现 ✅

- [x] Plan/Command 双模式（离线版）
- [x] 4个势力的顾问系统
- [x] 4个动态战略建议/轮
- [x] 官僚执行报告
- [x] 长期种子系统
- [x] 自动存档/读档
- [x] Dev 模式 (--dev)
- [x] 43个自动化测试
- [x] 多 Provider LLM 支持 (DeepSeek/OpenAI/通义千问/OpenRouter)

### 待实现 📝

- [ ] LLM World Model 版本（需要 DeepSeek API Key 验证）
- [ ] 顾问忠诚度系统（背叛/内斗）
- [ ] Court faction dynamics（主战派vs稳健派）
- [ ] Web UI
- [ ] Steam 发行

---

## 5. 测试策略

- **单元测试**: 43个测试覆盖所有核心函数
- **E2E测试**: 自动化脚本 scripts/e2e_experience.py
- **质量门禁**: Plan Mode显示顾问、Command Mode显示执行、无英文地名、无语义数字
- **回归测试**: 每次提交前运行 `pytest tests/`

---

## 6. 营销策略

### 冷启动渠道
1. **知乎** — 已发布 [2041629344255178474](https://zhuanlan.zhihu.com/p/2041629344255178474)
2. **Show HN** — Draft 待发布（周一10AM ET最佳时机）
3. **GitHub Stars** — 100 stars 目标
4. **B站** — 视频演示（需要用户本地录制）

### 差异化卖点
- "不是单选择题，是真的内政会议"
- "每个势力有4个不同性格的顾问"
- "你的决策种下的种子，会在10回合后开花"
- 完全开源 (MIT)
