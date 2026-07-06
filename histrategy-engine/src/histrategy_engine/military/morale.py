"""
Morale Cascade System — nonlinear combat effects from morale thresholds.

In the V2 baseline engine (used by both V1 fast-path and V3 hybrid),
this module provides deterministic morale effects that create dramatic
battle outcomes without requiring LLM.

Critical thresholds:
  80+  Inspiring → combat boost, recruitment bonus
  60-79 Normal → no modifiers
  40-59 Shaken → slight penalty
  20-39 Broken → significant penalty, desertion risk
  0-19  Routing → auto-retreat, heavy desertion
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class MoraleState(Enum):
    INSPIRING = "inspiring"  # 80-100
    NORMAL = "normal"        # 60-79
    SHAKEN = "shaken"        # 40-59
    BROKEN = "broken"        # 20-39
    ROUTING = "routing"      # 0-19


@dataclass
class MoraleEffect:
    """Combat/economy modifiers from current morale state."""

    state: MoraleState
    combat_multiplier: float   # affects unit power
    desertion_rate: float      # troops lost per turn
    recruitment_bonus: int     # bonus/penalty to recruitment
    tax_efficiency: float      # modifier on tax collection
    legitimacy_penalty: int    # per-turn legitimacy drain
    narrative_tag: str         # for LLM narrative generation


MORALE_EFFECTS: dict[MoraleState, MoraleEffect] = {
    MoraleState.INSPIRING: MoraleEffect(
        state=MoraleState.INSPIRING,
        combat_multiplier=1.15,
        desertion_rate=0.0,
        recruitment_bonus=10,
        tax_efficiency=1.1,
        legitimacy_penalty=0,
        narrative_tag="士气高涨，军民同心",
    ),
    MoraleState.NORMAL: MoraleEffect(
        state=MoraleState.NORMAL,
        combat_multiplier=1.0,
        desertion_rate=0.0,
        recruitment_bonus=0,
        tax_efficiency=1.0,
        legitimacy_penalty=0,
        narrative_tag="局势平稳",
    ),
    MoraleState.SHAKEN: MoraleEffect(
        state=MoraleState.SHAKEN,
        combat_multiplier=0.9,
        desertion_rate=0.01,
        recruitment_bonus=-5,
        tax_efficiency=0.95,
        legitimacy_penalty=-1,
        narrative_tag="军心不稳，民有忧色",
    ),
    MoraleState.BROKEN: MoraleEffect(
        state=MoraleState.BROKEN,
        combat_multiplier=0.7,
        desertion_rate=0.03,
        recruitment_bonus=-15,
        tax_efficiency=0.8,
        legitimacy_penalty=-2,
        narrative_tag="军心涣散，逃兵日增",
    ),
    MoraleState.ROUTING: MoraleEffect(
        state=MoraleState.ROUTING,
        combat_multiplier=0.4,
        desertion_rate=0.08,
        recruitment_bonus=-30,
        tax_efficiency=0.5,
        legitimacy_penalty=-3,
        narrative_tag="兵败如山倒，大势已去",
    ),
}


def get_morale_state(morale: int) -> MoraleState:
    """Map a 0-100 morale value to its state."""
    if morale >= 80:
        return MoraleState.INSPIRING
    elif morale >= 60:
        return MoraleState.NORMAL
    elif morale >= 40:
        return MoraleState.SHAKEN
    elif morale >= 20:
        return MoraleState.BROKEN
    else:
        return MoraleState.ROUTING


def get_morale_effect(morale: int) -> MoraleEffect:
    """Get the full effect profile for a morale value."""
    return MORALE_EFFECTS[get_morale_state(morale)]


def calculate_morale_change(
    current_morale: int,
    won_battle: bool = False,
    lost_battle: bool = False,
    lost_territory: bool = False,
    gained_territory: bool = False,
    food_surplus: bool = True,
    high_tax: bool = False,
    siege_active: bool = False,
    ally_victory: bool = False,
    ally_defeat: bool = False,
) -> int:
    """Calculate morale delta for one turn.

    Multiple events can affect morale simultaneously.
    Losses cascade harder when morale is already low.
    """
    delta = 0

    # ── Combat outcomes ──
    if won_battle:
        delta += 5
        if current_morale < 40:
            delta += 3  # bigger morale boost when things were bleak
    if lost_battle:
        delta -= 7
        if current_morale < 40:
            delta -= 4  # cascade: losing when already broken

    # ── Territory changes ──
    if lost_territory:
        delta -= 5
    if gained_territory:
        delta += 4

    # ── Economic factors ──
    if food_surplus:
        delta += 1
    else:
        delta -= 2
    if high_tax:
        delta -= 2

    # ── Siege pressure ──
    if siege_active:
        delta -= 3

    # ── Alliance effects ──
    if ally_victory:
        delta += 1
    if ally_defeat:
        delta -= 2

    return delta
