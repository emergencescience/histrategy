"""Tests for MultiplayerSession — group chat multiplayer state management."""

from histrategy_agent.multiplayer import MultiplayerSession, GamePhase, PlayerSlot


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
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host_user"
        )
        slot = session.add_player("player1", "赵将军")
        assert slot.user_id == "player1"
        assert slot.display_name == "赵将军"
        assert slot.faction_id == "shu"  # First available
        assert "player1" in session.players

    def test_add_multiple_players_assigns_different_factions(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        s1 = session.add_player("p1", "刘备")
        s2 = session.add_player("p2", "曹操")
        s3 = session.add_player("p3", "孙权")

        assert s1.faction_id != s2.faction_id
        assert s2.faction_id != s3.faction_id
        assert s1.faction_id != s3.faction_id
        assert len(session.players) == 3

    def test_add_player_returns_existing(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        s1 = session.add_player("p1", "Player One")
        s2 = session.add_player("p1", "Player One Again")  # same user
        assert s1 is s2
        assert s1.display_name == "Player One"  # original name kept

    def test_cannot_add_after_game_started(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "Player 1")
        session.start_game()
        try:
            session.add_player("p2", "Late")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_remove_player(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "Player 1")
        session.add_player("p2", "Player 2")
        assert "p1" in session.players

        assert session.remove_player("p1") is True
        assert "p1" not in session.players

    def test_cannot_remove_host(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("host", "Host Player")
        assert session.remove_player("host") is False
        assert "host" in session.players

    def test_start_game(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")

        assert session.game_phase == GamePhase.LOBBY
        session.start_game()
        assert session.game_phase == GamePhase.PLAYING
        assert len(session.turn_order) == 2

    def test_get_current_player(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")
        session.start_game()

        current = session.get_current_player()
        assert current is not None
        assert current.user_id in ("p1", "p2")  # shuffled

    def test_advance_turn(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "P1")
        session.add_player("p2", "P2")
        session.start_game()

        first = session.get_current_player()
        second = session.advance_turn()

        assert second is not None
        assert first.user_id != second.user_id

    def test_full_round_cycles_back(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "P1")
        session.start_game()

        # After advancing past one player, cycle back
        current = session.advance_turn()
        assert current is not None

    def test_end_game(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("p1", "P1")
        session.start_game()

        session.end_game()
        assert session.game_phase == GamePhase.FINISHED
        assert session.get_current_player() is None

    def test_status_message_lobby(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("host", "房主")
        session.add_player("p2", "玩家二")

        msg = session.get_status_message()
        assert "等待中" in msg or "多人游戏" in msg
        assert "host" in msg or "房主" in msg
        assert "join" in msg

    def test_status_message_playing(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        session.add_player("host", "房主")
        session.start_game()

        msg = session.get_status_message()
        assert "进行中" in msg or "PLAYING" in msg
        assert "当前行动" in msg

    def test_max_players(self):
        session = MultiplayerSession(
            session_id="group_abc", host_user_id="host"
        )
        for i in range(7):
            session.add_player(f"p{i}", f"Player {i}")
        assert len(session.players) == 7

        try:
            session.add_player("p7", "Overflow")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
