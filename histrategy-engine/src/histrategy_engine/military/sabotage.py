"""Sabotage Engine — discrete non-linear commands (assassinate, bribe).

These operations bypass the normal command-validate-execute pipeline and
directly modify character/army state with probability-based outcomes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import Character, WorldState


class SabotageType(Enum):
    ASSASSINATE = "assassinate"
    BRIBE = "bribe"


@dataclass
class SabotageResult:
    """Result of a sabotage attempt."""

    success: bool
    target_character_id: str
    target_name: str
    sabotage_type: SabotageType
    probability: float
    roll: float
    effect_description: str
    morale_penalty_applied: float  # 1.0 = no penalty, 0.5 = halved
    character_defected: bool = False
    new_faction_id: str | None = None


class SabotageEngine:
    """Handles non-linear discrete commands: assassination and bribery.

    Outcomes are probability-based, influenced by target character traits
    (loyalty, caution, politics) and the initiating faction's espionage strength.

    Design principle: these operations are the primary source of NON-LINEAR
    state changes — unlike the deterministic combat/economy math, sabotage
    outcomes can swing wildly based on character personalities.
    """

    # Base success probabilities
    BASE_ASSASSINATE = 0.15
    BASE_BRIBE = 0.10

    # Cost in treasury
    ASSASSINATE_COST = 800
    BRIBE_COST = 1200

    def attempt_assassinate(
        self,
        initiator_faction_id: str,
        target_character_id: str,
        world_state: WorldState,
        rng: random.Random | None = None,
    ) -> SabotageResult:
        """Attempt to assassinate a target character.

        Success factors:
          - Low loyalty: +1% per point below 80
          - High caution: -30% at max caution
          - High politics: -10% at max politics (target has connections)

        Effects on success:
          - Target character dies (alive=False)
          - Target's commanding army morale is halved
        """
        return self._attempt(
            initiator_faction_id, target_character_id, world_state, SabotageType.ASSASSINATE, rng
        )

    def attempt_bribe(
        self,
        initiator_faction_id: str,
        target_character_id: str,
        world_state: WorldState,
        rng: random.Random | None = None,
    ) -> SabotageResult:
        """Attempt to bribe a target character to defect.

        Success factors:
          - Low loyalty: +1.5% per point below 80 (money talks)
          - High caution: -20% at max caution (cautious people fear betrayal)
          - High politics: +15% at max politics (politicians are pragmatic)

        Effects on success:
          - Target character switches to initiator's faction
          - Target's former army morale reduced to 70%
        """
        return self._attempt(
            initiator_faction_id, target_character_id, world_state, SabotageType.BRIBE, rng
        )

    def _attempt(
        self,
        initiator_faction_id: str,
        target_character_id: str,
        world_state: WorldState,
        sabotage_type: SabotageType,
        rng: random.Random | None = None,
    ) -> SabotageResult:
        if rng is None:
            rng = random.Random()

        character = world_state.characters.get(target_character_id)
        if not character or not character.alive:
            return SabotageResult(
                success=False,
                target_character_id=target_character_id,
                target_name=character.name if character else "未知",
                sabotage_type=sabotage_type,
                probability=0.0,
                roll=0.0,
                effect_description="目标不存在或已死亡",
                morale_penalty_applied=1.0,
            )

        if character.faction_id == initiator_faction_id:
            return SabotageResult(
                success=False,
                target_character_id=target_character_id,
                target_name=character.name,
                sabotage_type=sabotage_type,
                probability=0.0,
                roll=0.0,
                effect_description="不能对己方武将使用",
                morale_penalty_applied=1.0,
            )

        # Calculate probability
        faction = world_state.factions.get(character.faction_id or "")
        faction_caution = faction.caution if faction else 0.5
        probability = self._calculate_probability(character, sabotage_type, faction_caution)

        roll = rng.random()
        success = roll < probability

        if not success:
            return SabotageResult(
                success=False,
                target_character_id=target_character_id,
                target_name=character.name,
                sabotage_type=sabotage_type,
                probability=probability,
                roll=roll,
                effect_description=f"行动失败 (概率{probability:.1%}, 骰子{roll:.3f})",
                morale_penalty_applied=1.0,
            )

        # Apply effects and build description
        effects = []
        morale_penalty = 1.0
        defected = False
        new_faction = None

        if sabotage_type == SabotageType.ASSASSINATE:
            character.alive = False
            morale_penalty = 0.5
            effects.append(f"{character.name}被暗杀身亡")

            # Halve morale of any army they command
            for army in world_state.armies.values():
                if army.commander_id == target_character_id:
                    army.morale = max(1, int(army.morale * 0.5))
                    army.commander_id = ""
                    effects.append(f"其麾下军队士气崩溃，减半至{army.morale}")

        elif sabotage_type == SabotageType.BRIBE:
            character.faction_id = initiator_faction_id
            character.loyalty = max(0, character.loyalty - 30)  # bribery erodes trust
            morale_penalty = 0.7
            defected = True
            new_faction = initiator_faction_id
            effects.append(f"{character.name}被重金策反，叛逃至我方")

            # Reduce morale of their former army
            for army in world_state.armies.values():
                if army.commander_id == target_character_id:
                    army.morale = max(1, int(army.morale * 0.7))
                    army.commander_id = ""
                    effects.append(f"其旧部士气受挫，降至{army.morale}")

        return SabotageResult(
            success=True,
            target_character_id=target_character_id,
            target_name=character.name,
            sabotage_type=sabotage_type,
            probability=probability,
            roll=roll,
            effect_description="; ".join(effects),
            morale_penalty_applied=morale_penalty,
            character_defected=defected,
            new_faction_id=new_faction,
        )

    def _calculate_probability(
        self,
        character: Character,
        sabotage_type: SabotageType,
        faction_caution: float = 0.5,
    ) -> float:
        """Calculate success probability based on character traits.

        Formula:
          base + loyalty_mod + caution_mod + politics_mod

        clamped to [0.01, 0.80].
        """
        if sabotage_type == SabotageType.ASSASSINATE:
            base = self.BASE_ASSASSINATE
            loyalty_mod = (80 - character.loyalty) * 0.01
            caution_mod = -faction_caution * 0.30
            politics_mod = -character.politics * 0.0010
        else:
            base = self.BASE_BRIBE
            loyalty_mod = (80 - character.loyalty) * 0.015
            caution_mod = -faction_caution * 0.20
            politics_mod = character.politics * 0.0015

        prob = base + loyalty_mod + caution_mod + politics_mod
        return max(0.01, min(0.80, prob))

    def get_cost(self, sabotage_type: SabotageType) -> int:
        """Return the treasury cost for this sabotage type."""
        return (
            self.ASSASSINATE_COST if sabotage_type == SabotageType.ASSASSINATE else self.BRIBE_COST
        )
