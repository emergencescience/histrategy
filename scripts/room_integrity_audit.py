#!/usr/bin/env python3
"""Room Integrity Audit (RIA) — deterministic invariant checks over an exported room.

Cures the "every real room discovers a new problem" meta-issue: instead of
finding bugs only when a human plays, export any production room and run this
audit. It flags the recurring bug families as DATA-INVARIANT violations:

  C1 invisible_transfer   — territory set changed but no battle/capture event
                            names that territory (ghost loss / ghost gain).
  C2 narrative_capture_mismatch — LLM battle_results claims capture(s) with no
                            matching state gain, OR state gained with no claim.
  C3 troop_cliff          — >10% single-quarter troop drop with no battle event
                            naming that faction (desertion cliff / mis-executed
                            disband / semantic inversion).
  C4 broke_spiral         — >=6 consecutive quarters treasury<10k AND troops
                            flat/declining (economy death spiral).
  C5 zombie_faction       — 0 territories for >=8 consecutive quarters (exile is
                            by-design; flagged INFO so humans decide).

Input: fixture JSON built from production DB (see assemble instructions in the
fixture header) — {room, states:[{quarter_number,faction_id,treasury,troops,
morale,territories:[{id,...}]}], turns:[{quarter_number, macro_delta:{...}}]}.

Deterministic — no LLM, no network. Exit code 0 even when findings exist
(report is the artifact); use --fail to exit 1 on any ERROR finding.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict


def _terr_ids(territories) -> set[str]:
    if not territories:
        return set()
    if isinstance(territories, dict):  # stray object form
        territories = territories.get("territories", [])
    ids = set()
    for t in territories:
        if isinstance(t, str):
            ids.add(t)
        elif isinstance(t, dict):
            ids.add(t.get("id") or t.get("name") or "")
    return {i for i in ids if i}


def _battle_events(turn) -> list[dict]:
    md = (turn or {}).get("macro_delta") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            return []
    if not isinstance(md, dict):
        return []
    br = md.get("battle_results") or []
    return br if isinstance(br, list) else []


def audit(room: dict, states: list[dict], turns: list[dict]) -> dict:
    findings: list[dict] = []
    n = lambda kind, sev, q, fid, msg: findings.append(
        {"kind": kind, "severity": sev, "quarter": q, "faction": fid, "msg": msg}
    )

    # group states by quarter
    by_q: dict[int, dict[str, dict]] = defaultdict(dict)
    for s in states:
        by_q[int(s["quarter_number"])][s["faction_id"]] = s
    quarters = sorted(by_q)
    turns_by_q = {int(t["quarter_number"]): t for t in turns}

    factions = sorted({f for q in by_q.values() for f in q})
    for fid in factions:
        prev_ids: set[str] | None = None
        prev_treasury: float | None = None
        prev_troops: int | None = None
        broke_run, zero_run = 0, 0
        for q in quarters:
            st = by_q[q].get(fid)
            if not st:
                continue
            ids = _terr_ids(st.get("territories"))
            treasury = st.get("treasury") or 0
            troops = st.get("troops") or 0
            cur = turns_by_q.get(q)
            nxt = turns_by_q.get(q + 1)
            events = _battle_events(cur) + _battle_events(nxt)

            if prev_ids is not None and ids != prev_ids:
                gained, lost = ids - prev_ids, prev_ids - ids
                for t in lost:
                    hits = [e for e in events if e.get("location") == t]
                    claimed = [e for e in hits if e.get("territory_captured")
                               and e.get("attacker") != fid]
                    if not any(e.get("result") in ("attack_win", "rout",
                                                   "capture", "defender_surrendered")
                               or e.get("territory_captured") for e in hits):
                        n("invisible_transfer", "ERROR", q, fid,
                          f"失去 {t} 但战役记录无对应事件: {[e.get('result') for e in hits] or '无战役'}")
                for t in gained:
                    hits = [e for e in events if e.get("location") == t]
                    if not any(e.get("territory_captured") and e.get("attacker") == fid
                               for e in hits):
                        n("invisible_transfer", "ERROR", q, fid,
                          f"获得 {t} 但无 capture 战役记录: {[e.get('result') for e in hits] or '无战役'}")

            # narrative capture claims vs actual gains (count at this boundary)
            if prev_ids is not None and cur:
                claims = [e for e in _battle_events(cur)
                          if e.get("territory_captured")]
                real_gains = sum(1 for _ in (ids - prev_ids))
                if claims and real_gains == 0:
                    n("narrative_capture_mismatch", "WARN", q, fid,
                      f"叙事声称 {len(claims)} 次攻陷但领土未变: "
                      f"{[e.get('location') for e in claims]}")
                if real_gains and not any(e.get("territory_captured")
                                          and e.get("attacker") == fid
                                          for e in _battle_events(cur)):
                    pass  # already flagged as invisible gain above

            # troop cliff
            if prev_troops and troops is not None:
                d = troops - prev_troops
                if prev_troops and d < -0.10 * prev_troops:
                    me = [e for e in _battle_events(cur)
                          if fid in (e.get("attacker"), e.get("defender"))]
                    if not me:
                        n("troop_cliff", "WARN", q, fid,
                          f"兵力单季 -{abs(d):,} ({d / prev_troops * 100:.1f}%) 无战役记录")

            # broke spiral
            shrinking = prev_troops is not None and troops <= prev_troops
            if treasury < 10000 and (prev_troops is None or shrinking):
                broke_run += 1
            else:
                broke_run = 0
            if broke_run == 6:
                n("broke_spiral", "ERROR", q, fid,
                  "连续 6+ 季 国库<1万 且兵力无增长 — 经济死亡螺旋")
            elif broke_run > 6:
                pass  # already flagged at 6

            # zombie
            if len(ids) == 0:
                zero_run += 1
            else:
                zero_run = 0
            if zero_run == 8:
                n("zombie_faction", "INFO", q, fid,
                  "连续 8+ 季 0 领土 (流亡军 by-design，人工确认是否僵死)")

            prev_ids, prev_treasury, prev_troops = ids, treasury, troops

    return {"quarters": quarters, "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", help="path to exported room JSON")
    ap.add_argument("--fail", action="store_true",
                    help="exit 1 if any ERROR finding")
    args = ap.parse_args()

    with open(args.fixture) as f:
        data = json.load(f)
    result = audit(data.get("room") or {}, data.get("states") or [],
                   data.get("turns") or [])
    errs = [x for x in result["findings"] if x["severity"] == "ERROR"]
    warns = [x for x in result["findings"] if x["severity"] == "WARN"]
    infos = [x for x in result["findings"] if x["severity"] == "INFO"]

    print(f"房间完整性审计 (Room Integrity Audit)")
    print(f"回合数: {result['quarters'][0]}–{result['quarters'][-1]}")
    print(f"发现: {len(errs)} ERROR / {len(warns)} WARN / {len(infos)} INFO\n")
    for x in errs + warns + infos:
        print(f"[{x['severity']:>5}] Q{x['quarter']:>3} {x['faction']:<10} "
              f"{x['kind']}: {x['msg']}")

    out = args.fixture.replace(".json", "_ria_report.json")
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入 {out}")
    return 1 if (args.fail and errs) else 0


if __name__ == "__main__":
    sys.exit(main())
