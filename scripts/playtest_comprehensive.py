#!/usr/bin/env python3
"""Comprehensive headless playtest for nanming — simulates production path.

Loads pre-baked NPC decisions from JSON, injects them as commands into
the V3 TurnController, and verifies battles, territory changes, troop
dynamics, and starvation mechanics across 10 turns.
"""

import json
import os
import sys

sys.path.insert(0, "/opt/data/repos/histrategy/histrategy-engine/src")
sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy_engine import (
    Command, DecisionEngine, MapEngine, MilitaryEngine,
    CharacterEngine, DomesticEngine, TurnController, 
    Season, WorldState,
)
from histrategy.engine.scenario_loader import ScenarioLoader

DECISIONS_DIR = "/opt/data/repos/histrategy/scenarios/nanming"

def load_npc_decisions(quarter, player_path=None):
    """Load pre-baked NPC decisions for a quarter."""
    fname = f"npc_decisions_q{quarter}.json"
    path = os.path.join(DECISIONS_DIR, fname)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    
    if quarter == 0:
        # Q0: {"decisions": {faction: {lang: {...}}}}
        return data.get("decisions", {})
    elif quarter == 1:
        # Q1: {"player_choices": {path: {"decisions": {...}}}}
        paths = data.get("player_choices", {})
        if player_path and player_path in paths:
            return paths[player_path].get("decisions", {})
        # Fallback to first path
        first = list(paths.keys())[0] if paths else None
        return paths[first].get("decisions", {}) if first else {}
    else:
        # Q2: {"player_paths": {path: {"decisions": {...}}}}
        paths = data.get("player_paths", {})
        if player_path and player_path in paths:
            return paths[player_path].get("decisions", {})
        first = list(paths.keys())[0] if paths else None
        return paths[first].get("decisions", {}) if first else {}

def npc_commands_from_decisions(decisions_data, lang="en", faction_ids=None):
    """Extract Command objects from NPC decisions data."""
    commands = {}
    for fid, lang_data in decisions_data.items():
        if faction_ids and fid not in faction_ids:
            continue
        ld = lang_data.get(lang, {})
        cmds_raw = ld.get("commands", [])
        cmds = []
        for c in cmds_raw:
            cmds.append(Command(
                faction_id=fid,
                type=c["type"],
                params=c.get("params", {}),
            ))
        commands[fid] = (ld.get("decision_text", ""), cmds)
    return commands


# ── Setup ──
loader = ScenarioLoader("nanming")
ws = loader.build_world_state("zheng")

# Initialize MapEngine with actual territory data
map_eng = MapEngine(ws.territories)
char_eng = CharacterEngine()
dom_eng = DomesticEngine()
mil_eng = MilitaryEngine()
dec_eng = DecisionEngine()
tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)

scenario = "nanming"
human_fid = "zheng"
npc_fids = ["qing", "nanming", "nongminjun"]

season_names = {Season.SPRING: "SPRING", Season.SUMMER: "SUMMER",
                Season.AUTUMN: "AUTUMN", Season.WINTER: "WINTER"}

def show_state(label):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'Faction':<16} {'Str':>8} {'Food':>8} {'Treas':>8} {'Terr':>5} {'Mor':>5} {'Deploy':>8}")
    print(f"  {'-'*65}")
    for fid in ["nanming", "qing", "nongminjun", "zheng"]:
        f = ws.factions.get(fid)
        if not f:
            continue
        armies = [a for a in ws.armies.values() if a.faction_id == fid]
        deployed = sum(a.total_troops for a in armies)
        n_terr = len(f.territories)
        print(f"  {fid:<16} {f.strength_actual:>8} {f.food:>8} {f.treasury:>8} {n_terr:>5} {f.morale_actual:>5} {deployed:>8}")
    
    # Territory ownership summary
    owned = {}
    for tid, t in ws.territories.items():
        owner = t.owner_id or "unowned"
        owned.setdefault(owner, []).append(tid)
    print(f"  Territories: {', '.join(f'{oid}:{len(ts)}' for oid, ts in sorted(owned.items()))}")


show_state(f"T0: {ws.year} {season_names.get(ws.season, '?')} — Initial State")

errors = []

# ── Run 10 turns ──
for turn in range(1, 11):
    # Load pre-baked NPC decisions for this turn
    if turn == 1:
        q = 0
        path = None
    elif turn == 2:
        q = 1
        path = "serve_ming"  # Player chose serve_ming in Q1
    else:
        q = 2
        path = "serve_ming_then_military_buildup"
    
    decisions_data = load_npc_decisions(q, path)
    npc_cmds = npc_commands_from_decisions(decisions_data, "en", npc_fids)
    
    # Build all commands: player + NPCs
    player_decision = f"Turn {turn}: strategic decision"
    player_cmds = [
        Command(faction_id="zheng", type="recruit", params={"territory": "fujian", "amount": 2000}),
        Command(faction_id="zheng", type="defend", params={"territory": "fujian"}),
    ]
    if turn >= 4:
        player_cmds.append(Command(faction_id="zheng", type="move", params={"destination": "zhejiang"}))
    
    all_cmds = list(player_cmds)
    npc_texts = {}
    for fid, (text, cmds) in npc_cmds.items():
        all_cmds.extend(cmds)
        npc_texts[fid] = text[:80]
    
    # Execute turn
    result = tc.execute_turn(
        ws,
        player_commands=all_cmds,
        year=ws.year,
        turn_number=turn,
        player_decision=player_decision,
    )
    
    # Show battles
    for b in result.battles:
        print(f"\n  ⚔️  BATTLE: {b.location} — {b.attacker_id} vs {b.defender_id} → {b.result.value}")
        print(f"      Attacker lost {sum(b.attacker_casualties.values())}, Defender lost {sum(b.defender_casualties.values())}")
        if b.territory_captured:
            print(f"      🏴 TERRITORY CAPTURED: {b.location} now belongs to {b.attacker_id}")
    
    show_state(f"Q{turn}: {ws.year} {season_names.get(ws.season, '?')}")
    
    # Validation checks
    # Check 1: strength_actual should roughly match deployed troops
    for fid in npc_fids + [human_fid]:
        f = ws.factions.get(fid)
        if not f:
            continue
        armies = [a for a in ws.armies.values() if a.faction_id == fid]
        deployed = sum(a.total_troops for a in armies)
        if deployed > 0 and f.strength_actual > 0:
            ratio = f.strength_actual / max(deployed, 1)
            if ratio > 1.5 or ratio < 0.5:
                errors.append(f"Q{turn}: {fid} strength_actual={f.strength_actual} vs deployed={deployed} (ratio={ratio:.2f})")

    # Check 2: no negative food
    for fid in npc_fids + [human_fid]:
        f = ws.factions.get(fid)
        if f and f.food < 0:
            errors.append(f"Q{turn}: {fid} food={f.food} (negative!)")

    # Check 3: territory owner consistency
    for fid in npc_fids + [human_fid]:
        f = ws.factions.get(fid)
        if not f:
            continue
        for tid in f.territories:
            t = ws.territories.get(tid)
            if t and t.owner_id != fid:
                errors.append(f"Q{turn}: {fid} claims {tid} but owner_id={t.owner_id}")

# ── Final summary ──
print(f"\n\n{'='*70}")
print(f"  FINAL: {ws.year} {season_names.get(ws.season, '?')} — After 10 Turns")
print(f"{'='*70}")

show_state("FINAL STATE")

zheng_f = ws.factions.get("zheng")
qing_f = ws.factions.get("qing")
print(f"\n  Zheng: {zheng_f.strength_actual} troops, {zheng_f.food} food, {len(zheng_f.territories)} terr, morale={zheng_f.morale_actual}")
print(f"  Qing:  {qing_f.strength_actual} troops, {qing_f.food} food, {len(qing_f.territories)} terr, morale={qing_f.morale_actual}")

if errors:
    print(f"\n❌ {len(errors)} validation errors:")
    for e in errors:
        print(f"  - {e}")
else:
    print(f"\n✅ No validation errors!")

# Territory change summary
print(f"\n  Territory changes:")
for tid, t in ws.territories.items():
    print(f"    {tid}: {t.owner_id} (pop={t.population}, dev={t.development})")

print("\n✅ 10-turn comprehensive playtest complete")
