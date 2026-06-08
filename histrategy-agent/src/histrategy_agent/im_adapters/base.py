"""
IMAdapter — abstract base class for platform-specific message formatting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IMAdapter(ABC):
    """Abstract base for platform-specific message formatting."""

    MAX_MESSAGE_LENGTH: int = 15000

    @abstractmethod
    def format_message(self, content: str) -> dict:
        """Format content for the platform's message format."""

    @abstractmethod
    def format_error(self, error_message: str) -> dict:
        """Format an error message."""

    def split_long_message(self, content: str) -> list[str]:
        """Split content that exceeds MAX_MESSAGE_LENGTH."""
        if len(content) <= self.MAX_MESSAGE_LENGTH:
            return [content]

        chunks = []
        start = 0
        while start < len(content):
            end = start + self.MAX_MESSAGE_LENGTH
            # Try to split at a natural boundary
            if end < len(content):
                # Look for last newline or period near the limit
                for ch in ["\n\n", "\n", "。", "，", " "]:
                    last = content.rfind(ch, start, end)
                    if last > start + self.MAX_MESSAGE_LENGTH // 2:
                        end = last + len(ch)
                        break
            chunks.append(content[start:end])
            start = end
        return chunks
