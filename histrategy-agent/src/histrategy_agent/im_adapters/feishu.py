"""
FeishuAdapter — Feishu (Lark) platform-specific message formatting.

Supports:
- Markdown messages (basic)
- Interactive cards (rich JSON format for Feishu API)
- Turn results, battle reports, onboarding rendered as cards
- Message splitting for long content
"""

from __future__ import annotations

from typing import Any

from .base import IMAdapter


class FeishuAdapter(IMAdapter):
    """Feishu-specific message formatting with rich card support.

    Feishu API message types:
    - 'text' — plain text (deprecated, use markdown)
    - 'interactive' — rich card (JSON)
    - 'post' — rich text (complex layout)

    This adapter uses 'interactive' cards for turn results and 'post'/markdown
    for simple messages. For MVP without actual Feishu API access, falls back
    to markdown rendering.
    """

    MAX_MESSAGE_LENGTH = 15000
    PLATFORM = "feishu"

    # ─── Basic message formatting ──────────────────────────

    def format_message(self, content: str) -> dict[str, Any]:
        """Return a Feishu-compatible message dict (markdown)."""
        return {
            "platform": "feishu",
            "content": content,
            "content_type": "markdown",
        }

    def format_error(self, error_message: str) -> dict[str, Any]:
        """Return error message with Feishu formatting."""
        return {
            "platform": "feishu",
            "content": f"❌ **错误**\n\n{error_message}",
            "content_type": "markdown",
        }

    # ─── Interactive card rendering ────────────────────────

    def render_interactive_card(
        self, title: str, body: str, actions: list[dict] | None = None
    ) -> dict[str, Any]:
        """Build a Feishu interactive card as proper JSON structure.

        When connected to Feishu API, this can be sent as msg_type='interactive'.
        Falls back to markdown for text-only channels.

        Args:
            title: Card title (supports markdown)
            body: Card body content (supports markdown)
            actions: List of action dicts with keys:
                - label: str — button text
                - value: str — action value/command
                - type: str — "primary"|"default"|"danger" (default: "default")
        """
        card = self._build_card_json(title, body, actions)
        return {
            "platform": "feishu",
            "content": card,
            "content_type": "interactive",
        }

    def _build_card_json(
        self, title: str, body: str, actions: list[dict] | None = None
    ) -> dict[str, Any]:
        """Build a Feishu card JSON structure.

        Conforms to Feishu Message Card schema:
        https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-components
        """
        header = {
            "title": {"tag": "plain_text", "content": title},
            "template": "wathet",  # Blue header
        }

        elements: list[dict] = [
            {"tag": "markdown", "content": body},
        ]

        # Add divider before actions
        if actions and len(actions) > 0:
            elements.append({"tag": "hr"})

            action_elements: list[dict] = []
            for action in actions:
                label = action.get("label", action.get("text", ""))
                value = action.get("value", "")
                btn_type = action.get("type", "default")

                action_elements.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": btn_type,
                    "value": {"command": value},
                })

            elements.append({
                "tag": "action",
                "actions": action_elements,
            })

        return {
            "header": header,
            "elements": elements,
        }

    # ─── Game-specific card renderers ──────────────────────

    def render_turn_card(
        self,
        year: int,
        season: str,
        turn: int,
        faction_name: str,
        narrative: str,
        stats: dict[str, Any],
        suggestions: list[str],
        events: list[str],
    ) -> dict[str, Any]:
        """Render a complete turn result as a Feishu interactive card.

        Args:
            year: Game year (e.g. 207)
            season: Chinese season name (春/夏/秋/冬)
            turn: Turn number
            faction_name: Player's faction name
            narrative: Main narrative text
            stats: Dict of stat name → value pairs
            suggestions: Suggested actions
            events: Notable events this turn
        """
        title = f"⚔️ {faction_name} | 建安{year}年 · {season} | 第{turn}回合"

        body_parts = []
        body_parts.append(f"**{narrative}**")
        body_parts.append("")

        # Stats section
        body_parts.append("📊 **势力概况**")
        for key, value in stats.items():
            emoji = self._stat_emoji(key)
            body_parts.append(f"{emoji} {key}: **{value}**")
        body_parts.append("")

        # Events section
        if events:
            body_parts.append("📜 **本回合事件**")
            for event in events[:8]:
                body_parts.append(f"• {event}")
            if len(events) > 8:
                body_parts.append(f"• ... 还有 {len(events) - 8} 条事件")
            body_parts.append("")

        body = "\n".join(body_parts)

        # Build action buttons from suggestions
        actions = []
        for i, s in enumerate(suggestions[:5]):
            actions.append({
                "label": f"{i + 1}. {s}",
                "value": s,
                "type": "primary" if i == 0 else "default",
            })

        return self.render_interactive_card(title, body, actions)

    def render_battle_card(
        self,
        attacker_name: str,
        defender_name: str,
        location: str,
        result_cn: str,
        attacker_losses: int,
        defender_losses: int,
        territory_captured: bool = False,
    ) -> dict[str, Any]:
        """Render a battle report as a Feishu card.

        Args:
            attacker_name: Attacking force name
            defender_name: Defending force name
            location: Battle location
            result_cn: Result in Chinese (大胜/胜利/平局/败北/大败)
            attacker_losses: Attacker casualties
            defender_losses: Defender casualties
            territory_captured: Whether territory was captured
        """
        title = f"⚔️ 战斗报告 — {location}"

        outcome_emoji = {
            "大胜": "🎉", "胜利": "✅", "平局": "🤝", "败北": "⚠️", "大败": "💔",
        }
        emoji = outcome_emoji.get(result_cn, "⚔️")

        body = (
            f"{emoji} **{result_cn}**\n\n"
            f"**攻击方**: {attacker_name}\n"
            f"**防守方**: {defender_name}\n\n"
            f"| 项目 | 数值 |\n"
            f"|------|------|\n"
            f"| 攻击方损失 | {attacker_losses:,} |\n"
            f"| 防守方损失 | {defender_losses:,} |\n"
        )

        if territory_captured:
            body += f"\n🏰 **已占领 {location}！**"

        return self.render_interactive_card(title, body)

    def render_faction_select_card(self) -> dict[str, Any]:
        """Render faction selection as an interactive card."""
        title = "🎌 三國志略 — 选择你的势力"

        body = (
            "汉室倾颓，奸臣当道。将军可愿匡扶天下？\n\n"
            "**可选势力**\n\n"
            "🟢 **刘备** — 汉室宗亲，仁义立世。寄居新野，急需卧龙出山。\n"
            "🔵 **曹操** — 汉丞相，雄才大略。挟天子以令诸侯，兵精粮足。\n"
            "🔴 **孙权** — 江东少主，继承父兄基业。坐断东南，水军强盛。\n"
            "🟡 **刘表** — 荆州牧，据守荆襄富庶之地。坐观天下变局。\n"
            "🟣 **刘璋** — 益州牧，天府之国。固守一方，偏安西蜀。\n"
        )

        actions = [
            {"label": "刘备", "value": "shu", "type": "primary"},
            {"label": "曹操", "value": "cao", "type": "default"},
            {"label": "孙权", "value": "wu", "type": "default"},
            {"label": "刘表", "value": "liubiao", "type": "default"},
            {"label": "刘璋", "value": "liuzhang", "type": "default"},
        ]

        return self.render_interactive_card(title, body, actions)

    def render_onboarding_card(
        self,
        faction_name: str,
        faction_intro: str,
        territories: list[str],
        heroes: list[str],
        year: int,
        season: str,
        treasury: int,
        food: int,
        prestige: int,
    ) -> dict[str, Any]:
        """Render new game onboarding as a rich card.

        Args:
            faction_name: Player faction name
            faction_intro: Descriptive intro text
            territories: List of starting territories
            heroes: List of key heroes
            year: Starting year
            season: Starting season
            treasury: Starting gold
            food: Starting food
            prestige: Starting prestige
        """
        title = f"🎌 {faction_name}势力 — 新游戏开始！"

        territory_str = "、".join(territories)
        hero_str = "、".join(heroes)

        body = (
            f"{faction_intro}\n\n"
            f"🏰 **领地**: {territory_str}\n"
            f"👥 **大将**: {hero_str}\n\n"
            f"📅 **建安{year}年 · {season}**\n"
            f"💰 金库: **{treasury:,}** | 🌾 粮草: **{food:,}** | ⭐ 声望: **{prestige}**\n\n"
            f"💡 **玩法提示**\n"
            f"• 用自然语言下达指令，如「进攻洛阳」「招募步兵」\n"
            f"• 输入「状态」查看当前局势\n"
            f"• 每回合都有建议行动供你选择\n\n"
            f"─── 汉室倾颓，奸臣当道。将军可愿匡扶天下？───"
        )

        actions = [
            {"label": "查看全图", "value": "map", "type": "default"},
            {"label": "开始行动", "value": "ready", "type": "primary"},
        ]

        return self.render_interactive_card(title, body, actions)

    def render_state_summary_card(
        self,
        faction_name: str,
        year: int,
        season: str,
        turn: int,
        territories: list[dict],
        total_troops: int,
        treasury: int,
        food: int,
        prestige: int,
        tax_rate: float,
        allies: list[str],
        enemies: list[str],
        armies: list[dict],
    ) -> dict[str, Any]:
        """Render state summary as a Feishu card.

        Args:
            faction_name: Faction name
            year: Game year
            season: Current season
            turn: Turn number
            territories: List of {name, population, development, garrison} dicts
            total_troops: Total military strength
            treasury: Gold reserves
            food: Food reserves
            prestige: Prestige rating
            tax_rate: Current tax rate
            allies: Allied faction IDs
            enemies: Enemy faction IDs
            armies: List of {id, location, troops, morale} dicts
        """
        title = f"📊 {faction_name} | 建安{year}年 · {season} | 第{turn}回合"

        body_parts = []

        # Territories
        body_parts.append("🏰 **领地**")
        for t in territories:
            body_parts.append(
                f"• {t['name']} | 人口: {t.get('population', 0):,} "
                f"| 发展: {t.get('development', 0)} | 守军: {t.get('garrison', 0):,}"
            )
        body_parts.append("")

        # Military
        body_parts.append("⚔️ **军事**")
        for army in armies:
            body_parts.append(
                f"• {army['id']} @ {army['location']} | "
                f"兵力: {army.get('troops', 0):,} | 士气: {army.get('morale', 0)}"
            )
        body_parts.append(f"**总兵力: {total_troops:,}**")
        body_parts.append("")

        # Resources
        body_parts.append("💰 **资源**")
        body_parts.append(f"• 金库: {treasury:,}")
        body_parts.append(f"• 粮草: {food:,}")
        body_parts.append(f"• 声望: {prestige}")
        body_parts.append(f"• 税率: {tax_rate:.0%}")
        body_parts.append("")

        # Diplomacy
        body_parts.append("🤝 **外交**")
        if allies:
            body_parts.append(f"• 盟友: {', '.join(allies)}")
        else:
            body_parts.append("• 暂无盟友")
        if enemies:
            body_parts.append(f"• 敌对: {', '.join(enemies)}")
        body_parts.append("")

        body = "\n".join(body_parts)

        actions = [
            {"label": "刷新状态", "value": "status", "type": "default"},
            {"label": "查看全图", "value": "map", "type": "default"},
        ]

        return self.render_interactive_card(title, body, actions)

    def render_help_card(self) -> dict[str, Any]:
        """Render help/command reference as a card."""
        title = "🎌 三國志略 — 帮助"

        body = (
            "**命令列表**\n\n"
            "• `/histrategy new` — 开始新游戏\n"
            "• `/histrategy new shu` — 直接以刘备开始\n"
            "• `/histrategy load` — 加载存档\n"
            "• `/histrategy status` — 查看状态\n"
            "• `/histrategy delete` — 删除存档\n\n"
            "**游戏指令**（自然语言）\n\n"
            "• 军事: 「进攻宛城」「招募三千骑兵」\n"
            "• 内政: 「开发新野」「税收30%」\n"
            "• 外交: 「与孙权结盟」「与曹操断交」\n"
            "• 情报: 「查看天下大势」「查看状态」\n\n"
            "**多人模式**（群聊）\n\n"
            "• `/histrategy join` — 加入多人游戏\n"
            "• `/histrategy start` — 开始游戏（房主）\n"
        )

        actions = [
            {"label": "开始新游戏", "value": "new", "type": "primary"},
            {"label": "查看状态", "value": "status", "type": "default"},
        ]

        return self.render_interactive_card(title, body, actions)

    # ─── Helpers ───────────────────────────────────────────

    @staticmethod
    def _stat_emoji(key: str) -> str:
        """Map stat keys to emoji icons."""
        emoji_map = {
            "领地": "🏰", "领土": "🏰",
            "兵力": "⚔️", "军队": "⚔️", "总兵力": "⚔️",
            "粮草": "🌾", "粮食": "🌾",
            "声望": "⭐",
            "金库": "💰", "资金": "💰", "金币": "💰",
            "税率": "📊",
            "发展度": "📈",
        }
        for k, v in emoji_map.items():
            if k in key:
                return v
        return "📌"

    @staticmethod
    def detect() -> bool:
        """Auto-detect if running in Feishu context.

        Always returns True for MVP since Feishu is the primary platform.
        """
        return True
