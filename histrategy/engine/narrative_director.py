"""NarrativeDirector — arc goal steering without railroading.

Maintains a list of narrative arc goals (major historical events that
should naturally occur). Injects a one-sentence "pressure hint" into
the GameMaster prompt to steer narrative toward upcoming goals.

This is "authorial pressure", not railroading:
  - The GM receives a hint but is NOT required to trigger the event
  - The player's deviation score reduces the pressure weight
  - Events can be averted if player deviation is high enough

Cost: ~400 input + ~100 output tokens, cached for 3 turns.
      Approximately free at DeepSeek pricing.

See: Nottingham (2024) §Goal-Oriented Narrative Planning
See: docs/design-iterations.md — v0.3 narrative arc rationale
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# ─── Arc Goal ─────────────────────────────────────────────────────


@dataclass
class ArcGoal:
    """A major narrative beat that the story should naturally arrive at.

    Not a guarantee — a gravitational pull. High player deviation weakens
    the pull. Low deviation keeps history on track.
    """

    event_id: str  # matches events.json id
    title: str  # e.g. "官渡之战"
    target_turn: int  # ideal turn for this to occur
    deadline_turn: int  # last reasonable turn before it's "missed"
    gravity: float = 0.7  # 0.0 = ignore, 1.0 = strong pull
    hint_template: str = ""  # Chinese hint injected into GM prompt
    completed: bool = False
    missed: bool = False


# ─── Default Three Kingdoms Arc Goals ─────────────────────────────

DEFAULT_ARC_GOALS = [
    ArcGoal(
        event_id="coalition_against_dong",
        title="讨董之盟",
        target_turn=2,
        deadline_turn=6,
        gravity=0.8,
        hint_template="讨伐董卓的时机已近，各路诸侯蠢蠢欲动，请在本回合NPC反应中自然埋下讨董联盟的伏笔。",
    ),
    ArcGoal(
        event_id="dong_zhuo_killed",
        title="董卓被刺",
        target_turn=8,
        deadline_turn=14,
        gravity=0.7,
        hint_template="董卓的末日将近，吕布与王允的密谋即将成熟，请在本回合NPC反应中体现长安朝廷的暗流涌动。",
    ),
    ArcGoal(
        event_id="cao_cao_controls_emperor",
        title="曹操迎献帝",
        target_turn=12,
        deadline_turn=20,
        gravity=0.75,
        hint_template="挟天子以令诸侯的时机成熟，献帝在洛阳颠沛流离，曹操的幕僚们正在谏言迎驾，请在本回合体现这一历史走向。",
    ),
    ArcGoal(
        event_id="battle_of_guandu",
        title="官渡之战",
        target_turn=24,
        deadline_turn=36,
        gravity=0.85,
        hint_template="官渡之战在历史上即将爆发，曹操与袁绍的决战时机已至，请在本回合的NPC行动和天下形势中自然地引导这一走向。",
    ),
    ArcGoal(
        event_id="battle_of_chibi",
        title="赤壁之战",
        target_turn=40,
        deadline_turn=60,
        gravity=0.9,
        hint_template="赤壁之战是三国历史的转折点，孙刘联军对抗曹操的时机正在成熟，请在本回合体现南方局势的变化。",
    ),
]


# ─── NarrativeDirector ────────────────────────────────────────────


class NarrativeDirector:
    """Tracks narrative arc goals and steers the game master toward them.

    Provides a get_pressure_hint() method that returns a one-sentence
    steering instruction to inject into the GameMaster's system prompt.
    """

    def __init__(self, arc_goals: list[ArcGoal] | None = None) -> None:
        self._goals = arc_goals or list(DEFAULT_ARC_GOALS)
        self._hint_cache: str = ""
        self._hint_cached_turn: int = -99

    @classmethod
    def from_json(cls, path: Path) -> NarrativeDirector:
        """Load arc goals from a JSON file (knowledge/data/arc_goals.json)."""
        try:
            with open(path) as f:
                raw = json.load(f)
            goals = [ArcGoal(**g) for g in raw]
            return cls(goals)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return cls()  # Fall back to defaults

    def get_pressure_hint(
        self,
        current_turn: int,
        player_deviation: float,
    ) -> str:
        """Return a pressure hint to inject into the GameMaster prompt.

        The hint is cached for 3 turns to avoid thrashing.
        Returns empty string if no relevant arc goals are pending.
        """
        # Cache for 3 turns
        if (current_turn - self._hint_cached_turn) < 3 and self._hint_cache:
            return self._hint_cache

        hint = self._compute_hint(current_turn, player_deviation)
        self._hint_cache = hint
        self._hint_cached_turn = current_turn
        return hint

    def mark_completed(self, event_id: str) -> None:
        """Mark an arc goal as completed (called when historical event occurs)."""
        for goal in self._goals:
            if goal.event_id == event_id or goal.title == event_id:
                goal.completed = True
                self._hint_cache = ""  # invalidate cache

    def check_missed(self, current_turn: int) -> list[str]:
        """Return list of event_ids that have been missed (past deadline)."""
        missed = []
        for goal in self._goals:
            if not goal.completed and not goal.missed and current_turn > goal.deadline_turn:
                goal.missed = True
                missed.append(goal.event_id)
        return missed

    def _compute_hint(self, turn: int, deviation: float) -> str:
        """Find the most pressing upcoming arc goal and return its hint."""
        candidates = [
            g
            for g in self._goals
            if not g.completed and not g.missed and g.target_turn <= turn + 8  # lookahead window of 8 turns
        ]
        if not candidates:
            return ""

        # Pick the goal closest to its target turn
        candidates.sort(key=lambda g: abs(turn - g.target_turn))
        goal = candidates[0]

        # Scale gravity by deviation: high deviation weakens the pull
        effective_gravity = goal.gravity * (1.0 - deviation * 0.5)
        if effective_gravity < 0.2:
            return ""  # Deviation is so high that history has diverged

        return goal.hint_template
