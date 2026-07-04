"""
三國志略 — REST API Server

Thin FastAPI wrapper around the SQL-backed room system.
Provides HTTP endpoints for the Web client, orchestrator proxy, and external integrations.

API groups:
  /api/rooms/*        — Multiplayer rooms (PostgreSQL, symmetric)
  /api/single-player/* — Single-player thin wrapper over rooms
  /api/scenarios/*    — Scenario metadata + timeline
  /api/health         — Health check (LLM, engine, DB)

Usage:
    histrategy serve                 # Start server on :8080
    histrategy serve --port 3000     # Custom port
    histrategy serve --host 0.0.0.0  # Listen on all interfaces
"""

from __future__ import annotations

from typing import Any

# ─── Shared Helpers ──────────────────────────────────────────────


def _safe_json_loads(value: str | None, default: Any = None) -> Any:
    """Safely deserialize a JSON string, returning default on failure."""
    if not value:
        return default
    try:
        import json as _json

        return _json.loads(value)
    except (TypeError, ValueError):
        return default


# ─── FastAPI App ─────────────────────────────────────────────────

_llm_provider: str | None = None  # Set by run_server / create_app


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

    from fastapi import FastAPI

    app = FastAPI(
        title="三國志略 API",
        description="Histrategy — Multiplayer Three Kingdoms Strategy Game Engine API",
        version="0.3.0",
    )

    # ── Database initialization ─────────────────────────
    try:
        from histrategy.db.connection import init_db

        init_db()
    except Exception as _db_err:
        import logging as _logging

        _logging.getLogger("histrategy").warning(f"DB init skipped: {_db_err}")

    # ─── Static File Routes ─────────────────────────────

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

    @app.get("/mp")
    def serve_multiplayer_page():
        """Serve the multiplayer web client."""
        import os as _os

        from fastapi.responses import FileResponse

        web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
        return FileResponse(_os.path.join(web_dir, "mp.html"))

    # ─── Health ─────────────────────────────────────────

    @app.get("/api/health")
    def health():
        """Health check: LLM availability, engine mode, DB type."""
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

            raw_key = _os.environ.get("DEEPSEEK_API_KEY", "")
            llm_debug["env_key_exists"] = bool(raw_key)
            llm_debug["env_key_length"] = len(raw_key) if raw_key else 0

        # v2 engine is always available (histrategy-engine is a hard dependency)
        v2_available = True
        v2_error = None

        # Detect active engine mode
        from histrategy.engine.engine_switch import detect_engine_mode

        config_engine = detect_engine_mode().value

        # DB type detection
        try:
            from histrategy.db.connection import _IS_SQLITE as _sqlite_flag
            from histrategy.db.connection import DATABASE_URL as _db_url

            db_type = "sqlite" if _sqlite_flag else "postgres"
            db_host = _db_url.split("@")[-1].split("/")[0] if "@" in _db_url else "local"
        except Exception:
            db_type = "unknown"
            db_host = "unknown"

        return {
            "status": "ok",
            "llm": {
                "available": llm_available,
                "provider": llm_provider_name,
                "debug": llm_debug,
            },
            "engine": {
                "version": config_engine,
                "config_engine": config_engine,
                "v2_available": v2_available,
                "v2_error": v2_error,
            },
            "db": {
                "type": db_type,
                "host": db_host,
            },
        }

    # ═══════════════════════════════════════════════════════════
    # Multiplayer Room API (/api/rooms)
    #
    # PostgreSQL-persisted room-based multiplayer (symmetric, DB-backed).
    # Survives pod restarts. Auth handled by orchestrator proxy (X-User-Id header).
    # ═══════════════════════════════════════════════════════════

    from fastapi import Body, Header

    @app.post("/api/rooms")
    def api_create_room(
        body: dict = Body(...),  # noqa: B008
        x_user_id: str = Header(default="", alias="X-User-Id"),
    ):
        """Create a multiplayer room.

        pre_assigned = {"cao": "张三", "shu": "李四"}
        → Host pre-assigns factions; each player gets a join link.
        → Unassigned factions become AI NPCs.

        Orchestrator proxy injects X-User-Id header (real user UUID).
        """
        from histrategy.server.room_manager import create_room

        # Prefer X-User-Id (injected by orchestrator proxy) over body user_id
        pre_assigned = body.get("pre_assigned")
        if not pre_assigned:
            return {
                "ok": False,
                "error": 'pre_assigned is required — e.g. {"cao": "张三", "shu": "李四"}',
            }

        result = create_room(
            scenario=body.get("scenario_id") or body.get("scenario", "three-kingdoms"),
            pre_assigned=pre_assigned,
            metadata=body.get("metadata"),
        )
        return result

    @app.post("/api/rooms/{room_id}/decide")
    def api_submit_decision(room_id: str, body: dict = Body(...)):  # noqa: B008
        """Submit this quarter's decision."""
        from histrategy.server.room_manager import submit_decision

        return submit_decision(
            room_id,
            body.get("faction_id", ""),
            body.get("decision", ""),
        )

    @app.get("/api/rooms/{room_id}/status")
    def api_room_status(room_id: str, faction_id: str = ""):
        """Get room status."""
        from histrategy.server.room_manager import get_room_status

        fid = faction_id if faction_id else None
        return get_room_status(room_id, fid)

    @app.get("/api/rooms/{room_id}/turns")
    def api_room_turns(room_id: str):
        """Return all quarter_turn records with turn_deltas and policy_state per quarter."""
        from histrategy.db.models import get_policies_by_quarter, get_quarter_turns, get_turn_deltas
        from histrategy.server.room_manager import _get_faction_names, _get_room

        raw_turns = get_quarter_turns(room_id, limit=10000)

        turns = []
        for row in raw_turns:
            qn = row["quarter_number"]

            # Fetch turn deltas for this quarter
            raw_deltas = get_turn_deltas(room_id, qn)
            deltas = {}
            for d in raw_deltas:
                fid = d["faction_id"]
                if fid not in deltas:
                    deltas[fid] = []
                deltas[fid].append(
                    {
                        "delta_type": d["delta_type"],
                        "old_value": d["old_value"],
                        "new_value": d["new_value"],
                        "delta": d["delta"],
                        "reason": d.get("reason", ""),
                        "source": d.get("source", ""),
                    }
                )

            # Fetch policies for this quarter
            raw_policies = get_policies_by_quarter(room_id, qn)
            policies = {}
            for p in raw_policies:
                fid = p["faction_id"]
                if fid not in policies:
                    policies[fid] = {}
                policies[fid][p["policy_name"]] = {
                    "policy_type": p["policy_type"],
                    "policy_level": p.get("policy_level", 1),
                    "params": _safe_json_loads(p.get("params")),
                    "status": p.get("status", "active"),
                }

            turn = {
                "quarter_number": qn,
                "year": row["year"],
                "season": row["season"],
                "faction_decisions": _safe_json_loads(row.get("faction_decisions")),
                "narratives": _safe_json_loads(row.get("narratives")),
                "state_changes": _safe_json_loads(row.get("state_changes")),
                "token_usage": _safe_json_loads(row.get("token_usage")),
                "turn_deltas": deltas,
                "policies": policies,
            }

            # Merge faction stats (population, troops, food, etc.) from game_state
            try:
                from histrategy.db.models import get_latest_game_states
                gs_rows = get_latest_game_states(room_id, qn)
                faction_stats = {}
                for gs in gs_rows:
                    fid = gs["faction_id"]
                    faction_stats[fid] = {
                        "population": gs.get("population", 0),
                        "troops": gs.get("troops", 0),
                        "food": gs.get("food", 0),
                        "treasury": gs.get("treasury", 0),
                        "morale": gs.get("morale", 0),
                        "territories": len(_safe_json_loads(gs.get("territories", "[]")) or []),
                    }
                if faction_stats:
                    if not turn["state_changes"]:
                        turn["state_changes"] = {}
                    turn["state_changes"]["faction_stats"] = faction_stats
            except Exception:
                pass  # Non-critical; don't break turns response if game_state query fails
            turns.append(turn)

        # Return in ascending quarter_number order
        turns.sort(key=lambda t: t["quarter_number"])

        # Build faction_names from room
        room = _get_room(room_id)
        lang = getattr(room, "metadata", {}).get("lang", "zh") if getattr(room, "metadata", None) else "zh"
        fnames = _get_faction_names(room, lang=lang) if room else {}

        return {
            "room_id": room_id,
            "turns": turns,
            "count": len(turns),
            "faction_names": fnames,
        }

    @app.get("/api/rooms/{room_id}/state")
    def api_room_state(room_id: str):
        """Return game_state and policy_state for game restoration."""
        from fastapi.responses import JSONResponse

        from histrategy.db.models import get_active_policies, get_latest_game_states
        from histrategy.server.room_manager import _get_room

        room = _get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "房间不存在"})

        quarter_number = room.quarter_number

        raw_states = get_latest_game_states(room_id, quarter_number)

        factions = []
        for row in raw_states:
            fid = row["faction_id"]
            policies_list = get_active_policies(room_id, fid)
            policies = {}
            for p in policies_list:
                policies[p["policy_name"]] = {
                    "policy_type": p["policy_type"],
                    "policy_level": p.get("policy_level", 1),
                    "params": _safe_json_loads(p.get("params")),
                    "status": p.get("status", "active"),
                }

            factions.append(
                {
                    "faction_id": fid,
                    "population": row["population"],
                    "troops": row["troops"],
                    "food": row["food"],
                    "treasury": row["treasury"],
                    "morale": row["morale"],
                    "territories": _safe_json_loads(row.get("territories"), default=[]),
                    "policies": policies,
                    "is_active": bool(row.get("is_active", 1)),
                }
            )

        return {
            "room_id": room_id,
            "quarter_number": quarter_number,
            "factions": factions,
        }

    # Publish / Unpublish
    @app.patch("/api/rooms/{room_id}/publish")
    def api_publish_room(room_id: str, body: dict = Body(...)):  # noqa: B008
        """Toggle room public/private. { public: true | false }"""
        from fastapi.responses import JSONResponse

        from histrategy.db.connection import execute_write
        from histrategy.server.room_manager import _get_room

        room = _get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "Room not found"})

        is_public = bool(body.get("public", False))
        room.is_public = is_public
        execute_write(
            "UPDATE game_room SET is_public = ? WHERE id = ?",
            (1 if is_public else 0, room_id),
        )
        return {"ok": True, "room_id": room_id, "is_public": is_public}

    # ═══════════════════════════════════════════════════════════
    # Single-Player API (/api/single-player)
    #
    # Thin wrapper over the multiplayer room system.
    # Creates 1-human + N-AI rooms behind the scenes.
    # ═══════════════════════════════════════════════════════════

    @app.get("/api/single-player/{game_id}/status")
    def api_sp_status(game_id: str):
        """Single-player — get game status."""
        from histrategy.server.single_player import status

        return status(game_id)

    @app.post("/api/single-player/{game_id}/command")
    def api_sp_command(game_id: str, body: dict = Body(...)):  # noqa: B008
        """Single-player — submit command (blocks until LLM resolution completes)."""
        from histrategy.server.single_player import command

        return command(game_id, body.get("decision") or body.get("command", ""), lang=body.get("lang", "zh"))

    @app.post("/api/single-player/start")
    def api_sp_start(
        body: dict = Body(...),  # noqa: B008
        x_user_id: str = Header(default="", alias="X-User-Id"),
    ):
        """Single-player — start new game."""
        from histrategy.server.single_player import start

        return start(
            faction=body.get("faction", "shu"),
            scenario=body.get("scenario", "three-kingdoms"),
            language_style=body.get("language_style", "vernacular"),
            lang=body.get("lang", "zh"),
        )

    # ═══════════════════════════════════════════════════════════
    # Scenario Metadata API (/api/scenarios)
    # ═══════════════════════════════════════════════════════════

    @app.get("/api/scenarios")
    def api_list_scenarios():
        """List all available scenarios with faction metadata."""
        from histrategy.engine.faction_slot import (
            FACTION_DISPLAY_TO_ID,
            FACTION_ID_TO_DISPLAY,
            PLAYABLE_FACTIONS,
        )
        from histrategy.engine.scenario_loader import ScenarioLoader

        # Known metadata for scenarios without scenario.toml
        _BUILTIN_META = {
            "three-kingdoms": {
                "name": "三國志略",
                "name_cn": "三國志略",
                "period": "公元207年 东汉末年",
                "start_year": 207,
                "epoch": "",
            },
            "nanming": {
                "name": "山河鼎革",
                "name_cn": "山河鼎革",
                "period": "公元1644年 明末清初",
                "start_year": 1644,
                "epoch": "",
            },
        }

        scenarios = []
        for sid in ScenarioLoader.list_scenarios():
            loader = ScenarioLoader(sid)
            cfg = loader._toml
            meta = cfg.get("meta", {})
            builtin = _BUILTIN_META.get(sid, {})

            # Determine playable faction IDs per scenario
            toml_available = set(meta.get("available", cfg.get("factions", {}).get("available", [])))
            # Map display IDs to internal IDs for TK scenario
            toml_available = {FACTION_DISPLAY_TO_ID.get(f, f) for f in toml_available}
            if not toml_available:
                # Fallback for TK: use PLAYABLE_FACTIONS
                toml_available = {FACTION_DISPLAY_TO_ID.get(f, f) for f in PLAYABLE_FACTIONS}

            factions_raw = loader.load_factions()
            faction_list = []
            for fname, fdata in factions_raw.items():
                playable = fname in toml_available
                # Determine display ID for backward compat
                display_id = FACTION_ID_TO_DISPLAY.get(fname, fname)
                if isinstance(fdata, dict):
                    faction_list.append(
                        {
                            "id": fname,
                            "display_id": display_id,
                            "name": fdata.get("name", fname),
                            "name_cn": fdata.get("name_cn", fdata.get("name", fname)),
                            "color": fdata.get("color", ""),
                            "playable": playable,
                        }
                    )
                else:
                    name = getattr(fdata, "name", fname)
                    faction_list.append(
                        {
                            "id": fname,
                            "display_id": display_id,
                            "name": name,
                            "name_cn": name,
                            "color": "",
                            "playable": playable,
                        }
                    )
            scenarios.append(
                {
                    "id": sid,
                    "name": meta.get("name") or builtin.get("name", sid),
                    "name_cn": meta.get("name_cn")
                    or meta.get("name")
                    or builtin.get("name_cn", builtin.get("name", sid)),
                    "period": meta.get("era") or builtin.get("period", ""),
                    "start_year": meta.get("start_year") or builtin.get("start_year", 0),
                    "epoch": meta.get("epoch") or builtin.get("epoch", ""),
                    "factions": faction_list,
                }
            )
        return {"ok": True, "scenarios": scenarios}

    @app.get("/api/scenarios/{scenario_id}/timeline")
    def api_scenario_timeline(scenario_id: str, year: int = 0, season: str = ""):
        """Return historical events matching the given year+season.

        Used by the frontend to display "📜 历史对照" annotations
        after each turn — showing what actually happened in history
        at this point in time.
        """
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(scenario_id)
        events = loader.get_timeline_events(year, season)
        return {
            "ok": True,
            "scenario_id": loader.scenario_id,
            "year": year,
            "season": season,
            "events": events,
            "count": len(events),
            "has_timeline": len(events) > 0,
        }

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
