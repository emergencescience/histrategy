"""Phase A: streaming vs completion turn-resolution modes.

Verifies the dual-mode contract added for the streaming turn-resolution design
(emergence-meta/internal/design/2026-06-18-histrategy-streaming-turn-resolution.md):

- Completion mode (default): command() returns the narrative inline.
- Streaming mode (HISTRATEGY_STREAMING=1): command() settles state and defers
  the narrative (narrative_pending=True, empty narrative); narrative-live-stream
  generates + streams + persists the chronicle afterward.

Runs offline (no LLM key) — exercises the plumbing, not narrative quality.
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HISTRATEGY_ENGINE", "v3")
    monkeypatch.setenv("HISTRATEGY_SYMMETRIC", "1")
    monkeypatch.setenv("HISTRATEGY_MACRO", "1")
    for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY", "TONGYI_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    import histrategy.server.room_manager as rm
    from histrategy.server.api import create_app

    # Disable the 30s inter-turn rate limit for test speed.
    monkeypatch.setattr(rm, "_check_rate_limit", lambda *a, **k: True)

    return TestClient(create_app(llm_provider=None))


def _play_to_v3(client, monkeypatch):
    """Start a nanming game and play 4 turns through the normal resolution path."""
    monkeypatch.setenv("HISTRATEGY_STREAMING", "1")
    r = client.post("/api/single-player/start",
                    json={"faction": "nanming", "scenario": "nanming", "lang": "zh"})
    assert r.status_code == 200, r.text
    gid = r.json()["game_id"]
    for t in range(1, 5):
        d = client.post(f"/api/single-player/{gid}/command",
                        json={"decision": "固守江淮，安抚百姓", "lang": "zh"})
        assert d.status_code == 200, d.text
    return gid


def test_streaming_mode_defers_and_streams_narrative(client, monkeypatch):
    monkeypatch.setenv("HISTRATEGY_STREAMING", "1")
    gid = _play_to_v3(client, monkeypatch)

    # Turn 5 (V3) — streaming: state settles, narrative deferred.
    d = client.post(f"/api/single-player/{gid}/command",
                    json={"decision": "固守江淮，联络郑氏水师", "lang": "zh"})
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["_debug"]["streaming"] is True
    assert body["narrative_pending"] is True
    assert body["narrative"] == ""            # deferred
    assert body["faction_status"]             # state already settled

    # narrative-live-stream yields at least one content chunk + [DONE].
    with client.stream("GET", f"/api/rooms/{gid}/narrative-live-stream") as s:
        assert s.status_code == 200
        frames = [ln[6:] for ln in s.iter_lines() if ln and ln.startswith("data: ")]
    assert "[DONE]" in frames
    content = [f for f in frames if f != "[DONE]"]
    assert content, "stream must yield a content chunk"
    # JSON-encoded string frames concatenate into the narrative.
    text = "".join(json.loads(f) for f in content)
    assert text.strip()

    # Narrative persisted to the quarter_turn row.
    turns = client.get(f"/api/rooms/{gid}/turns").json()["turns"]
    glob = (turns[-1].get("narratives") or {}).get("global", "")
    assert glob and glob.strip()


def test_completion_mode_returns_narrative_inline(client, monkeypatch):
    monkeypatch.setenv("HISTRATEGY_STREAMING", "1")
    gid = _play_to_v3(client, monkeypatch)

    # Turn 5 in COMPLETION mode: narrative returned inline, no pending flag.
    monkeypatch.setenv("HISTRATEGY_STREAMING", "")
    d = client.post(f"/api/single-player/{gid}/command",
                    json={"decision": "休养生息，安抚百姓", "lang": "zh"})
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["_debug"]["streaming"] is False
    assert not body.get("narrative_pending")
    assert body["narrative"].strip()
    # Regression: the fallback must not leak the _npc_actions JSON as narrative.
    assert "_npc_actions" not in body["narrative"]
