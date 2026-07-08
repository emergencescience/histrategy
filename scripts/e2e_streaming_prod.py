#!/usr/bin/env python3
"""Production E2E for streaming turn resolution (HISTRATEGY_STREAMING=1).

Verifies against the live Railway histrategy server:
 1. command() returns narrative_pending=true + settled state, and returns FAST
    (state settlement ~10s, NOT waiting for the ~22s narrative).
 2. GET /api/rooms/{id}/narrative-live-stream streams chunks then [DONE].
 3. The streamed narrative is persisted to the DB (visible via /turns).
 4. (optional) orchestrator proxy passes the SSE through (not 403).
"""
import json
import sys
import time
import urllib.request

BASE = "https://histrategy-production.up.railway.app"
UA = "Hermes-Agent/1.0"


def api(method, path, body=None, timeout=120):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data:
        req.add_header("Content-Type", "application/json")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read())
    return payload, time.time() - t0


def stream_sse(path, timeout=90):
    """Consume an SSE endpoint; return (chunks, saw_done, elapsed, first_chunk_dt)."""
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "text/event-stream")
    chunks, saw_done, err = [], False, None
    t0 = time.time()
    first_dt = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                saw_done = True
                break
            try:
                chunk = json.loads(payload)
            except Exception:
                chunk = payload
            if isinstance(chunk, dict) and "error" in chunk:
                err = chunk["error"]
                continue
            if first_dt is None:
                first_dt = time.time() - t0
            chunks.append(chunk)
    return chunks, saw_done, time.time() - t0, first_dt, err


def main():
    print("=" * 60)
    print("PRODUCTION E2E — streaming turn resolution")
    print("=" * 60)

    # 1) Start game
    print("\n[1] POST /api/single-player/start (three-kingdoms / shu / zh)")
    r, dt = api("POST", "/api/single-player/start",
                {"faction": "shu", "scenario": "three-kingdoms", "lang": "zh"})
    if r.get("ok") is False:
        print(f"  ✗ start failed: {r}")
        sys.exit(1)
    game_id = r["game_id"]
    intro_nar = r.get("intro", {}).get("narrative", "")
    print(f"  ✓ game_id={game_id}  ({dt:.1f}s)  intro={len(str(intro_nar))} chars")

    # 2) Submit command — expect fast return + narrative_pending
    decision = "励精图治，招募新兵，巩固荆州防务，遣使联络孙权共御曹操。"
    print(f"\n[2] POST /api/single-player/{{id}}/command  decision={decision[:24]}…")
    r, dt = api("POST", f"/api/single-player/{game_id}/command", {"decision": decision, "lang": "zh"})
    pending = r.get("narrative_pending")
    nar = r.get("narrative", "")
    streaming_flag = r.get("_debug", {}).get("streaming")
    fs = r.get("faction_status", {})
    print(f"  command returned in {dt:.1f}s")
    print(f"    narrative_pending = {pending}")
    print(f"    _debug.streaming  = {streaming_flag}")
    print(f"    narrative len     = {len(str(nar))} (expect ~0 in streaming)")
    print(f"    year/season/turn  = {r.get('year')}/{r.get('season')}/{r.get('turn')}")
    print(f"    faction troops    = {fs.get('troops') or fs.get('military')}, "
          f"treasury={fs.get('treasury')}, food={fs.get('food')}")
    print(f"    npc_actions       = {len(r.get('npc_actions', []))}")
    print(f"    new_suggestions   = {len(r.get('new_suggestions', []))}")

    ok_pending = pending is True
    ok_fast = dt < 22  # narrative alone is ~22s; state settlement is ~10s
    ok_empty = len(str(nar)) == 0
    ok_state = bool(fs)
    print(f"  {'✓' if ok_pending else '✗'} narrative_pending is True")
    print(f"  {'✓' if ok_fast else '✗'} returned before narrative would ({dt:.1f}s < 22s)")
    print(f"  {'✓' if ok_empty else '✗'} narrative empty (deferred)")
    print(f"  {'✓' if ok_state else '✗'} state settled (faction_status present)")

    # 3) Consume SSE stream
    print(f"\n[3] GET /api/rooms/{{id}}/narrative-live-stream (SSE)")
    chunks, saw_done, sdt, first_dt, err = stream_sse(f"/api/rooms/{game_id}/narrative-live-stream")
    full = "".join(str(c) for c in chunks)
    print(f"  stream done in {sdt:.1f}s, first chunk @ {first_dt}s, {len(chunks)} chunks, {len(full)} chars")
    print(f"    saw [DONE] = {saw_done}   error = {err}")
    print(f"    preview: {full[:180]!r}")
    ok_chunks = len(chunks) > 0 and len(full) > 40
    ok_done = saw_done
    ok_multichunk = len(chunks) > 1  # true token streaming yields many chunks
    print(f"  {'✓' if ok_chunks else '✗'} received narrative content")
    print(f"  {'✓' if ok_done else '✗'} stream terminated with [DONE]")
    print(f"  {'✓' if ok_multichunk else '⚠'} multiple chunks (token streaming): {len(chunks)}")

    # 4) Verify persistence — narrative written back to DB
    print(f"\n[4] GET /api/rooms/{{id}}/turns  (verify narrative persisted)")
    time.sleep(2)
    t, _ = api("GET", f"/api/rooms/{game_id}/turns")
    turns = t.get("turns", [])
    persisted = ""
    if turns:
        nr = turns[-1].get("narratives", {})
        if isinstance(nr, str):
            try:
                nr = json.loads(nr)
            except Exception:
                nr = {"global": nr}
        persisted = nr.get("global", "") or (next((v for k, v in nr.items() if not k.startswith("_") and v), "") if isinstance(nr, dict) else "")
    print(f"    turns in DB = {len(turns)}, latest persisted narrative = {len(str(persisted))} chars")
    print(f"    preview: {str(persisted)[:180]!r}")
    ok_persist = len(str(persisted)) > 40
    print(f"  {'✓' if ok_persist else '✗'} narrative persisted to DB (reload/replay works)")

    # Summary
    print("\n" + "=" * 60)
    checks = {
        "narrative_pending=True": ok_pending,
        "command fast (<22s)": ok_fast,
        "narrative deferred (empty)": ok_empty,
        "state settled": ok_state,
        "SSE streamed content": ok_chunks,
        "SSE [DONE]": ok_done,
        "narrative persisted to DB": ok_persist,
    }
    for k, v in checks.items():
        print(f"  {'✓ PASS' if v else '✗ FAIL'}  {k}")
    allok = all(checks.values())
    print("=" * 60)
    print("RESULT:", "✅ ALL PASS" if allok else "❌ SOME FAILED")
    print(f"game_id for reference: {game_id}")
    sys.exit(0 if allok else 2)


if __name__ == "__main__":
    main()
