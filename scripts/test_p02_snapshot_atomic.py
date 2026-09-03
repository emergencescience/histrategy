#!/usr/bin/env python3
"""P0-2 regression test — game_state snapshot atomicity.

Reproduces 90a7cac Q1: a faction fully wiped during resolution (0 cities,
legitimate exile) must NOT get its pre-war cities resurrected by the H35k
pre_territories fallback in _save_v3_state_to_db.

Cases:
  1. ws.territories intact + faction owns nothing  → save [] (FIXED behavior)
  2. ws.territories cleared (true engine data loss) → pre_territories fallback
     still applies (H35k protection preserved)

Run: python3 scripts/test_p02_snapshot_atomic.py
"""
import json
import os
import shutil
import sqlite3
import sys
import types
import glob

os.environ["HISTRATEGY_DATA_DIR"] = "/tmp/test_p02_snapshot"
os.environ.pop("HISTRATEGY_DATABASE_URL", None)
os.environ["HISTRATEGY_ENGINE"] = "v3"
shutil.rmtree("/tmp/test_p02_snapshot", ignore_errors=True)  # fresh db before imports

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.db.connection import init_db  # noqa: E402
from histrategy.engine.scenario_loader import ScenarioLoader  # noqa: E402
from histrategy.server import room_manager  # noqa: E402

init_db()  # once, after imports — creates tables in the fresh data dir


def _wipe_faction(ws, fid: str, wipe_map: bool):
    """Give all of fid's cities to cao; optionally also clear the whole map."""
    cities = list(getattr(ws.factions[fid], "territories", []) or [])
    for cid in cities:
        if cid in ws.territories:
            ws.territories[cid].owner_id = "cao"
    ws.factions[fid].territories = []
    if wipe_map:
        ws.territories = {}


def _pre_territories_snapshot(ws):
    """Snapshot in the same shape pre_territories is passed (per-faction city dicts)."""
    snap = {}
    for fid, f in ws.factions.items():
        items = []
        for cid in getattr(f, "territories", []) or []:
            t = ws.territories.get(cid)
            items.append({"id": cid, "name": getattr(t, "name", cid),
                          "population": getattr(t, "population", 50000)})
        snap[fid] = items
    return snap


def _run_case(wipe_map: bool, expected_terr_empty: bool) -> bool:
    loader = ScenarioLoader("three-kingdoms")
    ws = loader.build_world_state("cao")
    room_id = f"p02_{'maplost' if wipe_map else 'wipe'}"
    pre = _pre_territories_snapshot(ws)          # shu has 2 cities here
    _wipe_faction(ws, "shu", wipe_map=wipe_map)  # shu -> 0 cities
    old_state = {"shu": {"population": 100000, "troops": 10000,
                         "food": 3500, "treasury": 5000, "morale": 70}}

    room = types.SimpleNamespace(id=room_id, quarter_number=0)
    result = types.SimpleNamespace(state_changes={})
    # satisfy FK: game_state.room_id -> game_room(id)
    try:
        from histrategy.db import connection as _conn
        _conn.execute_write(
            "INSERT OR IGNORE INTO game_room (id, created_at, updated_at) "
            "VALUES (?, '', '')", (room_id,))
    except Exception as e:
        print(f"[case wipe_map={wipe_map}] game_room insert failed: {e}")
    try:
        room_manager._save_v3_state_to_db(
            room, ws, {}, result, old_state, pre_territories=pre)
    except Exception as e:
        print(f"[case wipe_map={wipe_map}] raised {type(e).__name__}: {e}")
        return False

    dbs = glob.glob("/tmp/test_p02_snapshot/**/*.db", recursive=True)
    if not dbs:
        print(f"[case wipe_map={wipe_map}] no sqlite db found under data dir")
        return False
    con = sqlite3.connect(dbs[0])
    row = con.execute(
        "SELECT territories FROM game_state WHERE room_id=? AND faction_id='shu' "
        "AND quarter_number=1", (room_id,)).fetchone()
    con.close()
    if row is None:
        print(f"[case wipe_map={wipe_map}] shu q1 row not found")
        return False
    saved = json.loads(row[0]) if row[0] else []
    ok = (len(saved) == 0) == expected_terr_empty
    print(f"[case wipe_map={wipe_map}] shu q1 saved cities={len(saved)} "
          f"(expect {'0 (legit wipe)' if expected_terr_empty else 'fallback ghost (map lost)'}) "
          f"→ {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    ok1 = _run_case(wipe_map=False, expected_terr_empty=True)   # the 90a7cac fix
    ok2 = _run_case(wipe_map=True, expected_terr_empty=False)   # H35k protection intact
    print("\nP0-2 snapshot atomicity:", "ALL PASS" if (ok1 and ok2) else "FAILED")
    sys.exit(0 if (ok1 and ok2) else 1)
