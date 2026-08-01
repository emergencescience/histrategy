#!/usr/bin/env python3
"""Nanming 10-game playtest: find optimal strategy to defend Nanjing, retake Beijing.

Usage: python3 scripts/playtest_nanming_10.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, "/opt/data/repos/histrategy")
os.environ["HISTRATEGY_ENGINE"] = "v3"
os.environ["HISTRATEGY_SYMMETRIC"] = "1"
os.environ["HISTRATEGY_MACRO"] = "1"

# Load DOUBAO_API_KEY from ~/.hermes/.env
_env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.strip() not in os.environ:
                    os.environ[key.strip()] = val.strip()

# ── Strategy variants ──────────────────────────────────────────
STRATEGIES = [
    # (name, decisions_list)
    (
        "稳健发展",
        [
            "将税率降至20%，推行屯田制以增加粮食产出。任命史可法为兵部尚书主抓军务。派使者携重礼前往福建与郑成功结盟，共同对抗清军。",
            "扩大屯田范围至全部领地，拨款8000金给南京和杭州用于农具改良。在武昌和南昌加紧练兵，征募10000新兵。巩固长江防线。",
            "任命何腾蛟为湖广总督，堵胤锡为督师。在武昌集结兵力准备北伐。向农民军发出联合抗清的号召。",
            "三路北伐！主力从武昌攻襄阳，偏师从南京攻扬州，水师从杭州北上。请求郑成功从福建配合进攻。",
            "攻克襄阳后继续北上取洛阳、开封。命令史可法督师进攻山东。对农民军保持善意中立，共同抗清。",
        ],
    ),
    (
        "北伐急攻",
        [
            "立即北伐！调集全部兵力从武昌北上攻襄阳。任命史可法为征北大将军，何腾蛟为先锋。向农民军发出最后通牒要求合作。",
            "攻克襄阳！继续北上取南阳、洛阳。征募15000新兵补充前线。命令郑成功水师北上袭扰清军沿海。",
            "主力进攻开封，偏师从南京攻徐州。派使者赴成都与农民军结盟。拨款5000金修建前线堡垒。",
            "围攻洛阳！命令水师封锁黄河。征调全部领地壮丁补充兵力。向清廷发出檄文号召汉人起义。",
            "攻克洛阳后直取北京！集中所有兵力发动总攻。请求农民军从西面策应。此战定天下！",
        ],
    ),
    (
        "联农抗清",
        [
            "派使者携重礼前往襄阳与农民军结盟。降低税率至25%休养生息。推行屯田制增加粮产。在南阳和武昌加固防线。",
            "与农民军达成军事同盟！请求农民军从西面进攻清军。南明主力从南京北上取扬州、徐州。拨款6000金给前线。",
            "联军北伐！南明主力攻开封，农民军攻洛阳。郑成功水师封锁渤海湾。征募12000新兵。",
            "分进合击！三路大军分别攻开封、洛阳、济南。农民军从四川出汉中攻西安。水师切断清军粮道。",
            "围攻北京！南明主力从南面进攻，农民军从西面进攻，水师封锁海上。号召北方汉人起义响应。",
        ],
    ),
    (
        "海陆并进",
        [
            "推行海禁开放政策，拨款5000金扩建福州船厂。与郑成功达成协议共掌水师。在浙江和广东征募水兵8000人。降低税率至25%。",
            "水师北上袭扰山东半岛和辽东。陆军在武昌和南昌集结备战。推行屯田制确保军粮。向农民军示好但不结盟。",
            "海陆协同！水师进攻登州、莱州，陆军从南京北上取徐州。在南阳加固防线防止清军南下。征募10000新兵。",
            "扩大水师优势！占领登州后在山东建立前进基地。陆军继续北上攻济南、开封。农民军若愿意合作则可夹击清军。",
            "最终决战！水师封锁渤海，陆军从济南攻德州，从襄阳攻洛阳。两路合围北京。郑成功总领水师。",
        ],
    ),
    (
        "固守反攻",
        [
            "全力防守！在长江沿线所有城市修建堡垒。推行屯田制和军屯制确保粮食自给。派使者向农民军和郑氏示好。税收降至15%收买民心。",
            "继续巩固防御！在南昌、武昌、南京三城修建城墙。秘密训练20000新兵但不暴露。派出大量间谍潜入清军领地刺探情报。",
            "清军内部出现裂隙！利用间谍散布谣言离间清廷。完成新兵训练后在武昌秘密集结。等待清军内乱的最佳时机。",
            "清军内乱爆发！立即发动反攻！三路大军分别攻襄阳、南阳、开封。郑成功从海路进攻山东。农民军趁机北上。",
            "乘胜追击！攻克开封后继续北上取洛阳、济南。水师封锁黄河切断清军退路。号召被占领土汉人起义。光复北京在望！",
        ],
    ),
    (
        "经济优先",
        [
            "大力发展经济！降低税率至15%，推行屯田制和盐铁专卖增加收入。拨款10000金修建南京至杭州的商路。与郑成功签订贸易协定。",
            "继续经济建设！在全部领地开垦荒地增加粮产。拨款8000金发展手工业和商业。秘密在武昌建立军械所储备武器。",
            "经济基础稳固！国库充盈后开始大规模扩军。在武昌、南昌、南京三地征募共30000新兵。命工匠日夜赶制火器和甲胄。",
            "精锐已成！发动北伐！装备精良的南明新军从武昌出发攻襄阳。水师从长江入汉水配合作战。向农民军发出合作邀请。",
            "闪电战！利用装备优势快速攻克洛阳和开封。水师北上切断清军补给。集中所有精锐攻向北京。",
        ],
    ),
    (
        "外交孤立",
        [
            "推行强硬外交！向农民军和郑氏发出最后通牒要求臣服。拒绝臣服则视为敌人。降低税率至20%稳住内部民心。在边境集结兵力。",
            "农民军拒绝臣服！出兵攻取襄阳和南阳。同时向郑氏施压要求水师配合。征募10000新兵补充前线。",
            "先灭农民军再抗清！集中兵力攻成都消灭张献忠残部。对清军采取守势固守武昌和南阳。郑氏若不服则水师南下讨伐。",
            "农民军已灭！收编其残部获得大量兵员。立即转向北伐！主力从襄阳攻洛阳。水师从长江转入黄河。",
            "势如破竹！攻克洛阳后直取北京。郑氏水师封锁渤海。北方清军孤立无援，灭亡在即！",
        ],
    ),
    (
        "守江必守淮",
        [
            "放弃外围领地，将兵力集中在南京-武昌-南昌三角地带。在扬州、徐州建立前哨阵地。推行军屯制确保前线粮食供应。向农民军请求军事同盟。",
            "巩固江淮防线！在扬州和徐州加固城防。在武昌秘密训练水师和步兵。派出间谍潜入清军搜集情报。征募8000新兵。",
            "清军开始进攻徐州！调集主力增援。利用水师优势在淮河阻击清军。在敌后发动游击战破坏清军补给线。",
            "淮河大捷！清军主力被重创。立即转入反攻！从徐州北上攻济南。从武昌出兵攻南阳配合。农民军若愿意参战则攻西安。",
            "两路北伐！东路从济南攻德州，西路从南阳攻洛阳。水师沿大运河北上支援。目标：北京！",
        ],
    ),
    (
        "游击消耗",
        [
            "不正面决战，推行焦土游击战术。在清军可能进攻的路线上坚壁清野。派出多股小分队深入敌后破坏粮道和驿站。降低税率至20%维持民心。",
            "游击战初见成效！清军补给线被严重破坏。在敌后组织汉人起义配合。主力在武昌待机而动。继续训练新兵和储备物资。",
            "清军因补给不足开始撤退！抓住机会收复南阳和襄阳。派出更多游击队骚扰撤退清军。征募15000新兵扩大战果。",
            "全面反攻！游击队已成功瘫痪清军后勤。主力分三路北上：攻洛阳、攻济南、攻西安。号召全部汉人起义。",
            "清军全面溃退！乘胜追击收复全部失地。三路大军合围北京。郑氏水师封锁海上退路。一统天下！",
        ],
    ),
    (
        "智取北京",
        [
            "不急于出兵，先离间清廷内部。派间谍向多尔衮和豪格散播对方谋反的谣言。同时推行屯田制和减税政策稳住内部。在武昌秘密训练精锐。",
            "清廷内斗加剧！多尔衮和豪格两派剑拔弩张。趁此机会征募20000新兵。与农民军和郑氏秘密商议瓜分清廷领地的方案。",
            "清廷内战爆发！抓住千载难逢的机会！三路出军：主力攻开封，偏师攻济南，水师封锁登州。农民军从西面攻西安。",
            "清军内部分裂不堪一击！攻克开封和济南。继续北上取德州和保定。派使者招降清军将领。",
            "兵临北京城下！清廷残余势力困守孤城。农民军从西面赶到，郑氏水师封锁海上。劝降不成即发动总攻！",
        ],
    ),
]


@dataclass
class GameResult:
    name: str
    strategy: str
    room_id: str
    turns: list[dict] = field(default_factory=list)
    survived: bool = True
    nanjing_lost: bool = False
    beijing_captured: bool = False
    final_troops: int = 0
    final_food: int = 0
    final_pop: int = 0
    final_territories: int = 0


def run_game(strategy_name: str, decisions: list[str]) -> GameResult:
    """Run one nanming game with the given strategy."""
    from histrategy.engine.game import GameEngine
    from histrategy.llm.adapter import LLMAdapter

    llm = LLMAdapter()
    engine = GameEngine(llm=llm, scenario="nanming", new_game=True)
    engine.set_player_faction("nanming")

    ws = engine.world_state_v2
    faction = ws.factions["nanming"]
    initial_territories = list(faction.territories)

    result = GameResult(
        name=f"nanming-{strategy_name}",
        strategy=strategy_name,
        room_id=getattr(engine, "room_id", ""),
    )

    print(f"\n{'='*60}")
    print(f"🎮 Strategy: {strategy_name}")
    print(f"   初始: 兵力={faction.strength_actual}, 粮草={faction.food}, "
          f"人口={sum(getattr(ws.territories[t],'population',0) for t in faction.territories if t in ws.territories)}, "
          f"领地={len(initial_territories)}")
    print(f"{'='*60}")

    nanjing_lost = False
    beijing_captured = False

    for i, decision in enumerate(decisions):
        print(f"\n  Q{i+1}: {decision[:60]}...")
        t0 = time.time()

        try:
            turn_result = engine.process_turn(decision)
        except Exception as e:
            print(f"    ❌ Simulation failed: {e}")
            result.survived = False
            break

        elapsed = time.time() - t0
        ws = turn_result.get("world_state", engine.world_state_v2)
        if ws is None:
            ws = engine.world_state_v2
        faction = ws.factions.get("nanming") if ws else None
        if not faction or not getattr(faction, "is_active", True):
            print(f"    💀 南明灭亡！")
            result.survived = False
            break

        territories = list(faction.territories)
        population = sum(
            getattr(ws.territories[t], "population", 0)
            for t in territories
            if t in ws.territories
        )

        nans = turn_result.get("narratives", {})
        global_nar = str(nans.get("global", ""))[:120] if nans else ""

        turn_info = {
            "quarter": i + 1,
            "troops": faction.strength_actual,
            "food": faction.food,
            "treasury": faction.treasury,
            "population": population,
            "territories": len(territories),
            "territory_list": territories,
            "morale": getattr(faction, "morale_actual", 0),
            "elapsed": round(elapsed, 1),
        }
        result.turns.append(turn_info)

        # Check territory changes
        if "nanjing" not in territories:
            nanjing_lost = True
            print(f"    🔴 南京失守！")
        if "beijing" in territories:
            beijing_captured = True
            print(f"    🟢 收复北京！")

        print(f"    兵力={faction.strength_actual}, 粮草={faction.food}, "
              f"人口={population}, 领地={len(territories)}, "
              f"民心={getattr(faction,'morale_actual','?')}, "
              f"耗时={elapsed:.1f}s")

        if nanjing_lost or beijing_captured:
            break

    result.nanjing_lost = nanjing_lost
    result.beijing_captured = beijing_captured
    if faction:
        result.final_troops = faction.strength_actual
        result.final_food = faction.food
        result.final_pop = sum(
            getattr(ws.territories[t], "population", 0)
            for t in (list(faction.territories) if hasattr(faction, "territories") else [])
            if t in ws.territories
        )
        result.final_territories = len(list(faction.territories)) if hasattr(faction, "territories") else 0

    return result


def main():
    print("=" * 60)
    print("NANMING 10-GAME PLAYTEST")
    print("Goal: Defend Nanjing, Retake Beijing")
    print("=" * 60)

    results: list[GameResult] = []

    for strategy_name, decisions in STRATEGIES:
        try:
            r = run_game(strategy_name, decisions)
            results.append(r)
        except Exception as e:
            print(f"❌ Strategy '{strategy_name}' crashed: {e}")
            import traceback
            traceback.print_exc()

    # ── Summary ──
    print("\n\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)

    # Sort by: beijing captured first, then survived, then territories
    def sort_key(r: GameResult) -> tuple:
        return (
            not r.beijing_captured,  # Beijing captured = best
            not r.survived,           # Survived = better
            not r.nanjing_lost,       # Nanjing not lost = better
            -(r.final_territories),   # More territories = better
        )

    results.sort(key=sort_key)

    for i, r in enumerate(results):
        status = "🟢" if r.beijing_captured else ("🟡" if r.survived and not r.nanjing_lost else "🔴")
        print(f"\n{i+1}. {status} {r.strategy}")
        print(f"   存活: {'✅' if r.survived else '❌'} | "
              f"南京: {'🔴失守' if r.nanjing_lost else '🟢守住'} | "
              f"北京: {'🟢收复!' if r.beijing_captured else '❌未收复'}")
        if r.turns:
            last = r.turns[-1]
            print(f"   最终: 兵力={last['troops']}, 粮草={last['food']}, "
                  f"人口={last['population']}, 领地={last['territories']}, "
                  f"民心={last['morale']}")
        print(f"   回合数: {len(r.turns)}")

    # Save results
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = f"/opt/data/repos/histrategy/logs/nanming_playtest_{ts}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            [
                {
                    "strategy": r.strategy,
                    "survived": r.survived,
                    "nanjing_lost": r.nanjing_lost,
                    "beijing_captured": r.beijing_captured,
                    "turns": r.turns,
                    "final_troops": r.final_troops,
                    "final_food": r.final_food,
                    "final_pop": r.final_pop,
                    "final_territories": r.final_territories,
                }
                for r in results
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n📁 Results saved to: {out_path}")

    # ── Best strategy recommendation ──
    print("\n" + "=" * 60)
    print("🏆 RECOMMENDATION")
    print("=" * 60)
    if results:
        best = results[0]
        if best.beijing_captured:
            print(f"✅ Best: '{best.strategy}' — 成功收复北京！")
        elif not best.nanjing_lost:
            print(f"🟡 Best: '{best.strategy}' — 守住南京但未收复北京")
        else:
            print(f"🔴 All strategies failed. Best: '{best.strategy}'")
        print(f"   最终状态: 兵力={best.final_troops}, 领地={best.final_territories}")


if __name__ == "__main__":
    main()
