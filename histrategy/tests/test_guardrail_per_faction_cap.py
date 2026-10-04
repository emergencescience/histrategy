"""守门规则（guardrail）：缩放必须**逐势力**，不能全体共用一个系数。

用户 2026-10-04 裁定：
「缩放只作用于超限的那个势力，或按"超出 50% 的部分"等比削减，而不是全体现乘同一系数。」

## 旧行为的病（生产/本地实测复现）

`_clamp_extreme_changes` 取**最大涨幅者的比例**当**全体**的缩放系数：
```
scale = (1 + 0.50) / max_gain_ratio
```
罗马实测（antony 27000 / octavian 1500 / senate 43000 / cleopatra 15000）：

| 势力 | 原始 | 旧结果 | 新结果 |
|---|---|---|---|
| octavian | 1500 → 5935 (+396%) | 2250 | 2250（自己的 +50% 上限）|
| cleopatra | 15000 → 17000 (+13%) | **6444（−57%）** | **保持 17000** |
| senate | 43000 → 48000 (+12%) | **18197（−58%）** | **保持 48000** |
| antony | 27000 → 27500 (+2%) | 8250（−69%） | **保持 27500** |

一个 1500 人的小势力涨兵 → 元老院和埃及被砍掉一半兵力，且与战损无关。
用户看到的"势力莫名掉一半兵"全出自这里。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "histrategy-engine" / "src"))

from histrategy.engine.helpers import create_initial_world  # noqa: E402
from histrategy.engine.scenario_loader import ScenarioLoader  # noqa: E402
from histrategy.server import room_manager  # noqa: E402

ROME = "rome-triumvirate"


def _make_ws(troops: dict[str, int]):
    """构造一个罗马世界并把各势力兵力设成指定值。"""
    ws = ScenarioLoader(ROME).build_world_state("antony")
    for fid, t in troops.items():
        ws.factions[fid].strength_actual = t
    return ws


def test_small_faction_gain_does_not_drag_down_everyone():
    """核心回归：一个 +396% 的小势力**不得**把大势力拉下水。"""
    old = {
        "antony": {"troops": 27000, "food": 32000},
        "octavian": {"troops": 1500, "food": 750},
        "senate": {"troops": 43000, "food": 30000},
        "cleopatra": {"troops": 15000, "food": 20000},
    }
    # 模拟 LLM 宏观层给出的原始值（就是生产日志里那组数）
    ws = _make_ws({
        "antony": 27500,     # +2%
        "octavian": 5935,    # +396%  ← 触发条件的小势力
        "senate": 48000,     # +12%
        "cleopatra": 17000,  # +13%
    })

    room_manager._clamp_extreme_changes(ws, old)

    # 超限者被压到自己的 +50% 上限
    assert ws.factions["octavian"].strength_actual == 2250, "1500 × 1.5 = 2250"

    # 未超限者**必须原样保留** —— 这是本次修复的核心
    assert ws.factions["cleopatra"].strength_actual == 17000, "埃及 +13% 不该被缩放"
    assert ws.factions["senate"].strength_actual == 48000, "元老院 +12% 不该被缩放"
    assert ws.factions["antony"].strength_actual == 27500, "安东尼 +2% 不该被缩放"


def test_gain_cap_is_per_faction_when_several_exceed():
    """多个势力同时超限 → 各自停在自己的上限，互不影响。"""
    old = {
        "antony": {"troops": 10000, "food": 5000},
        "octavian": {"troops": 1000, "food": 500},
        "senate": {"troops": 20000, "food": 5000},
        "cleopatra": {"troops": 4000, "food": 5000},
    }
    ws = _make_ws({
        "antony": 90000,     # +800% → 上限 15000
        "octavian": 20000,   # +1900% → 上限 1500
        "senate": 80000,     # +300% → 上限 30000
        "cleopatra": 5000,   # +25%  → 不动
    })

    room_manager._clamp_extreme_changes(ws, old)

    assert ws.factions["antony"].strength_actual == 15000
    assert ws.factions["octavian"].strength_actual == 1500
    assert ws.factions["senate"].strength_actual == 30000
    assert ws.factions["cleopatra"].strength_actual == 5000, "未超限者不受他人影响"


def test_loss_cap_applies_independently():
    """损失上限也必须独立生效 —— 旧代码里它只在"有人涨超"时才跑。"""
    old = {
        "antony": {"troops": 30000, "food": 5000},
        "octavian": {"troops": 1000, "food": 500},
        "senate": {"troops": 40000, "food": 5000},
        "cleopatra": {"troops": 20000, "food": 5000},
    }
    ws = _make_ws({
        "antony": 27000,     # +? 不涨不跌的没进统计
        "octavian": 1000,    # 不变
        "senate": 40000,     # 不变
        "cleopatra": 5000,   # −75% → 必须被压到 −35%（13000）
    })
    # 没有人涨超 +50%，旧代码因此**完全跳过** loss 分支 → 埃及真的掉到 5000
    room_manager._clamp_extreme_changes(ws, old)
    assert ws.factions["cleopatra"].strength_actual == 13000, "20000 × 0.65 = 13000"


def test_scenery_faction_is_skipped_by_guardrail():
    """布景势力不参与结算 → 也不进守门缩放（否则它的暴涨会污染统计）。"""
    old = {
        "antony": {"troops": 27000, "food": 32000},
        "sextus_pompey": {"troops": 5000, "food": 3000},
    }
    ws = _make_ws({"antony": 27000, "sextus_pompey": 99999})
    room_manager._clamp_extreme_changes(ws, old)
    assert ws.factions["sextus_pompey"].strength_actual == 99999, "布景势力不该被守门改动"


def test_population_is_not_guardrail_business():
    """不变量：本函数只改兵力/粮草，**不碰人口**（人口唯一来源是 settled_population）。

    检查属性赋值而非裸词 —— 源码注释里出现 "population" 是说明文字，不算改动。
    """
    import inspect

    src = inspect.getsource(room_manager._clamp_extreme_changes)
    assert "settled_population" not in src
    assert ".population" not in src, "人口不该在这里被赋值；每季由 settled_population() 重算"
