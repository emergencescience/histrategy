#!/usr/bin/env python3
"""Hermes Agent skill entry point for 三國志略 (Histrategy).

Called by the Hermes Agent skill dispatch system when:
- User sends a slash command: /histrategy, /三国, /sanguo
- User sends a message matching trigger words
- A game session is active and the user sends input
"""

import json
import sys
from pathlib import Path

# Ensure histrategy-agent is importable
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENT_DIR / "src"))

from histrategy_agent.format_engine import FormatEngine
from histrategy_agent.im_adapters.feishu import FeishuAdapter
from histrategy_agent.session import GameSessionManager
from histrategy_agent.turn_processor import TurnProcessor


def _get_adapter(platform: str = "feishu"):
    """Get the IM adapter for the given platform."""
    if platform == "feishu":
        return FeishuAdapter()
    # Fallback to Feishu for unknown platforms
    return FeishuAdapter()


def handle_new_game(platform: str, chat_id: str, user_id: str, faction: str = "") -> dict:
    """Start a new game. If faction is empty, return faction selection prompt."""
    manager = GameSessionManager()
    engine = FormatEngine()

    if not faction:
        # Return faction selection prompt
        return {
            "text": (
                "🎌 **三國志略** — 选择你的势力\n\n"
                "1. **刘备** 🟢 — 汉室宗亲，仁义立世，寄居新野\n"
                "2. **曹操** 🔵 — 汉丞相，雄才大略，挟天子以令诸侯\n"
                "3. **孙权** 🔴 — 江东之主，继承父兄基业，坐断东南\n"
                "4. **刘表** 🟡 — 荆州牧，据守荆襄，坐观天下\n"
                "5. **刘璋** 🟣 — 益州牧，天府之国，固守一方\n\n"
                "请回复势力名称或编号。"
            ),
        }

    session = manager.get_or_create(platform, chat_id, faction_id=faction)
    return {"text": engine.render_onboarding(session)}


def handle_turn(platform: str, chat_id: str, user_id: str, text: str) -> dict:
    """Process a game turn from user input."""
    manager = GameSessionManager()
    processor = TurnProcessor()
    engine = FormatEngine()
    adapter = _get_adapter(platform)

    # Handle slash commands
    cmd = text.strip().lower()
    if cmd in ("/histrategy new", "新游戏", "开始"):
        return handle_new_game(platform, chat_id, user_id)

    if cmd in ("/histrategy load", "加载", "读档"):
        session = manager.get_session(platform, chat_id)
        if not session:
            return {"text": "⚠️ 没有找到存档。输入「新游戏」开始。"}
        return {"text": engine.render_state_summary(session)}

    if cmd in ("/histrategy status", "/histrategy", "状态", "局势", "情报"):
        session = manager.get_session(platform, chat_id)
        if not session:
            return {"text": "⚠️ 游戏未开始。输入「新游戏」开始。"}
        return {"text": engine.render_state_summary(session)}

    if cmd in ("/histrategy help", "帮助", "help"):
        return {
            "text": (
                "🎌 **三國志略 帮助**\n\n"
                "**命令**\n"
                "- `新游戏` — 开始新游戏\n"
                "- `状态` — 查看当前局势\n"
                "- `加载` — 加载存档\n\n"
                "**游戏指令**（自然语言）\n"
                "- 「进攻洛阳」— 攻击敌方领地\n"
                "- 「招募步兵」— 招募军队\n"
                "- 「开发农业」— 发展领地\n"
                "- 「与孙权结盟」— 外交行动\n\n"
                "**多人模式**（群聊）\n"
                "- `/histrategy join` — 加入游戏\n"
                "- 回合制轮流行动"
            ),
        }

    if cmd in ("/histrategy delete", "删除存档"):
        deleted = manager.delete_session(platform, chat_id)
        if deleted:
            return {"text": "✅ 存档已删除。输入「新游戏」重新开始。"}
        return {"text": "⚠️ 没有找到存档。"}

    # Process game turn
    session = manager.get_session(platform, chat_id)
    if not session:
        return {
            "text": ("⚠️ 游戏未开始。输入「新游戏」开始。\n\n可选势力：刘备、曹操、孙权、刘表、刘璋"),
        }

    result = processor.process(session, text)
    manager.save_session(session)

    output = engine.render_turn_result(result, platform)
    formatted = adapter.format_message(output)
    return {"text": formatted.get("content", output)}


def main():
    """CLI entry point for direct testing."""
    if len(sys.argv) < 2:
        print("Usage: entry.py <command> [args...]")
        print("Commands: new <faction>, turn <text>, status, load, delete")
        sys.exit(1)

    command = sys.argv[1]

    if command == "new":
        faction = sys.argv[2] if len(sys.argv) > 2 else ""
        result = handle_new_game("cli", "test", "user", faction)
    elif command == "turn":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "状态"
        result = handle_turn("cli", "test", "user", text)
    elif command == "status":
        result = handle_turn("cli", "test", "user", "/histrategy status")
    elif command == "load":
        result = handle_turn("cli", "test", "user", "/histrategy load")
    elif command == "delete":
        result = handle_turn("cli", "test", "user", "/histrategy delete")
    else:
        result = {"text": f"Unknown command: {command}"}

    print(result.get("text", json.dumps(result, ensure_ascii=False)))


if __name__ == "__main__":
    main()
