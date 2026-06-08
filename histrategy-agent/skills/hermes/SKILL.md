---
name: histrategy
description: "三國志略 — AI 驱动的三国策略游戏。在飞书中用自然语言指挥千军万马。群聊即战场，自然语言即指令。"
version: 1.0.0
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gaming, strategy, three-kingdoms, multiplayer, history, feishu]
    related_skills: []
    category: gaming
    slash_commands:
      - /histrategy
      - /三国
      - /sanguo
---

# Histrategy — 三國志略

## When to Use
- 用户发送 `/histrategy`、`/三国`、`/sanguo`
- 用户在飞书/Telegram 中提及「三国志略」、「三国游戏」
- 用户在当前会话中已有活跃游戏存档

## Quick Start
- `/histrategy new` — 开始新游戏，选择势力
- `/histrategy load` — 加载已有存档
- `/histrategy status` — 查看当前局势
- `/histrategy join` — 加入多人游戏（群聊）
- `/histrategy help` — 显示帮助
- 直接发送指令 — 如「进攻洛阳」「招募步兵」「与孙权结盟」

## Procedure

### 1. 新游戏 (/histrategy new)
1. 调用 `scripts/entry.py` 的 `handle_new_game(platform, chat_id, user_id)`
2. 展示 5 个可选势力（刘备/曹操/孙权/刘表/刘璋）
3. 用户回复势力名称后，初始化世界状态
4. 渲染势力简介 + 起始状态 + 地图
5. 保存会话

### 2. 回合处理（玩家发送指令时）
1. 加载存档：`scripts/entry.py handle_turn(platform, chat_id, user_id, text)`
2. Intent parser 解析玩家意图
3. Engine 执行游戏逻辑
4. LLM 生成叙事（或离线 fallback）
5. 渲染结果：叙事 + 地图 + 状态卡片 + 建议选项
6. 保存状态
7. 将完整结果发送到聊天

### 3. 多人模式
- 第一位发 `/histrategy new` 的是房主
- 其他人发 `/histrategy join` 加入
- 房主可选势力分配方式
- 回合制轮流行动

### 4. 存档管理
- `/histrategy save` — 保存当前进度
- `/histrategy load` — 加载存档
- `/histrategy status` — 查看当前状态
- `/histrategy delete` — 删除存档

## Output Format (Feishu)

回合结果以 Markdown 格式输出：

```
🎌 **建安{year}年 · {season}** | 回合 #{turn}

> {narrative — LLM 生成的叙事文本}

🗺️ **天下大势**
{ASCII 地图，标注各势力领地}

⚔️ **我军态势**
| 领地 | {领土列表} |
| 兵力 | {总兵力} |
| 粮草 | {食物储备} |
| 声望 | {声望值} |
| 金库 | {金币} |

📋 **可选行动**
1. {建议1}
2. {建议2}
3. {建议3}
```

## State Files

游戏状态存储在 `HISTRATEGY_DATA_DIR`（默认 `~/.histrategy/sessions/`）
每个会话独立目录：`sessions/{platform}/{chat_id}/`

## Platform Rules

### Feishu
- 叙事部分：Markdown 文本（支持加粗、斜体、引用）
- 地图：ASCII art（< 30 行）
- 属性卡片：Markdown 表格
- 建议：带编号列表
- 单条消息不超过 15000 字符

### Future Platforms (Telegram, Discord)
- 适配器模式：参见 `im_adapters/` 目录
