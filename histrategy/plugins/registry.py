"""Plugin registry — discover plugins via Python entry points.

Plugins register themselves in their own pyproject.toml:
    [project.entry-points."histrategy.plugins"]
    my_plugin = "my_package.plugin:MyPlugin"

After pip install, histrategy automatically discovers them.
No changes to histrategy core are required.
"""

from __future__ import annotations

import importlib.metadata
import logging

from .interface import HistrategyPlugin, PluginType

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "histrategy.plugins"


def discover_plugins() -> list[HistrategyPlugin]:
    """Load and return all registered histrategy plugins.

    Plugins that fail to load are logged and skipped (never crash the game).
    """
    plugins: list[HistrategyPlugin] = []
    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:
        logger.debug("Plugin discovery failed: %s", exc)
        return plugins

    for ep in eps:
        try:
            cls = ep.load()
            instance = cls()
            if not isinstance(instance, HistrategyPlugin):
                logger.warning("Plugin %s is not a HistrategyPlugin subclass", ep.name)
                continue
            plugins.append(instance)
            logger.info("Loaded plugin: %s (%s)", instance.plugin_id, instance.plugin_type)
        except Exception as exc:
            logger.warning("Failed to load plugin %s: %s", ep.name, exc)

    return plugins


def get_plugins_by_type(
    plugins: list[HistrategyPlugin],
    plugin_type: PluginType,
) -> list[HistrategyPlugin]:
    """Filter plugins by type."""
    return [p for p in plugins if p.plugin_type == plugin_type]


def get_world_engine_plugin(plugins: list[HistrategyPlugin]):
    """Return the first registered WorldEnginePlugin, or None."""
    from .interface import WorldEnginePlugin
    for p in plugins:
        if isinstance(p, WorldEnginePlugin):
            return p
    return None
