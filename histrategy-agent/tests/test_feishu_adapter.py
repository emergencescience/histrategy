"""Tests for FeishuAdapter — rich card rendering."""

from histrategy_agent.im_adapters.feishu import FeishuAdapter


class TestFeishuAdapterBasics:
    """Basic formatting tests."""

    def setup_method(self):
        self.adapter = FeishuAdapter()

    def test_format_message(self):
        result = self.adapter.format_message("Hello")
        assert result["platform"] == "feishu"
        assert result["content"] == "Hello"
        assert result["content_type"] == "markdown"

    def test_format_error(self):
        result = self.adapter.format_error("Something went wrong")
        assert "错误" in result["content"]
        assert "Something went wrong" in result["content"]

    def test_detect(self):
        assert FeishuAdapter.detect() is True


class TestInteractiveCards:
    """Tests for Feishu interactive card JSON structure."""

    def setup_method(self):
        self.adapter = FeishuAdapter()

    def test_render_interactive_card_basic(self):
        result = self.adapter.render_interactive_card(
            "Test Title", "Test body content"
        )
        assert result["content_type"] == "interactive"
        card = result["content"]
        assert card["header"]["title"]["content"] == "Test Title"
        assert card["header"]["template"] == "wathet"
        assert len(card["elements"]) >= 1
        assert card["elements"][0]["tag"] == "markdown"
        assert card["elements"][0]["content"] == "Test body content"

    def test_render_interactive_card_with_actions(self):
        actions = [
            {"label": "Attack", "value": "attack_luoyang", "type": "primary"},
            {"label": "Defend", "value": "defend", "type": "default"},
        ]
        result = self.adapter.render_interactive_card(
            "Battle", "Enemy approaches!", actions
        )
        card = result["content"]
        # Should have markdown + hr + action
        assert len(card["elements"]) >= 3
        tags = [e["tag"] for e in card["elements"]]
        assert "markdown" in tags
        assert "hr" in tags
        assert "action" in tags

    def test_render_interactive_card_no_actions(self):
        result = self.adapter.render_interactive_card("Title", "Body")
        card = result["content"]
        # No hr or action if no actions
        tags = [e["tag"] for e in card["elements"]]
        assert "hr" not in tags
        assert "action" not in tags

    def test_card_action_button_structure(self):
        actions = [{"label": "Do Thing", "value": "cmd", "type": "danger"}]
        result = self.adapter.render_interactive_card("T", "B", actions)
        action_element = result["content"]["elements"][-1]
        assert action_element["tag"] == "action"
        btn = action_element["actions"][0]
        assert btn["tag"] == "button"
        assert btn["text"]["content"] == "Do Thing"
        assert btn["type"] == "danger"
        assert btn["value"] == {"command": "cmd"}


class TestGameCardRenderers:
    """Tests for game-specific card renderers."""

    def setup_method(self):
        self.adapter = FeishuAdapter()

    def test_render_turn_card(self):
        result = self.adapter.render_turn_card(
            year=207, season="冬", turn=3,
            faction_name="刘备",
            narrative="我军发起进攻，攻占宛城。",
            stats={"领地": "新野, 宛城", "兵力": "4,800", "金库": "2,800"},
            suggestions=["招募步兵", "休整一回合", "与吴联盟"],
            events=["攻占宛城", "曹操征收15000金"],
        )
        assert result["content_type"] == "interactive"
        card = result["content"]
        assert "刘备" in card["header"]["title"]["content"]
        assert "207" in card["header"]["title"]["content"]
        # Should have action buttons for suggestions
        body = card["elements"][0]["content"]
        assert "攻占宛城" in body

    def test_render_turn_card_many_events(self):
        events = [f"事件{i}" for i in range(15)]
        result = self.adapter.render_turn_card(
            year=207, season="春", turn=1,
            faction_name="曹操",
            narrative="test",
            stats={"兵力": "100,000"},
            suggestions=[],
            events=events,
        )
        body = result["content"]["elements"][0]["content"]
        # Should truncate at 8 + mention remaining
        assert "还有" in body
        assert "7" in body  # 15 - 8 = 7 remaining

    def test_render_battle_card_victory(self):
        result = self.adapter.render_battle_card(
            attacker_name="关羽军",
            defender_name="曹操军",
            location="宛城",
            result_cn="大胜",
            attacker_losses=500,
            defender_losses=3000,
            territory_captured=True,
        )
        card = result["content"]
        assert "大胜" in card["header"]["title"]["content"] or "大胜" in card["elements"][0]["content"]
        body = card["elements"][0]["content"]
        assert "关羽军" in body
        assert "已占领" in body

    def test_render_battle_card_defeat(self):
        result = self.adapter.render_battle_card(
            attacker_name="刘备军",
            defender_name="孙权军",
            location="柴桑",
            result_cn="大败",
            attacker_losses=5000,
            defender_losses=200,
        )
        body = result["content"]["elements"][0]["content"]
        assert "大败" in body
        assert "5,000" in body

    def test_render_faction_select_card(self):
        result = self.adapter.render_faction_select_card()
        card = result["content"]
        assert "三國志略" in card["header"]["title"]["content"]
        # Should have 5 faction buttons
        action_el = card["elements"][-1]
        assert len(action_el["actions"]) == 5

        btn_labels = [a["text"]["content"] for a in action_el["actions"]]
        assert "刘备" in btn_labels
        assert "曹操" in btn_labels
        assert "孙权" in btn_labels

    def test_render_onboarding_card(self):
        result = self.adapter.render_onboarding_card(
            faction_name="刘备",
            faction_intro="汉室宗亲刘备，以仁义立世。",
            territories=["新野"],
            heroes=["关羽", "张飞", "赵云"],
            year=207, season="冬",
            treasury=3000, food=2000, prestige=35,
        )
        card = result["content"]
        assert "刘备" in card["header"]["title"]["content"]
        body = card["elements"][0]["content"]
        assert "新野" in body
        assert "关羽" in body
        assert "3,000" in body

    def test_render_state_summary_card(self):
        result = self.adapter.render_state_summary_card(
            faction_name="曹操",
            year=208, season="春", turn=5,
            territories=[
                {"name": "许昌", "population": 100000, "development": 75, "garrison": 1000},
            ],
            total_troops=150000,
            treasury=50000, food=30000, prestige=90,
            tax_rate=0.4,
            allies=[], enemies=["shu", "wu"],
            armies=[
                {"id": "army_cao_1", "location": "许昌", "troops": 50000, "morale": 80},
            ],
        )
        card = result["content"]
        body = card["elements"][0]["content"]
        assert "曹操" in card["header"]["title"]["content"]
        assert "许昌" in body
        assert "150,000" in body
        assert "50,000" in body
        assert "shu" in body.lower() or "wu" in body.lower()

    def test_render_help_card(self):
        result = self.adapter.render_help_card()
        card = result["content"]
        body = card["elements"][0]["content"]
        assert "帮助" in card["header"]["title"]["content"] or "帮助" in body
        assert "new" in body or "新游戏" in body


class TestHelperMethods:
    """Tests for helper methods."""

    def test_stat_emoji(self):
        adapter = FeishuAdapter()
        assert adapter._stat_emoji("兵力") == "⚔️"
        assert adapter._stat_emoji("粮草") == "🌾"
        assert adapter._stat_emoji("金库") == "💰"
        assert adapter._stat_emoji("声望") == "⭐"
        assert adapter._stat_emoji("未知属性") == "📌"

    def test_message_splitting(self):
        adapter = FeishuAdapter()
        short = adapter.split_long_message("Hello")
        assert len(short) == 1

        long_msg = "A" * 30000  # 2x MAX
        chunks = adapter.split_long_message(long_msg)
        assert len(chunks) > 1
        assert all(len(c) <= adapter.MAX_MESSAGE_LENGTH for c in chunks)
