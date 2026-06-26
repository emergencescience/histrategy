#!/usr/bin/env python3
"""
E2E 多角色测试 — V1 和 V3 引擎分别用 cao/shu/wu 三势力完整测试。

用法：
    HISTRATEGY_ENGINE=v1 python3 scripts/e2e_multiplayer.py
    HISTRATEGY_ENGINE=v3 python3 scripts/e2e_multiplayer.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.engine.engine_switch import EngineMode, detect_engine_mode


def test_v3_multi():
    """V3 引擎：使用 GameEngine + HISTRATEGY_ENGINE=v3 模式，每个势力依次一回合。"""
    os.environ["HISTRATEGY_ENGINE"] = "v3"

    from histrategy.engine.game import GameEngine
    from histrategy.llm.adapter import LLMAdapter

    llm = LLMAdapter()
    if not llm.is_available:
        print("⚠️ LLM 不可用，跳过 V3 测试")
        return

    print(f"✅ LLM: {llm.provider_name} / {llm.model}")

    factions = [
        ("cao", "发展许昌内政，降低税率至20%，招募5000乡勇"),
        ("shu", "屯田新野，与刘表修好，请诸葛亮出山"),
        ("wu", "发展建业水军，稳固江东基业"),
    ]

    total_time = 0
    for i, (faction, decision) in enumerate(factions):
        print(f"\n{'='*60}")
        print(f"V3 Q1 — {faction}: {decision[:50]}...")
        print(f"{'='*60}")

        engine = GameEngine(scenario="207", new_game=True, llm=llm)
        engine.set_player_faction(faction)

        t0 = time.time()
        try:
            result = engine.process_turn(decision)
            elapsed = time.time() - t0
            total_time += elapsed

            narrative = result.get("narrative", "")[:200]
            print(f"  延迟: {elapsed:.1f}s")
            print(f"  叙事: {narrative}")
            print(f"  Token: {result.get('_usage', {})}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ 失败 ({elapsed:.1f}s): {e}")

    print(f"\n📊 V3 总耗时: {total_time:.1f}s, 平均: {total_time / len(factions):.1f}s/势力")
    return total_time > 0


def test_v1_multi():
    """V1 引擎：使用 V1Simulator 直接推演多势力。"""
    from histrategy.engine.game import GameEngine
    from histrategy.engine.v1_simulator import V1Simulator
    from histrategy.llm.adapter import LLMAdapter

    llm = LLMAdapter()
    if not llm.is_available:
        print("⚠️ LLM 不可用，跳过 V1 测试")
        return

    simulator = V1Simulator(llm)
    if not simulator.is_available:
        print("⚠️ V1Simulator 不可用")
        return

    # 初始化 world state
    engine = GameEngine(scenario="207", new_game=True)
    engine.set_player_faction("cao")
    ws = engine.world_state_v2

    # 模拟三势力决策
    decisions = {
        "cao": {"decision": "发展许昌内政，降低税率至20%，招募5000乡勇", "commands": []},
        "shu": {"decision": "屯田新野，与刘表修好，请诸葛亮出山", "commands": []},
        "wu": {"decision": "发展建业水军，稳固江东基业", "commands": []},
    }

    print(f"\n{'='*60}")
    print("V1 Q1 — 纯LLM推演 (cao + shu + wu + AI NPCs)")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        result = simulator.simulate(ws, decisions, [])
        elapsed = time.time() - t0

        narrative = result.get("narrative", "")[:300]
        print(f"  延迟: {elapsed:.1f}s")
        print(f"  叙事: {narrative}")

        # 显示状态变化
        factions_result = result.get("factions", {})
        for fid in ["cao", "shu", "wu"]:
            data = factions_result.get(fid, {})
            print(f"  {fid}: 兵力={data.get('troops', '?')}, 粮草={data.get('food', '?')}, "
                  f"民心={data.get('morale', '?')}")

        events = result.get("events", [])
        if events:
            print(f"  事件 ({len(events)}):")
            for e in events[:3]:
                print(f"    - {e[:80]}")

        token_usage = result.get("token_usage", {})
        print(f"  Token: {token_usage}")

        return elapsed > 0
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ V1 失败 ({elapsed:.1f}s): {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    engine_mode = detect_engine_mode()
    print(f"🚀 E2E 测试 — {engine_mode.value.upper()} 引擎\n")

    if engine_mode == EngineMode.V1:
        ok = test_v1_multi()
    elif engine_mode in (EngineMode.V3,):
        ok = test_v3_multi()
    else:
        print(f"⚠️ Unknown engine mode: {engine_mode}")
        ok = False

    print(f"\n{'✅' if ok else '❌'} 测试{'通过' if ok else '未通过'} — {engine_mode.value.upper()} 引擎")


if __name__ == "__main__":
    main()
