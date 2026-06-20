"""
Persistence Adapter — unified save/load interface for histrategy.

Current implementation:
  - LocalFileAdapter: JSON files in ~/.histrategy/sessions/ (no DB needed)

Orchestrator handles DB persistence; histrategy uses only local files.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ═══════════════════════════════════════════════════════════════
# Abstract Interface
# ═══════════════════════════════════════════════════════════════


class PersistenceAdapter(ABC):
    """Unified persistence — local JSON and remote PostgreSQL share this interface."""

    @abstractmethod
    def create_session(self, faction_id: str, scenario_id: str) -> str:
        """Create a new game session. Returns session_id."""
        ...

    @abstractmethod
    def save_state(self, session_id: str, world_state: dict, turn: int, year: int, season: str) -> None:
        """Save world state snapshot."""
        ...

    @abstractmethod
    def load_state(self, session_id: str) -> dict | None:
        """Load world state snapshot. Returns None if not found."""
        ...

    @abstractmethod
    def append_turn(
        self,
        session_id: str,
        turn_number: int,
        year: int,
        season: str,
        player_decision: str = "",
        narrative: str | None = None,
        aftermath: str | None = None,
        state_changes: dict | None = None,
        tokens: dict | None = None,
    ) -> None:
        """Append a turn record to history."""
        ...

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        """List all sessions."""
        ...


# ═══════════════════════════════════════════════════════════════
# LocalFileAdapter — JSON files, zero dependencies
# ═══════════════════════════════════════════════════════════════


class LocalFileAdapter(PersistenceAdapter):
    """Local JSON file persistence.

    Storage layout:
      ~/.histrategy/sessions/{session_id}/
        ├── world_v2.json       # Full world state snapshot
        ├── turns.jsonl         # Turn history (append-only JSONL)
        └── meta.json           # Session metadata
    """

    def __init__(self, data_dir: str | None = None):
        if data_dir is None:
            data_dir = os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy"))
        self.data_dir = os.path.expanduser(data_dir)

    def _session_dir(self, session_id: str) -> str:
        return os.path.join(self.data_dir, "sessions", session_id)

    # ── create / list ──────────────────────────────────────

    def create_session(self, faction_id: str, scenario_id: str) -> str:
        sid = f"{faction_id}_{int(time.time())}"
        sdir = self._session_dir(sid)
        os.makedirs(sdir, exist_ok=True)
        meta = {
            "session_id": sid,
            "faction_id": faction_id,
            "scenario_id": scenario_id,
            "created_at": time.time(),
            "turn": 0,
        }
        with open(os.path.join(sdir, "meta.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return sid

    def list_sessions(self) -> list[dict]:
        sessions_dir = os.path.join(self.data_dir, "sessions")
        if not os.path.isdir(sessions_dir):
            return []
        results = []
        for sid in os.listdir(sessions_dir):
            meta_path = os.path.join(sessions_dir, sid, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                    meta["session_id"] = sid
                    results.append(meta)
                except (json.JSONDecodeError, KeyError):
                    continue
        results.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return results

    # ── state ──────────────────────────────────────────────

    def save_state(self, session_id: str, world_state: dict, turn: int, year: int, season: str) -> None:
        sdir = self._session_dir(session_id)
        os.makedirs(sdir, exist_ok=True)

        # Write world state
        state_path = os.path.join(sdir, "world_v2.json")
        with open(state_path, "w") as f:
            json.dump(world_state, f, ensure_ascii=False, indent=2)

        # Update meta
        meta_path = os.path.join(sdir, "meta.json")
        meta = {}
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
        meta["turn"] = turn
        meta["year"] = year
        meta["season"] = season
        meta["updated_at"] = time.time()
        with open(meta_path, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def load_state(self, session_id: str) -> dict | None:
        state_path = os.path.join(self._session_dir(session_id), "world_v2.json")
        if not os.path.isfile(state_path):
            return None
        with open(state_path) as f:
            return json.load(f)

    # ── turn history ───────────────────────────────────────

    def append_turn(
        self,
        session_id: str,
        turn_number: int,
        year: int,
        season: str,
        player_decision: str = "",
        narrative: str | None = None,
        aftermath: str | None = None,
        state_changes: dict | None = None,
        tokens: dict | None = None,
    ) -> None:
        sdir = self._session_dir(session_id)
        os.makedirs(sdir, exist_ok=True)

        record = {
            "turn": turn_number,
            "year": year,
            "season": season,
            "player_decision": player_decision,
            "narrative": narrative or "",
            "aftermath": aftermath or "",
            "state_changes": state_changes or {},
            "tokens": tokens or {},
            "timestamp": time.time(),
        }

        turns_path = os.path.join(sdir, "turns.jsonl")
        with open(turns_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════


def create_persistence_adapter(jwt_token: str = "") -> PersistenceAdapter:
    """Create the persistence adapter.

    Always uses LocalFileAdapter (JSON files, no dependencies).
    Orchestrator handles DB persistence; histrategy does not call back.
    """
    return LocalFileAdapter()
