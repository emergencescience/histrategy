"""
三國志略 — REST API Server

Thin FastAPI wrapper around the v2 GameEngine.
Provides HTTP endpoints for the Web client and external integrations.

Usage:
    histrategy serve                 # Start server on :8080
    histrategy serve --port 3000     # Custom port
    histrategy serve --host 0.0.0.0  # Listen on all interfaces
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


# ─── Models ──────────────────────────────────────────────────────

class CreateGameRequest(BaseModel):
    faction: str = "shu"  # shu | cao | wu
    scenario: str = "207"
    new: bool = True


class CommandRequest(BaseModel):
    decision: str


class GameSummary(BaseModel):
    game_id: str
    scenario: str
    faction: str
    faction_name: str
    year: int
    season: str
    turn: int
    strength: int
    food: int
    treasury: int
    territories: int
    is_active: bool
    is_game_over: bool


class PlanResponse(BaseModel):
    game_id: str
    court_dialogue: str
    suggestions: list[str]
    season_summary: str
    year: int
    season: str
    turn: int
    faction_status: dict[str, Any]


class CommandResponse(BaseModel):
    game_id: str
    narrative: str
    aftermath: str
    state_changes: dict[str, int]
    events_occurred: list[str]
    npc_actions: list[str]
    new_suggestions: list[str]
    game_over: dict | None
    faction_status: dict[str, Any]
    year: int
    season: str
    turn: int


class FactionStatus(BaseModel):
    name: str
    strength: int
    food: int
    treasury: int
    territories: list[str]
    morale: int
    is_active: bool


# ─── Engine Pool ─────────────────────────────────────────────────

# In-memory game pool: {game_id: GameEngine}
_games: dict[str, Any] = {}


def _get_or_create_engine(faction: str = "shu", scenario: str = "207",
                          new: bool = True) -> tuple[str, Any]:
    """Get existing game by ID or create a new one."""
    # If not new, try to find an existing game
    if not new and _games:
        # Return the most recently created game
        return list(_games.keys())[-1], list(_games.values())[-1]

    # Create new game
    from histrategy.engine.game import GameEngine

    game_id = uuid.uuid4().hex[:12]
    engine = GameEngine(scenario=scenario, new_game=True)
    engine.set_player_faction(faction)

    _games[game_id] = engine
    return game_id, engine


def _get_engine(game_id: str) -> Any | None:
    """Get engine by game ID."""
    return _games.get(game_id)


def _build_faction_status(engine) -> dict:
    """Extract player faction status from engine."""
    if engine._use_v2:
        ws = engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return {}
        return {
            "name": player.name,
            "strength": player.strength_actual,
            "food": player.food,
            "treasury": player.treasury,
            "territories": player.territories,
            "morale": player.morale_actual,
            "is_active": player.is_active,
            "year": ws.year,
            "season": ws.season.cn,
            "turn": ws.turn_number,
        }
    else:
        player = engine.world_state.get_player_faction()
        if not player:
            return {}
        return {
            "name": player.name,
            "strength": player.strength,
            "food": player.food,
            "treasury": player.treasury,
            "territories": player.territories,
            "morale": player.morale,
            "is_active": player.is_active,
            "year": getattr(engine.world_state, "year", 190),
            "season": getattr(engine.world_state, "current_season_cn", "春"),
            "turn": getattr(engine.world_state, "turn", 1),
        }


# ─── FastAPI App ─────────────────────────────────────────────────


def create_app() -> Any:
    """Create and configure the FastAPI application."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="三國志略 API",
        description="Histrategy v2 — Three Kingdoms Strategy Game Engine API",
        version="0.2.0",
    )

    # CORS: allow all origins in MVP (localhost dev)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Routes ──────────────────────────────────────────

    @app.get("/")
    def root():
        """Serve the web client."""
        from fastapi.responses import FileResponse
        import os as _os
        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "index.html"))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "games_active": len(_games)}

    @app.post("/api/games")
    def create_game(req: CreateGameRequest):
        """Create a new game and return the intro scene."""
        game_id, engine = _get_or_create_engine(
            faction=req.faction, scenario=req.scenario, new=req.new
        )

        # Get intro scene
        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            intro = engine.get_intro_scene()

        status = _build_faction_status(engine)

        return {
            "game_id": game_id,
            "scenario": engine.scenario,
            "faction": engine.world_state_v2.player_faction_id if engine._use_v2 else engine.world_state.player_faction_id,
            "intro": intro,
            "faction_status": status,
        }

    @app.get("/api/games/{game_id}")
    def get_game(game_id: str):
        """Get current game state."""
        engine = _get_engine(game_id)
        if not engine:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Game not found"})

        status = _build_faction_status(engine)
        return {
            "game_id": game_id,
            "faction_status": status,
        }

    @app.post("/api/games/{game_id}/plan")
    def get_plan(game_id: str):
        """Get Plan Mode: advisor court + strategic suggestions."""
        engine = _get_engine(game_id)
        if not engine:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Game not found"})

        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            plan = engine.get_plan_data()

        status = _build_faction_status(engine)

        return {
            "game_id": game_id,
            "court_dialogue": plan.get("court_dialogue", ""),
            "suggestions": plan.get("suggestions", []),
            "season_summary": plan.get("season_summary", ""),
            "year": status.get("year", 207),
            "season": status.get("season", "春"),
            "turn": status.get("turn", 1),
            "faction_status": status,
        }

    @app.post("/api/games/{game_id}/command")
    def execute_command(game_id: str, req: CommandRequest):
        """Submit a decision and process the turn."""
        engine = _get_engine(game_id)
        if not engine:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Game not found"})

        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            result = engine.process_turn(req.decision)

        status = _build_faction_status(engine)

        # Extract new suggestions from result
        new_suggestions = result.get("new_choices", [])

        return {
            "game_id": game_id,
            "narrative": result.get("narrative", ""),
            "aftermath": result.get("aftermath", ""),
            "state_changes": result.get("state_changes", {}),
            "events_occurred": result.get("events_occurred", []),
            "npc_actions": result.get("npc_actions", result.get("npc_reactions", [])),
            "new_suggestions": new_suggestions,
            "game_over": result.get("game_over"),
            "faction_status": status,
            "year": status.get("year", 207),
            "season": status.get("season", "春"),
            "turn": status.get("turn", 1),
        }

    @app.get("/api/games")
    def list_games():
        """List all active games."""
        games = []
        for gid, engine in _games.items():
            status = _build_faction_status(engine)
            games.append({
                "game_id": gid,
                "faction_name": status.get("name", "?"),
                "year": status.get("year", 0),
                "season": status.get("season", "?"),
                "turn": status.get("turn", 0),
                "is_active": status.get("is_active", True),
            })
        return {"games": games, "count": len(games)}

    return app


# ─── Server Runner ───────────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the REST API server."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
