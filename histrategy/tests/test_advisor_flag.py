"""回归保护：advisor-first 灰度开关（T5）。

设计（设计文档 §2/§6）：
- 默认只对白名单剧本开启（`ADVISOR_FIRST_SCENARIOS`）
- `HISTRATEGY_ADVISOR_FIRST=0` 全局关闭（**不用重新部署前端**就能回滚）
- `HISTRATEGY_ADVISOR_FIRST=1` 全局开启（本地联调/全量）
- 关闭时**不向模型索要第 4 块** —— 回滚开关同时是一根省 token 的杠杆
"""
import ast
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import histrategy.server.api as api  # noqa: E402
from histrategy.server.api import _advisor_first_enabled  # noqa: E402

API = REPO / "histrategy" / "server" / "api.py"


@pytest.fixture(autouse=True)
def _clean_env():
    old = os.environ.pop("HISTRATEGY_ADVISOR_FIRST", None)
    yield
    os.environ.pop("HISTRATEGY_ADVISOR_FIRST", None)
    if old is not None:
        os.environ["HISTRATEGY_ADVISOR_FIRST"] = old


def test_default_is_whitelist_only():
    assert _advisor_first_enabled("rome-triumvirate") is True
    assert _advisor_first_enabled("three-kingdoms") is False
    assert _advisor_first_enabled("nanming") is False


def test_env_can_disable_globally():
    for raw in ("0", "false", "off", "no", "FALSE", " off "):
        os.environ["HISTRATEGY_ADVISOR_FIRST"] = raw
        assert _advisor_first_enabled("rome-triumvirate") is False, raw


def test_env_can_enable_globally():
    for raw in ("1", "true", "on", "yes"):
        os.environ["HISTRATEGY_ADVISOR_FIRST"] = raw
        assert _advisor_first_enabled("three-kingdoms") is True, raw


def test_whitelist_is_a_single_obvious_knob():
    """改成 three-kingdoms 起步（或换剧本）应当只动这一处。"""
    assert isinstance(api.ADVISOR_FIRST_SCENARIOS, set)
    assert api.ADVISOR_FIRST_SCENARIOS == {"rome-triumvirate"}


def test_custom_block_flag_is_evaluated_outside_the_language_branches():
    """`custom_block` 必须在 if is_en / else **之外**求值。

    这个 bug 真发生过：我把它插进了 `if is_en:` 里，于是中文分支引用未定义变量 →
    英文房间正常、中文房间 500。语法检查抓不到（是运行时 NameError），
    所以这里用 AST 断言它的缩进与 `query =` 同级、且行号在其之前。
    """
    tree = ast.parse(API.read_text(encoding="utf-8"))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_stream_advice":
            target = node
    assert target is not None, "未找到 _stream_advice"

    custom = query = None
    for node in target.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "custom_block" in names:
                custom = node
            if "query" in names and node.lineno > 1 and isinstance(node.value, ast.BinOp):
                query = node
    assert custom is not None, "custom_block 未赋值"
    assert query is not None, "query 未赋值"
    assert custom.col_offset == query.col_offset, (
        f"custom_block 缩进({custom.col_offset}) 与 query({query.col_offset}) 不同级 —— "
        "可能又被写进了 if 分支里"
    )
    assert custom.lineno < query.lineno


def test_flag_is_used_to_gate_the_fourth_block():
    src = API.read_text(encoding="utf-8")
    assert "_advisor_first_enabled(room.scenario)" in src
    assert "if custom_block else" in src, "第 4 块必须受开关控制"


def test_fourth_block_only_when_the_player_actually_wrote_something():
    """输入框为空时不得索要第 4 块 —— 没有"原话"可解析，让模型凭空编一个
    "你的决策"只会削弱这一块的可信度（而且更费 token）。"""
    from pathlib import Path as _P

    api = _P(__file__).resolve().parents[1] / "server" / "api.py"
    src = api.read_text(encoding="utf-8")
    assert "and bool(goal and goal.strip())" in src
