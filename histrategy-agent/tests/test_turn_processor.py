"""Tests for TurnProcessor — intent parsing, turn processing, suggestions."""

import tempfile

from histrategy_agent.session import GameSessionManager
from histrategy_agent.turn_processor import TurnProcessor


class TestIntentParser:
    """Unit tests for the keyword-based intent parser."""

    def setup_method(self):
        self.tp = TurnProcessor()

    def test_parse_attack_intent(self):
        result = self.tp._parse_intent("进攻宛城", "shu")
        assert result["action"] == "attack"
        assert result["target"] == "wancheng"

    def test_parse_recruit_intent(self):
        result = self.tp._parse_intent("招募步兵 5000", "shu")
        assert result["action"] == "recruit"
        assert result["params"]["unit_type"] == "infantry"
        assert result["params"]["amount"] == 5000

    def test_parse_recruit_cavalry(self):
        result = self.tp._parse_intent("招募骑兵3000人", "shu")
        assert result["action"] == "recruit"
        assert result["params"]["unit_type"] == "cavalry"
        assert result["params"]["amount"] == 3000

    def test_parse_recruit_archer(self):
        result = self.tp._parse_intent("招募弓兵1000", "shu")
        assert result["action"] == "recruit"
        assert result["params"]["unit_type"] == "archer"
        assert result["params"]["amount"] == 1000

    def test_parse_move_intent(self):
        result = self.tp._parse_intent("移动到洛阳", "shu")
        assert result["action"] == "move"
        assert result["target"] == "luoyang"

    def test_parse_develop_intent(self):
        result = self.tp._parse_intent("开发成都的农业", "shu")
        assert result["action"] == "develop"
        assert result["target"] == "chengdu"

    def test_parse_diplomacy_intent(self):
        result = self.tp._parse_intent("与孙权结盟", "shu")
        assert result["action"] == "diplomacy"
        assert result["target"] == "wu"
        assert result["params"]["action"] == "ally"

    def test_parse_break_ally_intent(self):
        result = self.tp._parse_intent("与曹操断交", "shu")
        assert result["action"] == "diplomacy"
        assert result["target"] == "cao"
        assert result["params"]["action"] == "break_ally"

    def test_parse_info_intent(self):
        result = self.tp._parse_intent("查看天下大势", "shu")
        assert result["action"] == "info"

    def test_parse_tax_intent(self):
        result = self.tp._parse_intent("调整税率为30%", "shu")
        assert result["action"] == "tax"
        assert result["params"]["rate"] == 0.3

    def test_parse_tax_other_rate(self):
        result = self.tp._parse_intent("税收设为15%", "shu")
        assert result["action"] == "tax"
        assert result["params"]["rate"] == 0.15

    def test_parse_unknown_intent(self):
        result = self.tp._parse_intent("今天天气真好", "shu")
        # Unrecognized input defaults to info (shows current state)
        assert result["action"] == "info"
        assert result["params"]["raw_text"] == "今天天气真好"

    def test_extract_number_too_large(self):
        # Numbers > 99999 should return None
        assert self.tp._extract_number("招募1000000步兵") is None

    def test_extract_territory_by_cn_name(self):
        assert self.tp._extract_territory("攻打襄阳") == "xiangyang"
        assert self.tp._extract_territory("移师成都") == "chengdu"
        assert self.tp._extract_territory("进军许昌") == "xuchang"

    def test_extract_territory_not_found(self):
        assert self.tp._extract_territory("攻打长安") == ""

    def test_extract_faction_by_cn_name(self):
        assert self.tp._extract_faction("与曹操联盟", "shu") == "cao"
        assert self.tp._extract_faction("和吴国结盟", "shu") == "wu"
        assert self.tp._extract_faction("与刘表合作", "shu") == "liubiao"

    def test_extract_faction_not_found(self):
        assert self.tp._extract_faction("和张角合作", "shu") == ""

    def test_recruit_default_amount(self):
        # No number specified → defaults to 1000
        result = self.tp._parse_intent("招募步兵", "shu")
        assert result["params"]["amount"] == 1000


class TestTurnProcessing:
    """Integration tests for the full turn processing pipeline."""

    def test_process_info_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_info", "shu", "207")
            tp = TurnProcessor()
            result = tp.process(session, "查看天下大势")

            assert result.narrative
            assert "天下大势" in result.narrative
            assert result.world_snapshot

    def test_process_recruit_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_recruit", "cao", "207")
            tp = TurnProcessor()
            result = tp.process(session, "招募步兵2000")

            assert result.narrative
            assert result.world_snapshot
            # Should have events
            assert isinstance(result.events, list)

    def test_process_develop_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_dev", "wu", "207")
            tp = TurnProcessor()
            result = tp.process(session, "开发建业")

            assert result.narrative
            # Should include NPC actions
            assert len(result.events) > 0

    def test_turn_increments_turn_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_incr", "shu", "207")
            assert session.turn_number == 1

            tp = TurnProcessor()
            tp.process(session, "查看天下大势")
            assert session.turn_number == 2

    def test_process_attack_invalid_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_attack", "shu", "207")
            tp = TurnProcessor()
            # Attacking a non-adjacent territory should fail
            result = tp.process(session, "进攻洛阳")
            assert result.narrative
            assert "受阻" in result.narrative or "无法" in result.narrative

    def test_process_diplomacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_diplo", "shu", "207")
            tp = TurnProcessor()
            result = tp.process(session, "与刘表联盟")
            assert result.narrative

    def test_process_tax(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_tax", "cao", "207")
            tp = TurnProcessor()
            result = tp.process(session, "税收20%")
            assert result.narrative
            assert result.world_snapshot

    def test_suggestions_include_action_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_sugg", "shu", "207")
            tp = TurnProcessor()
            result = tp.process(session, "查看天下大势")
            assert len(result.suggestions) >= 3
            assert len(result.suggestions) <= 5
            # Should include common actions
            has_view = any("天下大势" in s for s in result.suggestions)
            assert has_view
            # Suggestions should be strings
            assert all(isinstance(s, str) for s in result.suggestions)

    def test_season_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_season", "shu", "207")
            from histrategy_engine import Season

            assert session.world_state.season == Season.WINTER

            tp = TurnProcessor()
            # Turn 1 → 2: season advances to SPRING (every 2 turns)
            tp.process(session, "查看天下大势")
            assert session.world_state.season == Season.SPRING

            # Turn 2 → 3: season stays SPRING
            tp.process(session, "查看天下大势")
            assert session.world_state.season == Season.SPRING

            # Turn 3 → 4: season advances to SUMMER
            tp.process(session, "查看天下大势")
            assert session.world_state.season == Season.SUMMER

    def test_year_advances_after_four_seasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_year", "shu", "207")
            assert session.world_state.year == 207

            tp = TurnProcessor()
            # Advance 8 turns (4 season changes = 1 year)
            for _ in range(8):
                tp.process(session, "查看天下大势")

            assert session.world_state.year == 208

    def test_npc_actions_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_npc", "shu", "207")
            tp = TurnProcessor()
            result = tp.process(session, "查看天下大势")
            # Should have NPC faction actions
            npc_events = [e for e in result.events if "征收" in e or "开发" in e or "征税" in e]
            assert len(npc_events) > 0, f"No NPC events found in: {result.events}"
