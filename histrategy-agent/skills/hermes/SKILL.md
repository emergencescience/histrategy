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
    requires: histrategy-agent>=0.1.0,histrategy-sdk>=0.2.0
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

## 安装

```bash
pip install histrategy-agent histrategy-sdk
```

- `histrategy-agent` — Agent 集成层（`TurnProcessor`, `StateBridge`, IM 适配器）
- `histrategy-sdk` — 游戏 SDK（`Room`, `MultiplayerRoom`）
- `histrategy-engine` — 作为依赖自动安装

配置 LLM API Key:

```bash
export DEEPSEEK_API_KEY="sk-..."  # 推荐
# 或 OPENAI_API_KEY / TONGYI_API_KEY
```

## Quick Start
- `/histrategy new [faction]` — 开始单人游戏，可选指定势力
- `/histrategy host caocao=张三 liubei=李四` — 创建多人房间
- `/histrategy join <room_id> <faction> [token]` — 加入多人游戏
- `/histrategy play <decision>` — 提交回合决策
- `/histrategy status` — 查看当前状态
- `/histrategy turns` — 查看回合历史
- `/histrategy help` — 显示帮助

## Procedure

### 1. 单人模式 (`/histrategy new [faction]`)

使用 `histrategy_sdk.Room`（基于文件的状态管理）:

```python
from histrategy_sdk import Room

# 创建房间（支持 shu / wei / wu / neutral 等势力）
room = Room.create("my-game", faction="shu")

# 提交决策
result = room.play("联吴抗曹")

# 查看状态
room.status()
```

工作流：
1. 创建房间时展示势力简介 + 起始状态 + 地图
2. 玩家通过 `/histrategy play <decision>` 提交决策 → `room.play(decision_text)`
3. 引擎执行游戏逻辑，LLM 生成叙事
4. 渲染结果：叙事 + 地图 + 状态卡片 + 建议选项
5. 重复步骤 2-4，直到游戏结束

### 2. 多人模式

使用 `histrategy_sdk.MultiplayerRoom`:

#### 房主创建房间 (`/histrategy host caocao=张三 liubei=李四`)

```python
from histrategy_sdk import MultiplayerRoom

client = get_client()  # 平台客户端
room = MultiplayerRoom.create(client, {
    "caocao": "张三",
    "liubei": "李四",
})
# 将 room.player_links 分享给对应玩家
```

#### 玩家加入 (`/histrategy join <room_id> <faction> [token]`)

```python
room = MultiplayerRoom.join(client, room_id, faction, token)
```

#### 回合决策 (`/histrategy play <decision>`)

```python
# 提交决策
room.decide("攻打襄阳")

# 等待结算
room.wait_for_resolve()

# 查看结果
status = room.status()
```

### 3. 状态管理

- `/histrategy status` — 查看当前状态（`room.status()`）
- `/histrategy turns` — 查看回合历史
- `/histrategy save` — 保存进度
- `/histrategy load` — 加载存档
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
