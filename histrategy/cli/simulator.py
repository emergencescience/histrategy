"""Simulator — Automates a playthrough simulation for validation and log generation.

Runs three turns of scenario 207 and exports faction states and LLM usage.
"""

from __future__ import annotations

import contextlib
import json
import time

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter, detect_provider
from ..state.world_state import get_data_dir


def run_simulation_playthrough() -> None:
    """Run automated 3-turn playthrough and compile structured reports."""
    # Detect provider
    provider_info = detect_provider()
    llm = None
    if provider_info["name"]:
        llm = LLMAdapter()
        print(f"[系统] 检测到 {provider_info['name']} API，将启动大模型模拟。")
    else:
        print("[系统] 未检测到 API Key，将启动离线模式模拟。")

    # Resolve logs path in the active save directory (room-specific)
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    llm_log_path = log_dir / "llm_usage.jsonl"

    def count_llm_lines() -> int:
        if not llm_log_path.exists():
            return 0
        try:
            with open(llm_log_path, encoding="utf-8") as f:
                return len(f.readlines())
        except OSError:
            return 0

    def get_new_llm_logs(start_lines_count: int) -> list[dict]:
        if not llm_log_path.exists():
            return []
        try:
            with open(llm_log_path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        if len(lines) <= start_lines_count:
            return []
        new_logs = []
        for line in lines[start_lines_count:]:
            with contextlib.suppress(Exception):
                new_logs.append(json.loads(line))
        return new_logs

    def get_faction_details(ws: any) -> dict:
        details = {}
        for fid, f in ws.factions.items():
            details[fid] = {
                "name": getattr(f, "name", fid),
                "capital": getattr(f, "capital", ""),
                "territories": list(f.territories) if f.territories else [],
                "strength": getattr(f, "strength_actual", getattr(f, "strength", 0)),
                "food": getattr(f, "food", 0),
                "treasury": getattr(f, "treasury", 0),
                "morale": getattr(f, "morale_actual", getattr(f, "morale", 0)),
                "is_active": getattr(f, "is_active", True),
            }
        return details

    # Initialize Game Engine for Scenario 207 (三顾茅庐) with player faction shu
    engine = GameEngine(scenario="207", new_game=True, llm=llm)
    engine.set_player_faction("shu")

    playthrough_log = []

    # Get V2 or V1 World State reference
    ws = engine.world_state_v2 if getattr(engine, "_use_v2", False) else engine.world_state

    # Turn 0: Get Intro Scene and initial plans
    intro = engine.get_intro_scene()
    plan = engine.get_plan_data()

    playthrough_log.append(
        {
            "turn": 0,
            "year": ws.year,
            "season": ws.season.cn if hasattr(ws.season, "cn") else ws.current_season,
            "phase": "intro",
            "narrative": intro.get("narrative", ""),
            "suggestions": plan.get("suggestions", []),
            "factions": get_faction_details(ws),
            "llm_calls": [],
        }
    )

    decisions = [
        "派关羽张飞去卧龙岗三顾茅庐，务必请诸葛亮出山相助",
        "诸葛亮既出，请军师分析天下形势，制定隆中对策",
        "趁曹操北征乌桓无暇南顾，发展新野农业民生",
    ]

    for t, decision in enumerate(decisions, 1):
        print(f"正在执行第 {t} 回合模拟决策: '{decision}'...")
        start_lines = count_llm_lines()

        # Process turn
        result = engine.process_turn(decision)

        # Give async narrative generation task a brief moment to log response
        time.sleep(1.0)

        # Retrieve LLM calls made during this turn
        new_calls = get_new_llm_logs(start_lines)

        # Get plan recommendations for the next turn
        plan_data = engine.get_plan_data()

        current_ws = engine.world_state_v2 if getattr(engine, "_use_v2", False) else engine.world_state

        playthrough_log.append(
            {
                "turn": t,
                "year": current_ws.year,
                "season": current_ws.season.cn if hasattr(current_ws.season, "cn") else current_ws.current_season,
                "phase": "command",
                "decision": decision,
                "narrative": result.get("aftermath", result.get("narrative", "")),
                "state_changes": result.get("state_changes", {}),
                "events": result.get("events_occurred", []),
                "suggestions": plan_data.get("suggestions", []),
                "factions": get_faction_details(current_ws),
                "llm_calls": new_calls,
            }
        )

    # Format the playthrough record to Markdown
    md_lines = [
        "# 🎮 《三國志略》实战推演与数值仿真审查报告",
        "",
        "本报告记录了一局由 V2 引擎（7-引擎数值后台 + LLM 叙事层）驱动的实战推演细节。"
        "报告中包含每回合的**完整 NPC 势力数值状态变化**以及"
        "**大模型交互的完整 Prompt 与 Response**。",
        "",
        "---",
        "",
    ]

    for entry in playthrough_log:
        turn = entry["turn"]
        year = entry["year"]
        season = entry["season"]
        season_display = season
        if season == "spring":
            season_display = "春季"
        elif season == "summer":
            season_display = "夏季"
        elif season == "autumn":
            season_display = "秋季"
        elif season == "winter":
            season_display = "冬季"

        md_lines.append(f"## 📅 第 {turn} 回合 ({year}年{season_display})")
        md_lines.append("")
        if turn > 0:
            md_lines.append(f"**🎯 玩家君主决策**：`{entry['decision']}`")
            md_lines.append("")

        md_lines.append("### 🏛️ 势力全局数值状态 (Faction States)")
        md_lines.append("| 势力 | 城池数量 | 领地 | 兵力 | 粮草 | 资金 | 民心 |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for fid, f in entry["factions"].items():
            if not f["is_active"]:
                continue
            territories_str = ", ".join(f["territories"])
            md_lines.append(
                f"| {f['name']} ({fid}) | {len(f['territories'])} | {territories_str}"
                f" | {f['strength']:,} | {f['food']:,}"
                f" | {f['treasury']:,} | {f['morale']} |"
            )
        md_lines.append("")

        md_lines.append("### 📜 局势叙事")
        md_lines.append(entry["narrative"])
        md_lines.append("")

        if entry["llm_calls"]:
            md_lines.append("### 🤖 大模型 Prompt & Response 记录")
            for i, call in enumerate(entry["llm_calls"], 1):
                md_lines.append(
                    f"#### 调用 {i}: Model={call.get('model')} (Latency={call.get('latency_seconds', 0.0):.2f}s)"
                )
                md_lines.append("")
                md_lines.append("<details>")
                md_lines.append("<summary>展开查看完整 Prompt & Response</summary>")
                md_lines.append("")
                md_lines.append("##### 📥 Input Messages")
                for msg in call.get("messages", []):
                    role = msg.get("role", "").upper()
                    content = msg.get("content", "")
                    md_lines.append(f"**[{role}]**:")
                    md_lines.append(f"```text\n{content}\n```")
                    md_lines.append("")
                md_lines.append("##### 📤 Response")
                md_lines.append(f"```text\n{call.get('response')}\n```")
                md_lines.append("")
                md_lines.append("</details>")
                md_lines.append("")

    # Save markdown to the active save directory (room-specific)
    output_path = get_data_dir() / "playthrough_records.md"
    try:
        output_path.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"[系统] 模拟试玩报告已成功导出至 {output_path}")
    except OSError as e:
        print(f"[错误] 无法保存模拟报告到 {output_path}: {e}")
