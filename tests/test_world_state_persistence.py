"""
Unit tests for Rome V3 world-state persistence fixes (PR #151).

Covers:
- _serialize_world_state() handling both local and engine WorldState flavors
- deserialize_world_state() roundtrip preserving territories/armies/characters
- deserialize_world_state() raising instead of silently falling back to 207 AD
- load_room() full persistence path for a rome-triumvirate room
"""

import json
import os

import pytest

from histrategy.db import init_db
from histrategy.db.models import deserialize_world_state, load_room, save_room
from histrategy.engine.scenario_loader import ScenarioLoader
from histrategy.server.room_manager import _serialize_world_state


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """Use isolated DB for each test."""
    db_path = str(tmp_path / "test_ws.db")
    os.environ["HISTRATEGY_DATABASE_URL"] = f"sqlite:///{db_path}"

    import histrategy.db.connection as conn_module

    conn_module.DATABASE_URL = f"sqlite:///{db_path}"
    conn_module._IS_SQLITE = True
    conn_module._SCHEMA_LOADED = False

    init_db()
    yield
    os.environ.pop("HISTRATEGY_DATABASE_URL", None)


def _build_rome_ws():
    """Build a full Rome engine WorldState via ScenarioLoader."""
    loader = ScenarioLoader("rome-triumvirate")
    return loader.build_world_state("senate")


class TestSerializeWorldState:
    """_serialize_world_state handles both WorldState flavors."""

    def test_engine_world_state_serializes_without_to_dict(self):
        ws = _build_rome_ws()
        # Engine WorldState (PyPI dataclass) has no to_dict
        assert not hasattr(ws, "to_dict")

        d = _serialize_world_state(ws)
        assert d is not None
        assert d["year"] == -44
        assert d["scenario"] == "rome-triumvirate"
        # Must be JSON-serializable (enums unwrapped)
        json.dumps(d)
        # Territories/armies preserved
        assert len(d["territories"]) >= 10
        assert len(d["armies"]) > 0

    def test_local_world_state_serializes_via_to_dict(self):
        from histrategy.state.world_state import WorldState as LocalWS

        ws = LocalWS()
        ws.year = -44
        ws.player_faction_id = "senate"
        ws.scenario = "rome-triumvirate"
        d = _serialize_world_state(ws)
        assert d is not None
        assert d["year"] == -44

    def test_none_returns_none(self):
        assert _serialize_world_state(None) is None


class TestDeserializeWorldState:
    """deserialize_world_state rebuilds the FULL world state."""

    def test_roundtrip_preserves_territories_and_armies(self):
        ws = _build_rome_ws()
        d = _serialize_world_state(ws)

        ws2 = deserialize_world_state(json.loads(json.dumps(d)))

        assert ws2.year == -44
        assert ws2.scenario == "rome-triumvirate"
        # The key fix: territories and armies survive the roundtrip
        assert len(ws2.territories) == len(ws.factions) or len(ws2.territories) >= 10
        assert len(ws2.armies) > 0
        # Factions restored
        assert "senate" in ws2.factions
        assert "octavian" in ws2.factions
        # Territory enums restored (not raw strings)
        roma = ws2.territories.get("roma")
        if roma is not None:
            assert hasattr(roma.terrain_type, "value")

    def test_missing_year_raises_instead_of_fallback_207(self):
        """PR review: must NOT silently fall back to 207 AD."""
        ws = _build_rome_ws()
        d = _serialize_world_state(ws)
        del d["year"]

        with pytest.raises(ValueError, match="year"):
            deserialize_world_state(d)

    def test_missing_scenario_raises(self):
        ws = _build_rome_ws()
        d = _serialize_world_state(ws)
        del d["scenario"]

        with pytest.raises(ValueError, match="scenario"):
            deserialize_world_state(d)

    def test_invalid_season_raises(self):
        ws = _build_rome_ws()
        d = _serialize_world_state(ws)
        d["season"] = "not-a-season"
        d.pop("season_index", None)

        with pytest.raises(ValueError, match="season"):
            deserialize_world_state(d)

    def test_empty_factions_ok(self):
        d = {"year": -44, "scenario": "rome-triumvirate", "season": "spring", "factions": {}}
        ws = deserialize_world_state(d)
        assert ws.year == -44
        assert ws.factions == {}


class TestLoadRoomPersistence:
    """Full save_room → load_room roundtrip with Rome world state."""

    def test_save_and_load_rome_room_preserves_world_state(self):
        from histrategy.engine.faction_slot import create_human_slot
        from histrategy.engine.game_room import GameRoom, RoomPhase

        room = GameRoom(
            id="test-rome-room",
            scenario="rome-triumvirate",
            year=-44,
            season="spring",
            quarter_number=0,
            phase=RoomPhase.WAITING,
            host_user_id="tester",
        )
        room.slots = {"senate": create_human_slot("senate", "tester")}
        room.world_state = _build_rome_ws()

        save_room(room, _serialize_world_state(room.world_state))

        loaded = load_room("test-rome-room")
        assert loaded is not None
        assert loaded.scenario == "rome-triumvirate"
        assert loaded.world_state is not None
        assert loaded.world_state.year == -44
        assert len(loaded.world_state.territories) >= 10
        assert len(loaded.world_state.armies) > 0
        assert "senate" in loaded.world_state.factions

    def test_save_after_submit_keeps_world_state_non_null(self):
        """Regression: submit_decision used to NULL out world_state."""
        from histrategy.engine.faction_slot import create_human_slot
        from histrategy.engine.game_room import GameRoom, RoomPhase
        from histrategy.db.models import load_world_state_dict

        room = GameRoom(
            id="test-submit-room",
            scenario="rome-triumvirate",
            year=-44,
            season="spring",
            quarter_number=0,
            phase=RoomPhase.WAITING,
            host_user_id="tester",
        )
        room.slots = {"senate": create_human_slot("senate", "tester")}
        room.world_state = _build_rome_ws()

        # First save with explicit ws_dict
        save_room(room, _serialize_world_state(room.world_state))
        # Simulate submit_decision's _try_save path: save WITHOUT ws_dict,
        # letting save_room extract from room.world_state
        save_room(room)

        loaded_ws = load_world_state_dict(room.id)
        assert loaded_ws is not None, "world_state must not be NULL after save without ws_dict"
        assert loaded_ws["year"] == -44
