#!/usr/bin/env python3
"""P0-3 regression tests — economic equilibrium levers.

1. treasury-driven troop loss capped: broke 100k army at morale 6 loses ≤8%
   (3% desertion + 5% forced disband), and NO 10% morale rout at morale 6
   (old threshold ≤10 made the rout stack every quarter for chronically-broke
   factions — 90a7cac spiral).
2. conquest loot: taking a city adds treasury+food to the victor (expansion
   relieves the treasury spiral instead of deepening it).

Run: python3 scripts/test_p03_economy_equilibrium.py
"""
import os
import sys
import types

os.environ["HISTRATEGY_DATA_DIR"] = "/tmp/test_p03"
os.environ.pop("HISTRATEGY_DATABASE_URL", None)
os.environ["HISTRATEGY_ENGINE"] = "v3"

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.scenario_loader import ScenarioLoader  # noqa: E402
from histrategy.engine.quarterly_engine import QuarterlyEngine  # noqa: E402
from histrategy.engine.state_applier import _transfer_territory  # noqa: E402


def _test_desertion_cap() -> bool:
    ws = ScenarioLoader("three-kingdoms").build_world_state("cao")
    cao = ws.factions["cao"]
    cao.strength_actual = 100_000
    cao.treasury = 0.0
    cao.morale_actual = 6
    cao.food = 50_000
    result = types.SimpleNamespace(notable_events=[])
    QuarterlyEngine("three-kingdoms").execute_treasury_penalties(
        ws, result, apply_to_player=True)
    lost = 100_000 - cao.strength_actual
    pct = lost / 100_000
    ok = pct <= 0.085  # 3% desertion + 5% disband + rounding
    print(f"[desertion_cap] broke 100k army lost {lost} ({pct*100:.1f}%) "
          f"(expect ≤8.5%, no 10% rout at morale 6) → {'PASS' if ok else 'FAIL'}")
    print(f"  events: {[e for e in result.notable_events][:3]}")
    return ok


def _test_conquest_loot() -> bool:
    ws = ScenarioLoader("three-kingdoms").build_world_state("cao")
    shu = ws.factions["shu"]
    cao = ws.factions["cao"]
    # shu owns xinye/jiangxia in the loader; hand xinye to shu if needed
    target = "xinye"
    if target not in shu.territories:
        for tid in list(shu.territories):
            target = tid
            break
    t0 = ws.territories[target]
    pop0 = int(getattr(t0, "population", 0) or 0)
    gold0, food0 = cao.treasury, cao.food
    _transfer_territory(target, "cao", "shu", ws, {"territories_captured": 0})
    g_gold = cao.treasury - gold0
    g_food = cao.food - food0
    ok = g_gold >= max(1500, int(pop0 * 0.06)) and g_food >= max(3000, int(pop0 * 0.25))
    print(f"[conquest_loot] cao took {target} (pop {pop0}): +{g_gold:.0f} gold, "
          f"+{g_food:.0f} food → {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    ok1 = _test_desertion_cap()
    ok2 = _test_conquest_loot()
    print("\nP0-3 economy equilibrium:", "ALL PASS" if (ok1 and ok2) else "FAILED")
    sys.exit(0 if (ok1 and ok2) else 1)
