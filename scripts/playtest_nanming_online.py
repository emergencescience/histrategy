#!/usr/bin/env python3
"""Nanming online playtest — fixed with turn-completion polling."""
import json, time, sys, requests

API = "https://api.emergence.science/games/histrategy/api"
HEADERS = {"Content-Type": "application/json"}

# Only 3 strategies for quick re-run, 3 turns each
STRATEGIES = [
    ("稳健发展", [
        "将税率降至20%，推行屯田制。任命史可法为兵部尚书。派使者前往福建与郑成功结盟共同抗清。",
        "扩大屯田范围至全部领地，拨款8000金发展农业。在武昌和南昌加紧练兵，征募10000新兵。巩固长江防线。",
        "任命何腾蛟为湖广总督。在武昌集结兵力准备北伐。向农民军发出联合抗清的号召。征募15000新兵。",
    ]),
    ("联农抗清", [
        "派使者携重礼前往襄阳与农民军结盟。降低税率至25%。推行屯田制。在武昌加固防线。",
        "与农民军达成军事同盟！南明主力从南京北上取扬州、徐州。拨款6000金给前线。",
        "联军北伐！南明主力攻开封，农民军攻洛阳。郑成功水师封锁渤海湾。征募12000新兵。",
    ]),
    ("智取北京", [
        "不急于出兵，先离间清廷内部。派间谍散播多尔衮和豪格互相谋反的谣言。推行屯田制稳住内部。",
        "清廷内斗加剧！趁机征募20000新兵。与农民军和郑氏秘密商议瓜分方案。",
        "清廷内战爆发！三路出军：主力攻开封，偏师攻济南，水师封锁登州。农民军从西面攻西安。",
    ]),
]


def wait_for_turn(game_id: str, timeout: int = 180) -> dict:
    """Poll status until turn resolves (NPCs all submitted or phase changes)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{API}/rooms/{game_id}/status", headers=HEADERS, timeout=10)
            d = r.json()
            phase = d.get("phase", "")
            pending = d.get("pending", [])
            if phase != "waiting" or len(pending) == 0:
                return d
        except:
            pass
        time.sleep(3)
    return {}


def submit_and_wait(game_id: str, command: str) -> dict:
    """Submit command and wait for turn resolution."""
    t0 = time.time()
    resp = requests.post(
        f"{API}/single-player/{game_id}/command",
        json={"command": command},
        headers=HEADERS,
        timeout=300,
    )
    d = resp.json()
    elapsed = time.time() - t0

    # If turn resolved immediately, return
    fs = d.get("faction_status", {})
    territories = fs.get("territories", [])
    if territories and len(territories) > 0:
        return d

    # Otherwise poll for resolution
    print(f"      (提交 {elapsed:.0f}s, 等待NPC...)")
    status = wait_for_turn(game_id)
    if status:
        elapsed = time.time() - t0
        # Re-fetch the full status for faction data
        return {"_polled": True, "_elapsed": elapsed, "_status": status}
    return d


def main():
    results = []
    for strategy_name, decisions in STRATEGIES:
        print(f"\n{'='*60}")
        print(f"🎮 {strategy_name}")
        print(f"{'='*60}")

        # Create game
        r = requests.post(f"{API}/single-player/start", json={
            "faction": "nanming", "scenario": "nanming", "new": True, "lang": "zh"
        }, headers=HEADERS, timeout=120)
        game_id = (r.json().get("game_id") or r.json().get("room_id"))
        print(f"   房间: {game_id}")

        nanjing_lost = False
        beijing_taken = False

        for i, decision in enumerate(decisions):
            result = submit_and_wait(game_id, decision)
            fs = result.get("faction_status", {})

            # If we polled, extract from status
            if result.get("_polled"):
                status = result.get("_status", {})
                # Get faction data from power_ranking
                for p in status.get("power_ranking", []):
                    if p.get("faction_id") == "nanming":
                        fs = {
                            "strength": p.get("troops"),
                            "food": p.get("food"),
                            "morale": None,
                            "territories": list(range(p.get("territories", 0))),
                        }
                        break
                elapsed = result.get("_elapsed", 0)
            else:
                elapsed = (result.get("_debug", {}).get("elapsed") if isinstance(result.get("_debug"), dict) else 0) or 30

            troops = fs.get("strength") or fs.get("strength_actual", "?")
            food = fs.get("food", "?")
            morale = fs.get("morale", "?")
            territories = fs.get("territories", [])
            if territories and isinstance(territories[0], dict):
                tids = [t.get("id", "") for t in territories]
                tnames = [t.get("name", t.get("id", "?")) for t in territories]
            else:
                tids = territories if isinstance(territories, list) else []
                tnames = tids

            print(f"   Q{i+1}: 兵={troops} 粮={food} 民心={morale} 领地={len(territories)} {tnames[:5]} ({elapsed:.0f}s)")

            if "nanjing" not in tids:
                nanjing_lost = True
                print(f"   🔴 南京失守!")
                break
            if "beijing" in tids:
                beijing_taken = True
                print(f"   🟢 收复北京!")
                break

            time.sleep(3)

        # Publish
        share_url = ""
        try:
            pub = requests.patch(f"{API}/rooms/{game_id}/publish",
                json={"is_public": True}, headers=HEADERS, timeout=30).json()
            if pub.get("ok"):
                share_url = f"https://emergence.science/zh/play/histrategy/shared/{game_id}"
                print(f"   📎 {share_url}")
        except Exception as e:
            print(f"   ⚠️ 发布失败: {e}")

        results.append({
            "strategy": strategy_name, "room_id": game_id, "share_url": share_url,
            "nanjing_lost": nanjing_lost, "beijing_taken": beijing_taken,
        })

    # Summary
    print("\n\n" + "="*60)
    print("📊 RESULTS")
    print("="*60)
    for r in results:
        status = "🟢北京!" if r["beijing_taken"] else ("🔴南京失守" if r["nanjing_lost"] else "🟡守住")
        print(f"  {status} | {r['strategy']:8s} | {r['share_url']}")

    with open("/opt/data/repos/histrategy/logs/nanming_online_v2.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
