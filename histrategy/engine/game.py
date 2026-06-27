"""
三國志略 — Game Engine

The engine orchestrates the GameMaster (LLM-driven), world state,
and player memory. It provides a unified interface for the CLI.

This file composes GameEngine from modular mixins:
  - GameEngineCore   (engine/core.py):  initialization, engine stack, save/load
  - IntroPlanMixin   (engine/intro_plan.py):  intro scene, plan data, fallbacks
  - TurnProcessorMixin (engine/turn_processor.py):  all process_turn variants

Helper functions and constants live in engine/helpers.py.
"""

from __future__ import annotations

# ── Compose GameEngine from mixins ────────────────────────────────
from .core import GameEngineCore
from .intro_plan import IntroPlanMixin
from .turn_processor import TurnProcessorMixin


class GameEngine(GameEngineCore, IntroPlanMixin, TurnProcessorMixin):
    """
    Main game engine orchestrating world state and LLM interaction.

    Composed from:
      - GameEngineCore:   __init__, engine stack, save/load, faction setup
      - IntroPlanMixin:   get_intro_scene, get_plan_data, fallbacks
      - TurnProcessorMixin: process_turn and all variants

    v2 mode (default): Uses the 7-engine physics backend + NarrativeEngine.
    v1 fallback: Uses GameMaster (LLM) or offline_sim (template-based).
    """
    pass


# ── Backward-compatible re-exports ────────────────────────────────
# Everything that external code imports from histrategy.engine.game
from .helpers import (  # noqa: F401, E402
    FIRST_TURN_SUGGESTIONS,
    _auto_mobilize_for_attack,
    _build_faction_id_map,
    _build_territory_id_map,
    _inject_v3_into_baseline,
    _suppress_stderr,
    apply_event_effects,
    create_initial_world,
)
