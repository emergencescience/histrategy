"""
Decision Engine — NPC AI for autonomous faction behavior.

Evaluates threats, identifies opportunities, and generates commands
based on personality profiles. Pure-math, no LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world import Command, FactionState, WorldState

if TYPE_CHECKING:
    from ..map import MapEngine

# ─── Personality profiles ────────────────────────────────────────

DEFAULT_PROFILES: dict[str, dict[str, float]] = {
    # ── Three Kingdoms ──
    "caocao": {
        "aggression": 0.8,
        "cunning": 0.9,
        "caution": 0.3,
        "diplomacy": 0.5,
        "development": 0.6,
        "mercy": 0.2,
    },
    "liubei": {
        "aggression": 0.3,
        "cunning": 0.3,
        "caution": 0.7,
        "diplomacy": 0.8,
        "development": 0.8,
        "mercy": 0.95,
    },
    "sunquan": {
        "aggression": 0.6,
        "cunning": 0.6,
        "caution": 0.5,
        "diplomacy": 0.6,
        "development": 0.6,
        "mercy": 0.5,
    },
    "yuanshao": {
        "aggression": 0.5,
        "cunning": 0.6,
        "caution": 0.7,
        "diplomacy": 0.7,
        "development": 0.5,
        "mercy": 0.6,
    },
    "dongzhuo": {
        "aggression": 0.9,
        "cunning": 0.5,
        "caution": 0.1,
        "diplomacy": 0.1,
        "development": 0.2,
        "mercy": 0.05,
    },
    # ── Nanming (山河鼎革) ──
    "qing": {
        "aggression": 0.9,    # 多尔衮: aggressively expansionist
        "cunning": 0.8,       # political maneuvering
        "caution": 0.3,       # confident in military superiority
        "diplomacy": 0.6,     # willing to accept surrenders
        "development": 0.4,   # conquest-focused, not development
        "mercy": 0.2,         # siege atrocities (Yangzhou)
    },
    "nanming": {
        "aggression": 0.4,    # defensive posture
        "cunning": 0.4,       # factional infighting reduces cunning
        "caution": 0.7,       # survival mode
        "diplomacy": 0.5,     # tries to ally but ineffective
        "development": 0.5,   # half-hearted reforms
        "mercy": 0.7,         # relatively merciful
    },
    "nongminjun": {
        "aggression": 0.6,    # desperate, willing to fight
        "cunning": 0.3,       # not strategic thinkers
        "caution": 0.3,       # recklessness
        "diplomacy": 0.3,     # bad at diplomacy
        "development": 0.4,   # poor economic management
        "mercy": 0.4,         # rougher treatment
    },
    "zheng": {
        "aggression": 0.3,    # prefers trade over war
        "cunning": 0.8,       # master negotiator
        "caution": 0.8,       # preserves fleet at all costs
        "diplomacy": 0.9,     # plays all sides
        "development": 0.8,   # invests in trade infrastructure
        "mercy": 0.6,         # pragmatic but not cruel
    },
}


class DecisionEngine:
    """Generates strategic commands for NPC factions."""

    def __init__(self, personality_profiles: dict[str, dict[str, float]] | None = None):
        self._profiles = personality_profiles or DEFAULT_PROFILES

    def get_profile(self, faction_id: str) -> dict[str, float]:
        """Get personality profile, falling back to a balanced default."""
        return self._profiles.get(
            faction_id,
            {
                "aggression": 0.5,
                "cunning": 0.5,
                "caution": 0.5,
                "diplomacy": 0.5,
                "development": 0.5,
                "mercy": 0.5,
            },
        )

    # ── Threat evaluation ──

    def evaluate_threats(
        self,
        faction_id: str,
        world_state: WorldState,
        map_engine: MapEngine,
    ) -> dict[str, dict]:
        """
        Evaluate military threats from neighboring factions.

        Returns: {neighbor_faction_id: {ratio, level, neighbor_strength, my_strength}}
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            return {}

        my_strength = faction.strength_actual
        if my_strength <= 0:
            my_strength = 1

        # Find all neighboring factions and their strength
        neighbor_strengths: dict[str, int] = {}
        for tid in faction.territories:
            for neighbor_id in map_engine.get_neighbors(tid):
                neighbor_territory = world_state.territories.get(neighbor_id)
                if not neighbor_territory or not neighbor_territory.owner_id:
                    continue
                nfid = neighbor_territory.owner_id
                if nfid == faction_id:
                    continue
                nfaction = world_state.factions.get(nfid)
                if nfaction and nfaction.is_active:
                    neighbor_strengths[nfid] = max(
                        neighbor_strengths.get(nfid, 0),
                        nfaction.strength_actual,
                    )

        threats = {}
        for nfid, nstrength in neighbor_strengths.items():
            ratio = nstrength / my_strength
            if ratio > 1.5:
                level = "HIGH"
            elif ratio > 0.8:
                level = "MEDIUM"
            else:
                level = "LOW"

            threats[nfid] = {
                "ratio": ratio,
                "level": level,
                "neighbor_strength": nstrength,
                "my_strength": my_strength,
            }

        return threats

    # ── Opportunity evaluation ──

    def evaluate_opportunities(
        self,
        faction_id: str,
        world_state: WorldState,
        map_engine: MapEngine,
    ) -> list[dict]:
        """
        Identify expansion opportunities.

        Returns list of opportunities, each with type and target.
        Types: "attack" (weak neighbor), "occupy" (unowned territory)
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            return []

        my_strength = max(faction.strength_actual, 1)
        opportunities: list[dict] = []

        seen_neighbors: set[str] = set()

        for tid in faction.territories:
            for neighbor_id in map_engine.get_neighbors(tid):
                if neighbor_id in seen_neighbors:
                    continue
                seen_neighbors.add(neighbor_id)

                neighbor_territory = world_state.territories.get(neighbor_id)
                if not neighbor_territory:
                    continue

                # Unowned territory → occupy
                if not neighbor_territory.owner_id:
                    opportunities.append(
                        {
                            "type": "occupy",
                            "territory_id": neighbor_id,
                            "territory_name": neighbor_territory.name,
                            "score": 0.8,
                        }
                    )
                    continue

                # Own territory → skip
                if neighbor_territory.owner_id == faction_id:
                    continue

                # Enemy territory → evaluate for attack
                enemy_id = neighbor_territory.owner_id
                enemy_faction = world_state.factions.get(enemy_id)
                if not enemy_faction or not enemy_faction.is_active:
                    continue

                enemy_strength = enemy_faction.strength_actual
                strength_ratio = enemy_strength / my_strength if my_strength > 0 else float("inf")

                # Attack if we have superiority or at least parity
                # (enemy/my_strength < 1.0 means we are stronger)
                if strength_ratio < 1.0:
                    score = 0.7 * (1.0 - strength_ratio)
                elif strength_ratio < 1.3:
                    # Rough parity — worth considering
                    score = 0.3 * (1.3 - strength_ratio)
                else:
                    continue

                opportunities.append(
                        {
                            "type": "attack",
                            "territory_id": neighbor_id,
                            "territory_name": neighbor_territory.name,
                            "enemy_faction_id": enemy_id,
                            "enemy_faction_name": enemy_faction.name,
                            "strength_ratio": strength_ratio,
                            "score": 0.7 * (1.0 - strength_ratio),
                        }
                    )

        # Sort by score descending
        opportunities.sort(key=lambda o: o["score"], reverse=True)
        return opportunities

    # ── Command generation ──

    def generate_commands(
        self,
        faction_id: str,
        world_state: WorldState,
        map_engine: MapEngine,
    ) -> list[Command]:
        """
        Generate a set of commands for an NPC faction based on
        personality-weighted evaluation of the current situation.
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            return []

        profile = self.get_profile(faction_id)
        aggression = profile.get("aggression", 0.5)
        development = profile.get("development", 0.5)
        caution = profile.get("caution", 0.5)

        threats = self.evaluate_threats(faction_id, world_state, map_engine)
        opportunities = self.evaluate_opportunities(faction_id, world_state, map_engine)

        # Calculate overall opportunity score (0.0 - 1.0)
        opp_score = 0.0
        if opportunities:
            opp_score = opportunities[0]["score"]

        # Determine if there are high threats
        high_threats = any(t["level"] == "HIGH" for t in threats.values())
        medium_threats = any(t["level"] in ("HIGH", "MEDIUM") for t in threats.values())

        commands: list[Command] = []

        # Assess resource needs
        food_low = faction.food < 2000
        troops_low = faction.strength_actual < 3000
        treasury_ok = faction.treasury > 2000

        from ..world import HistoricalMode

        is_historical = (
            getattr(world_state, "historical_mode", HistoricalMode.HISTORICAL)
            == HistoricalMode.HISTORICAL
        )

        # Historical mode dampens aggression (stick closer to historical path)
        # but does NOT completely disable attacks — that was a bug that made
        # all NPCs passive in the default mode.
        # Aggressive NPCs (>0.7) are barely affected — they're warlike by nature.
        if is_historical:
            if aggression > 0.7:
                effective_aggression = aggression * 0.85  # minimal dampening for aggressive NPCs
            else:
                effective_aggression = aggression * 0.7
        else:
            effective_aggression = aggression

        # Decision weights — attack gets bonus for aggressive NPCs with opportunities
        # and penalty for cautious NPCs
        attack_score = effective_aggression * opp_score * 2.0  # boost attack attractiveness
        develop_score = development * (1.0 - opp_score * 0.5)   # reduce develop when opportunities exist

        # If under high threat, prioritize defense/recruitment
        if high_threats and caution > 0.3:
            if troops_low and treasury_ok and faction.territories:
                commands.append(self._make_recruit_command(faction))
            else:
                commands.append(self._make_develop_command(faction))
        elif food_low:
            commands.append(self._make_develop_command(faction))
        elif troops_low and treasury_ok and faction.territories:
            commands.append(self._make_recruit_command(faction))
        elif attack_score > develop_score and opportunities:
            # Find an attack/move opportunity
            attack_opps = [o for o in opportunities if o["type"] == "attack"]
            occupy_opps = [o for o in opportunities if o["type"] == "occupy"]

            if attack_opps and effective_aggression > 0.4:
                opp = attack_opps[0]
                commands.append(
                    Command(
                        type="attack",
                        params={"target_territory": opp["territory_id"]},
                        faction_id=faction_id,
                    )
                )
            elif occupy_opps and effective_aggression > 0.2:
                opp = occupy_opps[0]
                commands.append(
                    Command(
                        type="move",
                        params={"destination": opp["territory_id"]},
                        faction_id=faction_id,
                    )
                )
            elif faction.territories:
                commands.append(self._make_develop_command(faction))
        else:
            # Default: develop or recruit
            if treasury_ok and troops_low and faction.territories:
                commands.append(self._make_recruit_command(faction))
            elif faction.territories:
                commands.append(self._make_develop_command(faction))

        # Cautious factions may add a second defensive command
        if (
            medium_threats
            and caution > 0.5
            and len(commands) < 2
            and treasury_ok
            and faction.territories
        ):
            commands.append(self._make_recruit_command(faction))

        return commands

    def _make_recruit_command(self, faction: FactionState) -> Command:
        return Command(
            type="recruit",
            params={
                "territory": faction.capital
                or (faction.territories[0] if faction.territories else ""),
                "unit_type": "infantry",
                "amount": 500,
            },
            faction_id=faction.id,
        )

    def _make_develop_command(self, faction: FactionState) -> Command:
        return Command(
            type="develop",
            params={
                "territory": faction.capital
                or (faction.territories[0] if faction.territories else ""),
            },
            faction_id=faction.id,
        )
