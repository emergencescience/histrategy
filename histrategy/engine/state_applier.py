"""
State Applier + Turn Memory — safely applies validated LLM deltas to WorldState.

StateApplier: Mutates WorldState based on validated delta, with all
hard constraints already checked by GuardrailValidator.

TurnMemory: Append-only JSONL log of turn summaries + persistent effects.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

logger = logging.getLogger(__name__)


class StateApplier:
    """Safely applies validated LLM delta to WorldState."""

    @staticmethod
    def apply(
        delta: dict,
        world_state: WorldState,
    ) -> dict:
        """Apply a validated delta to the world state.

        Args:
            delta: Sanitized delta from GuardrailValidator
            world_state: Mutable WorldState (modified in place)

        Returns:
            Summary dict of applied changes for logging
        """
        summary = {
            "battles_modified": 0,
            "morale_changes": 0,
            "political_events": 0,
            "npc_actions": 0,
            "butterfly_effects": 0,
        }

        # ── Apply battle overrides ──
        for bo in delta.get("battle_overrides", []):
            _apply_battle_override(bo, world_state)
            summary["battles_modified"] += 1

        # ── Apply morale events ──
        for me in delta.get("morale_events", []):
            _apply_morale_event(me, world_state)
            summary["morale_changes"] += 1

        # ── Political events (log only, no state mutation unless specified) ──
        for pe in delta.get("political_events", []):
            logger.info(
                "Political event: %s — %s",
                pe.get("faction", "?"),
                pe.get("description", ""),
            )
            summary["political_events"] += 1

        # ── NPC actions (delegated to TurnController, not applied here) ──
        summary["npc_actions"] = len(delta.get("npc_actions", []))
        summary["butterfly_effects"] = len(delta.get("butterfly_effects", []))

        return summary


def _apply_battle_override(bo: dict, ws) -> None:
    """Apply a single battle override."""
    location = bo.get("location", "")
    casualties = bo.get("casualties", {})

    # Apply casualties to armies at this location
    # Auto-detect attacker/defender: attacker is the faction NOT owning the territory
    territory = ws.territories.get(location)
    defender_id = bo.get("defender_id", territory.owner_id if territory else "")
    attacker_id = bo.get("attacker_id", "")

    for army in ws.armies.values():
        if army.location != location:
            continue
        if army.total_troops <= 0:
            continue

        # Determine if this army is attacker or defender
        is_defender = army.faction_id == defender_id
        is_attacker = army.faction_id != defender_id

        if is_attacker and (not attacker_id or army.faction_id == attacker_id):
            loss = casualties.get("attacker", 0)
            _reduce_army(army, loss)
        elif is_defender:
            loss = casualties.get("defender", 0)
            _reduce_army(army, loss)

    # Handle territory capture
    if bo.get("territory_captured") and territory:
        old_owner = territory.owner_id
        # Find attacker ID from context
        for army in ws.armies.values():
            if army.location == location and army.total_troops > 0:
                territory.owner_id = army.faction_id
                # Update faction territories
                if old_owner and old_owner in ws.factions and location in ws.factions[old_owner].territories:
                    ws.factions[old_owner].territories.remove(location)
                if territory.owner_id in ws.factions and location not in ws.factions[territory.owner_id].territories:
                    ws.factions[territory.owner_id].territories.append(location)
                break

    # Handle captured characters
    for char_id in bo.get("captured_characters", []):
        char = ws.characters.get(char_id)
        if char and char.alive:
            char.faction_id = ""  # Captured — removed from faction
            char.is_commanding = False
            char.is_governor = False


def _apply_morale_event(me: dict, ws) -> None:
    """Apply a single morale event."""
    faction_id = me.get("faction", "")
    faction = ws.factions.get(faction_id)
    if not faction:
        return
    change = me.get("change", 0)
    current = getattr(faction, "morale_actual", 50)
    faction.morale_actual = max(0, min(100, current + change))


def _reduce_army(army, loss: int) -> None:
    """Reduce army troop count proportionally across unit types."""
    if loss <= 0 or army.total_troops <= 0:
        return
    ratio = min(1.0, loss / army.total_troops)
    for unit_type in list(army.units.keys()):
        army.units[unit_type] = max(0, int(army.units[unit_type] * (1 - ratio)))


# ═══════════════════════════════════════════════════════════════
# Turn Memory
# ═══════════════════════════════════════════════════════════════


class TurnMemory:
    """Append-only turn history and persistent effects tracker."""

    def __init__(self, data_dir: str | Path = ""):
        self.data_dir = Path(data_dir) if data_dir else Path.home() / ".histrategy"
        self.memory_dir = self.data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def record_turn(
        self,
        room_id: str,
        turn_number: int,
        year: int,
        season: str,
        player_decision: str,
        outcome_summary: str,
        key_events: list[str],
        state_snapshot: dict,
        persistent_effects: list[dict],
    ) -> dict:
        """Record a turn to the append-only memory log.

        Returns the recorded entry.
        """
        entry = {
            "turn": turn_number,
            "year": year,
            "season": season,
            "player_decision": player_decision,
            "outcome_summary": outcome_summary,
            "key_events": key_events,
            "state_snapshot": state_snapshot,
            "persistent_effects": persistent_effects,
        }

        # Append to turn log
        log_path = self.memory_dir / room_id / "turn_memory.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Update persistent effects
        if persistent_effects:
            self._update_persistent_effects(room_id, persistent_effects)

        return entry

    def clean_future_turns(self, room_id: str, current_turn: int) -> None:
        """Truncate/remove any memory entries from turn >= current_turn."""
        log_path = self.memory_dir / room_id / "turn_memory.jsonl"
        if not log_path.exists():
            return

        valid_entries = []
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("turn", 0) < current_turn:
                        valid_entries.append(line)
                except json.JSONDecodeError:
                    continue

        # Overwrite file with only valid entries
        with open(log_path, "w", encoding="utf-8") as f:
            f.writelines(valid_entries)

        # Also update persistent effects
        effects_path = self.memory_dir / room_id / "persistent_effects.json"
        if effects_path.exists():
            try:
                with open(effects_path, encoding="utf-8") as f:
                    effects = json.load(f)
                valid_effects = [e for e in effects if e.get("turn", 0) < current_turn]
                with open(effects_path, "w", encoding="utf-8") as f:
                    json.dump(valid_effects, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def get_recent_turns(self, room_id: str, n: int = 5) -> list[dict]:
        """Get the most recent N turns from memory."""
        log_path = self.memory_dir / room_id / "turn_memory.jsonl"
        if not log_path.exists():
            return []

        turns: list[dict] = []
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return turns[-n:]

    def get_persistent_effects(self, room_id: str) -> list[dict]:
        """Get accumulated persistent effects."""
        effects_path = self.memory_dir / room_id / "persistent_effects.json"
        if not effects_path.exists():
            return []
        try:
            with open(effects_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _update_persistent_effects(self, room_id: str, new_effects: list[dict]) -> None:
        """Merge new persistent effects with existing ones."""
        existing = self.get_persistent_effects(room_id)

        # Simple merge: append new effects, deduplicate by note content
        seen_notes = {e.get("note", "") for e in existing}
        for effect in new_effects:
            note = effect.get("note", "")
            if note and note not in seen_notes:
                existing.append(effect)
                seen_notes.add(note)

        effects_path = self.memory_dir / room_id / "persistent_effects.json"
        effects_path.parent.mkdir(parents=True, exist_ok=True)
        with open(effects_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    def build_epoch_summary(self, room_id: str) -> str:
        """Build a compact summary of persistent effects for LLM context."""
        effects = self.get_persistent_effects(room_id)
        if not effects:
            return "无持续性效应。"
        lines = []
        for e in effects:
            note = e.get("note", "")
            if note:
                lines.append(f"- {note}")
        return "\n".join(lines)
