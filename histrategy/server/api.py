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
    session_id: str | None = None      # Orchestrator session ID
    llm_api_key: str | None = None     # User's own DeepSeek API Key (not persisted)


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
# Game metadata: {game_id: {"session_id": str, "jwt_token": str}}
_game_meta: dict[str, dict] = {}
_llm_provider: str | None = None  # Set by run_server / create_app


def _get_or_create_engine(faction: str = "shu", scenario: str = "207",
                          new: bool = True,
                          llm_api_key: str | None = None) -> tuple[str, Any]:
    """Get existing game by ID or create a new one."""
    if not new and _games:
        return list(_games.keys())[-1], list(_games.values())[-1]

    from histrategy.engine.game import GameEngine
    from histrategy.llm.adapter import LLMAdapter

    # Build LLM adapter if API key or server provider is available
    llm = None
    # Temporarily set the key so detect_provider() can find it
    if llm_api_key:
        import os as _os
        _os.environ["DEEPSEEK_API_KEY"] = llm_api_key
    try:
        llm = LLMAdapter(provider=_llm_provider or None)
    except Exception:
        pass

    game_id = uuid.uuid4().hex[:12]
    engine = GameEngine(scenario=scenario, new_game=True, llm=llm)
    engine.set_player_faction(faction)

    _games[game_id] = engine
    return game_id, engine


def _get_engine(game_id: str) -> Any | None:
    """Get engine by game ID."""
    return _games.get(game_id)


def _build_faction_status(engine) -> dict:
    """Extract player faction status from engine."""
    # City-to-Chinese-name mapping (engine stores city IDs, not province IDs)
    _CITY_NAMES: dict[str, str] = {
        "xinye": "新野", "xiangyang": "襄阳", "jiangling": "江陵",
        "jiangxia": "江夏", "changsha": "长沙", "chengdu": "成都",
        "jiangzhou": "江州", "yongchang": "永昌", "jianye": "建业",
        "lujiang": "庐江", "wujun": "吴郡", "kuaiji": "会稽",
        "nanhai": "南海", "luoyang": "洛阳", "xuchang": "许昌",
        "changan": "长安", "yecheng": "邺城", "beiping": "北平",
        "hanshong": "汉中", "jinyang": "晋阳", "tianshui": "天水",
        "wuwei": "武威", "runan": "汝南", "xiapi": "下邳",
        "beihai": "北海", "jixian": "蓟县",
    }

    if engine._use_v2:
        ws = engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return {}
        # Resolve territory names from engine
        territory_names = []
        for tid in player.territories:
            t = ws.territories.get(tid)
            if t:
                territory_names.append(t.name)
            else:
                territory_names.append(_CITY_NAMES.get(tid, tid))

        return {
            "name": player.name,
            "faction_id": ws.player_faction_id,
            "strength": player.strength_actual,
            "food": player.food,
            "treasury": player.treasury,
            "territories": player.territories,
            "territory_names": territory_names,
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


def create_app(llm_provider: str | None = None) -> Any:
    """Create and configure the FastAPI application."""
    global _llm_provider
    if llm_provider:
        _llm_provider = llm_provider

    from fastapi import FastAPI, Header
    from fastapi.middleware.cors import CORSMiddleware
    from histrategy.server.auth import get_current_user_id
    from histrategy.server.persistence import save_game as persistence_save

    app = FastAPI(
        title="三國志略 API",
        description="Histrategy v2 — Three Kingdoms Strategy Game Engine API",
        version="0.2.0",
    )

    # CORS: allow Emergence ecosystem origins + env extras
    import os as _os

    _cors_origins = [
        "http://localhost:3000",
        "https://emergence.science",
        "https://www.emergence.science",
        "https://surprisal-portal.vercel.app",
    ]
    # Allow extra origins from env (comma-separated)
    _extra = _os.environ.get("ALLOWED_ORIGINS", "")
    if _extra:
        _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
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
        return {
            "status": "ok",
            "games_active": len(_games),
            "llm": {
                "available": _llm_provider is not None,
                "provider": _llm_provider or "none",
            },
        }

    @app.post("/api/games")
    def create_game(req: CreateGameRequest,
                    authorization: str | None = Header(default=None)):
        """Create a new game and return the intro scene."""
        game_id, engine = _get_or_create_engine(
            faction=req.faction, scenario=req.scenario, new=req.new,
            llm_api_key=req.llm_api_key
        )

        # Store session metadata if provided
        if req.session_id:
            _game_meta[game_id] = {"session_id": req.session_id}

        # Get intro scene
        from histrategy.engine.game import _suppress_stderr

        with _suppress_stderr():
            intro = engine.get_intro_scene()

        status = _build_faction_status(engine)

        # Clear LLM key from env after engine creation
        if req.llm_api_key:
            import os as _os
            _os.environ.pop("DEEPSEEK_API_KEY", None)

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

    @app.post("/api/games/{game_id}/summary")
    def get_game_summary(game_id: str):
        """Generate/fetch endgame summary (chronicle) for a game."""
        import os
        import json
        from pathlib import Path
        from histrategy.llm.endgame_summary import generate_chronicle
        from histrategy.llm.adapter import LLMAdapter

        # Check if the game is active in memory
        engine = _get_engine(game_id)
        
        player_events = []
        
        # 1. Try to load from session directory
        data_dir = Path(os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy")))
        session_dir = data_dir / "sessions" / game_id
        
        world_paths = [
            session_dir / "world_v2.json",
            session_dir / "world.json",
            session_dir / "event_history.json",
            data_dir / "world_v2.json",
        ]
        
        loaded_data = None
        for path in world_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded_data = json.load(f)
                    break
                except Exception:
                    pass

        # If we loaded data, try to extract event history or completed events
        if loaded_data:
            if isinstance(loaded_data, dict):
                # Try getting event_history or completed_events
                if "event_history" in loaded_data:
                    player_events = loaded_data["event_history"]
                elif "completed_events" in loaded_data:
                    # Try to map completed_events if we can, or just use them as titles
                    completed = loaded_data["completed_events"]
                    if engine and getattr(engine, "history_engine", None):
                        for evt_id in completed:
                            evt = next((e for e in engine.history_engine.all_events if e["id"] == evt_id), None)
                            if evt:
                                player_events.append({
                                    "title": evt.get("title", evt_id),
                                    "description": evt.get("description", "")
                                })
                            else:
                                player_events.append({"title": evt_id, "description": ""})
                    else:
                        player_events = [{"title": evt_id, "description": ""} for evt_id in completed]
            elif isinstance(loaded_data, list):
                player_events = loaded_data

        # 2. If player_events is still empty, try to get from active engine
        if not player_events and engine:
            if getattr(engine, "_use_v2", False) and engine.world_state_v2:
                ws = engine.world_state_v2
                completed = ws.completed_events
                if getattr(engine, "history_engine", None):
                    for evt_id in completed:
                        evt = next((e for e in engine.history_engine.all_events if e["id"] == evt_id), None)
                        if evt:
                            player_events.append({
                                "title": evt.get("title", evt_id),
                                "description": evt.get("description", "")
                            })
                        else:
                            player_events.append({"title": evt_id, "description": ""})
                else:
                    player_events = [{"title": evt_id, "description": ""} for evt_id in completed]

        # 3. Fallback: try loading from global or local current_session_log.json
        if not player_events:
            log_path = data_dir / "current_session_log.json"
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        log_entries = json.load(f)
                    for entry in log_entries:
                        player_events.append({
                            "title": f"第{entry.get('turn')}回合 政令: 「{entry.get('player_decision')}」",
                            "description": entry.get("aftermath", entry.get("narrative", ""))
                        })
                except Exception:
                    pass

        # Build LLM adapter if available
        llm = None
        if _llm_provider:
            try:
                llm = LLMAdapter(provider=_llm_provider)
            except Exception:
                pass

        summary_text = generate_chronicle(player_events, llm_adapter=llm)
        return {
            "game_id": game_id,
            "summary": summary_text,
            "events_count": len(player_events),
        }

    @app.post("/api/games/{game_id}/export_video")
    def export_video(game_id: str):
        """Export replay video for a game."""
        from histrategy.cli.record import generate_video
        from fastapi import HTTPException
        
        try:
            video_path = generate_video(game_id)
            return {
                "game_id": game_id,
                "video_path": video_path,
                "status": "success"
            }
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate video: {str(e)}")

    @app.post("/api/games/{game_id}/autosave")
    def autosave_game(game_id: str,
                      authorization: str | None = Header(default=None)):
        """Auto-save: persist game state to Orchestrator slot 0.

        Requires Authorization Bearer JWT.
        Degrades gracefully if no JWT or ORCHESTRATOR_URL not set.
        """
        engine = _get_engine(game_id)
        if not engine:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Game not found"})

        # Check for JWT
        jwt_token = None
        if authorization and authorization.startswith("Bearer "):
            jwt_token = authorization[len("Bearer "):]

        if not jwt_token:
            return {"ok": False, "reason": "No JWT token provided"}

        # Check ORCHESTRATOR_URL
        import os as _os
        orchestrator_url = _os.environ.get("ORCHESTRATOR_URL", "")
        if not orchestrator_url:
            return {"ok": False, "reason": "ORCHESTRATOR_URL not configured"}

        status = _build_faction_status(engine)
        meta = _game_meta.get(game_id, {})

        # Build world state dict from engine
        if engine._use_v2 and engine.world_state_v2:
            ws = engine.world_state_v2
            world_state = {
                "faction_id": ws.player_faction_id,
                "year": ws.year,
                "turn": ws.turn_number,
                "season": ws.season.cn,
                "faction": status,
            }
        else:
            world_state = {"faction": status}

        try:
            # Use session_id from meta, fall back to game_id
            session_id = meta.get("session_id", game_id)
            result = persistence_save(
                jwt_token=jwt_token,
                session_id=session_id,
                slot=0,
                world_state=world_state,
                turn=status.get("turn", 1),
                year=status.get("year", 207),
                season=status.get("season", "春"),
            )
            return {"ok": True, "save_id": result.get("save_id")}
        except Exception as e:
            return {"ok": False, "reason": f"Save failed: {e}"}

    return app


# ─── Server Runner ───────────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 8080, api_key: str | None = None):
    """Run the REST API server."""
    import os
    import uvicorn

    # Set API key from parameter or environment
    provider = None
    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key
        provider = "deepseek"
    elif os.environ.get("DEEPSEEK_API_KEY"):
        provider = "deepseek"
    elif os.environ.get("OPENAI_API_KEY"):
        provider = "openai"

    app = create_app(llm_provider=provider)

    if provider:
        print(f"🤖 LLM: {provider} API 已配置 — 智能叙事引擎已启用")
    else:
        print("📴 LLM: 未检测到 API Key — 使用离线模式（关键字规则引擎）")
        print("   💡 设置: export DEEPSEEK_API_KEY='sk-...' 或 histrategy --serve --api-key sk-...")

    uvicorn.run(app, host=host, port=port, log_level="info")
