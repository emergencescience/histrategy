"""Reconnaissance Tracker — scout and disinform state management.

Stores which territories have been scouted and which have active
disinformation campaigns. The LocalWorldStateProjector consults
this tracker to adjust visibility and accuracy.
"""

from __future__ import annotations


class ReconTracker:
    """Tracks reconnaissance and disinformation per faction.

    Key pattern:
      - scout(faction, territory): marks territory as "scouted" for N turns
      - disinform(faction, target_territory, fake_troops): overrides perceived
        garrison numbers for target_territory

    The projector uses this to:
      - Show accurate numbers for scouted territories (fuzz: ±5% vs ±15%)
      - Show fake numbers for disinformed territories (overrides real numbers)
    """

    SCOUT_COST = 200
    DISINFORM_COST = 300
    SCOUT_DURATION = 3  # turns

    def __init__(self):
        # scouted[(observer_faction, territory_id)] = remaining_turns
        self._scouted: dict[tuple[str, str], int] = {}
        # disinform[(observer_faction, territory_id)] = fake_troop_count
        self._disinformed: dict[tuple[str, str], int] = {}

    def scout(self, faction_id: str, territory_id: str) -> str:
        """Mark a territory as scouted. Returns result message."""
        key = (faction_id, territory_id)
        self._scouted[key] = self.SCOUT_DURATION
        return f"侦察成功：{territory_id} 将于 {self.SCOUT_DURATION} 回合内显示精确驻军"

    def disinform(self, faction_id: str, territory_id: str, fake_troops: int) -> str:
        """Plant false information about garrison size."""
        key = (faction_id, territory_id)
        self._disinformed[key] = fake_troops
        return f"反间成功：{territory_id} 将显示虚假驻军 {fake_troops}"

    def is_scouted(self, faction_id: str, territory_id: str) -> bool:
        """Check if a territory is currently scouted by this faction."""
        return self._scouted.get((faction_id, territory_id), 0) > 0

    def get_disinformation(self, faction_id: str, territory_id: str) -> int | None:
        """Get fake troop count if disinformation is active, else None."""
        return self._disinformed.get((faction_id, territory_id))

    def tick_turn(self):
        """Decrement all scout counters by 1. Call at end of each turn."""
        expired = []
        for key, turns in self._scouted.items():
            if turns <= 1:
                expired.append(key)
            else:
                self._scouted[key] = turns - 1
        for key in expired:
            del self._scouted[key]

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {
            "scouted": {f"{k[0]}:{k[1]}": v for k, v in self._scouted.items()},
            "disinformed": {f"{k[0]}:{k[1]}": v for k, v in self._disinformed.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReconTracker:
        """Deserialize from persistence."""
        tracker = cls()
        for key_str, turns in data.get("scouted", {}).items():
            parts = key_str.split(":", 1)
            if len(parts) == 2:
                tracker._scouted[(parts[0], parts[1])] = turns
        for key_str, troops in data.get("disinformed", {}).items():
            parts = key_str.split(":", 1)
            if len(parts) == 2:
                tracker._disinformed[(parts[0], parts[1])] = troops
        return tracker
