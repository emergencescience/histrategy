"""
Persistence client — wraps Orchestrator /games/histrategy/* endpoints.

All methods are synchronous (httpx). Called from FastAPI route handlers.
ORCHESTRATOR_URL default: https://api.emergence.science
"""
import os
from typing import Optional

import httpx

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "https://api.emergence.science").rstrip("/")
_TIMEOUT = 10.0  # seconds

def _headers(jwt_token: str) -> dict:
    return {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}

def create_session(jwt_token: str, scenario: str, faction: str,
                   preferences: dict | None = None) -> dict:
    """POST /games/histrategy/sessions → {session_id, ...}"""
    body = {"scenario": scenario, "faction": faction}
    if preferences:
        body["preferences"] = preferences
    r = httpx.post(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions",
        json=body,
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def list_sessions(jwt_token: str) -> list[dict]:
    """GET /games/histrategy/sessions → [{session_id, ...}, ...]"""
    r = httpx.get(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions",
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("sessions", [])

def save_game(jwt_token: str, session_id: str, slot: int,
              world_state: dict, turn: int, year: int, season: str) -> dict:
    """PUT /games/histrategy/sessions/{session_id}/save → {ok: true}"""
    r = httpx.put(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}/save",
        json={"slot": slot, "world_state": world_state,
              "turn": turn, "year": year, "season": season},
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def load_game(jwt_token: str, session_id: str) -> Optional[dict]:
    """GET /games/histrategy/sessions/{session_id} → session detail with latest save"""
    r = httpx.get(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}",
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


# ── Turn History ─────────────────────────────────────────────

def append_turn(
    jwt_token: str,
    session_id: str,
    turn_number: int,
    year: int,
    season: str,
    player_decision: str = "",
    court_dialogue: Optional[dict] = None,
    suggestions: Optional[list] = None,
    narrative: Optional[str] = None,
    aftermath: Optional[str] = None,
    bureaucracy: Optional[list] = None,
    npc_reactions: Optional[list] = None,
    state_changes: Optional[dict] = None,
    plan_tokens: Optional[int] = None,
    command_tokens: Optional[int] = None,
    npc_tokens: Optional[int] = None,
    sim_tokens: Optional[int] = None,
) -> dict:
    """POST /games/histrategy/sessions/{session_id}/turns → {ok, turn_id}"""
    r = httpx.post(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}/turns",
        json={
            "turn_number": turn_number,
            "year": year,
            "season": season,
            "player_decision": player_decision,
            "court_dialogue": court_dialogue,
            "suggestions": suggestions,
            "narrative": narrative,
            "aftermath": aftermath,
            "bureaucracy": bureaucracy,
            "npc_reactions": npc_reactions,
            "state_changes": state_changes,
            "plan_tokens": plan_tokens,
            "command_tokens": command_tokens,
            "npc_tokens": npc_tokens,
            "sim_tokens": sim_tokens,
        },
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def get_turns(jwt_token: str, session_id: str) -> dict:
    """GET /games/histrategy/sessions/{session_id}/turns → {turns: [...], count: N}"""
    r = httpx.get(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions/{session_id}/turns",
        headers=_headers(jwt_token),
        timeout=_TIMEOUT,
    )
    if r.status_code == 404:
        return {"turns": [], "count": 0}
    r.raise_for_status()
    return r.json()
