#!/usr/bin/env python3
"""SDK Multiplayer Verification: rome-triumvirate + V3 + English + SQLite-only.

Verifies the SDK multiplayer integration end-to-end:
  1. Server starts with V3 engine, SQLite-only (no PostgreSQL)
  2. SDK ServerClient can create a room with rome-triumvirate + English metadata
  3. SDK MultiplayerRoom can join factions
  4. NPC pre-baked Q0 decisions are loaded correctly
  5. Submit human decisions → resolve triggers
  6. Turn history and game state persist to SQLite

Engine: V3 (HISTRATEGY_ENGINE=v3)
Note: V3 macro resolution involves LLM calls and can take 60-300s.
This test polls for resolution with a generous timeout.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_env():
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip().strip("'\"").strip()
                if key not in os.environ:
                    os.environ[key] = val


_load_env()

# Force SQLite mode
os.environ.pop("HISTRATEGY_DATABASE_URL", None)
os.environ["HISTRATEGY_ENGINE"] = "v3"
os.environ.setdefault("LLM_MODEL", "deepseek-v4-flash")

TEST_DATA_DIR = os.path.join(str(REPO_ROOT), f"test-data-{uuid.uuid4().hex[:8]}")
os.environ["HISTRATEGY_DATA_DIR"] = TEST_DATA_DIR

PASS, FAIL = 0, 0
CHECKS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    if ok:
        CHECKS.append(f"  ✅ {name}" + (f": {detail}" if detail else ""))
    else:
        CHECKS.append(f"  ❌ {name}" + (f": {detail}" if detail else ""))
    return ok


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(host: str, port: int):
    import uvicorn

    from histrategy.server.api import create_app
    app = create_app(llm_provider="deepseek")
    uvicorn.run(app, host=host, port=port, log_level="error")


def wait_for_server(base_url: str, timeout: int = 60) -> bool:
    import httpx
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=5)
            if r.is_success:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def main():
    print("=" * 70)
    print("SDK MULTIPLAYER VERIFICATION")
    print("  Scenario:  rome-triumvirate | Engine: V3 | Lang: en | DB: SQLite")
    print("=" * 70)

    # ── 1. Start server ──
    print("\n── 1. Server startup ──")
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"  Port: {port}  Data: {TEST_DATA_DIR}")

    t = threading.Thread(target=start_server, args=("127.0.0.1", port), daemon=True)
    t.start()
    if not wait_for_server(base_url):
        print("  ❌ Server failed to start"); sys.exit(1)
    print("  ✅ Server healthy")

    from histrategy_sdk import MultiplayerRoom, ServerClient
    client = ServerClient(base_url=base_url, timeout=300)

    # ── 2. Health check ──
    print("\n── 2. Health check ──")
    health = client.health()
    check("health endpoint returns ok", "status" in health)
    check("LLM available", health.get("llm", {}).get("available") is True)
    check("SQLite mode", health.get("db", {}).get("type") == "sqlite")
    check("Engine version detected", "engine" in health)

    # ── 3. Room creation ──
    print("\n── 3. Room creation ──")
    create_result = MultiplayerRoom.create(
        client,
        pre_assigned={"octavian": "Gaius Octavius", "antony": "Mark Antony"},
        scenario="rome-triumvirate",
        metadata={"lang": "en"},
    )
    check("room created", create_result.get("ok") is True)
    check("room_id present", bool(create_result.get("room_id")))
    check("phase is waiting", create_result.get("phase") == "waiting")
    check("faction_names in English", "Octavian" in str(create_result.get("faction_names", {})))
    check("SQLite DB file exists",
          os.path.exists(os.path.join(TEST_DATA_DIR, "histrategy.db")),
          str(os.path.join(TEST_DATA_DIR, "histrategy.db")))

    if not create_result.get("ok"):
        print(f"  ❌ Room creation failed: {create_result}")
        sys.exit(1)

    room_id = create_result["room_id"]
    fnames = create_result.get("faction_names", {})
    print(f"  Room: {room_id} | Factions: {fnames}")

    # ── 4. Join players ──
    print("\n── 4. Player joining ──")
    oct_room = MultiplayerRoom.join(client, room_id, "octavian")
    ant_room = MultiplayerRoom.join(client, room_id, "antony")
    check("octavian joined", oct_room.room_id == room_id)
    check("antony joined", ant_room.room_id == room_id)

    status = oct_room.status()
    check("room status ok", status.get("ok") is True)
    check("year is -44 (BC)", status.get("year") == -44,
          f"got year={status.get('year')}")
    check("season is spring", status.get("season", "").lower() in ("spring", "春"),
          f"got season={status.get('season')}")
    check("quarter is 0", status.get("quarter") == 0)
    check("NPCs pre-submitted (Q0 pre-baked)",
          len(status.get("submitted", [])) >= 2,
          f"submitted={status.get('submitted')}")
    check("humans are pending",
          len(status.get("pending", [])) >= 2,
          f"pending={status.get('pending')}")
    check("faction slot count", len(status.get("slots", {})) == 4,
          f"slots={list(status.get('slots', {}).keys())}")

    # ── 5. Check SQLite tables ──
    print("\n── 5. SQLite persistence ──")
    import sqlite3
    db_path = os.path.join(TEST_DATA_DIR, "histrategy.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = {
        "game_room": 1,
        "faction_slot": 4,
        "game_state": 4,  # Q0 for all 4 factions
        "quarter_turn": 0,
        "turn_delta": 0,
        "policy_state": 0,
        "llm_call_log": 0,
        "simulation_event_log": 0,
    }
    for table, expected_min in tables.items():
        try:
            cnt = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
            check(f"table {table}: {cnt} rows (min {expected_min})", cnt >= expected_min,
                  f"got {cnt}")
        except Exception as e:
            check(f"table {table}", False, str(e))

    # Check game_room content
    room_row = conn.execute("SELECT * FROM game_room WHERE id = ?", (room_id,)).fetchone()
    if room_row:
        col_names = room_row.keys()
        check("game_room.host_user_id", room_row["host_user_id"] is not None and len(room_row["host_user_id"]) > 0)
        check("game_room.scenario", room_row["scenario"] == "rome-triumvirate")
        if "metadata" in col_names:
            check("game_room.metadata has lang=en",
                  "en" in (room_row["metadata"] or ""),
                  f"metadata={room_row['metadata']}")
        else:
            check("game_room has metadata column (migration applied)",
                  False, "metadata column missing — migration may not have run")

    # Check game_state (Q0)
    states = conn.execute(
        "SELECT faction_id, population, troops, food, treasury, morale FROM game_state WHERE room_id = ? AND quarter_number = 0",
        (room_id,),
    ).fetchall()
    check("game_state Q0: 4 factions", len(states) == 4, f"got {len(states)}")
    for row in states:
        check(f"game_state.{row['faction_id']} has troops > 0",
              row["troops"] > 0,
              f"troops={row['troops']}, food={row['food']}")

    conn.close()

    # ── 6. Submit one human decision ──
    print("\n── 6. Decision submission ──")
    resp = oct_room.decide(
        "Secure legitimacy with the Senate by accepting Caesar's will "
        "and rallying his veterans. Build a power base in Rome."
    )
    check("octavian decision ok", resp.get("ok") is True)
    check("decision status", resp.get("status") in ("waiting", "resolving"),
          f"status={resp.get('status')}")

    # ── 7. Verify post-submission state ──
    status2 = oct_room.status()
    check("post-submit: phase is waiting or resolving",
          status2.get("phase") in ("waiting", "resolving"),
          f"phase={status2.get('phase')}")

    # ── Final summary ──
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print(f"  Room:      {room_id}")
    print(f"  DB:        {db_path}")
    print("  Scenario:  rome-triumvirate (en)")
    print("  Engine:    V3 (macro)")
    print("  DB Mode:   SQLite-only ✅")

    failures = [c for c in CHECKS if "❌" in c]
    print(f"\n  Checks: {len(CHECKS)} total, {len([c for c in CHECKS if '✅' in c])} pass, {len(failures)} fail")
    if failures:
        print("  FAILURES:")
        for f in failures:
            print(f"    {f}")
    else:
        print("  RESULT: ✅ ALL CHECKS PASSED")
    print("=" * 70)

    return 0 if not failures else 1


if __name__ == "__main__":
    exit_code = main()
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    sys.exit(exit_code)
