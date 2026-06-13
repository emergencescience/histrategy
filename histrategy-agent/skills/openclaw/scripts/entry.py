#!/usr/bin/env python3
"""OpenClaw skill entry point for 三國志略 (Histrategy).

Called by the OpenClaw skill dispatch system when:
- User sends a trigger word: /histrategy, /三国, /sanguo, 三国志略
- A game session is active for this chat

Reads JSON from stdin (OpenClaw convention), returns JSON to stdout.
"""

import json
import sys
from pathlib import Path

# Ensure histrategy-agent is importable
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENT_DIR / "src"))

from histrategy_agent.format_engine import FormatEngine  # noqa: E402
from histrategy_agent.im_adapters.feishu import FeishuAdapter  # noqa: E402
from histrategy_agent.session import GameSessionManager  # noqa: E402
from histrategy_agent.turn_processor import TurnProcessor  # noqa: E402


def _get_adapter(platform: str = "feishu"):
    """Get the IM adapter for the given platform."""
    if platform == "feishu":
        return FeishuAdapter()
    return FeishuAdapter()


def handle_message(message: dict) -> dict:
    """Main entry point called by OpenClaw skill runtime.

    message fields:
        platform: str — "feishu", "telegram", etc.
        chat_id: str — IM chat/group ID
        user_id: str — sender ID
        text: str — message content
    """
    platform = message.get("platform", "feishu")
    chat_id = message.get("chat_id", "")
    message.get("user_id", "")
    text = message.get("text", "").strip()

    manager = GameSessionManager()
    processor = TurnProcessor()
    engine = FormatEngine()
    adapter = _get_adapter(platform)

    # ---- Commands ----

    if text in ("/histrategy new", "/三国 new", "/sanguo new", "新游戏", "开始"):
        # Faction selection prompt
        return {
            "text": (
                "🎌 **三國志略** — Choose your faction\n\n"
                "1. **刘备 (Liu Bei)** 🟢 — Imperial scion, virtue and righteousness\n"
                "2. **曹操 (Cao Cao)** 🔵 — Imperial Chancellor, ambition incarnate\n"
                "3. **孙权 (Sun Quan)** 🔴 — Lord of Jiangdong, naval supremacy\n"
                "4. **刘表 (Liu Biao)** 🟡 — Governor of Jing, observer of chaos\n"
                "5. **刘璋 (Liu Zhang)** 🟣 — Governor of Yi, land of abundance\n\n"
                "Reply with faction name or number."
            ),
        }

    if text in ("/histrategy load", "/三国 load", "加载", "读档"):
        session = manager.get_session(platform, chat_id)
        if not session:
            return {"text": "⚠️ No saved game found. Type '/histrategy new' to start."}
        return {"text": engine.render_state_summary(session)}

    if text in ("/histrategy status", "/histrategy", "/三国", "/sanguo", "状态", "情报"):
        session = manager.get_session(platform, chat_id)
        if not session:
            return {"text": "⚠️ No game active. Type '/histrategy new' to start."}
        return {"text": engine.render_state_summary(session)}

    if text in ("/histrategy help", "帮助"):
        return {
            "text": (
                "🎌 **Histrategy Help**\n\n"
                "**Commands**\n"
                "- `/histrategy new` — Start a new campaign\n"
                "- `/histrategy status` — View current state\n"
                "- `/histrategy load` — Load saved game\n\n"
                "**Gameplay** (natural language)\n"
                "- 「Attack Luoyang」— Launch an attack\n"
                "- 「Recruit infantry」— Raise troops\n"
                "- 「Develop agriculture」— Improve territory\n"
                "- 「Ally with Sun Quan」— Diplomacy\n\n"
                "**Multiplayer** (group chat)\n"
                "- `/histrategy join` — Join a game\n"
                "- Turn-based: one player per faction"
            ),
        }

    if text in ("/histrategy delete", "删除存档"):
        deleted = manager.delete_session(platform, chat_id)
        if deleted:
            return {"text": "✅ Save deleted. Type '/histrategy new' to restart."}
        return {"text": "⚠️ No save found."}

    # ---- Faction selection ----
    faction_map = {
        "刘备": "shu",
        "liubei": "shu",
        "shu": "shu",
        "1": "shu",
        "曹操": "cao",
        "caocao": "cao",
        "cao": "cao",
        "2": "cao",
        "孙权": "wu",
        "sunquan": "wu",
        "wu": "wu",
        "3": "wu",
        "刘表": "liubiao",
        "liubiao": "liubiao",
        "4": "liubiao",
        "刘璋": "liuzhang",
        "liuzhang": "liuzhang",
        "5": "liuzhang",
    }
    faction_id = faction_map.get(text)
    if faction_id and not manager.get_session(platform, chat_id):
        session = manager.get_or_create(platform, chat_id, faction_id=faction_id)
        return {"text": engine.render_onboarding(session)}

    # ---- Game turn ----
    session = manager.get_session(platform, chat_id)
    if not session:
        return {
            "text": (
                "⚠️ No game active. Type '/histrategy new' to start.\n\nAvailable factions: 刘备, 曹操, 孙权, 刘表, 刘璋"
            ),
        }

    result = processor.process(session, text)
    manager.save_session(session)

    output = engine.render_turn_result(result, platform)
    return adapter.format_message(output)


def main():
    """Read JSON from stdin, process, write JSON to stdout."""
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    output = handle_message(input_data)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
