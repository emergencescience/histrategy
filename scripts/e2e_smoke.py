#!/usr/bin/env python3
"""
E2E smoke test for Histrategy — validates core game loop works end-to-end.

Tests:
  1. Create a new single-player room (three-kingdoms scenario)
  2. Send a command and verify turn completes
  3. Check faction strength doesn't go to 0 (regression test for TurnController bug)
  4. Verify narrative is returned in correct language

Usage:
  HISTRATEGY_E2E_TOKEN=<jwt> python scripts/e2e_smoke.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

API_BASE = os.environ.get("HISTRATEGY_API", "https://histrategy-production.up.railway.app")
# The orchestrator proxies /games/histrategy/api/ to histrategy
ORCH_BASE = os.environ.get("ORCH_BASE", "https://api.emergence.science")
TOKEN = os.environ.get("HISTRATEGY_E2E_TOKEN", "")

if not TOKEN:
    print("❌ Set HISTRATEGY_E2E_TOKEN env var (JWT for yulin.shi.app or test account)")
    sys.exit(1)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}",
}


def api(path: str, method="GET", body=None):
    url = f"{ORCH_BASE}/games/histrategy{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        return e.code, {"error": body}


def test_create_room():
    """Test 1: Create a single-player room."""
    print("📋 Test 1: Create room...")
    status, data = api(
        "/api/single-player/room",
        method="POST",
        body={
            "scenario": "three-kingdoms",
            "faction": "shu",
            "lang": "zh",
        },
    )
    if status not in (200, 201):
        print(f"  ❌ Failed: {status} {data}")
        return None
    room_id = data.get("room_id") or data.get("game_id") or data.get("id")
    print(f"  ✅ Room created: {room_id} | year={data.get('year')} turn={data.get('turn')}")
    return room_id


def test_send_command(room_id: str):
    """Test 2: Send a command and verify turn completes."""
    print(f"📋 Test 2: Send command to {room_id}...")
    status, data = api(
        f"/api/single-player/{room_id}/command",
        method="POST",
        body={
            "decision": "发展农业，休养生息",
            "lang": "zh",
        },
    )
    if status != 200:
        print(f"  ❌ Failed: {status} {data}")
        return None
    print(f"  ✅ Command accepted: turn={data.get('turn')} year={data.get('year')}")
    return data


def test_troops_not_zero(data: dict):
    """Test 3: Regression — faction strength must not be 0."""
    print("📋 Test 3: Check faction strength > 0...")
    fs = data.get("faction_status", {})
    strength = fs.get("strength", 0)
    print(f"  Strength: {strength}")
    if strength <= 0:
        print(f"  ❌ FAIL: strength = {strength} — TurnController zeroing bug!")
        return False
    if strength < 500:
        print(f"  ⚠️ WARNING: strength {strength} is suspiciously low")
    else:
        print(f"  ✅ OK: strength {strength} > 0")
    return True


def test_narrative_language(data: dict):
    """Test 4: Narrative should be in Chinese."""
    print("📋 Test 4: Check narrative language...")
    narrative = data.get("narrative", "")
    if not narrative:
        # Streaming mode — narrative may be deferred
        after = data.get("aftermath", "")
        if after:
            print(f"  ✅ Aftermath present ({len(after)} chars)")
            return True
        print("  ⚠️ No narrative or aftermath — may be streaming mode")
        return True
    # Check for Chinese characters
    chinese_chars = sum(1 for c in narrative if '\u4e00' <= c <= '\u9fff')
    if chinese_chars > 10:
        print(f"  ✅ Narrative has {chinese_chars} Chinese chars")
        return True
    print(f"  ⚠️ Only {chinese_chars} Chinese chars — possible English output")
    return False


def test_second_turn(room_id: str):
    """Test 5: Run a second turn — regression for cumulative damage."""
    print(f"📋 Test 5: Second turn on {room_id}...")
    status, data = api(
        f"/api/single-player/{room_id}/command",
        method="POST",
        body={
            "decision": "招兵买马，扩充军备",
            "lang": "zh",
        },
    )
    if status != 200:
        print(f"  ❌ Failed: {status} {data}")
        return None

    fs = data.get("faction_status", {})
    strength = fs.get("strength", 0)
    print(f"  Turn {data.get('turn')}: strength={strength}")
    if strength <= 0:
        print(f"  ❌ FAIL: strength dropped to {strength} in 2 turns!")
        return False
    print(f"  ✅ Second turn OK")
    return True


def test_shared_room_narrative(room_id: str):
    """Test 6: Publish room and verify shared page narrative is clean markdown.

    Regression: _npc_actions stored as JSON strings by histrategy DB
    were being rendered as raw JSON on the shared page. Orchestrator
    must JSON-parse the string and return clean markdown.
    """
    print(f"📋 Test 6: Shared room narrative for {room_id}...")

    # Step A: Publish the room
    status, pub_data = api(
        f"/api/rooms/{room_id}/publish",
        method="PATCH",
        body={"public": True},
    )
    if status != 200:
        print(f"  ❌ Publish failed: {status} {pub_data}")
        return False
    verified = pub_data.get("verified", False)
    print(f"  {'✅' if verified else '⚠️'} Publish {'verified' if verified else 'accepted'}: is_public={pub_data.get('is_public')}")

    # Step B: Fetch shared page
    shared_url = f"{ORCH_BASE}/games/histrategy/shared/{room_id}"
    req = urllib.request.Request(shared_url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            shared = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"  ❌ Shared fetch failed: {e.code} {body}")
        return False

    # Step C: Verify narrative is NOT a JSON array string
    narrative = shared.get("narrative", "")
    if not narrative:
        print(f"  ❌ narrative is empty")
        return False
    if narrative.strip().startswith("["):
        print(f"  ❌ narrative is raw JSON array — not parsed!")
        print(f"     First 150: {narrative[:150]}")
        return False

    chinese_chars = sum(1 for c in narrative if '\u4e00' <= c <= '\u9fff')
    print(f"  ✅ narrative: {len(narrative)} chars, {chinese_chars} Chinese chars, starts with: {narrative[:60].strip()}")

    # Step D: Verify narratives.global exists
    narratives = shared.get("narratives", {})
    global_n = narratives.get("global", "")
    if not global_n:
        print(f"  ❌ narratives.global is missing or empty")
        return False
    if global_n.strip().startswith("["):
        print(f"  ❌ narratives.global is raw JSON array")
        return False
    print(f"  ✅ narratives.global: {len(global_n)} chars")

    return True


def main():
    print("=" * 60)
    print("Histrategy E2E Smoke Test")
    print(f"API: {ORCH_BASE}")
    print(f"Token: {TOKEN[:20]}...")
    print("=" * 60)

    results = {}

    # Test 1
    room_id = test_create_room()
    results["create_room"] = room_id is not None
    if not room_id:
        print("\n❌ Cannot continue — room creation failed")
        return 1

    # Test 2
    turn1 = test_send_command(room_id)
    results["send_command"] = turn1 is not None
    if not turn1:
        print("\n❌ Cannot continue — command failed")
        return 1

    # Test 3
    results["troops_not_zero"] = test_troops_not_zero(turn1)

    # Test 4
    results["narrative_lang"] = test_narrative_language(turn1)

    # Test 5
    results["second_turn"] = test_second_turn(room_id)

    # Test 6 — shared room narrative (regression check for _npc_actions JSON parsing)
    results["shared_narrative"] = test_shared_room_narrative(room_id)

    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
