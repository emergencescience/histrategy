#!/usr/bin/env python3
"""Headless playtest: Zheng (nanming) — 10 turns with V3 deterministic engine.

No HTTP server, no LLM calls. Pure engine test.
"""

import os
import sys

sys.path.insert(0, "/opt/data/repos/histrategy/histrategy-engine/src")
sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy_engine import (
    Army, Character, CharacterEngine, Command, DecisionEngine,
    DomesticEngine, MapEngine, MilitaryEngine, Season,
    Territory, TurnController, UnitType, WorldState, FactionState,
)

# ── Build nanming world state from scenario data ──
from histrategy.engine.scenario_loader import ScenarioLoader

loader = ScenarioLoader("nanming")
ws = loader.build_world_state("zheng")

print(f"Initial: year={ws.year}, season={ws.season.value}, turn={ws.turn_number}")
print(f"Factions: {list(ws.factions.keys())}")
print(f"Armies: {list(ws.armies.keys())}")

# ── Show initial state ──
print(f"\n{'='*70}")
print(f"  T0: {ws.year} {ws.season.value.upper()} — Initial State")
print(f"{'='*70}")
print(f"  {'Faction':<16} {'Strength':>10} {'Food':>8} {'Treasury':>8} {'Terr':>5} {'Morale':>6} {'Deploy':>10}")
print(f"  {'-'*70}")

def faction_summary(ws, label=""):
    if label:
        print(f"\n  --- {label} ---")
    for fid, f in ws.factions.items():
        armies = [a for a in ws.armies.values() if a.faction_id == fid]
        deployed = sum(a.total_troops for a in armies)
        n_terr = len(f.territories)
        print(f"  {fid:<16} {f.strength_actual:>10} {f.food:>8} {f.treasury:>8} {n_terr:>5} {f.morale_actual:>6} {deployed:>10}")

faction_summary(ws)

# ── Set up engines ──
map_eng = MapEngine()
char_eng = CharacterEngine()
dom_eng = DomesticEngine()
mil_eng = MilitaryEngine()
dec_eng = DecisionEngine()
tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)

# ── Player actions (English, Zheng perspective) ──
actions = [
    ("Consolidate coastal defenses. Recruit 3000 militia from Fujian villages.", [
        Command(faction_id="zheng", type="recruit", params={"territory": "fujian", "amount": 3000}),
        Command(faction_id="zheng", type="defend", params={"territory": "fujian"}),
    ]),
    ("Expand the fleet. Open trade with Southern Ming for food.", [
        Command(faction_id="zheng", type="recruit", params={"territory": "fujian", "amount": 2000}),
        Command(faction_id="zheng", type="develop", params={"territory": "fujian"}),
    ]),
    ("Fortify Guangdong. Build supply depots.", [
        Command(faction_id="zheng", type="develop", params={"territory": "guangdong"}),
        Command(faction_id="zheng", type="recruit", params={"territory": "guangdong", "amount": 2000}),
    ]),
    ("Send scouts north. Prepare naval raid.", [
        Command(faction_id="zheng", type="move", params={"destination": "zhejiang", "territory": "zhejiang"}),
    ]),
    ("Naval raid up the coast to harass Qing supply lines.", [
        Command(faction_id="zheng", type="attack", params={"target_territory": "jinan", "destination": "jinan"}),
    ]),
    ("Reinforce Southern Ming defenses at Nanjing.", [
        Command(faction_id="zheng", type="move", params={"destination": "nanjing", "territory": "nanjing"}),
    ]),
    ("Expand trade routes to fund war effort.", [
        Command(faction_id="zheng", type="develop", params={"territory": "fujian"}),
        Command(faction_id="zheng", type="recruit", params={"territory": "fujian", "amount": 2000}),
    ]),
    ("Coordinate joint offensive with allies.", [
        Command(faction_id="zheng", type="attack", params={"target_territory": "kaifeng", "destination": "kaifeng"}),
    ]),
    ("Naval bombardment of Qing coastal positions.", [
        Command(faction_id="zheng", type="attack", params={"target_territory": "beijing", "destination": "beijing"}),
    ]),
    ("Full joint offensive: fleet + army coordinated strike.", [
        Command(faction_id="zheng", type="attack", params={"target_territory": "luoyang", "destination": "luoyang"}),
        Command(faction_id="zheng", type="recruit", params={"territory": "fujian", "amount": 3000}),
    ]),
]

# ── Run 10 turns ──
for i, (desc, commands) in enumerate(actions):
    turn_num = i + 1
    result = tc.execute_turn(
        ws,
        player_commands=commands,
        year=ws.year,
        turn_number=turn_num,
        player_decision=desc,
    )

    season_display = {Season.SPRING: "SPRING", Season.SUMMER: "SUMMER",
                      Season.AUTUMN: "AUTUMN", Season.WINTER: "WINTER"}
    
    print(f"\n{'='*70}")
    print(f"  Q{turn_num}: {ws.year} {season_display.get(ws.season, '?')} — \"{desc[:50]}...\"")
    print(f"{'='*70}")

    # Show battles
    for b in result.battles:
        print(f"  ⚔️  {b.location}: {b.attacker_id} vs {b.defender_id} → {b.result.value}")
    
    # Show territory changes
    faction_summary(ws, f"After Q{turn_num}")

# ── Final summary ──
print(f"\n\n{'='*70}")
print(f"  FINAL STATE — {ws.year}, {ws.season.value.upper()}")
print(f"{'='*70}")
faction_summary(ws, "Final")

zheng_f = ws.factions.get("zheng")
qing_f = ws.factions.get("qing")
if zheng_f:
    print(f"\n  Zheng: {zheng_f.strength_actual} troops, {zheng_f.food} food, {len(zheng_f.territories)} territories")
if qing_f:
    print(f"  Qing:  {qing_f.strength_actual} troops, {qing_f.food} food, {len(qing_f.territories)} territories")

print("\n✅ 10-turn playtest complete")
