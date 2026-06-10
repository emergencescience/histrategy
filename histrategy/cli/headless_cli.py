"""
三國志略 — Headless CLI Mode (飞书桥接模式)

A machine-readable stdin/stdout interface for playing the game via Feishu.
All output goes to stdout in a structured format with clear markers.
All input comes from stdin (one command per line).

Output format:
  [PHASE:PLAN]     — Inner council / advisor suggestions
  [PHASE:DECISION] — Waiting for player input
  [PHASE:RESULT]   — Turn result / chronicle
  [PHASE:STATE]    — World state details
  [PHASE:INTRO]    — Game intro narrative
  [PHASE:FACTION]  — Faction selection screen
  [PHASE:GAMEOVER] — Game over screen
  [STATUS:xxx]     — Status bar (year, strength, etc.)
  [META:xxx]       — Token stats, latency, etc.
  [ERROR:xxx]      — Error messages

Each block ends with [END_BLOCK]

Usage:
    histrategy --headless              # Continue existing game or new
    histrategy --headless --new        # Force new game
    histrategy --headless --faction 2  # Auto-select faction
"""

from __future__ import annotations

import json
import sys

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter, detect_provider
from ..llm.game_master import GameMaster
from ..state.world_state import has_existing_game


def _emit(phase: str, content: str, meta: dict | None = None):
    """Emit a structured output block."""
    block = {
        "phase": phase,
        "content": content.strip(),
    }
    if meta:
        block["meta"] = meta
    print(json.dumps(block, ensure_ascii=False))
    print("[END_BLOCK]")
    sys.stdout.flush()


def _get_state(engine: GameEngine):
    """Return (world_state, player, is_v2) tuple that works with both v1 and v2 engines."""
    if getattr(engine, "_use_v2", False):
        ws = engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        return ws, player, True
    else:
        ws = engine.world_state
        player = ws.get_player_faction() if ws else None
        return ws, player, False


def _emit_status(engine: GameEngine):
    """Emit current game status."""
    ws, player, is_v2 = _get_state(engine)
    if is_v2:
        if player:
            status = {
                "year": ws.year,
                "season": ws.season.cn,
                "turn": ws.turn_number,
                "faction": player.name,
                "strength": player.strength_actual,
                "economy": player.economy_actual,
                "morale": player.morale_actual,
                "treasury": player.treasury,
                "food": player.food,
                "territories": list(player.territories),
            }
        else:
            status = {"year": ws.year, "season": ws.season.cn, "turn": ws.turn_number}
    else:
        if player:
            status = {
                "year": ws.year,
                "season": ws.current_season_cn,
                "turn": ws.turn,
                "faction": player.name,
                "strength": player.strength,
                "economy": player.economy,
                "morale": player.morale,
                "treasury": player.treasury,
                "food": player.food,
                "territories": player.territories,
            }
        else:
            status = {"year": ws.year, "season": ws.current_season_cn, "turn": ws.turn}
    status_str = json.dumps(status, ensure_ascii=False)
    _emit("STATUS", status_str)


def _emit_meta(engine: GameEngine):
    """Emit LLM stats if available."""
    llm = engine.llm
    if llm and getattr(llm, "last_call_stats", None):
        stats = llm.last_call_stats
        _emit("META", "", meta=stats)


def _format_plan_markdown(plan: dict) -> str:
    """Format plan data as readable markdown for Feishu."""
    lines = []
    summary = plan.get("season_summary", "")
    if summary:
        lines.append(f"*{summary}*")
        lines.append("")

    court_dialogue = plan.get("court_dialogue", "")
    if court_dialogue:
        lines.append(court_dialogue.strip())
        lines.append("")

    suggestions = plan.get("suggestions", [])
    if suggestions:
        lines.append("**🎯 廷议决策方向参考**")
        for i, s in enumerate(suggestions, 1):
            if s.startswith("【") and "】" in s:
                parts = s.split("】", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                lines.append(f"{i}. **{title}** — {desc}")
            elif s.startswith("[") and "]" in s:
                parts = s.split("]", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                lines.append(f"{i}. **{title}** — {desc}")
            else:
                lines.append(f"{i}. {s}")
        lines.append("")

    return "\n".join(lines)


def _format_command_markdown(result: dict) -> str:
    """Format command result as readable markdown for Feishu."""
    lines = []

    aftermath = result.get("aftermath", "")
    if aftermath:
        lines.append(aftermath.strip())
        lines.append("")

    bureaucracy = result.get("bureaucracy", [])
    if bureaucracy:
        lines.append("**🏛️ 各司政务**")
        for dept in bureaucracy:
            dept_name = dept.get("department", "")
            official = dept.get("official", "")
            action = dept.get("action", "")
            prefix = f"[{dept_name}" + (f" · {official}" if official else "") + "]"
            lines.append(f"- **{prefix}** {action}")
        lines.append("")

    npc_reactions = result.get("npc_reactions", [])
    if npc_reactions:
        lines.append("**⚔️ 列国战志**")
        for r in npc_reactions:
            lines.append(f"- {r}")
        lines.append("")

    seeds = result.get("seeds", [])
    if seeds:
        lines.append("**🔮 伏线机锋**")
        for s in seeds:
            trigger = s.get("trigger_after", "?")
            title = s.get("title", "未知")
            desc = s.get("description", "")
            lines.append(f"- **{title}** *({trigger}回合后)*: {desc}")
        lines.append("")

    # Offline fallback fields
    narrative = result.get("narrative", "")
    if narrative:
        lines.append(narrative.strip())
        lines.append("")

    npc_actions = result.get("npc_actions", [])
    if npc_actions and not npc_reactions:
        lines.append("**⚔️ 天下动向**")
        for a in npc_actions:
            lines.append(f"- {a}")
        lines.append("")

    state_changes = result.get("state_changes", {})
    player_changes = {k: v for k, v in state_changes.items() if k not in ("npc_changes", "before", "after") and v}
    if player_changes:
        lines.append("**📊 势力变动**")
        labels = {
            "strength": "兵力",
            "economy": "经济",
            "morale": "民心",
            "treasury": "资金",
            "food": "粮草",
        }
        for key in sorted(player_changes):
            val = player_changes[key]
            label = labels.get(key, key)
            sign = "+" if val > 0 else ""
            lines.append(f"- **{label}**: `{sign}{val}`")
        lines.append("")

    events = result.get("events_occurred", [])
    if events:
        lines.append("**⚡ 大事记**")
        for e in events:
            lines.append(f"- {e}")
        lines.append("")

    choices = result.get("new_choices", [])
    if choices:
        lines.append("**🎯 下一步可选方向**")
        for c in choices:
            if c.startswith("【") and "】" in c:
                parts = c.split("】", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                lines.append(f"- **{title}** — {desc}")
            elif c.startswith("[") and "]" in c:
                parts = c.split("]", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                lines.append(f"- **{title}** — {desc}")
            else:
                lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines)


def _format_intro_markdown(intro: dict) -> str:
    """Format intro scene as markdown."""
    lines = []
    narrative = intro.get("narrative", "")
    if narrative:
        lines.append(narrative.strip())
        lines.append("")

    npc_actions = intro.get("npc_actions", [])
    if npc_actions:
        lines.append("**🌍 天下大势**")
        for a in npc_actions:
            lines.append(f"- {a}")
        lines.append("")

    choices = intro.get("new_choices", [])
    if choices:
        lines.append("**🎯 开局选择**")
        for c in choices:
            lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines)


def _format_faction_selection() -> str:
    """Format faction selection as markdown."""
    factions = [
        ("曹操军", "曹操", 30000, "乱世奸雄，奉天子以令不臣"),
        ("刘备军", "刘备", 5000, "汉室宗亲，以仁德取天下"),
        ("孙坚军", "孙坚", 20000, "江东猛虎，据长江天险"),
        ("袁绍军", "袁绍", 80000, "四世三公，讨董盟主"),
    ]
    lines = ["**选择你的君主**", ""]
    for i, (name, ruler, strength, desc) in enumerate(factions, 1):
        lines.append(f"{i}. **{name}**（{ruler}）— {desc} — 兵力: {strength:,}")
    lines.append("")
    lines.append("请输入编号 (1-4) 选择势力。")
    return "\n".join(lines)


def run_headless(faction_choice: int | None = None, force_new: bool = False):
    """Run the game in headless mode with JSON-structured I/O."""
    # Detect provider
    provider_info = detect_provider()
    llm = None

    if provider_info["name"]:
        llm = LLMAdapter()
        GameMaster(llm)  # Initialize but don't store
        _emit("META", f"[系统] AI 模式: {provider_info['name']} ({provider_info['model']})")
    else:
        _emit("META", "[系统] 离线模式 — 无 API Key，使用规则引擎")

    engine = GameEngine(llm=llm, new_game=force_new)

    # Check for existing save
    if not force_new and has_existing_game():
        _emit("META", "[系统] 检测到存档，自动继续游戏")
        _emit_status(engine)
    else:
        # Faction selection
        factions = ["cao", "shu", "wu", "yuan_shao"]
        faction_names = ["曹操军", "刘备军", "孙坚军", "袁绍军"]

        if faction_choice is None:
            _emit("FACTION", _format_faction_selection())
            _emit("DECISION", "请输入势力编号 (1-4)")
            try:
                line = sys.stdin.readline().strip()
                if not line:
                    return
                idx = int(line) - 1
                idx = max(0, min(idx, 3))
            except (ValueError, EOFError, KeyboardInterrupt):
                return
        else:
            idx = max(0, min(faction_choice - 1, 3))

        engine.set_player_faction(factions[idx])
        _emit("META", f"[系统] 已选择 {faction_names[idx]}")

        # Intro scene
        intro = engine.get_intro_scene()
        _emit("INTRO", _format_intro_markdown(intro))
        _emit_meta(engine)

    # Main game loop
    _game_loop(engine)


def _game_loop(engine: GameEngine):
    """Main game loop with structured JSON I/O."""
    while True:
        try:
            # Check for elimination
            ws, player, is_v2 = _get_state(engine)
            if is_v2:
                alive = player and player.is_active and player.strength_actual > 0
            else:
                alive = player and player.is_active and player.strength > 0
            if not alive:
                _emit(
                    "GAMEOVER", "**势力覆灭**\n\n你的势力已经不复存在。乱世之中，成王败寇。\n\n感谢游玩《三國志略》。"
                )
                break

            # === PLAN MODE ===
            plan = engine.get_plan_data()
            _emit("PLAN", _format_plan_markdown(plan))
            _emit_meta(engine)
            _emit_status(engine)

            # === WAIT FOR DECISION ===
            _emit(
                "DECISION",
                "你的战略决策：\n(自由输入 — 如同真实军师一般下达命令)\n输入 `plan` 重开议事 | `state` 查看状态 | `exit` 退出",
            )

            try:
                line = sys.stdin.readline()
                if not line:
                    _emit("META", "[系统] 输入结束，退出游戏")
                    break
                decision = line.strip()
            except (EOFError, KeyboardInterrupt):
                _emit("META", "[系统] 输入中断，退出游戏")
                break

            if decision.lower() in ("exit", "quit", "退出", "q"):
                _emit("META", "[系统] 玩家退出游戏")
                break

            if decision.lower() in ("state", "状态"):
                _display_state(engine)
                continue

            if decision.lower() == "plan":
                continue

            if not decision:
                _emit("META", "[系统] 决策不能为空")
                continue

            # === COMMAND MODE ===
            result = engine.process_turn(decision)

            # Check for game over in result
            game_over = result.get("game_over")
            if game_over:
                _emit("RESULT", _format_command_markdown(result))
                _emit("GAMEOVER", game_over.get("message", "游戏结束"))
                _emit_meta(engine)
                break

            _emit("RESULT", _format_command_markdown(result))
            _emit_meta(engine)

        except Exception as e:
            _emit("ERROR", f"游戏发生错误：{e}")
            import traceback

            _emit("ERROR", traceback.format_exc())
            break


def _display_state(engine: GameEngine):
    """Show world state in structured format."""
    ws, player, is_v2 = _get_state(engine)
    lines = []
    if is_v2:
        lines.append(f"**{ws.year}年 {ws.season.cn} — 第 {ws.turn_number} 回合**")
        lines.append("")
        if player:
            lines.append(f"势力: {player.name}")
            lines.append(f"兵力: {player.strength_actual:,}")
            lines.append(f"经济: {player.economy_actual}/100")
            lines.append(f"民心: {player.morale_actual}/100")
            lines.append(f"资金: {player.treasury:,}")
            lines.append(f"粮草: {player.food:,}")
            lines.append(f"首都: {player.capital or '—'}")
            lines.append(f"领地: {', '.join(player.territories) if player.territories else '暂无'}")
        other_factions = [(fid, fs) for fid, fs in ws.factions.items() if fs.is_active and fid != ws.player_faction_id]
        if other_factions:
            lines.append("")
            lines.append("**其他势力**")
            for _fid, fs in other_factions[:8]:
                lines.append(f"  {fs.name}: 兵{fs.strength_actual:,} 领{len(fs.territories)}")
    else:
        lines.append(f"**{ws.year}年 {ws.current_season_cn} — 第 {ws.turn} 回合**")
        lines.append("")
        if player:
            lines.append(f"势力: {player.name}")
            lines.append(f"兵力: {player.strength:,}")
            lines.append(f"经济: {player.economy}/100")
            lines.append(f"民心: {player.morale}/100")
            lines.append(f"资金: {player.treasury:,}")
            lines.append(f"粮草: {player.food:,}")
            lines.append(f"首都: {player.capital or '—'}")
            lines.append(f"领地: {', '.join(player.territories) if player.territories else '暂无'}")
        other_factions = [(fid, fs) for fid, fs in ws.factions.items() if fs.is_active and fid != ws.player_faction_id]
        if other_factions:
            lines.append("")
            lines.append("**其他势力**")
            for _fid, fs in other_factions[:8]:
                lines.append(f"  {fs.name}: 兵{fs.strength:,} 领{len(fs.territories)}")
    _emit("STATE", "\\n".join(lines))
