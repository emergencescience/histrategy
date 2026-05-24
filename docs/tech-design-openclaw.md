# Tech Design: OpenClaw / Hermes Integration

> **Status**: Draft v0.1 — Design Phase
> **Owner**: Symbol Science
> **Date**: 2026-05-24

---

## 1. Architecture Overview

### 1.1 System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        IM CHANNELS                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ Discord  │  │  飞书    │  │ Telegram │  │  Slack   │  ...    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘         │
└───────┼─────────────┼─────────────┼─────────────┼────────────────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    OpenClaw / Hermes Gateway                       │
│  - 消息收发 (Webhook / WebSocket / Polling)                       │
│  - 渠道路由 (channel → agent session)                             │
│  - 认证 & 权限                                                    │
└──────────────────────────┬───────────────────────────────────────┘
                           │ skill invocation
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│           histrategy Skill (Agent Skill Package)                  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   Skill Entry Point                          │ │
│  │  - 接收 Agent Core 消息                                      │ │
│  │  - Session 路由 & 状态加载                                    │ │
│  │  - 命令解析 (slash commands + free text)                     │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                             │                                     │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │                Headless Game Engine                          │ │
│  │                                                              │ │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │ │
│  │  │ GameEngine  │  │  GameMaster  │  │  WorldState      │   │ │
│  │  │ (orchestr.)│  │  (LLM GM)    │  │  (persistence)   │   │ │
│  │  └─────────────┘  └──────────────┘  └──────────────────┘   │ │
│  │                                                              │ │
│  │  API:                                                        │ │
│  │    start_game(faction_id) → IntroResult                      │ │
│  │    enter_plan_mode(session_id) → PlanModeResult              │ │
│  │    execute_command(session_id, decision) → CommandResult     │ │
│  │    get_state(session_id) → WorldState                        │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                             │                                     │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │                 Channel Adapter Layer                        │ │
│  │                                                              │ │
│  │  ┌────────────┐  ┌───────────┐  ┌────────────┐             │ │
│  │  │ Discord    │  │  Feishu   │  │  Telegram  │  ...        │ │
│  │  │ Adapter    │  │  Adapter  │  │  Adapter   │             │ │
│  │  └────────────┘  └───────────┘  └────────────┘             │ │
│  │                                                              │ │
│  │  每个 adapter 实现:                                           │ │
│  │    render_plan_mode(PlanModeResult) → channel-specific msg   │ │
│  │    render_command(CommandResult) → channel-specific msg      │ │
│  │    render_state(WorldState) → channel-specific msg           │ │
│  │    parse_input(raw_message) → ParsedCommand                  │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Design Decision: Engine ↔ Channel Decoupling

关键设计决策：**游戏引擎与渠道完全解耦**。

```
                    ┌──────────────────┐
                    │  Headless Engine │
                    │                  │
                    │  输入: dict/str  │
                    │  输出: TypedDict │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Discord  │  │  Feishu  │  │   CLI    │
        │ Adapter  │  │  Adapter │  │  (existing│
        │          │  │          │  │   Rich)  │
        └──────────┘  └──────────┘  └──────────┘
```

引擎输出统一的结构化数据（TypedDict），每个渠道 adapter 负责将其渲染为该渠道的原生 UI 格式。这确保：
- 现有 CLI 不 broken（CLI 只是一个 channel adapter）
- 新增渠道不需要修改引擎代码
- 渠道特定功能（如 Discord Button、飞书卡片）可以充分利用

### 1.3 Why NOT MCP?

虽然 OpenClaw 和 Hermes 都支持 MCP，但 histrategy 不适用 MCP 作为主要集成协议：

| Concern | MCP | Native Skill |
|---------|-----|-------------|
| Token 开销 | MCP 注入完整 tool schema（每调用 ~44K tokens） | Skill 直接调用，无 schema 开销 |
| 交互模式 | tool-calling（function → result） | 多轮对话 + 异步推送 |
| Human-in-loop | MCP 设计用于 tool execution，不适合等待用户输入 | Skill 天然支持等待和状态保持 |
| 延迟 | 每次 tool call 走完整 MCP round-trip | 直接函数调用 |

**例外**：如果未来需要跨 Agent 查询游戏状态（如 Hermes 分析游戏数据），可额外提供 MCP server 作为 read-only 查询接口。

---

## 2. Headless Engine Design

### 2.1 API Surface

```python
# histrategy/engine/headless.py

from typing import TypedDict, NotRequired

class IntroResult(TypedDict):
    narrative: str
    npc_actions: list[str]
    state_changes: dict
    new_choices: list[str]
    faction_name: str
    faction_stats: dict  # strength, economy, morale, etc.

class PlanModeResult(TypedDict):
    season_summary: str
    advisors: list[dict]  # [{name, title, temperament, speech}]
    suggestions: list[str]
    year: int
    season: str
    turn: int
    player_stats: dict

class CommandResult(TypedDict):
    bureaucracy: list[dict]   # [{department, official, action}]
    aftermath: str
    state_changes: dict       # {strength, economy, morale, treasury, food}
    seeds: list[dict]         # [{title, description, trigger_after, type}]
    npc_reactions: list[str]
    game_over: NotRequired[dict]

class HeadlessEngine:
    """Headless game engine — no TUI/CLI dependencies."""

    def __init__(self, data_dir: str | None = None):
        """Initialize engine. data_dir defaults to ~/.histrategy."""

    # ── Game lifecycle ──

    def list_factions(self) -> list[dict]:
        """Return available factions with display info."""

    def start_game(self, faction_id: str, player_id: str) -> IntroResult:
        """Start a new game. player_id = IM user ID."""

    def resume_game(self, player_id: str) -> IntroResult | None:
        """Try to resume existing game. Returns None if no save."""

    # ── Turn lifecycle ──

    def plan_mode(self, session_id: str) -> PlanModeResult:
        """Enter Plan Mode: generate advisor court + suggestions."""

    def execute_decision(self, session_id: str,
                         decision: str) -> CommandResult:
        """Execute player's decision: Command Mode."""

    # ── Queries ──

    def get_state(self, session_id: str) -> dict:
        """Get current world state (for /state command)."""

    def get_history(self, session_id: str,
                    n: int = 10) -> list[dict]:
        """Get recent decision history (for /history command)."""

    def quit_game(self, session_id: str):
        """Save and end game. Player can resume later."""
```

### 2.2 Session Management

每个 IM 会话映射到一个游戏 session。Session 状态存储沿用现有的 `WorldState` 持久化机制。

```
~/.histrategy/
├── sessions/
│   ├── discord_123456_789012/    # Discord user 123456 in channel 789012
│   │   ├── world_state.json
│   │   ├── player_memory.json
│   │   ├── relationships.json
│   │   └── event_history.json
│   ├── feishu_ou_abc_def/        # Feishu user ou_abc in chat def
│   │   └── ...
│   └── telegram_12345/           # Telegram user 12345 (DM)
│       └── ...
└── global/
    └── active_sessions.json      # session_id → metadata mapping
```

**Session ID 格式**: `{channel_type}_{user_id}_{conversation_id}`

- Discord DM: `discord_{user_id}_{channel_id}`
- Discord Guild Channel: `discord_{guild_id}_{channel_id}`
- 飞书: `feishu_{open_id}_{chat_id}`
- Telegram: `telegram_{user_id}_{chat_id}`

### 2.3 Refactoring Path (from current codebase)

当前 `cli/app.py` 中的 game loop 逻辑需要提取到 engine 层：

```
Current:
  cli/app.py          — Rich TUI + game loop + display rendering
  cli/dev_cli.py      — plain-text I/O + game loop + display rendering

Target:
  engine/headless.py  — game loop logic (NEW)
  cli/app.py          — Rich TUI display rendering only
  cli/dev_cli.py      — plain-text display rendering only
  channel/discord.py  — Discord Embed/Button rendering (NEW)
  channel/feishu.py   — Feishu Card rendering (NEW)
```

**Key constraint**: 现有 CLI 的 `run_game()` 和 `run_dev()` 必须不受影响。改动方式是提取 game loop 到 engine 层，CLI 层只负责 rendering。

---

## 3. Channel Adapter Layer

### 3.1 Base Adapter Interface

```python
# histrategy/channel/base.py

from abc import ABC, abstractmethod

class ChannelAdapter(ABC):
    """Abstract channel adapter. Each IM platform gets one implementation."""

    @abstractmethod
    def render_intro(self, result: IntroResult) -> list[dict]:
        """Render game intro into channel-specific message(s)."""

    @abstractmethod
    def render_plan_mode(self, result: PlanModeResult) -> list[dict]:
        """Render Plan Mode (advisors + suggestions) into messages."""

    @abstractmethod
    def render_command_result(self, result: CommandResult) -> list[dict]:
        """Render Command Mode results into messages."""

    @abstractmethod
    def render_state(self, state: dict) -> list[dict]:
        """Render world state display."""

    @abstractmethod
    def render_error(self, message: str) -> list[dict]:
        """Render error message."""

    @abstractmethod
    def render_thinking(self) -> list[dict]:
        """Render a 'thinking...' indicator."""

    @abstractmethod
    def parse_command(self, raw_text: str) -> dict:
        """Parse raw message into structured command.
        Returns: {type: 'decision'|'slash_command'|'other', content: str, ...}
        """
```

每个 `render_*` 返回 `list[dict]`，因为一条游戏内容可能跨越多个消息（Discord 有 embed 数量限制，飞书有卡片大小限制）。

### 3.2 Discord Adapter

```python
# histrategy/channel/discord.py

class DiscordAdapter(ChannelAdapter):
    """Renders game output as Discord Embeds + Buttons."""

    def render_plan_mode(self, result: PlanModeResult) -> list[dict]:
        messages = []

        # Message 1: Season summary + advisor court
        embeds = []
        embeds.append({
            "title": f"🏛️ {result['year']}年{result['season']} · 内政会议",
            "description": result["season_summary"],
            "color": 0x9B59B6,  # purple
        })

        for adv in result["advisors"]:
            embeds.append({
                "title": f"{self._temperament_icon(adv['temperament'])} {adv['name']}（{adv['title']}）",
                "description": adv["speech"],
                "color": self._temperament_color(adv["temperament"]),
            })

        messages.append({"embeds": embeds})

        # Message 2: Suggestions with buttons
        components = []
        for i, s in enumerate(result["suggestions"], 1):
            components.append({
                "type": 2,  # Button
                "style": 1,  # Primary
                "label": s[:80],  # Discord button label limit
                "custom_id": f"suggestion_{i}",
            })

        messages.append({
            "content": "**🎯 军师建议的方案：**",
            "components": [{"type": 1, "components": components}],
        })

        return messages
```

### 3.3 Feishu Adapter

飞书使用「卡片消息」格式，支持富文本、按钮、多列布局。

```python
# histrategy/channel/feishu.py

class FeishuAdapter(ChannelAdapter):
    """Renders game output as Feishu Card Messages."""

    def render_plan_mode(self, result: PlanModeResult) -> list[dict]:
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text",
                          "content": f"🏛️ {result['year']}年{result['season']} · 内政会议"},
                "template": "purple",
            },
            "elements": [
                # Season summary
                {"tag": "markdown",
                 "content": f"*{result['season_summary']}*"},
                {"tag": "hr"},
            ],
        }

        # Advisor speeches
        for adv in result["advisors"]:
            card["elements"].append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{self._temperament_icon(adv['temperament'])} "
                        f"{adv['name']}（{adv['title']}）**\n"
                        f"{adv['speech']}"
                    ),
                },
            })
            card["elements"].append({"tag": "hr"})

        # Suggestions as clickable actions
        actions = []
        for i, s in enumerate(result["suggestions"], 1):
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"方案{i}"},
                "type": "primary",
                "value": {"suggestion": i, "text": s},
            })

        card["elements"].append({
            "tag": "action",
            "actions": actions,
        })

        return [card]
```

---

## 4. Human-in-Loop Interaction Design

### 4.1 State Machine

```
State machine per session:

  IDLE ──[start]──→ INTRO ──[auto]──→ WAITING_DECISION
                                          │           ▲
                          player sends    │           │ /plan
                          decision        │           │
                                          ▼           │
                                      EXECUTING ─────┘
                                          │
                          result ready    │
                                          ▼
                                      WAITING_DECISION  (loop)
```

### 4.2 Command Parsing

```python
# histrategy/channel/command_parser.py

import re

SLASH_COMMANDS = {
    "new-game": r"^/new-game\s+(\S+)",
    "state": r"^/state$|^状态$",
    "history": r"^/history$|^历史$",
    "plan": r"^/plan$|^plan$|^会议$",
    "quit": r"^/quit$|^退出$",
    "help": r"^/help$|^帮助$",
}

def parse_message(text: str, session_state: str) -> dict:
    """Parse incoming message into a command.

    Returns:
        {
            "type": "slash_command" | "decision" | "unknown",
            "command": str | None,       # slash command name
            "args": dict | None,         # slash command args
            "decision_text": str | None, # free-text decision
        }
    """
    # Check slash commands
    for cmd, pattern in SLASH_COMMANDS.items():
        m = re.match(pattern, text.strip(), re.IGNORECASE)
        if m:
            return {
                "type": "slash_command",
                "command": cmd,
                "args": m.groupdict() if m.groups() else {},
            }

    # If in WAITING_DECISION state, treat as decision
    if session_state == "WAITING_DECISION":
        return {
            "type": "decision",
            "decision_text": text.strip(),
        }

    return {"type": "unknown", "content": text.strip()}
```

### 4.3 Multi-Player Permission Model

```python
# histrategy/engine/session.py

@dataclass
class SessionConfig:
    session_id: str
    player_id: str           # The "主公" — only one per session
    advisor_ids: set[str]    # Can discuss but not decide
    spectator_ids: set[str]  # Read-only
    channel_type: str        # discord / feishu / telegram
    conversation_id: str     # Channel/DM ID
    created_at: datetime
    last_active: datetime

class SessionManager:
    """Multi-player session manager for IM-based gameplay."""

    def can_decide(self, session_id: str, user_id: str) -> bool:
        """Only the 主公 can make game decisions."""

    def can_view(self, session_id: str, user_id: str) -> bool:
        """Spectators and advisors can view."""

    def can_discuss(self, session_id: str, user_id: str) -> bool:
        """Advisors can discuss (messages shown but not acted on)."""

    def abdicate(self, session_id: str, new_player_id: str):
        """Transfer 主公 role to another user."""

    def promote_to_advisor(self, session_id: str, user_id: str):
        """Promote a spectator to advisor."""
```

---

## 5. Skill Package Structure

### 5.1 OpenClaw Skill Manifest

```json
// openclaw.json
{
  "name": "histrategy",
  "version": "0.2.0",
  "description": "三國志略 — AI-powered Three Kingdoms strategy game",
  "author": "Emergence Science",
  "license": "MIT",
  "extensions": {
    "histrategy": {
      "entry": "scripts/headless_server.py",
      "type": "service",
      "env": {
        "DEEPSEEK_API_KEY": {"required": false, "description": "LLM API key"},
        "OPENAI_API_KEY": {"required": false},
        "OPENROUTER_API_KEY": {"required": false},
        "TONGYI_API_KEY": {"required": false},
        "DATA_DIR": {"required": false, "default": "~/.histrategy"},
        "DEFAULT_CHANNEL": {"required": false, "default": "discord"}
      },
      "channels": ["discord", "feishu", "telegram", "slack"],
      "permissions": {
        "disk": ["~/.histrategy/"],
        "network": ["api.deepseek.com", "api.openai.com", "api.anthropic.com"]
      }
    }
  }
}
```

### 5.2 SKILL.md

Skill description that OpenClaw's Agent Core reads to understand how to use the skill:

```markdown
# histrategy — AI三国策略游戏主持

## What this skill does

Runs the 三國志略 game engine — an AI-powered Three Kingdoms strategy game where
the LLM is the game master. Players interact through Plan Mode (advisor court)
and Command Mode (bureaucracy execution).

## How to use

### Starting a game
When a user wants to play, call `/new-game <faction>` where faction is one of:
cao (曹操), shu (刘备), wu (孙坚), yuan_shao (袁绍)

### Game loop
1. The engine enters Plan Mode and returns advisor speeches + 4 suggestions
2. Render them using the channel adapter
3. Wait for the player's decision (free text)
4. The engine enters Command Mode and returns execution results
5. Render them using the channel adapter
6. Loop back to step 1

### Commands
- /new-game <faction> — start a new game
- /state — show current world state
- /history — show recent decisions
- /plan — re-enter Plan Mode
- /quit — save and exit

### Session management
- Each channel/chat is a separate game session
- Sessions auto-save after each turn
- Use /resume to continue a previous game
```

### 5.3 Hermes ACP Integration

For Hermes Agent, histrategy exposes itself as an ACP (Agent Communication Protocol) service:

```python
# histrategy/hermes/acp_server.py

from hermes.acp import ACPService, expose

class HistrategyACPService(ACPService):
    """Histrategy game engine exposed via ACP."""

    @expose
    async def new_game(self, faction_id: str, player_id: str) -> dict:
        """Start a new game session."""

    @expose
    async def resume_game(self, player_id: str) -> dict | None:
        """Resume existing game."""

    @expose
    async def plan_mode(self, session_id: str) -> dict:
        """Generate Plan Mode content."""

    @expose
    async def execute_decision(self, session_id: str,
                                decision: str) -> dict:
        """Process player decision."""
```

---

## 6. Deployment Model

### 6.1 Standalone (per-user install)

```
User installs OpenClaw on their machine
  → installs histrategy skill
  → configures LLM API key
  → connects Discord/Feishu via Gateway
  → game runs locally, channels reachable via IM
```

### 6.2 Hosted (shared server)

```
Server runs OpenClaw + histrategy
  → Multiple players connect via IM channels
  → Each player gets isolated game session
  → LLM costs shared or per-player billing
  → Game states persisted on server
```

### 6.3 Hybrid (recommended MVP)

```
Developer runs OpenClaw locally
  → Discord bot in a shared server
  → Friends join channel, play game
  → LLM costs borne by developer
  → Low barrier for testing/adoption
```

---

## 7. Testing Strategy

### 7.1 Unit Tests (new)

| Test | What it verifies |
|------|-----------------|
| `TestHeadlessEngine` | Game lifecycle (start → plan → execute → state) without any channel |
| `TestCommandParser` | Slash command parsing, free text detection, state-aware parsing |
| `TestSessionManager` | Permissions, abdication, advisor promotion |
| `TestChannelAdapters` | Each adapter produces valid channel-native payloads |

### 7.2 Integration Tests

| Test | What it verifies |
|------|-----------------|
| `TestDiscordAdapter` | Full game loop through Discord adapter (mock Discord API) |
| `TestFeishuAdapter` | Full game loop through Feishu adapter (mock Feishu API) |
| `TestSessionIsolation` | Two concurrent sessions don't interfere |

### 7.3 Existing Test Compatibility

The refactoring MUST maintain all 41 existing tests passing. The `HeadlessEngine` wraps the existing `GameEngine` — it doesn't replace it. CLI tests continue to use `cli/app.py` unchanged.

---

## 8. Migration Plan

### Phase 0: Extract headless engine (Week 1-2)

1. Create `histrategy/engine/headless.py` with `HeadlessEngine` class
2. `HeadlessEngine` wraps `GameEngine` — delegates but adds session management
3. Verify all existing tests pass (CLI still works via existing code path)
4. Add unit tests for `HeadlessEngine`

### Phase 1: Channel adapters (Week 2-3)

1. Create `histrategy/channel/base.py` (abstract interface)
2. Implement `DiscordAdapter` with Embed + Button rendering
3. Implement `FeishuAdapter` with Card rendering
4. Add channel adapter unit tests

### Phase 2: Skill packaging (Week 3-4)

1. Create `openclaw.json` and `SKILL.md`
2. Test end-to-end: OpenClaw Gateway → Discord → histrategy skill → game loop
3. Test end-to-end: OpenClaw Gateway → Feishu → histrategy skill → game loop
4. Write installation documentation

### Phase 3: Multi-player (Week 4-5)

1. Implement `SessionManager` with permission model
2. Implement cross-channel world state (multi-faction mode)
3. Implement CRON-based scheduled push notifications
4. Test with 3+ concurrent players in a Discord server
