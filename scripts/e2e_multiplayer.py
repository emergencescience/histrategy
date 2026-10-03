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

        engine = GameEngine(scenario="three-kingdoms", new_game=True, llm=llm)
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



def main():
    engine_mode = detect_engine_mode()
    print(f"🚀 E2E 测试 — {engine_mode.value.upper()} 引擎\n")

    if engine_mode == EngineMode.V2:
        ok = test_v2_multi()
    elif engine_mode in (EngineMode.V3,):
        ok = test_v3_multi()
    else:
        print(f"⚠️ Unknown engine mode: {engine_mode}")
        ok = False

    print(f"\n{'✅' if ok else '❌'} 测试{'通过' if ok else '未通过'} — {engine_mode.value.upper()} 引擎")


if __name__ == "__main__":
    main()
