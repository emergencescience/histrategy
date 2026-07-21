"""
Guardrail Validator — hard/soft constraint enforcement for v3 LLM deltas.

Validates structured output from WorldSimulator against physical constraints.
Hard violations → reject delta, use deterministic baseline.
Soft violations → accept but log warning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

logger = logging.getLogger(__name__)


class GuardrailViolation(Exception):
    """Raised when a hard constraint is violated."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"[{field}] {message}")


class GuardrailWarning:
    """Soft constraint violation — recorded but not blocking."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message


class GuardrailValidator:
    """Validates LLM-generated deltas against physical and game constraints."""

    def validate(
        self,
        delta: dict,
        world_state: WorldState,
        baseline: object,
    ) -> dict:
        """Validate an LLM delta against all constraints.

        Returns a dict with:
            "accepted": bool  — True if hard constraints pass
            "violations": list[GuardrailViolation]
            "warnings": list[GuardrailWarning]
            "sanitized_delta": dict  — delta with invalid entries removed
        """
        violations: list[GuardrailViolation] = []
        warnings: list[GuardrailWarning] = []
        sanitized = {
            "battle_overrides": [],
            "battle_results": [],
            "npc_faction_actions": [],
            "morale_events": [],
            "political_events": [],
            "narrative_seeds": delta.get("narrative_seeds", []),
        }

        # ── Validate battle overrides (legacy army-based schema) ──
        if "battle_overrides" in delta:
            for bo in delta["battle_overrides"]:
                try:
                    self._validate_battle_override(bo, world_state, baseline)
                    sanitized["battle_overrides"].append(bo)
                except GuardrailViolation as e:
                    violations.append(e)
                    logger.warning("Battle override rejected: %s", e)

        # ── Validate battle results (MacroPolicyEngine schema) ──
        # Soft-check adjacency; StateApplier is the hard gate.
        for br in delta.get("battle_results", []):
            if not isinstance(br, dict):
                continue
            loc = br.get("location", "")
            known_loc = loc and (
                loc in world_state.territories
                or any(
                    getattr(t, "name", "") == loc
                    for t in world_state.territories.values()
                )
            )
            if known_loc:
                # ── Soft check: warn if LLM tries to capture non-adjacent territory ──
                wants_capture = br.get("territory_captured") or br.get("result") in (
                    "attack_win",
                    "rout",
                )
                if wants_capture:
                    atk = br.get("attacker", "")
                    if atk and loc in world_state.territories:
                        target = world_state.territories[loc]
                        atk_owns = {
                            tid
                            for tid, t in world_state.territories.items()
                            if getattr(t, "owner_id", "") == atk
                        }
                        target_neighbors = set(getattr(target, "neighbors", []))
                        if (
                            not (target_neighbors & atk_owns)
                            and getattr(target, "owner_id", "") != atk
                        ):
                            warnings.append(
                                GuardrailWarning(
                                    "battle_results.territory_captured",
                                    (
                                        f"LLM wants {atk} to capture {loc} but "
                                        "attacker does not border it. "
                                        "StateApplier will block."
                                    ),
                                )
                            )
                sanitized["battle_results"].append(br)
            else:
                warnings.append(
                    GuardrailWarning(
                        "battle_results.location",
                        f"Unknown territory: {loc}",
                    )
                )

        # ── Validate NPC faction actions: cap conscription, check faction ──
        for nfa in delta.get("npc_faction_actions", []):
            if not isinstance(nfa, dict):
                continue
            fac = nfa.get("faction", "")
            faction_known = fac in world_state.factions or any(
                getattr(f, "name", "") == fac
                for f in world_state.factions.values()
            )
            if faction_known:
                # ── Hard cap: NPC conscript <= 8% of total faction population ──
                if nfa.get("action_type") == "conscript":
                    amount = int(
                        (nfa.get("params", {}) or {}).get("amount", 5000) or 5000
                    )
                    faction_obj = world_state.factions.get(fac)
                    total_pop = (
                        sum(
                            getattr(
                                world_state.territories.get(tid, None),
                                "population",
                                0,
                            )
                            for tid in getattr(faction_obj, "territories", [])
                        )
                        if faction_obj
                        else 0
                    )
                    max_allowed = max(500, int(total_pop * 0.08))
                    if amount > max_allowed:
                        warnings.append(
                            GuardrailWarning(
                                f"npc_faction_action.{fac}.conscript",
                                (
                                    f"Conscript {amount} exceeds 8% pop cap "
                                    f"({max_allowed}). Clamped to {max_allowed}."
                                ),
                            )
                        )
                        nfa.setdefault("params", {})["amount"] = max_allowed
                sanitized["npc_faction_actions"].append(nfa)
            else:
                warnings.append(
                    GuardrailWarning(
                        "npc_faction_action.faction",
                        f"Unknown faction: {fac}",
                    )
                )

        # ── Validate morale events ──
        if "morale_events" in delta:
            for me in delta["morale_events"]:
                try:
                    self._validate_morale_event(me, world_state)
                    sanitized["morale_events"].append(me)
                except GuardrailViolation as e:
                    violations.append(e)
                else:
                    # Soft constraint: single-turn change ≤ 15
                    change = abs(me.get("change", 0))
                    if change > 15:
                        warnings.append(
                            GuardrailWarning(
                                f"morale_event.{me.get('faction', '?')}",
                                f"Single-turn morale change {change} exceeds +-15 cap",
                            )
                        )

        # ── Validate political events (pass through with basic checks) ──
        if "political_events" in delta:
            for pe in delta["political_events"]:
                faction = pe.get("faction", "")
                if faction and faction in world_state.factions:
                    sanitized["political_events"].append(pe)
                else:
                    warnings.append(
                        GuardrailWarning(
                            "political_event",
                            f"Unknown faction: {faction}",
                        )
                    )

        accepted = len(violations) == 0

        return {
            "accepted": accepted,
            "violations": violations,
            "warnings": warnings,
            "sanitized_delta": sanitized,
        }

    # ── Hard Constraint Validators ──────────────────────────

    def _validate_battle_override(self, bo: dict, ws: WorldState, baseline) -> None:
        """Hard constraints for battle overrides."""
        location = bo.get("location", "")

        # Constraint: territory must exist
        if location not in ws.territories:
            raise GuardrailViolation("location", f"Unknown territory: {location}")

        casualties = bo.get("casualties", {})
        atk_loss = casualties.get("attacker", 0)
        def_loss = casualties.get("defender", 0)

        # Constraint: casualties must be non-negative integers
        if not isinstance(atk_loss, (int, float)) or atk_loss < 0:
            raise GuardrailViolation(
                "casualties.attacker", f"Negative casualties: {atk_loss}"
            )
        if not isinstance(def_loss, (int, float)) or def_loss < 0:
            raise GuardrailViolation(
                "casualties.defender", f"Negative casualties: {def_loss}"
            )

        # Constraint: captured/escaped characters must be valid
        for char_id in bo.get("captured_characters", []):
            if char_id not in ws.characters:
                raise GuardrailViolation(
                    "captured_characters", f"Unknown character: {char_id}"
                )
        for char_id in bo.get("escaped_characters", []):
            if char_id not in ws.characters:
                raise GuardrailViolation(
                    "escaped_characters", f"Unknown character: {char_id}"
                )

        # Constraint: cannot capture AND have the same character escape
        captured = set(bo.get("captured_characters", []))
        escaped = set(bo.get("escaped_characters", []))
        overlap = captured & escaped
        if overlap:
            raise GuardrailViolation(
                "characters", f"Characters both captured and escaped: {overlap}"
            )

        # Find the baseline battle for deviation check
        if hasattr(baseline, "battles"):
            for b in baseline.battles:
                if getattr(b, "location", "") == location:
                    base_atk = (
                        sum(b.attacker_casualties.values())
                        if hasattr(b, "attacker_casualties")
                        else 0
                    )
                    base_def = (
                        sum(b.defender_casualties.values())
                        if hasattr(b, "defender_casualties")
                        else 0
                    )

                    # Non-combat outcomes may have zero casualties
                    llm_result = bo.get("llm_result", "")
                    is_non_combat = llm_result in (
                        "defender_surrendered",
                        "defender_retreated",
                        "attacker_repelled",
                        "stalemate",
                    )

                    if not is_non_combat:
                        if base_atk > 0:
                            ratio = atk_loss / base_atk
                            if ratio > 2.0 or ratio < 0.1:
                                raise GuardrailViolation(
                                    "casualties.attacker",
                                    (
                                        f"Attacker casualties {atk_loss} deviate too far"
                                        f" from baseline {base_atk} (ratio={ratio:.2f})"
                                    ),
                                )
                        if base_def > 0:
                            ratio = def_loss / base_def
                            if ratio > 2.0 or ratio < 0.1:
                                raise GuardrailViolation(
                                    "casualties.defender",
                                    (
                                        f"Defender casualties {def_loss} deviate too far"
                                        f" from baseline {base_def} (ratio={ratio:.2f})"
                                    ),
                                )
                    break

    def _validate_morale_event(self, me: dict, ws: WorldState) -> None:
        """Hard constraints for morale events."""
        faction_id = me.get("faction", "")
        if faction_id not in ws.factions:
            raise GuardrailViolation(
                "faction", f"Unknown faction: {faction_id}"
            )

        faction = ws.factions[faction_id]
        current_morale = getattr(faction, "morale_actual", 50)
        change = me.get("change", 0)

        # Constraint: morale must stay in [0, 100]
        new_morale = current_morale + change
        if new_morale < 0:
            raise GuardrailViolation(
                "change",
                f"Morale would go below 0: {current_morale} + {change} = {new_morale}",
            )
        if new_morale > 100:
            raise GuardrailViolation(
                "change",
                f"Morale would exceed 100: {current_morale} + {change} = {new_morale}",
            )

        # Constraint: territory must exist if specified
        territory = me.get("territory", "")
        if territory and territory not in ws.territories:
            raise GuardrailViolation(
                "territory", f"Unknown territory: {territory}"
            )
