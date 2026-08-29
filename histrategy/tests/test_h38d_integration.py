"""H38d 集成测试：税率键名统一 (tax_rate|new_rate|rate) + 兵力裁决铁律 prompts。

回归保护：
- NPC 决策文本循环根因 — tax 命令键名三处不一致 (npc prompt 用 tax_rate,
  macro-sim 用 new_rate, 代码只读 rate) → 所有 NPC 税收令被静默丢弃,
  南明"税率60%"死循环。
- macro-sim 双标 (玩家攻必胜 / NPC 攻必败) → 6 个 macro_simulator prompt
  必须包含兵力裁决铁律。
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "histrategy-engine" / "src"))

from histrategy.engine.helpers import create_initial_world  # noqa: E402
from histrategy_engine import (  # noqa: E402
    CharacterEngine,
    DecisionEngine,
    DomesticEngine,
    MapEngine,
    MilitaryEngine,
    TurnController,
)
from histrategy_engine.world import Command  # noqa: E402


@pytest.fixture(scope="module")
def tc():
    return TurnController(
        map_engine=MapEngine(),
        char_engine=CharacterEngine(),
        domestic_engine=DomesticEngine(),
        military_engine=MilitaryEngine(),
        decision_engine=DecisionEngine(),
    )


def _tax(params, fid="nanming"):
    return Command(type="tax", params=params, faction_id=fid)


# ── 1. 校验器接受三种键名 + 新区间 [0.05, 0.6] ──
@pytest.mark.parametrize(
    "params,expected",
    [
        ({"rate": 0.15}, True),  # 旧键名
        ({"tax_rate": 0.08}, True),  # NPC 结构化决策键名 (原被拒)
        ({"new_rate": 0.20}, True),  # macro-sim 键名 (原被拒)
        ({"rate": 0.60}, True),  # 上限 0.6 现在合法
        ({"rate": 0.05}, True),  # 下限 0.05 现在合法
        ({"rate": 0.02}, False),  # 低于新下限 → 拒绝
        ({"rate": 0.9}, False),  # 超新上限 → 拒绝
        ({"foo": 0.1}, False),  # 无任何已知键 → 拒绝
    ],
)
def test_tax_validator_accepts_all_keys(tc, params, expected):
    ws = create_initial_world("zheng", "nanming")
    assert tc._is_valid_command(_tax(params), ws) == expected


# ── 2. 执行器应用三种键名 + clamp 到 [0.05, 0.6] ──
def test_tax_executor_applies_keys(tc):
    ws = create_initial_world("zheng", "nanming")
    nanming = ws.factions["nanming"]
    rc = {}

    tc._execute_domestic(_tax({"tax_rate": 0.08}), ws, rc)
    assert abs(nanming.tax_rate - 0.08) < 1e-9, f"tax_rate 键未生效: {nanming.tax_rate}"

    tc._execute_domestic(_tax({"new_rate": 0.25}), ws, rc)
    assert abs(nanming.tax_rate - 0.25) < 1e-9, f"new_rate 键未生效: {nanming.tax_rate}"

    tc._execute_domestic(_tax({"rate": 0.7}), ws, rc)
    assert abs(nanming.tax_rate - 0.6) < 1e-9, f"应 clamp 到 0.6: {nanming.tax_rate}"


# ── 3. 完整确定性回合 (多势力混合命令, 无 LLM) — 无回归 ──
def test_full_deterministic_turn_with_tax(tc):
    from histrategy.engine.scenario_loader import ScenarioLoader

    ws = ScenarioLoader("nanming").build_world_state("zheng")
    cmds = [
        Command(type="tax", params={"tax_rate": 0.15}, faction_id="nanming"),
        Command(type="develop", params={"territory": "fujian", "focus": "agriculture"}, faction_id="zheng"),
        Command(type="recruit", params={"territory": "fujian", "unit_type": "infantry", "amount": 2000}, faction_id="zheng"),
        Command(type="move", params={"destination": "taiwan", "source_territory": "fujian", "unit_type": "navy"}, faction_id="zheng"),
    ]
    result = tc.execute_turn(ws, player_commands=cmds, year=1645, turn_number=1)
    # tax_rate 键名统一后必须真正生效
    assert abs(ws.factions["nanming"].tax_rate - 0.15) < 1e-9, "完整回合中 tax_rate 未生效"
    assert result is not None


# ── 4. 6 个 macro_sim prompt 含新铁律 ──
def test_macro_sim_prompts_contain_rules():
    for scenario in ("nanming", "three-kingdoms", "rome-triumvirate"):
        for lang, marker in (("zh", "兵力裁决铁律"), ("en", "Force-adjudication iron law")):
            p = REPO / "scenarios" / scenario / "prompts" / f"macro_simulator_{lang}.md"
            assert p.exists(), f"missing {p}"
            text = p.read_text(encoding="utf-8")
            assert marker in text, f"{p} missing {marker}"
            assert "地图边界铁律" in text or "Map-boundary" in text, f"{p} missing map-boundary rule"
