"""Fog-of-War Projector — generates asymmetric local world views.

Each faction sees only its own data plus public information.
Enemy resources, secret armies, and non-border forces are hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import WorldState


@dataclass
class PerceivedFaction:
    """What a faction looks like from another faction's perspective."""

    id: str
    name: str
    estimated_strength: str = "???"
    territory_count: int = 0
    capital: str = ""
    is_border: bool = False
    is_allied: bool = False


@dataclass
class LocalWorldState:
    """A faction's limited view of the world.

    This is the ONLY state a player or NPC AI should use for decisions.
    The projector filters out:
      - Non-border enemy resources (treasury, food)
      - Hidden armies (ambush units)
      - Distant faction troop counts (shown as range estimates)
    """

    faction_id: str
    year: int
    season_str: str
    turn: int

    # Full visibility — own faction
    my_treasury: int = 0
    my_food: int = 0
    my_strength: int = 0
    my_economy: int = 50
    my_morale: int = 50
    my_territories: list[str] = field(default_factory=list)
    my_characters: dict[str, dict] = field(default_factory=dict)

    # Limited visibility — other factions
    perceived_factions: dict[str, PerceivedFaction] = field(default_factory=dict)

    # Visible armies (filtered)
    visible_armies: dict[str, dict] = field(default_factory=dict)

    # Border territory garrisons with range estimates
    border_garrisons: dict[str, dict] = field(default_factory=dict)

    # Always public
    chronicle_entries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON/LLM context."""
        return {
            "faction_id": self.faction_id,
            "year": self.year,
            "season": self.season_str,
            "turn": self.turn,
            "my": {
                "treasury": self.my_treasury,
                "food": self.my_food,
                "strength": self.my_strength,
                "economy": self.my_economy,
                "morale": self.my_morale,
                "territories": self.my_territories,
                "characters": {
                    cid: {
                        "name": cd["name"],
                        "loyalty": cd["loyalty"],
                        "leadership": cd["leadership"],
                        "role": cd.get("role", ""),
                    }
                    for cid, cd in self.my_characters.items()
                },
            },
            "perceived": {
                fid: {
                    "name": pf.name,
                    "strength": pf.estimated_strength,
                    "territories": pf.territory_count,
                    "capital": pf.capital,
                    "is_border": pf.is_border,
                    "is_allied": pf.is_allied,
                }
                for fid, pf in self.perceived_factions.items()
            },
            "visible_armies": self.visible_armies,
            "border_garrisons": self.border_garrisons,
            "chronicle": self.chronicle_entries[-10:],  # last 10 entries
        }


class LocalWorldStateProjector:
    """Projects a full WorldState into a faction-specific LocalWorldState.

    Design: players and NPCs should NEVER access global state directly.
    All decisions must be made based on projected LocalWorldState.

    This ensures:
      - Hidden armies (ambush) are invisible to enemies
      - Distant faction resources are hidden
      - Border garrisons show range estimates, not exact numbers
      - The fog of war is real and strategic
    """

    ESTIMATE_FUZZ = 0.15  # ±15% default
    SCOUTED_FUZZ = 0.05  # ±5% when scouted

    # Re-export from recon module for convenience
    from .recon import ReconTracker

    def project(
        self,
        world_state: WorldState,
        faction_id: str,
        border_territories: set[str] | None = None,
        recon: object | None = None,
    ) -> LocalWorldState:
        """Project global state into a faction's local view.

        Args:
            world_state: The full global state
            faction_id: The viewing faction
            border_territories: Pre-computed set of border territory IDs.
                If None, borders are inferred from ownership adjacency.

        Returns:
            LocalWorldState with fog-of-war applied
        """
        faction = world_state.factions.get(faction_id)
        if not faction:
            return LocalWorldState(
                faction_id=faction_id,
                year=world_state.year,
                season_str=world_state.season.cn
                if hasattr(world_state.season, "cn")
                else str(world_state.season),
                turn=getattr(world_state, "turn_number", 0),
            )

        # Compute borders if not provided
        if border_territories is None:
            border_territories = self._compute_borders(world_state, faction_id)

        local = LocalWorldState(
            faction_id=faction_id,
            year=world_state.year,
            season_str=world_state.season.cn
            if hasattr(world_state.season, "cn")
            else str(world_state.season),
            turn=getattr(world_state, "turn_number", 0),
            # Own faction — full visibility
            my_treasury=faction.treasury,
            my_food=faction.food,
            my_strength=faction.strength_actual,
            my_economy=faction.economy_actual,
            my_morale=faction.morale_actual,
            my_territories=list(faction.territories),
            my_characters={
                cid: {
                    "name": c.name,
                    "loyalty": c.loyalty,
                    "leadership": c.leadership,
                    "politics": c.politics,
                    "intelligence": c.intelligence,
                    "role": self._char_role(c, faction_id, world_state),
                }
                for cid, c in world_state.characters.items()
                if c.faction_id == faction_id and c.alive
            },
        )

        # Other factions — limited visibility
        for fid, f in world_state.factions.items():
            if fid == faction_id or not f.is_active:
                continue

            is_border = bool(border_territories & set(f.territories)) or bool(
                set(faction.territories) & set(f.territories)
            )

            is_allied = fid in (faction.allies or []) or faction_id in (f.allies or [])

            if is_border:
                # Border faction: show range estimate
                fuzz = int(f.strength_actual * self.ESTIMATE_FUZZ)
                low = max(0, f.strength_actual - fuzz)
                high = f.strength_actual + fuzz
                est = f"{low:,}~{high:,}"
            elif is_allied:
                # Allied: show accurate
                est = f"{f.strength_actual:,}"
            else:
                # Distant: show very fuzzy
                magnitude = len(str(f.strength_actual))
                if magnitude <= 4:
                    est = "数千"
                elif magnitude == 5:
                    est = "数万"
                else:
                    est = "十万以上"

            local.perceived_factions[fid] = PerceivedFaction(
                id=fid,
                name=f.name,
                estimated_strength=est,
                territory_count=len(f.territories),
                capital=f.capital,
                is_border=is_border,
                is_allied=is_allied,
            )

        # Visible armies — only allied or in own/border territories
        for army_id, army in world_state.armies.items():
            if army.total_troops <= 0:
                continue
            if army.faction_id == faction_id:
                # Own army: full visibility
                local.visible_armies[army_id] = {
                    "faction_id": army.faction_id,
                    "location": army.location,
                    "troops": army.total_troops,
                    "morale": army.morale,
                    "commander": army.commander_id,
                }
            elif army.faction_id in (faction.allies or []):
                # Allied army: visible with exact numbers
                local.visible_armies[army_id] = {
                    "faction_id": army.faction_id,
                    "location": army.location,
                    "troops": army.total_troops,
                }
            elif army.location in border_territories or army.location in faction.territories:
                # Enemy in border/own territory: visible with fuzz
                fuzz = int(army.total_troops * self.ESTIMATE_FUZZ)
                low = max(0, army.total_troops - fuzz)
                high = army.total_troops + fuzz
                local.visible_armies[army_id] = {
                    "faction_id": army.faction_id,
                    "location": army.location,
                    "estimated_troops": f"{low:,}~{high:,}",
                }
            # Hidden armies (non-border, non-allied) are NOT included

        # Border garrison estimates
        for tid in border_territories:
            garrison = self._estimate_garrison(tid, world_state, faction_id)
            if garrison:
                local.border_garrisons[tid] = garrison

        # Public chronicle log
        if hasattr(world_state, "chronicle"):
            local.chronicle_entries = list(world_state.chronicle[-10:])

        return local

    def _compute_borders(self, world_state: WorldState, faction_id: str) -> set[str]:
        """Find all territories bordering the given faction."""
        faction = world_state.factions.get(faction_id)
        if not faction:
            return set()

        borders: set[str] = set()
        for own_tid in faction.territories:
            own_t = world_state.territories.get(own_tid)
            if not own_t:
                continue
            for neighbor_id in own_t.neighbors:
                neighbor = world_state.territories.get(neighbor_id)
                if neighbor and neighbor.owner_id != faction_id:
                    borders.add(neighbor_id)
        return borders

    def _estimate_garrison(
        self,
        territory_id: str,
        world_state: WorldState,
        viewer_faction_id: str,
        recon: object | None = None,
    ) -> dict | None:
        """Estimate total troops in a border territory."""
        territory = world_state.territories.get(territory_id)
        if not territory:
            return None

        total = 0
        for army in world_state.armies.values():
            if army.location == territory_id and army.faction_id != viewer_faction_id:
                total += army.total_troops

        if total == 0:
            return None

        # Check for disinformation
        if recon and hasattr(recon, "get_disinformation"):
            fake = recon.get_disinformation(viewer_faction_id, territory_id)
            if fake is not None:
                total = fake
                fuzz = int(total * self.SCOUTED_FUZZ)
                return {
                    "territory_name": territory.name,
                    "owner": territory.owner_id,
                    "estimated_troops": f"{max(0, total - fuzz):,}~{total + fuzz:,}",
                    "scouted": True,
                    "disinformed": True,
                }

        # Use narrower fuzz if scouted
        if recon and hasattr(recon, "is_scouted"):
            fuzz_pct = (
                self.SCOUTED_FUZZ
                if recon.is_scouted(viewer_faction_id, territory_id)
                else self.ESTIMATE_FUZZ
            )
        else:
            fuzz_pct = self.ESTIMATE_FUZZ

        fuzz = int(total * fuzz_pct)
        return {
            "territory_name": territory.name,
            "owner": territory.owner_id,
            "estimated_troops": f"{max(0, total - fuzz):,}~{total + fuzz:,}",
            "scouted": recon.is_scouted(viewer_faction_id, territory_id)
            if recon and hasattr(recon, "is_scouted")
            else False,
        }

    def _char_role(self, char: Character, faction_id: str, world_state: WorldState) -> str:
        """Determine a character's role (governor, commander, etc.)."""
        if char.is_governor:
            for tid in (
                world_state.factions[faction_id].territories
                if faction_id in world_state.factions
                else []
            ):
                pass  # Governor detection would need territory-tracking logic
            return "太守"
        if char.is_commanding:
            return "主帅"
        return "幕僚"
