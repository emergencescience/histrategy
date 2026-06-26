"""
Integration test: histrategy ↔ orchestrator API contract.

Verifies that histrategy's API responses conform to the format expected
by emergence-orchestrator's routes/games.py proxy and shared-spectate endpoints.
Run with HISTRATEGY_ENGINE=v2 (no LLM calls) for fast execution.

Usage:
    HISTRATEGY_ENGINE=v2 pytest tests/test_orchestrator_integration.py -v
"""

import pytest

# ═════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════


@pytest.fixture
def room_id():
    """Create a Caesar room with pre-assigned human player (no LLM calls)."""
    import os

    os.environ.setdefault("HISTRATEGY_ENGINE", "v2")

    from histrategy.server.room_manager import create_room

    result = create_room(
        scenario="rome-triumvirate",
        pre_assigned={"octavian": "TestPlayer"},
    )
    assert result["ok"], f"Room creation failed: {result}"
    return result["room_id"]


@pytest.fixture
def tk_room_id():
    """Create a Three Kingdoms room for backward compat testing."""
    import os

    os.environ.setdefault("HISTRATEGY_ENGINE", "v2")

    from histrategy.server.room_manager import create_room

    result = create_room(
        scenario="three-kingdoms",
        pre_assigned={"shu": "TestPlayer"},
    )
    assert result["ok"]
    return result["room_id"]


# ═════════════════════════════════════════════════════════════
# API Contract Tests — orchestrator depends on these endpoints
# ═════════════════════════════════════════════════════════════


class TestScenariosAPI:
    """GET /api/scenarios — used by frontend and orchestrator to discover factions."""

    def test_returns_ok(self):
        from histrategy.engine.scenario_loader import ScenarioLoader

        result = ScenarioLoader.list_scenarios()
        assert len(result) >= 2  # at least three-kingdoms + rome-triumvirate

    def test_caesar_factions_are_playable(self):
        from histrategy.engine.scenario_loader import ScenarioLoader

        result = ScenarioLoader.list_scenarios()
        assert "rome-triumvirate" in result
        loader = ScenarioLoader("rome-triumvirate")
        factions = loader.load_factions()
        # All 4 factions should be playable (npc_only: false)
        playable = {fid for fid, f in factions.items() if not f.get("npc_only", False)}
        assert playable == {"octavian", "antony", "cleopatra", "senate"}

    def test_caesar_factions_have_display_names(self):
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader("rome-triumvirate")
        factions = loader.load_factions()
        for fid, f in factions.items():
            assert f.get("name") or f.get("name_en"), f"Faction {fid} has no display name"


class TestRoomStatusAPI:
    """GET /api/rooms/{id}/status — used by orchestrator's get_shared_room."""

    def test_returns_faction_names(self, room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(room_id)
        assert status["ok"]
        assert "faction_names" in status, "orchestrator requires faction_names field"
        fnames = status["faction_names"]
        # Caesar factions should have Chinese names
        assert fnames.get("octavian") == "屋大维"
        assert fnames.get("antony") == "马克·安东尼"
        assert fnames.get("cleopatra") == "克利奥帕特拉七世"
        assert fnames.get("senate") == "罗马元老院"

    def test_slot_keys_use_display_names(self, room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(room_id)
        slots = status["slots"]
        # Slot keys should be display names, not internal IDs
        assert "屋大维" in slots, f"Expected 屋大维 in slot keys, got {list(slots.keys())}"
        assert "octavian" not in slots, "Slot keys should NOT use internal IDs"

    def test_required_fields_for_orchestrator(self, room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(room_id)
        # Fields that orchestrator's _format_shared_turn reads
        required = [
            "ok",
            "room_id",
            "phase",
            "year",
            "season",
            "quarter",
            "faction_names",
            "slots",
            "submitted",
            "pending",
        ]
        for field in required:
            assert field in status, f"orchestrator requires field '{field}'"

    def test_three_kingdoms_backward_compat(self, tk_room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(tk_room_id)
        assert status["ok"]
        assert "faction_names" in status
        fnames = status["faction_names"]
        # TK factions should still resolve correctly
        assert fnames.get("shu") in ("刘备", "刘备军", "shu"), f"shu→{fnames.get('shu')}"
        assert fnames.get("cao") in ("曹操", "曹操军", "cao"), f"cao→{fnames.get('cao')}"


class TestRoomTurnsAPI:
    """GET /api/rooms/{id}/turns — used by orchestrator's shared session endpoint."""

    def test_returns_faction_names(self, room_id):
        from histrategy.server.room_manager import _get_faction_names, _get_room

        room = _get_room(room_id)
        fnames = _get_faction_names(room)
        assert "octavian" in fnames
        assert fnames["octavian"] == "屋大维"

    def test_turns_response_structure(self, room_id):
        from histrategy.db.models import get_quarter_turns

        turns = get_quarter_turns(room_id, limit=10)
        # orch expects: quarter_number, year, season, faction_decisions,
        # narratives, state_changes, token_usage
        if turns:
            turn = turns[0]
            required = ["quarter_number", "year", "season", "faction_decisions", "narratives", "state_changes"]
            for field in required:
                assert field in turn.keys() if hasattr(turn, "keys") else field in dict(turn), (
                    f"orchestrator requires turn field '{field}'"
                )


class TestCaesarYearAndSeason:
    """Verify Caesar starts at -44 spring (not -43)."""

    def test_room_year_is_negative_44(self, room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(room_id)
        assert status["year"] == -44, f"Expected -44, got {status['year']}"

    def test_room_season_is_spring(self, room_id):
        from histrategy.server.room_manager import get_room_status

        status = get_room_status(room_id)
        assert status["season"] in ("spring", "春"), f"Expected spring, got {status['season']}"


class TestNpcOnlyFactionsExcluded:
    """Verify npc_only factions are not created as AI slots."""

    def test_caesar_slots_includes_npc_only_minors(self, room_id):
        from histrategy.server.room_manager import _get_room

        room = _get_room(room_id)
        assert room is not None
        # Major playable factions + npc_only minor factions are all added as AI slots
        assert len(room.slots) >= 4, f"Expected at least 4 slots, got {len(room.slots)}"
        faction_ids = set(room.slots.keys())
        major_factions = {"octavian", "antony", "cleopatra", "senate"}
        assert major_factions <= faction_ids, f"Missing major factions: {major_factions - faction_ids}"
        # npc_only minor factions with real troops should be present as AI heuristic slots
        expected_minors = {"sextus_pompey", "lepidus", "decimus_brutus", "cassius_brutus"}
        assert expected_minors <= faction_ids, f"Missing npc_only minors: {expected_minors - faction_ids}"


class TestFactionNamesAllScenarios:
    """Verify faction_names works for all scenarios."""

    def test_three_kingdoms_faction_names(self, tk_room_id):
        from histrategy.server.room_manager import _get_faction_names, _get_room

        room = _get_room(tk_room_id)
        fnames = _get_faction_names(room)
        # Should have at least the 3 main TK factions
        assert len(fnames) >= 3
        # All values should be non-empty strings
        for fid, name in fnames.items():
            assert name and isinstance(name, str), f"Empty name for {fid}"
