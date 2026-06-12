"""Policy Validator — validates PolicyCommands against world state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from histrategy.policy.policy_types import PolicyCommand, validate_policy_params

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


def _normalize_faction_id(raw: str, ws) -> str:
    """Normalize faction identifiers: '刘表(liubiao)' → 'liubiao', '曹操' → 'cao'."""
    if not raw:
        return raw
    # Strip annotation: "刘表(liubiao)" → extract "liubiao"
    if '(' in raw and raw.endswith(')'):
        inner = raw[raw.rindex('(') + 1:-1]
        if inner in ws.factions:
            return inner
        base = raw[:raw.index('(')]
        for fid, f in ws.factions.items():
            if getattr(f, 'name', '') == base:
                return fid
    if raw in ws.factions:
        return raw
    for fid, f in ws.factions.items():
        if getattr(f, 'name', '') == raw:
            return fid
    return raw


class PolicyValidator:
    """Checks that policy commands are executable given current world state."""

    def validate(
        self, commands: list[PolicyCommand], world_state: WorldState
    ) -> list[PolicyCommand]:
        """Validate and return all commands (invalid ones are tagged with notes)."""
        for cmd in commands:
            errors = self._check(cmd, world_state)
            if errors:
                cmd.notes = cmd.notes + (" [VALIDATION: " + "; ".join(errors) + "]")
        return commands

    def _check(self, cmd: PolicyCommand, ws: WorldState) -> list[str]:
        errors = []
        errors.extend(validate_policy_params(cmd.type, cmd.params))

        if cmd.type in ("declare_war", "diplomacy", "sue_peace", "trade", "intelligence"):
            target = cmd.params.get("target", "")
            if target:
                normalized = _normalize_faction_id(target, ws)
                cmd.params["target"] = normalized  # Fix in-place
                if normalized not in ws.factions:
                    errors.append(f"Target faction '{target}' does not exist")
                elif cmd.type == "declare_war":
                    if not getattr(ws.factions.get(normalized), "is_active", True):
                        errors.append(f"Faction '{normalized}' already defeated")

        elif cmd.type == "appoint":
            char_id = cmd.params.get("character", "")
            if char_id and char_id not in ws.characters:
                errors.append(f"Character '{char_id}' does not exist")

        elif cmd.type in ("relocate_capital", "develop"):
            territory = cmd.params.get("to") or cmd.params.get("territory", "")
            if territory and territory not in ws.territories:
                errors.append(f"Territory '{territory}' does not exist")

        elif cmd.type == "tax_rate":
            rate = cmd.params.get("rate", 0)
            if not (0.0 <= rate <= 1.0):
                errors.append(f"Tax rate must be 0.0-1.0, got {rate}")

        return errors
