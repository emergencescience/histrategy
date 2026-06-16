"""
Character Engine — officer management and relationship dynamics.

Manages five-dimensional stats, skills, loyalty, relationships,
and life/death events for all historical figures.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..world import Character

if TYPE_CHECKING:
    pass


class CharacterEngine:
    """Manages all character-related logic."""

    def __init__(self, characters: dict[str, Character] | None = None):
        self._characters: dict[str, Character] = characters or {}

    # ── Data loading ──

    def load_characters(self, characters: dict[str, Character]) -> None:
        self._characters = characters

    def add_character(self, char: Character) -> None:
        self._characters[char.id] = char

    def get(self, char_id: str) -> Character | None:
        return self._characters.get(char_id)

    def get_all(self) -> list[Character]:
        return list(self._characters.values())

    def get_by_faction(self, faction_id: str) -> list[Character]:
        return [c for c in self._characters.values() if c.faction_id == faction_id and c.alive]

    def get_alive(self) -> list[Character]:
        return [c for c in self._characters.values() if c.alive]

    # ── Stat bonuses ──

    def get_governor_bonus(self, territory_id: str, faction_id: str) -> float:
        """
        Domestic bonus from the governor of a territory.
        Uses the character with highest politics assigned to that location.
        Returns multiplier: 1.0 (no governor) → 1.5 (max politics).
        """
        best_politics = 0
        for char in self.get_by_faction(faction_id):
            if char.location == territory_id and char.is_governor and char.politics > best_politics:
                best_politics = char.politics
        return 1.0 + best_politics / 200.0

    def get_commander_bonus(self, character_id: str) -> float:
        """Combat bonus from the commanding officer's leadership."""
        char = self._characters.get(character_id)
        if not char:
            return 1.0
        return char.leadership_bonus()

    def get_research_bonus(self, faction_id: str) -> float:
        """Tech research speed bonus from the faction's best brain."""
        best_int = 0
        for char in self.get_by_faction(faction_id):
            if char.intelligence > best_int:
                best_int = char.intelligence
        return 1.0 + best_int / 200.0

    def get_diplomacy_bonus(self, character_id: str) -> float:
        """Diplomacy success bonus from envoy's charisma."""
        char = self._characters.get(character_id)
        if not char:
            return 1.0
        return char.charisma_bonus()

    # ── Loyalty ──

    def update_loyalty(self, char_id: str, delta: int, reason: str = "") -> int:
        """Change a character's loyalty and clamp to 0-100."""
        char = self._characters.get(char_id)
        if not char or not char.alive:
            return -1
        char.loyalty = max(0, min(100, char.loyalty + delta))
        return char.loyalty

    def get_discontented(self, faction_id: str, threshold: int = 30) -> list[Character]:
        """Characters with dangerously low loyalty."""
        return [c for c in self.get_by_faction(faction_id) if c.loyalty < threshold]

    def check_defections(self, faction_id: str) -> list[dict]:
        """
        Check if any low-loyalty characters defect.

        Returns list of defection events:
        [{"character_id": "x", "from": "cao", "to": "wu", "reason": "..."}]
        """
        events = []
        # Simple model: loyalty < 20 has chance to defect each turn
        for char in self.get_by_faction(faction_id):
            if (
                char.loyalty < 20
                and char.id != self._get_ruler_id(faction_id)
                and random.random() < (20 - char.loyalty) / 100.0
            ):
                # Find a neighboring faction to defect to
                # (simplified: just mark as defected, actual target resolved by caller)
                events.append(
                    {
                        "character_id": char.id,
                        "character_name": char.name,
                        "from_faction": faction_id,
                        "loyalty": char.loyalty,
                        "type": "defection",
                    }
                )
        return events

    def _get_ruler_id(self, faction_id: str) -> str:
        """Find the ruler of a faction. Placeholder — caller provides."""
        for char in self._characters.values():
            if char.faction_id == faction_id and char.id == faction_id:
                return char.id
        return ""

    # ── Relationships ──

    def on_character_death(self, char_id: str) -> list[dict]:
        """
        When a character dies, trigger relationship effects.

        Returns list of loyalty impacts:
        [{"character_id": "zhangfei", "delta": -30, "reason": "关羽被杀"}]
        """
        char = self._characters.get(char_id)
        if not char:
            return []

        impacts = []
        for other in self._characters.values():
            if not other.alive or other.id == char_id:
                continue
            delta = 0
            reason = ""

            if char_id in other.sworn_brothers:
                delta = -30
                reason = f"结义兄弟{char.name}去世"
            elif char_id == other.spouse:
                delta = -25
                reason = f"配偶{char.name}去世"
            elif char_id == other.mentor:
                delta = -10
                reason = f"恩师{char.name}去世"
            elif other.hometown and other.hometown == char.hometown:
                delta = -2
                reason = f"同乡{char.name}去世"

            if delta != 0:
                impacts.append(
                    {
                        "character_id": other.id,
                        "character_name": other.name,
                        "delta": delta,
                        "reason": reason,
                    }
                )

        return impacts

    # ── Life & Death ──

    def check_natural_death(self, char_id: str, current_year: int, deviation: float = 0.0) -> bool:
        """
        Check if a character dies of natural causes this year.

        - At their historical death year: high probability
        - deviation > 0.5 allows extending lifespan (alt-history mode)
        """
        char = self._characters.get(char_id)
        if not char or not char.alive:
            return False

        if char.death is None or current_year < char.death:
            return False

        years_past_death = current_year - char.death
        if years_past_death == 0:
            base_prob = 0.6
        elif years_past_death == 1:
            base_prob = 0.8
        else:
            base_prob = 0.95

        # High deviation → characters live longer (alternate history)
        adjusted_prob = base_prob * (1.0 - deviation * 0.5)

        return random.random() < adjusted_prob

    def kill_character(self, char_id: str) -> list[dict]:
        """Mark a character as dead and trigger relationship effects."""
        char = self._characters.get(char_id)
        if not char or not char.alive:
            return []

        char.alive = False
        char.is_governor = False
        char.is_commanding = False
        return self.on_character_death(char_id)

    # ── Recruitment ──

    def get_recruitment_bonus(self, territory_id: str, faction_id: str) -> float:
        """
        Recruitment efficiency bonus.

        Governor's charisma affects how many troops can be raised.
        """
        best_charisma = 0
        for char in self.get_by_faction(faction_id):
            if char.location == territory_id and char.is_governor and char.charisma > best_charisma:
                best_charisma = char.charisma
        return 1.0 + best_charisma / 200.0
