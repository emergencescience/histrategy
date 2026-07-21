#!/usr/bin/env python3
"""Playtest: Zheng (nanming) 10 turns — headless, deterministic V3 engine.

Usage:
    cd /opt/data/repos/histrategy
    uv run python scripts/playtest_zheng_10.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip().strip("'\"").strip()
                env[key] = val
    return env


def start_server(host: str, port: int, data_dir: str, env_vars: dict[str, str]):
    for k, v in env_vars.items():
        os.environ[k] = v
    os.environ["HISTRATEGY_ENGINE"] = "v3"
    os.environ["HISTRATEGY_DATA_DIR"] = data_dir
    os.environ["LLM_MODEL"] = "deepseek-v4-flash"
    os.environ["HISTRATEGY_OFFLINE"] = "1"  # No LLM calls

    import logging
    logging.basicConfig(level=logging.WARNING)

    import uvicorn
    from histrategy.server.api import create_app

    app = create_app(llm_provider="deepseek")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    env = load_env(Path("/opt/data/.env"))
    env.update(load_env(REPO / ".env"))
    api_key = env.get("DEEPSEEK_API_KEY", "")

    port = find_free_port()
    host = "127.0.0.1"
    data_dir = f"/tmp/histrategy_playtest_{int(time.time())}"
    os.makedirs(data_dir, exist_ok=True)

    print(f"🚀 Starting histrategy server on {host}:{port}")
    print(f"   data_dir: {data_dir}")
    t = threading.Thread(target=start_server, args=(host, port, data_dir, env), daemon=True)
    t.start()

    client = httpx.Client(base_url=f"http://{host}:{port}", timeout=30)
    for _ in range(30):
        try:
            r = client.get("/api/health")
            if r.status_code == 200:
                print("✅ Server ready")
                break
        except Exception:
            time.sleep(1)
    else:
        print("❌ Server failed to start")
        sys.exit(1)

    # ── Create room: Zheng as human, others as AI ──
    print("\n📋 Creating room: nanming / zheng player / en")
    r = client.post("/api/rooms", json={
        "scenario": "nanming",
        "pre_assigned": {"zheng": "TestPlayer"},
        "metadata": {"lang": "en"},
    })
    if r.status_code != 200:
        print(f"❌ Create failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    if not data.get("ok"):
        print(f"❌ Create failed: {data}")
        sys.exit(1)

    room_id = data["room_id"]
    print(f"✅ Room created: {room_id}")

    def get_status():
        r = client.get(f"/api/rooms/{room_id}/status")
        s = r.json()
        return s

    def show_faction_state(label, status_data):
        """Show faction state from status response."""
        factions = status_data.get("factions", {})
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"{'='*70}")
        print(f"  {'Faction':<18} {'Troops':>8} {'Food':>8} {'Treasury':>8} {'Terr':>5} {'Morale':>6}")
        print(f"  {'-'*60}")
        for fid, f in factions.items():
            troops = f.get("troops", f.get("strength", 0))
            food = f.get("food", 0)
            treasury = f.get("treasury", 0)
            n_terr = len(f.get("territories", []))
            morale = f.get("morale", 0)
            print(f"  {fid:<18} {troops:>8} {food:>8} {treasury:>8} {n_terr:>5} {morale:>6}")
        return factions

    status = get_status()
    show_faction_state("T0: Initial State", status)

    # ── Play turns ──
    actions = [
        "Consolidate Fujian and Guangdong defenses. Recruit 3000 militia from coastal villages. Send scouts north to assess Qing positions.",
        "Expand the fleet by recruiting 5000 sailors. Open trade negotiations with the Southern Ming — offer naval support in exchange for food supplies.",
        "Develop the harbors in Fujian and Guangdong. Continue building the fleet. Send envoys to the peasant army proposing a united front against the Qing.",
        "Fortify coastal positions. Build supply depots. Recruit 2000 more troops from Guangdong.",
        "Launch a naval raid up the coast to harass Qing supply lines. Demonstrate our naval superiority.",
        "Send 5000 troops to reinforce the Southern Ming's northern defenses. Show we are committed to the alliance.",
        "Expand maritime trade routes to Southeast Asia. Trade silk and ceramics for silver to fund the war effort.",
        "Continue naval blockade of Qing coastal positions. Send more food supplies to the Southern Ming.",
        "Coordinate with the Southern Ming and peasant army for a joint spring offensive. We will hold the coast and provide naval support.",
        "Launch the joint offensive: our fleet bombards Qing coastal positions while the peasant army attacks from the west and the Southern Ming pushes north.",
    ]

    for i, action in enumerate(actions[:10]):
        turn_num = i + 1
        print(f"\n\n🔄 Turn {turn_num}: {action[:70]}...")
        
        r = client.post(f"/api/rooms/{room_id}/decide", json={
            "faction_id": "zheng",
            "decision": action,
        }, timeout=60)
        
        if r.status_code != 200:
            print(f"  ❌ Turn failed: {r.status_code}")
            try:
                print(f"     {r.text[:200]}")
            except:
                pass
            break
        
        turn_data = r.json()
        if not turn_data.get("ok"):
            print(f"  ❌ Turn error: {turn_data.get('error', 'unknown')}")
            break
        
        # Show events  
        events = turn_data.get("events", [])
        for ev in events[:5]:
            ev_type = ev.get("type", "")
            if ev_type == "battle":
                result = ev.get("result", "?")
                loc = ev.get("location", "?")
                print(f"  ⚔️  Battle at {loc}: {result}")
            elif ev_type == "narrative":
                text = str(ev.get("text", ""))[:100]
                if text:
                    print(f"  📜 {text}")
        
        # Get and show status
        status = get_status()
        show_faction_state(f"Q{turn_num}", status)

    # Final
    print("\n\n" + "="*70)
    print("  FINAL STATE (after 10 turns)")
    print("="*70)
    final = get_status()
    factions = show_faction_state("Final", final)
    
    zheng = factions.get("zheng", {})
    qing = factions.get("qing", {})
    nanming = factions.get("nanming", {})
    nongminjun = factions.get("nongminjun", {})
    
    print(f"\n📊 Key metrics:")
    print(f"  Zheng troops:   {zheng.get('troops', '?')} (start: 35,000)")
    print(f"  Qing troops:    {qing.get('troops', '?')} (start: 120,000)")
    print(f"  Nanming troops: {nanming.get('troops', '?')} (start: 80,000)")
    print(f"  Peasant troops: {nongminjun.get('troops', '?')} (start: 90,000)")
    print(f"  Zheng food:     {zheng.get('food', '?')}")
    print(f"  Qing food:      {qing.get('food', '?')}")
    print(f"  Zheng terr:     {len(zheng.get('territories', []))}")
    print(f"  Qing terr:      {len(qing.get('territories', []))}")


if __name__ == "__main__":
    main()
