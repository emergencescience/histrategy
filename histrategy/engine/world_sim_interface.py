"""
Histrategy — World Simulation Engine Interface

All world simulation engines must implement this interface.
This enables the plugin architecture: any engine (LLM-based, offline, agent-based,
cron-driven, Rome-era, Red Alert, etc.) can be swapped in without changing the game loop.

Implementations:
  - LLMSimEngine        → llm/llm_sim_engine.py   (primary, requires API key)
  - OfflineSimEngine    → engine/offline_sim_engine.py  (fallback, always works)

  Auto-fallback (LLM→offline) is handled by _ResilientSimEngine in engine/core.py.

Plugin authors: subclass WorldSimEngine and register via pyproject.toml entry points:
  [project.entry-points."histrategy.plugins"]
  my_engine = "my_package.engine:MyEngine"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state.world_state import WorldState


# ─── SimResult ──────────────────────────────────────────────────


@dataclass
class SimResult:
    """Output of a single simulation step.

    This is a plain dataclass — UI-agnostic and JSON-serializable.
    Any decoration layer (Rich TUI, Web UI, Voice, Discord) renders this.
    """

    # Narrative
    narrative: str = ""
    aftermath: str = ""  # 1-3 sentence consequence summary

    # Execution detail
    bureaucracy: list[dict] = field(default_factory=list)
    # Each entry: {"department": str, "official": str, "action": str}

    # State changes
    short_term: dict = field(default_factory=dict)
    # {"changes": {"strength": N, "economy": N, ...}}
    state_changes: dict = field(default_factory=dict)
    # Flat dict of applied changes, for UI display

    # Long-term consequences
    seeds: list[dict] = field(default_factory=list)
    # Each entry: {"title": str, "description": str, "trigger_after": int, "type": str}

    # World events
    npc_reactions: list[str] = field(default_factory=list)
    npc_actions: list[str] = field(default_factory=list)  # aliases for offline compat
    events_occurred: list[str] = field(default_factory=list)

    # Updated state (engine must return this)
    world_state: WorldState | None = None

    # Game over / win condition
    game_over: dict | None = None

    # Source metadata
    engine_id: str = "unknown"
    used_llm: bool = False

    def to_dict(self) -> dict:
        """Serialize for JSON logging / export."""
        return {
            "narrative": self.narrative,
            "aftermath": self.aftermath,
            "bureaucracy": self.bureaucracy,
            "state_changes": self.state_changes,
            "seeds": self.seeds,
            "npc_reactions": self.npc_reactions,
            "events_occurred": self.events_occurred,
            "game_over": self.game_over,
            "engine_id": self.engine_id,
            "used_llm": self.used_llm,
        }


# ─── Abstract Engine ─────────────────────────────────────────────


class WorldSimEngine(ABC):
    """Abstract world simulation engine.

    Implement this to create a custom world simulation engine.
    The engine receives the current WorldState and the player's action,
    and returns a SimResult containing the updated world and narrative.

    The simulation is purely responsive (lazy): it only runs when the
    player sends a message. There are no background ticks or cron jobs.

    Example plugin registration (pyproject.toml):
        [project.entry-points."histrategy.plugins"]
        rome_engine = "histrategy_rome.engine:RomeWorldEngine"
    """

    @abstractmethod
    def simulate(
        self,
        state: WorldState,
        player_action: str,
    ) -> SimResult:
        """Advance the world by one turn in response to a player action.

        Args:
            state: Current complete world state.
            player_action: The player's free-text decision for this turn.

        Returns:
            SimResult with updated world state and narrative.
        """

    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Unique identifier for this engine (e.g. 'llm', 'offline', 'rome-llm')."""

    @property
    @abstractmethod
    def requires_llm(self) -> bool:
        """True if this engine requires a live LLM API to function."""

    def health_check(self) -> bool:
        """Return True if this engine is ready to simulate.

        Override in engines that may be unavailable (e.g. LLM API unreachable).
        """
        return True
