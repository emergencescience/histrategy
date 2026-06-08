"""Command handler for slash commands in the Hermes Agent skill.

Parses `/histrategy` subcommands and dispatches to the appropriate handler.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CORE_PATH = Path(__file__).parent.parent.parent.parent / "src"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

from histrategy_agent.session import GameSessionManager
from histrategy_agent.format_engine import FormatEngine
from histrategy_agent.multiplayer import MultiplayerSession, GamePhase

from .session_manager import (
    load_or_create_session,
    create_new_session,
    list_factions,
    get_faction_info,
    DEFAULT_FACTION,
    FACTION_CHOICES,
)

# Multiplayer sessions: keyed by chat_id
MULTIPLAYER_SESSIONS: dict[str, MultiplayerSession] = {}


# ─── Command detection ─────────────────────────────────────

COMMAND_PREFIXES = ["/histrategy", "/三国", "/sanguo"]
TRIGGER_WORDS = ["新游戏", "开始三国", "三国志略", "histrategy"]


def is_command(text: str) -> bool:
    """Check if text is a known command or trigger word."""
    text_lower = text.lower().strip()
    for prefix in COMMAND_PREFIXES:
        if text_lower.startswith(prefix):
            return True
    for word in TRIGGER_WORDS:
        if word in text_lower:
            return True
    return False


# ─── Command dispatch ──────────────────────────────────────

def handle_command(
    text: str, platform: str, chat_id: str, user_id: str, user_name: str
) -> dict:
    """Parse and execute a slash command."""
    text_lower = text.lower().strip()

    # Normalize: extract the part after the command prefix
    subcommand = text_lower
    for prefix in COMMAND_PREFIXES:
        if text_lower.startswith(prefix):
            subcommand = text_lower[len(prefix):].strip()
            break

    # /histrategy new [faction]
    if subcommand.startswith("new") or text_lower in ("新游戏", "开始三国"):
        parts = subcommand.split()
        faction = parts[1] if len(parts) > 1 and parts[1] in FACTION_CHOICES else None

        if faction:
            session, onboarding = create_new_session(platform, chat_id, faction)
            return {
                "platform": platform,
                "content": onboarding,
                "content_type": "markdown",
            }
        else:
            return {
                "platform": platform,
                "content": list_factions(),
                "content_type": "markdown",
            }

    # /histrategy load
    if subcommand.startswith("load"):
        session = load_or_create_session(platform, chat_id)
        if not session:
            return {
                "platform": platform,
                "content": (
                    "未找到存档。输入以下命令之一：\n\n"
                    "• `/histrategy new` — 开始新游戏\n"
                    "• `/histrategy new shu` — 直接以刘备势力开始"
                ),
                "content_type": "markdown",
            }
        engine = FormatEngine()
        return {
            "platform": platform,
            "content": engine.render_state_summary(session),
            "content_type": "markdown",
        }

    # /histrategy status
    if subcommand.startswith("status") or text_lower in ("查看状态", "状态"):
        session = load_or_create_session(platform, chat_id)
        if not session:
            return {
                "platform": platform,
                "content": "没有活跃的游戏会话。输入 `/histrategy new` 开始！",
                "content_type": "markdown",
            }
        engine = FormatEngine()
        return {
            "platform": platform,
            "content": engine.render_state_summary(session),
            "content_type": "markdown",
        }

    # /histrategy quit
    if subcommand.startswith("quit") or subcommand.startswith("exit"):
        manager = GameSessionManager()
        deleted = manager.delete_session(platform, chat_id)
        if deleted:
            return {
                "platform": platform,
                "content": "存档已删除。输入 `/histrategy new` 开始新游戏。",
                "content_type": "markdown",
            }
        return {
            "platform": platform,
            "content": "没有找到存档。",
            "content_type": "markdown",
        }

    # /histrategy join (multiplayer)
    if subcommand.startswith("join"):
        if chat_id not in MULTIPLAYER_SESSIONS:
            # Create new multiplayer session with this user as host
            mp = MultiplayerSession(session_id=chat_id, host_user_id=user_id)
            MULTIPLAYER_SESSIONS[chat_id] = mp

        mp = MULTIPLAYER_SESSIONS[chat_id]
        try:
            mp.add_player(user_id, user_name)
        except ValueError as e:
            return {
                "platform": platform,
                "content": f"加入失败: {e}",
                "content_type": "markdown",
            }

        return {
            "platform": platform,
            "content": mp.get_status_message(),
            "content_type": "markdown",
        }

    # /histrategy start (multiplayer)
    if subcommand.startswith("start"):
        mp = MULTIPLAYER_SESSIONS.get(chat_id)
        if not mp:
            return {
                "platform": platform,
                "content": "没有多人游戏会话。使用 `/histrategy join` 创建。",
                "content_type": "markdown",
            }
        if mp.host_user_id != user_id:
            return {
                "platform": platform,
                "content": "只有房主可以开始游戏。",
                "content_type": "markdown",
            }
        mp.start_game()
        return {
            "platform": platform,
            "content": mp.get_status_message(),
            "content_type": "markdown",
        }

    # /histrategy players (multiplayer)
    if subcommand.startswith("players") or subcommand.startswith("player"):
        mp = MULTIPLAYER_SESSIONS.get(chat_id)
        if not mp:
            return {
                "platform": platform,
                "content": "没有多人游戏会话。",
                "content_type": "markdown",
            }
        return {
            "platform": platform,
            "content": mp.get_status_message(),
            "content_type": "markdown",
        }

    # Unknown subcommand — show help
    return {
        "platform": platform,
        "content": (
            "🎌 **三國志略** — 命令列表\n\n"
            "• `/histrategy new [势力]` — 开始新游戏\n"
            "• `/histrategy load` — 加载存档\n"
            "• `/histrategy status` — 查看当前状态\n"
            "• `/histrategy quit` — 删除存档\n"
            "• `/histrategy join` — 加入多人游戏\n"
            "• `/histrategy start` — 开始多人游戏（房主）\n"
            "• `/histrategy players` — 查看多人游戏玩家\n\n"
            "或直接输入游戏指令，如「进攻洛阳」「招募步兵」"
        ),
        "content_type": "markdown",
    }
