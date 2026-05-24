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

    # Game loop
    _game_loop(engine, llm)


def _game_loop(engine: GameEngine, llm: Optional[LLMAdapter]):
    """The main game loop in dev mode."""
    while True:
        try:
            # Show choices
            last_result = getattr(_game_loop, "last_result", None)
            if last_result and last_result.get("new_choices"):
                print("\n=== 可选择的战略方向 ===")
                for c in last_result["new_choices"]:
                    print(f"  {c}")

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

            # Process turn
            print("---", file=sys.stderr)
            print("[系统] 正在推演天下大势...", file=sys.stderr)

            result = engine.process_turn(decision)

            # Display result
            print("=== 结果 ===")
            _display_result(result)

            _game_loop.last_result = result

        except (EOFError, KeyboardInterrupt):
            print("\n退出游戏", file=sys.stderr)
            break


def _display_result(result: dict):
    """Display a turn result in dev mode."""
    # Advisor feedback
    advisor = _format_advisor_feedback(result.get("advisor_feedback", {}))
    if advisor:
        print("---")
        print("幕府参议:")
        print(advisor)

    # Narrative
    narrative = result.get("narrative", "")
    if narrative:
        print("---")
        print(narrative)

    # Aftermath
    aftermath = result.get("aftermath", "")
    if aftermath:
        print("---")
        print(aftermath)

    # State changes
    changes = result.get("state_changes", {})
    if changes:
        player_changes = {k: v for k, v in changes.items() if k != "npc_changes"}
        if player_changes:
            print("---")
            print("状态变化:")
            labels = {"strength": "兵力", "economy": "经济", "morale": "民心",
                      "treasury": "资金", "food": "粮草"}
            for key, val in player_changes.items():
                label = labels.get(key, key)
                sign = "+" if val > 0 else ""
                print(f"  {label}: {sign}{val}" if val else "")

    # NPC actions
    npc_actions = result.get("npc_actions", [])
    if npc_actions:
        print("---")
        print("天下动向:")
        for a in npc_actions:
            print(f"  ⚡ {a}")

    # Events
    events = result.get("events_occurred", [])
    if events:
        print("---")
        print("大事记:")
        for e in events:
            print(f"  📌 {e}")

    # Choices
    choices = result.get("new_choices", [])
    if choices and not result.get("game_over"):
        print("---")
        print("可选择的战略方向:")
        for c in choices:
            print(f"  {c}")


def _format_advisor_feedback(feedback) -> str:
    """Format advisor feedback for plain-text dev output."""
    if not feedback:
        return ""
    if isinstance(feedback, str):
        return feedback.strip()
    if not isinstance(feedback, dict):
        return ""

    lines = []
    understanding = feedback.get("understanding")
    if understanding:
        lines.append(str(understanding))

    sections = [
        ("研判", feedback.get("strategic_read", [])),
        ("风险", feedback.get("risks", [])),
        ("本季可行", feedback.get("recommended_execution", [])),
    ]
    for title, items in sections:
        if isinstance(items, str):
            items = [items]
        if items:
            lines.append(f"{title}:")
            lines.extend(f"  - {item}" for item in items if item)

    question = feedback.get("clarifying_question")
    if question:
        lines.append("待主公决断:")
        lines.append(f"  - {question}")

    return "\n".join(lines).strip()


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
