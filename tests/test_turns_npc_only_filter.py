"""Regression: /api/rooms/{id}/turns must hide npc_only factions everywhere.

Bug (2026-10-04, room b1600eecb77f4ec99212c32cc9da4add): the shared page's
「势力资源」table showed a raw `sextus_pompey` row for the Rome scenario.

Root cause: `_extract_state_changes()` (V3) embeds `faction_stats` INSIDE
`state_changes`, which made the npc_only-filtered `game_state` fallback branch
in `api_room_turns()` dead code. `state_changes` itself was passed through
unfiltered, so npc_only factions leaked into every consumer of the shared page.
`power_ranking` was never affected because it filters npc_only explicitly.

This test asserts the contract: for a room whose scenario marks a faction as
npc_only, that faction must not appear ANYWHERE in the /turns payload.
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HISTRATEGY_ENGINE", "v3")
    for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
              "LLM_API_KEY", "TONGYI_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    from histrategy.server.api import create_app

    return TestClient(create_app(llm_provider=None))


# One quarter whose state_changes carries BOTH shapes that used to leak:
#   - top-level per-faction entries (feeds the "Power Shifts" panel)
#   - faction_stats (feeds the 「势力资源」 table)
_TURN_ROW = {
    "quarter_number": 1,
    "year": -44,
    "season": "spring",
    "faction_decisions": json.dumps({
        "octavian": {"decision": "veteran outreach", "source": "human"},
        "sextus_pompey": {"decision": "raid shipping", "source": "llm"},
    }),
    "narratives": json.dumps({"global": "chronicle", "sextus_pompey": "raided"}),
    "state_changes": json.dumps({
        "octavian": {"strength": 1000, "population": 100, "territories": []},
        "sextus_pompey": {"strength": 5000, "population": 50000, "territories": []},
        "faction_stats": {
            "octavian": {"population": 100, "troops": 1000, "territories": 0},
            "sextus_pompey": {"population": 50000, "troops": 5000, "territories": 0},
        },
    }),
    "token_usage": "{}",
}


def _wire(monkeypatch, npc_only):
    import histrategy.db.models as db
    import histrategy.server.room_manager as rm

    def _deltas(room_id, qn):
        return [
            {"faction_id": "octavian", "delta_type": "morale", "old_value": 90,
             "new_value": 95, "delta": 5, "reason": "r", "source": "s"},
            # The phantom 0 -> 50000 population event that used to leak.
            {"faction_id": "sextus_pompey", "delta_type": "population", "old_value": 0,
             "new_value": 50000, "delta": 50000, "reason": "r", "source": "s"},
        ]

    monkeypatch.setattr(db, "get_quarter_turns", lambda *a, **k: [dict(_TURN_ROW)])
    monkeypatch.setattr(db, "get_turn_deltas", _deltas)
    monkeypatch.setattr(db, "get_policies_by_quarter", lambda *a, **k: [])
    monkeypatch.setattr(db, "get_latest_game_states", lambda *a, **k: [])
    monkeypatch.setattr(rm, "_get_npc_only_ids", lambda room_id: set(npc_only))
    monkeypatch.setattr(rm, "_get_room", lambda room_id: None)
    monkeypatch.setattr(rm, "_get_faction_names", lambda room, lang="zh": {})


def test_npc_only_faction_hidden_everywhere_in_turns(client, monkeypatch):
    _wire(monkeypatch, {"sextus_pompey"})

    r = client.get("/api/rooms/room-x/turns")
    assert r.status_code == 200, r.text
    data = r.json()

    turn = data["turns"][0]
    # The contract: npc_only must not appear as a faction entry in ANY of the
    # content sections the shared page renders.
    assert "sextus_pompey" not in turn["faction_decisions"]
    assert "sextus_pompey" not in turn["narratives"]
    assert "sextus_pompey" not in turn["state_changes"]
    assert "sextus_pompey" not in turn["state_changes"]["faction_stats"]
    assert "sextus_pompey" not in turn["turn_deltas"]
    # …while the top-level declaration still tells the frontend who is npc_only.
    assert data["npc_only_factions"] == ["sextus_pompey"]

    # Major factions must survive the filter intact.
    assert "octavian" in turn["state_changes"]
    assert "octavian" in turn["state_changes"]["faction_stats"]
    assert "octavian" in turn["faction_decisions"]
    assert "octavian" in turn["turn_deltas"]
    # Non-faction keys must not be clobbered by the filter.
    assert "faction_stats" in turn["state_changes"]


def test_no_npc_only_still_returns_all_factions(client, monkeypatch):
    """Guard: when a scenario has no npc_only factions nothing is filtered."""
    _wire(monkeypatch, set())

    r = client.get("/api/rooms/room-x/turns")
    assert r.status_code == 200, r.text
    turn = r.json()["turns"][0]
    assert "sextus_pompey" in turn["state_changes"]["faction_stats"]
    assert r.json()["npc_only_factions"] == []
