#!/usr/bin/env python3
"""
E2E 多角色测试 — V1 和 V3 引擎分别用 cao/shu/wu 三势力完整测试。

用法：
    HISTRATEGY_ENGINE=v1 python3 scripts/e2e_multiplayer.py
    HISTRATEGY_ENGINE=v3 python3 scripts/e2e_multiplayer.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.engine.engine_switch import detect_engine_mode, EngineMode
from histrategy.engine.game_room import GameRoom, RoomPhase
from histrategy.engine.faction_slot import (
    create_human_slot,
    create_ai_slot,
    FactionSlot,
    LLM_NPC_FACTIONS,
    HEURISTIC_NPC_FACTIONS,
)
from histrategy.engine.decision_bus import collect_all_decisions
from histrategy.engine.game import GameEngine


def setup_room() -> GameRoom:
    """创建三人类玩家的游戏房间。"""
    room = GameRoom(scenario="207")

    # 三个玩家分别控制 cao, shu, wu
    room.slots["cao"] = create_human_slot("cao", "player_cao")
    room.slots["shu"] = create_human_slot("shu", "player_shu")
    room.slots["wu"] = create_human_slot("wu", "player_wu")

    # 次要势力 → AI
    for fid in HEURISTIC_NPC_FACTIONS:
        room.slots[fid] = create_ai_slot(fid)

    # 初始化 WorldState
    engine = GameEngine(scenario="207", new_game=True)
    engine.set_player_faction("shu")
    room.world_state = engine.world_state_v2

    room.phase = RoomPhase.WAITING
    return room


def simulate_turn(room: GameRoom, human_decisions: dict[str, str]) -> dict:
    """模拟一个完整季度。

    Args:
        room: 游戏房间
        human_decisions: {faction_id: decision_text}

    Returns:
        结果摘要
    """
    engine_mode = detect_engine_mode()
    print(f"\n{'='*60}")
    print(f"Q{room.quarter_number + 1} — {engine_mode.value.upper()} 引擎")
    print(f"{'='*60}")

    # 1. 人类提交决策
    for fid, decision in human_decisions.items():
        if fid in room.slots:
            room.slots[fid].submit_decision(decision)
            print(f"  Human {fid}: {decision[:60]}...")

    # 2. AI NPC 生成决策（模拟 DecisionBus）
    from histrategy.llm.adapter import LLMAdapter

    llm = None
    try:
        llm = LLMAdapter()
    except Exception:
        pass

    ws = room.world_state
    decisions = collect_all_decisions(room, ws, llm=llm, turn_memory=room.turn_summaries)

    # 3. 执行引擎
    start = time.time()

    if engine_mode == EngineMode.V1:
        result = _run_v1(room, ws, decisions, llm)
    else:
        from histrategy.engine.quarterly_resolver import QuarterlyResolver

        resolver = QuarterlyResolver()
        result = resolver.resolve(room, ws, decisions, llm=llm)

    elapsed = time.time() - start

    # 4. 输出结果
    print(f"\n  延迟: {elapsed:.1f}s")
    for fid in human_decisions:
        narrative = result.narratives.get(fid, "")
        if narrative:
            print(f"  {fid}: {narrative[:100]}...")

    # 5. 推进季度
    from histrategy_engine.world import Season

    seasons = list(Season)
    idx = seasons.index(ws.season) if ws.season in seasons else 0
    ws.season = seasons[(idx + 1) % len(seasons)]
    if ws.season == seasons[0]:
        ws.year += 1
    ws.turn_number += 1
    room.advance_quarter()
    room.world_state = ws

    if result.turn_summary:
        room.turn_summaries.append(result.turn_summary)

    return {
        "elapsed": elapsed,
        "engine": engine_mode.value,
        "quarter": room.quarter_number,
        "year": ws.year,
        "season": ws.season.cn if hasattr(ws.season, "cn") else str(ws.season),
    }


def _run_v1(room, ws, decisions, llm):
    """V1 引擎仿真。"""
    from histrategy.engine.v1_simulator import V1Simulator, _apply_v1_state_to_world
    from dataclasses import dataclass

    simulator = V1Simulator(llm)
    fd = {fid: {"decision": dr.decision_text, "commands": dr.commands} for fid, dr in decisions.items()}

    v1_result = simulator.simulate(ws, fd, room.turn_summaries)
    _apply_v1_state_to_world(ws, v1_result.get("factions", {}))

    narratives = {}
    for fid in decisions:
        narratives[fid] = v1_result.get("narrative", "")

    @dataclass
    class V1Result:
        narratives: dict
        state_changes: dict
        turn_summary: dict | None

    return V1Result(narratives=narratives, state_changes={}, turn_summary={"quarter": room.quarter_number, "engine": "v1"})


def main():
    engine_mode = detect_engine_mode()
    print(f"🚀 E2E 测试 — {engine_mode.value.upper()} 引擎")
    print(f"   三人类玩家: cao, shu, wu")
    print(f"   AI NPC: liubiao, liuzhang, zhanglu, machao")

    room = setup_room()
    print(f"   Room ID: {room.id}")
    print(f"   Factions: {list(room.slots.keys())}")

    # 3 轮测试
    test_turns = [
        {
            "cao": "发展许昌内政，降低税率至20%，招募5000乡勇",
            "shu": "屯田新野，与刘表修好，请诸葛亮出山",
            "wu": "发展建业水军，稳固江东基业",
        },
        {
            "cao": "集结兵力准备南下，派夏侯惇为先锋",
            "shu": "加强与荆州刘表的关系，收编荆州水军",
            "wu": "采纳鲁肃榻上策，发展长江水师",
        },
        {
            "cao": "大军南下征讨荆州",
            "shu": "三顾茅庐求贤若渴",
            "wu": "坐观北方变动，静待时机",
        },
    ]

    results = []
    for i, decisions in enumerate(test_turns):
        try:
            result = simulate_turn(room, decisions)
            results.append(result)
        except Exception as e:
            print(f"\n  ❌ Q{i+1} 失败: {e}")
            import traceback
            traceback.print_exc()

    # 总结
    ws = room.world_state
    print(f"\n{'='*60}")
    print(f"📊 最终状态 (Q{room.quarter_number}, {ws.year}年)")
    print(f"{'='*60}")
    for fid in ["cao", "shu", "wu"]:
        faction = ws.factions.get(fid)
        if faction:
            print(
                f"  {faction.name}: 兵力={getattr(faction, 'strength_actual', 0)}, "
                f"粮草={faction.food}, 库金={faction.treasury}, "
                f"民心={getattr(faction, 'morale_actual', 50)}, "
                f"城池={faction.territories}"
            )

    print(f"\n  ✅ 完成 {len(results)}/{len(test_turns)} 轮")
    total_time = sum(r["elapsed"] for r in results)
    print(f"  ⏱ 总耗时: {total_time:.1f}s, 平均: {total_time / max(len(results), 1):.1f}s/轮")


if __name__ == "__main__":
    main()
