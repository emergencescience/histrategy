"""Tests for FormatEngine — platform-specific output formatting."""

import tempfile
from unittest.mock import Mock

from histrategy_agent.session import GameSessionManager
from histrategy_agent.format_engine import FormatEngine
from histrategy_agent.turn_processor import TurnResult, TurnProcessor
from histrategy_agent.multiplayer import MultiplayerSession, GamePhase, PlayerSlot


class TestFormatEngineTurnResult:
    """Tests for rendering turn results."""

    def setup_method(self):
        self.engine = FormatEngine()

    def test_render_turn_result_basic(self):
        result = TurnResult(
            narrative="我军发起进攻，攻占宛城。",
            world_snapshot={
                "year": 207, "season": "冬", "turn": 3,
                "territories": [{"name": "新野"}, {"name": "宛城"}],
                "total_troops": 4800, "food": 1800, "prestige": 40,
                "treasury": 2800, "faction_name": "刘备",
                "faction_id": "shu",
            },
            suggestions=["招募步兵", "休整一回合", "与吴联盟"],
            events=["攻占宛城", "曹操：征收获得15000金"],
            map_ascii="",
            raw_world_state=Mock(),
        )
        output = self.engine.render_turn_result(result, "feishu")
        assert "建安207年" in output
        assert "冬" in output
        assert "宛城" in output
        assert "刘备" in output or "我军" in output
        assert "可选行动" in output
        assert "本回合事件" in output

    def test_render_turn_result_with_map(self):
        result = TurnResult(
            narrative="大军开拔。",
            world_snapshot={
                "year": 208, "season": "春", "turn": 5,
                "territories": [], "total_troops": 1000,
                "food": 500, "prestige": 25, "treasury": 1000,
                "faction_name": "刘备", "faction_id": "shu",
            },
            suggestions=[],
            events=[],
            map_ascii="[蜀] 新野\n[魏] 宛城",
            raw_world_state=Mock(),
        )
        output = self.engine.render_turn_result(result, "feishu")
        assert "天下大势图" in output or "[蜀]" in output

    def test_render_turn_result_with_many_events(self):
        events = [f"事件{i}" for i in range(20)]
        result = TurnResult(
            narrative="test",
            world_snapshot={"year": 207, "season": "冬", "turn": 1,
                            "territories": [], "total_troops": 0,
                            "food": 0, "prestige": 0, "treasury": 0,
                            "faction_name": "Test", "faction_id": "test"},
            suggestions=["action 1"],
            events=events,
            map_ascii="",
            raw_world_state=Mock(),
        )
        output = self.engine.render_turn_result(result)
        # Should truncate to max 10 events (+ header line)
        event_lines = [l for l in output.split("\n") if l.startswith("- 事件")]
        assert len(event_lines) <= 11  # header + up to 10 events

    def test_render_turn_result_empty_suggestions(self):
        result = TurnResult(
            narrative="test",
            world_snapshot={"year": 207, "season": "冬", "turn": 1,
                            "territories": [], "total_troops": 0,
                            "food": 0, "prestige": 0, "treasury": 0,
                            "faction_name": "Test", "faction_id": "test"},
            suggestions=[],
            events=[],
            map_ascii="",
            raw_world_state=Mock(),
        )
        output = self.engine.render_turn_result(result)
        # Empty suggestions should not cause issues
        assert "可选行动" not in output


class TestFormatEngineStateSummary:
    """Tests for rendering state summaries."""

    def test_render_state_summary_shu(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_summary", "shu", "207")
            engine = FormatEngine()
            output = engine.render_state_summary(session)
            assert "刘备" in output
            assert "新野" in output
            assert "建安207年" in output
            assert "金库" in output
            assert "粮草" in output
            assert "总兵力" in output

    def test_render_state_summary_cao(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_cao", "cao", "207")
            engine = FormatEngine()
            output = engine.render_state_summary(session)
            assert "曹操" in output or "cao" in output
            assert "许昌" in output
            assert "宛城" in output
            # Cao has many territories
            assert "领地" in output

    def test_render_state_summary_no_faction(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_none", "shu", "207")
            session.player_faction_id = "nonexistent"
            engine = FormatEngine()
            output = engine.render_state_summary(session)
            assert "无存档" in output or "不存在" in output or output.strip() != ""


class TestFormatEngineOnboarding:
    """Tests for new game onboarding message."""

    def test_render_onboarding_shu(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_onboarding", "shu", "207")
            engine = FormatEngine()
            output = engine.render_onboarding(session)
            assert "刘备" in output or "汉室" in output
            assert "新野" in output
            assert "三國志略" in output
            assert "新游戏" in output

    def test_render_onboarding_cao(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_onboard_cao", "cao", "207")
            engine = FormatEngine()
            output = engine.render_onboarding(session)
            assert "曹操" in output
            assert "许昌" in output

    def test_render_onboarding_wu(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_onboard_wu", "wu", "207")
            engine = FormatEngine()
            output = engine.render_onboarding(session)
            assert "孙权" in output
            assert "建业" in output

    def test_render_onboarding_unknown_faction(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_unknown", "shu", "207")
            session.player_faction_id = "nonexistent"
            engine = FormatEngine()
            output = engine.render_onboarding(session)
            # Should return fallback message, not crash
            assert isinstance(output, str)
            assert len(output) > 0


class TestFormatEngineSuggestions:
    """Tests for suggestion formatting."""

    def test_render_suggestions(self):
        engine = FormatEngine()
        suggestions = ["招募步兵", "与孙权结盟", "开发农业", "查看天下大势"]
        output = engine.render_suggestions(suggestions)
        assert "可选行动" in output
        assert "1. 招募步兵" in output
        assert "2. 与孙权结盟" in output
        assert "3. 开发农业" in output
        assert "4. 查看天下大势" in output

    def test_render_suggestions_empty(self):
        engine = FormatEngine()
        output = engine.render_suggestions([])
        assert "可选行动" in output


class TestFormatEngineMapAndBattle:
    """Tests for ASCII map and battle card rendering."""

    def test_render_map_ascii_has_territories(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_map", "shu", "207")
            engine = FormatEngine()
            output = engine.render_map_ascii(session.world_state, "shu")
            # Should contain territory names
            assert "新野" in output
            assert "许昌" in output or "宛城" in output
            # Should have legend
            assert "蜀" in output or "[shu]" in output or "刘备" in output


class TestFormatEngineEdgeCases:
    """Edge cases for format engine."""

    def test_render_turn_result_no_territories(self):
        result = TurnResult(
            narrative="全军覆没。",
            world_snapshot={
                "year": 207, "season": "冬", "turn": 1,
                "territories": [],
                "total_troops": 0, "food": 0, "prestige": 0, "treasury": 0,
                "faction_name": "刘备", "faction_id": "shu",
            },
            suggestions=["休整"],
            events=["败亡"],
            map_ascii="",
            raw_world_state=Mock(),
        )
        engine = FormatEngine()
        output = engine.render_turn_result(result)
        assert "无" in output  # No territories → "无"

    def test_render_turn_result_zero_values(self):
        result = TurnResult(
            narrative="弹尽粮绝。",
            world_snapshot={
                "year": 207, "season": "冬", "turn": 5,
                "territories": [{"name": "新野"}],
                "total_troops": 0, "food": 0, "prestige": 0, "treasury": 0,
                "faction_name": "刘备", "faction_id": "shu",
            },
            suggestions=[],
            events=[],
            map_ascii="",
            raw_world_state=Mock(),
        )
        engine = FormatEngine()
        output = engine.render_turn_result(result)
        assert "0" in output  # Shows zeros
