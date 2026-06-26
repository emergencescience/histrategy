#!/usr/bin/env python3
"""E2E test: Rome Triumvirate — Cleopatra VII (Egypt), 8+ quarters, optimal strategy.

Production environment test — runs against live DB/LLM.
Tests the optimal Cleopatra strategy: leverage massive economy (90) + naval
superiority (80 ships) to dominate the Eastern Mediterranean, play pragmatic
diplomacy between Roman factions, and expand Egyptian influence.
"""
import os
import sys
import time

# Use V3 engine for realistic macro simulation
os.environ["HISTRATEGY_ENGINE"] = "v3"

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter

llm = LLMAdapter()
print(f"LLM available: {llm.is_available}  provider: {getattr(llm, 'provider', 'unknown')}")

# Cleopatra's optimal strategy across 8+ quarters (44 BC Spring →)
# Strategy: Leverage economy (90), navy (80 ships), and pragmatism.
# Phase 1: Consolidate Egypt's power base
# Phase 2: Naval expansion + Mediterranean trade dominance
# Phase 3: Expand territory into vulnerable regions
# Phase 4: Choose winning Roman ally + secure Eastern Mediterranean

DECISIONS = [
    # Q1: 44 BC Spring - Consolidate Egypt, open diplomacy
    "Secure Egypt's borders and begin a shipbuilding program to expand the navy. "
    "Send diplomatic envoys to Octavian, Antony, and the Senate — offer grain shipments "
    "to Rome as a gesture of goodwill while assessing their positions. "
    "Begin stockpiling treasury reserves for future campaigns.",

    # Q2: 44 BC Summer - Economic dominance
    "Leverage Egypt's grain monopoly to gain political leverage. "
    "Increase trade with Eastern Mediterranean ports. "
    "Continue naval buildup — target 100+ ships. "
    "Send secret envoys to both Octavian and Antony to understand their intentions "
    "toward Egypt's independence.",

    # Q3: 44 BC Autumn - Military strengthening
    "Recruit additional legions from Egypt and Cyrenaica. "
    "Dispatch the navy to patrol Eastern Mediterranean shipping lanes. "
    "Offer to mediate between Roman factions as a neutral power. "
    "Begin fortifying Alexandria and the Nile delta against potential invasion.",

    # Q4: 44 BC Winter - Intelligence gathering
    "Deploy spies across Rome, Greece, and Asia Minor to track Roman civil war developments. "
    "Consolidate control over Cyprus — establish it as a forward naval base. "
    "Strengthen trade agreements with Eastern kingdoms (Judea, Nabataea). "
    "Prepare contingency plans for any Roman faction threatening Egypt.",

    # Q5: 43 BC Spring - Flex naval power
    "Project naval power across the Eastern Mediterranean. "
    "Offer to support whichever Roman faction best guarantees Egypt's sovereignty. "
    "Expand grain exports to build foreign currency reserves. "
    "Continue military modernization — adopt Roman military tactics with Egyptian resources.",

    # Q6: 43 BC Summer - Strategic expansion
    "Identify and exploit weaknesses in neighboring territories. "
    "If Sextus Pompey is vulnerable, negotiate a naval alliance or absorb his fleet. "
    "Increase legion count to match any single Roman faction's land force. "
    "Offer Alexandria as a neutral meeting ground for Roman peace talks.",

    # Q7: 43 BC Autumn - Assert independence
    "Demand formal recognition of Egypt's sovereignty from all Roman factions. "
    "Use naval dominance to control grain shipments to Rome — starve factions that "
    "refuse to negotiate. Expand influence into Syria or North Africa if undefended. "
    "Position Egypt as the indispensable power broker of the Mediterranean.",

    # Q8: 43 BC Winter - Consolidate era
    "Formalize alliances with the most stable Roman faction. "
    "Secure all Eastern Mediterranean territories bordering Egypt. "
    "Begin long-term infrastructure projects (irrigation, ports, granaries). "
    "Establish Egypt as the economic and cultural heart of the Eastern Mediterranean.",
]

print("=" * 60)
print("E2E TEST: Rome Triumvirate — Cleopatra VII (8+ quarters, optimal strategy)")
print("=" * 60)

engine = GameEngine(llm=llm, scenario="rome-triumvirate", new_game=True)
engine.set_player_faction("cleopatra")

ws = engine.world_state_v2
print(f"Initial: Year {ws.year}, Player={ws.player_faction_id}")
pf = ws.factions.get(ws.player_faction_id)
if pf:
    territories = list(pf.territories) if pf.territories else []
    morale = getattr(pf, 'morale_actual', '?')
    print(f"  Territories: {territories}")
    print(f"  Treasury: {pf.treasury}  Food: {pf.food}  Strength: {pf.strength}  Morale: {morale}")
    print(f"  Ships: {getattr(pf, 'ships_count', '?')}  Economy: {getattr(pf, 'economy', '?')}")

all_pass = True
quarterly_data = []  # Collect stats for analysis

for i, decision in enumerate(DECISIONS):
    t0 = time.time()
    yr = -44 + (i // 4)
    season_names = ['Spring', 'Summer', 'Autumn', 'Winter']
    sz = season_names[i % 4]
    print(f"\n{'=' * 50}")
    print(f"Q{i+1} ({yr} {sz}): {decision[:80]}...")
    print(f"{'=' * 50}")

    try:
        result = engine.process_turn(decision)
        t1 = time.time()

        ws = result.get("world_state", engine.world_state_v2)
        pf = ws.factions.get(ws.player_faction_id) if ws else None

        usage = result.get("_usage", {})
        print(f"  Time: {t1 - t0:.1f}s  Tokens: {usage.get('sim_tokens', 'N/A')}")

        aftermath = result.get("aftermath", str(result)[:300])
        print(f"  Narrative: {aftermath[:300]}")

        if pf:
            morale = getattr(pf, 'morale_actual', '?')
            strength = getattr(pf, 'strength_actual', '?')
            territories = list(pf.territories) if pf.territories else []
            quarterly_data.append({
                "quarter": i+1,
                "year": yr,
                "season": sz,
                "treasury": pf.treasury,
                "food": pf.food,
                "strength": strength,
                "morale": morale,
                "territories": len(territories),
                "territory_list": territories,
                "tokens": usage.get('sim_tokens', 0),
                "time": t1 - t0,
            })
            print(f"  Treasury:{pf.treasury}  Food:{pf.food}  Str:{strength}  "
                  f"Morale:{morale}  Territories({len(territories)}):{territories}")

        # Check for errors
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
            all_pass = False

        if result.get("game_over"):
            print("  GAME OVER!")
            break

    except Exception as e:
        import traceback
        print(f"  CRASH: {type(e).__name__}: {e}")
        traceback.print_exc()
        all_pass = False

# ─── Final Report ────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print("CLEOPATRA STRATEGY REPORT")
print(f"{'=' * 60}")

print("\nQuarter-by-Quarter Stats:")
print(f"{'Q':>3} {'Year':>5} {'Season':>8} {'Treasury':>10} {'Food':>8} {'Str':>6} {'Morale':>6} {'Terrs':>5} {'Time':>6} {'Tokens':>6}")
print("-" * 85)
for q in quarterly_data:
    print(f"{q['quarter']:>3} {q['year']:>5} {q['season']:>8} {q['treasury']:>10} "
          f"{q['food']:>8} {q['strength']:>6} {q['morale']:>6} {q['territories']:>5} "
          f"{q['time']:>5.1f}s {q['tokens']:>6}")

print(f"\n{'=' * 60}")
print("FINAL STATE — All Factions")
print(f"{'=' * 60}")
ws = engine.world_state_v2
for fid, f in ws.factions.items():
    active = getattr(f, "is_active", True)
    if not active:
        print(f"  {fid} ({getattr(f, 'name', fid)}): DEFEATED")
    else:
        t = list(f.territories) if f.territories else []
        morale = getattr(f, 'morale_actual', '?')
        strength = getattr(f, 'strength_actual', '?')
        ships = getattr(f, 'ships_count', '?')
        print(f"  {fid} ({getattr(f, 'name', fid)}): Str={strength}  Gold={f.treasury}  "
              f"Food={f.food}  Morale={morale}  Ships={ships}  Terrs({len(t)})={t}")

total_tokens = sum(q['tokens'] for q in quarterly_data)
total_time = sum(q['time'] for q in quarterly_data)
print(f"\nTotal tokens: {total_tokens}  Total time: {total_time:.1f}s")

# Strategy assessment
if quarterly_data:
    first = quarterly_data[0]
    last = quarterly_data[-1]
    print("\nStrategy Assessment:")
    print(f"  Treasury change: {first['treasury']} → {last['treasury']} "
          f"({'+' if last['treasury'] >= first['treasury'] else ''}{last['treasury'] - first['treasury']})")
    print(f"  Territory change: {first['territories']} → {last['territories']} "
          f"({'+' if last['territories'] >= first['territories'] else ''}{last['territories'] - first['territories']})")
    print(f"  Strength change: {first['strength']} → {last['strength']}")
    print(f"  Morale change: {first['morale']} → {last['morale']}")

    # Optimal strategy check
    if last['territories'] >= first['territories'] and last['treasury'] >= first['treasury'] * 0.5:
        print("  Verdict: ✅ OPTIMAL — Egypt maintained or grew without catastrophic loss")
    elif last['territories'] >= first['territories']:
        print("  Verdict: ⚠️ MODERATE — Held territory but economic pressure")
    else:
        print("  Verdict: ❌ SUBOPTIMAL — Lost territory")

print(f"\n{'=' * 60}")
print("E2E TEST RESULT: " + ("PASS" if all_pass else "FAIL"))
print(f"{'=' * 60}")
sys.exit(0 if all_pass else 1)
