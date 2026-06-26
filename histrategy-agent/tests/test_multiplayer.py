"""Tests for MultiplayerSession — faction-only, server-backed multiplayer (v2)."""

from histrategy_agent.multiplayer import FactionPlayer, GamePhase, MultiplayerSession


class TestFactionPlayer:
    """FactionPlayer dataclass tests."""

    def test_create_with_display_name(self):
        fp = FactionPlayer(faction_id="shu", display_name="刘备")
        assert fp.faction_id == "shu"
        assert fp.display_name == "刘备"
        assert not fp.is_spectator
        assert fp.joined_at != ""

    def test_create_defaults_display_name_to_faction_id(self):
        fp = FactionPlayer(faction_id="cao")
        assert fp.display_name == "cao"
        assert not fp.is_spectator

    def test_spectator(self):
        fp = FactionPlayer(faction_id="shu", is_spectator=True)
        assert fp.is_spectator

    def test_to_dict_from_dict_roundtrip(self):
        fp = FactionPlayer(faction_id="shu", display_name="刘备")
        data = fp.to_dict()
        restored = FactionPlayer.from_dict(data)
        assert restored.faction_id == "shu"
        assert restored.display_name == "刘备"
        assert restored.joined_at == fp.joined_at


class TestMultiplayerSession:
    """MultiplayerSession — thin server-backed wrapper."""

    def test_create_session(self):
        session = MultiplayerSession(
            session_id="group_abc",
            room_id="room_123",
        )
        assert session.session_id == "group_abc"
        assert session.room_id == "room_123"
        assert session.game_phase == GamePhase.LOBBY
        assert len(session.factions) == 0

    def test_add_faction_player(self):
        session = MultiplayerSession(session_id="group_abc")
        session.factions["shu"] = FactionPlayer(faction_id="shu", display_name="刘备")
        session.factions["cao"] = FactionPlayer(faction_id="cao", display_name="曹操")
        assert len(session.factions) == 2

    def test_to_dict_from_dict_roundtrip(self):
        session = MultiplayerSession(
            session_id="group_abc",
            room_id="room_xyz",
        )
        session.factions["shu"] = FactionPlayer(faction_id="shu", display_name="刘备")
        session.game_phase = GamePhase.PLAYING

        data = session.to_dict()
        restored = MultiplayerSession.from_dict(data)

        assert restored.session_id == "group_abc"
        assert restored.room_id == "room_xyz"
        assert restored.game_phase == GamePhase.PLAYING
        assert "shu" in restored.factions
        assert restored.factions["shu"].display_name == "刘备"

    def test_get_status_message_lobby(self):
        session = MultiplayerSession(session_id="test", room_id="r1")
        session.factions["shu"] = FactionPlayer(faction_id="shu", display_name="刘备")
        msg = session.get_status_message()
        assert "等待中" in msg
        assert "刘备" in msg
        assert "/histrategy start" in msg

    def test_get_status_message_playing(self):
        session = MultiplayerSession(session_id="test", room_id="r1")
        session.game_phase = GamePhase.PLAYING
        session.factions["cao"] = FactionPlayer(faction_id="cao", display_name="曹操")
        msg = session.get_status_message()
        assert "进行中" in msg
        assert "曹操" in msg

    def test_get_status_message_with_spectator(self):
        session = MultiplayerSession(session_id="test")
        session.factions["shu"] = FactionPlayer(faction_id="shu", display_name="刘备")
        session.factions["wu"] = FactionPlayer(faction_id="wu", is_spectator=True)
        msg = session.get_status_message()
        assert "👁️" in msg
