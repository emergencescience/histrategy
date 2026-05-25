"""
三國志略 — Dev CLI Mode

A plain-text input/output interface for the game, accessible via:
    histrategy --dev

Flow (LLM-driven):
  Plan Mode   → LLM generates advisor court + 4 suggestions
  Player      → types free-text strategic decision
  Command Mode → LLM generates execution results + consequences

Input format:
    Type your strategic decision as natural text (free text).
    'plan'  — re-enter Plan Mode (regenerate advisors/suggestions)
    'state' — view current world state
    'exit'  — quit

Offline mode:
    When no API key is available, falls back to template-based offline_sim.
    Set DEEPSEEK_API_KEY (or other provider) for full LLM-driven experience.
"""

from __future__ import annotations

import sys

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter, detect_provider
from ..llm.game_master import GameMaster
from ..state.world_state import DATA_DIR, has_existing_game


def run_dev(faction_choice: int | None = None, force_new: bool = False):
    """
    Run the game in dev mode (plain text input/output).

    Args:
        faction_choice: Pre-select faction index (1-4), or None to ask
        force_new: If True, ignore any existing save game
    """
    provider_info = detect_provider()
    llm = None
    game_master = None

    if provider_info["name"]:
        llm = LLMAdapter()
        game_master = GameMaster(llm)
        print(f"[系统] 检测到 {provider_info['name']} API ({provider_info['model']})", file=sys.stderr)
    else:
        print("[系统] 未检测到 API Key，将启动离线模式", file=sys.stderr)
        print("[系统] 设置 DEEPSEEK_API_KEY 可体验AI驱动的游戏主持", file=sys.stderr)

    engine = GameEngine(llm=llm, new_game=force_new)

    # Check for existing save
    if not force_new and has_existing_game():
        print("[系统] 检测到存档，将自动继续游戏", file=sys.stderr)
        print("[系统] 使用 --new 可强制开始新游戏", file=sys.stderr)
        print("---")
        _display_state(engine)
    else:
        # Faction selection
        factions = [
            ("cao", "曹操", "乱世奸雄，奉天子以令不臣"),
            ("shu", "刘备", "汉室宗亲，以仁德取天下"),
            ("wu", "孙坚", "江东猛虎，据长江天险"),
            ("yuan_shao", "袁绍", "四世三公，讨董盟主"),
        ]

        if faction_choice is None:
            print("=== 选择势力 ===")
            for i, (fid, name, desc) in enumerate(factions, 1):
                print(f"  {i}. {name} - {desc}")
            print()
            try:
                choice = input("请输入编号 (1-4): ").strip()
                idx = int(choice) - 1 if choice.isdigit() else 0
            except (EOFError, KeyboardInterrupt):
                print("\n退出游戏", file=sys.stderr)
                return
        else:
            idx = max(0, min(faction_choice - 1, 3))

        fid, fname, _ = factions[idx]
        print(f"\n[系统] 已选择 {fname}", file=sys.stderr)
        engine.set_player_faction(fid)

        # Intro
        intro = engine.get_intro_scene()
        print("=== 开局 ===")
        print("---")
        print(intro.get("narrative", ""))
        print("---")
        for action in intro.get("npc_actions", []):
            print(f"  ⚡ {action}")
        print("---")

    # Main game loop
    _game_loop(engine)


def _game_loop(engine: GameEngine):
    """The main game loop — Plan Mode → Player Decision → Command Mode.

    Unified through GameEngine:
      Plan Mode → engine.get_plan_data()
      Player types free-text decision
      Command Mode → engine.process_turn()
    """
    while True:
        try:
            # ═══ PLAN MODE ═══════════════════════════════════════
            if engine.llm:
                _show_llm_plan_mode(engine)
            else:
                _show_offline_plan_mode(engine)

            # ═══ PLAYER DECISION ════════════════════════════════
            print()
            decision = input("你的决策: ").strip()

            if decision.lower() in ("exit", "quit", "退出", "q"):
                print("\n退出游戏", file=sys.stderr)
                break

            if decision.lower() in ("state", "状态"):
                _display_state(engine)
                continue

            if decision.lower() == "plan":
                continue  # re-enter Plan Mode

            if not decision:
                print("[系统] 请输入你的决策", file=sys.stderr)
                continue

            # ═══ COMMAND MODE ═══════════════════════════════════
            print("---", file=sys.stderr)
            if engine.llm:
                print("[系统] AI游戏主持正在推演天下大势...", file=sys.stderr)
            else:
                print("[系统] 正在推演天下大势...", file=sys.stderr)
            result = engine.process_turn(decision)
            if engine.llm:
                _show_llm_command_result(result)
            else:
                _show_offline_command_result(result)

        except (EOFError, KeyboardInterrupt):
            print("\n退出游戏", file=sys.stderr)
            break


# ─── LLM-Driven Plan Mode ──────────────────────────────────

def _show_llm_plan_mode(engine: GameEngine):
    """Generate and display LLM-driven Plan Mode (advisor court + suggestions)."""
    plan = engine.get_plan_data()

    # Season summary
    summary = plan.get("season_summary", "")
    if summary:
        print(f"\n  {summary}")

    # Unified Court Dialogue
    court_dialogue = plan.get("court_dialogue", "")
    suggestions = plan.get("suggestions", [])

    print("\n=== 🏛️ 议事厅 - 谋臣献策 ===")
    if court_dialogue:
        print(court_dialogue.strip())
        print()

    if suggestions:
        print("---")
        print("🎯 廷议决策方向参考:")
        for i, s in enumerate(suggestions, 1):
            if s.startswith("【") and "】" in s:
                parts = s.split("】", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                print(f"  {i}. **{title}** — {desc}")
            elif s.startswith("[") and "]" in s:
                parts = s.split("]", 1)
                title = parts[0][1:]
                desc = parts[1].strip()
                print(f"  {i}. **{title}** — {desc}")
            else:
                print(f"  {i}. {s}")
        print()


def _show_llm_command_result(result: dict):
    """Display Command Mode results from LLM in a single unified chronicle block."""
    bureaucracy = result.get("bureaucracy", [])
    aftermath = result.get("aftermath", "")
    seeds = result.get("seeds", [])
    npc_reactions = result.get("npc_reactions", [])

    print("\n=== 📜 局势推演纪事 ===")
    if aftermath:
        print(aftermath.strip())
        print()

    if bureaucracy:
        print("### 🏛️ 各司政务")
        for dept in bureaucracy:
            dept_name = dept.get("department", "")
            official = dept.get("official", "")
            action = dept.get("action", "")
            prefix = f"[{dept_name}" + (f" · {official}" if official else "") + "]"
            print(f"  - **{prefix}** {action}")
        print()

    if npc_reactions:
        print("### ⚔️ 列国战志")
        for r in npc_reactions:
            print(f"  - {r}")
        print()

    if seeds:
        print("### 🔮 伏线机锋")
        for s in seeds:
            trigger = s.get("trigger_after", "?")
            title = s.get("title", "未知")
            desc = s.get("description", "")
            print(f"  - **{title}** *({trigger}回合后)*: {desc}")
        print()


# ─── Offline Fallbacks ──────────────────────────────────────

def _show_offline_plan_mode(engine: GameEngine):
    """Minimal Plan Mode for offline play."""
    player = engine.world_state.get_player_faction()
    if not player:
        return

    print(f"\n  {engine.world_state.year}年{engine.world_state.current_season_cn} | 第{engine.world_state.turn}回合")
    print(f"  {player.name}：兵力{player.strength:,} | 经济{player.economy} | 民心{player.morale}")
    print()
    print("  输入你的战略决策（自由文本）：")
    print("  例如：发展内政、扩军备战、派遣使者联合袁绍、搜集敌方情报等")


def _show_offline_command_result(result: dict):
    """Display Command Mode results from offline_sim."""
    # Narrative
    narrative = result.get("narrative", "")
    if narrative:
        print(f"\n{narrative}")

    # Bureaucracy
    bureaucracy = result.get("bureaucracy", [])
    if bureaucracy:
        print("\n=== 政令执行 ===")
        for dept in bureaucracy:
            dept_name = dept.get("department", "")
            official = dept.get("official", "")
            action = dept.get("action", "")
            prefix = f"[{dept_name}" + (f"·{official}" if official else "") + "]"
            print(f"  {prefix} {action}")

    # Aftermath
    aftermath = result.get("aftermath", "")
    if aftermath:
        print(f"\n  ⚡ {aftermath}")

    # State changes
    changes = result.get("state_changes", {})
    if changes:
        player_changes = {
            k: v for k, v in changes.items()
            if k not in ("npc_changes", "changes", "before", "after")
        }
        if any(player_changes.values()):
            print()
            print("  本季变化:")
            labels = {
                "strength": "兵力", "economy": "经济", "morale": "民心",
                "treasury": "资金", "food": "粮草",
            }
            for key, val in sorted(player_changes.items()):
                if val:
                    label = labels.get(key, key)
                    sign = "+" if val > 0 else ""
                    print(f"    {label}: {sign}{val}")

    # Seeds
    seeds = result.get("seeds", [])
    if seeds:
        print()
        print("  🌱 潜在影响:")
        for s in seeds:
            print(f"    • {s.get('description', s.get('title', ''))}")

    # NPC actions
    npc_actions = result.get("npc_actions", result.get("npc_reactions", []))
    if npc_actions:
        print()
        print("  天下动向:")
        for a in npc_actions:
            print(f"    {a}")

    # Events
    events = result.get("events_occurred", [])
    if events:
        print()
        print("  大事记:")
        for e in events:
            print(f"    📌 {e}")

    # Choices for next turn
    choices = result.get("new_choices", [])
    if choices:
        print()
        print("  可选方向:")
        for c in choices[:6]:
            print(f"    {c}")


# ─── State Display ──────────────────────────────────────────

def _display_state(engine: GameEngine):
    """Show the current game state."""
    ws = engine.world_state
    player = ws.get_player_faction()

    print(f"=== {ws.year}年 {ws.current_season_cn} ===")
    print(f"回合: {ws.turn}")

    if player:
        print(f"势力: {player.name}")
        print(f"兵力: {player.strength:,}")
        print(f"经济: {player.economy}/100")
        print(f"民心: {player.morale}/100")
        print(f"资金: {player.treasury:,}")
        print(f"粮草: {player.food:,}")
        print(f"领地: {', '.join(player.territories) if player.territories else '暂无'}")

    print(f"\n存檔位置: {DATA_DIR}")
    print("---")
