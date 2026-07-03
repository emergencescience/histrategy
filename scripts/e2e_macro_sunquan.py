#!/usr/bin/env python3
"""E2E test: Sun Quan (Wu) macro historical engine — 5 quarters."""
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
    # Q1: 207 spring — consolidate, develop internal
    "任命周瑜为大都督，鲁肃为参军。在会稽推行屯田减税（税率降至25%），开发沿海盐田，增加税收。",
    # Q2: 207 summer — naval build-up
    "扩建柴桑水军大营，建造20艘蒙冲战船。派步骘出使交州建立朝贡关系。拨款8000金修建建业码头。",
    # Q3: 207 autumn — diplomatic web
    "派鲁肃出使刘备（新野）提议联合抗曹。同时修复与刘表（襄阳）关系，互派商队通商。在庐江屯重兵防范曹操南下。",
    # Q4: 207 winter — strategic positioning
    "攻取江口（刘表的jiangkou），作为前出长江中游的据点。由周瑜亲率水军出战，速战速决后安抚当地民众。",
    # Q5: 208 spring — two-front strategy
    "乘曹操在荆州北部用兵，从庐江出兵试探攻取下邳。若形势有利则进占徐州；否则退回长江防线坚守。",
]

print("=" * 60)
print("E2E TEST: Sun Quan (Wu) Macro Historical Engine (5 quarters)")
print("=" * 60)

engine = GameEngine(llm=llm, scenario="three-kingdoms", new_game=True)
engine.set_player_faction("wu")

ws = engine.world_state_v2
print(f"Initial: Year {ws.year}, Player={ws.player_faction_id}, Macro={engine._use_v3}")
print(f"  Territories: {list(ws.factions[ws.player_faction_id].territories)}")
print(f"  Treasury: {ws.factions[ws.player_faction_id].treasury}")

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
