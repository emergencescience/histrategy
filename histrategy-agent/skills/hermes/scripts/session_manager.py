"""Session management helpers for the Hermes Agent skill.

Wraps GameSessionManager with platform-specific defaults and error handling.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CORE_PATH = Path(__file__).parent.parent.parent.parent / "src"
if str(_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_CORE_PATH))

from histrategy_agent.session import GameSessionManager


# ─── Faction selection helpers ─────────────────────────────

FACTION_CHOICES = {
    "shu": "刘备（蜀）— 汉室宗亲，仁义立世，以匡扶汉室为己任。初始领地：新野",
    "cao": "曹操（魏）— 汉丞相，雄才大略，挟天子以令诸侯。初始领地：许昌等六城",
    "wu": "孙权（吴）— 江东少主，继承父兄基业，坐断东南。初始领地：建业等三城",
    "liubiao": "刘表（荆）— 荆州牧，坐拥荆襄富庶之地。初始领地：襄阳、江陵",
    "liuzhang": "刘璋（益）— 益州牧，据守天府之国。初始领地：成都、汉中",
}

DEFAULT_FACTION = "shu"
DEFAULT_SCENARIO = "207"


def load_or_create_session(platform: str, chat_id: str):
    """Load existing session or return None (caller should prompt for new game)."""
    manager = GameSessionManager()
    return manager.get_session(platform, chat_id)


def create_new_session(
    platform: str, chat_id: str, faction_id: str = DEFAULT_FACTION
):
    """Create a fresh game session and return it with onboarding text."""
    manager = GameSessionManager()

    # Delete any existing session first
    manager.delete_session(platform, chat_id)

    session = manager.get_or_create(
        platform, chat_id, faction_id=faction_id, scenario=DEFAULT_SCENARIO
    )

    from histrategy_agent.format_engine import FormatEngine

    engine = FormatEngine()
    onboarding = engine.render_onboarding(session)

    return session, onboarding


def list_factions() -> str:
    """Return a markdown-formatted faction selection menu."""
    lines = ["🎌 **选择你的势力**", ""]
    for fid, desc in FACTION_CHOICES.items():
        lines.append(f"• **{fid}** — {desc}")
    lines.append("")
    lines.append("输入势力代码开始游戏，如 `/histrategy new shu`")
    return "\n".join(lines)


def get_faction_info(faction_id: str) -> str | None:
    """Get description for a faction ID."""
    return FACTION_CHOICES.get(faction_id)
