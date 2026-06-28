#!/usr/bin/env python3
"""
E2E Test: V3 Engine — English rome-triumvirate, 10 turns with Octavian.
Analyzes game_state, policy_state, LLM performance, and multi-language.

Usage:
    uv run python scripts/e2e_v3_test.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

# ── Add repo root to path ────────────────────────────────────
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
    """Start uvicorn in a daemon thread."""
    for k, v in env_vars.items():
        os.environ[k] = v
    os.environ["HISTRATEGY_ENGINE"] = "v3"
    os.environ["HISTRATEGY_DATA_DIR"] = data_dir
    os.environ["LLM_MODEL"] = "deepseek-v4-flash"

    import logging

    logging.basicConfig(level=logging.WARNING)

    import uvicorn
    from histrategy.server.api import create_app

    app = create_app(llm_provider="deepseek")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    # ── Load env ──────────────────────────────────────────────
    env = load_env(Path("/opt/data/.env"))
    env.update(load_env(REPO / ".env"))
    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("❌ DEEPSEEK_API_KEY not found")
        sys.exit(1)
    print(f"✅ DEEPSEEK_API_KEY loaded ({api_key[:8]}...{api_key[-4:]})")

    # ── Start server ──────────────────────────────────────────
    port = find_free_port()
    host = "127.0.0.1"
    data_dir = os.path.join(
        os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy")),
        f"e2e-v3-{uuid.uuid4().hex[:8]}",
    )

    t = threading.Thread(
        target=start_server,
        args=(host, port, data_dir, {"DEEPSEEK_API_KEY": api_key}),
        daemon=True,
    )
    t.start()

    base_url = f"http://{host}:{port}"
    client = httpx.Client(timeout=httpx.Timeout(180.0))

    # Health check
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            r = client.get(f"{base_url}/api/health")
            if r.is_success:
                print(f"✅ Server healthy at {base_url}")
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        print("❌ Server did not start in 60s")
        sys.exit(1)

    # ── Create English rome-triumvirate room ──────────────────
    print("\n📦 Creating room: rome-triumvirate, lang=en, Octavian=human")
    r = client.post(
        f"{base_url}/api/rooms",
        json={
            "scenario": "rome-triumvirate",
            "pre_assigned": {"octavian": "Player"},  # human
            "metadata": {"lang": "en"},
        },
        headers={"X-User-Id": "test-user"},
    )
    room_data = r.json()
    print(f"   Response: {json.dumps(room_data, indent=2, ensure_ascii=False)}")

    if not room_data.get("ok"):
        print(f"❌ Failed to create room: {room_data}")
        sys.exit(1)

    room_id = room_data["room_id"]
    print(f"   Room ID: {room_id}")

    # ── Start game ────────────────────────────────────────────
    print("\n🎮 Starting game...")
    r = client.post(f"{base_url}/api/rooms/{room_id}/start")
    start_data = r.json()
    print(f"   Response: {json.dumps(start_data, indent=2, ensure_ascii=False)[:500]}...")

    # ── Play 10 turns ─────────────────────────────────────────
    stats = []
    for turn in range(1, 11):
        print(f"\n{'='*50}")
        print(f"🔄 Turn {turn}/10")

        # Check status
        r = client.get(f"{base_url}/api/rooms/{room_id}/status")
        status = r.json()
        phase = status.get("phase", "unknown")
        qn = status.get("quarter_number", -1)
        print(f"   Phase: {phase}, Quarter: {qn}")
        if status.get("faction_status"):
            print(f"   Faction status: {status['faction_status']}")

        # Submit decision
        decisions = [
            f"Turn {turn}: Consolidate power in Rome, recruit soldiers, improve economy.",
            f"Turn {turn}: Expand territory eastward, build fortifications.",
            f"Turn {turn}: Secure alliances, develop infrastructure.",
            f"Turn {turn}: Train elite legions, increase tax collection.",
            f"Turn {turn}: Launch diplomatic missions to secure borders.",
            f"Turn {turn}: Invest in agriculture and trade routes.",
            f"Turn {turn}: Fortify key positions, raise new legions.",
            f"Turn {turn}: Exploit weaknesses in enemy territory.",
            f"Turn {turn}: Economic reforms and military modernization.",
            f"Turn {turn}: Strategic withdrawal to defensible positions.",
        ]
        decision = decisions[turn - 1]

        t0 = time.monotonic()
        r = client.post(
            f"{base_url}/api/rooms/{room_id}/decide",
            json={"faction_id": "octavian", "decision": decision},
            headers={"X-User-Id": "test-user"},
        )
        elapsed = time.monotonic() - t0
        result = r.json()
        ok = result.get("ok", False)
        error = result.get("error", "")
        narrative = result.get("narrative", "")[:200] if result.get("narrative") else ""

        print(f"   Decision submitted: {decision[:80]}...")
        print(f"   OK: {ok}, Elapsed: {elapsed:.1f}s")
        if error:
            print(f"   ❌ Error: {error}")
        if narrative:
            print(f"   Narrative: {narrative}...")

        stats.append(
            {
                "turn": turn,
                "ok": ok,
                "elapsed_s": round(elapsed, 1),
                "error": error,
                "phase": phase,
                "quarter_number": qn,
            }
        )

    # ── Collect data ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📊 COLLECTING DATA")
    print(f"{'='*60}")

    # 1. Game state
    print("\n─── GAME STATE ───")
    r = client.get(f"{base_url}/api/rooms/{room_id}/state")
    state = r.json()
    print(json.dumps(state, indent=2, ensure_ascii=False)[:3000])

    # 2. Turn history
    print("\n─── TURN HISTORY ───")
    r = client.get(f"{base_url}/api/rooms/{room_id}/turns")
    turns = r.json()
    print(f"   Count: {turns.get('count', 0)}")
    for t_data in turns.get("turns", []):
        qn = t_data["quarter_number"]
        deltas = t_data.get("turn_deltas", {})
        policies = t_data.get("policies", {})
        token_usage = t_data.get("token_usage", {})
        narratives = t_data.get("narratives", {})
        narrative_text = ""
        if isinstance(narratives, dict):
            narrative_text = narratives.get("global", "")[:150]
        print(f"\n   Q{qn}:")
        print(f"     Narrative: {narrative_text}...")
        print(f"     Deltas: {json.dumps({k: len(v) for k,v in deltas.items()}, ensure_ascii=False)}")
        print(f"     Policies: {json.dumps({k: list(v.keys()) for k,v in policies.items()}, ensure_ascii=False)}")
        if token_usage:
            print(f"     Token usage: {token_usage}")
        if deltas:
            for fid, dlist in deltas.items():
                print(f"     {fid}:")
                for d in dlist[:3]:
                    print(f"       {d['delta_type']}: {d['old_value']} → {d['new_value']} (Δ={d.get('delta', '?')})")

    # ── Analysis ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📈 ANALYSIS")
    print(f"{'='*60}")

    # Latency
    elapsed_times = [s["elapsed_s"] for s in stats if s["ok"]]
    success_count = sum(1 for s in stats if s["ok"])
    error_count = sum(1 for s in stats if not s["ok"])

    print(f"\n⏱️  LATENCY:")
    print(f"   Success: {success_count}/{len(stats)}")
    print(f"   Errors: {error_count}")
    if elapsed_times:
        print(f"   Min: {min(elapsed_times):.1f}s")
        print(f"   Max: {max(elapsed_times):.1f}s")
        print(f"   Avg: {sum(elapsed_times)/len(elapsed_times):.1f}s")

    # State analysis
    if state.get("factions"):
        print(f"\n🏛️  FINAL STATE:")
        for f in state["factions"]:
            print(f"   {f['faction_id']}: pop={f.get('population')}, troops={f.get('troops')}, "
                  f"food={f.get('food')}, treasury={f.get('treasury')}, morale={f.get('morale')}")
            if f.get("policies"):
                print(f"     Policies: {list(f['policies'].keys())}")

    # LLM performance
    print(f"\n🤖 LLM PERFORMANCE:")
    total_tokens = 0
    total_turns_with_llm = 0
    for t_data in turns.get("turns", []):
        tu = t_data.get("token_usage", {})
        if tu and tu.get("total_tokens", 0) > 0:
            total_tokens += tu["total_tokens"]
            total_turns_with_llm += 1
    if total_turns_with_llm > 0:
        print(f"   Turns with LLM calls: {total_turns_with_llm}/{turns.get('count', 0)}")
        print(f"   Total tokens: {total_tokens}")
        print(f"   Avg tokens/turn: {total_tokens/total_turns_with_llm:.0f}")

    # Language check
    print(f"\n🌐 LANGUAGE CHECK:")
    non_english_count = 0
    for t_data in turns.get("turns", []):
        narratives = t_data.get("narratives", {})
        if isinstance(narratives, dict):
            text = narratives.get("global", "")
        elif isinstance(narratives, str):
            text = narratives
        else:
            text = ""
        # Check for Chinese characters
        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in text)
        if has_chinese:
            non_english_count += 1
            print(f"   ⚠️  Q{t_data['quarter_number']}: Contains Chinese characters")
    if non_english_count == 0:
        print(f"   ✅ All narratives in English")

    # Policy state evolution
    print(f"\n📋 POLICY STATE EVOLUTION:")
    all_policies = set()
    for t_data in turns.get("turns", []):
        for fid, pols in t_data.get("policies", {}).items():
            all_policies.update(pols.keys())
    print(f"   Unique policies seen: {sorted(all_policies)}")

    client.close()
    print(f"\n✅ E2E test complete. Room ID: {room_id}")
    return room_id


if __name__ == "__main__":
    main()
