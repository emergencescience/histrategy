"""罗马剧本 V3 可玩性回归（2026-10-04）

设计文档：emergence-meta/internal/design/2026-10-04-histrategy-rome-v3-playability.md

覆盖四件事：
1. **地图拓扑** —— 罗马世界以地中海为交通主干，剧本声明 `map_topology =
   fully_connected`，loader 物化成全连通图（不需要显式边）。此前罗马 0/18 块地
   有 neighbors → 任何势力都无法移动/进攻/占领，全剧本零战斗。
2. **人口与土地脱钩** —— 人口是势力级属性；剧本可声明 population（家丁/门客），
   无地也保有人口。此前 `_build_factions()` 根本没传 population，声明无效。
3. **非领土收入** —— 庄园(patrimonium) + 海外贸易。声明在剧本里，每季结算，
   与领土无关。此前无地势力完全没有经济基座。
4. **硬编码下限删除** —— 人口 50000 / 100、粮食 3000 三个魔法数字被删除，
   两条人口计算路径必须给出同一个数（否则同一势力在两个页面显示两个值）。
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "histrategy-engine" / "src"))

from histrategy.engine.helpers import create_initial_world  # noqa: E402
from histrategy.engine.scenario_loader import ScenarioLoader  # noqa: E402
from histrategy_engine import (  # noqa: E402
    CharacterEngine,
    DecisionEngine,
    DomesticEngine,
    MapEngine,
    MilitaryEngine,
    TurnController,
)

ROME = "rome-triumvirate"
PLAYER = "octavian"


@pytest.fixture
def rome_ws():
    return ScenarioLoader(ROME).build_world_state(PLAYER)


@pytest.fixture(scope="module")
def tc():
    return TurnController(
        map_engine=MapEngine(),
        char_engine=CharacterEngine(),
        domestic_engine=DomesticEngine(),
        military_engine=MilitaryEngine(),
        decision_engine=DecisionEngine(),
    )


# ── 1. 地图拓扑 ──────────────────────────────────────────────────────
def test_rome_map_topology_is_fully_connected(rome_ws):
    """罗马地图必须是全连通：任意两块地彼此相邻，且邻接对称。"""
    me = MapEngine(rome_ws.territories)
    ids = list(rome_ws.territories)
    assert len(ids) >= 19, f"expected campania to be added, got {len(ids)} territories"

    empties = [t for t, v in rome_ws.territories.items() if not v.neighbors]
    assert not empties, f"territories with empty neighbors (map is disconnected): {empties}"

    for a in ids:
        for b in ids:
            if a == b:
                continue
            assert me.are_adjacent(a, b), f"{a} not adjacent to {b}"
            assert me.are_adjacent(a, b) == me.are_adjacent(b, a), f"asymmetric: {a}/{b}"


def test_rome_capture_guard_no_longer_blocks_remote_attacks(rome_ws):
    """端到端语义验证：`state_applier._attacker_borders_territory` 是**唯一**
    会打印 "Territory capture BLOCKED" 的关卡。罗马零邻接时它对任何一对
    势力/城池都返回 False（攻城永远被拒）；全连通后必须放行。

    这是"罗马剧本零战斗"这个症状的直接判据 —— 断言守卫本身，而不是间接的
    `are_adjacent()`。
    """
    from histrategy.engine.state_applier import _attacker_borders_territory

    # campania(octavian) → aegyptus(cleopatra)：罗马世界最远的对角
    assert _attacker_borders_territory(PLAYER, "aegyptus", rome_ws) is True
    assert _attacker_borders_territory("cleopatra", "campania", rome_ws) is True
    # 每一对（势力, 非己方城池）都必须放行
    for fid, f in rome_ws.factions.items():
        for tid, t in rome_ws.territories.items():
            if t.owner_id == fid:
                continue
            assert _attacker_borders_territory(fid, tid, rome_ws) is True, f"{fid} -> {tid} blocked"


def test_other_scenarios_keep_sparse_adjacency():
    """反向用例：三国/南明仍走 territories.json 的显式 neighbors，没被全连通污染。"""
    for scenario in ("three-kingdoms", "nanming"):
        sl = ScenarioLoader(scenario)
        assert sl.map_topology == "adjacency", f"{scenario} should stay adjacency-based"
        ws = sl.build_world_state(sl.available_factions[0])
        ids = list(ws.territories)
        total = len(ids) * (len(ids) - 1)
        actual = sum(len(v.neighbors) for v in ws.territories.values())
        assert actual < total, f"{scenario} became fully connected ({actual} edges)"


# ── 2. 玩家势力有了起始城 + 家丁 ────────────────────────────────────
def test_octavian_has_campania_and_retainers(rome_ws):
    oct_ = rome_ws.factions[PLAYER]
    assert "campania" in oct_.territories, "octavian must start with campania"
    assert rome_ws.territories["campania"].owner_id == PLAYER
    # 有城时人口 = 城池人口（120000）；家丁声明是**下限**，不是叠加
    assert oct_.population == 120000, f"got {oct_.population}"
    # 兵力不变 —— 弱而有基
    assert oct_.strength_actual == 1000


def test_landless_faction_keeps_declared_population():
    """无地势力靠剧本声明的 population 存活（100 家丁），不再是 0 或 50000。"""
    sl = ScenarioLoader(ROME)
    ws = sl.build_world_state(PLAYER)
    oct_ = ws.factions[PLAYER]

    # 模拟丢掉全部领土
    for tid in list(oct_.territories):
        ws.territories[tid].owner_id = ""
    oct_.territories = []
    oct_.population = 100  # 剧本声明值

    from histrategy.server.room_manager import _resolve_faction_population

    resolved = _resolve_faction_population(oct_, ws, [], {"population": 100})
    assert resolved == 100, f"landless retainer population should be 100, got {resolved}"


def test_no_more_hardcoded_population_floors():
    """无地 + 无人口的势力必须解析为 0 —— 不许再出现 50000 / 100 这类魔法数字。"""
    from histrategy.server.room_manager import _resolve_faction_population

    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    sextus = ws.factions["sextus_pompey"]
    sextus.territories = []
    sextus.population = 0

    assert _resolve_faction_population(sextus, ws, [], {"population": 0}) == 0
    assert _resolve_faction_population(sextus, ws, [{"population": 0}], {"population": 0}) == 0
    assert _resolve_faction_population(sextus, ws, [], None) == 0


def test_two_population_paths_agree(rome_ws):
    """`_resolve_faction_population`（写 game_state）与 `_extract_state_changes`
    （写 state_changes / 分享页）对同一势力必须给出同一个数。

    这条契约的失守正是"游戏页 50000、分享页 100"的根因。
    """
    from histrategy.engine.quarterly_resolver import _extract_state_changes
    from histrategy.server.room_manager import _resolve_faction_population

    changes = _extract_state_changes(rome_ws, {})
    for fid, faction in rome_ws.factions.items():
        if not faction.is_active:
            continue
        a = _resolve_faction_population(faction, rome_ws, [], {"population": faction.population})
        b = changes["faction_stats"][fid]["population"]
        assert a == b, f"{fid}: game_state={a} vs state_changes={b}"


# ── 3. 非领土收入 ────────────────────────────────────────────────────
def test_off_territory_income_is_declared_and_zero_by_default(rome_ws):
    assert rome_ws.factions[PLAYER].off_territory_income == 1200
    assert rome_ws.factions[PLAYER].off_territory_food == 200
    # 其他三势力 + 其他剧本：默认 0，零影响
    for fid in ("antony", "cleopatra", "senate", "sextus_pompey"):
        assert rome_ws.factions[fid].off_territory_income == 0.0
        assert rome_ws.factions[fid].off_territory_food == 0.0


def test_off_territory_income_paid_even_without_territory(tc, rome_ws):
    """无地也照付：这是"屋大维不靠领土取得财税"的落地保证。

    直接调用 TurnController.execute_turn 走真实经济结算，断言屋大维的国库
    在一季度后**增加**（此前他永远卡在 1000，一分不动）。
    """
    oct_ = rome_ws.factions[PLAYER]
    # 剥掉领土，只有家丁 + 家族收入
    for tid in list(oct_.territories):
        rome_ws.territories[tid].owner_id = ""
    oct_.territories = []
    oct_.strength_actual = 0  # 免掉无地驻军粮耗，隔离出收入这一项
    gold_before = oct_.treasury

    tc.execute_turn(rome_ws, player_commands=[])

    assert oct_.treasury > gold_before, (
        f"landless octavian treasury did not grow: {gold_before} -> {oct_.treasury}"
    )
    assert oct_.treasury - gold_before == 1200


def test_landless_treasury_at_zero_income_stays_flat(tc):
    """反向用例：没声明 off_territory_income 的无地势力，国库不会凭空增长。"""
    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    sx = ws.factions["sextus_pompey"]
    sx.territories = []
    sx.strength_actual = 0
    before = sx.treasury
    tc.execute_turn(ws, player_commands=[])
    assert sx.treasury == before, f"sextus got free money: {before} -> {sx.treasury}"


# ── 4. 粮食绝对下限删除 ──────────────────────────────────────────────
def test_food_absolute_floor_removed(rome_ws):
    """低粮势力不再被抬到 3000。proportional 保底仍在，但绝对地板必须为 0。"""
    import inspect

    from histrategy.server import room_manager

    src = inspect.getsource(room_manager._clamp_extreme_changes)
    assert "_FOOD_FLOOR_ABSOLUTE = 0" in src, "food absolute floor must be 0"
    assert "_FOOD_FLOOR_ABSOLUTE = 3000" not in src

    # 行为验证：把屋大维粮食压到 500 以下，跑完 guardrail 不应被抬到 3000
    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    old_state = {fid: {"population": f.population, "troops": 0, "food": 500,
                       "treasury": f.treasury, "morale": f.morale_actual,
                       "territories": list(f.territories)}
                 for fid, f in ws.factions.items()}
    for f in ws.factions.values():
        f.food = 100
    room_manager._clamp_extreme_changes(ws, old_state)
    assert ws.factions[PLAYER].food < 3000, (
        f"food was bumped back to a magic floor: {ws.factions[PLAYER].food}"
    )
