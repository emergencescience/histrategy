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


async def _sse_error(message: str):
    """Yield an SSE error event."""
    import json

    yield f"data: {json.dumps({'error': message})}\n\n"
    yield "data: [DONE]\n\n"


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

        from histrategy.llm.adapter import detect_provider as _detect_provider

        _detected = _detect_provider()
        _llm_provider = _detected.get("name") or None

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
        user_agent: str = Header(default="", alias="User-Agent"),
    ):
        """Create a multiplayer room.

        pre_assigned = {"cao": "张三", "shu": "李四"}
        → Host pre-assigns factions; each player gets a join link.
        → Unassigned factions become AI NPCs.

        Orchestrator proxy injects X-User-Id header (real user UUID).
        """
        from histrategy.server.room_manager import create_room, detect_browser, detect_device_type

        # Prefer X-User-Id (injected by orchestrator proxy) over body user_id
        pre_assigned = body.get("pre_assigned")
        if not pre_assigned:
            return {
                "ok": False,
                "error": 'pre_assigned is required — e.g. {"cao": "张三", "shu": "李四"}',
            }

        metadata = dict(body.get("metadata") or {})
        metadata["device_type"] = detect_device_type(user_agent)
        metadata["browser"] = detect_browser(user_agent)

        result = create_room(
            scenario=body.get("scenario_id") or body.get("scenario", "three-kingdoms"),
            pre_assigned=pre_assigned,
            metadata=metadata,
            host_user_id=x_user_id,
        )
        return result

    @app.post("/api/rooms/{room_id}/decide")
    def api_submit_decision(room_id: str, body: dict = Body(...)):  # noqa: B008
        """Submit this quarter's decision."""
        from histrategy.server.room_manager import submit_decision

        decision = body.get("decision", "").strip()
        if not decision:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "decision is required (cannot be empty)"},
            )

        return submit_decision(
            room_id,
            body.get("faction_id", ""),
            decision,
        )

    @app.get("/api/rooms/{room_id}/narrative-stream")
    def api_narrative_stream(room_id: str, quarter: int = 0):
        """Stream global narrative for a room's latest quarter via SSE.

        After /decide returns, the frontend connects here to receive
        the global_narrative as Server-Sent Events for typewriter rendering.
        If quarter=0, the latest quarter's narrative is streamed.
        """
        from fastapi.responses import StreamingResponse

        from histrategy.db.models import get_quarter_turns

        # Fetch the latest turn's narrative (room existence is implied by turns)
        turns = get_quarter_turns(room_id, limit=1)
        if not turns:
            return StreamingResponse(
                _sse_error("No turns found"),
                media_type="text/event-stream",
            )

        latest = turns[0]
        narratives_raw = _safe_json_loads(latest.get("narratives"), {})
        global_narrative = (
            narratives_raw.get("global", "")
            if isinstance(narratives_raw, dict)
            else ""
        )

        # If narrative already exists in DB, stream it as a single chunk
        # (this covers the case where LLM already generated it)
        if global_narrative and global_narrative.strip():
            async def _serve_cached():
                # Split into paragraphs for visual pacing
                for paragraph in global_narrative.split("\n"):
                    if paragraph.strip():
                        yield f"data: {paragraph}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                _serve_cached(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # No narrative yet — stream a graceful fallback (not the misleading "叙事生成中")
        async def _serve_fallback():
            lang = "zh"  # Default; room_id-based lang detection would require extra DB call
            yield (
                "data: 本回合尚未推演完成，请刷新页面查看最新状态。若问题持续，请重新下达政令。\n\n"
                if lang == "zh"
                else "data: This turn has not been resolved yet. Please refresh the page. If the problem persists, please re-issue your command.\n\n"
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _serve_fallback(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/rooms/{room_id}/narrative-live-stream")
    def api_narrative_live_stream(room_id: str):
        """Stream the deferred narrative for a room's latest quarter (streaming mode).

        After /command settles state (skip_narrative), the client opens this to
        receive the chronicle as it's generated (true token streaming). The full
        text is persisted to the quarter_turn row on completion (see
        room_manager.stream_and_persist_narrative).

        SSE framing: each data frame is a JSON-encoded string chunk
        (data: "…\\n\\n…") so newlines within the narrative survive framing.
        The client does JSON.parse(payload) and concatenates.
        """
        import json as _json

        from fastapi.responses import StreamingResponse

        from histrategy.server.room_manager import _get_room, stream_and_persist_narrative

        room = _get_room(room_id)
        if not room:
            return StreamingResponse(_sse_error("Room not found"), media_type="text/event-stream")

        def _sse():
            try:
                for chunk in stream_and_persist_narrative(room):
                    if chunk:
                        yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/rooms/{room_id}/advisor")
    def api_advisor(room_id: str, faction_id: str = ""):
        """Return structured strategic advice as JSON.

        Manual trigger via 军师 button. Returns:
          {ok, analysis, suggestions: [{title, description, command}]}

        The 'command' field in each suggestion is a ready-to-execute
        decree that bypasses keyword parsing — the player can send it
        directly as their /decide input.
        """
        from histrategy.llm.adapter import LLMAdapter
        from histrategy.server.room_manager import _get_room

        try:
            room = _get_room(room_id)
        except Exception:
            return {"ok": False, "error": "Room not found"}

        if not room:
            return {"ok": False, "error": "Room not found"}

        fid = faction_id
        if not fid:
            human_slots = list(room.human_slots())
            fid = human_slots[0].faction_id if human_slots else ""

        if not fid:
            return {"ok": False, "error": "No faction found"}

        ws = room.world_state
        if not ws:
            return {"ok": False, "error": "Failed to load game state"}

        faction = ws.factions.get(fid)
        if not faction:
            return {"ok": False, "error": f"Faction {fid} not found"}

        # Build context (same as advisor-stream)
        turn_summaries = getattr(room, "turn_summaries", [])[-4:]
        chronicle = []
        for ts in turn_summaries:
            year = ts.get("year", "?")
            season = ts.get("season", "?")
            outcome = ts.get("outcome_summary", "")
            decision = ts.get("decision", "")
            chronicle.append(f"{year}年{season}: {decision[:60]} → {outcome}"[:180])

        perceived = {}
        for ofid, of in ws.factions.items():
            if ofid == fid or not getattr(of, "is_active", True):
                continue
            perceived[ofid] = {
                "name": of.name,
                "strength": getattr(of, "strength_actual", 0),
                "territories": len(list(getattr(of, "territories", []))),
                "is_border": False,
                "is_allied": getattr(of, "relations", {}).get(fid, 0) >= 50,
            }

        terr_names = []
        for tid in list(getattr(faction, "territories", [])):
            t = ws.territories.get(tid) if hasattr(ws, "territories") else None
            terr_names.append(getattr(t, "name", tid) if t else tid)

        local_state = {
            "turn": ws.turn_number,
            "year": ws.year,
            "season": getattr(ws.season, "cn", str(ws.season)),
            "faction_id": fid,
            "scenario": getattr(room, "scenario", ""),
            "my": {
                "strength": getattr(faction, "strength_actual", 0),
                "treasury": faction.treasury,
                "food": faction.food,
                "morale": getattr(faction, "morale_actual", 50),
                "territories": terr_names,
            },
            "perceived": perceived,
            "chronicle": chronicle,
        }
        personality = {
            "name": faction.name,
            "aggression": getattr(faction, "aggression", 0.5),
            "caution": getattr(faction, "caution", 0.5),
        }

        try:
            llm = LLMAdapter()
        except Exception:
            llm = None

        if not llm or not llm.is_available:
            from histrategy.llm.advisor import StrategicAdvisor
            lang_meta = getattr(room, "metadata", {}).get("lang", "zh")
            advisor = StrategicAdvisor(llm, language=lang_meta)
            result = advisor._offline_structured(local_state, personality)
            result["ok"] = True
            return result

        from histrategy.llm.advisor import StrategicAdvisor

        lang_meta = getattr(room, "metadata", {}).get("lang", "zh")
        advisor = StrategicAdvisor(llm, language=lang_meta)
        result = advisor.advise_player_structured(local_state, personality=personality)
        result["ok"] = True
        return result

    @app.get("/api/rooms/{room_id}/advisor-stream")
    def api_advisor_stream(room_id: str, faction_id: str = ""):
        """Stream AI advisor advice (军师进言) via SSE.

        Uses recent 3-4 turn_summaries + current faction state to generate
        strategic advice. Streams via SSE for typewriter rendering.
        Rate-limited: client should throttle (once per turn recommended).
        """
        from fastapi.responses import StreamingResponse

        from histrategy.llm.adapter import LLMAdapter
        from histrategy.server.room_manager import _get_room

        try:
            room = _get_room(room_id)
        except Exception:
            return StreamingResponse(
                _sse_error("Room not found"),
                media_type="text/event-stream",
            )

        if not room:
            return StreamingResponse(
                _sse_error("Room not found"),
                media_type="text/event-stream",
            )

        # Determine faction — default to first human slot
        fid = faction_id
        if not fid:
            human_slots = list(room.human_slots())
            fid = human_slots[0].faction_id if human_slots else ""

        if not fid:
            return StreamingResponse(
                _sse_error("No faction found"),
                media_type="text/event-stream",
            )

        # Get world state and faction info
        ws = room.world_state
        if not ws:
            return StreamingResponse(
                _sse_error("Failed to load game state"),
                media_type="text/event-stream",
            )

        faction = ws.factions.get(fid)
        if not faction:
            return StreamingResponse(
                _sse_error(f"Faction {fid} not found"),
                media_type="text/event-stream",
            )

        # Build context from recent turn summaries → chronicle (what _build_context reads)
        turn_summaries = getattr(room, "turn_summaries", [])[-4:]
        chronicle = []
        for ts in turn_summaries:
            year = ts.get("year", "?")
            season = ts.get("season", "?")
            outcome = ts.get("outcome_summary", "")
            decision = ts.get("decision", "")
            chronicle.append(f"{year}年{season}: {decision[:60]} → {outcome}"[:180])

        # Perceived rival factions (schema consumed by StrategicAdvisor._build_context)
        perceived = {}
        for ofid, of in ws.factions.items():
            if ofid == fid or not getattr(of, "is_active", True):
                continue
            perceived[ofid] = {
                "name": of.name,
                "strength": getattr(of, "strength_actual", 0),
                "territories": len(list(getattr(of, "territories", []))),
                "is_border": False,
                "is_allied": getattr(of, "relations", {}).get(fid, 0) >= 50,
            }

        # Map territory ids → names
        terr_names = []
        for tid in list(getattr(faction, "territories", [])):
            t = ws.territories.get(tid) if hasattr(ws, "territories") else None
            terr_names.append(getattr(t, "name", tid) if t else tid)

        local_state = {
            "turn": ws.turn_number,
            "year": ws.year,
            "season": getattr(ws.season, "cn", str(ws.season)),
            "faction_id": fid,
            "scenario": getattr(room, "scenario", ""),
            "my": {
                "strength": getattr(faction, "strength_actual", 0),
                "treasury": faction.treasury,
                "food": faction.food,
                "morale": getattr(faction, "morale_actual", 50),
                "territories": terr_names,
            },
            "perceived": perceived,
            "chronicle": chronicle,
        }
        personality = {
            "name": faction.name,
            "aggression": getattr(faction, "aggression", 0.5),
            "caution": getattr(faction, "caution", 0.5),
        }

        # Get LLM adapter
        try:
            llm = LLMAdapter()
        except Exception:
            llm = None

        if not llm or not llm.is_available:
            return StreamingResponse(
                _sse_error("LLM not available"),
                media_type="text/event-stream",
            )

        from histrategy.llm.advisor import StrategicAdvisor

        # Read language from room metadata for bilingual advisor support
        lang_meta = getattr(room, "metadata", {}).get("lang", "zh")

        advisor = StrategicAdvisor(llm, language=lang_meta)

        # Sync generator (runs in FastAPI's threadpool — does NOT block the event
        # loop like an async def wrapping a blocking LLM stream would). This mirrors
        # the narrative-live-stream endpoint and prevents bursty/truncated flushing
        # through the orchestrator SSE proxy.
        def _stream_advice():
            import json as _json_adv

            # Structured 三策/Three Strategies format so the frontend can parse
            # the stream into clickable option cards (click → fill the input box).
            is_en = lang_meta.startswith("en")
            if is_en:
                query = (
                    f"Advise me as the war councilor of {faction.name}: first, analyze "
                    f"the current strategic situation in 2-3 sentences of vivid prose, "
                    f"then provide three actionable strategies considering relative "
                    f"strength and recent developments.\n"
                    f"Output STRICTLY in this format (one blank line between strategies), "
                    f"where 'Decree:' is a single executable command the player can "
                    f"copy-paste and send directly:\n\n"
                    f"【Upper Strategy】〈title ≤8 words〉\nDecree: 〈one executable command〉\n\n"
                    f"【Middle Strategy】〈title ≤8 words〉\nDecree: 〈one executable command〉\n\n"
                    f"【Lower Strategy】〈title ≤8 words〉\nDecree: 〈one executable command〉"
                )
            else:
                query = (
                    f"请以我（{faction.name}）的军师身份进言：先用2-3句文言简析当前形势，"
                    f"再给出三条可执行的策略，务必兼顾敌我实力对比与近期战况。\n"
                    f"严格按以下格式输出（每条策略之间空一行），"
                    f"其中「策令：」后必须是一句玩家可直接照抄发送的具体政令：\n\n"
                    f"【上策】〈不超过8字的标题〉\n策令：〈一句可直接执行的政令〉\n\n"
                    f"【中策】〈不超过8字的标题〉\n策令：〈一句可直接执行的政令〉\n\n"
                    f"【下策】〈不超过8字的标题〉\n策令：〈一句可直接执行的政令〉"
                )
            # JSON-encode each chunk so newlines in the structured format survive
            # SSE framing (the frontend does JSON.parse then concatenates). Same
            # robust framing as narrative-live-stream.
            try:
                for chunk in advisor.advise_player_stream(local_state, personality=personality, query=query):
                    if chunk:
                        yield f"data: {_json_adv.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                fallback = advisor._offline_advice(local_state, query)
                yield f"data: {_json_adv.dumps(fallback, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream_advice(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
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

        # Pre-fetch npc_only faction IDs for filtering
        npc_only_ids: set[str] = set()
        try:
            from histrategy.server.room_manager import _get_npc_only_ids
            npc_only_ids = _get_npc_only_ids(room_id)
        except Exception:
            pass  # Non-critical; if lookup fails, show all factions

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

            # Filter NPC-only factions from decisions & narratives
            raw_fd = _safe_json_loads(row.get("faction_decisions")) or {}
            raw_narr = _safe_json_loads(row.get("narratives")) or {}
            fd_filtered = (
                {fid: v for fid, v in raw_fd.items() if fid not in npc_only_ids}
                if npc_only_ids else raw_fd
            )
            narr_filtered = (
                {fid: v for fid, v in raw_narr.items() if fid not in npc_only_ids}
                if npc_only_ids else raw_narr
            )

            turn = {
                "quarter_number": qn,
                "year": row["year"],
                "season": row["season"],
                "faction_decisions": fd_filtered,
                "narratives": narr_filtered,
                "state_changes": _safe_json_loads(row.get("state_changes")),
                "token_usage": _safe_json_loads(row.get("token_usage")),
                "turn_deltas": deltas,
                "policies": policies,
            }

            # Merge faction stats — only if not already present from turn save
            # (V3 _extract_state_changes now embeds faction_stats directly)
            try:
                from histrategy.db.models import get_latest_game_states
                from histrategy.server.room_manager import _get_npc_only_ids

                existing_sc = turn.get("state_changes") or {}
                if not existing_sc.get("faction_stats"):
                    gs_rows = get_latest_game_states(room_id, qn)
                    faction_stats = {}
                    for gs in gs_rows:
                        fid = gs["faction_id"]
                        if fid in npc_only_ids:
                            continue  # Skip npc_only factions (e.g. sextus_pompey)
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

        # Deduplicate by quarter_number (keep first occurrence) then sort
        seen_quarters = set()
        deduped = []
        for t in turns:
            qn = t["quarter_number"]
            if qn not in seen_quarters:
                seen_quarters.add(qn)
                deduped.append(t)
        turns = deduped
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
            "npc_only_factions": sorted(npc_only_ids) if npc_only_ids else [],
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
        """Toggle room public/private. { public: true | false }

        Reads back from DB after write to ensure persistence.
        Also updates the in-memory room so subsequent save_room()
        calls (NPC pre-gen, etc.) don't overwrite is_public.
        """
        from fastapi.responses import JSONResponse

        from histrategy.db.connection import execute_one, execute_write
        from histrategy.server.room_manager import _get_room

        room = _get_room(room_id)
        if not room:
            return JSONResponse(status_code=404, content={"error": "Room not found"})

        is_public = bool(body.get("public", False))

        # 1. Update in-memory room (survives until next _get_room() reload)
        room.is_public = is_public

        # 2. Write to DB
        rows = execute_write(
            "UPDATE game_room SET is_public = ? WHERE id = ?",
            (1 if is_public else 0, room_id),
        )

        # 3. Read back from DB to verify (catches race conditions)
        verify = execute_one(
            "SELECT is_public FROM game_room WHERE id = ?", (room_id,)
        )
        if verify is None:
            return JSONResponse(
                status_code=500,
                content={"error": "Room vanished during publish"},
            )
        db_is_public = bool(verify.get("is_public", 0))

        if db_is_public != is_public:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Publish write didn't persist",
                    "expected": is_public,
                    "actual": db_is_public,
                },
            )

        return {
            "ok": True,
            "room_id": room_id,
            "is_public": is_public,
            "verified": True,
            "rows_affected": rows,
        }

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

    @app.get("/api/single-player/{game_id}/command-progress")
    def api_command_progress(game_id: str):
        """DEPRECATED: No longer polled by frontend since SSE narrative-live-stream was introduced.
        Returns empty progress — kept for backward compatibility with old clients."""
        return {"phase": "deprecated", "elapsed": 0, "detail": ""}

    @app.post("/api/single-player/{game_id}/command")
    def api_sp_command(game_id: str, body: dict = Body(...)):  # noqa: B008
        """Single-player — submit command (blocks until LLM resolution completes).

        Accepts optional suggestion_id for precompute intent cache lookup.
        """
        from histrategy.server.single_player import command

        return command(
            game_id,
            body.get("decision") or body.get("command", ""),
            lang=body.get("lang", "zh"),
            suggestion_id=body.get("suggestion_id"),
        )

    @app.post("/api/intent/precompute")
    def api_intent_precompute(body: dict = Body(...)):  # noqa: B008
        """Pre-compute intent_parse for a strategic suggestion.

        Fire-and-forget: returns immediately, caches result in background.
        When the user later clicks the suggestion and includes suggestion_id
        in the /command request, the cached parse is used for instant execution.

        Feature flag: HISTRATEGY_PRECOMPUTE_INTENT=true (disabled by default).
        When disabled, returns 200 but does nothing.
        """
        from histrategy.server.intent_cache import (
            _feature_enabled,
            precompute_and_cache,
        )
        from histrategy.server.room_manager import _get_room

        suggestion_id = body.get("suggestion_id", "").strip()
        command_text = body.get("command_text", "").strip()
        game_id = body.get("game_id", "").strip()
        faction_id = body.get("faction_id", "").strip()

        if not suggestion_id or not command_text:
            return {"ok": False, "error": "suggestion_id and command_text are required"}

        # Resolve faction_id and quarter_number from room
        room = _get_room(game_id) if game_id else None
        if room:
            if not faction_id:
                human_slots = list(room.human_slots())
                faction_id = human_slots[0].faction_id if human_slots else ""
            quarter = room.quarter_number
            room_id = room.id
        else:
            quarter = 0
            room_id = game_id or "unknown"

        if not _feature_enabled():
            return {
                "ok": True,
                "cached": False,
                "reason": "feature_disabled",
                "suggestion_id": suggestion_id,
            }

        # Spawn background precompute
        llm = None
        try:
            from histrategy.llm.adapter import LLMAdapter
            llm = LLMAdapter()
            if not llm.is_available:
                llm = None
        except Exception:
            llm = None

        precompute_and_cache(
            suggestion_id=suggestion_id,
            command_text=command_text,
            faction_id=faction_id,
            room_id=room_id,
            quarter_number=quarter,
            llm_adapter=llm,
        )

        return {
            "ok": True,
            "cached": False,
            "reason": "precomputing",
            "suggestion_id": suggestion_id,
        }

    @app.get("/api/debug/cmd-hash")
    def api_debug_cmd_hash():
        """Return a hash of the command() source to verify deployed version."""
        import hashlib
        import inspect

        from histrategy.server.single_player import command
        src = inspect.getsource(command)
        return {"sha256": hashlib.sha256(src.encode()).hexdigest()[:12], "lines": len(src.splitlines())}

    @app.post("/api/single-player/start")
    def api_sp_start(
        body: dict = Body(...),  # noqa: B008
        x_user_id: str = Header(default="", alias="X-User-Id"),
        user_agent: str = Header(default="", alias="User-Agent"),
    ):
        """Single-player — start new game."""
        from histrategy.server.room_manager import detect_device_type
        from histrategy.server.single_player import start

        return start(
            faction=body.get("faction", "shu"),
            scenario=body.get("scenario", "three-kingdoms"),
            language_style=body.get("language_style", "vernacular"),
            lang=body.get("lang", "zh"),
            device_type=detect_device_type(user_agent),
        )

    # ═══════════════════════════════════════════════════════════
    # Scenario Metadata API (/api/scenarios)
    # ═══════════════════════════════════════════════════════════

    @app.get("/api/scenarios/{scenario_id}/characters")
    def api_scenario_characters(scenario_id: str):
        """Return character knowledge data for a scenario (hover popup bios)."""
        import json
        import os

        # Try scenario-specific characters first, fall back to default
        scenario_path = os.path.join("scenarios", scenario_id, "knowledge", "characters.json")
        default_path = os.path.join("histrategy", "knowledge", "data", "characters.json")

        for path in [scenario_path, default_path]:
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                # Return minimal fields for hover popups
                chars = []
                for c in data:
                    chars.append({
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "name_en": c.get("name_en", c.get("name", "")),
                        "faction": c.get("faction", ""),
                        "birth": c.get("birth"),
                        "death": c.get("death"),
                        "description": c.get("description", ""),
                        "description_en": c.get("description_en", ""),
                    })
                return {"scenario_id": scenario_id, "characters": chars, "count": len(chars)}

        return {"scenario_id": scenario_id, "characters": [], "count": 0}

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
    def api_scenario_timeline(scenario_id: str, year: int = 0, season: str = "", lang: str = "zh"):
        """Return historical events matching the given year+season.

        Used by the frontend to display "📜 历史对照" annotations
        after each turn — showing what actually happened in history
        at this point in time. Supports lang param for i18n.
        """
        from histrategy.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader(scenario_id)
        events = loader.get_timeline_events(year, season)
        # When lang=en, return English title/description fields
        if lang.startswith("en"):
            events = [
                {
                    **e,
                    "title": e.get("title_en", e.get("title", "")),
                    "description": e.get("description_en", e.get("description", "")),
                }
                for e in events
            ]
        return {
            "ok": True,
            "scenario_id": loader.scenario_id,
            "year": year,
            "season": season,
            "events": events,
            "count": len(events),
            "has_timeline": len(events) > 0,
        }

    @app.post("/api/events")
    async def api_track_event(body: dict = Body(...)):
        """Track a client-side analytics event.

        Accepts JSON: {event_type, room_id?, user_id?, event_data?, session_id?}
        Writes to analytics_event table.
        """
        import uuid as _uuid
        from datetime import datetime, timezone

        event_id = str(_uuid.uuid4())
        event_type = body.get("event_type", "unknown")
        room_id = body.get("room_id", "")
        user_id = body.get("user_id", "")
        event_data = body.get("event_data", {})
        session_id = body.get("session_id", "")
        now = datetime.now(timezone.utc).isoformat()

        try:
            from histrategy.db.models import execute_write, json_dumps

            execute_write(
                """INSERT INTO analytics_event
                    (id, room_id, user_id, event_type, event_data, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    room_id,
                    user_id,
                    event_type,
                    json_dumps(event_data) if isinstance(event_data, dict) else str(event_data),
                    session_id,
                    now,
                ),
            )
        except Exception as db_err:
            import logging
            logging.getLogger("histrategy").warning("analytics_event insert failed: %s", db_err)

        return {"ok": True, "event_id": event_id}

    @app.get("/api/events/stats")
    def api_event_stats(room_id: str = "", hours: int = 24):
        """Get analytics event counts grouped by event_type."""
        from histrategy.db.models import execute

        try:
            if room_id:
                rows = execute(
                    """SELECT event_type, COUNT(*) as cnt
                    FROM analytics_event
                    WHERE room_id = ? AND created_at::timestamptz >= NOW() - (? || ' hours')::interval
                    GROUP BY event_type ORDER BY cnt DESC""",
                    (room_id, str(hours)),
                )
            else:
                rows = execute(
                    """SELECT event_type, COUNT(*) as cnt
                    FROM analytics_event
                    WHERE created_at::timestamptz >= NOW() - (? || ' hours')::interval
                    GROUP BY event_type ORDER BY cnt DESC""",
                    (str(hours),),
                )
            return {"ok": True, "events": rows, "hours": hours, "room_id": room_id or None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return app


# ─── Server Runner ───────────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 8080, api_key: str | None = None):
    """Run the REST API server."""
    import os

    import uvicorn

    # Set API key from parameter or environment (provider-agnostic)
    if api_key:
        os.environ["LLM_API_KEY"] = api_key

    # Auto-detect provider — delegate to adapter, don't hardcode
    from histrategy.llm.adapter import detect_provider as _detect_provider

    _detected = _detect_provider()
    provider = _detected.get("name") or None

    app = create_app(llm_provider=provider)

    if provider:
        model = _detected.get("model", "unknown")
        print(f"🤖 LLM: {provider} ({model}) — 智能叙事引擎已启用")
    else:
        print("📴 LLM: 未检测到 API Key — 使用离线模式（关键字规则引擎）")
        print("   💡 设置: export DOUBAO_API_KEY='ark-...' 或 DEEPSEEK_API_KEY='sk-...'")

    uvicorn.run(app, host=host, port=port, log_level="info")
