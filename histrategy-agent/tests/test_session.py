"""Tests for GameSessionManager — session CRUD and persistence."""

import tempfile
from pathlib import Path

from histrategy_agent.session import GameSessionManager, _coerce_value, _from_dict, _to_dict
from histrategy_engine import FactionState, Season, TerrainType, Territory, WorldState


class TestGameSessionManager:
    """Full integration tests for session creation, persistence, and loading."""

    def test_create_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_abc", "shu", "207")

            assert session.session_id == "feishu:chat_abc"
            assert session.platform == "feishu"
            assert session.player_faction_id == "shu"
            assert session.turn_number == 1
            assert session.world_state.year == 207
            assert session.world_state.season == Season.WINTER
            assert not session.is_multiplayer
            assert "shu" in session.world_state.factions
            assert "cao" in session.world_state.factions

    def test_persist_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            mgr.get_or_create("feishu", "chat_abc", "shu", "207")

            # Verify files exist
            session_dir = Path(tmp) / "feishu" / "chat_abc"
            assert session_dir.exists()
            assert (session_dir / "world_state.json").exists()
            assert (session_dir / "session_meta.json").exists()

            # Load back
            loaded = mgr.get_session("feishu", "chat_abc")
            assert loaded is not None
            assert loaded.session_id == "feishu:chat_abc"
            assert loaded.player_faction_id == "shu"
            assert loaded.world_state.year == 207

    def test_reuse_existing_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            s1 = mgr.get_or_create("feishu", "chat_xyz", "wu", "207")
            s2 = mgr.get_or_create("feishu", "chat_xyz", "cao", "207")  # different faction

            # s2 should be the same session (reused), so faction should remain "wu"
            assert s2.player_faction_id == "wu"
            assert s2.session_id == s1.session_id

    def test_nonexistent_session_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            assert mgr.get_session("feishu", "nonexistent") is None

    def test_delete_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            mgr.get_or_create("feishu", "chat_del", "shu", "207")

            assert mgr.get_session("feishu", "chat_del") is not None
            assert mgr.delete_session("feishu", "chat_del") is True
            assert mgr.get_session("feishu", "chat_del") is None
            assert mgr.delete_session("feishu", "chat_del") is False  # already gone

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            mgr.get_or_create("feishu", "chat_a", "shu", "207")
            mgr.get_or_create("feishu", "chat_b", "cao", "207")
            mgr.get_or_create("telegram", "chat_c", "wu", "207")

            all_sessions = mgr.list_sessions()
            assert len(all_sessions) == 3

            feishu_only = mgr.list_sessions(platform="feishu")
            assert len(feishu_only) == 2

    def test_empty_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            assert mgr.list_sessions() == []

    def test_multiple_chats_per_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            mgr.get_or_create("feishu", "chat_1", "shu", "207")
            mgr.get_or_create("feishu", "chat_2", "cao", "207")

            s1 = mgr.get_session("feishu", "chat_1")
            s2 = mgr.get_session("feishu", "chat_2")
            assert s1.player_faction_id == "shu"
            assert s2.player_faction_id == "cao"
            assert s1.session_id != s2.session_id

    def test_session_meta_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_meta", "wu", "207")
            assert session.created_at
            assert session.updated_at
            assert session.created_at <= session.updated_at

    def test_turn_number_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_turn", "shu", "207")
            session.turn_number = 5
            mgr.save_session(session)

            loaded = mgr.get_session("feishu", "chat_turn")
            assert loaded.turn_number == 5

    def test_multiplayer_fields_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_mp", "cao", "207")
            session.is_multiplayer = True
            session.player_ids = ["user_a", "user_b"]
            mgr.save_session(session)

            loaded = mgr.get_session("feishu", "chat_mp")
            assert loaded.is_multiplayer is True
            assert loaded.player_ids == ["user_a", "user_b"]


class TestSerializationHelpers:
    """Unit tests for the _to_dict / _from_dict / _coerce_value helpers."""

    def test_faction_state_roundtrip(self):
        fs = FactionState(
            id="test",
            name="Test",
            ruler_id="r1",
            capital="cap1",
            territories=["t1", "t2"],
            prestige=50,
            strength_actual=1000,
            strength_estimated=1000,
            treasury=500,
            food=300,
            tax_rate=0.3,
            morale_actual=70,
            morale_estimated=70,
            economy_actual=50,
            economy_estimated=50,
            relations={"ally": 80, "enemy": -50},
            tech_levels={"agriculture": 3},
        )
        d = _to_dict(fs)
        assert d["id"] == "test"
        assert d["prestige"] == 50
        assert d["relations"] == {"ally": 80, "enemy": -50}

        restored = _from_dict(FactionState, d)
        assert restored.id == "test"
        assert restored.prestige == 50
        assert restored.relations == {"ally": 80, "enemy": -50}

    def test_territory_roundtrip(self):
        t = Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            population=30000,
            development=25,
            terrain_type=TerrainType.PLAINS,
            neighbors=["wancheng", "xiangyang"],
        )
        d = _to_dict(t)
        restored = _from_dict(Territory, d)
        assert restored.id == "xinye"
        assert restored.name == "新野"
        assert restored.terrain_type == TerrainType.PLAINS
        assert restored.neighbors == ["wancheng", "xiangyang"]

    def test_enum_coercion(self):
        assert _coerce_value(Season, "spring") == Season.SPRING
        assert _coerce_value(Season, Season.SUMMER) == Season.SUMMER

    def test_world_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_rt", "cao", "207")
            d = _to_dict(session.world_state)
            restored = _from_dict(WorldState, d)
            assert restored.year == 207
            assert restored.season == Season.WINTER
            assert "shu" in restored.factions
            assert "cao" in restored.factions
            assert len(restored.territories) == len(session.world_state.territories)
