#!/usr/bin/env python3
"""E2E test: Liu Bei (Shu) macro historical engine — 5 quarters."""
import os
import sys
import time

os.environ["HISTRATEGY_ENGINE"] = "v3"
sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter

llm = LLMAdapter()
print("LLM available:", llm.is_available)

DECISIONS = [
    # Q1: 207 spring — survival + talent
    "三顾茅庐请诸葛亮出山！全军节衣缩食（税率降至20%），在新野周边屯田自给。派关羽操练仅有的5000兵马，每日苦练不辍。",
    # Q2: 207 summer — diplomatic maneuvering
    "听从诸葛亮《隆中对》：联吴抗曹！派诸葛亮出使柴桑与孙权结盟，共商抗曹大计。同时派糜竺出使襄阳缓和与刘表关系，请求借道江陵暂驻。",
    # Q3: 207 autumn — desperate expansion
    "趁刘表病重（据报），以'保卫汉室'之名出兵占领江口（jiangkou），打通与东吴的直接联系通道。命赵云为先锋，轻骑突进。",
    # Q4: 207 winter — seize opportunity
    "刘表已逝，刘琮献荆州于曹操！趁曹操大军未至，火速南下占领襄阳（xiangyang）和江陵（jiangling），收编荆州水军。打出'刘皇叔'旗号收拢人心。",
    # Q5: 208 spring — race against time
    "在襄阳整编新军，收容刘表旧部。若曹操来攻，则与孙权（柴桑方向）前后夹击。推行《蜀科》新法，取信荆州士族民心。",
]

print("=" * 60)
print("E2E TEST: Liu Bei (Shu) Macro Historical Engine (5 quarters)")
print("=" * 60)

engine = GameEngine(llm=llm, scenario="three-kingdoms", new_game=True)
engine.set_player_faction("shu")

ws = engine.world_state_v2
print(f"Initial: Year {ws.year}, Player={ws.player_faction_id}, Macro={engine._use_v3}")
print(f"  Territories: {list(ws.factions[ws.player_faction_id].territories)}")
pf = ws.factions[ws.player_faction_id]
print(f"  Starting: 兵{pf.strength_actual} 钱{pf.treasury} 粮{pf.food} 民心{pf.morale_actual}")

for i, decision in enumerate(DECISIONS):
    t0 = time.time()
    yr = 207 + (i // 4)
    sz = ['spring','summer','autumn','winter'][i % 4]
    print(f"\n{'='*50}")
    print(f"Q{i+1} ({yr} {sz}): {decision[:80]}...")
    print(f"{'='*50}")

    result = engine.process_turn(decision)
    t1 = time.time()

    ws = result.get("world_state", engine.world_state_v2)
    pf = ws.factions.get(ws.player_faction_id) if ws else None

    usage = result.get("_usage", {})
    print(f"  Time: {t1-t0:.1f}s  Tokens: {usage.get('sim_tokens', 0)}")

    aftermath = str(result.get("aftermath", str(result)[:200]))
    print(f"  结果: {aftermath[:200]}")

    if pf:
        morale = getattr(pf, 'morale_actual', '?')
        territories = list(pf.territories) if pf.territories else []
        print(f"  资金:{pf.treasury} 粮草:{pf.food} 民心:{morale} 领地:{len(territories)}={territories}")

    if result.get("knowledge_cards"):
        for kc in result["knowledge_cards"]:
            print(f"  [知识] {kc}")
    if result.get("events_occurred"):
        print(f"  [事件] {result['events_occurred']}")
    if result.get("game_over"):
        print("  GAME OVER!")
        break

print(f"\n{'='*60}")
print("FINAL STATE")
print(f"{'='*60}")
ws = engine.world_state_v2
for fid, f in ws.factions.items():
    active = getattr(f, "is_active", True)
    if not active:
        print(f"  {fid} ({f.name}): DEFEATED")
    else:
        t = list(f.territories) if f.territories else []
        morale = getattr(f, 'morale_actual', '?')
        strength = getattr(f, 'strength_actual', '?')
        print(f"  {fid} ({f.name}): 兵{strength} 钱{f.treasury} "
              f"粮{f.food} 民心{morale} 领地({len(t)})={t}")

print("\nLogs at: ~/.histrategy/rooms/*/logs/llm_usage.log")
