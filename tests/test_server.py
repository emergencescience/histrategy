"""
Tests for REST API server endpoints.

Uses FastAPI TestClient to call endpoints without starting a real server.
ImportError is caught at module level so tests skip gracefully when
fastapi is not installed (it's an optional dependency).
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

# Check optional dependency
try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not installed — pip install histrategy[web]", allow_module_level=True)  # noqa: DTZ003


@pytest.fixture
def client():
    """Create a fresh TestClient with an empty game pool."""
    from histrategy.server.api import _games, create_app

    _games.clear()
    app = create_app()
    return TestClient(app)


@pytest.fixture
def cleanup_games():
    """Ensure game pool is cleaned up after each test."""
    from histrategy.server.api import _games

    yield
    _games.clear()


class TestHealth:
    """Health and root endpoints."""

    def test_root_returns_api_info(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # Root now serves the web client HTML page
        assert "text/html" in resp.headers.get("content-type", "")
        assert "三國志略" in resp.text

    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCreateGame:
    """POST /api/games — create new game."""

    def test_create_game_shu_207(self, client):
        resp = client.post("/api/games", json={
            "faction": "shu", "scenario": "207", "new": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "game_id" in data
        assert len(data["game_id"]) == 12
        assert data["faction"] in ("shu", "liubei")
        assert "intro" in data
        assert "faction_status" in data
        assert data["faction_status"]["is_active"] is True

    def test_create_game_cao(self, client):
        resp = client.post("/api/games", json={
            "faction": "cao", "scenario": "207", "new": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "game_id" in data
        assert data["faction"] in ("cao", "cao")

    def test_create_game_defaults_to_shu(self, client):
        resp = client.post("/api/games", json={})
        assert resp.status_code == 200
        assert "game_id" in resp.json()


class TestGetGame:
    """GET /api/games/{id} — fetch game state."""

    def test_get_existing_game(self, client):
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        resp = client.get(f"/api/games/{game_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert "faction_status" in data

    def test_get_missing_game(self, client):
        resp = client.get("/api/games/nonexistent")
        assert resp.status_code == 404


class TestPlanMode:
    """POST /api/games/{id}/plan — strategic suggestions."""

    def test_get_plan_for_created_game(self, client):
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        resp = client.post(f"/api/games/{game_id}/plan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert "court_dialogue" in data
        assert isinstance(data["suggestions"], list)
        assert len(data["suggestions"]) > 0
        assert "season_summary" in data
        assert "year" in data

    def test_plan_nonexistent_game(self, client):
        resp = client.post("/api/games/nonexistent/plan")
        assert resp.status_code == 404


class TestCommandMode:
    """POST /api/games/{id}/command — process player decision."""

    def test_execute_command(self, client):
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        resp = client.post(f"/api/games/{game_id}/command", json={
            "decision": "发展农业",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "narrative" in data
        assert "aftermath" in data
        assert "state_changes" in data
        assert "faction_status" in data
        # Verifies the turn was actually processed
        assert data["turn"] >= 1

    def test_execute_multiple_turns(self, client):
        """Run 3 turns to verify engine stability."""
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        decisions = ["发展农业", "招募乡勇", "派遣使者联络孙权"]
        for decision in decisions:
            resp = client.post(f"/api/games/{game_id}/command", json={
                "decision": decision,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("game_over") is None, f"Unexpected game over on turn: {data.get('turn')}"

        # After 3 turns, check state is consistent
        resp = client.get(f"/api/games/{game_id}")
        assert resp.status_code == 200
        status = resp.json()["faction_status"]
        assert status["turn"] >= 3

    def test_command_nonexistent_game(self, client):
        resp = client.post("/api/games/nonexistent/command", json={
            "decision": "test",
        })
        assert resp.status_code == 404


class TestListGames:
    """GET /api/games — list active games."""

    def test_list_games_empty(self, client):
        resp = client.get("/api/games")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_games_after_create(self, client):
        client.post("/api/games", json={"faction": "shu"})
        client.post("/api/games", json={"faction": "cao"})

        resp = client.get("/api/games")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["games"]) == 2


class TestGamePool:
    """Engine pool lifecycle tests."""

    def test_game_pool_isolation(self, client):
        """Each create call returns a unique game_id."""
        resp1 = client.post("/api/games", json={"faction": "shu"})
        resp2 = client.post("/api/games", json={"faction": "cao"})

        gid1 = resp1.json()["game_id"]
        gid2 = resp2.json()["game_id"]
        assert gid1 != gid2

        # Check each game is independent
        client.post(f"/api/games/{gid1}/command", json={"decision": "发展农业"})
        status1 = client.get(f"/api/games/{gid1}").json()["faction_status"]
        status2 = client.get(f"/api/games/{gid2}").json()["faction_status"]
        assert status1["turn"] != status2["turn"], "Games are not independent"


class TestSummaryAndExportVideo:
    """Tests for summary and video export endpoints."""

    def test_get_game_summary(self, client):
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        resp = client.post(f"/api/games/{game_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert "summary" in data
        assert "events_count" in data

    def test_export_video_not_found(self, client):
        resp = client.post("/api/games/nonexistent_game/export_video")
        assert resp.status_code == 404

    @patch("histrategy.cli.record.generate_video")
    def test_export_video_success(self, mock_generate_video, client):
        mock_generate_video.return_value = "/path/to/mock_video.mp4"
        
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        resp = client.post(f"/api/games/{game_id}/export_video")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert data["video_path"] == "/path/to/mock_video.mp4"
        assert data["status"] == "success"
        mock_generate_video.assert_called_once_with(game_id)


class TestAuthAndPersistence:
    """Tests for JWT auth and autosave endpoint."""

    def test_autosave_without_jwt_returns_degraded(self, client):
        """Autosave without JWT should return ok=false gracefully, not 401."""
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]
        resp = client.post(f"/api/games/{game_id}/autosave")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "reason" in data

    def test_create_game_with_llm_api_key(self, client):
        """llm_api_key in body is accepted and sets env for LLM (not stored)."""
        resp = client.post("/api/games", json={
            "faction": "shu",
            "llm_api_key": "sk-test-key-1234",
        })
        assert resp.status_code == 200
        assert "game_id" in resp.json()

    def test_create_game_with_session_id(self, client):
        """session_id in body is accepted and stored in game meta."""
        resp = client.post("/api/games", json={
            "faction": "shu",
            "session_id": "test-session-uuid-1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "game_id" in data


class TestRestoreGame:
    """POST /api/games/restore — resume from saved world state."""

    def test_restore_preserves_turn_number(self, client):
        """After playing 3 turns, restoring should show correct turn number."""
        # Create and play
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        decisions = ["发展农业", "招募乡勇", "派遣使者联络孙权"]
        for decision in decisions:
            client.post(f"/api/games/{game_id}/command", json={"decision": decision})

        # Get current state after 3 turns
        status_resp = client.get(f"/api/games/{game_id}")
        status = status_resp.json()["faction_status"]
        original_turn = status["turn"]
        assert original_turn >= 3, f"Expected turn >= 3, got {original_turn}"

        # Build a serialized world state (simulating orchestrator save)
        from histrategy.server.api import _games
        engine = _games.get(game_id)
        assert engine is not None, "Engine not found in game pool"
        saved_state = engine.to_dict()

        # Restore from saved state
        restore_resp = client.post("/api/games/restore", json={
            "world_state": saved_state,
        })
        assert restore_resp.status_code == 200
        restore_data = restore_resp.json()
        assert restore_data["restored"] is True
        assert restore_data["restored_turn"] == original_turn
        assert restore_data["restored_year"] == status["year"]

        # Verify the restored game can get plan data
        restored_id = restore_data["game_id"]
        plan_resp = client.post(f"/api/games/{restored_id}/plan")
        assert plan_resp.status_code == 200
        plan = plan_resp.json()
        assert plan["turn"] == original_turn
        assert "court_dialogue" in plan
        assert len(plan["suggestions"]) > 0

    def test_restore_preserves_territory_changes(self, client):
        """Territory changes from gameplay should survive restore."""
        create_resp = client.post("/api/games", json={"faction": "cao"})
        game_id = create_resp.json()["game_id"]

        # Play some turns (territories may change due to NPC actions)
        for _ in range(3):
            client.post(f"/api/games/{game_id}/command", json={"decision": "发展农业"})

        # Save and restore
        from histrategy.server.api import _games
        engine = _games.get(game_id)
        assert engine is not None, "Engine not found in game pool"
        saved_state = engine.to_dict()

        restore_resp = client.post("/api/games/restore", json={
            "world_state": saved_state,
        })
        assert restore_resp.status_code == 200
        restore_data = restore_resp.json()

        # Verify faction territories match
        original_player = saved_state["factions"].get(saved_state["player_faction_id"])
        restored_status = restore_data["faction_status"]
        assert restored_status["territories"] == original_player["territories"]

    def test_restore_can_continue_playing(self, client):
        """After restore, the game should be fully playable."""
        create_resp = client.post("/api/games", json={"faction": "shu"})
        game_id = create_resp.json()["game_id"]

        # Play 2 turns
        client.post(f"/api/games/{game_id}/command", json={"decision": "发展农业"})
        client.post(f"/api/games/{game_id}/command", json={"decision": "招募乡勇"})

        # Save and restore
        from histrategy.server.api import _games
        engine = _games.get(game_id)
        assert engine is not None, "Engine not found in game pool"
        saved_state = engine.to_dict()

        restore_resp = client.post("/api/games/restore", json={
            "world_state": saved_state,
        })
        restored_id = restore_resp.json()["game_id"]

        # Continue playing from restored state
        resp = client.post(f"/api/games/{restored_id}/command", json={
            "decision": "派遣使者联络孙权",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("game_over") is None, "Game should not be over after restore+play"

    def test_restore_minimal_state_succeeds(self, client):
        """Even with minimal world_state data, restore creates a playable game."""
        resp = client.post("/api/games/restore", json={
            "world_state": {"player_faction_id": "cao", "scenario": "207"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["restored"] is True
        assert "game_id" in data
        assert data["faction"] == "cao"
        # Verify the restored game is playable
        restored_id = data["game_id"]
        plan_resp = client.post(f"/api/games/{restored_id}/plan")
        assert plan_resp.status_code == 200
        plan = plan_resp.json()
        assert len(plan["suggestions"]) > 0

