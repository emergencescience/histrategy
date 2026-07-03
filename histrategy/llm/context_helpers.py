"""Shared context-building helpers for LLM prompt construction.

Centralizes logic that was duplicated across game_master.py and narrative.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


def collect_dead_characters(world_state: WorldState) -> list[str]:
    """Collect names of deceased/inactive characters that must not be revived.

    Builds a list of character names that the LLM should never bring back
    or depict as taking active actions. Includes hard-coded fallbacks for
    characters known to be dead at game start but possibly missing from
    the character registry.

    Used by GameMaster plan/command context builders and NarrativeEngine.
    """
    dead = [c.name for c in world_state.characters.values() if not c.alive]

    # Hard-coded characters known to be dead at scenario start
    _known_dead = {
        "dongzhuo": "\u8463\u5353",  # Dong Zhuo
        "liubiao": "\u5218\u8868",    # Liu Biao
    }

    for char_id, char_name in _known_dead.items():
        if (
            char_id not in world_state.characters
            or not world_state.characters[char_id].alive
        ) and char_name not in dead:
            dead.append(char_name)

    return dead


# Shared knowledge data directory — V1 legacy engine data
# (schema differs from scenarios/three-kingdoms/knowledge/ — keep separate)
KNOWLEDGE_DATA_DIR = Path(__file__).parent.parent / "knowledge" / "data"
