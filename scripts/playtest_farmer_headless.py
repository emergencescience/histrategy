"""
Headless playtest: 农民军 (nongminjun) as human player, 10 turns.
User Story: Can the farmer faction survive and turn the tide against Qing, Nanming, Zheng?
"""
from __future__ import annotations

import os, sys, time, contextlib, logging

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("HISTRATEGY_ENGINE", "v3")
os.environ.setdefault("HISTRATEGY_MACRO", "1")
os.environ.setdefault("HISTRATEGY_STREAMING", "0")
os.environ.pop("HISTRATEGY_DATABASE_URL", None)
DB_PATH = f"/tmp/histrategy_farmer_{os.getpid()}.db"
os.environ["HISTRATEGY_DATABASE_URL"] = f"sqlite:///{DB_PATH}"

logging.basicConfig(level=logging.WARNING)

from histrategy.db.connection import init_db; init_db()
from histrategy.server.room_manager import (
    create_room, _get_room, _resolve_v2_or_v3,
    _try_save, _get_llm, _capture_faction_state,
    _territories_to_list,
)
from histrategy.engine.decision_bus import DecisionResult

# ── Strategy templates ──
FARMER_STRATEGIES = [
    "【西征固本】退守四川，命李自成督成都屯田积粮。命刘宗敏率两万精兵镇守襄阳。遣使南明联合抗清。",
    "【东出探路】刘宗敏率一万步卒东出侦察南阳。李过率五千步兵出汉中牵制陕西。主力四川屯田。",
    "【趁虚而入】清军主力在开封，南阳空虚。命刘宗敏率三万精兵攻取南阳！李过镇守汉中。",
    "【巩固战线】若南阳已克则据城固守募兵。清军仍在洛阳则袭扰粮道。李自成领成都精锐北上汉中。",
    "【北上伐秦】秋收后粮草充足。李自成率四万精兵出汉中北伐陕西！刘宗敏守南阳。联南明南北夹击清军。",
    "【随机应变】据局势调整。清军势大则固守四川襄阳。南明得势则东进扩张。郑氏北上则结盟抗清。",
    "【稳步推进】继续既定战略。兵力充足则进攻，兵疲则休整屯田。保持与南明外交。优先控制四川陕西。",
    "【扩张版图】若已有三州以上领地则继续推进。兵锋指甘肃或河南东部。若仅两州则巩固根基发展经济。",
    "【决战时刻】清军已疲则总攻洛阳开封。南明已弱则东进夺武昌。保持战略主动。",
    "【最终冲刺】集中优势兵力攻最弱敌人。保持粮草供应防饥荒。若无法获胜则转入防守。",
]


def main():
    print("=" * 60)
    print("  农民军 (nongminjun) — 10轮生存测试")
    print("=" * 60)

    # Create room via room_manager
    room_data = create_room(
        scenario="nanming",
        pre_assigned={"nongminjun": "human_player"},
        metadata={"lang": "zh"}
    )
    room_id = room_data["room_id"]
    room = _get_room(room_id)
    ws = room.world_state

    print(f"\n🌍 {room.year}年 {room.season}")
    for fid, f in ws.factions.items():
        t = list(f.territories)
        print(f"  {f.name}: {f.strength_actual:,}💂 {f.food:,}🍚 {t}")

    llm = _get_llm()
    print(f"🤖 LLM: {getattr(llm, 'provider_name', 'auto')}")

    total_start = time.time()

    for turn_idx in range(10):
        q_start = time.time()
        print(f"\n{'─' * 50}")
        print(f"  Q{turn_idx + 1}: {room.year}年 {room.season}")

        # Human decision
        strategy = FARMER_STRATEGIES[min(turn_idx, len(FARMER_STRATEGIES) - 1)]

        # Submit human decision
        from histrategy.server.room_manager import submit_decision
        submit_decision(
            room_id=room_id,
            faction_id="nongminjun",
            decision=strategy,
        )

        # Collect all decisions (this generates NPC decisions internally)
        from histrategy.engine.decision_bus import collect_all_decisions
        decisions = collect_all_decisions(room, ws, llm, lang="zh")

        # Show decisions
        for fid, dr in decisions.items():
            cmds = dr.commands or []
            csum = ", ".join(
                f"{c.get('type','?')}→{c.get('params',{}).get('target_territory','?')}"
                for c in cmds[:2]
            ) if cmds else "—"
            print(f"  {fid[:10]:<10} {dr.decision_text[:50]}... [{csum[:30]}]")

        # Resolve
        result = _resolve_v2_or_v3(room, ws, decisions, llm, "v3", skip_narrative=True)

        # Show state
        for fid, f in ws.factions.items():
            t = list(f.territories)
            print(f"  {f.name[:8]:<8} {f.strength_actual:>6,}💂 {f.food:>8,}🍚 {getattr(f,'morale_actual',50):>3}❤️ {t}")

        elapsed = time.time() - q_start
        print(f"  ⏱ {elapsed:.1f}s")

        # Advance
        room.quarter_number += 1
        room.year = ws.year
        room.season = str(ws.season.value) if hasattr(ws.season, "value") else str(ws.season)
        _try_save(room)

    total_elapsed = time.time() - total_start
    print(f"\n{'=' * 60}")
    print(f"  FINAL: {room.year}年 {room.season}")
    print(f"{'=' * 60}")

    survived = False
    for fid, f in ws.factions.items():
        t = list(f.territories)
        status = "✅" if fid == "nongminjun" and len(t) > 0 else ("❌ 亡国" if fid == "nongminjun" else "")
        print(f"  {f.name[:8]:<8} {f.strength_actual:>6,}💂 {f.food:>8,}🍚 {getattr(f,'morale_actual',50):>3}❤️ {t} {status}")
        if fid == "nongminjun" and len(t) > 0:
            survived = True

    print(f"\n⏱ 总耗时: {total_elapsed:.1f}s ({total_elapsed/10:.1f}s/轮)")
    print("✅ 农民军存活!" if survived else "❌ 农民军亡国")

    contextlib.suppress(Exception, os.unlink(DB_PATH))


if __name__ == "__main__":
    main()
