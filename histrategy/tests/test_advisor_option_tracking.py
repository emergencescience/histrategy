"""回归保护：advisor-first 选项埋点（T3）。

PRD §D1：每轮记录玩家选了哪个选项（`top|bottom|custom|timeout`），落到
`quarter_turn`，为"是否收敛为纯三策"提供数据。

设计（不改 schema）：
- 前端提交时带 `option`；自由文本直接提交记 `direct`
- `submit_decision` 把选项写进 `room.metadata["decision_options"]`（随 room 持久化）
- `_save_quarter` 落库时写进该势力决策条目的 `_option` 键
- 判定规则见 `_resolve_decision_option`

**不依赖 PostHog**（founder 指示 PostHog 需账号、暂不启动），灰度期用 SQL 人工核对。
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.server.room_manager import _resolve_decision_option  # noqa: E402

API = REPO / "histrategy" / "server" / "api.py"
RM = REPO / "histrategy" / "server" / "room_manager.py"


def test_human_with_recorded_option():
    assert _resolve_decision_option("human", "top") == "top"
    assert _resolve_decision_option("human", "bottom") == "bottom"
    assert _resolve_decision_option("human", "custom") == "custom"


def test_human_without_option_counts_as_direct():
    """旧前端不传 option —— 必须仍能记下来，不能丢数据（否则样本会有系统性缺口）。"""
    assert _resolve_decision_option("human", None) == "direct"
    assert _resolve_decision_option("human", "") == "direct"
    assert _resolve_decision_option("human", "   ") == "direct"


def test_timeout_is_recorded():
    assert _resolve_decision_option("heuristic_timeout", None) == "timeout"
    # 超时时即便 metadata 里残留了旧选项，也应以 timeout 为准（他没选）
    assert _resolve_decision_option("heuristic_timeout", "top") == "timeout"


def test_npc_sources_are_not_recorded():
    for src in ("llm", "heuristic", "heuristic_fallback", ""):
        assert _resolve_decision_option(src, "top") is None, f"{src} 不应该被记成玩家选项"


def test_case_insensitive_source():
    assert _resolve_decision_option("HUMAN", "top") == "top"


def test_api_passes_option_through():
    src = API.read_text(encoding="utf-8")
    assert 'option=str(body.get("option", "") or "")' in src


def test_submit_decision_accepts_option_and_persists_it():
    src = RM.read_text(encoding="utf-8")
    assert "def submit_decision(" in src
    assert "    option: str = \"\"," in src, "submit_decision 必须接收 option"
    assert 'meta["decision_options"] = opts' in src, "选项必须写进 room.metadata"
    assert 'entry["_option"] = _opt' in src, "落库时必须写进 _option"


def test_quarter_turn_stores_option_inside_json_column():
    """不得新增数据库列 —— PRD 明确 option 存 JSON 字段内。"""
    schema = (REPO / "histrategy" / "db" / "schema.sql").read_text(encoding="utf-8")
    assert "_option" not in schema, "不应改 schema"


def test_single_player_command_path_threads_option():
    """前端实际走的是 `/single-player/{id}/command`，不是 `/rooms/{id}/decide`。

    两条提交路径都必须把 option 透传到底 —— 只接一条的话，线上（单人房）永远记不到数据，
    而测试却会因为另一条通了而变绿。这种"测了没用的路"最危险，所以两条都断言。
    """
    sp = (REPO / "histrategy" / "server" / "single_player.py").read_text(encoding="utf-8")
    assert 'option: str = "",' in sp, "single_player.command 必须接收 option"
    assert "skip_narrative=streaming, option=option" in sp, "主路径必须透传"
    assert "submit_decision(game_id, human_fid, decision, option=option)" in sp, "重试路径必须透传"

    api = API.read_text(encoding="utf-8")
    assert api.count('option=str(body.get("option", "") or "")') >= 2, (
        "两个提交端点（/decide 与 /single-player/command）都要接收 option"
    )
