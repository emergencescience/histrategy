#!/usr/bin/env python3
"""P0-1 regression test — battle record must reflect deterministic settlement.

Reproduces 90a7cac Q16/Q21: LLM narrated "僵持/stalemate, capture=false" but
the deterministic engine (force ratio OR defender-morale collapse) transferred
the city. The stored macro_delta kept the LLM fiction → 战报与状态脱节.

Cases:
  1. morale-collapse capture: weak liubiao attacks cao's wancheng while cao's
     morale=5 (< _MORALE_COLLAPSE_THRESHOLD). LLM says stalemate/capture=false
     → settle MUST transfer AND rewrite br: territory_captured=True,
     result="capture", settled.reason="morale_collapse".
  2. no-capture correction: weak shu attacks cao, LLM claims attack_win/
     capture=True → settle does NOT transfer AND br is corrected to
     territory_captured=False, result="defense_held".

Run: python3 scripts/test_p01_battle_truth_sync.py
"""
import os
import sys
import types

os.environ["HISTRATEGY_DATA_DIR"] = "/tmp/test_p01"
os.environ.pop("HISTRATEGY_DATABASE_URL", None)
os.environ["HISTRATEGY_ENGINE"] = "v3"

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.scenario_loader import ScenarioLoader  # noqa: E402
from histrategy.engine.state_applier import StateApplier  # noqa: E402

TARGET = "wancheng"  # cao city bordering liubiao(xiangyang) & shu(xinye)


def _set_morale(f, val):
    for attr in ("morale_actual", "morale"):
        if hasattr(f, attr):
            setattr(f, attr, val)


def _run(br: dict, cao_morale: int, shu_morale: int,
         attacker: str, expected_captured: bool, label: str) -> bool:
    ws = ScenarioLoader("three-kingdoms").build_world_state("cao")
    cao, shu, liubiao = ws.factions["cao"], ws.factions["shu"], ws.factions["liubiao"]
    _set_morale(cao, cao_morale)
    _set_morale(shu, shu_morale)
    _set_morale(liubiao, 50)

    before = ws.territories[TARGET].owner_id
    baseline = types.SimpleNamespace(notable_events=[], state_changes={})
    try:
        StateApplier().apply_macro_delta({"battle_results": [br]}, ws, baseline)
    except Exception as e:
        print(f"[{label}] apply raised {type(e).__name__}: {e}")
        return False

    after = ws.territories[TARGET].owner_id
    ok_owner = (after != before) == expected_captured
    ok_br = bool(br.get("territory_captured")) == expected_captured
    settled = br.get("settled") or {}
    print(f"[{label}] owner {before}->{after} (expect transfer={expected_captured}) "
          f"| br.territory_captured={br.get('territory_captured')} "
          f"| br.result={br.get('result')!r} "
          f"| settled={ {k: settled.get(k) for k in ('captured', 'reason', 'power_ratio')} }")
    ok = ok_owner and ok_br and settled.get("captured") == expected_captured
    print(f"[{label}] → {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    # Case 1: morale collapse — weak attacker takes the city despite LLM "stalemate"
    ok1 = _run(
        {"attacker": "liubiao", "defender": "cao", "location": TARGET,
         "result": "stalemate", "territory_captured": False, "casualties": {}},
        cao_morale=5, shu_morale=50, attacker="liubiao",
        expected_captured=True, label="morale_collapse_capture")
    # Case 2: LLM overclaims a capture — engine holds, record corrected
    ok2 = _run(
        {"attacker": "shu", "defender": "cao", "location": TARGET,
         "result": "attack_win", "territory_captured": True, "casualties": {}},
        cao_morale=80, shu_morale=30, attacker="shu",
        expected_captured=False, label="overclaim_corrected")
    print("\nP0-1 battle truth sync:", "ALL PASS" if (ok1 and ok2) else "FAILED")
    sys.exit(0 if (ok1 and ok2) else 1)
