"""Histrategy plugin system — base classes and PluginType enum.

Plugin authors: subclass the appropriate base class and register via
pyproject.toml entry points. See CONTRIBUTING.md for details.

Plugin types:
  - WorldEnginePlugin  — alternate simulation engine (Rome, Red Alert, agent-based, etc.)
  - KnowledgePlugin    — alternate history knowledge base (Rome, other Three Kingdoms eras)
  - NPCAgentPlugin     — alternate NPC behavior engine (full agent, cron-driven, etc.)
  - UIPlugin           — alternate UI/rendering layer (Web, Voice, Discord, API)
  - NarrativePlugin    — alternate narrative director (branching VN, custom retrospective)

Future separate repos (when plugin counts justify it):
  - github.com/emergencescience/histrategy-world    (WorldEnginePlugin implementations)
  - github.com/emergencescience/histrategy-history  (KnowledgePlugin implementations)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.world_sim_interface import SimResult
    from ..state.world_state import WorldState


class PluginType(Enum):
    WORLD_ENGINE = "world_engine"
    KNOWLEDGE = "knowledge"
    NPC_AGENT = "npc_agent"
    UI = "ui"
    NARRATIVE = "narrative"


# ─── Base Plugin ──────────────────────────────────────────────────


class HistrategyPlugin(ABC):
    """Base class for all histrategy plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier, e.g. 'rome-knowledge', 'agent-npc-engine'."""

    @property
    @abstractmethod
    def plugin_type(self) -> PluginType:
        """Plugin category."""

    @property
    def version(self) -> str:
        """Plugin version string."""
        return "0.1.0"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return ""


# ─── WorldEnginePlugin ────────────────────────────────────────────


class WorldEnginePlugin(HistrategyPlugin):
    """Implement a custom world simulation engine.

    Example use cases:
      - Rome-era strategic simulation
      - Red Alert Cold War simulation
      - Full LLM-agent NPC engine (Tier 3)
      - Cron-driven background simulation with push notifications

    Example (pyproject.toml):
        [project.entry-points."histrategy.plugins"]
        rome_engine = "histrategy_rome.engine:RomeWorldEngine"
    """

    plugin_type = PluginType.WORLD_ENGINE

    @abstractmethod
    def simulate(self, state: WorldState, action: str) -> SimResult:
        """Advance the world by one turn in response to a player action."""

    @property
    def requires_llm(self) -> bool:
        return True

    def health_check(self) -> bool:
        return True


# ─── KnowledgePlugin ─────────────────────────────────────────────


class KnowledgePlugin(HistrategyPlugin):
    """Provide an alternate historical knowledge base.

    The knowledge base is a set of characters, factions, regions, and events
    for a specific historical setting (Three Kingdoms, Rome, WWII, etc.).

    The plugin replaces or extends the default knowledge/data/ JSON files.

    Example (pyproject.toml):
        [project.entry-points."histrategy.plugins"]
        rome_knowledge = "histrategy_rome.knowledge:RomeKnowledgePlugin"
    """

    plugin_type = PluginType.KNOWLEDGE

    @abstractmethod
    def get_characters(self) -> list[dict]:
        """Return list of character dicts matching characters.json schema."""

    @abstractmethod
    def get_factions(self) -> list[dict]:
        """Return list of faction dicts matching factions.json schema."""

    @abstractmethod
    def get_regions(self) -> list[dict]:
        """Return list of region dicts matching regions.json schema."""

    @abstractmethod
    def get_events(self) -> list[dict]:
        """Return list of historical event dicts matching events.json schema."""

    def get_arc_goals(self) -> list[dict]:
        """Return list of narrative arc goals for this setting. Optional."""
        return []


# ─── NPCAgentPlugin ──────────────────────────────────────────────


class NPCAgentPlugin(HistrategyPlugin):
    """Provide an alternate NPC behavior engine.

    Default: Tier 1 NPCInterpreter (bounded mood states + batch LLM call).
    Advanced: Full agent loop, cron-driven NPC actions, etc.

    Example (pyproject.toml):
        [project.entry-points."histrategy.plugins"]
        agent_npc = "histrategy_agents.npc:FullAgentNPCPlugin"
    """

    plugin_type = PluginType.NPC_AGENT

    @abstractmethod
    def interpret(
        self,
        state: WorldState,
        player_action: str,
        npc_states: dict,
    ) -> dict[str, dict]:
        """Return NPC update dicts keyed by character_id."""


# ─── UIPlugin ────────────────────────────────────────────────────


class UIPlugin(HistrategyPlugin):
    """Decorate the headless engine with a UI.

    The headless core produces SimResult (plain dataclass).
    A UIPlugin renders SimResult and collects player input.

    Example use cases:
      - Rich TUI (current default)
      - Next.js web app
      - Voice interaction (TTS + STT)
      - Discord bot
      - REST API server

    Example (pyproject.toml):
        [project.entry-points."histrategy.plugins"]
        web_ui = "histrategy_web.ui:WebUIPlugin"
    """

    plugin_type = PluginType.UI

    @abstractmethod
    def render(self, sim_result: SimResult) -> None:
        """Render a SimResult to the user."""

    @abstractmethod
    def get_player_input(self, prompt: str) -> str:
        """Collect and return player input."""


# ─── NarrativePlugin ─────────────────────────────────────────────


class NarrativePlugin(HistrategyPlugin):
    """Provide an alternate narrative director.

    Default: NarrativeDirector (arc goal steering).
    Advanced: Branching visual novel structure, retrospective narrator, etc.
    """

    plugin_type = PluginType.NARRATIVE

    @abstractmethod
    def get_pressure_hint(self, state: WorldState) -> str:
        """Return a steering hint for the current turn."""
