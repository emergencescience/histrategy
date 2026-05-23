# 《三國志略》— 开源 AI 驱动的历史策略游戏，用 LLM 作为世界引擎

## 缘起

你有没有玩过那种游戏——选了个选项，结果却跟你选什么毫无关系？

2026 年，AI + 历史策略文本游戏正在证明自己是一个真实的市场需求。但现有的解决方案有个共同问题：**你的决策，真的改变了世界吗？**

大部分 AI 游戏本质上还是 "单选题 + LLM 润色"：引擎用模板算好结果，LLM 只是把已经决定的事情翻译成更好看的文字。你打的「联合袁绍」，和打个「发展经济」，最终走向差异不大。

所以我们换了一个思路。

## 让 LLM 做 Game Master，而不是翻译官

《三國志略》的核心架构是这样的：

```
每回合:
  1. LLM 接收完整世界状态 (JSON)
     - 所有势力的兵力/经济/民心/资金/粮草
     - 所有势力的领地
     - 玩家最近5次决策及其后果
     - 真实历史的同期事件参考
  2. LLM 收到玩家的决策文本
  3. LLM 输出完整更新后的世界状态 + 叙事 + 新选项
```

**关键区别**：LLM 不是在"给已经算好的结果润色"，而是在**决定结果本身**。

你输入「联合袁绍讨伐董卓」，LLM 会考虑：
- 袁绍的性格（好谋无断，会不会答应？）
- 当前天下局势（董卓势力多大？其他诸侯什么态度？）
- 你之前跟袁绍打过交道吗（存储在 player_memory.json）
- 真实历史中这时发生了什么（~50% 的锚定）

然后**真正地改变世界状态**——袁绍的势力值可能变化，他和你的关系可能改变，董卓可能做出反应。这些变化会被保存，在后续回合继续影响推演。

## 为什么这个设计有本质不同

| 维度 | 传统模板驱动 | LLM 世界模型 |
|------|-------------|-------------|
| 决策后果 | 预设模板，5-10种 | 涌现的，无上限 |
| 玩家的输入 | 被分类到5个桶 | 被直接引用+响应 |
| 历史锚定 | 硬编码事件链 | ~50% 参考+20%+可改变 |
| 世界状态 | 游戏代码内，不持久化 | 结构化JSON，每回合保存 |
| 叙事 | 模板填空 | LLM 生成的文言风格 |
| replayability | 低（每次一样） | 高（每个决策产生分支） |

## 怎么玩

安装：

```bash
pip install histrategy
# 或从 GitHub 克隆
git clone https://github.com/emergencescience/histrategy
```

玩（即使没有 API Key）：

```bash
histrategy
```

你扮演一方诸侯，每个季度做一次战略决策。AI 实时推演你的决策的后果。

有 API Key 的话（推荐 DeepSeek，便宜又好用）：

```bash
export DEEPSEEK_API_KEY='sk-...'
histrategy
```

想从存档继续：

```bash
histrategy  # 自动检测并加载 ~/.histrategy/
```

## 为什么不一样

| | 《三國志略》 |
|---|---|
| 定价 | 完全开源免费 (MIT) |
| 题材 | 三国（190 年群雄逐鹿） |
| 可选势力 | 曹操/刘备/孙坚/袁绍 等 |
| AI 模式 | DeepSeek / OpenAI / 通义千问 / OpenRouter |
| 离线模式 | 知识驱动规则引擎 |
| 开源 | ✅ MIT 协议 |
| 测试 | 41 个单元+E2E 测试全部通过 |

## 技术亮点

- **多 Provider 支持**：自动检测 DEEPSEEK_API_KEY → OPENAI_API_KEY → TONGYI_API_KEY → OPENROUTER_API_KEY
- **结构化世界状态**：FactionState / CharacterState / TerritoryState / EventEntry，每回合保存到磁盘
- **决策记忆系统**：`~/.histrategy/` 保存所有历史，下次启动自动加载
- **历史轨迹追踪**：每回合记录 `historical_deviation` 字段，量化历史偏离程度
- **Dev 模式**：`histrategy --dev` 纯文本输入/输出，方便测试和脚本集成
- **41 个自动化测试**：覆盖所有核心逻辑

## 项目地址

[https://github.com/emergencescience/histrategy](https://github.com/emergencescience/histrategy)

欢迎 Star，欢迎 PR，欢迎在 Issue 里提建议。

这是我们用 AI 重塑历史策略游戏的一次尝试——历史不是你读过的故事，而是你将要书写的传奇。

---

*《三國志略》是 [Emergence Science](https://emergence.science) 的开源项目。Emergence Science 是一个 AI Agent 任务交易平台。*
