"""
Military Engine — recruitment, movement, combat, and supply.

Pure-math engine. No LLM dependency.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..world import Army, BattleResult, CombatResult, Season, TerrainType, Territory, UnitType

if TYPE_CHECKING:
    from ..character import CharacterEngine
    from ..map import MapEngine

# ─── Unit stats ──────────────────────────────────────────────────

UNIT_STATS: dict[UnitType, dict] = {
    UnitType.INFANTRY: {"cost": 3, "atk": 10, "def": 10, "speed": 1},
    UnitType.CAVALRY: {"cost": 10, "atk": 14, "def": 7, "speed": 2},
    UnitType.ARCHER: {"cost": 6, "atk": 8, "def": 13, "speed": 1},
    UnitType.NAVY: {"cost": 8, "atk": 9, "def": 10, "speed": 1.5},
}

# Unit special terrain bonuses (applied on top of terrain modifiers)
UNIT_TERRAIN_BONUSES: dict[UnitType, dict[str, float]] = {
    UnitType.INFANTRY: {"city_defense": 5},
    UnitType.CAVALRY: {"plains_attack": 5},
    UnitType.ARCHER: {"forest_defense": 3},
    UnitType.NAVY: {"river_attack": 8},
}

# Resource requirements for recruitment
UNIT_RESOURCES: dict[UnitType, list[str]] = {
    UnitType.INFANTRY: [],
    UnitType.CAVALRY: ["horse_resource"],
    UnitType.ARCHER: ["iron_resource"],
    UnitType.NAVY: ["has_river_or_coast"],
}

SUPPLY_RANGE = 2
MAX_ATTRITION = 0.20  # 20% max troop loss per turn from attrition
ATTRITION_PER_TILE = 0.05  # 5% per tile beyond supply range
WINTER_CONSUMPTION_MULT = 1.5

# ─── Result types ────────────────────────────────────────────────


@dataclass
class RecruitResult:
    territory_id: str
    unit_type: UnitType
    amount: int
    cost: int
    success: bool
    reason: str = ""


@dataclass
class MoveResult:
    army_id: str
    from_location: str
    to_location: str
    distance_tiles: int
    success: bool
    reason: str = ""


@dataclass
class SupplyStatus:
    army_id: str
    supply_level: int
    in_range: bool
    attrition_pct: float
    winter_penalty: float
    troops_lost: int = 0


# ─── Military Engine ─────────────────────────────────────────────


class MilitaryEngine:
    """Handles recruitment, movement, combat resolution, and supply."""

    # ── Recruitment ──

    def recruit(
        self,
        territory: Territory,
        unit_type: UnitType,
        amount: int,
        treasury: int,
        population: int,
    ) -> RecruitResult:
        if amount <= 0:
            return RecruitResult(
                territory_id=territory.id,
                unit_type=unit_type,
                amount=0,
                cost=0,
                success=False,
                reason="招募数量必须大于0",
            )

        stats = UNIT_STATS[unit_type]
        cost_per_unit = stats["cost"]
        total_cost = cost_per_unit * amount

        # Check resource requirements
        for res in UNIT_RESOURCES.get(unit_type, []):
            if res == "horse_resource" and not territory.horse_resource:
                return RecruitResult(
                    territory_id=territory.id,
                    unit_type=unit_type,
                    amount=amount,
                    cost=total_cost,
                    success=False,
                    reason=f"招募{unit_type.value}需要马匹资源",
                )
            if res == "iron_resource" and not territory.iron_resource:
                return RecruitResult(
                    territory_id=territory.id,
                    unit_type=unit_type,
                    amount=amount,
                    cost=total_cost,
                    success=False,
                    reason=f"招募{unit_type.value}需要铁矿资源",
                )
            if res == "has_river_or_coast" and not (territory.has_river or territory.has_coast):
                return RecruitResult(
                    territory_id=territory.id,
                    unit_type=unit_type,
                    amount=amount,
                    cost=total_cost,
                    success=False,
                    reason=f"招募{unit_type.value}需要河流或海岸",
                )

        if treasury < total_cost:
            return RecruitResult(
                territory_id=territory.id,
                unit_type=unit_type,
                amount=amount,
                cost=total_cost,
                success=False,
                reason=f"资金不足: 需要{total_cost}，当前{treasury}",
            )

        if population < amount:
            return RecruitResult(
                territory_id=territory.id,
                unit_type=unit_type,
                amount=amount,
                cost=total_cost,
                success=False,
                reason=f"人口不足: 需要{amount}，当前{population}",
            )

        return RecruitResult(
            territory_id=territory.id,
            unit_type=unit_type,
            amount=amount,
            cost=total_cost,
            success=True,
            reason="",
        )

    # ── Movement ──

    def move_army(
        self,
        army: Army,
        destination: str,
        map_engine: MapEngine,
    ) -> MoveResult:
        if army.location == destination:
            return MoveResult(
                army_id=army.id,
                from_location=army.location,
                to_location=destination,
                distance_tiles=0,
                success=True,
                reason="已在目标位置",
            )

        path_result = map_engine.find_path(army.location, destination, army.faction_id)

        if not path_result.path or path_result.total_cost == float("inf"):
            return MoveResult(
                army_id=army.id,
                from_location=army.location,
                to_location=destination,
                distance_tiles=0,
                success=False,
                reason="无法到达目的地",
            )

        # Calculate army speed: slowest unit determines speed
        army_speed = self._army_speed(army)
        path_tiles = len(path_result.path) - 1  # number of edges to traverse

        if path_tiles == 0:
            return MoveResult(
                army_id=army.id,
                from_location=army.location,
                to_location=destination,
                distance_tiles=0,
                success=True,
                reason="已在目标位置",
            )

        # Move up to army_speed tiles along the path
        max_step = min(path_tiles, max(1, int(army_speed)))
        new_location = path_result.path[max_step]

        army.location = new_location

        return MoveResult(
            army_id=army.id,
            from_location=army.location if new_location != path_result.path[0] else army.location,
            to_location=new_location,
            distance_tiles=max_step,
            success=True,
            reason="",
        )

    def _army_speed(self, army: Army) -> float:
        speeds = []
        for unit_type, count in army.units.items():
            if count > 0:
                speeds.append(UNIT_STATS[unit_type]["speed"])
        return min(speeds) if speeds else 1.0

    # ── Battle resolution ──

    def resolve_battle(
        self,
        attacker: Army,
        defender: Army,
        location: str,
        map_engine: MapEngine,
        char_engine: CharacterEngine | None = None,
    ) -> CombatResult:
        terrain = map_engine.get_terrain(location)

        # Calculate base power
        atk_power = self._calculate_power(attacker, is_attack=True, terrain=terrain)
        def_power = self._calculate_power(defender, is_attack=False, terrain=terrain)

        # Apply terrain modifier per unit type
        atk_terrain_mod = self._aggregate_terrain_mod(attacker, location, map_engine, "attack")
        def_terrain_mod = self._aggregate_terrain_mod(defender, location, map_engine, "defense")

        atk_power *= atk_terrain_mod
        def_power *= def_terrain_mod

        # Apply commander bonuses
        if char_engine and attacker.commander_id:
            atk_power *= char_engine.get_commander_bonus(attacker.commander_id)
        if char_engine and defender.commander_id:
            def_power *= char_engine.get_commander_bonus(defender.commander_id)

        # Apply fortification bonus to defender
        def_power *= map_engine.get_fortification_bonus(location)

        # ── Terrain defense modifier ──
        # Mountainous/hill terrain favors defenders (historical: Sichuan basin,
        # Fujian highlands repelled invaders for centuries)
        if terrain in (TerrainType.MOUNTAIN, TerrainType.HILLS):
            def_power *= 1.30  # +30% defense in rough terrain
            # Cavalry is severely hindered in mountains
            if terrain == TerrainType.MOUNTAIN:
                atk_power *= 0.70  # -30% attack in mountains

        # ── Cavalry charge bonus ──
        # Factions with significant cavalry get a decisive advantage
        # against infantry-heavy defenders (historical: Eight Banners vs Ming infantry)
        atk_cav = attacker.units.get(UnitType.CAVALRY, 0)
        atk_total = attacker.total_troops
        def_cav = defender.units.get(UnitType.CAVALRY, 0)
        def_total = defender.total_troops
        atk_cav_ratio = atk_cav / max(atk_total, 1)
        def_cav_ratio = def_cav / max(def_total, 1)

        if atk_cav_ratio > 0.25 and def_cav_ratio < 0.15:
            # Cavalry charge against infantry: +30% power
            atk_power *= 1.30
        if atk_cav_ratio > 0.35 and terrain == TerrainType.PLAINS:
            # Heavy cavalry on open plains: devastating charge, additional +15%
            atk_power *= 1.15

        # ── Navy vs non-navy coastal advantage ──
        atk_navy = attacker.units.get(UnitType.NAVY, 0)
        def_navy = defender.units.get(UnitType.NAVY, 0)
        if atk_navy > 0 and def_navy == 0:
            t = map_engine.territories.get(location)
            if t and (t.has_coast or t.has_river):
                atk_power *= 1.20  # Naval superiority on coastal/river terrain

        # Determine result
        ratio = float("inf") if def_power == 0 else atk_power / def_power

        if ratio > 2.0:
            result = BattleResult.DECISIVE_VICTORY
            atk_loss_pct, def_loss_pct = 0.05, 0.50
        elif ratio > 1.3:
            result = BattleResult.VICTORY
            atk_loss_pct, def_loss_pct = 0.10, 0.30
        elif ratio > 0.7:
            result = BattleResult.DRAW
            atk_loss_pct, def_loss_pct = 0.15, 0.15
        elif ratio > 0.5:
            result = BattleResult.DEFEAT
            atk_loss_pct, def_loss_pct = 0.30, 0.10
        else:
            result = BattleResult.DECISIVE_DEFEAT
            atk_loss_pct, def_loss_pct = 0.50, 0.05

        # Apply casualties
        atk_casualties = self._apply_casualties(attacker, atk_loss_pct)
        def_casualties = self._apply_casualties(defender, def_loss_pct)

        territory_captured = result in (BattleResult.DECISIVE_VICTORY, BattleResult.VICTORY)

        battle_id = f"battle_{uuid.uuid4().hex[:8]}"

        return CombatResult(
            battle_id=battle_id,
            location=location,
            attacker_id=attacker.faction_id,
            defender_id=defender.faction_id,
            result=result,
            attacker_casualties=atk_casualties,
            defender_casualties=def_casualties,
            territory_captured=territory_captured,
        )

    def _calculate_power(
        self, army: Army, is_attack: bool, terrain: TerrainType | None = None
    ) -> float:
        power = 0.0
        for unit_type, count in army.units.items():
            if count <= 0:
                continue
            stats = UNIT_STATS[unit_type]
            stat_key = "atk" if is_attack else "def"
            base = stats[stat_key]

            # Apply special unit-terrain bonuses
            bonus = self._unit_terrain_bonus(unit_type, terrain, is_attack)
            effective_stat = base + bonus

            power += count * effective_stat * (army.morale / 100.0) * army.training
        return power

    def _unit_terrain_bonus(
        self, unit_type: UnitType, terrain: TerrainType | None, is_attack: bool
    ) -> float:
        """Get special terrain bonus for a unit type (e.g., cavalry on plains)."""
        if terrain is None:
            return 0.0
        bonuses = UNIT_TERRAIN_BONUSES.get(unit_type, {})
        if unit_type == UnitType.CAVALRY and terrain == TerrainType.PLAINS and is_attack:
            return bonuses.get("plains_attack", 0)
        if unit_type == UnitType.ARCHER and terrain == TerrainType.FOREST and not is_attack:
            return bonuses.get("forest_defense", 0)
        if unit_type == UnitType.NAVY and terrain == TerrainType.RIVER and is_attack:
            return bonuses.get("river_attack", 0)
        # City defense bonus for infantry when defending in any terrain with fortification
        if unit_type == UnitType.INFANTRY and not is_attack:
            return bonuses.get("city_defense", 0)
        return 0.0

    def _aggregate_terrain_mod(
        self, army: Army, location: str, map_engine: MapEngine, mod_type: str
    ) -> float:
        """Weighted-average terrain modifier across all unit types in the army."""
        total_count = army.total_troops
        if total_count == 0:
            return 1.0

        weighted_mod = 0.0
        for unit_type, count in army.units.items():
            if count <= 0:
                continue
            mod = map_engine.get_combat_modifier(location, unit_type, mod_type)
            weighted_mod += mod * count

        return weighted_mod / total_count

    def _apply_casualties(self, army: Army, loss_pct: float) -> dict[UnitType, int]:
        """Apply percentage losses to an army, distributed across unit types."""
        casualties: dict[UnitType, int] = {}
        for unit_type, count in list(army.units.items()):
            lost = int(count * loss_pct)
            if lost > 0:
                casualties[unit_type] = lost
                army.units[unit_type] = count - lost
        return casualties

    # ── Supply ──

    def calculate_supply(
        self,
        army: Army,
        map_engine: MapEngine,
        season: Season | None = None,
    ) -> SupplyStatus:
        territory = map_engine.territories.get(army.location)
        if not territory:
            return SupplyStatus(
                army_id=army.id,
                supply_level=0,
                in_range=False,
                attrition_pct=MAX_ATTRITION,
                winter_penalty=1.0,
                troops_lost=0,
            )

        # Friendly territory: auto refill
        if territory.owner_id == army.faction_id:
            return SupplyStatus(
                army_id=army.id,
                supply_level=30,
                in_range=True,
                attrition_pct=0.0,
                winter_penalty=season.supply_multiplier if season else 1.0,
                troops_lost=0,
            )

        # Find nearest friendly territory distance (BFS up to 2 tiles)
        nearest = self._find_nearest_friendly(
            army.location, army.faction_id, map_engine, max_depth=SUPPLY_RANGE + 5
        )

        in_range = nearest <= SUPPLY_RANGE
        if nearest < 0:
            # No friendly territory reachable at all
            attrition_pct = MAX_ATTRITION
        elif in_range:
            attrition_pct = 0.0
        else:
            # 5% per tile beyond supply range
            extra_tiles = nearest - SUPPLY_RANGE
            attrition_pct = min(ATTRITION_PER_TILE * extra_tiles, MAX_ATTRITION)

        winter_penalty = season.supply_multiplier if season else 1.0

        if attrition_pct > 0 and winter_penalty > 1.0:
            attrition_pct *= winter_penalty

        troops_lost = 0
        if attrition_pct > 0:
            troops_lost = int(army.total_troops * attrition_pct)
            # Apply attrition proportionally
            for unit_type, count in list(army.units.items()):
                if count <= 0:
                    continue
                lost = int(count * attrition_pct)
                if lost > 0:
                    army.units[unit_type] = max(0, count - lost)

        return SupplyStatus(
            army_id=army.id,
            supply_level=army.supply,
            in_range=in_range,
            attrition_pct=attrition_pct,
            winter_penalty=winter_penalty,
            troops_lost=troops_lost,
        )

    def _find_nearest_friendly(
        self,
        origin: str,
        faction_id: str,
        map_engine: MapEngine,
        max_depth: int = 7,
    ) -> int:
        """BFS to find the shortest distance (in tiles) to a friendly territory."""
        if origin not in map_engine.territories:
            return -1

        visited = {origin}
        queue = deque([(origin, 0)])

        while queue:
            current, dist = queue.popleft()
            territory = map_engine.territories.get(current)
            if territory and territory.owner_id == faction_id and dist > 0:
                return dist

            if dist >= max_depth:
                continue

            for neighbor in map_engine.get_neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))

        return -1
