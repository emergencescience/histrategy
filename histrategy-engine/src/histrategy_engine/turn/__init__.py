"""
Turn Controller — orchestrates the 10-step turn sequence.

Coordinates all engines to process one complete game turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world import (
    Army,
    BattleResult,
    Command,
    Season,
    TurnResult,
    UnitType,
    WorldState,
)

if TYPE_CHECKING:
    from ..ai import DecisionEngine
    from ..character import CharacterEngine
    from ..domestic import DomesticEngine
    from ..map import MapEngine
    from ..military import MilitaryEngine


class TurnController:
    """Orchestrates full turn execution across all engines."""

    def __init__(
        self,
        map_engine: MapEngine,
        char_engine: CharacterEngine,
        domestic_engine: DomesticEngine,
        military_engine: MilitaryEngine,
        decision_engine: DecisionEngine,
    ):
        self.map_engine = map_engine
        self.char_engine = char_engine
        self.domestic_engine = domestic_engine
        self.military_engine = military_engine
        self.decision_engine = decision_engine

    def execute_turn(
        self,
        world_state: WorldState,
        player_commands: list[Command] | None = None,
        year: int = 207,
        turn_number: int = 1,
    ) -> TurnResult:
        """
        Execute a full turn sequence.

        1. Climate roll
        2. Resource production
        3. Collect commands (player + NPC)
        4. Command validation
        5. Move resolution
        6. Battle resolution
        7. Domestic execution (recruit/develop)
        8. Character updates (death + loyalty)
        9. State persistence (skip)
        10. Return TurnResult
        """
        season = world_state.season

        # ── Step 1: Climate roll ──
        climate_events = self.domestic_engine.climate.roll_all(
            world_state.territories, season, year, turn_number
        )

        # ── Step 2: Resource production ──
        # Calculate troop counts per territory
        territory_troops = {tid: 0 for tid in world_state.territories}
        for army in world_state.armies.values():
            if army.location in territory_troops:
                territory_troops[army.location] += army.total_troops

        # Build tax_rates and tech_levels from factions
        tax_rates = {
            fid: f.tax_rate for fid, f in world_state.factions.items() if f.is_active
        }
        tech_levels = {
            fid: f.tech_levels for fid, f in world_state.factions.items() if f.is_active
        }

        territory_results = self.domestic_engine.process_season(
            world_state.territories,
            season,
            year,
            turn_number,
            char_engine=self.char_engine,
            tax_rates=tax_rates,
            tech_levels=tech_levels,
            territory_troops=territory_troops,
        )

        # Apply season results: update faction treasuries and food
        resource_changes: dict[str, dict] = {}
        for tr in territory_results:
            territory = world_state.territories.get(tr.territory_id)
            if not territory or not territory.owner_id:
                continue
            fid = territory.owner_id
            faction = world_state.factions.get(fid)
            if not faction:
                continue
            faction.food += tr.food_delta
            faction.treasury += tr.tax_revenue
            faction.morale_actual = max(0, min(100, faction.morale_actual + tr.morale_change))

            if fid not in resource_changes:
                resource_changes[fid] = {"food_delta": 0, "tax_revenue": 0}
            resource_changes[fid]["food_delta"] += tr.food_delta
            resource_changes[fid]["tax_revenue"] += tr.tax_revenue

        # Check for famine across all active factions
        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            if faction.food < 0:
                faction.food = 0
                # Famine!
                faction.morale_actual = max(0, faction.morale_actual - 5)
                faction.legitimacy = max(0, faction.legitimacy - 10)
                # Population in all territories of this faction drops by 5%
                for tid in list(faction.territories):
                    t = world_state.territories.get(tid)
                    if t:
                        pop_loss = int(t.population * 0.05)
                        t.population = max(100, t.population - pop_loss)
                # Log famine in resource changes
                if fid not in resource_changes:
                    resource_changes[fid] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[fid]["famine_occurred"] = True

        # ── Step 3: Collect commands ──
        all_commands: list[Command] = list(player_commands or [])

        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue
            if fid == world_state.player_faction_id:
                continue
            npc_commands = self.decision_engine.generate_commands(
                fid, world_state, self.map_engine
            )
            all_commands.extend(npc_commands)

        # ── Step 4: Command validation ──
        valid_commands = self._validate_commands(all_commands, world_state)

        # Separate commands by type
        move_commands = [c for c in valid_commands if c.type in ("move", "attack")]
        domestic_commands = [c for c in valid_commands if c.type in ("recruit", "develop", "tax")]

        # ── Step 5: Move resolution ──
        move_results = []
        for cmd in move_commands:
            result = self._execute_move(cmd, world_state)
            if result:
                move_results.append(result)

        # ── Step 6: Battle resolution ──
        battles = self._resolve_all_battles(world_state)

        # ── Step 7: Domestic execution ──
        for cmd in domestic_commands:
            self._execute_domestic(cmd, world_state, resource_changes)

        # ── Step 8: Character updates ──
        character_events: list[dict] = []

        # Annual loyalty changes (applied in Winter)
        if season == Season.WINTER:
            from histrategy_engine.character.loyalty import calculate_loyalty_change
            for char in world_state.characters.values():
                if char.alive and char.faction_id:
                    faction = world_state.factions.get(char.faction_id)
                    if faction:
                        delta = calculate_loyalty_change(faction.legitimacy, char.politics)
                        if delta != 0:
                            char.loyalty = max(0, min(100, char.loyalty + delta))
                            character_events.append({
                                "type": "loyalty_change",
                                "character_id": char.id,
                                "character_name": char.name,
                                "delta": delta,
                                "new_loyalty": char.loyalty,
                                "reason": f"势力合法性影响(当前合法性: {faction.legitimacy})"
                            })

        for char_id in list(world_state.characters.keys()):
            char = world_state.characters[char_id]
            if not char.alive:
                continue

            # Natural death check
            if self.char_engine.check_natural_death(
                char_id, year, world_state.player_deviation
            ):
                impacts = self.char_engine.kill_character(char_id)
                character_events.append({
                    "type": "natural_death",
                    "character_id": char_id,
                    "character_name": char.name,
                    "year": year,
                })
                for impact in impacts:
                    character_events.append({
                        "type": "loyalty_impact",
                        **impact,
                    })

            # Loyalty check for discontented
            if char.faction_id:
                discontented = self.char_engine.get_discontented(char.faction_id)
                for dc in discontented:
                    if dc.id == char_id:
                        defections = self.char_engine.check_defections(char.faction_id)
                        for d in defections:
                            character_events.append(d)
                            # Actually apply defection: remove from faction and clear roles
                            defect_char = world_state.characters.get(d["character_id"])
                            if defect_char:
                                defect_char.faction_id = ""
                                defect_char.is_governor = False
                                defect_char.is_commanding = False
                                # Clear commander reference in armies
                                for army in world_state.armies.values():
                                    if army.commander_id == d["character_id"]:
                                        army.commander_id = ""

        # Update faction legitimacy based on events gathered during the turn
        from histrategy_engine.governance.legitimacy import LegitimacyState, update_legitimacy

        for fid, faction in world_state.factions.items():
            if not faction.is_active:
                continue

            events = []
            if faction.tax_rate >= 0.4:
                events.append("heavy_tax")

            for combat in battles:
                if combat.attacker_id == fid and combat.result in (BattleResult.VICTORY, BattleResult.DECISIVE_VICTORY):
                    events.append("win_battle")
                elif combat.defender_id == fid and combat.result in (BattleResult.DEFEAT, BattleResult.DECISIVE_DEFEAT):
                    events.append("win_battle")

            leg_state = LegitimacyState(current_score=faction.legitimacy)
            updated_state = update_legitimacy(leg_state, events)
            faction.legitimacy = updated_state.current_score

        # ── Step 9: State persistence (skip) ──

        # ── Step 10: Return TurnResult ──
        # Build faction snapshots
        faction_snapshots = {
            fid: f for fid, f in world_state.factions.items()
        }

        # Advance season
        self._advance_season(world_state)

        return TurnResult(
            year=year,
            season=season,
            turn_number=turn_number,
            climate_events=climate_events,
            resource_changes=resource_changes,
            battles=battles,
            diplomatic_events=[],
            character_events=character_events,
            history_events=[],
            faction_snapshots=faction_snapshots,
        )

    # ── Helpers ──

    def _validate_commands(
        self, commands: list[Command], world_state: WorldState
    ) -> list[Command]:
        valid: list[Command] = []
        for cmd in commands:
            if self._is_valid_command(cmd, world_state):
                valid.append(cmd)
        return valid

    def _is_valid_command(self, cmd: Command, world_state: WorldState) -> bool:
        if not cmd.faction_id:
            return False

        faction = world_state.factions.get(cmd.faction_id)
        if not faction or not faction.is_active:
            return False

        if cmd.type in ("recruit", "develop"):
            tid = cmd.params.get("territory", "")
            territory = world_state.territories.get(tid)
            if not territory:
                return False
            if territory.owner_id != cmd.faction_id:
                return False
            return True

        if cmd.type in ("move", "attack"):
            target = cmd.params.get("destination") or cmd.params.get("target_territory", "")
            if not target or target not in world_state.territories:
                return False
            return True

        if cmd.type == "tax":
            rate = cmd.params.get("rate")
            if rate is None or not (0.1 <= rate <= 0.5):
                return False
            return True

        return False

    def _execute_move(self, cmd: Command, world_state: WorldState) -> dict | None:
        faction_id = cmd.faction_id
        target = cmd.params.get("destination") or cmd.params.get("target_territory", "")

        # Find an army belonging to this faction
        army = self._find_faction_army(faction_id, world_state, prefer_border=True)
        if not army:
            return None

        result = self.military_engine.move_army(army, target, self.map_engine)
        return {
            "command_type": cmd.type,
            "faction_id": faction_id,
            "army_id": army.id,
            "from": result.from_location,
            "to": result.to_location,
            "success": result.success,
            "reason": result.reason,
        }

    def _execute_domestic(
        self, cmd: Command, world_state: WorldState, resource_changes: dict
    ) -> None:
        faction_id = cmd.faction_id
        faction = world_state.factions.get(faction_id)
        if not faction:
            return

        if cmd.type == "recruit":
            tid = cmd.params.get("territory", "")
            unit_type_str = cmd.params.get("unit_type", "infantry")
            amount = cmd.params.get("amount", 500)

            try:
                unit_type = UnitType(unit_type_str)
            except ValueError:
                return

            territory = world_state.territories.get(tid)
            if not territory:
                return

            rec_result = self.military_engine.recruit(
                territory, unit_type, amount, faction.treasury, territory.population
            )

            if rec_result.success:
                faction.treasury -= rec_result.cost
                territory.population -= amount

                # Add to an army in this territory
                army = self._find_or_create_army(faction_id, tid, world_state)
                army.units[unit_type] = army.units.get(unit_type, 0) + amount
                faction.strength_actual += amount

                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + rec_result.cost
                )

        elif cmd.type == "develop":
            tid = cmd.params.get("territory", "")
            territory = world_state.territories.get(tid)
            if not territory or territory.owner_id != faction_id:
                return

            # Calculate development cost
            current_dev = territory.development
            target_dev = min(100, current_dev + 5)
            cost = self.domestic_engine.calculate_development_cost(territory, target_dev)

            if faction.treasury >= cost:
                faction.treasury -= cost
                territory.development = target_dev
                if faction_id not in resource_changes:
                    resource_changes[faction_id] = {"food_delta": 0, "tax_revenue": 0}
                resource_changes[faction_id]["treasury_spent"] = (
                    resource_changes[faction_id].get("treasury_spent", 0) + cost
                )

        elif cmd.type == "tax":
            rate = cmd.params.get("rate", 0.3)
            faction.tax_rate = max(0.1, min(0.5, rate))

    def _resolve_all_battles(self, world_state: WorldState) -> list:
        """Find all territories with armies from different factions and resolve battles."""
        battles = []

        # Group armies by location
        location_armies: dict[str, list[Army]] = {}
        for army in world_state.armies.values():
            if army.total_troops <= 0:
                continue
            location_armies.setdefault(army.location, []).append(army)

        for location, armies in location_armies.items():
            # Only resolve if multiple factions present
            faction_ids = {a.faction_id for a in armies}
            if len(faction_ids) < 2:
                continue

            # Resolve battles pairwise between hostile factions
            resolved_pairs: set[tuple[str, str]] = set()

            for i, army_a in enumerate(armies):
                for army_b in armies[i + 1:]:
                    if army_a.faction_id == army_b.faction_id:
                        continue
                    pair = tuple(sorted([army_a.faction_id, army_b.faction_id]))
                    if pair in resolved_pairs:
                        continue
                    resolved_pairs.add(pair)

                    # Attacker is the one who moved into the territory (simplified: first)
                    attacker = army_a
                    defender = army_b

                    combat = self.military_engine.resolve_battle(
                        attacker, defender, location,
                        self.map_engine, self.char_engine,
                    )
                    battles.append(combat)

                    # If territory captured, change ownership to attacker
                    if combat.territory_captured:
                        territory = world_state.territories.get(location)
                        if territory:
                            old_owner = territory.owner_id
                            territory.owner_id = attacker.faction_id

                            # Update faction territories
                            if old_owner and old_owner in world_state.factions:
                                old_faction = world_state.factions[old_owner]
                                if location in old_faction.territories:
                                    old_faction.territories.remove(location)
                            if attacker.faction_id in world_state.factions:
                                atk_faction = world_state.factions[attacker.faction_id]
                                if location not in atk_faction.territories:
                                    atk_faction.territories.append(location)

        return battles

    def _find_faction_army(
        self, faction_id: str, world_state: WorldState, prefer_border: bool = False
    ) -> Army | None:
        """Find an army belonging to a faction, optionally preferring border armies."""
        faction_armies = [
            a for a in world_state.armies.values()
            if a.faction_id == faction_id and a.total_troops > 0
        ]

        if not faction_armies:
            return None

        if prefer_border:
            borders = self.map_engine.get_border_territories(faction_id)
            border_armies = [a for a in faction_armies if a.location in borders]
            if border_armies:
                return border_armies[0]

        return faction_armies[0]

    def _find_or_create_army(
        self, faction_id: str, territory_id: str, world_state: WorldState
    ) -> Army:
        """Find an existing army in the territory or create a new one."""
        for army in world_state.armies.values():
            if army.faction_id == faction_id and army.location == territory_id:
                return army

        army_id = f"army_{faction_id}_{territory_id}"
        army = Army(
            id=army_id,
            faction_id=faction_id,
            location=territory_id,
        )
        world_state.armies[army_id] = army
        return army

    def _advance_season(self, world_state: WorldState) -> None:
        """Advance to the next season."""
        seasons = [Season.SPRING, Season.SUMMER, Season.AUTUMN, Season.WINTER]
        idx = seasons.index(world_state.season)
        next_idx = (idx + 1) % 4
        world_state.season = seasons[next_idx]
        if next_idx == 0:
            world_state.year += 1
        world_state.turn_number += 1
