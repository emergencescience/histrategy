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

import contextlib
import uuid
from typing import Any

from pydantic import BaseModel

# ─── Models ──────────────────────────────────────────────────────


class CreateGameRequest(BaseModel):
    faction: str = "shu"  # shu | cao | wu
    scenario: str = "207"
    new: bool = True
    session_id: str | None = None  # Orchestrator session ID
    llm_api_key: str | None = None  # User's own DeepSeek API Key (not persisted)
    language_style: str | None = None  # "classical" | "vernacular" — narrative style preference


class CommandRequest(BaseModel):
    decision: str
    session_id: str | None = None  # Orchestrator session ID for debug logging


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


class RestoreGameRequest(BaseModel):
    world_state: dict  # Full world_state dict from orchestrator save
    session_id: str | None = None
    llm_api_key: str | None = None


# ─── Engine Pool ─────────────────────────────────────────────────

# In-memory game pool: {game_id: GameEngine}
_games: dict[str, Any] = {}
# Game metadata: {game_id: {"session_id": str, "jwt_token": str}}
_game_meta: dict[str, dict] = {}
_llm_provider: str | None = None  # Set by run_server / create_app


def _get_or_create_engine(
    faction: str = "shu", scenario: str = "207", new: bool = True, llm_api_key: str | None = None
) -> tuple[str, Any]:
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
    with contextlib.suppress(Exception):
        llm = LLMAdapter(provider=_llm_provider or None)

    game_id = uuid.uuid4().hex  # full UUID v4
    engine = GameEngine(scenario=scenario, new_game=True, llm=llm)
    engine.set_player_faction(faction)

    _games[game_id] = engine
    return game_id, engine


def _get_engine(game_id: str) -> Any | None:
    """Get engine by game ID."""
    return _games.get(game_id)


def _format_character_events(events: list) -> list[str]:
    """Convert v2 character event dicts to human-readable Chinese strings.

    The v2 engine returns rich event dicts (e.g. loyalty_change, natural_death,
    defection). The frontend expects a list of strings — React cannot render
    raw objects as children (React error #31).
    """
    formatted: list[str] = []
    for evt in events:
        if not isinstance(evt, dict):
            formatted.append(str(evt))
            continue
        etype = evt.get("type", "unknown")
        name = evt.get("character_name", evt.get("character_id", "?"))
        if etype == "loyalty_change":
            delta = evt.get("delta", 0)
            sign = "+" if delta > 0 else ""
            new_val = evt.get("new_loyalty", "?")
            reason = evt.get("reason", "")
            formatted.append(f"{name} 忠诚度 {sign}{delta} (→{new_val}): {reason}")
        elif etype == "natural_death":
            year = evt.get("year", "?")
            formatted.append(f"{name} 自然死亡（{year}年）")
        elif etype == "loyalty_impact":
            cname = evt.get("character_name", evt.get("character_id", "?"))
            delta = evt.get("delta", 0)
            reason = evt.get("reason", "")
            formatted.append(f"{cname} 忠诚度受影响 {delta:+d}: {reason}")
        elif etype == "defection":
            from_faction = evt.get("from_faction", "?")
            to_faction = evt.get("to_faction", "?")
            reason = evt.get("reason", "")
            formatted.append(f"{name} 从{from_faction}叛逃至{to_faction}: {reason}")
        else:
            # Fallback: JSON serialize unknown event types
            formatted.append(str(evt))
    return formatted


def _build_faction_status(engine) -> dict:
    """Extract player faction status from engine."""
    # City-to-Chinese-name mapping (engine stores city IDs, not province IDs)
    _CITY_NAMES: dict[str, str] = {
        "xinye": "新野",
        "xiangyang": "襄阳",
        "jiangling": "江陵",
        "jiangxia": "江夏",
        "changsha": "长沙",
        "chengdu": "成都",
        "jiangzhou": "江州",
        "yongchang": "永昌",
        "jianye": "建业",
        "lujiang": "庐江",
        "wujun": "吴郡",
        "kuaiji": "会稽",
        "nanhai": "南海",
        "luoyang": "洛阳",
        "xuchang": "许昌",
        "changan": "长安",
        "yecheng": "邺城",
        "beiping": "北平",
        "hanshong": "汉中",
        "jinyang": "晋阳",
        "tianshui": "天水",
        "wuwei": "武威",
        "runan": "汝南",
        "xiapi": "下邳",
        "beihai": "北海",
        "jixian": "蓟县",
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
            "year": getattr(engine.world_state, "year", 207),
            "season": getattr(engine.world_state, "current_season_cn", "春"),
            "turn": getattr(engine.world_state, "turn", 1),
        }


# ─── FastAPI App ─────────────────────────────────────────────────


def create_app(llm_provider: str | None = None) -> Any:
    """Create and configure the FastAPI application."""
    global _llm_provider

    # Auto-detect LLM provider from environment if not explicitly set
    if llm_provider:
        _llm_provider = llm_provider
    elif not _llm_provider:
        import os as _os

        if _os.environ.get("DEEPSEEK_API_KEY"):
            _llm_provider = "deepseek"
        elif _os.environ.get("OPENAI_API_KEY"):
            _llm_provider = "openai"
        elif _os.environ.get("TONGYI_API_KEY"):
            _llm_provider = "tongyi"
        elif _os.environ.get("OPENROUTER_API_KEY"):
            _llm_provider = "openrouter"
        elif _os.environ.get("LLM_API_KEY") or _os.environ.get("LLM_API_BASE"):
            _llm_provider = "custom"

    from fastapi import FastAPI, Header
    from fastapi.middleware.cors import CORSMiddleware

    from histrategy.server.persistence_adapter import create_persistence_adapter

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

    # ── Database initialization ─────────────────────────
    try:
        from histrategy.db.connection import init_db

        init_db()
    except Exception as _db_err:
        import logging as _logging

        _logging.getLogger("histrategy").warning(f"DB init skipped: {_db_err}")

    # ─── Routes ──────────────────────────────────────────

    @app.get("/")
    def root():
        """Serve the web client."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "index.html"))

    @app.get("/manual")
    def manual():
        """Serve the player manual."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "manual.html"))

    @app.get("/css/{path:path}")
    def serve_css(path: str):
        """Serve CSS files."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "css", path))

    @app.get("/js/{path:path}")
    def serve_js(path: str):
        """Serve JavaScript files."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "js", path))

    @app.get("/images/{path:path}")
    def serve_images(path: str):
        """Serve image files."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "images", path))

    @app.get("/api/health")
    def health():
        # Actually probe LLM availability
        llm_available = False
        llm_provider_name = _llm_provider or "none"
        llm_debug: dict[str, Any] = {}
        if _llm_provider:
            import os as _os

            from histrategy.llm.adapter import LLMAdapter

            try:
                adapter = LLMAdapter(provider=_llm_provider)
                llm_available = adapter.is_available
                llm_debug = {
                    "has_api_key": bool(adapter.api_key),
                    "key_length": len(adapter.api_key) if adapter.api_key else 0,
                    "key_prefix": adapter.api_key[:5] + "..." if adapter.api_key else "",
                    "has_client": adapter.client is not None,
                    "provider_name": adapter.provider_name,
                    "api_base": adapter.api_base,
                    "model": adapter.model,
                }
            except Exception as e:
                llm_debug = {"error": f"{type(e).__name__}: {e}"}

            # Also show raw env state (safely)
            raw_key = _os.environ.get("DEEPSEEK_API_KEY", "")
            llm_debug["env_key_exists"] = bool(raw_key)
            llm_debug["env_key_length"] = len(raw_key) if raw_key else 0

        # Check v2 engine availability
        v2_available = False
        v2_error = None
        try:
            from histrategy.engine.game import _V2_AVAILABLE as _v2a
            from histrategy.engine.game import _V2_IMPORT_ERROR as _v2err

            v2_available = _v2a
            v2_error = _v2err
        except ImportError as e:
            v2_error = str(e)
        except Exception as e:
            v2_error = f"{type(e).__name__}: {e}"

        return {
            "status": "ok",
            "games_active": len(_games),
            "llm": {
                "available": llm_available,
                "provider": llm_provider_name,
                "debug": llm_debug,
            },
            "engine": {
                "version": "v2" if v2_available else "v1",
                "v2_available": v2_available,
                "v2_error": v2_error,
            },
        }

    @app.post("/api/games")
    def create_game(req: CreateGameRequest, authorization: str | None = Header(default=None)):
        """Create a new game and return the intro scene."""
        game_id, engine = _get_or_create_engine(
            faction=req.faction, scenario=req.scenario, new=req.new, llm_api_key=req.llm_api_key
        )

        # Store session metadata if provided
        if req.session_id:
            jwt_token = None
            if authorization and authorization.startswith("Bearer "):
                jwt_token = authorization[len("Bearer ") :]
            _game_meta[game_id] = {"session_id": req.session_id, "jwt_token": jwt_token}
            # Also store on engine directly (survives _game_meta loss on restart)
            engine.set_debug_context(req.session_id, jwt_token or "")

        # Store language style preference for use by engine
        if req.language_style:
            meta = _game_meta.setdefault(game_id, {})
            meta["language_style"] = req.language_style

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
            "faction": engine.world_state_v2.player_faction_id
            if engine._use_v2
            else engine.world_state.player_faction_id,
            "intro": intro,
            "faction_status": status,
        }

    class RestoreGameRequest(BaseModel):  # noqa: F811 — redefined for use inside create_app closure
        world_state: dict
        session_id: str | None = None
        llm_api_key: str | None = None

    @app.post("/api/games/restore")
    def restore_game(req: RestoreGameRequest, authorization: str | None = Header(default=None)):
        """Restore a game from a saved world_state dict.

        Used when resuming a game from the orchestrator. The frontend passes
        the world_state from GET /sessions/{id} and gets back a game_id for
        subsequent commands.

        On restore failure, returns a partial state with restore_error for
        the frontend to handle gracefully (e.g. show error + offer new game).
        """
        import logging
        import traceback as _tb

        _logger = logging.getLogger(__name__)

        import os as _os

        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        if req.llm_api_key:
            _os.environ["DEEPSEEK_API_KEY"] = req.llm_api_key

        try:
            llm = LLMAdapter(provider=_llm_provider or None)
        except Exception:
            llm = None

        restore_error = None
        try:
            engine = GameEngine.from_dict(req.world_state, llm=llm)
        except Exception as e:
            _logger.error("Game restore failed: %s\n%s", e, _tb.format_exc())
            # Try to extract at least faction info for a new game fallback
            faction = req.world_state.get("player_faction_id", "shu")
            saved_turn = req.world_state.get("turn_number", 1)
            saved_year = req.world_state.get("year", 207)
            restore_error = {
                "message": f"Save restore failed: {str(e)[:200]}",
                "faction": faction,
                "saved_turn": saved_turn,
                "saved_year": saved_year,
            }
            # Create a new game with the same faction so player can continue
            game_id, engine = _get_or_create_engine(faction=faction, new=True, llm_api_key=req.llm_api_key)
            if req.session_id:
                jwt_token = None
                if authorization and authorization.startswith("Bearer "):
                    jwt_token = authorization[len("Bearer ") :]
                _game_meta[game_id] = {"session_id": req.session_id, "jwt_token": jwt_token}
                engine.set_debug_context(req.session_id, jwt_token or "")
            status = _build_faction_status(engine)
            return {
                "game_id": game_id,
                "faction": faction,
                "faction_status": status,
                "restored": False,
                "restore_error": restore_error,
            }

        game_id = uuid.uuid4().hex  # full UUID v4
        _games[game_id] = engine

        if req.session_id:
            jwt_token = None
            if authorization and authorization.startswith("Bearer "):
                jwt_token = authorization[len("Bearer ") :]
            _game_meta[game_id] = {"session_id": req.session_id, "jwt_token": jwt_token}

        status = _build_faction_status(engine)

        if req.llm_api_key:
            _os.environ.pop("DEEPSEEK_API_KEY", None)

        intro = _build_resume_narrative(engine)

        return {
            "game_id": game_id,
            "scenario": engine.scenario,
            "faction": engine.world_state_v2.player_faction_id
            if engine._use_v2
            else engine.world_state.player_faction_id,
            "intro": intro,
            "faction_status": status,
            "restored": True,
            "restored_turn": status.get("turn", 1),
            "restored_year": status.get("year", 207),
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

        # Extract token usage for credit billing
        _usage = plan.get("_usage", {})

        return {
            "game_id": game_id,
            "court_dialogue": plan.get("court_dialogue", ""),
            "suggestions": plan.get("suggestions", []),
            "season_summary": plan.get("season_summary", ""),
            "year": status.get("year", 207),
            "season": status.get("season", "春"),
            "turn": status.get("turn", 1),
            "faction_status": status,
            "_usage": _usage,
        }

    @app.post("/api/games/{game_id}/command")
    def execute_command(game_id: str, req: CommandRequest, authorization: str | None = Header(default=None)):
        """Submit a decision and process the turn. Persists turn history to orchestrator."""
        engine = _get_engine(game_id)
        if not engine:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=404, content={"error": "Game not found"})

        from histrategy.engine.game import _suppress_stderr

        # Set debug context for Postgres logging
        # Prefer session_id from request (survives multi-worker), fallback to _game_meta
        session_id = req.session_id or _game_meta.get(game_id, {}).get("session_id", game_id)
        jwt_token = _game_meta.get(game_id, {}).get("jwt_token", "")
        engine.set_debug_context(session_id, jwt_token)

        with _suppress_stderr():
            result = engine.process_turn(req.decision)

        status = _build_faction_status(engine)

        # Extract new suggestions from result
        new_suggestions = result.get("new_choices", [])

        response_data = {
            "game_id": game_id,
            "narrative": result.get("narrative", ""),
            "aftermath": result.get("aftermath", ""),
            "state_changes": result.get("state_changes", {}),
            "events_occurred": _format_character_events(result.get("events_occurred", [])),
            "npc_actions": result.get("npc_actions", result.get("npc_reactions", [])),
            "new_suggestions": new_suggestions,
            "game_over": result.get("game_over"),
            "faction_status": status,
            "year": status.get("year", 207),
            "season": status.get("season", "春"),
            "turn": status.get("turn", 1),
            "_usage": result.get("_usage", {}),
        }

        # ── Persist turn AND world_state via adapter ──
        try:
            meta = _game_meta.get(game_id, {})
            session_id = meta.get("session_id", game_id)
            jwt_token = meta.get("jwt_token")
            if not jwt_token and authorization and authorization.startswith("Bearer "):
                jwt_token = authorization[len("Bearer ") :]

            if session_id:
                adapter = create_persistence_adapter(jwt_token or "")
                usage = result.get("_usage", {})
                # Save state
                try:
                    world_dict = engine.to_dict()
                    adapter.save_state(
                        session_id,
                        world_dict,
                        status.get("turn", 1),
                        status.get("year", 207),
                        status.get("season", "春"),
                    )
                except Exception:
                    pass
                # Append turn history
                with contextlib.suppress(Exception):
                    adapter.append_turn(
                        session_id,
                        turn_number=status.get("turn", 1),
                        year=status.get("year", 207),
                        season=status.get("season", "春"),
                        player_decision=req.decision,
                        narrative=result.get("narrative", ""),
                        aftermath=result.get("aftermath", ""),
                        state_changes=result.get("state_changes"),
                        tokens=usage,
                    )
        except Exception:
            pass  # Non-blocking — don't fail the game on persistence error

        # ── Debug log: token usage to stdout (Railway captures) + Postgres ──
        _usage = result.get("_usage", {})
        _sim_tokens = _usage.get("sim_tokens") or _usage.get("command_tokens", 0)
        if _sim_tokens > 0:
            log_entry = {
                "session_id": session_id,
                "turn_number": status.get("turn", 1),
                "year": status.get("year", 207),
                "season": status.get("season", "春"),
                "tokens": _sim_tokens,
                "model": _os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
            }
            # Log to stdout (visible in railway logs)
            import json as _json

            print(f"[HISTRATEGY_LOG] {_json.dumps(log_entry, ensure_ascii=False)}", flush=True)
            # Also POST to orchestrator Postgres
            try:
                _jwt = _game_meta.get(game_id, {}).get("jwt_token", "")
                import httpx as _httpx

                _orch_url = _os.environ.get("ORCHESTRATOR_URL", "https://api.emergence.science").rstrip("/")
                _httpx.post(
                    f"{_orch_url}/games/histrategy/api/log/batch",
                    json={
                        "session_id": session_id,
                        "turn_number": status.get("turn", 1),
                        "llm_calls": [
                            {
                                "call_type": "macro_simulate",
                                "provider": "deepseek",
                                "model": _os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
                                "total_tokens": _sim_tokens,
                            }
                        ],
                        "sim_events": [],
                    },
                    headers={"Authorization": f"Bearer {_jwt}"} if _jwt else {},
                    timeout=5.0,
                )
            except Exception:
                pass  # Non-blocking

        return response_data

    @app.get("/api/games")
    def list_games():
        """List all active games."""
        games = []
        for gid, engine in _games.items():
            status = _build_faction_status(engine)
            games.append(
                {
                    "game_id": gid,
                    "faction_name": status.get("name", "?"),
                    "year": status.get("year", 0),
                    "season": status.get("season", "?"),
                    "turn": status.get("turn", 0),
                    "is_active": status.get("is_active", True),
                }
            )
        return {"games": games, "count": len(games)}

    @app.get("/api/credit/status")
    def credit_status():
        """Return credit cost estimation for the game engine.

        Called by the frontend to show per-turn cost estimates.
        Actual credit deduction happens in the Orchestrator proxy.
        """
        PRICING = {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "input_cost_per_1m_tokens": 0.55,
            "output_cost_per_1m_tokens": 2.19,
            "markup_percent": 50,
            "credit_exchange_rate_usd": 1.0,
            "micro_credits_per_credit": 1_000_000,
        }
        ESTIMATED_TOKENS = {
            "plan_prompt": 3500,
            "plan_completion": 3200,
            "command_prompt": 4000,
            "command_completion": 2500,
            "npc_prompt": 1500,
            "npc_completion": 800,
        }
        total_prompt = (
            ESTIMATED_TOKENS["plan_prompt"] + ESTIMATED_TOKENS["command_prompt"] + ESTIMATED_TOKENS["npc_prompt"]
        )
        total_completion = (
            ESTIMATED_TOKENS["plan_completion"]
            + ESTIMATED_TOKENS["command_completion"]
            + ESTIMATED_TOKENS["npc_completion"]
        )
        base_cost_usd = (
            total_prompt * PRICING["input_cost_per_1m_tokens"] / 1_000_000
            + total_completion * PRICING["output_cost_per_1m_tokens"] / 1_000_000
        )
        markup_usd = base_cost_usd * PRICING["markup_percent"] / 100
        total_cost_usd = base_cost_usd + markup_usd
        estimated_cost_micro = round(total_cost_usd * PRICING["micro_credits_per_credit"])
        return {
            "pricing": PRICING,
            "estimated_tokens_per_turn": ESTIMATED_TOKENS,
            "estimated_cost_per_turn": {
                "base_usd": round(base_cost_usd, 6),
                "markup_usd": round(markup_usd, 6),
                "total_usd": round(total_cost_usd, 6),
                "micro_credits": estimated_cost_micro,
                "credits_display": f"{estimated_cost_micro / 1_000_000:.4f}",
            },
            "estimated_turns_per_credit": round(1_000_000 / estimated_cost_micro, 1),
            "llm_available": _llm_provider is not None,
        }

    @app.post("/api/games/{game_id}/summary")
    def get_game_summary(game_id: str):
        """Generate/fetch endgame summary (chronicle) for a game."""
        import json
        import os
        from pathlib import Path

        from histrategy.llm.adapter import LLMAdapter
        from histrategy.llm.endgame_summary import generate_chronicle

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
                    with open(path, encoding="utf-8") as f:
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
                                player_events.append(
                                    {"title": evt.get("title", evt_id), "description": evt.get("description", "")}
                                )
                            else:
                                player_events.append({"title": evt_id, "description": ""})
                    else:
                        player_events = [{"title": evt_id, "description": ""} for evt_id in completed]
            elif isinstance(loaded_data, list):
                player_events = loaded_data

        # 2. If player_events is still empty, try to get from active engine
        if not player_events and engine and getattr(engine, "_use_v2", False) and engine.world_state_v2:
            ws = engine.world_state_v2
            completed = ws.completed_events
            if getattr(engine, "history_engine", None):
                for evt_id in completed:
                    evt = next((e for e in engine.history_engine.all_events if e["id"] == evt_id), None)
                    if evt:
                        player_events.append(
                            {"title": evt.get("title", evt_id), "description": evt.get("description", "")}
                        )
                    else:
                        player_events.append({"title": evt_id, "description": ""})
            else:
                player_events = [{"title": evt_id, "description": ""} for evt_id in completed]

        # 3. Fallback: try loading from global or local current_session_log.json
        if not player_events:
            log_path = data_dir / "current_session_log.json"
            if log_path.exists():
                try:
                    with open(log_path, encoding="utf-8") as f:
                        log_entries = json.load(f)
                    for entry in log_entries:
                        player_events.append(
                            {
                                "title": f"第{entry.get('turn')}回合 政令: 「{entry.get('player_decision')}」",
                                "description": entry.get("aftermath", entry.get("narrative", "")),
                            }
                        )
                except Exception:
                    pass

        # Build LLM adapter if available
        llm = None
        if _llm_provider:
            with contextlib.suppress(Exception):
                llm = LLMAdapter(provider=_llm_provider)

        summary_text = generate_chronicle(player_events, llm_adapter=llm)
        return {
            "game_id": game_id,
            "summary": summary_text,
            "events_count": len(player_events),
        }

    @app.post("/api/games/{game_id}/export_video")
    def export_video(game_id: str):
        """Export replay video for a game."""
        from fastapi import HTTPException

        from histrategy.cli.record import generate_video

        try:
            video_path = generate_video(game_id)
            return {"game_id": game_id, "video_path": video_path, "status": "success"}
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate video: {str(e)}") from e

    @app.post("/api/games/{game_id}/autosave")
    def autosave_game(game_id: str, authorization: str | None = Header(default=None)):
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
            jwt_token = authorization[len("Bearer ") :]

        if not jwt_token:
            return {"ok": False, "reason": "No JWT token provided"}

        status = _build_faction_status(engine)
        meta = _game_meta.get(game_id, {})

        # Build world state dict from engine
        world_state = engine.to_dict() if engine._use_v2 and engine.world_state_v2 else {"faction": status}

        try:
            adapter = create_persistence_adapter(jwt_token or "")
            session_id = meta.get("session_id", game_id)
            adapter.save_state(
                session_id,
                world_state,
                status.get("turn", 1),
                status.get("year", 207),
                status.get("season", "春"),
            )
            return {"ok": True, "session_id": session_id}
        except Exception as e:
            return {"ok": False, "reason": f"Save failed: {e}"}

    # ═══════════════════════════════════════════════════════════
    # Multiplayer Room Endpoints (v2: room_player symmetric)
    # ═══════════════════════════════════════════════════════════

    from fastapi import Body

    @app.post("/api/rooms")
    def api_create_room(body: dict = Body(...)):
        """创建房间。

        human_faction_ids: Host 选择哪些势力由人类控制，其余自动变 AI NPC。
        玩家通过 /mp?room=xxx&faction=cao 直接进入。

        示例: {"human_faction_ids": ["cao", "shu", "wu"]}
        """
        from histrategy.server.room_manager import create_room

        human_faction_ids = body.get("human_faction_ids", ["cao", "shu", "wu"])

        result = create_room(
            host_user_id=body.get("user_id", ""),
            host_name=body.get("display_name", ""),
            scenario=body.get("scenario", "207"),
            human_faction_ids=human_faction_ids,
        )
        return result

    @app.post("/api/rooms/{room_id}/enter")
    def api_enter_room(room_id: str, body: dict = Body(...)):
        """进入房间（任何人都可以，host/player/spectator）。"""
        from histrategy.server.room_manager import enter_room

        return enter_room(
            room_id,
            body.get("user_id", ""),
            body.get("display_name", ""),
        )

    @app.post("/api/rooms/{room_id}/pick")
    def api_pick_faction(room_id: str, body: dict = Body(...)):
        """选择势力。"""
        from histrategy.server.room_manager import pick_faction

        return pick_faction(
            room_id,
            body.get("user_id", ""),
            body.get("faction_id", ""),
        )

    @app.post("/api/rooms/{room_id}/start")
    def api_start_room(room_id: str, body: dict = Body(...)):
        """host 开始游戏。"""
        from histrategy.server.room_manager import start_game

        return start_game(room_id, body.get("user_id", ""))

    @app.post("/api/rooms/{room_id}/decide")
    def api_submit_decision(room_id: str, body: dict = Body(...)):
        """提交本季度决策。"""
        from histrategy.server.room_manager import submit_decision

        return submit_decision(
            room_id,
            body.get("faction_id", ""),
            body.get("user_id", ""),
            body.get("decision", ""),
        )

    @app.get("/api/rooms/{room_id}/status")
    def api_room_status(room_id: str, faction_id: str = ""):
        """获取房间状态。"""
        from histrategy.server.room_manager import get_room_status

        fid = faction_id if faction_id else None
        return get_room_status(room_id, fid)

    @app.get("/mp")
    def serve_multiplayer_page():
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "mp.html"))

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


def _build_resume_narrative(engine) -> dict:
    """Generate a context-aware resume summary for restored games.

    Returns an intro dict matching the GameCreatedResponse.intro shape
    with narrative text summarizing the current game state.
    """
    status = _build_faction_status(engine)
    if not status:
        return {"narrative": "游戏已恢复", "new_choices": [], "npc_actions": []}

    name = status.get("name", "未知势力")
    year = status.get("year", 207)
    season = status.get("season", "春")
    turn = status.get("turn", 1)
    strength = status.get("strength", 0)
    food = status.get("food", 0)
    treasury = status.get("treasury", 0)
    morale = status.get("morale", 0)
    territory_names = status.get("territory_names", [])
    territories_str = "、".join(territory_names) if territory_names else "无领地"

    # Build narrative
    narrative = (
        f"## 📜 存档恢复 · 公元{year}年{season} · 第{turn}回合\n\n"
        f"**{name}** 势力，当前坐拥 **{territories_str}**。\n\n"
        f"| 兵力 | 粮草 | 库金 | 民心 |\n"
        f"|------|------|------|------|\n"
        f"| {strength} | {food} | {treasury} | {morale} |\n\n"
        f"谋臣武将已在帐中候命。请颁布君令，继续你的霸业。"
    )

    # Generate suggestions based on current state
    suggestions = []
    if hasattr(engine, "_use_v2") and engine._use_v2 and engine.world_state_v2:
        ws = engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if player:
            if player.food < 5000:
                suggestions.append("粮草不足，建议发展农业或征粮")
            if player.treasury < 3000:
                suggestions.append("库金紧张，可考虑征税或贸易")
            if player.strength_actual < 10000:
                suggestions.append("兵力薄弱，宜招募乡勇壮大军队")

    # Check for NPC actions since last save
    npc_actions = []
    if hasattr(engine, "_use_v2") and engine._use_v2 and engine.world_state_v2:
        ws = engine.world_state_v2
        for fid, f in ws.factions.items():
            if fid != ws.player_faction_id and f.is_active:
                npc_actions.append(f"{f.name}势力仍在活跃")

    return {
        "narrative": narrative,
        "new_choices": suggestions,
        "npc_actions": npc_actions,
    }
