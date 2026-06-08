"""IM platform adapters for message formatting."""

from .base import IMAdapter
from .feishu import FeishuAdapter

__all__ = ["IMAdapter", "FeishuAdapter"]
