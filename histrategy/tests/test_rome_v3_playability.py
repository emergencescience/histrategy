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
    from histrategy_engine.world import is_settled

    checked = 0
    for fid, faction in rome_ws.factions.items():
        if not faction.is_active or not is_settled(rome_ws, fid):
            continue  # 布景势力不参与结算，自然不在 faction_stats 里
        checked += 1
        a = _resolve_faction_population(faction, rome_ws, [], {"population": faction.population})
        b = changes["faction_stats"][fid]["population"]
        assert a == b, f"{fid}: game_state={a} vs state_changes={b}"
    # 罗马：4 个势力参与结算，sextus_pompey 排除在外
    assert checked == 4, f"expected 4 settled factions, checked {checked}"
    assert "sextus_pompey" not in changes["faction_stats"]


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


# ── 3.5 结算范围：只有 N 个势力被结算（用户 2026-10-04 裁定）───────────
def test_settled_faction_scope_per_scenario():
    """罗马 4 个、三国 3 个势力参与每回合状态结算，其余是"世界布景"。

    布景势力（minor_npc / npc_only）持有静态驻军：不产出 state_changes /
    turn_delta，经济不漂移。此前他们被结算，漂移泄漏成分享页上的裸内部 ID
    和幽灵 0→50000 人口增量。
    """
    from histrategy.engine.scenario_loader import ScenarioLoader

    # 顺序 = available ∪ major_npc（available 已按难度从易到难排列）
    assert ScenarioLoader("rome-triumvirate").settled_factions == [
        "antony", "senate", "cleopatra", "octavian",
    ]
    assert ScenarioLoader("three-kingdoms").settled_factions == ["cao", "shu", "wu"]
    # 三国的 liubiao / liuzhang 在 initial_state 里存在，但**不**参与结算
    tk = ScenarioLoader("three-kingdoms").settled_factions
    assert "liubiao" not in tk and "liuzhang" not in tk


def test_scenery_faction_is_excluded_from_state_changes(rome_ws):
    from histrategy.engine.quarterly_resolver import _extract_state_changes

    changes = _extract_state_changes(rome_ws, {})
    assert "sextus_pompey" not in changes
    assert "sextus_pompey" not in changes["faction_stats"]
    assert set(changes["faction_stats"]) == {"octavian", "antony", "cleopatra", "senate"}


def test_scenery_faction_state_does_not_drift(tc):
    """跑一个季度，布景势力的经济状态必须**一动不动**（无税收、无粮耗、无漂移）。"""
    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    sextus = ws.factions["sextus_pompey"]
    before = (sextus.treasury, sextus.food, sextus.population, sextus.morale_actual)
    before_terr = {
        tid: ws.territories[tid].population
        for tid in sextus.territories
    }
    assert before_terr, "sextus should hold sicilia+sardinia as scenery"

    tc.execute_turn(ws, player_commands=[])

    after = (sextus.treasury, sextus.food, sextus.population, sextus.morale_actual)
    assert before == after, f"scenery faction drifted: {before} -> {after}"
    for tid, pop in before_terr.items():
        assert ws.territories[tid].population == pop, f"{tid} population drifted"


def test_settled_factions_still_get_settled(tc):
    """反向用例：参与结算的势力**必须**仍然会变（别把'冻结'做成'全冻'）。"""
    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    oct_ = ws.factions[PLAYER]
    gold_before = oct_.treasury
    tc.execute_turn(ws, player_commands=[])
    assert oct_.treasury != gold_before, "settled faction must still be settled"


def test_population_drops_when_city_is_lost():
    """丢城 → 编户人口随之消失，只剩家丁下限（用户 2026-10-04 追问的语义）。

    此前 `faction.population` 只在载入时算一次，丢了城仍带着旧值
    （生产实测：屋大维丢了坎帕尼亚，人口还显示 112860）。
    """
    from histrategy.server.room_manager import _resolve_faction_population

    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    oct_ = ws.factions[PLAYER]
    assert _resolve_faction_population(oct_, ws, [], None) == 120000

    # 坎帕尼亚被夺走
    ws.territories["campania"].owner_id = "antony"
    oct_.territories = []
    pop = _resolve_faction_population(oct_, ws, [], {"population": 112860})
    assert pop == 100, f"丢城后应只剩 100 家丁，实得 {pop}（陈旧的 112860 是 bug）"


def test_settled_scope_survives_db_round_trip():
    """⚠️ 这条测试是为了锁死一个**只在生产暴露**的静默失效（2026-10-04）。

    进程内的 WorldState 带着 `settled_faction_ids`（房间刚创建时正确），
    但 `load_room()` 是从 DB 反序列化重建 WorldState 的 —— 而
    `deserialize_world_state()` 此前**从不恢复这个字段**，空列表的含义又是
    "全部结算"，于是「只有 N 个势力参与结算」在第一次 DB 往返后就静默退回全体。
    症状：单元测试全绿，生产却仍在给 sextus_pompey 写 game_state / turn_delta。

    所以这里必须走真实的 serialize → deserialize 往返，而不是只测内存对象。
    """
    from histrategy.db.models import _serialize_world_state, deserialize_world_state
    from histrategy_engine.world import is_settled

    ws = ScenarioLoader(ROME).build_world_state(PLAYER)
    blob = _serialize_world_state(ws)
    assert blob is not None
    restored = deserialize_world_state(blob)

    assert restored.settled_faction_ids == ["antony", "senate", "cleopatra", "octavian"], (
        f"DB 往返后结算范围丢了：{restored.settled_faction_ids}"
    )
    assert not is_settled(restored, "sextus_pompey"), (
        "sextus_pompey 在 DB 往返后又变成'参与结算'了 —— 生产会继续给他写 state"
    )
    for fid in ("antony", "senate", "cleopatra", "octavian"):
        assert is_settled(restored, fid)

    # 反向：三国的 liubiao 同样必须在往返后仍被排除
    tk = ScenarioLoader("three-kingdoms").build_world_state("cao")
    tk_restored = deserialize_world_state(_serialize_world_state(tk))
    assert not is_settled(tk_restored, "liubiao")
    assert is_settled(tk_restored, "cao")


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
