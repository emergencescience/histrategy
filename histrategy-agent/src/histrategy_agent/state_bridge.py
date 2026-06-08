"""
StateBridge — thin bridge between agent sessions and histrategy-engine.

Calls the deterministic engines (Map, Character, Domestic, Military)
to execute game commands and retrieve world state.
"""

from __future__ import annotations

import uuid
from typing import Any

from histrategy_engine import (
    Army,
    CharacterEngine,
    Command,
    DecisionEngine,
    DomesticEngine,
    FactionState,
    MapEngine,
    MilitaryEngine,
    Territory,
    UnitType,
    WorldState,
)


class StateBridge:
    """Bridges agent sessions to histrategy-engine deterministic engines."""

    def __init__(self, world_state: WorldState):
        self.world_state = world_state
        self.map_engine = MapEngine(world_state.territories)
        self.character_engine = CharacterEngine()
        self.domestic_engine = DomesticEngine()
        self.military_engine = MilitaryEngine()
        self.decision_engine = DecisionEngine(personality_profiles={
            "cao": {"aggression": 0.8, "cunning": 0.9, "caution": 0.3,
                    "diplomacy": 0.5, "development": 0.6, "mercy": 0.2},
            "shu": {"aggression": 0.3, "cunning": 0.3, "caution": 0.7,
                    "diplomacy": 0.8, "development": 0.8, "mercy": 0.95},
            "wu": {"aggression": 0.6, "cunning": 0.6, "caution": 0.5,
                   "diplomacy": 0.6, "development": 0.6, "mercy": 0.5},
            "liuzhang": {"aggression": 0.2, "cunning": 0.3, "caution": 0.8,
                         "diplomacy": 0.3, "development": 0.4, "mercy": 0.7},
            "liubiao": {"aggression": 0.2, "cunning": 0.4, "caution": 0.7,
                        "diplomacy": 0.6, "development": 0.7, "mercy": 0.8},
        })

    def execute_command(self, command: Command) -> dict:
        """Execute a game command through the appropriate engine.

        Returns {"success": bool, "result": ..., "message": str}
        """
        cmd_type = command.type
        params = command.params
        faction_id = command.faction_id

        if cmd_type == "recruit":
            return self._execute_recruit(faction_id, params)
        elif cmd_type == "move":
            return self._execute_move(faction_id, params)
        elif cmd_type == "attack":
            return self._execute_attack(faction_id, params)
        elif cmd_type == "develop":
            return self._execute_develop(faction_id, params)
        elif cmd_type == "tax":
            return self._execute_tax(faction_id, params)
        elif cmd_type == "diplomacy":
            return self._execute_diplomacy(faction_id, params)
        elif cmd_type == "info":
            return self._execute_info(faction_id)
        else:
            return {"success": False, "result": None, "message": f"未知命令类型: {cmd_type}"}

    def _execute_recruit(self, faction_id: str, params: dict) -> dict:
        unit_type_str = params.get("unit_type", "infantry")
        amount = params.get("amount", 1000)
        territory_id = params.get("territory", "")

        try:
            unit_type = UnitType(unit_type_str)
        except ValueError:
            return {"success": False, "result": None, "message": f"未知兵种: {unit_type_str}"}

        faction = self.world_state.factions.get(faction_id)
        if not faction:
            return {"success": False, "result": None, "message": f"势力不存在: {faction_id}"}

        # Use faction capital if no territory specified
        if not territory_id:
            territory_id = params.get("target", "") or faction.capital

        territory = self.world_state.territories.get(territory_id)
        if not territory:
            return {"success": False, "result": None, "message": f"领地不存在: {territory_id}"}

        result = self.military_engine.recruit(
            territory=territory,
            unit_type=unit_type,
            amount=amount,
            treasury=faction.treasury,
            population=territory.population,
        )

        if result.success:
            # Deduct cost
            faction.treasury -= result.cost
            territory.population -= result.amount

            # Add to army
            army = self._get_or_create_army(faction_id, territory_id)
            army.units[unit_type] = army.units.get(unit_type, 0) + result.amount

            return {
                "success": True,
                "result": result,
                "message": f"在{territory.name}招募了{result.amount}{unit_type.value}兵，花费{result.cost}金",
            }
        return {"success": False, "result": result, "message": result.reason}

    def _execute_move(self, faction_id: str, params: dict) -> dict:
        target = params.get("target", "")
        army_id = params.get("army_id", "")

        if not target:
            return {"success": False, "result": None, "message": "请指定移动目标"}

        # Respect explicit army_id, otherwise find best
        if army_id:
            army = self._find_army(faction_id, army_id)
        else:
            army = self._find_best_army_for_target(faction_id, target)
        if not army:
            return {"success": False, "result": None, "message": "没有找到可移动的军队"}

        result = self.military_engine.move_army(army, target, self.map_engine)
        if result.success:
            return {
                "success": True,
                "result": result,
                "message": f"军队从{result.from_location}移动到{result.to_location}，行军{result.distance_tiles}格",
            }
        return {"success": False, "result": result, "message": result.reason}

    def _execute_attack(self, faction_id: str, params: dict) -> dict:
        target = params.get("target", "")
        army_id = params.get("army_id", "")

        if not target:
            return {"success": False, "result": None, "message": "请指定攻击目标"}

        attacker = self._find_best_army_for_target(faction_id, target)
        if not attacker:
            return {"success": False, "result": None, "message": "没有找到可进攻的军队"}

        # Find defender army at target
        defender = self._find_defender(target)
        if not defender:
            # Create a garrison army for the defender
            defender = self._create_garrison(target)

        if attacker.location != target and not self.map_engine.are_adjacent(attacker.location, target):
            return {
                "success": False,
                "result": None,
                "message": f"军队不在{target}或其相邻领地，无法进攻",
            }

        result = self.military_engine.resolve_battle(
            attacker=attacker,
            defender=defender,
            location=target,
            map_engine=self.map_engine,
        )

        if result.territory_captured:
            territory = self.world_state.territories.get(target)
            if territory:
                old_owner = territory.owner_id
                territory.owner_id = faction_id
                if old_owner and old_owner in self.world_state.factions:
                    old_faction = self.world_state.factions[old_owner]
                    if target in old_faction.territories:
                        old_faction.territories.remove(target)
                faction = self.world_state.factions.get(faction_id)
                if faction and target not in faction.territories:
                    faction.territories.append(target)
                # Move attacker into captured territory
                attacker.location = target

        return {
            "success": True,
            "result": result,
            "message": f"与{defender.faction_id}军在{target}交战，结果: {result.result.value}",
        }

    def _execute_develop(self, faction_id: str, params: dict) -> dict:
        territory_id = params.get("target", "")
        faction = self.world_state.factions.get(faction_id)
        if not faction:
            return {"success": False, "result": None, "message": f"势力不存在: {faction_id}"}

        if not territory_id:
            territory_id = faction.capital

        territory = self.world_state.territories.get(territory_id)
        if not territory:
            return {"success": False, "result": None, "message": f"领地不存在: {territory_id}"}

        cost = self.domestic_engine.calculate_development_cost(territory, territory.development + 10)
        if faction.treasury < cost:
            return {
                "success": False,
                "result": None,
                "message": f"资金不足: 需要{cost}金，当前{faction.treasury}金",
            }

        faction.treasury -= cost
        territory.development = min(100, territory.development + 10)

        return {
            "success": True,
            "result": {"cost": cost, "new_development": territory.development},
            "message": f"开发{territory.name}，发展度提升至{territory.development}，花费{cost}金",
        }

    def _execute_tax(self, faction_id: str, params: dict) -> dict:
        faction = self.world_state.factions.get(faction_id)
        if not faction:
            return {"success": False, "result": None, "message": f"势力不存在: {faction_id}"}

        new_rate = params.get("rate", faction.tax_rate)
        # Normalize: if rate > 1 (e.g. 20 meaning 20%), divide by 100
        if new_rate > 1:
            new_rate = new_rate / 100.0
        if not (0.1 <= new_rate <= 0.5):
            return {"success": False, "result": None, "message": "税率应在0.1到0.5之间"}

        faction.tax_rate = new_rate
        morale_impact = self.domestic_engine.calculate_tax_morale_impact(new_rate)

        total_revenue = 0
        for tid in faction.territories:
            territory = self.world_state.territories.get(tid)
            if territory:
                revenue = self.domestic_engine.calculate_tax_revenue(territory, new_rate)
                total_revenue += revenue

        faction.treasury += total_revenue

        return {
            "success": True,
            "result": {"revenue": total_revenue, "new_rate": new_rate, "morale_impact": morale_impact},
            "message": f"调整税率为{new_rate:.0%}，获得税收{total_revenue}金",
        }

    def _execute_diplomacy(self, faction_id: str, params: dict) -> dict:
        target_faction = params.get("target", "")
        action = params.get("action", "ally")

        faction = self.world_state.factions.get(faction_id)
        target = self.world_state.factions.get(target_faction)
        if not faction or not target:
            return {"success": False, "result": None, "message": "势力不存在"}

        if action == "ally":
            if target_faction not in faction.allies:
                faction.allies.append(target_faction)
            if faction_id not in target.allies:
                target.allies.append(faction_id)
            faction.relations[target_faction] = min(100, faction.relations.get(target_faction, 0) + 50)
            target.relations[faction_id] = min(100, target.relations.get(faction_id, 0) + 50)
            return {"success": True, "result": None, "message": f"与{target.name}结盟成功"}

        elif action == "break_ally":
            if target_faction in faction.allies:
                faction.allies.remove(target_faction)
            if faction_id in target.allies:
                target.allies.remove(faction_id)
            faction.relations[target_faction] = max(-100, faction.relations.get(target_faction, 0) - 50)
            target.relations[faction_id] = max(-100, target.relations.get(faction_id, 0) - 50)
            return {"success": True, "result": None, "message": f"与{target.name}解除盟约"}

        else:
            return {"success": False, "result": None, "message": f"未知外交行动: {action}"}

    def _execute_info(self, faction_id: str) -> dict:
        snapshot = self.get_world_snapshot(faction_id)
        return {
            "success": True,
            "result": snapshot,
            "message": f"当前势力: {snapshot.get('faction_name', '')}，回合 {self.world_state.turn_number}",
        }

    def get_world_snapshot(self, faction_id: str) -> dict:
        """Get a summary of the world from a faction's perspective."""
        faction = self.world_state.factions.get(faction_id)
        if not faction:
            return {"error": f"势力不存在: {faction_id}"}

        own_territories = [
            {"id": tid, "name": self.world_state.territories[tid].name}
            for tid in faction.territories
            if tid in self.world_state.territories
        ]

        # Find neighboring enemy territories
        enemy_borders = []
        for tid in faction.territories:
            territory = self.world_state.territories.get(tid)
            if not territory:
                continue
            for neighbor_id in territory.neighbors:
                neighbor = self.world_state.territories.get(neighbor_id)
                if neighbor and neighbor.owner_id and neighbor.owner_id != faction_id:
                    nf = self.world_state.factions.get(neighbor.owner_id)
                    is_enemy = (
                        neighbor.owner_id in faction.enemies
                        or faction.relations.get(neighbor.owner_id, 0) < 0
                    )
                    if is_enemy:
                        enemy_borders.append({
                            "territory_id": neighbor_id,
                            "territory_name": neighbor.name,
                            "owner_id": neighbor.owner_id,
                            "owner_name": nf.name if nf else neighbor.owner_id,
                        })

        # Total troops
        total_troops = sum(
            army.total_troops
            for army in self.world_state.armies.values()
            if army.faction_id == faction_id
        )

        return {
            "faction_id": faction_id,
            "faction_name": faction.name,
            "year": self.world_state.year,
            "season": self.world_state.season.cn,
            "turn": self.world_state.turn_number,
            "capital": faction.capital,
            "territories": own_territories,
            "territory_count": len(faction.territories),
            "total_troops": total_troops,
            "prestige": faction.prestige,
            "food": faction.food,
            "treasury": faction.treasury,
            "tax_rate": faction.tax_rate,
            "allies": faction.allies,
            "enemies": faction.enemies,
            "enemy_borders": enemy_borders,
            "army_count": sum(1 for a in self.world_state.armies.values() if a.faction_id == faction_id),
        }

    # ─── personality mapping ──────────────────────────────

    _PERSONALITY_MAP: dict[str, str] = {
        "cao": "caocao",
        "shu": "liubei",
        "wu": "sunquan",
    }

    # ─── NPC faction advancement ──────────────────────────

    def advance_npc_factions(self) -> list[dict]:
        """Let NPC factions take their turns via DecisionEngine.

        Each NPC collects taxes, then the DecisionEngine generates
        strategic commands based on personality and world state.
        """
        npc_actions = []
        player_fid = self.world_state.player_faction_id

        for fid, faction in self.world_state.factions.items():
            if fid == player_fid:
                continue
            if not faction.is_active:
                continue

            actions: list[str] = []

            # 1. Collect taxes
            try:
                total_revenue = 0
                for tid in faction.territories:
                    territory = self.world_state.territories.get(tid)
                    if territory:
                        revenue = self.domestic_engine.calculate_tax_revenue(
                            territory, faction.tax_rate
                        )
                        total_revenue += revenue
                if total_revenue > 0:
                    faction.treasury += total_revenue
                    actions.append(f"征税获得{total_revenue}金")
            except Exception:
                pass

            # 2. Generate strategic commands via DecisionEngine
            try:
                commands = self.decision_engine.generate_commands(
                    fid, self.world_state, self.map_engine
                )
            except Exception:
                commands = []

            # 3. Execute commands with normalized params
            for cmd in commands:
                try:
                    normalized = self._normalize_params(cmd)
                    result = self.execute_command(normalized)
                    if result["success"]:
                        actions.append(result["message"])
                    else:
                        actions.append(f"失败: {result['message']}")
                except Exception as exc:
                    actions.append(f"命令异常: {exc}")

            profile_name = self._PERSONALITY_MAP.get(fid, "default")
            npc_actions.append({
                "faction_id": fid,
                "faction_name": faction.name,
                "actions": actions,
                "personality": profile_name,
            })

        # Sync faction strength_actual with actual army totals
        for fid, faction in self.world_state.factions.items():
            faction.strength_actual = sum(
                a.total_troops for a in self.world_state.armies.values()
                if a.faction_id == fid
            )

        return npc_actions

    def _normalize_params(self, cmd: Command) -> Command:
        """Normalize DecisionEngine param keys to state_bridge expectations."""
        params = dict(cmd.params)

        # attack: "target_territory" → "target"
        if cmd.type == "attack" and "target_territory" in params:
            params["target"] = params.pop("target_territory")
        # move: "destination" → "target"
        elif cmd.type == "move" and "destination" in params:
            params["target"] = params.pop("destination")
        # develop: "territory" → "target"
        elif cmd.type == "develop" and "territory" in params:
            params["target"] = params.pop("territory")

        return Command(type=cmd.type, params=params, faction_id=cmd.faction_id)

    def get_territory_map(self) -> dict[str, list[str]]:
        """Return adjacency map for map rendering."""
        return {
            tid: list(t.neighbors) for tid, t in self.world_state.territories.items()
        }

    # ─── helpers ─────────────────────────────────────────

    def _get_or_create_army(self, faction_id: str, location: str) -> Army:
        for army in self.world_state.armies.values():
            if army.faction_id == faction_id and army.location == location:
                return army
        army_id = f"army_{faction_id}_{uuid.uuid4().hex[:6]}"
        army = Army(
            id=army_id,
            faction_id=faction_id,
            location=location,
            units={},
            morale=80,
            training=1.0,
            supply=30,
        )
        self.world_state.armies[army_id] = army
        return army

    def _find_army(self, faction_id: str, army_id: str = "") -> Army | None:
        if army_id and army_id in self.world_state.armies:
            return self.world_state.armies[army_id]
        for army in self.world_state.armies.values():
            if army.faction_id == faction_id:
                return army
        return None

    def _find_best_army_for_target(self, faction_id: str, target: str) -> Army | None:
        """Find best army for attacking/moving to target.
        
        Prefers: at target > adjacent to target > any army.
        """
        best = None
        best_score = -1
        
        for army in self.world_state.armies.values():
            if army.faction_id != faction_id:
                continue
            if army.total_troops <= 0:
                continue
            
            # Score: 2 for at target, 1 for adjacent, 0 for other
            if army.location == target:
                score = 2
            elif self.map_engine.are_adjacent(army.location, target):
                score = 1
            else:
                score = 0
            
            # Tiebreak: bigger army wins
            score += army.total_troops / 100000
            
            if score > best_score:
                best_score = score
                best = army
        
        return best or self._find_army(faction_id)

    def _find_defender(self, territory_id: str) -> Army | None:
        territory = self.world_state.territories.get(territory_id)
        if not territory:
            return None
        owner_id = territory.owner_id
        for army in self.world_state.armies.values():
            if army.location == territory_id and army.faction_id == owner_id:
                return army
        return None

    def _create_garrison(self, territory_id: str) -> Army:
        territory = self.world_state.territories.get(territory_id)
        owner_id = territory.owner_id if territory else ""

        army_id = f"garrison_{territory_id}"
        army = Army(
            id=army_id,
            faction_id=owner_id,
            location=territory_id,
            units={UnitType.INFANTRY: territory.garrison if territory else 1000},
            morale=50,
            training=0.8,
            supply=15,
        )
        self.world_state.armies[army_id] = army
        return army
