"""ServerClient — HTTP client for remote histrategy server.

Use this when the game engine runs on a separate server (Railway, etc.).
Lightweight: only depends on httpx.
"""

from __future__ import annotations

from typing import Any

import httpx

from .exceptions import APIError, ConnectionError, GameNotFoundError
from .types import (
    FactionStatus,
    GameIntro,
    PlanData,
    RestoreResult,
    TurnResult,
)


class ServerClient:
    """HTTP client for a remote histrategy game server.

    Usage:
        client = ServerClient(base_url="https://histrategy.example.com")
        game = client.create_game(faction="shu")
        result = client.execute_command(game["game_id"], "联吴抗曹")
        print(result["narrative"])
    """

    def __init__(
        self,
        base_url: str = "https://histrategy-production.up.railway.app",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> ServerClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── HTTP helpers ──────────────────────────────────────

    def _get(self, path: str) -> dict:
        try:
            r = self._client.get(f"{self.base_url}{path}")
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not reach server: {e}") from e
        if r.status_code == 404:
            raise GameNotFoundError(f"Game not found at {path}")
        if not r.is_success:
            detail = ""
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise APIError(r.status_code, detail)
        return r.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        try:
            r = self._client.post(f"{self.base_url}{path}", json=json)
        except httpx.RequestError as e:
            raise ConnectionError(f"Could not reach server: {e}") from e
        if r.status_code == 404:
            raise GameNotFoundError(f"Resource not found at {path}")
        if not r.is_success:
            detail = ""
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise APIError(r.status_code, detail)
        return r.json()

    # ── Game API ──────────────────────────────────────────

    def create_game(
        self,
        faction: str = "shu",
        scenario: str = "207",
        llm_api_key: str | None = None,
        session_id: str | None = None,
        language_style: str | None = None,
    ) -> GameIntro:
        """Create a new game and return the intro scene.

        Args:
            faction: "shu" (刘备), "cao" (曹操), or "wu" (孙权)
            scenario: Scenario ID, currently only "207"
            llm_api_key: User's own DeepSeek API key (not persisted)
            session_id: Orchestrator session ID for persistence
            language_style: "classical" (古文风) or "vernacular" (白话文)

        Returns:
            GameIntro with game_id, intro narrative, suggestions, faction status
        """
        body: dict[str, Any] = {"faction": faction, "scenario": scenario}
        if llm_api_key:
            body["llm_api_key"] = llm_api_key
        if session_id:
            body["session_id"] = session_id
        if language_style:
            body["language_style"] = language_style

        data = self._post("/api/games", body)
        intro = data.get("intro", {})
        if isinstance(intro, dict):
            narrative = intro.get("narrative", "")
            suggestions = intro.get("new_choices", [])
        else:
            narrative = str(intro)
            suggestions = []

        return GameIntro(
            game_id=data["game_id"],
            scenario=data.get("scenario", scenario),
            faction=data.get("faction", faction),
            narrative=narrative,
            suggestions=suggestions,
            faction_status=FactionStatus(**data.get("faction_status", {})),
        )

    def get_status(self, game_id: str) -> FactionStatus:
        """Get current faction status for a game.

        Returns:
            FactionStatus with strength, food, treasury, territories, etc.
        """
        data = self._get(f"/api/games/{game_id}")
        return FactionStatus(**data.get("faction_status", {}))

    def get_plan(self, game_id: str) -> PlanData:
        """Get Plan Mode: advisor court dialogue + strategic suggestions.

        Returns:
            PlanData with court_dialogue, suggestions, faction_status
        """
        data = self._post(f"/api/games/{game_id}/plan")
        return PlanData(
            game_id=data["game_id"],
            court_dialogue=data.get("court_dialogue", ""),
            suggestions=data.get("suggestions", []),
            season_summary=data.get("season_summary", ""),
            year=data.get("year", 207),
            season=data.get("season", "春"),
            turn=data.get("turn", 1),
            faction_status=FactionStatus(**data.get("faction_status", {})),
        )

    def execute_command(self, game_id: str, decision: str) -> TurnResult:
        """Submit a player decision and process the turn.

        Args:
            game_id: Game ID from create_game / restore_game
            decision: Free-text player decision (e.g. "联吴抗曹，攻打襄阳")

        Returns:
            TurnResult with narrative, aftermath, state_changes, suggestions, etc.
        """
        data = self._post(f"/api/games/{game_id}/command", {"decision": decision})

        # Build token usage from response (may be empty if not tracked)
        token_usage: dict[str, int] = {}
        for key in ("command_tokens", "plan_tokens", "npc_tokens", "sim_tokens"):
            token_usage[key] = data.get(key, 0)

        from .types import TokenUsage as _TU

        return TurnResult(
            game_id=data["game_id"],
            narrative=data.get("narrative", ""),
            aftermath=data.get("aftermath", ""),
            state_changes=data.get("state_changes", {}),
            events_occurred=data.get("events_occurred", []),
            npc_actions=data.get("npc_actions", []),
            new_suggestions=data.get("new_suggestions", []),
            game_over=data.get("game_over"),
            faction_status=FactionStatus(**data.get("faction_status", {})),
            year=data.get("year", 207),
            season=data.get("season", "春"),
            turn=data.get("turn", 1),
            token_usage=_TU(**token_usage),
        )

    def restore_game(
        self,
        world_state: dict,
        session_id: str | None = None,
        llm_api_key: str | None = None,
    ) -> RestoreResult:
        """Restore a game from a previously saved world_state dict.

        Args:
            world_state: Full world_state dict (from engine.to_dict() or previous save)
            session_id: Orchestrator session ID for persistence
            llm_api_key: User's own DeepSeek API key

        Returns:
            RestoreResult with game_id and restored faction status
        """
        body: dict[str, Any] = {"world_state": world_state}
        if session_id:
            body["session_id"] = session_id
        if llm_api_key:
            body["llm_api_key"] = llm_api_key

        data = self._post("/api/games/restore", body)
        return RestoreResult(
            game_id=data["game_id"],
            scenario=data.get("scenario", "207"),
            faction=data.get("faction", "?"),
            faction_status=FactionStatus(**data.get("faction_status", {})),
            restored=data.get("restored", False),
            restored_turn=data.get("restored_turn", 1),
            restored_year=data.get("restored_year", 207),
        )

    def health(self) -> dict:
        """Check server health and LLM availability."""
        return self._get("/api/health")
