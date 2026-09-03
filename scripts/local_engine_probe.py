#!/usr/bin/env python3
"""Local engine probe — run N quarters of any engine mode, print per-turn
snapshots + macro events so integrity invariants can be eyeballed or asserted.

Usage:
  HISTRATEGY_ENGINE=v3 python3 scripts/local_engine_probe.py \
      --scenario three-kingdoms --faction cao --quarters 5 [--json /tmp/out.json]

Decisions are passed as JSON via --decisions-file or --decisions (list of str).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "/opt/data/repos/histrategy")
os.environ["HISTRATEGY_DATA_DIR"] = os.environ.get(
    "HISTRATEGY_DATA_DIR", "/tmp/histrategy_probe"
)
os.environ.pop("HISTRATEGY_DATABASE_URL", None)  # force local sqlite, never prod

_hermes_env = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_hermes_env):
    for line in open(_hermes_env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
_repo_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_repo_env):
    for line in open(_repo_env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter


def snap(engine) -> dict:
    """Per-faction snapshot from the engine's live world state."""
    out = {}
    ws = getattr(engine, "world_state_v2", None) or getattr(engine, "world_state", None)
    if ws is None:
        return {"error": "no world_state attr"}
    for fid, f in (getattr(ws, "factions", {}) or {}).items():
        out[fid] = {
            "troops": getattr(f, "strength_actual", None) or getattr(f, "strength", None),
            "treasury": getattr(f, "treasury", None),
            "food": getattr(f, "food", None),
            "morale": getattr(f, "morale", None),
            "terr": sorted(getattr(f, "territories", []) or []),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="three-kingdoms")
    ap.add_argument("--faction", default="cao")
    ap.add_argument("--quarters", type=int, default=4)
    ap.add_argument("--decisions-file", default=None)
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--json", default=None, help="write JSON report here")
    args = ap.parse_args()

    if args.decisions_file:
        decisions = json.load(open(args.decisions_file))
    else:
        decisions = json.loads(args.decisions or "[]")

    mode = os.environ.get("HISTRATEGY_ENGINE", "v3")
    llm = LLMAdapter()
    print(f"[probe] engine={mode} llm_available={llm.is_available} "
          f"provider={getattr(llm, 'provider_name', '?')} model={getattr(llm, 'model', '?')}")
    if not llm.is_available and mode != "v2":
        print("[probe] LLM NOT available — engine will degrade; aborting")
        return 2

    engine = GameEngine(llm=llm, scenario=args.scenario, new_game=True)
    engine.set_player_faction(args.faction)
    report = {
        "engine": mode, "scenario": args.scenario, "faction": args.faction,
        "turns": [],
    }
    report["turns"].append({
        "quarter": 0, "note": "initial",
        "snap": snap(engine),
        "battle_results": [], "npc_actions": [],
    })

    for i in range(args.quarters):
        decision = decisions[i] if i < len(decisions) else "休养生息，发展经济，操练兵马。"
        t0 = time.time()
        print(f"\n[probe] Q{i+1}: {decision[:60]}...")
        try:
            r = engine.process_turn(decision)
        except Exception as e:
            import traceback
            traceback.print_exc()
            report["turns"].append({"quarter": i + 1, "error": str(e)})
            break
        md = getattr(r, "macro_delta", None) or (r or {}).get("macro_delta", {}) if isinstance(r, dict) else getattr(r, "macro_delta", None)
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:
                md = {}
        dt = time.time() - t0
        print(f"[probe] Q{i+1} done in {dt:.0f}s")
        report["turns"].append({
            "quarter": i + 1,
            "latency_s": round(dt, 1),
            "snap": snap(engine),
            "battle_results": (md or {}).get("battle_results", []) if isinstance(md, dict) else [],
            "npc_actions": (md or {}).get("npc_faction_actions", []) if isinstance(md, dict) else [],
            "narrative": (md or {}).get("narrative_seeds", []) if isinstance(md, dict) else [],
        })

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[probe] report -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
