"""
FormatEngine — renders game output as platform-specific text/cards.

All user-facing text is in Chinese (Simplified) by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine import CombatResult, WorldState

from .session import GameSession
from .turn_processor import TurnResult


class FormatEngine:
    """Formats game output for different IM platforms."""

    def render_turn_result(self, result: TurnResult, platform: str = "feishu") -> str:
        """Render complete turn output as markdown text for the platform."""
        ws = result.world_snapshot
        year = ws.get("year", 207)
        season = ws.get("season", "春")
        turn = ws.get("turn", 1)

        lines = []
        lines.append(f"🎌 **建安{year}年 · {season}** | 回合 #{turn}")
        lines.append("")
        lines.append(f"> {result.narrative}")
        lines.append("")

        if result.map_ascii:
            lines.append("🗺️ **天下大势**")
            lines.append("```")
            lines.append(result.map_ascii)
            lines.append("```")
            lines.append("")

        lines.append("⚔️ **我军态势**")
        territories = "、".join(
            t.get("name", "") for t in ws.get("territories", [])
        ) or "无"
        lines.append(f"| 领地 | {territories} |")
        lines.append(f"| 兵力 | {ws.get('total_troops', 0):,} |")
        lines.append(f"| 粮草 | {ws.get('food', 0):,} |")
        lines.append(f"| 声望 | {ws.get('prestige', 0)} |")
        lines.append(f"| 金库 | {ws.get('treasury', 0):,} |")
        lines.append("")

        if result.events:
            lines.append("📜 **本回合事件**")
            for event in result.events[:10]:
                lines.append(f"- {event}")
            lines.append("")

        if result.suggestions:
            lines.append("📋 **可选行动**")
            for i, s in enumerate(result.suggestions, 1):
                lines.append(f"{i}. {s}")
            lines.append("")

        return "\n".join(lines).strip()

    def render_state_summary(self, session: GameSession) -> str:
        """Render faction overview + territory list + military strength."""
        ws = session.world_state
        faction = ws.factions.get(session.player_faction_id)
        if not faction:
            return "无存档数据"

        lines = []
        lines.append(f"🎌 **{faction.name}** | 建安{ws.year}年 · {ws.season.cn} | 回合 #{ws.turn_number}")
        lines.append("")

        # Territories
        lines.append("🏰 **领地**")
        for tid in faction.territories:
            territory = ws.territories.get(tid)
            if territory:
                lines.append(
                    f"- {territory.name} | 人口: {territory.population:,} | "
                    f"发展: {territory.development} | 守军: {territory.garrison:,}"
                )
        lines.append("")

        # Military
        lines.append("⚔️ **军事**")
        total_troops = 0
        for army in ws.armies.values():
            if army.faction_id == session.player_faction_id:
                unit_desc = "、".join(
                    f"{ut.value}{c}" for ut, c in army.units.items() if c > 0
                )
                lines.append(
                    f"- {army.id} 位置: {army.location} | "
                    f"兵力: {army.total_troops:,} ({unit_desc}) | "
                    f"士气: {army.morale}"
                )
                total_troops += army.total_troops
        if total_troops == 0:
            lines.append("- 暂无军队")
        lines.append(f"**总兵力: {total_troops:,}**")
        lines.append("")

        # Resources
        lines.append("💰 **资源**")
        lines.append(f"- 金库: {faction.treasury:,}")
        lines.append(f"- 粮草: {faction.food:,}")
        lines.append(f"- 声望: {faction.prestige}")
        lines.append(f"- 税率: {faction.tax_rate:.0%}")
        lines.append("")

        # Diplomacy
        lines.append("🤝 **外交**")
        if faction.allies:
            for aid in faction.allies:
                ally = ws.factions.get(aid)
                lines.append(f"- 盟友: {ally.name if ally else aid}")
        else:
            lines.append("- 暂无盟友")
        if faction.enemies:
            for eid in faction.enemies:
                enemy = ws.factions.get(eid)
                lines.append(f"- 敌对: {enemy.name if enemy else eid}")
        lines.append("")

        return "\n".join(lines).strip()

    def render_map_ascii(self, world_state: WorldState, faction_id: str) -> str:
        """Render a simplified ASCII map showing controlled territories."""
        faction_symbols = {
            "shu": "蜀",
            "cao": "魏",
            "wu": "吴",
            "liubiao": "荆",
            "liuzhang": "益",
        }

        player_faction = world_state.factions.get(faction_id)
        capital_id = player_faction.capital if player_faction else ""

        lines = []
        lines.append("天下大势图")
        lines.append("─" * 40)

        for tid, territory in sorted(world_state.territories.items()):
            owner = territory.owner_id
            symbol = faction_symbols.get(owner, "·")
            marker = "★" if tid == capital_id else "  "
            name = territory.name
            neighbors = " → ".join(
                world_state.territories[n].name if n in world_state.territories else n
                for n in territory.neighbors[:2]
            )
            lines.append(f"[{symbol}] {name:<6} → {neighbors}")

        lines.append("─" * 40)
        lines.append("蜀=刘备 魏=曹操 吴=孙权 荆=刘表 益=刘璋")
        return "\n".join(lines)

    def render_battle_card(self, battle: CombatResult) -> str:
        """Render a battle report as markdown."""
        result_cn = {
            "decisive_victory": "大胜",
            "victory": "胜利",
            "draw": "平局",
            "defeat": "败北",
            "decisive_defeat": "大败",
        }
        result_text = result_cn.get(
            battle.result.value if hasattr(battle.result, "value") else str(battle.result),
            str(battle.result),
        )

        lines = []
        lines.append(f"⚔️ **战斗报告** — {battle.location}")
        lines.append("")
        lines.append(f"| 内容 | 详情 |")
        lines.append(f"|------|------|")
        lines.append(f"| 攻击方 | {battle.attacker_id} |")
        lines.append(f"| 防守方 | {battle.defender_id} |")
        lines.append(f"| 结果 | **{result_text}** |")

        if battle.attacker_casualties:
            atk_loss = sum(battle.attacker_casualties.values())
            lines.append(f"| 攻击方损失 | {atk_loss:,} |")

        if battle.defender_casualties:
            def_loss = sum(battle.defender_casualties.values())
            lines.append(f"| 防守方损失 | {def_loss:,} |")

        if battle.territory_captured:
            lines.append(f"| 领土占领 | 成功占领{battle.location} |")

        lines.append("")
        return "\n".join(lines)

    def render_onboarding(self, session: GameSession) -> str:
        """Render new game welcome message with faction intro and starting state."""
        faction = session.world_state.factions.get(session.player_faction_id)
        if not faction:
            return "游戏初始化失败"

        faction_intros = {
            "shu": (
                "汉室宗亲刘备，以仁义立世，心怀匡扶汉室之志。"
                "目前寄居新野，兵微将寡，急需卧龙出山，谋定天下。"
                "\n\n**初始领土**: 新野\n**大将**: 关羽、张飞、赵云"
            ),
            "cao": (
                "汉丞相曹操，雄才大略，挟天子以令诸侯。"
                "拥兖豫之地，兵精粮足，虎视天下。"
                "\n\n**初始领土**: 许昌、宛城、洛阳、邺城等\n**大将**: 夏侯渊、张郃、张辽、司马懿"
            ),
            "wu": (
                "江东孙权，继承父兄基业，坐断东南。"
                "水军强盛，人才济济，伺机北伐中原。"
                "\n\n**初始领土**: 建业、柴桑、吴郡\n**大将**: 周瑜、鲁肃、吕蒙、陆逊"
            ),
        }

        intro = faction_intros.get(
            session.player_faction_id,
            f"欢迎来到三國志略！您将扮演{faction.name}，在乱世中争霸天下。",
        )

        lines = []
        lines.append(f"🎌 **三國志略** — 新游戏开始！")
        lines.append("")
        lines.append(f"**{faction.name}势力**")
        lines.append("")
        lines.append(intro)
        lines.append("")
        lines.append(f"📅 **建安207年 · 冬**")
        lines.append(f"💰 金库: {faction.treasury:,} | 🌾 粮草: {faction.food:,} | ⭐ 声望: {faction.prestige}")
        lines.append("")
        lines.append("💡 **玩法提示**")
        lines.append("- 用自然语言下达指令，如「进攻洛阳」「招募步兵」")
        lines.append("- 输入「状态」查看当前局势")
        lines.append("- 每回合都有建议行动供你选择")
        lines.append("")
        lines.append("─── 汉室倾颓，奸臣当道。将军可愿匡扶天下？───")

        return "\n".join(lines)

    def render_suggestions(self, suggestions: list[str]) -> str:
        """Format suggestions as a numbered list."""
        lines = ["📋 **可选行动**"]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. {s}")
        return "\n".join(lines)
