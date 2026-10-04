"""第三轮（2026-10-04）回归：start 必须传 faction + parsed_commands 改名。

用户裁定：
- 「`/api/single-player/start` 不传 faction 这看起来是个 bug。必须要传 faction，
  否则 http request 返回失败。」
  此前 `faction` 的默认值是**硬编码的 "shu"**，于是
  `{"scenario": "rome-triumvirate"}` 会返回一个三国势力 id —— 罗马世界里没有
  shu，结果是 `is_active: false`、0 兵 0 城 0 钱的**空壳房间**，且 HTTP 200。
- 「改名成 parsed_commands」—— 该字段装的是**全体势力**该回合的解析后命令。
"""
import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "histrategy-engine" / "src"))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from histrategy.server.api import create_app

    return TestClient(create_app(llm_provider=None))


# ── 1. start 必须传 faction ───────────────────────────────────────────
def test_start_without_faction_is_rejected(client):
    """不传 faction → 422。**不再**兜底成 "shu"。"""
    r = client.post("/api/single-player/start", json={"scenario": "rome-triumvirate"})
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body["code"] == "FACTION_REQUIRED"


def test_start_with_cross_scenario_faction_is_rejected(client):
    """罗马房间里传三国的 shu → 422（这正是那个空壳房间 bug 的入口）。"""
    r = client.post(
        "/api/single-player/start",
        json={"scenario": "rome-triumvirate", "faction": "shu"},
    )
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body["code"] == "UNKNOWN_FACTION"
    assert "antony" in body["valid_factions"]


def test_start_with_valid_faction_reaches_start(client, monkeypatch):
    """合法 faction 才会真的进 start()。start 本身被替换掉，不碰 DB。"""
    called: dict = {}

    def fake_start(**kwargs):
        called.update(kwargs)
        return {"game_id": "fake", "faction": kwargs["faction"]}

    monkeypatch.setattr("histrategy.server.single_player.start", fake_start)

    r = client.post(
        "/api/single-player/start",
        json={"scenario": "rome-triumvirate", "faction": "antony"},
    )
    assert r.status_code == 200, r.text[:200]
    assert called["faction"] == "antony"
    assert called["scenario"] == "rome-triumvirate"


# ── 2. parsed_commands 改名 ──────────────────────────────────────────
def test_turn_result_field_is_parsed_commands():
    from histrategy_engine.world import TurnResult

    names = {f.name for f in fields(TurnResult)}
    assert "parsed_commands" in names
    assert "player_commands" not in names, (
        "字段应已改名为 parsed_commands；player_commands 只能作为只读别名存在，"
        "否则持久化的 baseline_result 里会出现两个含义不同的同名键"
    )


def test_player_commands_alias_still_works():
    """兼容别名：老代码/老测试仍能读写 .player_commands，指向同一份数据。"""
    from histrategy_engine.world import TurnResult

    tr = TurnResult()
    tr.player_commands = [{"type": "attack", "params": {"target_territory": "sicilia"}}]
    assert tr.parsed_commands == [{"type": "attack", "params": {"target_territory": "sicilia"}}]

    tr.parsed_commands = [{"type": "move"}]
    assert tr.player_commands == [{"type": "move"}]


def test_only_parsed_commands_is_persisted():
    """asdict() 只看 dataclass 字段 → 落库只有 parsed_commands 一个键。"""
    from histrategy_engine.world import TurnResult

    tr = TurnResult()
    tr.parsed_commands = [{"type": "attack"}]
    d = asdict(tr)
    assert "parsed_commands" in d
    assert "player_commands" not in d, "别名不该被序列化，否则 DB 里出现双份数据"
