"""终局回归测试：max_quarters 终局链（2026-08-28 修复）。

背景：nanming(山河鼎革) scenario.toml 配了 max_quarters=68（1644冬起 68 季 = 1661冬止），
但 quarterly_resolver Step 7.6 设置的 result.game_over 无人消费——不置 phase、不回传前端，
导致玩家能一路玩到 133 回合(1678年)。本测试锁定终局链的纯函数部分。
"""
from histrategy.engine.quarterly_resolver import _build_conclusion, _get_max_quarters


def test_get_max_quarters_nanming():
    """山河鼎革 68 季 = 17 年（1644冬 → 1661冬），历史终点 1661。"""
    assert _get_max_quarters("nanming") == 68


def test_get_max_quarters_three_kingdoms():
    assert _get_max_quarters("three-kingdoms") == 60


def test_build_conclusion_shape():
    class _R:
        scenario = "nanming"

    class _WS:
        year = 1661

    c = _build_conclusion(_R(), _WS())
    assert c["type"] == "conclusion"
    assert "1661" in c["message"]
    assert c["message"].startswith("#")
