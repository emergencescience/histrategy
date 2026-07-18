#!/usr/bin/env python3
"""
Mass Warlords Headless Simulation Runner
=========================================
Runs 31 warlords (all NPC) autonomously for 100 turns.
Heuristic-only mode (no LLM needed).
Exports CSV data and generates SVG charts.

Usage:
    HISTRATEGY_ENGINE=v3 .venv/bin/python scripts/mass_warlords_sim.py \\
        --turns 100 --output results/mass_warlords
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("HISTRATEGY_ENGINE", "v3")
os.environ.setdefault("HISTRATEGY_DATA_DIR", "/tmp/histrategy_mass")

from histrategy.engine.game_room import GameRoom, RoomPhase
from histrategy.engine.faction_slot import create_ai_slot
from histrategy.engine.scenario_loader import ScenarioLoader
from histrategy.engine.decision_bus import DecisionResult, collect_all_decisions
from histrategy.engine.quarterly_resolver import QuarterlyResolver
from histrategy.engine.game import GameEngine

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("mass_warlords")

MAJOR_NPC_IDS = {"cao", "wu", "shu", "liubiao", "mateng", "liuzhang", "zhanglu", "gongsunkang"}


def build_all_ai_room(scenario: str, faction_ids: list[str]) -> GameRoom:
    """Create a GameRoom where every faction is AI-controlled."""
    room = GameRoom(scenario=scenario)
    for fid in faction_ids:
        room.slots[fid] = create_ai_slot(fid)
    room.major_npc_ids = MAJOR_NPC_IDS
    room.phase = RoomPhase.WAITING
    return room


def run_simulation(
    scenario: str = "mass-warlords",
    turns: int = 100,
    output_prefix: str = "results/mass_warlords",
) -> dict:
    """Run the full simulation and return results."""
    os.makedirs(os.path.dirname(output_prefix) or ".", exist_ok=True)

    # ── Load scenario ──
    loader = ScenarioLoader(scenario)
    ws = loader.build_world_state("cao")  # pick any as "player" — we override slots below
    faction_ids = sorted(ws.factions.keys())
    print(f"Loaded {len(faction_ids)} factions: {', '.join(faction_ids[:8])}...")
    print(f"Starting year={ws.year}, season={ws.season}")

    # ── Create GameRoom (all AI) ──
    room = build_all_ai_room(scenario, faction_ids)

    # ── Create GameEngine (V2: TurnController only, no LLM) ──
    try:
        engine = GameEngine(scenario=scenario, new_game=True, llm=None)
        engine.world_state_v2 = ws
        engine._use_v2 = True
        # IMPORTANT: Load territories into MapEngine for pathfinding
        engine.map_engine.load_territories(ws.territories)
        resolver = QuarterlyResolver(
            intent_parser=getattr(engine, "intent_parser", None),
            turn_controller=getattr(engine, "turn_controller", None),
        )
        print("GameEngine initialized (V2 heuristic mode)")
    except Exception as e:
        print(f"GameEngine init failed: {e}, using bare resolver")
        resolver = QuarterlyResolver()

    # ── CSV output ──
    csv_path = f"{output_prefix}_turns.csv"
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow([
        "turn", "year", "season", "active_factions", "total_strength",
        "max_strength", "max_faction", "min_strength", "min_faction",
        "median_strength", "gini_strength",
        "casualties", "battles", "diplomacy_events",
    ])

    # ── Faction detail CSV ──
    detail_path = f"{output_prefix}_factions.csv"
    detail_file = open(detail_path, "w", newline="")
    detail_writer = csv.writer(detail_file)
    detail_writer.writerow(["turn", "faction_id", "name", "strength", "territories",
                             "economy", "morale", "is_active", "survived"])

    # ── Run turns ──
    stats = []
    total_start = time.time()

    for turn_num in range(1, turns + 1):
        t_start = time.time()

        # Collect decisions from all AI slots
        decisions = collect_all_decisions(room, ws, llm=None, turn_memory=room.turn_summaries)

        # Resolve quarter
        result = resolver.resolve(room, ws, decisions, llm=None, skip_narrative=True)

        # ── Post-resolution: sync faction state from armies & territories ──
        _sync_faction_state(ws)

        # Count active (active = has territories)
        active_factions = [f for f in ws.factions.values() if getattr(f, "territories", []) and f.is_active]
        strengths = sorted([f.strength_actual for f in active_factions], reverse=True)

        # Calculate Gini coefficient
        gini = _gini(strengths) if len(strengths) > 1 else 0.0

        # Extract casualties/battles from result
        casualties = result.macro_delta.get("total_casualties", 0) if hasattr(result, "macro_delta") and result.macro_delta else 0
        battles = result.macro_delta.get("total_battles", 0) if hasattr(result, "macro_delta") and result.macro_delta else 0
        diplomacy = result.macro_delta.get("diplomacy_events", 0) if hasattr(result, "macro_delta") and result.macro_delta else 0

        row = [
            turn_num, ws.year, ws.season.value, len(active_factions),
            sum(strengths), strengths[0] if strengths else 0,
            active_factions[0].id if active_factions else "",
            strengths[-1] if strengths else 0,
            active_factions[-1].id if active_factions else "",
            _median(strengths), round(gini, 4),
            casualties, battles, diplomacy,
        ]
        csv_writer.writerow(row)

        # Detail rows
        all_fs = sorted(ws.factions.values(), key=lambda f: f.strength_actual, reverse=True)
        for fs in all_fs:
            detail_writer.writerow([
                turn_num, fs.id, fs.name, fs.strength_actual,
                len(fs.territories) if hasattr(fs, "territories") else 0,
                getattr(fs, "economy_actual", 0),
                getattr(fs, "morale_actual", 0),
                1 if fs.is_active else 0,
                1 if fs.is_active else 0,
            ])

        # Advance quarter
        room.advance_quarter()

        elapsed = time.time() - t_start
        survivors = len(active_factions)

        # Print progress
        if turn_num % 10 == 0 or survivors <= 8 or turn_num <= 5:
            top3 = ", ".join(f"{f.name}({f.strength_actual})" for f in all_fs[:3]) if all_fs else "none"
            print(f"  T{turn_num:3d} | {survivors:2d} alive | gini={gini:.3f} | top3: {top3} | {elapsed:.1f}s")

        stats.append({"turn": turn_num, "survivors": survivors, "gini": gini,
                       "total_strength": sum(strengths),
                       "max_strength": strengths[0] if strengths else 0,
                       "max_faction": all_fs[0].name if all_fs else ""})

        # Early termination: if only 1 left, stop
        if survivors <= 1:
            print(f"Only {survivors} faction(s) remain — stopping at turn {turn_num}")
            break

    csv_file.close()
    detail_file.close()

    # ── Summary ──
    total_elapsed = time.time() - total_start
    final_active = [f for f in ws.factions.values() if f.is_active]
    print(f"\n=== SIMULATION COMPLETE ===")
    print(f"Turns: {turn_num}, Time: {total_elapsed:.0f}s ({total_elapsed/turn_num:.1f}s/turn)")
    print(f"Survivors: {len(final_active)}/{len(faction_ids)}")
    for f in sorted(final_active, key=lambda x: x.strength_actual, reverse=True):
        print(f"  {f.name:10s} str={f.strength_actual:>8} terrs={len(f.territories)}")

    # Save final state
    final_path = f"{output_prefix}_final.json"
    final_state = {
        f.id: {
            "name": f.name,
            "strength": f.strength_actual,
            "economy": getattr(f, "economy_actual", 0),
            "morale": getattr(f, "morale_actual", 0),
            "territories": len(f.territories),
            "is_active": f.is_active,
        }
        for f in ws.factions.values()
    }
    with open(final_path, "w") as f:
        json.dump(final_state, f, indent=2, ensure_ascii=False)
    print(f"CSV: {csv_path}, {detail_path}")
    print(f"Final state: {final_path}")

    return {"turns": turn_num, "stats": stats, "final_factions": final_state}


def _gini(values: list[float]) -> float:
    """Compute Gini coefficient (0=perfect equality, 1=perfect inequality)."""
    if not values:
        return 0.0
    n = len(values)
    total = sum(values)
    if total == 0:
        return 0.0
    sorted_vals = sorted(values)
    cumsum = 0.0
    for i, v in enumerate(sorted_vals, 1):
        cumsum += v
        # Lorenz curve area
    # Gini = 1 - 2 * area_under_lorenz
    # Quick formula: sum((2*i - n - 1) * x_i) / (n * sum(x))
    numerator = sum((2 * i - n - 1) * x for i, x in enumerate(sorted(sorted_vals), 1))
    return numerator / (n * sum(sorted_vals))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    n = len(values)
    mid = n // 2
    if n % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2
    return values[mid]


def _distribute_armies(ws) -> None:
    """Place an army at every territory owned by each faction.

    The default loader creates only one army per faction (at the capital).
    But the TurnController can only move to adjacent territories, so
    factions need armies at border territories to attack neighbours.
    This creates extra small garrison armies at non-capital territories.
    """
    from histrategy_engine.world import Army, UnitType

    army_idx = 100  # start high to avoid collision with existing armies
    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        territories = list(getattr(faction, "territories", []))
        if len(territories) <= 1:
            continue

        # Check which territories already have an army
        existing_locations = {
            a.location for a in ws.armies.values() if a.faction_id == fid
        }
        capital = getattr(faction, "capital", territories[0])

        for tid in territories:
            if tid in existing_locations:
                continue
            # Create a garrison force (10-20% of the main army size)
            garrison_size = max(1000, faction.strength_actual // (len(territories) * 3))
            if garrison_size < 500:
                continue
            army_id = f"army_{fid}_{army_idx}"
            army_idx += 1
            ws.armies[army_id] = Army(
                id=army_id,
                faction_id=fid,
                location=tid,
                units={UnitType.INFANTRY: garrison_size},
                morale=faction.morale_actual,
            )
    print(f"Distributed garrison armies: {len(ws.armies)} total armies")


def _sync_faction_state(ws) -> None:
    """Reconcile faction state from armies and territory ownership.

    The V2 TurnController resolves battles but doesn't update faction-level
    stats. This function:
    - Recalculates faction strength from surviving armies
    - Marks factions with 0 territories as inactive
    """
    for fid, faction in ws.factions.items():
        # Sum army troops for this faction
        total_troops = sum(
            a.total_troops for a in ws.armies.values()
            if a.faction_id == fid
        )
        territory_count = len(getattr(faction, "territories", []))

        # Update strength from surviving armies
        if territory_count == 0:
            # No land = dead faction, regardless of surviving troops
            faction.strength_actual = 0
            faction.is_active = False
        elif total_troops > 0:
            faction.strength_actual = max(500, total_troops)

        # Clean up dead armies from ws.armies
        dead_army_ids = [
            aid for aid, a in ws.armies.items()
            if a.faction_id == fid and a.total_troops == 0
        ]
        for aid in dead_army_ids:
            del ws.armies[aid]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mass Warlords Headless Simulation")
    parser.add_argument("--turns", type=int, default=100, help="Number of turns to simulate")
    parser.add_argument("--output", type=str, default="results/mass_warlords", help="Output file prefix")
    args = parser.parse_args()

    run_simulation(turns=args.turns, output_prefix=args.output)
