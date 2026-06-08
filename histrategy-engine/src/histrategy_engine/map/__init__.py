"""
Map Engine — spatial world representation.

Handles territory topology, terrain effects, pathfinding (A*),
strategic choke-points, and visibility/fog-of-war.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..world import StrategicPoint, TerrainType, Territory, UnitType

if TYPE_CHECKING:
    pass  # avoid circular imports at type-check time


# ─── Terrain combat modifiers ──────────────────────────────────

TERRAIN_MODIFIERS: dict[tuple[TerrainType, UnitType], dict[str, float]] = {
    # (terrain, unit) → {attack_mod, defense_mod, move_cost}
    (TerrainType.PLAINS, UnitType.INFANTRY):     {"attack": 1.0, "defense": 1.0, "move": 1.0},
    (TerrainType.PLAINS, UnitType.CAVALRY):      {"attack": 1.3, "defense": 0.9, "move": 0.6},
    (TerrainType.PLAINS, UnitType.ARCHER):       {"attack": 1.0, "defense": 0.8, "move": 1.0},
    (TerrainType.PLAINS, UnitType.NAVY):         {"attack": 0.1, "defense": 0.1, "move": 99},
    (TerrainType.HILLS, UnitType.INFANTRY):      {"attack": 1.0, "defense": 1.2, "move": 1.3},
    (TerrainType.HILLS, UnitType.CAVALRY):       {"attack": 0.8, "defense": 0.9, "move": 1.8},
    (TerrainType.HILLS, UnitType.ARCHER):        {"attack": 1.1, "defense": 1.0, "move": 1.2},
    (TerrainType.HILLS, UnitType.NAVY):          {"attack": 0.1, "defense": 0.1, "move": 99},
    (TerrainType.MOUNTAIN, UnitType.INFANTRY):   {"attack": 0.7, "defense": 1.5, "move": 2.5},
    (TerrainType.MOUNTAIN, UnitType.CAVALRY):    {"attack": 0.3, "defense": 0.6, "move": 4.0},
    (TerrainType.MOUNTAIN, UnitType.ARCHER):     {"attack": 1.2, "defense": 1.3, "move": 2.0},
    (TerrainType.MOUNTAIN, UnitType.NAVY):       {"attack": 0.0, "defense": 0.0, "move": 99},
    (TerrainType.FOREST, UnitType.INFANTRY):     {"attack": 0.9, "defense": 1.3, "move": 1.4},
    (TerrainType.FOREST, UnitType.CAVALRY):      {"attack": 0.5, "defense": 0.7, "move": 2.2},
    (TerrainType.FOREST, UnitType.ARCHER):       {"attack": 0.7, "defense": 1.4, "move": 1.5},
    (TerrainType.FOREST, UnitType.NAVY):         {"attack": 0.0, "defense": 0.0, "move": 99},
    (TerrainType.WETLAND, UnitType.INFANTRY):    {"attack": 0.8, "defense": 1.0, "move": 2.0},
    (TerrainType.WETLAND, UnitType.CAVALRY):     {"attack": 0.4, "defense": 0.5, "move": 3.5},
    (TerrainType.WETLAND, UnitType.ARCHER):      {"attack": 0.8, "defense": 0.9, "move": 2.0},
    (TerrainType.WETLAND, UnitType.NAVY):        {"attack": 0.1, "defense": 0.1, "move": 99},
    (TerrainType.RIVER, UnitType.NAVY):          {"attack": 1.5, "defense": 1.2, "move": 0.5},
    (TerrainType.COAST, UnitType.NAVY):          {"attack": 1.3, "defense": 1.1, "move": 0.7},
}

# Default for any (terrain, unit) not explicitly defined
_DEFAULT_MODIFIER = {"attack": 1.0, "defense": 1.0, "move": 1.0}


def _get_mod(terrain: TerrainType, unit: UnitType, key: str) -> float:
    return TERRAIN_MODIFIERS.get((terrain, unit), _DEFAULT_MODIFIER)[key]


# ─── Pathfinding ──────────────────────────────────────────────


@dataclass
class PathResult:
    path: list[str]       # ordered territory IDs from origin to dest
    total_cost: float     # sum of movement costs
    turns_required: int   # how many game turns this takes
    blocked_by: str = ""  # strategic_point_id if blocked


class MapEngine:
    """Manages spatial data and movement logic."""

    def __init__(self, territories: dict[str, Territory] | None = None):
        self._territories: dict[str, Territory] = territories or {}
        self._adjacency: dict[str, list[str]] = {}
        if territories:
            self._build_adjacency()

    # ── Data loading ──

    def load_territories(self, territories: dict[str, Territory]) -> None:
        self._territories = territories
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        self._adjacency = {}
        for tid, t in self._territories.items():
            self._adjacency[tid] = list(t.neighbors)

    @property
    def territories(self) -> dict[str, Territory]:
        return self._territories

    # ── Terrain queries ──

    def get_terrain(self, territory_id: str) -> TerrainType:
        t = self._territories.get(territory_id)
        return t.terrain_type if t else TerrainType.PLAINS

    def get_combat_modifier(
        self, territory_id: str, unit_type: UnitType, mod_type: str = "attack"
    ) -> float:
        """Get terrain combat modifier for a unit type at a location."""
        terrain = self.get_terrain(territory_id)
        return _get_mod(terrain, unit_type, mod_type)

    def get_fortification_bonus(self, territory_id: str) -> float:
        """Defender fortification bonus: 1.0 (none) → 1.5 (max fort)."""
        t = self._territories.get(territory_id)
        if not t:
            return 1.0
        return 1.0 + t.fortification / 200.0

    # ── Movement cost ──

    def get_move_cost(self, territory_id: str, unit_type: UnitType) -> float:
        """Base movement cost to traverse this territory."""
        terrain = self.get_terrain(territory_id)
        return _get_mod(terrain, unit_type, "move")

    # ── Pathfinding (A*) ──

    def find_path(
        self,
        origin: str,
        destination: str,
        faction_id: str,
        unit_type: UnitType = UnitType.INFANTRY,
    ) -> PathResult:
        """
        A* pathfinding between territories.

        Returns the shortest path. Path is blocked by:
        - Enemy territories (cannot pass through)
        - Uncontrolled strategic points at borders
        """
        if origin not in self._territories or destination not in self._territories:
            return PathResult(path=[], total_cost=float("inf"), turns_required=-1)

        if origin == destination:
            return PathResult(path=[origin], total_cost=0.0, turns_required=0)

        # A* search
        frontier: list[tuple[float, str]] = [(0.0, origin)]
        came_from: dict[str, str] = {}
        cost_so_far: dict[str, float] = {origin: 0.0}

        while frontier:
            frontier.sort(key=lambda x: x[0])
            _, current = frontier.pop(0)

            if current == destination:
                break

            for neighbor_id in self._adjacency.get(current, []):
                if not self._can_pass(current, neighbor_id, faction_id):
                    continue

                move_cost = self.get_move_cost(neighbor_id, unit_type)
                new_cost = cost_so_far[current] + move_cost

                if neighbor_id not in cost_so_far or new_cost < cost_so_far[neighbor_id]:
                    cost_so_far[neighbor_id] = new_cost
                    priority = new_cost
                    frontier.append((priority, neighbor_id))
                    came_from[neighbor_id] = current

        if destination not in came_from and origin != destination:
            return PathResult(path=[], total_cost=float("inf"), turns_required=-1)

        # Reconstruct path
        path = [destination]
        current = destination
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()

        total_cost = cost_so_far.get(destination, float("inf"))
        # Convert cost to turns: roughly 1 turn = 2.0 movement units
        turns = max(1, int(total_cost / 2.0) + 1)

        return PathResult(path=path, total_cost=total_cost, turns_required=turns)

    def _can_pass(self, from_id: str, to_id: str, faction_id: str) -> bool:
        """Check if faction can move from one territory to its neighbor."""
        from_territory = self._territories.get(from_id)
        to_territory = self._territories.get(to_id)
        if not from_territory or not to_territory:
            return False

        # Cannot pass through enemy territory (explicitly hostile)
        # Neutral and allied territories are passable
        # For now, only block if target is an ACTIVE enemy (simplified: just allow non-owned)
        # TODO: check faction relationships for actual enemy status

        # Check if there's a strategic point blocking
        crossing_id = from_territory.neighbor_crossings.get(to_id)
        if crossing_id:
            for sp in from_territory.strategic_points:
                if sp.id == crossing_id:
                    if sp.owner_id and sp.owner_id != faction_id:
                        return False
                    break

        return True

    # ── Neighbor queries ──

    def get_neighbors(self, territory_id: str) -> list[str]:
        return self._adjacency.get(territory_id, [])

    def are_adjacent(self, a: str, b: str) -> bool:
        return b in self._adjacency.get(a, [])

    def get_border_territories(self, faction_id: str) -> list[str]:
        """Territories owned by faction that border foreign territory."""
        result = []
        for tid, t in self._territories.items():
            if t.owner_id != faction_id:
                continue
            for neighbor_id in self._adjacency.get(tid, []):
                neighbor = self._territories.get(neighbor_id)
                if neighbor and neighbor.owner_id != faction_id:
                    result.append(tid)
                    break
        return result

    # ── Visibility ──

    def get_visible_territories(self, faction_id: str) -> set[str]:
        """
        Territories visible to a faction.

        - Own territories: fully visible
        - Adjacent territories: partially visible (strength estimate has ±20% error)
        - Beyond: not visible (unless spy network)
        """
        visible: set[str] = set()

        for tid, t in self._territories.items():
            if t.owner_id == faction_id:
                visible.add(tid)
                # Adjacent territories are partially visible
                for neighbor_id in self._adjacency.get(tid, []):
                    visible.add(neighbor_id)

        return visible
