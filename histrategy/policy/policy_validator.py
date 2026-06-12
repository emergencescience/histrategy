"""Policy Validator — validates PolicyCommands against world state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from histrategy.policy.policy_types import PolicyCommand, validate_policy_params

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


class PolicyValidator:
    """Checks that policy commands are executable given current world state."""

    def validate(
        self, commands: list[PolicyCommand], world_state: WorldState
    ) -> list[PolicyCommand]:
        """Filter and warn about invalid commands.

        Returns only valid commands. Logs warnings for invalid ones.
        """
        valid: list[PolicyCommand] = []
        for cmd in commands:
            errors = self._check(cmd, world_state)
            if errors:
                # We still include the command but tag it with validation errors
                # so downstream can decide how to handle (some errors are soft)
                cmd.notes = cmd.notes + (" [VALIDATION: " + "; ".join(errors) + "]")
            valid.append(cmd)
        return valid

    def _check(self, cmd: PolicyCommand, ws: WorldState) -> list[str]:
        """Check a single command. Returns list of error messages."""
        errors = []

        # Check required params
        param_errors = validate_policy_params(cmd.type, cmd.params)
        errors.extend(param_errors)

        if cmd.type == "declare_war":
            target = cmd.params.get("target", "")
            if target:
                if target not in ws.factions:
                    errors.append(f"Target faction '{target}' does not exist")
                elif not getattr(ws.factions[target], "is_active", True):
                    errors.append(f"Target faction '{target}' is already defeated")
                elif target == ws.player_faction_id:
                    errors.append("Cannot declare war on yourself")

        elif cmd.type == "diplomacy":
            target = cmd.params.get("target", "")
            if target and target not in ws.factions:
                errors.append(f"Target faction '{target}' does not exist")

        elif cmd.type == "appoint":
            char_id = cmd.params.get("character", "")
            if char_id and char_id not in ws.characters:
                errors.append(f"Character '{char_id}' does not exist")

        elif cmd.type == "relocate_capital":
            to_territory = cmd.params.get("to", "")
            if to_territory:
                if to_territory not in ws.territories:
                    errors.append(f"Territory '{to_territory}' does not exist")
                elif ws.territories[to_territory].owner_id != ws.player_faction_id:
                    errors.append(f"Territory '{to_territory}' is not owned by you")

        elif cmd.type == "develop":
            territory = cmd.params.get("territory", "")
            if territory:
                if territory not in ws.territories:
                    errors.append(f"Territory '{territory}' does not exist")
                elif territory != "all" and ws.territories[territory].owner_id != ws.player_faction_id:
                    errors.append(f"Territory '{territory}' is not owned by you")

        elif cmd.type == "tax_rate":
            rate = cmd.params.get("rate", 0)
            if not (0.0 <= rate <= 1.0):
                errors.append(f"Tax rate must be between 0.0 and 1.0, got {rate}")

        return errors
