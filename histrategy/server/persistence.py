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


def create_session(jwt_token: str, scenario: str, faction: str) -> dict:
    """POST /games/histrategy/sessions → {session_id, ...}"""
    r = httpx.post(
        f"{ORCHESTRATOR_URL}/games/histrategy/sessions",
        json={"scenario": scenario, "faction": faction},
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
