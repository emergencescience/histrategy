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


# ═══════════════════════════════════════════════════════════════
# Deterministic combat grounding constants (P4 — fairness).
# The physics engine does not know who is human: territory and troop
# outcomes flow from FORCE RATIOS + morale, not from LLM narrative alone.
# ═══════════════════════════════════════════════════════════════
_DEFENDER_TERRAIN_BONUS = 1.15  # defending your own city is easier
_MIN_ACTIVE_TROOPS = 500  # an active faction never drops below this from one battle
_MAX_BATTLE_LOSS_FRAC = 0.40  # a single battle can cost at most 40% of an army
_MIN_BATTLE_LOSS_FRAC = 0.02  # even a rout costs the winner something
_BASE_ATTRITION = 0.10  # baseline per-battle attrition scalar
_TERRITORY_CAPTURE_POWER_RATIO = 1.10  # attacker effective power must exceed this × defender's
_MORALE_COLLAPSE_THRESHOLD = 20  # defender morale below this → city may fall regardless of force
_MORALE_EVENT_CAP = 15  # single-turn morale change hard cap
_TROOP_ABSORB_FRAC = 0.15  # captured city → victor absorbs this fraction of loser's troops
_MORALE_EQUILIBRIUM = 55  # wartime morale mean-reversion target
_MORALE_REVERT_MAX = 3  # max mean-reversion step per quarter

# ── NPC recruitment constraints (P1/P2: grounded economy) ──
_NPC_CONSCRIPT_MAX_RATE = 0.05  # max 5% of total faction population per quarter
_NPC_CONSCRIPT_CONSECUTIVE_DECAY = 0.02  # each consecutive quarter reduces rate by 2%
_NPC_CONSCRIPT_LABOR_FLOOR_RATIO = 0.25  # below 25% of original pop, conscription blocked
_NPC_CONSCRIPT_MIN_AMOUNT = 100  # minimum conscription even for tiny factions
_NPC_CONSCRIPT_COST_PER_SOLDIER = 3  # gold per soldier (matches military.yaml infantry cost)
_NPC_CONSCRIPT_FOOD_PER_SOLDIER = 0.5  # food per soldier upkeep

# ── Territory adjacency check ──
# Tracks consecutive conscription quarters per faction (module-level, resets per game)
_npc_conscript_streak: dict[str, int] = {}
_initial_faction_population: dict[str, int] = {}  # snapshotted on first call


def _local_faction_id_map(ws) -> dict:
    """name/id → faction pinyin id (inlined to avoid circular import)."""
    m: dict = {}
    for fid, f in ws.factions.items():
        m[fid] = fid
        name = getattr(f, "name", "")
        if name:
            m[name] = fid
    return m


def _local_territory_id_map(ws) -> dict:
    m: dict = {}
    for tid, t in ws.territories.items():
        m[tid] = tid
        name = getattr(t, "name", "")
        if name:
            m[name] = tid
    return m


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class StateApplier:
    """Safely applies validated LLM delta to WorldState."""

    # ── Symmetric multi-faction settlement (QuarterlyResolver path) ──
    @staticmethod
    def apply_macro_delta(
        delta: dict,
        world_state: WorldState,
        baseline: object = None,
    ) -> dict:
        """Apply a MacroPolicyEngine delta to a symmetric-mode WorldState.

        Unlike ``apply()`` (which reads ``battle_overrides`` and mutates
        ``ws.armies``), this reads the ACTUAL MacroPolicyEngine schema
        (``battle_results``, ``morale_events``, ``npc_faction_actions``) and
        mutates scalar ``strength_actual`` / ``faction.territories`` — the
        representation the symmetric engine actually uses.

        Combat is GROUNDED deterministically: casualties and territory
        capture are decided by force-ratio + morale, with the LLM's numbers
        only used as a clamped hint. This prevents "conquest by prose" (P4)
        and guarantees troops/territory change incrementally (P1/P2).
        """
        summary = {
            "battles_settled": 0,
            "territories_captured": 0,
            "troops_lost": 0,
            "morale_changes": 0,
            "npc_actions": 0,
            "factions_defeated": 0,
        }
        ws = world_state
        fmap = _local_faction_id_map(ws)
        tmap = _local_territory_id_map(ws)

        # 1) Morale events (LLM) — hard-capped to ±15 per quarter.
        for me in delta.get("morale_events", []):
            fid = fmap.get(me.get("faction", ""), me.get("faction", ""))
            f = ws.factions.get(fid)
            if not f:
                continue
            ch = _clamp(int(me.get("change", 0) or 0), -_MORALE_EVENT_CAP, _MORALE_EVENT_CAP)
            if ch:
                f.morale_actual = _clamp(getattr(f, "morale_actual", 50) + ch, 0, 100)
                summary["morale_changes"] += 1

        # 2) Battle results → deterministic casualty + territory settlement.
        for br in delta.get("battle_results", []):
            _settle_battle(br, ws, fmap, tmap, summary)

        # 3) NPC autonomous economic/military actions.
        for nfa in delta.get("npc_faction_actions", []):
            _apply_npc_faction_action(nfa, ws, fmap, summary)

        # 4) Morale mean-reversion — de-pin extremes from 0/100 (P3).
        for f in ws.factions.values():
            m = getattr(f, "morale_actual", 50)
            if abs(m - _MORALE_EQUILIBRIUM) > 25:
                step = _clamp(round((_MORALE_EQUILIBRIUM - m) * 0.12), -_MORALE_REVERT_MAX, _MORALE_REVERT_MAX)
                f.morale_actual = _clamp(m + step, 0, 100)

        # 5) Auto-surrender: broken NPCs (morale < 15, ≤ 1 territory) fold.
        for fid, f in list(ws.factions.items()):
            if fid == getattr(ws, "player_faction_id", None):
                continue
            if getattr(f, "is_active", True) and getattr(f, "morale_actual", 50) < 15 and len(f.territories) <= 1:
                _absorb_defeated_faction(fid, ws, summary)

        return summary

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
        summary["npc_actions"] = len(delta.get("npc_faction_actions", []))
        summary["butterfly_effects"] = 0  # butterfly_effects removed from schema

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


# ═══════════════════════════════════════════════════════════════
# Deterministic combat settlement (symmetric multi-faction engine)
# ═══════════════════════════════════════════════════════════════


def _settle_battle(br: dict, ws, fmap: dict, tmap: dict, summary: dict) -> None:
    """Settle one battle_results entry against scalar faction strength.

    Force-ratio grounded: the LLM narrates, but Python decides how many
    troops die and whether a city actually changes hands.
    """
    loc = tmap.get(br.get("location", ""), br.get("location", ""))
    territory = ws.territories.get(loc)

    atk = fmap.get(br.get("attacker", ""), br.get("attacker", ""))
    dfd_raw = br.get("defender", "") or br.get("defender_faction", "")
    dfd = fmap.get(dfd_raw, dfd_raw)
    if not dfd and territory:
        dfd = territory.owner_id

    af = ws.factions.get(atk)
    df = ws.factions.get(dfd)
    if not af or not df or atk == dfd:
        return
    if not getattr(af, "is_active", True) or not getattr(df, "is_active", True):
        return

    a_tr = max(0, int(getattr(af, "strength_actual", 0)))
    d_tr = max(0, int(getattr(df, "strength_actual", 0)))
    if a_tr <= 0 or d_tr <= 0:
        return

    a_mor = getattr(af, "morale_actual", 50)
    d_mor = getattr(df, "morale_actual", 50)

    # ── Effective combat power (troops weighted by morale + terrain) ──
    a_pow = a_tr * (0.6 + a_mor / 250.0)
    terrain = _DEFENDER_TERRAIN_BONUS if (territory and territory.owner_id == dfd) else 1.0
    d_pow = d_tr * (0.6 + d_mor / 250.0) * terrain
    ratio = a_pow / max(d_pow, 1.0)

    # ── Deterministic casualties: the weaker side bleeds more ──
    # Attacker loss fraction shrinks as its ratio grows; defender's grows.
    atk_loss_frac = _clamp(_BASE_ATTRITION / max(ratio, 0.25), _MIN_BATTLE_LOSS_FRAC, _MAX_BATTLE_LOSS_FRAC)
    def_loss_frac = _clamp(_BASE_ATTRITION * max(ratio, 0.25), _MIN_BATTLE_LOSS_FRAC, _MAX_BATTLE_LOSS_FRAC)
    det_atk_loss = int(a_tr * atk_loss_frac)
    det_def_loss = int(d_tr * def_loss_frac)

    # ── Blend with LLM hint, clamped to [0.5×, 1.5×] of deterministic ──
    cas = br.get("casualties", {}) or {}
    llm_atk = _sum_casualties(cas.get("attacker"))
    llm_def = _sum_casualties(cas.get("defender"))
    atk_loss = _blend_casualty(det_atk_loss, llm_atk)
    def_loss = _blend_casualty(det_def_loss, llm_def)

    # ── Apply casualties (floor active factions at _MIN_ACTIVE_TROOPS) ──
    af.strength_actual = max(_MIN_ACTIVE_TROOPS, a_tr - atk_loss)
    df.strength_actual = max(_MIN_ACTIVE_TROOPS, d_tr - def_loss)
    summary["troops_lost"] += (a_tr - af.strength_actual) + (d_tr - df.strength_actual)
    summary["battles_settled"] += 1

    # ── Territory capture: gated by force ratio OR defender morale collapse ──
    # AND adjacency: attacker must border the target territory (P1 — no rear-line sniping)
    llm_wants_capture = bool(br.get("territory_captured")) or br.get("result") in ("attack_win", "rout")
    force_permits = a_pow > d_pow * _TERRITORY_CAPTURE_POWER_RATIO
    morale_collapse = d_mor < _MORALE_COLLAPSE_THRESHOLD
    adjacency_ok = _attacker_borders_territory(atk, loc, ws)
    if territory and llm_wants_capture and (force_permits or morale_collapse):
        if not adjacency_ok:
            logger.warning(
                "Territory capture BLOCKED: %s does not border %s (%s)",
                atk, loc, getattr(territory, "name", loc),
            )
        else:
            _transfer_territory(loc, atk, dfd, ws, summary)
            # capture morale swing
            af.morale_actual = _clamp(getattr(af, "morale_actual", 50) + 5, 0, 100)
            df.morale_actual = _clamp(getattr(df, "morale_actual", 50) - 8, 0, 100)
            # If the defender lost its last city, it is finished.
            if not df.territories:
                df.is_active = False
                summary["factions_defeated"] += 1


def _sum_casualties(v) -> int:
    """battle_results casualties may be a scalar or {unit_type: n} dict."""
    if isinstance(v, dict):
        return int(sum(x for x in v.values() if isinstance(x, (int, float))))
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _blend_casualty(deterministic: int, llm_hint: int) -> int:
    """Average deterministic + LLM hint, clamped to [0.5×, 1.5×] deterministic."""
    if llm_hint <= 0:
        return deterministic
    lo = int(deterministic * 0.5)
    hi = int(deterministic * 1.5)
    blended = (deterministic + _clamp(llm_hint, lo, hi)) // 2
    return max(0, blended)


def _attacker_borders_territory(attacker_id: str, target_id: str, ws) -> bool:
    """Check whether the attacker faction borders the target territory.

    A faction "borders" a territory if it owns at least one territory that
    is a neighbor of the target territory. Uses MapEngine adjacency when
    available; falls back to territory neighbor lists.

    Naval adjacency: if both attacker-owned territory and target territory
    have ports (has_coast=True), they are considered adjacent across the sea.
    This enables cross-sea invasions (e.g. Italy → Greece, Egypt → Greece).
    """
    target = ws.territories.get(target_id)
    if not target:
        return False
    # Get all territories owned by the attacker
    atk_territories = {
        tid for tid, t in ws.territories.items()
        if getattr(t, "owner_id", "") == attacker_id
    }
    # Check if any of them are neighbors of the target
    target_neighbors = set(getattr(target, "neighbors", []))
    if target_neighbors & atk_territories:
        return True
    # Also accept if attacker already owns the target (shouldn't happen normally)
    if getattr(target, "owner_id", "") == attacker_id:
        return True
    # ── Naval adjacency: port-to-port sea crossing ──
    target_has_port = getattr(target, "has_coast", False)
    if target_has_port:
        for tid in atk_territories:
            t = ws.territories.get(tid)
            if t and getattr(t, "has_coast", False):
                return True
    return False


def _transfer_territory(loc: str, new_owner: str, old_owner: str, ws, summary: dict) -> None:
    """Move a territory + absorb a slice of the loser's troops."""
    territory = ws.territories.get(loc)
    if not territory or new_owner not in ws.factions:
        return
    old = old_owner if old_owner in ws.factions else territory.owner_id
    territory.owner_id = new_owner
    if old in ws.factions and loc in ws.factions[old].territories:
        ws.factions[old].territories.remove(loc)
    if loc not in ws.factions[new_owner].territories:
        ws.factions[new_owner].territories.append(loc)
    summary["territories_captured"] += 1

    # Absorb a fraction of the loser's per-city troops into the victor.
    if old and old in ws.factions:
        old_faction = ws.factions[old]
        per_city = old_faction.strength_actual / max(len(old_faction.territories) + 1, 1)
        absorbed = int(per_city * _TROOP_ABSORB_FRAC)
        if absorbed > 0:
            old_faction.strength_actual = max(_MIN_ACTIVE_TROOPS, old_faction.strength_actual - absorbed)
            ws.factions[new_owner].strength_actual = getattr(ws.factions[new_owner], "strength_actual", 0) + absorbed


def _absorb_defeated_faction(fid: str, ws, summary: dict) -> None:
    """Mark a broken faction inactive and hand its last land to a neighbor."""
    f = ws.factions.get(fid)
    if not f:
        return
    f.is_active = False
    summary["factions_defeated"] += 1
    for last_t in list(f.territories):
        territory = ws.territories.get(last_t)
        neighbors = getattr(territory, "neighbors", []) if territory else []
        heir = None
        for nid in neighbors:
            nt = ws.territories.get(nid)
            if nt and nt.owner_id in ws.factions and getattr(ws.factions[nt.owner_id], "is_active", True):
                heir = nt.owner_id
                break
        if heir:
            _transfer_territory(last_t, heir, fid, ws, summary)


def _apply_npc_faction_action(nfa: dict, ws, fmap: dict, summary: dict) -> None:
    """Apply an NPC faction's autonomous economic/military action."""
    fid = fmap.get(nfa.get("faction", ""), nfa.get("faction", ""))
    faction = ws.factions.get(fid)
    if not faction or fid == getattr(ws, "player_faction_id", None):
        return
    if not getattr(faction, "is_active", True):
        return
    action_type = nfa.get("action_type", "none")
    params = nfa.get("params", {}) or {}
    summary["npc_actions"] += 1

    if action_type == "conscript":
        amount = int(params.get("amount", 5000) or 5000)
        # ── Grounded recruitment: cap by population, treasury, food, and streak ──
        # Use faction.population as primary source (territories may have stale/zero pop).
        # Fall back to territory sum if faction.population is not set.
        faction_pop = getattr(faction, "population", 0)
        territory_pop = sum(
            getattr(ws.territories.get(tid, None), "population", 0)
            for tid in getattr(faction, "territories", [])
        )
        total_pop = faction_pop if faction_pop > 0 else territory_pop
        # Snapshot initial population on first call (for labor floor check)
        if fid not in _initial_faction_population:
            _initial_faction_population[fid] = max(total_pop, 1)
        initial_pop = _initial_faction_population[fid]

        # Labor floor: below 25% of original pop, no conscription possible.
        # EXCEPTION: if faction has lost all territories (total_pop=0), the
        # V1 simulation may have killed/reanimated them. Allow conscription
        # from treasury reserves (costly but keeps the faction alive).
        if total_pop <= 0:
            streak = _npc_conscript_streak.get(fid, 0)
            # Faction has no population but still has treasury — emergency draft
            # from hidden reserves (deserters, refugees, mercenaries).
            # Very expensive: 10 gold per soldier, half as many recruits.
            if faction.treasury >= amount * 10:
                emergency_amount = min(amount // 2, 2000)
                faction.strength_actual = getattr(faction, "strength_actual", 0) + emergency_amount
                faction.treasury -= emergency_amount * 10
                _npc_conscript_streak[fid] = streak + 1
                logger.warning(
                    "NPC %s emergency draft: no population, recruited %d from reserves (cost=%dg)",
                    fid, emergency_amount, emergency_amount * 10,
                )
            return
        if initial_pop > 0 and total_pop < initial_pop * _NPC_CONSCRIPT_LABOR_FLOOR_RATIO:
            logger.warning(
                "NPC %s conscript blocked: population %d below labor floor (%d)",
                fid, total_pop, int(initial_pop * _NPC_CONSCRIPT_LABOR_FLOOR_RATIO),
            )
            return

        # Max conscription rate with consecutive decay
        streak = _npc_conscript_streak.get(fid, 0)
        effective_rate = max(0.01, _NPC_CONSCRIPT_MAX_RATE - streak * _NPC_CONSCRIPT_CONSECUTIVE_DECAY)
        max_amount = max(_NPC_CONSCRIPT_MIN_AMOUNT, int(total_pop * effective_rate))
        amount = min(amount, max_amount)

        if amount <= 0:
            return

        # Realistic cost: 3 gold + 0.5 food per soldier (matches military.yaml)
        cost = int(amount * _NPC_CONSCRIPT_COST_PER_SOLDIER)
        food_cost = int(amount * _NPC_CONSCRIPT_FOOD_PER_SOLDIER)

        if faction.treasury >= cost and faction.food >= food_cost:
            faction.strength_actual = getattr(faction, "strength_actual", 0) + amount
            faction.treasury -= cost
            faction.food = max(0, faction.food - food_cost)
            _npc_conscript_streak[fid] = streak + 1
            logger.info(
                "NPC %s conscripted %d troops (rate=%.2f%%, pop=%d, cost=%dg+%df, streak=%d)",
                fid, amount, effective_rate * 100, total_pop, cost, food_cost, streak + 1,
            )
        else:
            _npc_conscript_streak[fid] = 0  # failed conscription resets streak
    elif action_type == "develop":
        cost = int(params.get("cost", 300) or 300)
        if faction.treasury >= cost:
            faction.treasury -= cost
            faction.economy_actual = min(100, getattr(faction, "economy_actual", 50) + 5)
    elif action_type == "diplomacy":
        target = fmap.get(nfa.get("target", ""), nfa.get("target", ""))
        if target in ws.factions and hasattr(faction, "relations"):
            rel_delta = int(params.get("relation_delta", 10) or 10)
            cur = faction.relations.get(target, 0)
            faction.relations[target] = _clamp(cur + rel_delta, -100, 100)
    elif action_type == "tax":
        if hasattr(faction, "tax_rate"):
            faction.tax_rate = _clamp(float(params.get("rate", 0.3) or 0.3), 0.05, 0.6)
    # declare_war / naval_blockade resolve via battle_results next quarter.


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
