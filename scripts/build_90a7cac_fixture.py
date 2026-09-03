#!/usr/bin/env python3
"""Assemble anonymized playtest fixture from exported production room files.

Sources (files produced by \\copy ... WITH CSV from the production histrategy DB):
  /tmp/90a7cac_room.csv     — 1 row (jsonb object)
  /tmp/90a7cac_turns.csv    — 24 quarter_turn rows
  /tmp/90a7cac_states.csv   — 123 game_state rows

Output: tests/fixtures/rooms/90a7cac_cao_24q.json

PRIVACY: host_user_id, participation rows, and llm_call_log are NOT exported.
The player's in-game decision text is kept (fictional game content, no personal
data) but the fixture must NEVER be pushed to origin/main — local regression
only.
"""
import csv
import json
import os

def _load_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return [json.loads(r[0]) for r in csv.reader(f)]

room = _load_csv("/tmp/90a7cac_room.csv")[0]
turns = _load_csv("/tmp/90a7cac_turns.csv")
states = _load_csv("/tmp/90a7cac_states.csv")

# strip production-internal noise
for k in ("id",):
    room.pop(k, None)
# pending NPC pre-bakes are megabytes of noise; keep only occupant_type
for slot in (room.get("slots") or {}).values():
    for k in ("pending_decision", "pending_commands"):
        slot.pop(k, None)

fixture = {
    "_meta": {
        "source": "production room 90a7cac (three-kingdoms v3, cao=human)",
        "exported": "2026-09-03",
        "privacy": "anonymized — no user identifiers, no participation, no llm logs",
        "usage": "LOCAL-ONLY regression fixture. NEVER push to origin/main.",
        "known_issues": [
            "Q16 cao loses jiangxia with no capture event (stalemate only)",
            "Q21 cao regains jiangxia with no capture event (佯攻僵持 narrated)",
            "Q20 cao -19381 troops in one quarter with EMPTY battle_results",
            "Q6-Q23 cao treasury<10k for 18 consecutive quarters (broke_spiral)",
            "Q2-Q24 shu at 0 territories (zombie exile)",
        ],
    },
    "room": room,
    "states": states,
    "turns": turns,
}

out = "/opt/data/repos/histrategy/tests/fixtures/rooms/90a7cac_cao_24q.json"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump(fixture, f, ensure_ascii=False)
print(f"fixture written: {out} ({os.path.getsize(out):,} bytes)")
print(f"human faction: {[k for k, v in (room.get('slots') or {}).items() if v.get('occupant_type') == 'human']}")
print(f"turns: {len(turns)}, states: {len(states)}")
