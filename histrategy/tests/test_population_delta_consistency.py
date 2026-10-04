"""回归保护：人口增量必须与落库状态一致（H38e）。

根因（2026-10-03 由真实玩家房间 cecdcd987… 反查发现）：
`room_manager` 里"本势力人口"被**算了两遍**——
  - 写 `game_state` 用 `computed_population`（三层兜底，无城池也会给 50000）
  - 写 `turn_delta` 另调用 `_capture_faction_population()`（无城池势力返回 0）
于是同一个回合里 `game_state.population = 50000` 而 `turn_delta` 记 `50000 → 0`，
玩家屏幕上每回合演一次"人口归零"的假灾难。全库 25.1%（2041/8143）的
population delta 都归零，rome 剧本开局无城池的 octavian / sextus_pompey 每回合必中。

修法：抽出唯一来源 `_resolve_faction_population()`，状态写入与增量记录共用同一个值。

## 契约更新（2026-10-04）—— 兜底不再编造数字
上面那个修法把两处收敛成一处，但**兜底链本身**还留着硬编码的绝对下限
（`_resolve_faction_population` 末尾 `50000`、`_extract_state_changes` 里
`max(100, len(owned)*50000)`）。两条路径各留一个下限，于是同一回合同一势力
在游戏页显示 50000、在分享页显示 100 —— 同一个 bug 换了个形态又回来了
（房间 b1600eecb77f4ec99212c32cc9da4add，全库 15 条幽灵 `0→50000` 增量）。

用户裁定：**无地 + 无人口就是 0**，不许再编造。想要门客/家丁的势力应该
**在剧本数据里声明 `population`**（`initial_state.json`），由 loader 读入 ——
剧本数据是事实，引擎兜底不是。因此：

- 无地、无声明 → **0**（0 是"这家没有编户人口"这个事实，不是灾难）
- 无地、有声明（如屋大维的 100 家丁）→ **声明值**
- 有地 → 领土人口之和（与声明取大者）
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


def test_territoryless_faction_is_zero_when_nothing_declared():
    """无地 + 无声明 = 0。这不是"灾难"，是"这家没有编户人口"这个事实。

    2026-10-04 之前这里断言必须回落到 50000 —— 那个 50000 正是
    "游戏页 50000 / 分享页 100" 那条自相矛盾的源头，已删除。
    """
    pop = _resolve_faction_population(_faction(), _ws(), [], None)
    assert pop == 0, f"无地无人口应如实为 0，实得 {pop}"


def test_territoryless_faction_keeps_declared_retainers():
    """无地但有门客/家丁声明（屋大维 = 100）→ 保住声明值，不掉到 0。

    罗马时期人口不绑土地（clientela 随主家走），所以「无地」不等于「无人」。
    但依据必须是**剧本声明的数据**，不是引擎里的魔法数字。
    """
    pop = _resolve_faction_population(_faction(population=100), _ws(), [], None)
    assert pop == 100, f"应保住声明的 100 家丁，实得 {pop}"

    # 上一季度也是 0 时同样要保住声明值（不能被 old_row 拖到 0）
    pop = _resolve_faction_population(_faction(population=100), _ws(), [], {"population": 0})
    assert pop == 100, f"实得 {pop}"


def test_territoryless_faction_carries_forward_previous_quarter():
    """有上一季度记录时，应沿用上一季度，而不是掉到 0 或跳到 50000。"""
    pop = _resolve_faction_population(_faction(), _ws(), [], {"population": 12345})
    assert pop == 12345, f"应沿用上一季度 12345，实得 {pop}"


def test_population_from_territories_sum():
    tids = ["roma", "campania"]
    ws = _ws({"roma": SimpleNamespace(population=30000), "campania": SimpleNamespace(population=20000)})
    pop = _resolve_faction_population(_faction(territories=tids), ws, [], None)
    assert pop == 50000, f"应由领土求和得 50000，实得 {pop}"


@pytest.mark.parametrize(
    "faction,ws,tl,old,expected",
    [
        # 无地 + 无声明 + 无历史 → 0（如实）
        (_faction(), _ws(), [], None, 0),
        (_faction(), _ws(), [], {"population": 0}, 0),
        # 无地 + 有声明 → 声明值（家丁/门客随主家走）
        (_faction(population=100), _ws(), [], {"population": 0}, 100),
        # 有历史记录 → 沿用历史（不是 0，也不是魔法数）
        (_faction(), _ws(), [], {"population": 12345}, 12345),
        # 地名不存在于 ws → 求和为 0，落到历史/声明
        (_faction(territories=["ghost"]), _ws(), [], {"population": 777}, 777),
        # 快照里人口为 0 → 0
        (_faction(), _ws(), [{"population": 0}], None, 0),
    ],
)
def test_population_resolution_matches_contract(faction, ws, tl, old, expected):
    """穷举组合，钉住 2026-10-04 新契约：**不再编造数字**。

    旧契约是"任何情况都不许返回 0"（于是两条路径各自编了 50000 / 100，
    互相矛盾）。新契约是"有什么说什么"：没有就是 0，有声明就用声明，
    有历史就沿历史。
    """
    assert _resolve_faction_population(faction, ws, tl, old) == expected
