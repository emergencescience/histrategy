"""Quick multiplayer E2E test — two players, one room, 2 turns."""
import os, sys, json, time, urllib.request, urllib.error

os.environ["HISTRATEGY_SYMMETRIC"] = "1"
os.environ["HISTRATEGY_DATA_DIR"] = "/tmp/ht_mp_e2e"
for k in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
    os.environ.pop(k, None)

BASE = "http://localhost:8765"

def post(path, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def get(path):
    return post(path)

# ── Start server ──
import subprocess
import threading

def run_server():
    import uvicorn
    from histrategy.server.api import create_app
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2)

try:
    # 1. Create room
    r = post("/api/rooms", {"scenario": "207", "faction_ids": ["cao", "shu"]})
    assert r["ok"], f"Create room failed: {r}"
    room_id = r["room_id"]
    print(f"Room created: {room_id}")

    # 2. Player 1 joins as cao
    r = post(f"/api/rooms/{room_id}/join", {"faction_id": "cao", "user_id": "p1"})
    assert r["ok"], f"P1 join failed: {r}"
    print("P1 joined as cao")

    # 3. Player 2 joins as shu
    r = post(f"/api/rooms/{room_id}/join", {"faction_id": "shu", "user_id": "p2"})
    assert r["ok"], f"P2 join failed: {r}"
    print("P2 joined as shu")

    # 4. Start game
    r = post(f"/api/rooms/{room_id}/start")
    assert r["ok"], f"Start failed: {r}"
    print(f"Game started: humans={r.get('humans')}, ai={r.get('ai_npcs')}")

    # 5. Both submit decisions
    r1 = post(f"/api/rooms/{room_id}/decide", {"faction_id": "cao", "user_id": "p1", "decision": "南征新野，进攻刘备"})
    print(f"P1 submit: {r1.get('status')}")

    r2 = post(f"/api/rooms/{room_id}/decide", {"faction_id": "shu", "user_id": "p2", "decision": "三顾茅庐，请诸葛亮出山"})
    print(f"P2 submit: {r2.get('status')}")

    # 6. Check status (should be resolved now)
    time.sleep(1)
    s1 = get(f"/api/rooms/{room_id}/status?faction_id=cao")
    s2 = get(f"/api/rooms/{room_id}/status?faction_id=shu")
    print(f"Phase: {s1.get('phase')}, Quarter: {s1.get('quarter')}")
    print(f"Cao narrative: {s1.get('narrative', '')[:80]}...")
    print(f"Shu narrative: {s2.get('narrative', '')[:80]}...")

    # 7. Turn 2
    r1 = post(f"/api/rooms/{room_id}/decide", {"faction_id": "cao", "user_id": "p1", "decision": "如果新野已克，进军襄阳"})
    r2 = post(f"/api/rooms/{room_id}/decide", {"faction_id": "shu", "user_id": "p2", "decision": "联合孙权，共抗曹操"})
    time.sleep(1)
    s1 = get(f"/api/rooms/{room_id}/status?faction_id=cao")
    print(f"Turn 2 — Phase: {s1.get('phase')}, Quarter: {s1.get('quarter')}")

    print("\n✅ ALL MULTIPLAYER TESTS PASSED")

except Exception as e:
    print(f"\n❌ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
