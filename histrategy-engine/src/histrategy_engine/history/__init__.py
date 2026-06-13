"""
History Engine — determines which historical events trigger based on
deviation from the historical timeline.

Core formula:
  effective_prob = event.gravity * (1.0 - deviation * 0.5)
  If random < effective_prob → event triggers
  Else → mark as averted, block downstream butterfly effects
"""

from __future__ import annotations

import json
import os
import random
from typing import TYPE_CHECKING

from ..world import EventProposal, Season, WorldState

if TYPE_CHECKING:
    pass


class HistoryEngine:
    """Evaluates historical events against the current world state."""

    def __init__(self, knowledge_path: str):
        """Load knowledge base JSON files from the given path."""
        self.knowledge_path = knowledge_path
        self._timeline: list[dict] = []
        self._characters: list[dict] = []
        self._scenarios: dict = {}
        self._territories: dict = {}
        self._event_index: dict[str, dict] = {}
        self._averted_events: dict[str, str] = {}  # event_id → reason
        self._blocked_downstream: set[str] = set()
        self._triggered_events: set[str] = set()

        self._load_knowledge()

    def _load_knowledge(self) -> None:
        """Load all knowledge files."""
        # Load timeline
        timeline_dir = os.path.join(self.knowledge_path, "timeline")
        if os.path.isdir(timeline_dir):
            for fname in sorted(os.listdir(timeline_dir)):
                if fname.endswith(".json"):
                    fpath = os.path.join(timeline_dir, fname)
                    with open(fpath) as f:
                        data = json.load(f)
                        if "events" in data:
                            self._timeline.extend(data["events"])

        # Build event index by id
        for evt in self._timeline:
            self._event_index[evt["id"]] = evt

        # Load characters
        char_dir = os.path.join(self.knowledge_path, "characters")
        if os.path.isdir(char_dir):
            for fname in os.listdir(char_dir):
                if fname.endswith(".json"):
                    fpath = os.path.join(char_dir, fname)
                    with open(fpath) as f:
                        data = json.load(f)
                        if "characters" in data:
                            self._characters.extend(data["characters"])

        # Load scenarios
        scenario_dir = os.path.join(self.knowledge_path, "scenarios")
        if os.path.isdir(scenario_dir):
            for fname in os.listdir(scenario_dir):
                if fname.endswith(".json"):
                    fpath = os.path.join(scenario_dir, fname)
                    with open(fpath) as f:
                        data = json.load(f)
                        sid = data.get("scenario_id", fname)
                        self._scenarios[sid] = data

        # Load territories
        geo_dir = os.path.join(self.knowledge_path, "geography")
        if os.path.isdir(geo_dir):
            for fname in os.listdir(geo_dir):
                if fname.endswith(".json"):
                    fpath = os.path.join(geo_dir, fname)
                    with open(fpath) as f:
                        data = json.load(f)
                        if "regions" in data:
                            for region in data["regions"]:
                                self._territories[region["id"]] = region

    # ── Core event checking ──

    def check_events(
        self,
        year: int,
        season: Season | str,
        world_state: WorldState,
        deviation: float = 0.0,
    ) -> list[EventProposal]:
        """
        Check all timeline events for the current year/season.
        Returns list of EventProposals for events that should trigger.
        Also marks events as averted if probability check fails.
        """
        proposals: list[EventProposal] = []

        # Accept both Season enum and string (e.g. "春", "summer")
        season_label = season if isinstance(season, str) else season.cn
        if season_label == "春":
            season_month = 3
        elif season_label == "夏":
            season_month = 6
        elif season_label == "秋":
            season_month = 9
        else:
            season_month = 12

        for evt_data in self._timeline:
            evt_id = evt_data["id"]

            # Skip already processed events
            if evt_id in self._triggered_events:
                continue
            if evt_id in self._averted_events:
                continue
            if evt_id in self._blocked_downstream:
                continue

            evt_year = evt_data["year"]
            evt_month = evt_data.get("month", 6)

            # Event is relevant to current year (allow ±1 year for multi-year events)
            year_min = evt_year - 1
            year_max = evt_year + 2  # events can trigger up to 2 years after

            if not (year_min <= year <= year_max):
                # Check if event is in a range
                evt_data.get("title", "")
                if not self._year_in_range(year, evt_data):
                    continue

            # Check month/season alignment — allow 1 season margin
            if abs(season_month - evt_month) > 4:
                continue

            # Check preconditions
            if not self._check_preconditions(evt_data, world_state):
                # If current time aligns with scheduled target year/season, it is averted
                if year == evt_year and abs(season_month - evt_month) <= 4:
                    self.mark_averted(evt_id, "Preconditions not met")
                    self.block_downstream(evt_id)
                    world_state.player_deviation = min(1.0, world_state.player_deviation + 0.05)
                    if evt_id not in world_state.averted_events:
                        world_state.averted_events.append(evt_id)
                continue

            # Core probability formula
            gravity = evt_data.get("gravity", 0.7)
            effective_prob = gravity * (1.0 - deviation * 0.5)

            if random.random() < effective_prob:
                # Event triggers
                self._triggered_events.add(evt_id)
                if evt_id not in world_state.completed_events:
                    world_state.completed_events.append(evt_id)

                # Collect butterfly effects as triggered events
                butterfly = evt_data.get("butterfly_effects", {})
                triggered_ids = butterfly.get("triggered", [])
                for downstream_id in triggered_ids:
                    if downstream_id in self._event_index:
                        self._triggered_events.add(downstream_id)
                        if downstream_id not in world_state.completed_events:
                            world_state.completed_events.append(downstream_id)

                # Build effects from outcomes
                outcomes = evt_data.get("outcomes", [])
                default_outcome = outcomes[0] if outcomes else {}
                effects = {
                    "event_id": evt_id,
                    "title": evt_data["title"],
                    "category": evt_data["category"],
                    "outcome": default_outcome.get("id", "default"),
                    "outcome_description": default_outcome.get("description", ""),
                    "effects": default_outcome.get("effects", {}),
                }

                # Add faction-relevant effects
                if "participants" in evt_data:
                    effects["participants"] = evt_data["participants"]

                proposals.append(
                    EventProposal(
                        event_id=evt_id,
                        title=evt_data["title"],
                        effects=effects,
                        narrative_hint=evt_data.get("description", ""),
                    )
                )
            else:
                # Event does not trigger — mark as averted
                self.mark_averted(evt_id, f"Probability check failed: {effective_prob:.3f}")
                self.block_downstream(evt_id)
                world_state.player_deviation = min(1.0, world_state.player_deviation + 0.05)
                if evt_id not in world_state.averted_events:
                    world_state.averted_events.append(evt_id)

        return proposals

    def _year_in_range(self, year: int, evt_data: dict) -> bool:
        """Check if year falls within an event's multi-year range based on title."""
        title = evt_data.get("title", "")
        # Detect year ranges like "211-214" from title/id
        evt_year = evt_data.get("year", 0)
        # For multi-year events, allow trigger in any year of the range
        if "211" in title and "214" in title:
            return 211 <= year <= 214
        if "217" in title and "219" in title:
            return 217 <= year <= 219
        if "221" in title and "222" in title:
            return 221 <= year <= 222
        return evt_year == year

    def _check_preconditions(self, evt_data: dict, world_state: WorldState) -> bool:
        """Check if event preconditions are met in the current world state."""
        precond = evt_data.get("preconditions", {})
        if not precond:
            return True

        for key, value in precond.items():
            if key == "liubei_location":
                char = world_state.characters.get("liubei")
                if char and char.location != value:
                    return False
            elif key == "zhugeliang_alive":
                char = world_state.characters.get("zhugeliang")
                if value and not (char and char.alive):
                    return False
                if not value and char and char.alive:
                    return False
            elif key == "liubei_has_advisor":
                # Simple check: if zhugeliang joined
                zgl = world_state.characters.get("zhugeliang")
                if value and not (zgl and zgl.faction_id == "shu"):
                    return False
                if not value and zgl and zgl.faction_id == "shu":
                    return False
            elif key == "liubiao_alive":
                char = world_state.characters.get("liubiao")
                if value and not (char and char.alive):
                    return False
            elif key == "liubiao_faction":
                # Check if liubiao faction exists and controls Jingzhou
                lb = world_state.factions.get("liubiao")
                if value and not (lb and lb.is_active and lb.territories):
                    return False
            elif key == "caocao_south":
                # Approximate: cao owns a Jingzhou territory
                cao_owns_jing = any(
                    t.owner_id == "cao" and "xiangyang" in tid
                    for tid, t in world_state.territories.items()
                ) or any(
                    t.owner_id == "cao" and "jiangling" in tid
                    for tid, t in world_state.territories.items()
                )
                if value and not cao_owns_jing:
                    # Also check if xuchang/wancheng neighbor xinye is owned by cao
                    pass  # allow for general game state
            elif key == "liubei_fleeing":
                char = world_state.characters.get("liubei")
                if value and char and char.location == "xinye":
                    return False
            elif key == "caocao_controls_jingzhou":
                cao_owns = any(
                    t.owner_id == "cao" and ("xiangyang" in tid or "jiangling" in tid)
                    for tid, t in world_state.territories.items()
                )
                if value and not cao_owns:
                    return False
            elif key == "sunliu_alliance":
                wu = world_state.factions.get("wu")
                if wu:
                    rel = wu.relations.get("shu", 0)
                    if value and rel < 10:
                        return False
            elif key == "red_cliffs_won":
                if value and "red_cliffs_208" in self._triggered_events:
                    pass  # Already triggered
            elif key == "caocao_retreated":
                pass  # Assume if red_cliffs triggered
            elif key == "liubei_has_yizhou":
                has_yizhou = any(
                    t.owner_id == "shu" and tid in ("chengdu", "hanshui")
                    for tid, t in world_state.territories.items()
                )
                if value and not has_yizhou:
                    return False
            elif key == "guanyu_guards_jingzhou":
                char = world_state.characters.get("guanyu")
                if value and not (char and char.alive):
                    return False
            elif key == "liubei_has_hanzhong":
                has_hz = any(
                    t.owner_id == "shu" and "han" in tid
                    for tid, t in world_state.territories.items()
                )
                if value and not has_hz:
                    return False
            elif key == "guanyu_dead":
                guanyu = world_state.characters.get("guanyu")
                if value and guanyu and guanyu.alive:
                    return False
            elif key == "liubei_emperor":
                # Check if liebei titled himself emperor
                pass  # Allow to pass for now
            elif key == "wu_holds_jingzhou":
                wu_owns = any(
                    t.owner_id == "wu" and ("jiangling" in tid or "xiangyang" in tid)
                    for tid, t in world_state.territories.items()
                )
                if value and not wu_owns:
                    return False
            elif key == "caocao_alive":
                char = world_state.characters.get("caocao")
                if value and not (char and char.alive):
                    return False
            elif key == "liubei_alive":
                char = world_state.characters.get("liubei")
                if value and not (char and char.alive):
                    return False
            elif key == "yiling_lost":
                if value and "yiling_battle_221" in self._averted_events:
                    return False
            elif key == "liuzhang_holds_yizhou":
                has_yz = any(
                    t.owner_id in ("liuzhang",) and tid in ("chengdu", "hanshui")
                    for tid, t in world_state.territories.items()
                )
                if value and not has_yz:
                    return False
            elif key == "caocao_has_hanzhong":
                cao_hz = any(
                    t.owner_id == "cao" and "han" in tid
                    for tid, t in world_state.territories.items()
                )
                if value and not cao_hz:
                    return False
            # Unknown preconditions pass by default (flexibility for game state)
        return True

    # ── Event state management ──

    def mark_averted(self, event_id: str, reason: str) -> None:
        """Mark an event as not having occurred."""
        self._averted_events[event_id] = reason
        if event_id in self._triggered_events:
            self._triggered_events.discard(event_id)

    def block_downstream(self, event_id: str) -> None:
        """Block all butterfly effect downstream events."""
        evt_data = self._event_index.get(event_id)
        if not evt_data:
            return

        butterfly = evt_data.get("butterfly_effects", {})
        triggered_ids = butterfly.get("triggered", [])

        for downstream_id in triggered_ids:
            self._blocked_downstream.add(downstream_id)
            # Recursively block further downstream
            if downstream_id in self._event_index:
                self.block_downstream(downstream_id)

    def get_alternative_chain(self, blocked_event_id: str) -> list[dict]:
        """
        Return alternative history chain when an event is blocked.
        Uses the alternative outcomes from the event data if available.
        """
        evt_data = self._event_index.get(blocked_event_id)
        if not evt_data:
            return []

        alternatives: list[dict] = []
        outcomes = evt_data.get("outcomes", [])
        # Alternative outcomes are outcomes[1:] (since outcomes[0] is historical)
        for outcome in outcomes[1:]:
            alternatives.append(
                {
                    "event_id": blocked_event_id,
                    "title": evt_data["title"],
                    "alternative_id": outcome["id"],
                    "description": outcome["description"],
                    "effects": outcome.get("effects", {}),
                    "divergence_level": outcome.get("effects", {}).get(
                        "game_divergence", "moderate"
                    ),
                }
            )

        # Also provide downstream alternatives from blocked events
        butterfly = evt_data.get("butterfly_effects", {})
        downstream_ids = butterfly.get("triggered", [])
        for ds_id in downstream_ids:
            if ds_id in self._blocked_downstream:
                ds_data = self._event_index.get(ds_id)
                if ds_data:
                    alternatives.append(
                        {
                            "event_id": ds_id,
                            "title": ds_data["title"],
                            "alternative_id": "averted",
                            "description": (
                                f"由于{evt_data['title']}未发生，{ds_data['title']}也不会发生"
                            ),
                            "effects": {},
                            "divergence_level": "high",
                        }
                    )

        return alternatives

    def get_historical_context(self, year: int, deviation: float = 0.0) -> str:
        """
        Generate a historical context summary for a given year,
        suitable for use in LLM prompts / RAG context.
        """
        lines: list[str] = []
        lines.append(f"## 公元{year}年历史背景\n")

        # Collect events within ±2 year window
        relevant_events: list[dict] = []
        for evt_data in self._timeline:
            evt_year = evt_data["year"]
            if abs(evt_year - year) <= 2:
                relevant_events.append(evt_data)
            else:
                # Check multi-year events
                title = evt_data.get("title", "")
                if (
                    "211" in title
                    and "214" in title
                    and 211 <= year <= 214
                    or "217" in title
                    and "219" in title
                    and 217 <= year <= 219
                    or "221" in title
                    and "222" in title
                    and 221 <= year <= 222
                ):
                    relevant_events.append(evt_data)

        # Sort by year then month
        relevant_events.sort(key=lambda e: (e["year"], e.get("month", 6)))

        for evt in relevant_events:
            status = (
                "✓ 已触发"
                if evt["id"] in self._triggered_events
                else ("✗ 未发生" if evt["id"] in self._averted_events else "○ 待定")
            )
            title = evt["title"]
            desc = evt.get("description", "")
            lines.append(f"- {status} | {evt['year']}年 | {title}")
            if desc:
                lines.append(f"  {desc[:120]}")

        if deviation > 0:
            lines.append(f"\n历史偏离度: {deviation:.2f} (高偏离可能导致事件走向改变)")

        return "\n".join(lines)

    # ── Properties ──

    @property
    def event_count(self) -> int:
        return len(self._timeline)

    @property
    def triggered_count(self) -> int:
        return len(self._triggered_events)

    @property
    def averted_count(self) -> int:
        return len(self._averted_events)

    @property
    def blocked_count(self) -> int:
        return len(self._blocked_downstream)

    @property
    def all_events(self) -> list[dict]:
        return list(self._timeline)

    @property
    def averted_events(self) -> dict[str, str]:
        return dict(self._averted_events)

    def reset(self) -> None:
        """Reset all event state (for testing)."""
        self._averted_events.clear()
        self._blocked_downstream.clear()
        self._triggered_events.clear()
