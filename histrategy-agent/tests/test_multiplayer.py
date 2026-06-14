"""Tests for MultiplayerSession — group chat multiplayer state management."""

import os

from histrategy_agent.multiplayer import GamePhase, MultiplayerSession, PlayerSlot


class TestPlayerSlot:
    """PlayerSlot dataclass tests."""

    def test_create_slot(self):
        slot = PlayerSlot(user_id="user123", faction_id="shu", display_name="张三")
        assert slot.user_id == "user123"
        assert slot.faction_id == "shu"
        assert slot.display_name == "张三"
        assert slot.is_spectator is False
        assert slot.joined_at  # Should be auto-populated

    def test_slot_defaults(self):
        slot = PlayerSlot(user_id="user456", faction_id="cao")
        assert slot.display_name == "user456"  # defaults to user_id
        assert slot.is_spectator is False

    def test_spectator_slot(self):
        slot = PlayerSlot(user_id="watch", faction_id="shu", is_spectator=True)
        assert slot.is_spectator is True

    def test_to_dict_from_dict(self):
        """PlayerSlot to_dict/from_dict round-trip."""
        slot = PlayerSlot(user_id="u1", faction_id="shu", display_name="刘备")
        data = slot.to_dict()
        restored = PlayerSlot.from_dict(data)
        assert restored.user_id == slot.user_id
        assert restored.faction_id == slot.faction_id
        assert restored.display_name == slot.display_name
        assert restored.is_spectator == slot.is_spectator
        assert restored.joined_at == slot.joined_at


class TestMultiplayerSession:
    """MultiplayerSession lifecycle tests."""

    def test_create_session(self):
        session = MultiplayerSession(
            session_id="group_abc",
            host_user_id="host_user",
        )
        assert session.session_id == "group_abc"
        assert session.host_user_id == "host_user"
        assert session.game_phase == GamePhase.LOBBY
        assert len(session.players) == 0

    def test_add_player(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host_user")
        slot = session.add_player("player1", "赵将军")
        assert slot.user_id == "player1"
        assert slot.display_name == "赵将军"
        assert slot.faction_id == "shu"  # First available
        assert "player1" in session.players

    def test_add_multiple_players_assigns_different_factions(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        s1 = session.add_player("p1", "刘备")
        s2 = session.add_player("p2", "曹操")
        s3 = session.add_player("p3", "孙权")

        assert s1.faction_id != s2.faction_id
        assert s2.faction_id != s3.faction_id
        assert s1.faction_id != s3.faction_id
        assert len(session.players) == 3

    def test_add_player_returns_existing(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        s1 = session.add_player("p1", "Player One")
        s2 = session.add_player("p1", "Player One Again")  # same user
        assert s1 is s2
        assert s1.display_name == "Player One"  # original name kept

    def test_cannot_add_after_game_started(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "Player 1")
        session.start_game()
        try:
            session.add_player("p2", "Late")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_remove_player(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "Player 1")
        session.add_player("p2", "Player 2")
        assert "p1" in session.players

        assert session.remove_player("p1") is True
        assert "p1" not in session.players

    def test_cannot_remove_host(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("host", "Host Player")
        assert session.remove_player("host") is False
        assert "host" in session.players

    def test_start_game(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")

        assert session.game_phase == GamePhase.LOBBY
        session.start_game()
        assert session.game_phase == GamePhase.PLAYING
        assert len(session.turn_order) == 2

    def test_get_current_player(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")
        session.start_game()

        current = session.get_current_player()
        assert current is not None
        assert current.user_id in ("p1", "p2")  # shuffled

    def test_advance_turn(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")
        session.start_game()

        first = session.get_current_player()
        second = session.advance_turn()

        assert second is not None
        assert first.user_id != second.user_id

    def test_full_round_cycles_back(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "P1")
        session.start_game()

        # After advancing past one player, cycle back
        current = session.advance_turn()
        assert current is not None

    def test_end_game(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("p1", "P1")
        session.start_game()

        session.end_game()
        assert session.game_phase == GamePhase.FINISHED
        assert session.get_current_player() is None

    def test_status_message_lobby(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("host", "房主")
        session.add_player("p2", "玩家二")

        msg = session.get_status_message()
        assert "等待中" in msg or "多人游戏" in msg
        assert "host" in msg or "房主" in msg
        assert "join" in msg

    def test_status_message_playing(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        session.add_player("host", "房主")
        session.start_game()

        msg = session.get_status_message()
        assert "进行中" in msg or "PLAYING" in msg
        assert "当前行动" in msg

    def test_max_players(self):
        session = MultiplayerSession(session_id="group_abc", host_user_id="host")
        for i in range(7):
            session.add_player(f"p{i}", f"Player {i}")
        assert len(session.players) == 7

        try:
            session.add_player("p7", "Overflow")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass


class TestMultiplayerPersistence:
    """Persistence tests — save, load, round-trip."""

    def test_save_and_load(self, tmp_path):
        """Save a lobby session, load it back, verify all fields match."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

        session = MultiplayerSession(
            session_id="persist_test",
            host_user_id="host_user",
        )
        session.add_player("p1", "Player 1")
        session.add_player("p2", "Player 2")

        # Save
        session.save()

        # Load
        loaded = MultiplayerSession.load("persist_test")
        assert loaded is not None
        assert loaded.session_id == "persist_test"
        assert loaded.host_user_id == "host_user"
        assert loaded.game_phase == GamePhase.LOBBY
        assert len(loaded.players) == 2
        assert "p1" in loaded.players
        assert loaded.players["p1"].display_name == "Player 1"
        assert loaded.players["p1"].faction_id == "shu"

    def test_save_and_load_playing(self, tmp_path):
        """Save a started game, load it back, verify game phase and turn order."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

        session = MultiplayerSession(
            session_id="playing_test",
            host_user_id="host",
        )
        session.add_player("p1", "刘备")
        session.add_player("p2", "曹操")
        session.start_game()

        loaded = MultiplayerSession.load("playing_test")
        assert loaded is not None
        assert loaded.game_phase == GamePhase.PLAYING
        assert len(loaded.turn_order) == 2
        assert set(loaded.turn_order) == {"p1", "p2"}

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading a nonexistent session should return None, not crash."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)
        assert MultiplayerSession.load("no_such_session") is None

    def test_auto_save_on_add_player(self, tmp_path):
        """add_player() should auto-save."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

        session = MultiplayerSession(
            session_id="auto_save_test",
            host_user_id="host",
        )
        session.add_player("p1", "Player 1")
        # Load from disk — should already be there
        loaded = MultiplayerSession.load("auto_save_test")
        assert loaded is not None
        assert "p1" in loaded.players

    def test_remove_persists(self, tmp_path):
        """remove_player() should auto-save."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

        session = MultiplayerSession(
            session_id="remove_test",
            host_user_id="host",
        )
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")
        session.remove_player("p1")

        loaded = MultiplayerSession.load("remove_test")
        assert loaded is not None
        assert "p1" not in loaded.players
        assert "p2" in loaded.players

    def test_end_game_persists(self, tmp_path):
        """end_game() should auto-save."""
        os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path)

        session = MultiplayerSession(
            session_id="end_test",
            host_user_id="host",
        )
        session.add_player("p1", "P1")
        session.start_game()
        session.end_game()

        loaded = MultiplayerSession.load("end_test")
        assert loaded is not None
        assert loaded.game_phase == GamePhase.FINISHED

    def test_to_from_dict_roundtrip(self):
        """to_dict → from_dict should produce an equivalent session."""
        session = MultiplayerSession(
            session_id="dict_test",
            host_user_id="host",
        )
        session.add_player("p1", "Player 1")
        session.add_player("p2", "Player 2")
        session.start_game()

        data = session.to_dict()
        restored = MultiplayerSession.from_dict(data)

        assert restored.session_id == session.session_id
        assert restored.host_user_id == session.host_user_id
        assert restored.game_phase == session.game_phase
        assert restored.current_turn_index == session.current_turn_index
        assert restored.turn_order == session.turn_order
        assert len(restored.players) == len(session.players)
