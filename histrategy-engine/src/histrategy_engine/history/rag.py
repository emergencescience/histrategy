"""
RAG retriever for historical events — lightweight year-hash index.

No vector database required. Events are indexed by year and retrieved
with a sliding window whose size depends on historical deviation.
"""

from __future__ import annotations

import json
import os


class HistoricalRAG:
    """Year-indexed event retrieval for LLM context building."""

    def __init__(self, knowledge_path: str):
        self.knowledge_path = knowledge_path
        self._events: list[dict] = []
        self._year_index: dict[int, list[dict]] = {}
        self._load_events()

    def _load_events(self) -> None:
        """Load all timeline events and build year-hash index."""
        timeline_dir = os.path.join(self.knowledge_path, "timeline")
        if os.path.isdir(timeline_dir):
            for fname in sorted(os.listdir(timeline_dir)):
                if fname.endswith(".json"):
                    fpath = os.path.join(timeline_dir, fname)
                    with open(fpath) as f:
                        data = json.load(f)
                        if "events" in data:
                            self._events.extend(data["events"])

        for evt in self._events:
            year = evt["year"]
            if year not in self._year_index:
                self._year_index[year] = []
            self._year_index[year].append(evt)

    def retrieve(
        self,
        year: int,
        deviation: float = 0.0,
        max_events: int = 8,
        averted_events: list[str] | None = None,
    ) -> list[dict]:
        """
        Retrieve relevant historical events for a given year.

        Window size depends on deviation:
          - Low deviation (< 0.3):  ±3 years
          - Medium deviation (0.3-0.6):  ±2 years
          - High deviation (> 0.6):  ±1 year
        """
        # Determine window size based on deviation
        if deviation < 0.3:
            window = 3
        elif deviation < 0.6:
            window = 2
        else:
            window = 1

        year_min = year - window
        year_max = year + window

        candidates: list[dict] = []

        for y in range(year_min, year_max + 1):
            if y in self._year_index:
                for evt in self._year_index[y]:
                    if averted_events and evt["id"] in averted_events:
                        continue
                    candidates.append({
                        "id": evt["id"],
                        "title": evt["title"],
                        "year": evt["year"],
                        "month": evt.get("month", 6),
                        "category": evt.get("category", "general"),
                        "description": evt.get("description", ""),
                        "gravity": evt.get("gravity", 0.7),
                        "participants": evt.get("participants", []),
                        "outcomes": evt.get("outcomes", []),
                        "preconditions": evt.get("preconditions", {}),
                        "butterfly_effects": evt.get("butterfly_effects", {}),
                    })

        # Sort by year, then month
        candidates.sort(key=lambda e: (e["year"], e["month"]))

        # Cap at max_events
        return candidates[:max_events]

    def build_llm_context(self, events: list[dict]) -> str:
        """
        Format retrieved events into an LLM prompt context string.
        Suitable as historical reference for the Narrative Engine or
        for player-facing historical background.
        """
        if not events:
            return "（无相关历史事件参考）"

        lines: list[str] = []
        lines.append("【历史参考 - 周边年份关键事件】\n")

        for evt in events:
            year = evt["year"]
            month = evt.get("month", 6)
            title = evt["title"]
            category = evt.get("category", "general")
            desc = evt.get("description", "")
            gravity = evt.get("gravity", 0.7)
            participants = evt.get("participants", [])

            lines.append(f"### {year}年{month}月 — {title}")
            lines.append(f"- 类别: {category}")
            lines.append(f"- 历史引力: {gravity:.2f}")
            if participants:
                lines.append(f"- 参与人物: {', '.join(participants[:8])}")
            if desc:
                lines.append(f"- 描述: {desc[:200]}")
            lines.append("")

        return "\n".join(lines)

    def get_event_by_id(self, event_id: str) -> dict | None:
        """Look up a specific event by ID."""
        for evt in self._events:
            if evt["id"] == event_id:
                return evt
        return None

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def year_coverage(self) -> tuple[int, int]:
        """Return (min_year, max_year) covered by the index."""
        if not self._year_index:
            return (0, 0)
        years = sorted(self._year_index.keys())
        return (years[0], years[-1])
