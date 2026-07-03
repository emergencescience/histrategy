#!/usr/bin/env python3
"""E2E test: 5-quarters of Cao Cao macro historical engine."""
import os
import sys
import time

os.environ["HISTRATEGY_ENGINE"] = "v3"

sys.path.insert(0, "/opt/data/repos/histrategy")

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter

llm = LLMAdapter()

DECISIONS = [
    # Q1: 207 spring - recovery
    "将税率从40%降至30%，推行屯田制以增加粮食产出。任命荀彧为尚书令主管内政。派使者携重礼前往建业与孙权结好。",
    # Q2: 207 summer - build up
    "扩大屯田范围至全部领地，拨款10000金给许昌和邺城用于农具改良。在宛城和洛阳加紧练兵，征募15000新兵。",
    # Q3: 207 autumn - prepare
    "任命司马懿为军师中郎将，夏侯渊为征南将军。在宛城集结兵力准备南征。向刘表发出最后通牒。",
    # Q4: 207 winter - conquer
    "正式对刘表宣战！宛城大军直取襄阳。命令张辽率水军封锁江面防止孙权援救。",
    # Q5: 208 spring - consolidation
    "攻克襄阳后顺势南下江陵消灭刘表势力。派夏侯渊从洛阳西进取汉中。对孙权保持善意中立。",
]

print("=" * 60)
print("E2E TEST: Cao Cao Macro Historical Engine (5 quarters)")
print("=" * 60)

engine = GameEngine(llm=llm, scenario="three-kingdoms", new_game=True)
engine.set_player_faction("cao")

ws = engine.world_state_v2
print(f"Initial: Year {ws.year}, Player={ws.player_faction_id}, Macro={engine._use_v3}")
print(f"  Territories: {list(ws.factions[ws.player_faction_id].territories)}")
print(f"  Treasury: {ws.factions[ws.player_faction_id].treasury}")

for i, decision in enumerate(DECISIONS):
    t0 = time.time()
    yr = 207 + (i // 4)
    sz = ['spring','summer','autumn','winter'][i % 4]
    print(f"\n{'='*50}")
    print(f"Q{i+1} ({yr} {sz}): {decision[:70]}...")
    print(f"{'='*50}")

    result = engine.process_turn(decision)
    t1 = time.time()

    ws = result.get("world_state", engine.world_state_v2)
    pf = ws.factions.get(ws.player_faction_id) if ws else None

    usage = result.get("_usage", {})
    print(f"  Time: {t1-t0:.1f}s  Tokens: {usage.get('sim_tokens', 0)}")

    aftermath = result.get("aftermath", str(result)[:150])
    print(f"  结果: {aftermath[:150]}")

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
