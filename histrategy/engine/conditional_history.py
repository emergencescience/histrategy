"""ConditionalHistoryEngine — injects historical context into NPC LLM decisions.

Loads events from scenarios/{name}/rules/historical_events.yaml and evaluates
whether each event is still relevant based on current world state. Only events
whose preconditions are met AND whose cancellation conditions haven't been
triggered are injected into NPC decision context.

Key design: events are CONDITIONAL predictions, not forced outcomes.
If the player changes history (e.g., conquers Jingzhou before Liu Biao dies),
the corresponding events become irrelevant and are suppressed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

logger = logging.getLogger("histrategy.history_events")

# ── Language labels for injected context headers ──────────────
_HEADERS = {
    "zh": "## 📜 天下大势（当前可能的走向）",
    "en": "## 📜 The Realm's Current Trajectory",
}

_FOOTERS = {
    "zh": "请在你的决策中考虑以上形势，但不可将这些预测视为必然——天下大势随时可能因各方行动而改变。",
    "en": "Consider the above in your decision, but do not treat these predictions as certain — "
    "the situation can change at any moment due to actions by any faction.",
}


class ConditionalHistoryEngine:
    """Evaluates historical event conditions and produces injectable context."""

    def __init__(self, scenario: str | None = None, language: str = "zh"):
        self._language = language
        self._events: list[dict] = []
        self._scenario = scenario

        if scenario:
            self._load(scenario)

    def _load(self, scenario: str) -> None:
        """Load historical_events.yaml for the given scenario."""
        candidates = [
            Path(f"scenarios/{scenario}/rules/historical_events.yaml"),
            Path(f"scenarios/{scenario}/rules/historical_events.yml"),
        ]
        for p in candidates:
            if p.is_file():
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8"))
                    self._events = data.get("events", []) if isinstance(data, dict) else []
                    logger.info(
                        "Loaded %d conditional historical events for scenario=%s",
                        len(self._events),
                        scenario,
                    )
                    return
                except Exception:
                    logger.warning("Failed to load historical events from %s", p)

    # ── Condition checkers ──────────────────────────────────

    @staticmethod
    def _check_precondition(ws: WorldState, cond: dict) -> bool:
        """Evaluate a single precondition dict against the world state."""
        for key, value in cond.items():
            if key == "faction_exists":
                return value in ws.factions
            elif key == "faction_alive":
                f = ws.factions.get(value)
                return f is not None and getattr(f, "is_active", True)
            elif key == "territory_owned":
                fid, tid = value
                t = ws.territories.get(tid)
                return t is not None and getattr(t, "owner_id", None) == fid
            elif key == "faction_stat_lt":
                fid, attr, threshold = value
                f = ws.factions.get(fid)
                if f is None:
                    return False
                return getattr(f, attr, 0) < threshold
            elif key == "faction_stat_gte":
                fid, attr, threshold = value
                f = ws.factions.get(fid)
                if f is None:
                    return False
                return getattr(f, attr, 0) >= threshold
            elif key == "faction_owns":
                fid, tid = value
                f = ws.factions.get(fid)
                if f is None:
                    return False
                return tid in getattr(f, "territories", [])
            elif key == "faction_at_war":
                f1, f2 = value
                f1_obj = ws.factions.get(f1)
                if f1_obj is None:
                    return False
                relations = getattr(f1_obj, "relations", {})
                return relations.get(f2, 0) < -30
        return True

    # ── Main interface ─────────────────────────────────────

    def get_active_context(self, ws: WorldState) -> str | None:
        """Return context string for all currently-active historical events.

        Returns None if no events are active.
        """
        if not self._events:
            return None

        is_en = self._language.startswith("en")
        header = _HEADERS["en" if is_en else "zh"]
        footer = _FOOTERS["en" if is_en else "zh"]
        current_year = ws.year
        current_season = getattr(ws, "current_season", "spring")
        if hasattr(current_season, "value"):
            current_season = current_season.value

        active: list[str] = []

        for evt in self._events:
            # Year/season check
            yr_range = evt.get("year_range", [current_year, current_year + 10])
            if not (yr_range[0] <= current_year <= yr_range[1]):
                continue

            evt_season = evt.get("season", "any")
            if evt_season != "any" and evt_season != current_season:
                continue

            # Preconditions: ALL must pass
            preconditions = evt.get("preconditions", [])
            all_pre = all(
                self._check_precondition(ws, cond) for cond in preconditions
            )
            if not all_pre:
                continue

            # Cancellations: if ANY fires, event is suppressed
            cancel_conditions = evt.get("cancel_if", [])
            any_cancelled = any(
                self._check_precondition(ws, cond) for cond in cancel_conditions
            )
            if any_cancelled:
                continue

            # Event is active — inject context
            ctx_key = "context_for_npc_en" if is_en else "context_for_npc"
            ctx = evt.get(ctx_key, "")
            if ctx:
                active.append(f"- **{evt['title']}**: {ctx.strip()}")

        if not active:
            return None

        return header + "\n\n" + "\n\n".join(active) + "\n\n" + footer

    @property
    def event_count(self) -> int:
        """Number of loaded events (for debugging)."""
        return len(self._events)
