"""
Command Validator — validates parsed commands against physics engine constraints.

Checks each command against the current WorldState:
- recruit: amount ≤ 5% of territory population
- move/attack: destination reachable and exists
- develop: territory belongs to player faction
- tax: rate within 0.1-0.5

Invalid commands are silently dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.map import MapEngine
    from histrategy_engine.world import Command, WorldState


class CommandValidator:
    """Validates Command objects against the physics engine's world state."""

    def __init__(self, map_engine: MapEngine | None = None):
        self.map_engine = map_engine

    def validate(
        self,
        commands: list[Command],
        world_state: WorldState,
    ) -> list[Command]:
        """Validate a list of commands and return only the valid ones.

        Args:
            commands: Raw commands from IntentParser
            world_state: Current game world snapshot

        Returns:
            Filtered list of valid Command objects. Invalid ones are discarded.
        """
        valid: list[Command] = []

        for cmd in commands:
            if self._is_valid(cmd, world_state):
                valid.append(cmd)

        return valid

    def _is_valid(self, cmd: Command, world_state: WorldState) -> bool:
        """Check if a single command is valid against the world state."""
        if not cmd.faction_id:
            return False

        faction = world_state.factions.get(cmd.faction_id)
        if not faction or not faction.is_active:
            return False

        cmd_type = cmd.type

        if cmd_type == "recruit":
            return self._validate_recruit(cmd, world_state)
        elif cmd_type in ("move", "attack"):
            return self._validate_movement(cmd, world_state)
        elif cmd_type == "develop":
            return self._validate_develop(cmd, world_state)
        elif cmd_type == "tax":
            return self._validate_tax(cmd)
        elif cmd_type == "train":
            return self._validate_train(cmd, world_state)
        elif cmd_type == "defend":
            return self._validate_train(cmd, world_state)  # defend uses same territory-ownership check
        elif cmd_type == "negotiate":
            return self._validate_negotiate(cmd, world_state)
        elif cmd_type in ("spy", "trade"):
            return self._validate_target_faction(cmd, world_state)
        elif cmd_type in ("rest", "military_posture"):
            return True  # rest/posture always valid
        elif cmd_type in ("appoint", "dismiss"):
            return self._validate_character_command(cmd, world_state)
        elif cmd_type == "research":
            return True  # research is always valid if faction has resources

        return False

    # ── Specific validators ──────────────────────────────────────

    def _validate_recruit(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate recruitment: amount ≤ 5% of territory population.

        流亡军（0 领地）例外：允许从跟随百姓征召（faction.population 仍在），
        不需要指定/拥有领地。
        """
        faction = world_state.factions.get(cmd.faction_id)
        if not faction:
            return False

        tid = cmd.params.get("territory", "")
        amount = cmd.params.get("amount", 0)
        if amount <= 0:
            return False

        territory = world_state.territories.get(tid) if tid else None

        if faction.territories:
            # 常规势力：必须有领地且领地归本方所有
            if not territory or territory.owner_id != cmd.faction_id:
                return False
            pop_source = territory.population
        else:
            # 流亡军：0 领地，从跟随百姓征召（population 仍在，或按兵力估算）
            pop_source = getattr(faction, "population", 0) or 0
            if pop_source <= 0:
                # 无人口记录时，用现有兵力作为「流民基数」估算（10% 兵力）
                pop_source = max(1, int(getattr(faction, "strength_actual", 0) or 0) * 2)

        max_recruit = max(1, int(pop_source * 0.05))
        if amount > max_recruit:
            return False

        # Check treasury
        unit_type = cmd.params.get("unit_type", "infantry")
        cost_per_unit = {"infantry": 3, "cavalry": 10, "archer": 6, "navy": 8}
        cost = cost_per_unit.get(unit_type, 3) * amount
        if faction.treasury < cost:
            return False

        return True

    def _validate_movement(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate movement/attack: destination exists and is reachable."""
        target = cmd.params.get("destination") or cmd.params.get("target_territory", "")
        if not target:
            return False

        if target not in world_state.territories:
            return False

        # If attacking, target must not be owned by self
        if cmd.type == "attack":
            target_territory = world_state.territories.get(target)
            if target_territory and target_territory.owner_id == cmd.faction_id:
                return False

        # Check reachability via MapEngine
        if self.map_engine:
            faction = world_state.factions.get(cmd.faction_id)
            if faction and faction.territories:
                # Find a path from any owned territory
                reachable = False
                for tid in faction.territories:
                    path = self.map_engine.find_path(tid, target, cmd.faction_id)
                    if path.path and path.total_cost != float("inf"):
                        reachable = True
                        break
                if not reachable:
                    return False

        return True

    def _validate_develop(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate develop: territory must belong to the player faction."""
        tid = cmd.params.get("territory", "")
        if not tid:
            return False

        territory = world_state.territories.get(tid)
        if not territory:
            return False

        if territory.owner_id != cmd.faction_id:
            return False

        # Cannot develop beyond 100
        if territory.development >= 100:
            return False

        # Must have enough treasury
        faction = world_state.factions.get(cmd.faction_id)
        if faction:
            # Simple cost estimate: 500 + population/100
            cost = 500 + territory.population // 100
            if faction.treasury < cost:
                return False

        return True

    def _validate_tax(self, cmd: Command) -> bool:
        """Validate tax: rate must be 0.1-0.5."""
        rate = cmd.params.get("rate")
        if rate is None:
            return False
        return 0.1 <= float(rate) <= 0.5

    def _validate_train(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate training: territory must belong to faction."""
        tid = cmd.params.get("territory", "")
        if not tid:
            return False

        territory = world_state.territories.get(tid)
        if not territory:
            return False
        return territory.owner_id == cmd.faction_id

    def _validate_negotiate(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate negotiation: target faction must exist and be active."""
        target = cmd.params.get("target_faction", "")
        if not target:
            return False
        if target == cmd.faction_id:
            return False

        target_faction = world_state.factions.get(target)
        return not (not target_faction or not target_faction.is_active)

    def _validate_target_faction(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate commands that target a faction (spy, trade)."""
        target = cmd.params.get("target_faction", "")
        if not target:
            return False
        if target == cmd.faction_id:
            return False

        target_faction = world_state.factions.get(target)
        return target_faction is not None and target_faction.is_active

    def _validate_character_command(self, cmd: Command, world_state: WorldState) -> bool:
        """Validate character-related commands (appoint, dismiss)."""
        char_id = cmd.params.get("character", "")
        if not char_id:
            return False

        char = world_state.characters.get(char_id)
        if not char:
            return False
        if not char.alive:
            return False

        if cmd.type == "appoint" or cmd.type == "dismiss":
            # Character must be in the faction
            return char.faction_id == cmd.faction_id

        return False
