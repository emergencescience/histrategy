"""Integration tests for MultiplayerRoom + ServerClient.

Requires a running histrategy server (started via conftest.py fixture)
and DEEPSEEK_API_KEY set in environment.
"""

from __future__ import annotations

import pytest
from histrategy_sdk import MultiplayerRoom, ServerClient

# ── ServerClient tests ──────────────────────────────────


class TestServerClient:
    """Basic ServerClient integration tests."""

    def test_health(self, server_client: ServerClient):
        """Server health check returns ok."""
        result = server_client.health()
        assert isinstance(result, dict)

    def test_create_room(self, server_client: ServerClient):
        """Create a multiplayer room with pre-assigned factions."""
        result = server_client.create_room(
            pre_assigned={"caocao": "曹操", "liubei": "刘备", "sunquan": "孙权"},
        )
        assert result["ok"] is True
        assert "room_id" in result
        assert "host_token" in result
        assert result["phase"] == "waiting"
        assert "player_links" in result
        assert len(result["player_links"]) == 3

        # Verify player_links structure
        for link in result["player_links"]:
            assert "faction" in link
            assert "player_name" in link
            assert "player_token" in link
            assert "url" in link

    def test_enter_room(self, server_client: ServerClient):
        """Enter a room with a player token."""
        create_result = server_client.create_room(
            pre_assigned={"caocao": "曹操", "liubei": "刘备"},
        )
        room_id = create_result["room_id"]
        cao_link = next(l for l in create_result["player_links"] if l["faction"] == "caocao")

        enter_result = server_client.enter_room(
            room_id=room_id,
            faction="caocao",
            player_token=cao_link["player_token"],
        )
        assert enter_result["ok"] is True
        assert "user_id" in enter_result
        assert "player_token" in enter_result

    def test_room_status(self, server_client: ServerClient):
        """Get room status after creation."""
        create_result = server_client.create_room(
            pre_assigned={"caocao": "曹操", "liubei": "刘备"},
        )
        room_id = create_result["room_id"]

        status = server_client.get_room_status(room_id)
        assert status["ok"] is True
        assert status["room_id"] == room_id
        assert "phase" in status
        assert "quarter" in status
        assert "submitted" in status
        assert "pending" in status
        assert "slots" in status
        assert "players" in status


# ── MultiplayerRoom tests ───────────────────────────────


class TestMultiplayerRoom:
    """MultiplayerRoom integration tests — full flow."""

    def test_create_and_join(self, server_client: ServerClient):
        """Host creates a room, then players join."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操", "liubei": "刘备"},
        )
        assert result["ok"] is True
        room_id = result["room_id"]

        cao_link = next(l for l in result["player_links"] if l["faction"] == "caocao")
        liu_link = next(l for l in result["player_links"] if l["faction"] == "liubei")

        cao_room = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])
        liu_room = MultiplayerRoom.join(server_client, room_id, "liubei", liu_link["player_token"])

        assert cao_room.room_id == room_id
        assert cao_room.faction == "caocao"
        assert cao_room.user_id  # should have a user_id
        assert liu_room.faction == "liubei"

    @pytest.mark.skip(reason="LLM resolve in test env is slow — verified working in manual E2E")
    def test_decide_and_resolve(self, server_client: ServerClient):
        """Full turn: create room, all players decide, wait for resolve."""
        # Host creates room with 2 human players
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操", "liubei": "刘备"},
        )
        room_id = result["room_id"]

        # Both players join
        cao_link = next(l for l in result["player_links"] if l["faction"] == "caocao")
        liu_link = next(l for l in result["player_links"] if l["faction"] == "liubei")

        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])
        liu = MultiplayerRoom.join(server_client, room_id, "liubei", liu_link["player_token"])

        # Both submit decisions
        resp1 = cao.decide("发展农业，积蓄力量")
        assert resp1["ok"] is True
        assert resp1["status"] in ("waiting", "resolving")

        resp2 = liu.decide("北伐中原，光复汉室")
        assert resp2["ok"] is True

        # After the last submit, resolution should happen
        # Wait for resolve
        final = cao.wait_for_resolve(timeout=180)
        assert final["ok"] is True
        assert final["phase"] == "waiting"

        # Quarter should have advanced
        initial_status = cao.status()
        assert initial_status.get("quarter", 0) > 0

    @pytest.mark.skip(reason="LLM resolve in test env is slow — verified working in manual E2E")
    def test_get_turns(self, server_client: ServerClient):
        """Get turn history after playing a turn."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操"},
        )
        room_id = result["room_id"]

        cao_link = result["player_links"][0]
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        cao.decide("发展农业")
        cao.wait_for_resolve(timeout=180)

        turns = cao.get_turns()
        assert isinstance(turns, list)
        if turns:  # V1 engine may generate turn history
            turn = turns[0]
            assert "quarter_number" in turn
            assert "year" in turn
            assert "season" in turn

    def test_get_state(self, server_client: ServerClient):
        """Get game state."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操"},
        )
        room_id = result["room_id"]

        cao_link = result["player_links"][0]
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        state = cao.get_state()
        assert state["room_id"] == room_id
        assert "factions" in state

    def test_room_status_after_join(self, server_client: ServerClient):
        """Status reflects player joins correctly."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操", "liubei": "刘备"},
        )
        room_id = result["room_id"]

        cao_link = next(l for l in result["player_links"] if l["faction"] == "caocao")
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        status = cao.status()
        assert status["ok"] is True
        assert "slots" in status
        assert "pending" in status
        # cao should be pending (hasn't submitted yet)
        assert any("caocao" in s or s == "cao" for s in status.get("pending", [])) or status["phase"] == "resolving"

    def test_wait_for_npc_readiness_q0_prebaked(self, server_client: ServerClient):
        """Q0 NPC decisions are pre-baked — wait_for_npc_readiness returns fast."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操", "liubei": "刘备", "sunquan": "孙权"},
        )
        room_id = result["room_id"]

        # Join as one human player
        cao_link = next(l for l in result["player_links"] if l["faction"] == "caocao")
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        # All 3 factions are human; other scenario factions are AI NPCs
        # Wait for NPC readiness — should be fast for Q0 (pre-baked)
        status = cao.wait_for_npc_readiness(timeout=60)
        assert status["ok"] is True
        assert "slots" in status

        # Verify AI NPCs have submitted (not in pending)
        pending = status.get("pending", [])
        slots = status.get("slots", {})
        for fid, slot in slots.items():
            if slot.get("occupant_type") == "ai_npc":
                assert fid not in pending, f"AI NPC {fid} still pending after wait_for_npc_readiness"

    def test_wait_for_npc_readiness_no_npcs(self, server_client: ServerClient):
        """When all factions are human, wait_for_npc_readiness returns immediately."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操", "liubei": "刘备"},
        )
        room_id = result["room_id"]

        cao_link = next(l for l in result["player_links"] if l["faction"] == "caocao")
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        # Should return quickly since there are no AI NPCs or all NPCs are handled
        status = cao.wait_for_npc_readiness(timeout=10)
        assert status["ok"] is True

    def test_create_with_scenario_and_metadata(self, server_client: ServerClient):
        """Scenario and metadata are forwarded correctly to the server."""
        result = MultiplayerRoom.create(
            server_client,
            {"caocao": "曹操"},
            scenario="three-kingdoms",
            metadata={"lang": "zh"},
        )
        assert result["ok"] is True
        room_id = result["room_id"]

        cao_link = result["player_links"][0]
        cao = MultiplayerRoom.join(server_client, room_id, "caocao", cao_link["player_token"])

        status = cao.status()
        assert status["ok"] is True
        # Should use the 207 scenario (default for zh)
        assert "slots" in status


class TestMultiplayerRoomTypes:
    """Verify newly exported types."""

    def test_types_importable(self):
        """All multiplayer types are importable from the SDK."""
        from histrategy_sdk import (
            CreateRoomResult,
            PlayerLink,
            RoomStatus,
        )

        assert CreateRoomResult is not None
        assert PlayerLink is not None
        assert RoomStatus is not None
