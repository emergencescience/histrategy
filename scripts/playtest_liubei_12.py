#!/usr/bin/env python3
"""
H20c: 刘备线12回合推演 — 隆中对+emergent背刺叙事

Runs a 12-turn headless playtest as Liu Bei (Shu) faction using the game engine.
Tests: no crashes, emergent narrative, state progression, Longzhong Plan arc.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ── Isolate environment ─────────────────────────────────
TEST_DIR = f"/tmp/histrategy_playtest_liubei_{os.getpid()}"
os.makedirs(TEST_DIR, exist_ok=True)
os.environ["HISTRATEGY_DATA_DIR"] = TEST_DIR

# Force offline mode for deterministic, fast testing
for key in [
    "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "TONGYI_API_KEY",
    "OPENROUTER_API_KEY", "LLM_API_KEY", "LLM_API_BASE",
]:
    os.environ.pop(key, None)

# ── Add repo to path ────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from histrategy.engine.game import GameEngine, _suppress_stderr

# ── Liu Bei 12-turn Longzhong Plan arc ──────────────────
# Follows the historical arc: 三顾茅庐 → 隆中对 → 赤壁 → 入蜀 → 汉中
LIUBEI_DECISIONS = [
    # Turn 1: 三顾茅庐 — recruit Zhuge Liang
    "派关羽张飞去卧龙岗三顾茅庐，务必请诸葛亮出山相助",
    # Turn 2: 隆中对 — strategic planning
    "诸葛亮既出，请军师分析天下形势，制定隆中对策：先取荆州为家，再图益州",
    # Turn 3: 发展新野
    "趁曹操北征乌桓无暇南顾，发展新野农业民生，安抚百姓",
    # Turn 4: 练兵备战
    "练兵备战，招募乡勇，扩充军力以备将来",
    # Turn 5: 联络江东
    "联络江东孙权，商议共抗曹操之策，建立孙刘联盟",
    # Turn 6: 携民渡江
    "曹操南下，携民渡江，保护百姓撤退至江陵",
    # Turn 7: 赤壁之战
    "与孙权结盟，联合周瑜在赤壁迎战曹操，以火攻破曹",
    # Turn 8: 夺取荆南
    "赤壁大胜后，趁势夺取荆南四郡作为根基",
    # Turn 9: 西进入蜀
    "西进入蜀，以助刘璋拒张鲁为名取益州",
    # Turn 10: 定都成都
    "定都成都，休养生息，安抚蜀中百姓",
    # Turn 11: 北伐汉中
    "北伐汉中，与曹操争夺汉中之地",
    # Turn 12: 汉中王
    "占据汉中后，进位汉中王，号召天下讨曹",
]


def run_playtest() -> dict:
    """Run 12-turn Liu Bei playtest. Returns summary dict."""
    print("=" * 60)
    print("三國志略 H20c: 刘备线12回合推演")
    print("=" * 60)
    print(f"势力: 刘备 (Shu)  剧本: 207  回合: 12")
    print(f"数据目录: {TEST_DIR}")
    print()

    results = []
    errors = []
    start_time = time.time()

    try:
        # Initialize engine
        print("[1/3] 初始化游戏引擎...")
        with _suppress_stderr():
            engine = GameEngine(scenario="three-kingdoms", new_game=True)

        # Select Liu Bei faction
        engine.set_player_faction("shu")

        def _get_state(engine):
            """Get world state regardless of v1/v2 path."""
            if engine._use_v2:
                ws = engine.world_state_v2
                pf = ws.factions.get(ws.player_faction_id) if ws else None
                year = ws.year if ws else "?"
                season = str(ws.season) if ws else "?"
                territories = list(pf.territories) if pf else []
            else:
                ws = engine.world_state
                pf = ws.get_player_faction() if ws else None
                year = ws.year if ws else "?"
                season = str(ws.season) if ws else "?"
                territories = pf.territories if pf else []
            return ws, pf, year, season, territories

        ws, pf, year, season, territories = _get_state(engine)
        if pf:
            print(f"  玩家势力: {getattr(pf, 'name', '?')}")
        print(f"  初始年份: {year}年")
        print()

        # ── Run 12 turns ──────────────────────────────
        print("[2/3] 开始12回合推演...")
        for i, decision in enumerate(LIUBEI_DECISIONS):
            turn_start = time.time()

            try:
                with _suppress_stderr():
                    result = engine.process_turn(decision)

                ws, pf, year, season, territories = _get_state(engine)

                turn_info = {
                    "turn": i + 1,
                    "decision": decision[:40] + "..." if len(decision) > 40 else decision,
                    "year": year,
                    "season": season,
                    "narrative_preview": str(result.get("aftermath", result.get("narrative", "")))[:100],
                    "game_over": result.get("game_over"),
                    "strength": pf.strength_actual if pf else "?",
                    "treasury": pf.treasury if pf else "?",
                    "food": pf.food if pf else "?",
                    "territories": len(territories) if territories else 0,
                    "latency_ms": int((time.time() - turn_start) * 1000),
                }
                results.append(turn_info)

                status = (
                    f"  T{turn_info['turn']:2d} | {turn_info['year']}年{turn_info['season']}"
                    f" | 兵:{turn_info['strength']} | 金:{turn_info['treasury']}"
                    f" | 粮:{turn_info['food']} | 城:{turn_info['territories']}"
                    f" | {turn_info['latency_ms']}ms"
                )
                print(status)

                if turn_info["game_over"]:
                    print(f"  ⚠️  游戏在第{i+1}回合结束: {turn_info['game_over']}")
                    break

            except Exception as e:
                err_msg = f"Turn {i+1} ERROR: {e}"
                print(f"  ❌ {err_msg}")
                errors.append({"turn": i + 1, "error": str(e)})

        # ── Summary ────────────────────────────────────
        elapsed = time.time() - start_time
        print()
        print("[3/3] 推演完成")
        print(f"  总回合: {len(results)}")
        print(f"  总耗时: {elapsed:.1f}s")
        print(f"  平均每回合: {elapsed/len(results)*1000:.0f}ms" if results else "")
        print(f"  错误数: {len(errors)}")

        if results:
            first = results[0]
            last = results[-1]
            print(f"  起始状态: {first['year']}年 | 兵:{first['strength']} | 金:{first['treasury']}")
            print(f"  最终状态: {last['year']}年{last['season']} | 兵:{last['strength']} | 金:{last['treasury']} | 城:{last['territories']}")

        return {
            "faction": "shu (刘备)",
            "scenario": "207",
            "turns_completed": len(results),
            "errors": len(errors),
            "error_details": errors,
            "total_time_s": round(elapsed, 1),
            "results": results,
            "passed": len(errors) == 0 and len(results) >= 10,
        }

    except Exception as e:
        print(f"FATAL: {e}")
        import traceback
        traceback.print_exc()
        return {
            "faction": "shu (刘备)",
            "turns_completed": len(results),
            "errors": len(errors) + 1,
            "error_details": errors + [{"turn": "fatal", "error": str(e)}],
            "total_time_s": round(time.time() - start_time, 1),
            "results": results,
            "passed": False,
        }


if __name__ == "__main__":
    summary = run_playtest()

    # Save report
    report_path = Path(TEST_DIR) / "playtest_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n📄 报告已保存: {report_path}")

    # Exit code
    if summary["passed"]:
        print("\n✅ H20c 验证通过: 刘备线12回合推演完成")
        sys.exit(0)
    else:
        print(f"\n❌ H20c 验证失败: {summary['errors']} 个错误")
        sys.exit(1)
