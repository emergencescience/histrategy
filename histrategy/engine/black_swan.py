"""
Black Swan Injector — stochastically triggers historical events.

Works with the existing HistoryEngine but adds probability-based
triggering based on historical gravity and player deviation.

For the macro engine, battles (赤壁, 官渡) and character deaths
(刘表, 周瑜) are treated as black swan events that the LLM can trigger
or avert based on the game state.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


class BlackSwanInjector:
    """Injects historically-plausible random events into the simulation.

    Events are defined in knowledge/data/ and have:
    - history_gravity: how strongly history "wants" this to happen (0-1)
    - preconditions: what must be true for this event to be possible
    - effects: what happens when triggered
    """

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self._triggered: set[str] = set()      # already triggered this game
        self._averted: set[str] = set()        # explicitly averted
        self._blocked_downstream: set[str] = set()  # downstream events blocked

    def check_events(
        self,
        year: int,
        season,  # Season | str — passed through to HistoryEngine
        world_state: WorldState,
        deviation: float = 0.05,
        history_engine=None,
    ) -> list[dict]:
        """Check which historical events can/should trigger this quarter.

        Args:
            year, season: Current game time
            world_state: Current world state
            deviation: Player deviation from history (0-1, higher = more averted events)
            history_engine: Optional existing HistoryEngine for event definitions

        Returns:
            List of event proposals, each with {event_id, title, triggered, effects, narrative}
        """
        proposals: list[dict] = []

        # If we have a history_engine, use its event definitions
        if history_engine:
            try:
                raw_proposals = history_engine.check_events(
                    year, season, world_state, deviation=deviation
                )
                for prop in raw_proposals:
                    event_id = prop.event_id if hasattr(prop, "event_id") else prop.get("event_id", "")
                    if event_id and event_id not in self._triggered:
                        # Apply stochastic triggering based on gravity
                        gravity = getattr(prop, "history_gravity", 0.8) if hasattr(prop, "history_gravity") else prop.get("history_gravity", 0.8)
                        triggered = self._roll(gravity, deviation)
                        proposals.append({
                            "event_id": event_id,
                            "title": getattr(prop, "title", "") if hasattr(prop, "title") else prop.get("title", ""),
                            "gravity": gravity,
                            "triggered": triggered,
                            "effects": getattr(prop, "effects", {}) if hasattr(prop, "effects") else prop.get("effects", {}),
                            "outcome": "triggered" if triggered else "averted",
                        })
                        if triggered:
                            self._triggered.add(event_id)
                            self._block_downstream(event_id, history_engine)
            except Exception as e:
                import logging
                logging.getLogger("histrategy").warning(f"BlackSwanInjector.check_events failed: {e}")

        return proposals

    def _roll(self, gravity: float, deviation: float) -> bool:
        """Roll for event triggering.

        gravity=0.95, deviation=0.05 → ~90% chance (highly likely)
        gravity=0.80, deviation=0.3  → ~55% chance (player diverged a lot)
        """
        adjusted = gravity * (1.0 - deviation * 0.5)
        return self._rng.random() < adjusted

    def _block_downstream(self, event_id: str, history_engine) -> None:
        """Block downstream events that depend on this one."""
        try:
            if hasattr(history_engine, "block_downstream"):
                history_engine.block_downstream(event_id)
                self._blocked_downstream.update(getattr(history_engine, "_blocked_downstream", set()))
        except Exception:
            pass

    def get_blocked_events(self) -> set[str]:
        """Get set of all blocked downstream event IDs."""
        return self._blocked_downstream

    def inject_event(
        self,
        event_id: str,
        effects: dict,
        world_state: WorldState,
    ) -> None:
        """Manually inject a black swan event's effects into world state."""
        # Apply territory transfers
        for key, value in effects.items():
            if key.endswith("_owner") and value:
                # e.g., "jingzhou_owner": "cao"
                territory_group = key.replace("_owner", "")
                # Handle specific groups
                if territory_group == "jingzhou":
                    for tid in ["xiangyang", "jiangling", "jiangkou", "changsha"]:
                        if tid in world_state.territories:
                            world_state.territories[tid].owner_id = value

            elif key.endswith("_dead") and value is True:
                char_id = key.replace("_dead", "")
                if char_id in world_state.characters:
                    world_state.characters[char_id].alive = False

            elif key.endswith("_location") and value:
                char_id = key.replace("_location", "")
                if char_id in world_state.characters:
                    world_state.characters[char_id].location = value

            elif key.endswith("_faction") and value:
                char_id = key.replace("_faction", "")
                if char_id in world_state.characters:
                    world_state.characters[char_id].faction_id = value

        self._triggered.add(event_id)
