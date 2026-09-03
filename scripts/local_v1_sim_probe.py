#!/usr/bin/env python3
"""V1 engine quality probe — drives V1Simulator directly with real player/NPC
decision texts from the 90a7cac fixture. Measures pure-LLM world advancement:
state coherence, troop/treasury sanity, narrative quality, latency, cost.

Usage:
  python3 scripts/local_v1_sim_probe.py --quarters 3 [--json /tmp/v1_report.json]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "/opt/data/repos/histrategy")
os.environ["HISTRATEGY_DATA_DIR"] = "/tmp/histrategy_v1sim"
os.environ.pop("HISTRATEGY_DATABASE_URL", None)

for env_file in (os.path.expanduser("~/.hermes/.env"),
                 os.path.join("/opt/data/repos/histrategy", ".env")):
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from histrategy.engine.scenario_loader import ScenarioLoader  # v3 loader path (safe for TK)
from histrategy.engine.v1_simulator import V1Simulator
from histrategy.llm.adapter import LLMAdapter

FIXTURE = "/opt/data/repos/histrategy/tests/fixtures/rooms/90a7cac_cao_24q.json"
GENERIC = "休养生息，发展经济，整饬军备，待时而动。"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", type=int, default=3)
    ap.add_argument("--json", default="/tmp/v1_sim_report.json")
    args = ap.parse_args()

    turns = json.load(open(FIXTURE))["turns"]
    # per-quarter decision text for factions present in fixture
    dec_by_q = {}
    for t in turns:
        fd = t.get("faction_decisions") or {}
        if isinstance(fd, str):
            fd = json.loads(fd)
        q = t["quarter_number"]
        if q and q <= args.quarters:
            dec_by_q[q] = {
                fid: (v.get("decision") if isinstance(v, dict) else str(v))
                for fid, v in fd.items() if isinstance(v, dict) and v.get("decision")
            }

    llm = LLMAdapter()
    print(f"[v1probe] provider={getattr(llm, 'provider_name', '?')} "
          f"model={getattr(llm, 'model', '?')} available={llm.is_available}")
    if not llm.is_available:
        print("LLM unavailable — abort")
        return 2

    loader = ScenarioLoader("three-kingdoms")
    world = loader.build_world_state("cao")
    sim = V1Simulator(llm)
    memory: list = []
    report = {"engine": "v1-simulator", "turns": []}

    def snap():
        out = {}
        for fid, f in (getattr(world, "factions", {}) or {}).items():
            out[fid] = {
                "troops": getattr(f, "strength_actual", None) or getattr(f, "strength", None),
                "treasury": getattr(f, "treasury", None),
                "food": getattr(f, "food", None),
                "morale": getattr(f, "morale", None),
                "terr": sorted(getattr(f, "territories", []) or []),
            }
        return out

    report["turns"].append({"quarter": 0, "note": "initial", "snap": snap()})
    for q in range(1, args.quarters + 1):
        qdec = dec_by_q.get(q, {})
        decisions = {}
        for fid in (world.factions or {}):
            decisions[fid] = qdec.get(fid, GENERIC)
        t0 = time.time()
        print(f"\n[v1probe] Q{q}: decisions={ {k: (v[:24] + '…') for k, v in decisions.items()} }")
        try:
            result = sim.simulate(world, decisions, memory)
        except Exception as e:
            import traceback
            traceback.print_exc()
            report["turns"].append({"quarter": q, "error": str(e)})
            break
        dt = time.time() - t0
        rkeys = list(result.keys()) if isinstance(result, dict) else type(result).__name__
        print(f"[v1probe] Q{q} done in {dt:.0f}s, result keys: {rkeys}")
        # production flow: server calls _apply_v1_state_to_world after simulate
        try:
            from histrategy.engine.v1_simulator import _apply_v1_state_to_world
            v1_factions = result.get("factions", {}) if isinstance(result, dict) else {}
            _apply_v1_state_to_world(world, v1_factions)
            applied = True
        except Exception as e:
            applied = False
            print(f"[v1probe] apply failed: {e}")
        report["turns"].append({
            "quarter": q, "latency_s": round(dt, 1),
            "state_applied": applied,
            "snap": snap(),
            "result_keys": [str(k) for k in (rkeys or [])],
        })
        if isinstance(result, dict):
            for k in ("narrative", "global_narrative", "summary", "events"):
                if result.get(k):
                    report["turns"][-1][k] = str(result[k])[:600]
        if memory is not None and isinstance(memory, list) and len(memory) > 0:
            report["turns"][-1]["memory_tail"] = str(memory[-1])[:300]

    with open(args.json, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[v1probe] report -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
