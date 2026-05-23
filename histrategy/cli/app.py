"""三國志略 - CLI module."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.text import Text
from rich.columns import Columns
from rich.markdown import Markdown
from rich import box
from rich.prompt import Prompt
from rich.align import Align

from ..engine.game import GameEngine
from ..llm.adapter import LLMAdapter

console = Console()

ASCII_TITLE = """
        / \\   |  _ \\ / \\  |_ _|_   _| \\ | |_ _|  _ \\ 
       / _ \\  | |_) / _ \\  | |  | | |  \\| || || |_) |
      / ___ \\ |  __/ ___ \\ | |  | | | |\\  || ||  _ < 
     /_/   \\_\\|_| /_/   \\_\\|___| |_| |_| \\_|___|_| \\_\\
                                                                                                    
    ⚔  A Text-Based History Strategy Game Powered by AI ⚔
"""


def render_faction_card(faction: dict, selected: bool = False) -> str:
    """Render a faction selection card."""
    ruler = faction.get("ruler", "?")
    name = faction["name"]
    desc = faction["description"]
    strength = f"{faction['strength']:,}"
    # Simple ASCII card
    card = f"""
┌─{'─' * 30}─┐
│ {'★' if selected else ' '} {name:<26} │
│   君主：{ruler:<22} │
│   兵力：{strength:<22} │
│   {desc:<28} │
└─{'─' * 30}─┘
"""
    return card


def run_game():
    """Main game loop."""
    console.clear()
    console.print()
    console.print(Panel(Align(Text(ASCII_TITLE, style="bold yellow"), align="center"),
                        border_style="red", padding=1))
    console.print(Align("[italic yellow]初平元年，汉室倾颓，群雄逐鹿。\n你将扮演一方诸侯，在这个风云激荡的时代书写你的传奇。[/]", align="center"))
    console.print()

    # --- API Key check ---
    api_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("HERMES_API_KEY", "")
    api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    # Try to detect Hermes provider
    hermes_provider = os.environ.get("HERMES_PROVIDER")
    if hermes_provider and not api_key:
        # We might need to configure this differently
        pass

    if not api_key:
        console.print(Panel(
            "[bold yellow]⚠ 未检测到 API Key，将启动离线模式[/]\n\n"
            "离线模式基于规则引擎模拟，适合体验游戏概念。\n"
            "要体验 AI 生成的动态叙事，请设置环境变量：\n"
            "  export OPENAI_API_KEY='your-key-here'\n"
            "  export OPENAI_API_BASE='https://api.openai.com/v1'\n"
            "  export LLM_MODEL='gpt-4o-mini'\n",
            title="三國志略 · 离线模式",
            border_style="yellow",
        ))
        console.print("[dim]按回车继续...[/]")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass

    # --- Initialize Engine ---
    llm = None
    if api_key:
        llm = LLMAdapter(
            api_key=api_key,
            api_base=api_base,
            model=model,
        )
    engine = GameEngine(llm=llm)

    # --- Faction Selection ---
    factions = [
        {"id": "cao", "name": "曹操军", "ruler": "曹操", "strength": 30000, "description": "乱世奸雄，奉天子以令不臣"},
        {"id": "shu", "name": "刘备军", "ruler": "刘备", "strength": 5000, "description": "汉室宗亲，以仁德取天下"},
        {"id": "wu", "name": "孙坚军", "ruler": "孙坚", "strength": 20000, "description": "江东猛虎，据长江天险"},
        {"id": "yuan_shao", "name": "袁绍军", "ruler": "袁绍", "strength": 80000, "description": "四世三公，讨董盟主"},
    ]

    console.print("[bold cyan]选择你的君主[/]")

    faction_table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    faction_table.add_column("#", style="yellow", width=3)
    faction_table.add_column("势力", style="bold", width=15)
    faction_table.add_column("君主", width=12)
    faction_table.add_column("兵力", justify="right", width=10)
    faction_table.add_column("简介", width=35)

    for i, f in enumerate(factions, 1):
        faction_table.add_row(str(i), f["name"], f["ruler"], f"{f['strength']:,}", f["description"])

    console.print(faction_table)
    console.print()

    choice = Prompt.ask("请选择", choices=[str(i) for i in range(1, len(factions)+1)], default="1")
    selected = factions[int(choice) - 1]
    engine.set_player_faction(selected["id"])

    console.clear()
    console.print(Panel(
        f"[bold yellow]{ASCII_TITLE}[/]",
        border_style="red",
    ))
    console.print()
    console.print(Panel(
        f"[bold]{selected['name']}[/] - [italic]{selected['description']}[/]\n"
        f"[dim]初平元年（190 AD）春季 | {selected['name']}，兵力 {selected['strength']:,}[/]",
        border_style="cyan",
        title="⚔ 开局",
    ))
    console.print()

    # --- Initial Scene ---
    with console.status("[yellow]天机运转，推演天下大势...[/]", spinner="dots"):
        intro = engine.get_intro_scene()

    display_season_report(engine, intro)
    console.print()

    # --- Game Loop ---
    while True:
        player_decision = get_player_input()
        if player_decision is None:
            break

        with console.status("[yellow]天机运转，推演天下大势...[/]", spinner="dots"):
            result = engine.process_turn(player_decision)

        display_season_report(engine, result)
        console.print()
        console.print("[dim]─" * 50 + "[/]")

        # Check for game over
        player = engine.world.get_player_faction()
        if player and player.strength <= 0:
            console.print(Panel("[bold red]你的势力已覆灭。[/]", border_style="red"))
            break


def display_season_report(engine: GameEngine, result: dict):
    """Display a season report to the player."""
    world = engine.world
    player = world.get_player_faction()

    # --- Header: Date + Faction Status ---
    date_str = f"{world.current_year}年·{season_cn(world.current_season)}"
    header = Panel(
        f"[bold yellow]{date_str}[/] | "
        f"{'兵力' if player else ''}: [cyan]{player.strength:,}[/] | "
        f"{'经济' if player else ''}: [green]{player.economy}/100[/] | "
        f"{'民心' if player else ''}: [magenta]{player.morale}/100[/] | "
        f"{'资金' if player else ''}: [yellow]{player.treasury:,}[/] | "
        f"{'粮草' if player else ''}: [yellow]{player.food:,}[/]",
        border_style="bright_blue",
    )
    console.print(header)
    console.print()

    # --- Narrative ---
    narrative_text = result.get("narrative", "")
    if narrative_text:
        console.print(Panel(
            narrative_text,
            border_style="green",
            title="📜 军师来报",
            title_align="left",
        ))
        console.print()

    # --- NPC Actions ---
    npc_actions = result.get("npc_actions", [])
    if npc_actions:
        action_lines = "\n".join(f"  ⚡ {a}" for a in npc_actions)
        console.print(Panel(
            action_lines,
            border_style="yellow",
            title="🌍 天下动向",
            title_align="left",
        ))
        console.print()

    # --- Events ---
    events = result.get("events_occurred", [])
    if events:
        event_lines = "\n".join(f"  📌 {e}" for e in events)
        console.print(Panel(
            event_lines,
            border_style="red",
            title="⚡ 大事记",
            title_align="left",
        ))
        console.print()

    # --- Choices ---
    choices = result.get("new_choices", [])
    if choices:
        choice_panel = Table.grid(padding=(0, 2))
        for c in choices:
            num = c.split(".", 1)[0].strip() if "." in c else "?"
            text = c.split(".", 1)[1].strip() if "." in c else c
            choice_panel.add_row(f"[bold yellow]{num}.[/]", text)
        console.print(Panel(
            choice_panel,
            border_style="cyan",
            title="🎯 可选择的战略方向",
            title_align="left",
        ))
        console.print()


def season_cn(season: str) -> str:
    mapping = {
        "spring": "春季", "summer": "夏季",
        "autumn": "秋季", "winter": "冬季",
    }
    return mapping.get(season, season)


def get_player_input() -> Optional[str]:
    """Get player's strategic decision."""
    console.print("[bold cyan]你的战略决策：[/]")
    console.print("[dim]（比如：'联合袁绍讨伐董卓'、'发展经济训练新军'、'派间谍潜入长安'\n"
                  "  或直接输入选项编号，如 '1'）[/]")
    try:
        decision = Prompt.ask("", default="1")
        if decision.lower() in ("exit", "quit", "退出", "save"):
            if decision.lower() in ("save",):
                console.print("[green]正在保存...[/]")
                # TODO: implement save
                pass
            return None
        # Map number choices
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
