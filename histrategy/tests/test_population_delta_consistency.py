"""回归保护：人口增量必须与落库状态一致（H38e）。

根因（2026-10-03 由真实玩家房间 cecdcd987… 反查发现）：
`room_manager` 里"本势力人口"被**算了两遍**——
  - 写 `game_state` 用 `computed_population`（三层兜底，无城池也会给 50000）
  - 写 `turn_delta` 另调用 `_capture_faction_population()`（无城池势力返回 0）
于是同一个回合里 `game_state.population = 50000` 而 `turn_delta` 记 `50000 → 0`，
玩家屏幕上每回合演一次"人口归零"的假灾难。全库 25.1%（2041/8143）的
population delta 都归零，rome 剧本开局无城池的 octavian / sextus_pompey 每回合必中。

修法：抽出唯一来源 `_resolve_faction_population()`，状态写入与增量记录共用同一个值。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.server.room_manager import _resolve_faction_population  # noqa: E402


def _faction(population=None, territories=()):
    kwargs = {"territories": list(territories)}
    if population is not None:
        kwargs["population"] = population
    return SimpleNamespace(**kwargs)


def _ws(territories=None):
    return SimpleNamespace(territories=territories or {})


def test_territoryless_faction_does_not_collapse_to_zero():
    """rome 的 octavian 开局无城池 —— 绝不能解析成 0（那正是那个假灾难）。"""
    pop = _resolve_faction_population(_faction(), _ws(), [], None)
    assert pop == 50000, f"无城池势力应回落到最低人口 50000，实得 {pop}"


def test_territoryless_faction_carries_forward_previous_quarter():
    """有上一季度记录时，应沿用上一季度，而不是掉到 0 或跳到 50000。"""
    pop = _resolve_faction_population(_faction(), _ws(), [], {"population": 12345})
    assert pop == 12345, f"应沿用上一季度 12345，实得 {pop}"


def test_population_from_territories_sum():
    tids = ["roma", "campania"]
    ws = _ws({"roma": SimpleNamespace(population=30000), "campania": SimpleNamespace(population=20000)})
    pop = _resolve_faction_population(_faction(territories=tids), ws, [], None)
    assert pop == 50000, f"应由领土求和得 50000，实得 {pop}"


def test_no_zero_for_any_combination():
    """穷举常见组合：任何情况下都不允许返回 0（0 会渲染成"归零"）。"""
    cases = [
        (_faction(), _ws(), [], None),
        (_faction(), _ws(), [], {"population": 0}),
        (_faction(territories=["ghost"]), _ws(), [], None),
        (_faction(), _ws(), [{"population": 0}], None),
    ]
    for faction, ws, tl, old in cases:
        assert _resolve_faction_population(faction, ws, tl, old) > 0
