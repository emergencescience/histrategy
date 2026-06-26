#!/usr/bin/env python3
"""E2E test: Rome Triumvirate — Octavian, 5 quarters, English mode."""
import os
import sys
import time

# Use macro engine for realistic simulation
os.environ["HISTRATEGY_ENGINE"] = "v3"

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter

llm = LLMAdapter()
print(f"LLM available: {llm.is_available}  provider: {llm.provider if hasattr(llm, 'provider') else 'unknown'}")

# Octavian's strategic decisions across 5 quarters (44 BC Spring → 43 BC Spring)
DECISIONS = [
    # Q1: 44 BC Spring - Secure legitimacy
    "Accept Caesar's will and claim my inheritance. Rally Caesar's veterans in Campania. "
    "Send envoys to the Senate declaring loyalty to the Republic while quietly building support.",

    # Q2: 44 BC Summer - Build power base
    "Use Caesar's treasury to recruit two legions from Campanian veterans. "
    "Negotiate with Cicero and moderate senators to gain political legitimacy. "
    "Observe Antony's moves in Rome but avoid direct confrontation for now.",

    # Q3: 44 BC Autumn - Challenge Antony
    "March toward Rome with my legions to pressure the Senate. "
    "Demand Antony hand over Caesar's treasury and documents. "
    "Offer a public reconciliation if Antony compromises.",

    # Q4: 44 BC/43 BC Winter - Political maneuvering
    "Accept the Senate's offer to make me propraetor with imperium. "
    "Form an alliance with Cicero against Antony. "
    "Send diplomats to Decimus Brutus in Cisalpine Gaul.",

    # Q5: 43 BC Spring - Consolidation
    "Demand the consulship from the Senate, backed by my legions. "
    "Begin negotiations with Antony to form a triumvirate if the Senate refuses. "
    "Continue consolidating control over central Italy.",
]

print("=" * 60)
print("E2E TEST: Rome Triumvirate — Octavian (5 quarters, English)")
print("=" * 60)

engine = GameEngine(llm=llm, scenario="rome-triumvirate", new_game=True)
engine.set_player_faction("octavian")

ws = engine.world_state_v2
print(f"Initial: Year {ws.year}, Player={ws.player_faction_id}")
pf = ws.factions.get(ws.player_faction_id)
if pf:
    territories = list(pf.territories) if pf.territories else []
    morale = getattr(pf, 'morale_actual', '?')
    print(f"  Territories: {territories}")
    print(f"  Treasury: {pf.treasury}  Food: {pf.food}  Strength: {pf.strength}  Morale: {morale}")

all_pass = True
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

        aftermath = result.get("aftermath", str(result)[:200])
        print(f"  Result: {aftermath[:200]}")

        if pf:
            morale = getattr(pf, 'morale_actual', '?')
            territories = list(pf.territories) if pf.territories else []
            print(f"  Treasury:{pf.treasury}  Food:{pf.food}  Morale:{morale}  Territories:{len(territories)}={territories}")

        # Check for errors
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
            all_pass = False

        if result.get("game_over"):
            print("  GAME OVER!")
            break

    except Exception as e:
        print(f"  CRASH: {type(e).__name__}: {e}")
        all_pass = False

print(f"\n{'=' * 60}")
print("FINAL STATE")
print(f"{'=' * 60}")
ws = engine.world_state_v2
for fid, f in ws.factions.items():
    active = getattr(f, "is_active", True)
    if not active:
        print(f"  {fid} ({f.name}): DEFEATED")
    else:
        t = list(f.territories) if f.territories else []
        morale = getattr(f, 'morale_actual', '?')
        strength = getattr(f, 'strength_actual', '?')
        print(f"  {fid} ({f.name}): Str={strength}  Gold={f.treasury}  "
              f"Food={f.food}  Morale={morale}  Terrs({len(t)})={t}")

print(f"\n{'=' * 60}")
print("E2E TEST RESULT: " + ("PASS" if all_pass else "FAIL"))
print(f"{'=' * 60}")
sys.exit(0 if all_pass else 1)
