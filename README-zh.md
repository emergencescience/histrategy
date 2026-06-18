# 三國志略 (Histrategy)

**开源 AI 驱动的历史策略游戏。**

> *建安十二年，汉室倾颓，群雄逐鹿。你执掌一方诸侯，书写属于你的传奇。亦可重返公元前 44 年的罗马，见证屋大维、安东尼与克利奥帕特拉争夺天下。*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Made by Emergence Science](https://img.shields.io/badge/Made%20by-Emergence%20Science-8A2BE2)](https://emergence.science)

<p align="center">
  <img src="publications/2026-05-25-introduction/assets/2026-05-25-histrategy-yuan-shao.png" alt="三國志略 CLI 界面" width="720">
</p>

---

## 剧本

| 剧本 | 年份 | 可选势力 | 语言 |
|------|------|----------|------|
| **三国** | 公元 207 年 | 曹操、刘备、孙权 | 中文, English |
| **罗马三巨头** | 公元前 44 年 | 屋大维、安东尼、克利奥帕特拉、元老院 | 中文, English |

## 快速开始

### 推荐：V1 引擎

```bash
pip install histrategy-sdk
export HISTRATEGY_ENGINE=v1
export DEEPSEEK_API_KEY="sk-..."
```

```python
from histrategy_sdk import Room

# 三国 — 中文
room = Room.create("my-game", faction="cao", lang="zh")
result = room.play("南下荆州，发兵攻打新野")
print(result["narrative"])

# 罗马三巨头 — 英文
room = Room.create("rome", faction="octavian", scenario="rome-triumvirate", lang="en")
result = room.play("Secure the Senate's support against Antony")
```

### 从源码安装

```bash
git clone https://github.com/emergencescience/histrategy
cd histrategy
python3 -m venv .venv
source .venv/bin/activate

# 安装引擎 + SDK
pip install -e histrategy-engine/
pip install -e histrategy-sdk/

# 可选：完整游戏（含 CLI 和服务器）
pip install -e .
histrategy
```

## 引擎选择

| 引擎 | 说明 | LLM | 适用场景 |
|------|------|-----|----------|
| **V1**（推荐） | 每回合单次 LLM 调用，叙事丰富 | 是 | 正式游玩，沉浸体验 |
| V2 | 纯确定性公式，零 LLM | 否 | 测试、离线、平衡调校 |
| V3 | 混合：确定性基线 + LLM 非线性层 | 是 | 高级模拟 |

通过 `HISTRATEGY_ENGINE=v1`（或 `v2`、`v3`）设置。推荐使用 V1。

## 架构

```
histrategy/              # 完整游戏：FastAPI 服务器、CLI、Web UI
histrategy-sdk/          # 玩家 SDK：Room、DirectEngine（文件存储）
histrategy-agent/        # Agent 集成：TurnProcessor、IM 适配器
histrategy-engine/       # 核心引擎：WorldState、TurnController、公式
```

**依赖链**：`histrategy-engine` → `histrategy-sdk` / `histrategy-agent` → `histrategy`

## 核心特性

- **文件存储**：游戏状态存于磁盘。Agent 上下文重置不丢进度。`Room.load(名称)` 即可恢复。
- **多剧本**：三国和罗马三巨头已支持。可扩展设计。
- **双语**：SDK 级别支持中英文。传入 `lang="zh"` 或 `lang="en"`。
- **AI NPC**：对手势力根据性格和局势自主决策。
- **Agent 原生**：专为 Hermes、OpenClaw 等 AI Agent 设计，可在任意聊天平台主持多人游戏。

## 为 AI Agent 安装

让你的 Agent 在聊天中主持策略游戏：

```bash
# OpenClaw
cp histrategy-agent/skills/openclaw/SKILL.md ~/.openclaw/skills/histrategy.md

# Hermes Agent
hermes skills install https://raw.githubusercontent.com/emergencescience/histrategy/main/histrategy-agent/skills/hermes/SKILL.md
```

## 可用势力

| 势力 | faction 参数 | 君主 |
|------|-------------|------|
| 曹魏 | `cao` | 曹操 🔵 |
| 蜀汉 | `shu` | 刘备 🟢 |
| 东吴 | `wu` | 孙权 🔴 |

罗马剧本：`octavian`、`antony`、`cleopatra`、`senate`

## 游戏规则

- **回合制**：每回合 = 一个季节。春→夏→秋→冬
- **资源**：兵力、粮草、资金、士气
- **内政**：发展商业、开垦农田、招募乡勇
- **军事**：出征、防守、奇袭、攻城
- **外交**：结盟、离间、劝降、纳贡
- **NPC**：AI 势力自主行动，相互征战

## 文档

- [游戏手册](https://emergence.science/zh/games/histrategy)
- [SDK 参考](https://github.com/emergencescience/histrategy/blob/main/histrategy-sdk/README.md)
- [引擎设计](https://github.com/emergencescience/histrategy/blob/main/docs/design/)

## 许可证

MIT © [Emergence Science](https://emergence.science)
