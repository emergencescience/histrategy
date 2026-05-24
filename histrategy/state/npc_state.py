"""NPC emotional state — Tier 1 stateful profiles.

NPCs are NOT full LLM agents. Instead, each key NPC maintains a small
JSON emotional state. One batch LLM call per turn interprets all NPC states
simultaneously and produces mood updates + visible actions.

Design constraints:
  - Mood changes max 1 level per turn (prevents jarring betrayals)
  - Player receives warning hints 3+ turns before drastic NPC actions
  - All moods are bounded enums — no free-text mood (prevents hallucination)
  - Drastic actions (betrayal, self-action) require 3 consecutive turns at danger mood

See: docs/design-iterations.md — v0.3 NPC design rationale.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


# ─── Mood enum ────────────────────────────────────────────────────

class NPCMood(str, Enum):
    """NPC emotional state. Ordered from most positive to most dangerous.

    Mood can shift at most ONE level per turn. This means:
      CONTENT → FRUSTRATED needs 1 turn of neglect
      FRUSTRATED → ANGRY needs 1 more turn
      ANGRY → PLOTTING needs 1 more turn
    Players get at least 3 turns of warning before PLOTTING.
    """
    LOYAL = "loyal"           # Extra loyalty — advisor actively supports player
    CONTENT = "content"       # Normal state — no issues
    FRUSTRATED = "frustrated" # Warning level — advisor unhappy, hints surfaced
    ANGRY = "angry"           # Danger level — advisor may leak intel or disobey
    SCHEMING = "scheming"     # High danger — advisor forming court faction against player
    PLOTTING = "plotting"     # Critical — betrayal or defection imminent (1-2 turns)

    @property
    def danger_level(self) -> int:
        """0 = safe, 5 = imminent betrayal."""
        order = [self.LOYAL, self.CONTENT, self.FRUSTRATED,
                 self.ANGRY, self.SCHEMING, self.PLOTTING]
        try:
            return order.index(self)
        except ValueError:
            return 2  # default: FRUSTRATED

    @property
    def is_warning(self) -> bool:
        return self.danger_level >= 2  # FRUSTRATED+

    @property
    def is_danger(self) -> bool:
        return self.danger_level >= 3  # ANGRY+

    @property
    def is_critical(self) -> bool:
        return self.danger_level >= 5  # PLOTTING

    def shift_toward(self, direction: int) -> NPCMood:
        """Shift mood by direction (-1=improve, +1=worsen). Max 1 step."""
        order = [NPCMood.LOYAL, NPCMood.CONTENT, NPCMood.FRUSTRATED,
                 NPCMood.ANGRY, NPCMood.SCHEMING, NPCMood.PLOTTING]
        idx = self.danger_level
        new_idx = max(0, min(len(order) - 1, idx + direction))
        return order[new_idx]


# ─── NPCState ─────────────────────────────────────────────────────

@dataclass
class NPCState:
    """Emotional state of a single NPC (character in the game world).

    Stored in ~/.histrategy/npc_states.json per character_id.
    """
    character_id: str
    loyalty: int = 80              # 0-100 overall loyalty score
    mood: NPCMood = NPCMood.CONTENT
    grievance: str = ""            # One-sentence reason for unhappiness (in Chinese)
    key_events: list[str] = field(default_factory=list)  # e.g. ["turn_3_ignored"]
    is_plotting: bool = False
    turns_at_current_mood: int = 0  # How long they've been at this mood

    def apply_mood_shift(self, direction: int, reason: str = "") -> bool:
        """Shift mood by at most 1 level. Returns True if mood changed."""
        new_mood = self.mood.shift_toward(direction)
        if new_mood == self.mood:
            self.turns_at_current_mood += 1
            return False
        self.mood = new_mood
        self.turns_at_current_mood = 0
        if reason:
            self.grievance = reason
        if new_mood == NPCMood.PLOTTING:
            self.is_plotting = True
        return True

    def improve(self, reason: str = "") -> bool:
        """Improve mood by 1 level."""
        return self.apply_mood_shift(-1, reason)

    def worsen(self, reason: str = "") -> bool:
        """Worsen mood by 1 level."""
        return self.apply_mood_shift(+1, reason)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mood"] = self.mood.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> NPCState:
        data = dict(data)
        data["mood"] = NPCMood(data.get("mood", "content"))
        return cls(**data)


# ─── Save / Load ──────────────────────────────────────────────────

def _npc_states_file() -> Path:
    override = os.environ.get("HISTRATEGY_DATA_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".histrategy"
    return base / "npc_states.json"


def load_npc_states() -> dict[str, NPCState]:
    """Load all NPC states from disk. Returns empty dict if file missing."""
    path = _npc_states_file()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            raw = json.load(f)
        return {cid: NPCState.from_dict(data) for cid, data in raw.items()}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def save_npc_states(states: dict[str, NPCState]) -> None:
    """Save all NPC states to disk."""
    path = _npc_states_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({cid: s.to_dict() for cid, s in states.items()},
                  f, ensure_ascii=False, indent=2)


def get_or_create_npc_state(
    states: dict[str, NPCState],
    character_id: str,
    initial_loyalty: int = 80,
) -> NPCState:
    """Get existing NPC state or create a fresh one."""
    if character_id not in states:
        states[character_id] = NPCState(
            character_id=character_id,
            loyalty=initial_loyalty,
        )
    return states[character_id]
