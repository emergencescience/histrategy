# Histrategy Multi-Platform Agent Client — Tech Design

> **Status:** DRAFT — 待 review
> **Date:** 2026-06-08
> **Author:** Prometheus (Hermes Agent)
> **Repo:** `emergencescience/histrategy` (branch: `feat/agent-clients`)

---

## 1. 愿景 (Vision)

让三國志略成为**任何 AI Agent 平台**上的可玩游戏。用户在他们日常使用的 IM 工具中（飞书、Telegram、Discord、微信），通过自然语言指挥三国势力，LLM 驱动整个世界运转。

不只做一个「历史教育工具」——它是一个**多面体**：
- 🎮 **纯粹的策略游戏** — 单人沉浸式三国体验
- 🏛️ **开源可商用引擎** — MIT 协议，任何人可 fork 商用
- 🔬 **科研仿真平台** — 多智能体行为经济学实验场
- 👥 **社交多人游戏** — IM 群聊即游戏房间，朋友一起玩

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    IM LAYER (Feishu First)                    │
│  飞书群聊 / 私聊 → webhook → Agent Gateway → skill dispatch   │
└──────────────────────────┬───────────────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
┌─────────────────────┐     ┌─────────────────────┐
│   OpenClaw Skill     │     │  Hermes Agent Skill  │
│   ─────────────────  │     │  ─────────────────   │
│   SKILL.md            │     │  SKILL.md            │
│   + trigger words     │     │  + slash commands    │
│   + ClawHub publish   │     │  + agentskills.io    │
└──────────┬───────────┘     └──────────┬──────────┘
           │                            │
           │    Both call into:         │
           └────────────┬───────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────┐
│              histrategy-agent (SHARED CORE)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ Game Session  │ │ Turn Engine  │ │  Multiplayer State   │ │
│  │ Manager       │ │ Processor    │ │  (group_id → saves)  │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ State Bridge  │ │ Format Engine│ │  IM Adapter          │ │
│  │ (→ engine)    │ │ (card/map)   │ │  (Feishu/Tele/...)   │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
└──────────────────────────┬───────────────────────────────────┘
                           │ calls
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              histrategy-engine (REUSED)                      │
│  Map │ Character │ Domestic │ Military │ AI │ Turn │ History │
│  7 engines, 239 tests, zero framework dependencies           │
└──────────────────────────────────────────────────────────────┘
                           │ reads
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              histrategy-knowledge (JSON data)                │
│  timeline/ │ characters/ │ geography/ │ scenarios/ │ schema/ │
└──────────────────────────────────────────────────────────────┘
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **Core shared, platform thin** | 游戏逻辑在 `histrategy-agent` 共享核心，平台层只是薄适配器 |
| **State in files, not memory** | 游戏状态持久化到 JSON 文件，支持跨会话、跨平台 |
| **Natural language I/O** | 玩家用自然语言下指令，Agent 用自然语言+富文本返回结果 |
| **Silent execution** | Agent 内部执行游戏逻辑，只把最终结果发到聊天 |
| **Multiplayer via group chat** | 群聊 ID = 游戏房间 ID，无需额外服务器 |
| **LLM as game engine** | LLM 处理所有叙事、NPC 行为、后果生成（与现有架构一致） |

---

## 3. 共享核心：`histrategy-agent`

### 3.1 包结构

```
histrategy-agent/                    # NEW: shared agent client core
├── pyproject.toml
├── src/histrategy_agent/
│   ├── __init__.py
│   ├── session.py                   # GameSessionManager — 多会话管理
│   ├── turn_processor.py            # TurnProcessor — 单回合处理管线
│   ├── state_bridge.py              # StateBridge → 调用 histrategy-engine
│   ├── format_engine.py             # FormatEngine — 富文本输出渲染
│   ├── multiplayer.py               # MultiplayerState — 群聊多人状态
│   ├── im_adapters/
│   │   ├── __init__.py
│   │   ├── base.py                  # IMAdapter 抽象基类
│   │   ├── feishu.py                # 飞书适配器
│   │   ├── telegram.py              # Telegram 适配器 (未来)
│   │   └── discord.py               # Discord 适配器 (未来)
│   └── tests/
│       ├── test_session.py
│       ├── test_turn_processor.py
│       ├── test_state_bridge.py
│       └── test_multiplayer.py
```

### 3.2 GameSessionManager

```python
class GameSessionManager:
    """Manages all active game sessions, keyed by (platform, chat_id)."""

    def get_or_create(self, platform: str, chat_id: str,
                      faction: int | None = None) -> GameSession:
        """Get existing session or create new one for this chat."""

    def process_turn(self, session: GameSession,
                     player_input: str) -> TurnResult:
        """Process one player turn and return formatted result."""

    def save_session(self, session: GameSession) -> None:
        """Persist session state to disk."""

    def list_sessions(self, platform: str) -> list[GameSession]:
        """List all active sessions for a platform."""
```

**存储路径**: `~/.histrategy/sessions/{platform}/{chat_id}/`

每个 session 目录：
```
~/.histrategy/sessions/feishu/oc_xxxxx/
├── world_state.json
├── player_memory.json
├── relationships.json
├── event_history.json
├── character_profiles.json
└── session_meta.json        # faction, turn_count, created_at, players[]
```

### 3.3 TurnProcessor — 单回合处理管线

```
Player Input (NL text)
       │
       ▼
┌─────────────────┐
│ 1. Intent Parser │  → 解析玩家意图（attack/move/recruit/diplomacy/...）
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. Validator     │  → 检验合法性（够不够兵力、领土是否相邻...）
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. Engine Step   │  → 调用 histrategy-engine 执行游戏逻辑
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. LLM Narrative │  → GameMaster 生成叙事、NPC反应、后果
└────────┬────────┘
         ▼
┌─────────────────┐
│ 5. Format Engine │  → 渲染为 Feishu 富文本卡片
└────────┬────────┘
         ▼
    TurnResult { narrative, map, cards, state_summary }
```

### 3.4 StateBridge — 连接 histrategy-engine

```python
class StateBridge:
    """Thin bridge between agent sessions and histrategy-engine."""

    def __init__(self, session: GameSession):
        self.session = session
        # Load histrategy-engine modules lazily
        self._engine = None

    def execute(self, action: ParsedAction) -> EngineResult:
        """Execute a parsed action through the engine pipeline."""

    def get_world_snapshot(self) -> WorldSnapshot:
        """Get current world state for LLM context building."""

    def apply_consequences(self, consequences: dict) -> None:
        """Apply LLM-generated consequences back to engine state."""
```

**关键设计**: StateBridge 是薄适配层，所有重逻辑仍在 `histrategy-engine` 中。我们**不重复实现**任何引擎逻辑。

### 3.5 FormatEngine — 富文本输出

```python
class FormatEngine:
    """Renders game output as platform-specific rich text."""

    def render_turn_result(self, result: TurnResult,
                           platform: str) -> PlatformMessage:
        """Render a complete turn result for the target platform."""

    def render_map(self, territories: list[Territory],
                   platform: str) -> str:
        """Render territory map (ASCII for text, or image for rich)."""

    def render_battle_card(self, battle: BattleResult) -> str:
        """Render a battle report as a rich card."""

    def render_state_summary(self, state: WorldState) -> str:
        """Render faction overview + resources + military strength."""
```

**Feishu 输出格式**:
- 叙事文本：Markdown（加粗、斜体、引用）
- 地图：ASCII art 或图片（MEDIA:path）
- 属性卡片：Feishu 富文本卡片（使用 feishu_drive 或纯 Markdown 表格）
- 选项列表：编号按钮式建议

### 3.6 MultiplayerState — 群聊多人

```python
@dataclass
class MultiplayerSession:
    session_id: str           # = group_chat_id
    host_player_id: str       # 房主
    players: dict[str, PlayerSlot]  # user_id → PlayerSlot
    turn_order: list[str]     # 行动顺序
    current_turn_index: int
    game_phase: GamePhase     # LOBBY / PLAYING / FINISHED

@dataclass
class PlayerSlot:
    user_id: str
    faction: int              # 0-6 (不同的势力)
    is_spectator: bool
    joined_at: datetime
```

**多人回合流程**:
1. 当前玩家收到 "轮到你了" 提示
2. 玩家发送指令
3. 系统处理回合，更新世界
4. 所有群成员看到回合结果（叙事+地图+状态变化）
5. 下一个玩家收到提示
6. 可以 `@bot skip` 跳过或 `@bot spectate` 旁观

---

## 4. OpenClaw Skill

### 4.1 文件结构

```
histrategy-agent/skills/openclaw/
├── SKILL.md                        # 主技能文件 (agentskills.io 格式)
├── references/
│   ├── game-rules.md               # 游戏规则参考
│   ├── unit-stats.md               # 兵种数据
│   └── faction-guide.md            # 势力指南
├── scripts/
│   ├── game_entry.py               # 入口：接收消息 → 调用 shared core
│   ├── session_init.py             # 新游戏初始化
│   └── trigger_handler.py          # 触发词处理
└── templates/
    ├── turn_card.md                # 回合结果卡片模板
    └── battle_report.md            # 战斗报告模板
```

### 4.2 SKILL.md 设计

```yaml
---
name: histrategy
description: "三國志略 — AI 驱动的三国策略游戏。群聊即战场，自然语言即指令。"
version: 1.0.0
author: Emergence Science
license: MIT
homepage: https://github.com/emergencescience/histrategy
platforms: [linux, macos, windows]
triggers:
  - 三国
  - 三国志略
  - histrategy
  - /histrategy
  - /三国
  - /sanguo
metadata:
  hermes:
    tags: [gaming, strategy, three-kingdoms, multiplayer, history]
  openclaw:
    category: gaming
    min_version: "1.0.0"
    clawhub_id: histrategy
---

# 三國志略 (Histrategy)

## Trigger
当用户在任何聊天中发送 `/histrategy`、`/三国`、或包含「三国志略」的消息时激活。

## 快速开始
- `/histrategy new` — 开始新游戏（选择势力）
- `/histrategy load` — 加载存档
- 直接发送指令 — 如 "进攻洛阳"、"招募步兵"、"与孙权结盟"

## 多人模式
在群聊中使用。第一位 `/histrategy new` 的玩家成为房主，其他人 `/histrategy join` 加入。
回合制进行，每回合由一位玩家行动。所有人看到公共事件。

## 核心循环
1. 玩家输入自然语言指令
2. AI 处理回合（意图解析 → 引擎执行 → LLM 叙事）
3. 返回：叙事 + 地图 + 状态卡片 + 建议选项
4. 世界持续演化，NPC 自主行动
```

### 4.3 脚本入口（scripts/game_entry.py）

```python
"""OpenClaw Skill entry point — called by the OpenClaw skill dispatch system.

Receives: user message, chat context, platform info
Returns: formatted game response
"""
import sys
import json
from pathlib import Path

# Add shared core to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from histrategy_agent.session import GameSessionManager
from histrategy_agent.format_engine import FormatEngine


def handle_message(message: dict) -> dict:
    """Main entry point called by OpenClaw skill runtime."""
    platform = message.get("platform", "feishu")
    chat_id = message.get("chat_id")
    user_id = message.get("user_id")
    text = message.get("text", "").strip()

    manager = GameSessionManager()
    engine = FormatEngine()

    # Handle commands
    if text.startswith("/histrategy new") or text in ("新游戏", "开始"):
        session = manager.create_session(platform, chat_id, user_id)
        return engine.render_onboarding(session, platform)

    if text.startswith("/histrategy load"):
        session = manager.load_session(platform, chat_id, user_id)
        if not session:
            return {"text": "没有找到存档。输入 `/histrategy new` 开始新游戏。"}
        return engine.render_state_summary(session, platform)

    if text.startswith("/histrategy join"):
        return manager.join_multiplayer(platform, chat_id, user_id)

    # Process game turn
    session = manager.get_or_create(platform, chat_id)
    if not session:
        return {"text": "游戏未开始。输入 `/histrategy new` 开始。"}

    result = manager.process_turn(session, text)
    manager.save_session(session)

    return engine.render_turn_result(result, platform)


if __name__ == "__main__":
    # Read JSON from stdin (OpenClaw convention)
    input_data = json.loads(sys.stdin.read())
    output = handle_message(input_data)
    print(json.dumps(output, ensure_ascii=False))
```

### 4.4 部署

```bash
# OpenClaw 用户安装
claw skills install emergencescience/histrategy

# 或从 ClawHub
claw skills install histrategy
```

---

## 5. Hermes Agent Skill

### 5.1 文件结构

```
histrategy-agent/skills/hermes/
├── SKILL.md                        # 主技能文件
├── references/
│   ├── game-rules.md
│   ├── unit-stats.md
│   └── faction-guide.md
├── scripts/
│   ├── entry.py                    # Hermes skill 入口
│   ├── session_manager.py          # 会话管理（复用 shared core）
│   └── commands.py                 # slash command 定义
└── templates/
    ├── turn_card.md
    └── battle_report.md
```

### 5.2 SKILL.md 设计

```yaml
---
name: histrategy
description: "三國志略 — AI 驱动的三国策略游戏。在飞书/Telegram 中用自然语言指挥千军万马。"
version: 1.0.0
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
- 用户在飞书群聊中提及「三国志略」
- 用户在当前会话中已有活跃游戏存档

## Procedure

### 1. 新游戏
当用户发送 `/histrategy new` 或「开始三国」时：
1. 展示可选势力（刘备/曹操/孙权/袁绍/刘表/刘璋/马腾）
2. 生成对应的起始世界状态
3. 渲染势力简介 + 起始地图 + 当前局势描述

### 2. 回合处理
当玩家发送自然语言指令时：
1. 加载存档（`scripts/session_manager.py` → shared core）
2. 调用 `turn_processor.py` 处理回合
3. 渲染结果：叙事 + 地图 + 状态卡片 + 建议
4. 保存状态
5. 将完整结果发送到聊天

### 3. 多人模式
群聊中：
- 第一位发 `/histrategy new` 的是房主
- 其他人发 `/histrategy join` 加入
- 房主可以选择势力分配方式（自选/随机/历史）

### 4. 存档管理
- `/histrategy save` — 保存当前进度
- `/histrategy load` — 加载存档
- `/histrategy status` — 查看当前状态

## Platform Rules

### Feishu 输出格式
- 叙事部分：Markdown 文本
- 地图：ASCII art（< 50 行）或 图片文件（MEDIA:path）
- 属性卡片：Markdown 表格
- 选项提示：带编号的建议列表

### 状态文件
- 存储在 `HISTRATEGY_DATA_DIR`（默认 `~/.histrategy/`）
- 每个会话独立目录：`sessions/{platform}/{chat_id}/`
```

### 5.3 与 Hermes Agent 的集成方式

Hermes Agent skill 系统支持：
- **Slash commands**: `/histrategy` → 自动加载此 skill → 执行 scripts/entry.py
- **Trigger words**: 消息包含「三国」→ 自动路由
- **Session persistence**: skill 的 `scripts/` 子进程可读写文件系统

### 5.4 部署

```bash
# Hermes Agent 用户安装
hermes skills install histrategy

# 或从 agentskills.io
hermes skills install agentskills.io/emergencescience/histrategy
```

---

## 6. Feishu 适配（Phase 1）

### 6.1 为什么 Feishu 优先

1. **用户在用** — 我们已经在飞书上与用户沟通
2. **企业级富文本** — 飞书支持 Markdown、富文本卡片、图片、文件
3. **OpenClaw + Hermes 都原生支持** — 无需额外开发 IM 桥接
4. **群聊即房间** — 飞书群聊天然适合多人游戏

### 6.2 消息流

```
用户发送 "进攻洛阳"
       │
       ▼
飞书 Webhook → OpenClaw/Hermes Gateway
       │
       ▼
Skill 匹配 /histrategy → 加载 SKILL.md
       │
       ▼
scripts/entry.py 执行
       │
       ▼
GameSessionManager.process_turn()
       │
       ▼
TurnProcessor pipeline (intent → validate → engine → LLM → format)
       │
       ▼
FormatEngine.render_turn_result() → Feishu Markdown + Card
       │
       ▼
Agent 发送回复到飞书群聊
```

### 6.3 Feishu 富文本格式

**回合叙事示例**（飞书 Markdown）:

```
🎌 **建安五年 · 春** | 回合 #12

> 「明公！关羽将军已率五千精兵抵达洛阳城下。守将徐晃闭门不出，城防坚固。」

🗺️ **天下大势**
[ASCII MAP or MEDIA:/tmp/histrategy_map.png]

⚔️ **我军态势**
| 势力 | 领地 | 兵力 | 粮草 | 声望 |
|------|------|------|------|------|
| 刘备 | 3城 | 12,000 | 8,000石 | 72 |

📋 **可选行动**
1. 围城劝降 — 利用关羽威名，派使者劝降徐晃
2. 强攻洛阳 — 不惜代价攻城（预计伤亡 30-40%）
3. 转攻许昌 — 留少量兵力佯攻洛阳，主力偷袭许昌
4. 撤退修整 — 保存实力，回新野休整

请输入行动编号或自由描述你的决策。
```

### 6.4 飞书适配器关键实现

```python
class FeishuAdapter(IMAdapter):
    """Feishu-specific message formatting and delivery."""

    MAX_MESSAGE_LENGTH = 15000       # 飞书单条消息上限
    MAX_CARD_SIZE = 100 * 1024       # 飞书卡片 100KB

    def format_message(self, content: str) -> dict:
        """Format content for Feishu Markdown message."""

    def format_interactive_card(self, card: TurnCard) -> dict:
        """Build Feishu interactive card with buttons."""

    def send_image(self, image_path: str) -> dict:
        """Upload and send image via Feishu IM API."""

    def split_long_message(self, content: str) -> list[str]:
        """Split messages exceeding Feishu limit."""
```

---

## 7. 多人游戏设计

### 7.1 游戏模式

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **单人** | 一个玩家，控制一方势力，NPC 控制其余 | 个人游戏、科研仿真 |
| **合作** | 多个玩家共同控制一方势力（民主投票） | 公司团建、朋友合作 |
| **对抗** | 每方势力一个玩家，相互对抗 | 竞技比赛、社交娱乐 |
| **旁观** | 纯 AI 对打，玩家旁观 | 直播内容、教学演示 |

### 7.2 回合机制

```
对抗模式回合流：

Turn 1: 玩家A（刘备）行动 → 世界更新 → 全群看到结果
Turn 2: 玩家B（曹操）行动 → 世界更新 → 全群看到结果
Turn 3: 玩家C（孙权）行动 → ...
         ─── 所有 NPC 势力在每回合末自主行动 ───
Turn 4: 玩家A 行动 ...
```

### 7.3 状态文件隔离

```
~/.histrategy/sessions/feishu/
├── oc_group_abc123/                    # 群聊 room
│   ├── session_meta.json               # 多人元数据
│   ├── players/
│   │   ├── user_001/                   # 玩家A的私有状态
│   │   │   ├── world_state.json        # 玩家A看到的世界（战争迷雾）
│   │   │   └── player_memory.json
│   │   └── user_002/
│   │       └── ...
│   └── public/
│       └── world_state.json            # 公共世界状态（所有玩家可见）
```

---

## 8. 跨平台一致性

### 8.1 共享代码比例

```
histrategy-agent/src/histrategy_agent/    ← 100% 共享
├── session.py                            ← 共享
├── turn_processor.py                     ← 共享
├── state_bridge.py                       ← 共享
├── format_engine.py                      ← 共享
├── multiplayer.py                        ← 共享
└── im_adapters/
    ├── base.py                           ← 共享接口
    ├── feishu.py                         ← 平台特定
    ├── telegram.py                       ← 平台特定 (P2)
    └── discord.py                        ← 平台特定 (P2)

skills/
├── openclaw/
│   └── SKILL.md + scripts/               ← 薄适配层 (~200行)
└── hermes/
    └── SKILL.md + scripts/               ← 薄适配层 (~200行)
```

**目标**: 90%+ 代码共享，平台特定代码 < 500 行。

### 8.2 开发顺序

```
Phase 1: Feishu + Hermes Agent (本 sprint)
  ├── histrategy-agent 共享核心
  ├── Hermes Agent skill
  └── Feishu 适配器

Phase 2: Feishu + OpenClaw
  ├── OpenClaw skill (复用 shared core)
  └── ClawHub 发布

Phase 3: 多人游戏
  ├── MultiplayerState
  ├── 群聊房间管理
  └── 合作/对抗模式

Phase 4: 多 IM 扩展
  ├── Telegram 适配器
  ├── Discord 适配器
  └── 微信适配器 (将来)
```

---

## 9. 技术决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | **共享核心用 Python** | `histrategy-engine` 已用 Python，无需重写；Hermes Agent 原生 Python |
| 2 | **OpenClaw skill 用 Python scripts** | OpenClaw 支持外部脚本调用（参考 yumfu 模式），无需重写 TypeScript |
| 3 | **Feishu 优先** | 用户在飞书；两个平台都原生支持；企业级富文本 |
| 4 | **状态在文件系统，不在内存** | 兼容 Agent 会话隔离；跨平台可共享；支持存档导入导出 |
| 5 | **自然语言接口（无命令行）** | 参考 yumfu 成功模式；降低用户门槛；适合 IM 环境 |
| 6 | **群聊 ID 即房间 ID** | 无需额外服务器；无需注册登录；飞书群聊天然隔离 |
| 7 | **LLM 输出完整状态更新** | 与现有架构一致；后果真实涌现；无模板限制 |
| 8 | **不引入新依赖框架** | 共享核心只依赖 `histrategy-engine`（已有）；`httpx`（已有）用于 LLM 调用 |

---

## 10. 风险 & 缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 延迟 > 30s，IM 用户体验差 | 玩家流失 | 先返回 "处理中..."；后台处理完再推送结果 |
| 多人状态同步冲突 | 数据不一致 | 回合锁 + 单写者模式；文件级锁 |
| 飞书消息长度限制 | 叙事被截断 | 分页发送 + 摘要；关键信息优先 |
| OpenClaw skill 审核/发布延迟 | 无法分发 | Hermes Agent 先行验证；两边同时提交 |
| 用户量增大后 LLM 成本失控 | 运营不可持续 | 离线引擎 fallback；缓存常见回合；批量 API 优惠 |

---

## 11. 下一步

1. **此文档 review** — 用户审阅，确认架构方向
2. **创建 kanban 任务** — Sprint 4 任务拆分
3. **开始 Phase 1 开发** — `histrategy-agent` 共享核心 + Hermes Agent skill + Feishu
4. **E2E 验证** — 在飞书私聊中完整玩一局
