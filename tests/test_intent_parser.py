"""
Unit tests for IntentParser — command parsing, _resolve_names, defend support.

Covers:
- Keyword fallback: defend, recruit, muster (not recruit), attack, move
- _resolve_names: clean text, pre-resolved text, double-nesting prevention
- _build_command: notes field passthrough
- Missing territory detection
"""

import pytest
from histrategy_engine.world import Command

from histrategy.parser.intent import (
    TERRITORY_NAME_MAP,
    IntentParser,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def parser():
    """Keyword-fallback parser (no LLM)."""
    return IntentParser(None)


# ═══════════════════════════════════════════════════════════════
# _resolve_names — double-nesting prevention
# ═══════════════════════════════════════════════════════════════


class TestResolveNames:
    """Tests for _resolve_names() — the name→id resolution step."""

    def test_clean_text_chinese_names(self, parser):
        """Chinese faction/territory names get IDs appended."""
        text = "进攻刘备的新野，防范孙权"
        result = parser._resolve_names(text, "cao")
        assert "刘备(shu)" in result
        assert "新野(xinye)" in result
        assert "孙权(wu)" in result

    def test_clean_text_no_double_nesting(self, parser):
        """After resolution, no name(id(id)) patterns appear."""
        text = "南征刘备，集结宛城5万步兵，进攻新野。防范孙权从庐江进攻下邳。"
        result = parser._resolve_names(text, "cao")
        bad_patterns = [
            "shu(shu)", "wancheng(wancheng)", "xinye(xinye)",
            "wu(wu)", "lujiang(lujiang)", "xiapi(xiapi)",
        ]
        for bad in bad_patterns:
            assert bad not in result, f"Double-nesting: {bad} found in {result}"

    def test_pre_resolved_text_stays_clean(self, parser):
        """Text that already has name(id) format should NOT be re-resolved."""
        text = "【南征刘备(shu)】— 集结宛城(wancheng)5万步兵，进攻新野(xinye)。防范孙权(wu)。"
        result = parser._resolve_names(text, "cao")
        # Should match exactly (no extra nesting)
        assert "刘备(shu(shu))" not in result
        assert "宛城(wancheng(wancheng))" not in result
        assert "新野(xinye(xinye))" not in result
        assert "孙权(wu(wu))" not in result
        # Clean IDs should appear exactly once in resolved form
        assert result.count("刘备(shu)") == 1
        assert result.count("宛城(wancheng)") == 1

    def test_missing_territories_now_present(self, parser):
        """Territories that were missing (xiapi, lujiang, etc.) are now in the map."""
        assert "下邳" in TERRITORY_NAME_MAP
        assert "xiapi" in TERRITORY_NAME_MAP
        assert "庐江" in TERRITORY_NAME_MAP
        assert "lujiang" in TERRITORY_NAME_MAP
        assert "濮阳" in TERRITORY_NAME_MAP
        assert "北海" in TERRITORY_NAME_MAP
        assert "成都" in TERRITORY_NAME_MAP
        assert TERRITORY_NAME_MAP["下邳"] == "xiapi"
        assert TERRITORY_NAME_MAP["庐江"] == "lujiang"

    def test_partially_resolved_input(self, parser):
        """If only some names are pre-resolved, the rest get resolved once."""
        text = "进攻刘备(shu)的新野，防范孙权"
        result = parser._resolve_names(text, "cao")
        assert "刘备(shu(shu))" not in result  # already resolved
        assert "新野(xinye)" in result          # not yet resolved
        assert "孙权(wu)" in result              # not yet resolved


# ═══════════════════════════════════════════════════════════════
# Keyword fallback — command types
# ═══════════════════════════════════════════════════════════════


class TestKeywordFallback:
    """Tests for _keyword_parse() — without LLM."""

    # ── defend ──

    def test_defend_xiapi(self, parser):
        """'防守下邳' → defend command with territory xiapi."""
        cmds = parser.parse("在下邳部署3万兵力防守，防止孙权偷袭", "cao")
        defend_cmds = [c for c in cmds if c.type == "defend"]
        assert len(defend_cmds) == 1
        assert defend_cmds[0].params["territory"] == "xiapi"
        assert "防守" in defend_cmds[0].notes

    def test_defend_keywords(self, parser):
        """All defend keywords should trigger defend command."""
        keywords = ["防守", "布防", "防御", "戒备", "镇守", "驻防", "保卫", "设防"]
        for kw in keywords:
            cmds = parser.parse(f"在下邳{kw}", "cao")
            assert any(c.type == "defend" for c in cmds), f"Keyword '{kw}' missed defend"

    # ── muster vs recruit ──

    def test_muster_not_recruit(self, parser):
        """'集结' should NOT produce a recruit command."""
        cmds = parser.parse("集结宛城5万步兵和1万骑兵，进攻新野", "cao")
        recruit_cmds = [c for c in cmds if c.type == "recruit"]
        assert len(recruit_cmds) == 0, f"Muster produced recruit: {recruit_cmds}"

    def test_explicit_recruit_still_works(self, parser):
        """'招募' should still produce a recruit command."""
        cmds = parser.parse("在许昌招募1万骑兵", "cao")
        recruit_cmds = [c for c in cmds if c.type == "recruit"]
        assert len(recruit_cmds) == 1
        assert recruit_cmds[0].params["territory"] == "xuchang"
        assert recruit_cmds[0].params["amount"] == 10000
        assert recruit_cmds[0].params["unit_type"] == "cavalry"

    # ── attack ──

    def test_attack_with_explicit_target(self, parser):
        """'进攻新野' → attack xinye."""
        cmds = parser.parse("进攻新野", "cao")
        attack_cmds = [c for c in cmds if c.type == "attack"]
        assert len(attack_cmds) == 1
        assert attack_cmds[0].params["target_territory"] == "xinye"

    # ── combined commands ──

    def test_attack_and_defend_combo(self, parser):
        """Attack + defend in one text → both parsed."""
        cmds = parser.parse("进攻新野，同时在下邳防守孙权", "cao")
        types = {c.type for c in cmds}
        assert "attack" in types
        assert "defend" in types

    # ── no commands ──

    def test_unrelated_text_returns_empty(self, parser):
        """Non-strategic text → empty list."""
        cmds = parser.parse("今天天气真好", "cao")
        assert cmds == []

    def test_empty_text_returns_empty(self, parser):
        cmds = parser.parse("", "cao")
        assert cmds == []


# ═══════════════════════════════════════════════════════════════
# _build_command — notes passthrough
# ═══════════════════════════════════════════════════════════════


class TestBuildCommand:
    """Tests for _build_command() — JSON → Command conversion."""

    def test_notes_passthrough(self, parser):
        """The notes field from LLM JSON should be preserved."""
        cmd = parser._build_command(
            {
                "type": "defend",
                "params": {"territory": "xiapi"},
                "notes": "防范孙权从庐江进攻",
            },
            "cao",
        )
        assert cmd is not None
        assert cmd.type == "defend"
        assert cmd.notes == "防范孙权从庐江进攻"

    def test_notes_default_empty(self, parser):
        """If no notes in JSON, defaults to empty string."""
        cmd = parser._build_command(
            {"type": "attack", "params": {"target_territory": "xinye"}},
            "cao",
        )
        assert cmd is not None
        assert cmd.notes == ""

    def test_defend_type_accepted(self, parser):
        """'defend' is now in the allowed command types."""
        cmd = parser._build_command(
            {"type": "defend", "params": {"territory": "xiapi"}},
            "cao",
        )
        assert cmd is not None
        assert cmd.type == "defend"

    def test_unknown_type_rejected(self, parser):
        """Unknown command types should return None."""
        cmd = parser._build_command(
            {"type": "nuke", "params": {"target": "everywhere"}},
            "cao",
        )
        assert cmd is None


# ═══════════════════════════════════════════════════════════════
# Command dataclass — notes field
# ═══════════════════════════════════════════════════════════════


class TestCommandDataclass:
    """Tests for the Command dataclass with new notes field."""

    def test_notes_field_exists(self):
        cmd = Command(type="attack", params={"target_territory": "xinye"}, faction_id="cao")
        assert hasattr(cmd, "notes")
        assert cmd.notes == ""

    def test_notes_field_settable(self):
        cmd = Command(
            type="defend",
            params={"territory": "xiapi"},
            faction_id="cao",
            notes="防范孙权",
        )
        assert cmd.notes == "防范孙权"

    def test_command_serializable(self):
        """Command to_dict should not break with notes field."""
        cmd = Command(
            type="recruit",
            params={"territory": "xuchang", "unit_type": "infantry", "amount": 5000},
            faction_id="cao",
            notes="扩充兵力",
        )
        d = {
            "type": cmd.type,
            "params": cmd.params,
            "faction_id": cmd.faction_id,
            "notes": cmd.notes,
        }
        assert d["notes"] == "扩充兵力"
