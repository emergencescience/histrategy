"""
三國志略 — Dev CLI Mode

A plain-text input/output interface for the game, accessible via:
    histrategy --dev

This mode:
- Uses simple stdin/stdout (no Rich TUI)
- Is perfect for E2E testing and debugging
- Outputs structured text that's easy to parse
- Shows the full world state after each turn

Usage:
    histrategy --dev
    histrategy --dev --faction 2    # start with specific faction
    histrategy --dev --new           # force new game (ignore save)

Input format:
    Just type your strategic decision as natural text.
    Or type 'exit'/'quit' to quit.
    Or type 'state' to see full world state.

Output format:
    Plain text with --- section separators.
    Easy to grep/parse for testing.
"""

from __future__ import annotations

import sys
import os
from typing import Optional

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter, detect_provider
from ..state.world_state import has_existing_game, DATA_DIR


def run_dev(faction_choice: Optional[int] = None, force_new: bool = False):
    """
    Run the game in dev mode (plain text input/output).

    Args:
        faction_choice: Pre-select faction index (1-4), or None to ask
        force_new: If True, ignore any existing save game
    """
    provider_info = detect_provider()
    llm = None

    if provider_info["name"]:
        llm = LLMAdapter()
        print(f"[系统] 检测到 {provider_info['name']} API ({provider_info['model']})", file=sys.stderr)
    else:
        print("[系统] 未检测到 API Key，将启动离线模式", file=sys.stderr)
        print("[系统] 设置 DEEPSEEK_API_KEY 可体验AI驱动的世界模型", file=sys.stderr)

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
        _game_loop.last_result = intro

    # Game loop
    _game_loop(engine, llm)


def _game_loop(engine: GameEngine, llm: Optional[LLMAdapter]):
    """The main game loop in dev mode.
    
    Flow:
    1. Generate Plan Mode (advisors + suggestions based on current state)
    2. Show Plan Mode to player  
    3. Player makes decision
    4. Process turn → Command Mode executes
    5. Show Command Mode results (bureaucracy, short-term, seeds)
    """
    from histrategy.engine.advisors import generate_plan_mode
    
    while True:
        try:
            # ═══ PLAN MODE ═══════════════════════════════════
            plan = generate_plan_mode(engine.world_state)
            
            # Show court assembly
            if plan.get("advisors"):
                print("\n=== 内政会议 ===")
                for adv in plan["advisors"]:
                    style = {
                        "cautious": "  🛡 ", "aggressive": "  ⚔ ",
                        "scheming": "  🕵 ", "pragmatic": "  📋 ",
                        "strict": "  📜 ", "friendly": "  🤝 ", "proud": "  🐉 ",
                    }.get(adv.get("temperament", ""), "  💬 ")
                    print(f"{style}{adv['name']}（{adv['title']}）:")
                    print(f"    {adv['speech']}")
                print()
            
            # Show suggestions
            suggestions = plan.get("suggestions", [])
            if suggestions:
                print("---")
                print("军师建议的方案:")
                for c in suggestions:
                    print(f"  {c}")
                print()
            
            # Player input
            print()
            decision = input("你的决策: ").strip()
            if decision.lower() in ("exit", "quit", "退出", "q"):
                print("\n退出游戏", file=sys.stderr)
                break
            if decision.lower() in ("state", "状态"):
                _display_state(engine)
                continue
            if not decision:
                print("[系统] 请输入你的决策", file=sys.stderr)
                continue
            
            # ═══ COMMAND MODE ════════════════════════════════
            # If player typed a number, use the suggestion text
            if decision.strip().isdigit() and suggestions:
                idx = int(decision) - 1
                if 0 <= idx < len(suggestions):
                    suggestion_text = suggestions[idx]
                    # Extract just the strategy name, not the number
                    if ". " in suggestion_text:
                        decision = suggestion_text.split(". ", 1)[1]
                    else:
                        decision = suggestion_text
            
            print("---", file=sys.stderr)
            print("[系统] 正在推演天下大势...", file=sys.stderr)
            
            result = engine.process_turn(decision)
            
            # ═══ DISPLAY COMMAND MODE RESULTS ════════════════
            print("\n=== 政令执行 ===")
            
            # Bureaucracy report
            bureaucracy = result.get("bureaucracy", [])
            if bureaucracy:
                for dept in bureaucracy:
                    dept_name = dept.get("department", "")
                    official = dept.get("official", "")
                    action = dept.get("action", "")
                    prefix = f"[{dept_name}" + (f"·{official}" if official else "") + "]"
                    print(f"  {prefix} {action}")
            else:
                # Fallback: show narrative
                narrative = result.get("narrative", "")
                if narrative:
                    print(f"  {narrative[:200]}")
            
            # Short-term effects
            short_term = result.get("short_term", {})
            changes = short_term.get("changes", result.get("state_changes", {}))
            if changes:
                player_changes = {k: v for k, v in changes.items() if k not in ("npc_changes", "changes", "before", "after")}
                if any(player_changes.values()):
                    print()
                    print("  本季变化:")
                    labels = {"strength": "兵力", "economy": "经济", "morale": "民心",
                              "treasury": "资金", "food": "粮草"}
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
                    print(f"    • {s.get('description', '')}")
            
            # NPC reactions
            npc_actions = result.get("npc_actions", result.get("npc_reactions", []))
            if npc_actions:
                print()
                print("  天下动向:")
                for a in npc_actions[:3]:
                    print(f"    {a}")
            
            # Events
            events = result.get("events_occurred", [])
            if events:
                print()
                print("  大事记:")
                for e in events[:3]:
                    print(f"    📌 {e}")
            
            _game_loop.last_result = result
            
        except (EOFError, KeyboardInterrupt):
            print("\n退出游戏", file=sys.stderr)
            break


def _display_result(result: dict):
    """Display a turn result in dev mode."""
    # ═══ PLAN MODE ═══════════════════════════════════════
    advisors = result.get("advisors", [])
    if advisors:
        print("=== 内政会议 ===")
        for adv in advisors:
            style = {
                "cautious": "  🛡 ",
                "aggressive": "  ⚔ ",
                "scheming": "  🕵 ",
                "pragmatic": "  📋 ",
                "strict": "  📜 ",
                "friendly": "  🤝 ",
                "proud": "  🐉 ",
            }.get(adv.get("temperament", ""), "  💬 ")
            print(f"{style}{adv['name']}（{adv['title']}）:")
            print(f"    {adv['speech']}")
        print()

    # Suggestions
    suggestions = result.get("new_choices", result.get("suggestions", []))
    if suggestions:
        print("---")
        print("军师建议的方案:")
        for c in suggestions:
            print(f"  {c}")
        print()

    # ═══ COMMAND MODE ════════════════════════════════════

    # Narrative
    narrative = result.get("narrative", "")
    if narrative and not advisors:
        # Only show standalone narrative if no plan mode was shown
        # (Plan mode already shows it through bureaucracy)
        pass
    if narrative:
        print("---")
        print(narrative)

    # Bureaucracy execution report
    bureaucracy = result.get("bureaucracy", [])
    if bureaucracy:
        print("=== 政令执行 ===")
        for dept in bureaucracy:
            dept_name = dept.get("department", "")
            official = dept.get("official", "")
            action = dept.get("action", "")
            prefix = f"{dept_name}" + (f"（{official}）" if official else "")
            print(f"  [{prefix}] {action}")
        print()

    # Aftermath
    aftermath = result.get("aftermath", "")
    if aftermath:
        print("---")
        print(aftermath)

    # Short-term effects
    short_term = result.get("short_term", {})
    changes = short_term.get("changes", result.get("state_changes", {}))
    if changes:
        player_changes = {k: v for k, v in changes.items() if k not in ("npc_changes", "changes", "before", "after")}
        if player_changes:
            print("---")
            print("本季变化:")
            labels = {"strength": "兵力", "economy": "经济", "morale": "民心",
                      "treasury": "资金", "food": "粮草"}
            for key, val in sorted(player_changes.items()):
                if val:
                    label = labels.get(key, key)
                    sign = "+" if val > 0 else ""
                    print(f"  {label}: {sign}{val}")

    # Seeds (long-term consequences)
    seeds = result.get("seeds", [])
    if seeds:
        print("---")
        print("🌱 潜在影响:")
        for s in seeds:
            print(f"  • {s.get('title', '')} — {s.get('description', '')}")

    # NPC actions
    npc_actions = result.get("npc_actions", result.get("npc_reactions", []))
    if npc_actions:
        print("---")
        print("天下动向:")
        for a in npc_actions:
            print(f"  {a}")

    # Events
    events = result.get("events_occurred", [])
    if events:
        print("---")
        print("大事记:")
        for e in events:
            print(f"  📌 {e}")

    # Choices (if not already shown as suggestions)
    if not suggestions:
        choices = result.get("new_choices", [])
        if choices and not result.get("game_over"):
            print("---")
            print("可选择的战略方向:")
            for c in choices:
                print(f"  {c}")


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


# Initialize last result
_game_loop.last_result = None
