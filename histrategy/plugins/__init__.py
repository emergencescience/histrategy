"""Histrategy plugin system."""

from .interface import (
    HistrategyPlugin,
    KnowledgePlugin,
    NarrativePlugin,
    NPCAgentPlugin,
    PluginType,
    UIPlugin,
    WorldEnginePlugin,
)
from .registry import discover_plugins, get_plugins_by_type, get_world_engine_plugin

__all__ = [
    "HistrategyPlugin",
    "PluginType",
    "WorldEnginePlugin",
    "KnowledgePlugin",
    "NPCAgentPlugin",
    "UIPlugin",
    "NarrativePlugin",
    "discover_plugins",
    "get_plugins_by_type",
    "get_world_engine_plugin",
]
