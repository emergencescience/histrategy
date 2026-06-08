"""
FeishuAdapter — Feishu (Lark) platform-specific message formatting.
"""

from __future__ import annotations

from .base import IMAdapter


class FeishuAdapter(IMAdapter):
    """Feishu-specific message formatting.

    For MVP, renders content as markdown text since we can't use
    the Feishu API directly. Rich cards are rendered as formatted
    markdown.
    """

    MAX_MESSAGE_LENGTH = 15000
    PLATFORM = "feishu"

    def format_message(self, content: str) -> dict:
        """Return a Feishu-compatible message dict."""
        return {
            "platform": "feishu",
            "content": content,
            "content_type": "markdown",
        }

    def format_error(self, error_message: str) -> dict:
        """Return error message with Feishu formatting."""
        return {
            "platform": "feishu",
            "content": f"❌ **错误**\n\n{error_message}",
            "content_type": "markdown",
        }

    def render_interactive_card(
        self, title: str, body: str, actions: list[dict]
    ) -> dict:
        """Build a Feishu card-like structure rendered as markdown.

        For MVP, renders as formatted markdown instead of actual
        Feishu interactive cards.
        """
        lines = [f"📌 **{title}**", "", body, ""]
        if actions:
            lines.append("---")
            for action in actions:
                label = action.get("label", action.get("text", ""))
                value = action.get("value", "")
                lines.append(f"- [{label}] — {value}")
        content = "\n".join(lines)

        return {
            "platform": "feishu",
            "content": content,
            "content_type": "markdown",
        }

    @staticmethod
    def detect() -> bool:
        """Auto-detect if running in Feishu context.

        Always returns True for MVP since Feishu is the primary platform.
        """
        return True
