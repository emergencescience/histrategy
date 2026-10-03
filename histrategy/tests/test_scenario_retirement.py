"""回归保护：剧本软下线闸门（H40）+ 自建可开。

背景：`create_room` 里对 nanming/ming-qing/shanhe-dingge 无条件返回
409 `SCENARIO_RETIRED`，但**面对玩家的提示语写着"请从 GitHub 自建部署后本地游玩"** ——
而自建部署跑的就是这段代码。也就是说自建服务端同样开不了房，提示与实现自相矛盾。
本文件把两个方向都钉住：默认下线不动，自建开关能开。
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.server.room_manager import (  # noqa: E402
    ALLOW_RETIRED_ENV, _retired_scenarios, create_room,
)

RETIRED = {"nanming", "ming-qing", "shanhe-dingge"}


@pytest.fixture(autouse=True)
def _clean_env():
    old = os.environ.pop(ALLOW_RETIRED_ENV, None)
    yield
    os.environ.pop(ALLOW_RETIRED_ENV, None)
    if old is not None:
        os.environ[ALLOW_RETIRED_ENV] = old


def test_default_retires_the_three_aliases():
    assert _retired_scenarios() == RETIRED


def test_env_opens_them_for_self_hosting():
    for raw in ("1", "true", "on", "yes", "TRUE", " 1 "):
        os.environ[ALLOW_RETIRED_ENV] = raw
        assert _retired_scenarios() == set(), raw


def test_create_room_still_refuses_by_default_with_self_host_hint():
    """默认行为不变：409 + 自建引导。"""
    res = create_room(scenario="nanming")
    assert res["ok"] is False
    assert res["code"] == "SCENARIO_RETIRED"
    assert res["self_host_url"].startswith("https://github.com/")


def test_the_hint_must_be_true_that_is_why_the_switch_exists():
    """提示语让玩家去自建 —— 那么自建必须真的能开。

    这条断言是把"文案"和"实现"绑在一起：如果哪天有人删掉自建开关，
    提示语就变成一句假话，而这个测试会立刻提醒他二选一
    （要么恢复开关，要么改掉提示语）。
    """
    assert ALLOW_RETIRED_ENV == "HISTRATEGY_ALLOW_RETIRED_SCENARIOS"
    os.environ[ALLOW_RETIRED_ENV] = "1"
    assert _retired_scenarios() == set()

    src = (REPO / "histrategy" / "server" / "room_manager.py").read_text(encoding="utf-8")
    assert "in _retired_scenarios()" in src, "闸门必须经过可开关的 helper"
