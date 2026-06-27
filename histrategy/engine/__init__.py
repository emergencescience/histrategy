"""Game engine modules.

GameEngine is composed from modular mixins:
  - GameEngineCore   (engine/core.py)
  - IntroPlanMixin   (engine/intro_plan.py)
  - TurnProcessorMixin (engine/turn_processor.py)

Helper functions: engine/helpers.py
"""

__all__ = [
    "GameEngine",
    "OldGameWorld",
    # Re-exported helpers
    "FIRST_TURN_SUGGESTIONS",
    "apply_event_effects",
    "create_initial_world",
    "_suppress_stderr",
]

from .game import GameEngine

# Re-export commonly-used helpers
from .helpers import (  # noqa: E402
    FIRST_TURN_SUGGESTIONS,
    _suppress_stderr,
    apply_event_effects,
    create_initial_world,
)
from .world import GameWorld as OldGameWorld
