"""三國志略 - CLI module with enhanced game loop."""
from __future__ import annotations

import os
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich import box
from rich.prompt import Prompt
from rich.align import Align

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter, detect_provider

console = Console()

ASCII_TITLE = r"""
       / \   |  _ \ / \  |_ _|_   _| \ | |_ _|  _ \ 
      / _ \  | |_) / _ \  | |  | | |  \| || || |_) |
     / ___ \ |  __/ ___ \ | |  | | | |\  || ||  _ < 
    /_/   \_\|_| /_/   \_\|___| |_| |_| \_|___|_| \_\

   ⚔  A Text-Based History Strategy Game Powered by AI ⚔
"""


def run_game():
    """Main game loop."""
    console.clear()
    _print_title()

    # --- Provider detection ---
    provider_info = detect_provider()
    llm = None

    if provider_info["name"]:
        llm = LLMAdapter()
        console.print(Panel(
            f"[bold green]✓ 检测到 {provider_info['name']} API[/] ({provider_info['model']})",
            border_style="green",
            title="🤖 AI模式",
        ))
    else:
        console.print(Panel(
            "[bold yellow]⚠ 未检测到 API Key，将启动离线模式[/]\n\n"
            "离线模式基于事件驱动的规则引擎，有完整的战役/内政/外交体验。\n"
            "要体验 AI 生成的动态叙事，请设置环境变量：\n\n"
            "  export DEEPSEEK_API_KEY='sk-...'   # 推荐，价格低\n"
            "  export OPENAI_API_KEY='sk-...'     # OpenAI 兼容\n"
            "  export TONGYI_API_KEY='...'        # 通义千问\n",
            title="三國志略 · 离线模式",
            border_style="yellow",
        ))
        console.print("[dim]按回车开始...[/]")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass

    engine = GameEngine(llm=llm)

    # --- Faction Selection ---
    factions = [
        {"id": "cao", "name": "曹操军", "ruler": "曹操", "strength": 30000,
         "description": "乱世奸雄，奉天子以令不臣"},
        {"id": "shu", "name": "刘备军", "ruler": "刘备", "strength": 5000,
         "description": "汉室宗亲，以仁德取天下"},
        {"id": "wu", "name": "孙坚军", "ruler": "孙坚", "strength": 20000,
         "description": "江东猛虎，据长江天险"},
        {"id": "yuan_shao", "name": "袁绍军", "ruler": "袁绍", "strength": 80000,
         "description": "四世三公，讨董盟主"},
    ]

    console.print("\n[bold cyan]选择你的君主[/]\n")

    faction_table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    faction_table.add_column("#", style="yellow", width=3)
    faction_table.add_column("势力", style="bold", width=15)
    faction_table.add_column("君主", width=12)
    faction_table.add_column("兵力", justify="right", width=10)
    faction_table.add_column("简介", width=35)

    for i, f in enumerate(factions, 1):
        faction_table.add_row(str(i), f["name"], f["ruler"],
                              f"{f['strength']:,}", f["description"])

    console.print(faction_table)
    console.print()

    choice = Prompt.ask("请选择",
                        choices=[str(i) for i in range(1, len(factions) + 1)],
                        default="1")
    selected = factions[int(choice) - 1]
    engine.set_player_faction(selected["id"])

    # --- Intro Scene ---
    console.clear()
    _print_title()
    console.print(Panel(
        f"[bold]{selected['name']}[/] - [italic]{selected['description']}[/]\n"
        f"[dim]初平元年（190 AD）春季 | {selected['name']}，兵力 {selected['strength']:,}[/]",
        border_style="cyan",
        title="⚔ 开局",
    ))
    console.print()

    with console.status("[yellow]天机运转，推演天下大势...[/]", spinner="dots"):
        intro = engine.get_intro_scene()

    display_season_report(engine, intro)

    # --- Game Loop ---
    while True:
        console.print()
        player_decision = get_player_input()
        if player_decision is None:
            break

        with console.status("[yellow]天机运转，推演天下大势...[/]", spinner="dots"):
            result = engine.process_turn(player_decision)

        console.clear()
        _print_title()

        display_season_report(engine, result)

        # Check for game over (from the enhanced offline sim)
        game_over = result.get("game_over")
        if game_over:
            _display_game_over(game_over)
            final_choice = Prompt.ask("请选择", choices=["1", "2"], default="1")
            if final_choice == "1":
                # Restart
                engine = GameEngine(llm=llm)
                # For restart, we'd need to re-select faction
                # For now, just exit
            break


def display_season_report(engine: GameEngine, result: dict):
    """Display a season report to the player."""
    world = engine.world
    player = world.get_player_faction()

    if not player:
        console.print("[red]你的势力已经不复存在...[/]")
        return

    # Header: Date + Status
    date_str = f"{world.current_year}年·{_season_cn(world.current_season)}"
    header = Panel(
        f"[bold yellow]{date_str}[/] | "
        f"兵力: [cyan]{player.strength:,}[/] | "
        f"经济: [green]{player.economy}/100[/] | "
        f"民心: [magenta]{player.morale}/100[/] | "
        f"资金: [yellow]{player.treasury:,}[/] | "
        f"粮草: [yellow]{player.food:,}[/]",
        border_style="bright_blue",
    )
    console.print(header)

    # Narrative
    narrative_text = result.get("narrative", "")
    if narrative_text:
        console.print()
        console.print(Panel(
            narrative_text,
            border_style="green",
            title="📜 军师来报",
            title_align="left",
        ))

    # NPC Actions
    npc_actions = result.get("npc_actions", [])
    if npc_actions:
        console.print()
        action_lines = "\n".join(f"  ⚡ {a}" for a in npc_actions)
        console.print(Panel(
            action_lines,
            border_style="yellow",
            title="🌍 天下动向",
            title_align="left",
        ))

    # Events
    events = result.get("events_occurred", [])
    if events:
        console.print()
        event_lines = "\n".join(f"  📌 {e}" for e in events)
        console.print(Panel(
            event_lines,
            border_style="red",
            title="⚡ 大事记",
            title_align="left",
        ))

    # Choices
    choices = result.get("new_choices", [])
    if choices and not result.get("game_over"):
        console.print()
        choice_grid = Table.grid(padding=(0, 2))
        for c in choices:
            num = c.split(".", 1)[0].strip() if "." in c else "?"
            text = c.split(".", 1)[1].strip() if "." in c else c
            choice_grid.add_row(f"[bold yellow]{num}.[/]", text)
        console.print(Panel(
            choice_grid,
            border_style="cyan",
            title="🎯 可选择的战略方向",
            title_align="left",
        ))


def _print_title():
    """Print the game title ASCII art."""
    console.print(Panel(
        Align(Text(ASCII_TITLE, style="bold yellow"), align="center"),
        border_style="red",
        padding=1,
    ))
    console.print(Align(
        "[italic yellow]初平元年，汉室倾颓，群雄逐鹿。\n"
        "你将扮演一方诸侯，在这个风云激荡的时代书写你的传奇。[/]",
        align="center",
    ))


def _display_game_over(game_over: dict):
    """Display game over screen."""
    console.print()
    console.print(Panel(
        Markdown(game_over["message"]),
        border_style="bright_red" if game_over["type"] == "defeat" else "bright_green",
        title="🏁 游戏结束",
        title_align="center",
        padding=2,
    ))
    console.print()


def _season_cn(season: str) -> str:
    mapping = {
        "spring": "春季", "summer": "夏季",
        "autumn": "秋季", "winter": "冬季",
    }
    return mapping.get(season, season)


def get_player_input() -> Optional[str]:
    """Get player's strategic decision."""
    console.print()
    console.print("[bold cyan]你的战略决策：[/]")
    console.print("[dim]（比如：'联合袁绍讨伐董卓'、'发展经济训练新军'、'派间谍潜入长安'[/]")
    console.print("[dim]  或直接输入选项编号，如 '1'）[/]")
    try:
        decision = Prompt.ask("", default="1")
        if decision.lower() in ("exit", "quit", "退出", "q"):
            return None
        if decision.strip().isdigit():
            decision = f"选择第{decision}个方案"
        return decision
    except (EOFError, KeyboardInterrupt):
        return None


def main():
    try:
        run_game()
    except KeyboardInterrupt:
        console.print("\n[yellow]退出游戏。[/]")
    except Exception as e:
        console.print(f"\n[red]游戏出错：{e}[/]")
        import traceback
        console.print(traceback.format_exc())
