"""Unit tests for LLM grounding contexts (territories and deceased characters)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.llm.game_master import _build_command_context, _build_plan_context
from histrategy.llm.narrative import NarrativeEngine
from histrategy.state.world_state import CharacterState, FactionState, TerritoryState, WorldState


class MockSeason:
    def __init__(self, cn):
        self.cn = cn


class MockTurnResult:
    def __init__(self):
        self.year = 207
        self.season = MockSeason("冬季")
        self.turn_number = 1
        self.climate_events = {}
        self.resource_changes = {}
        self.battles = []
        self.character_events = []
        self.faction_snapshots = {}


def test_narrative_context_with_world_state():
    """Verify that _build_narrative_context properly formats territories and deceased characters."""
    engine = NarrativeEngine(None)
    tr = MockTurnResult()
    ws = WorldState()
    ws.year = 208
    ws.season_index = 2  # autumn
    ws.turn = 3

    # Mock factions
    ws.factions["cao"] = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        strength=30000,
        economy=55,
        morale=75,
        treasury=10000,
        food=5000,
        territories=["xuchang", "luoyang"],
    )
    ws.factions["cao"].strength_actual = 30000

    # Mock territories
    ws.territories["xuchang"] = TerritoryState(id="xuchang", name="许昌", owner_id="cao")
    ws.territories["luoyang"] = TerritoryState(id="luoyang", name="洛阳", owner_id="cao")

    # Mock characters
    ws.characters["caocao"] = CharacterState(id="caocao", name="曹操", faction_id="cao", alive=True)
    ws.characters["dongzhuo"] = CharacterState(id="dongzhuo", name="董卓", faction_id="dongzhuo", alive=False)

    context = engine._build_narrative_context(tr, world_state=ws)

    assert "## 天下势力及控制城池" in context
    assert "曹操军" in context
    assert "许昌, 洛阳" in context
    assert "## 已亡故/不活跃人物" in context
    assert "董卓" in context
    assert "刘表" in context


def test_plan_context_formatting():
    """Verify that _build_plan_context correctly maps names and deceased characters."""
    ws = WorldState()
    ws.year = 208
    ws.season_index = 2
    ws.turn = 3
    ws.player_faction_id = "cao"

    ws.factions["cao"] = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        strength=30000,
        economy=55,
        morale=75,
        treasury=10000,
        food=5000,
        territories=["xuchang"],
    )
    ws.factions["shu"] = FactionState(
        id="shu",
        name="刘备军",
        ruler_id="liubei",
        capital="xinye",
        strength=5000,
        economy=30,
        morale=80,
        treasury=2000,
        food=1500,
        territories=["xinye"],
    )

    ws.territories["xuchang"] = TerritoryState(id="xuchang", name="许昌", owner_id="cao")
    ws.territories["xinye"] = TerritoryState(id="xinye", name="新野", owner_id="shu")

    ws.characters["caocao"] = CharacterState(id="caocao", name="曹操", faction_id="cao", alive=True)
    ws.characters["liubei"] = CharacterState(id="liubei", name="刘备", faction_id="shu", alive=True)
    ws.characters["dongzhuo"] = CharacterState(id="dongzhuo", name="董卓", faction_id="dongzhuo", alive=False)

    plan_context = _build_plan_context(ws)

    assert "领地：许昌" in plan_context
    assert "刘备军" in plan_context
    assert "控制城池：新野" in plan_context
    assert "## 已亡故/不活跃人物" in plan_context
    assert "董卓" in plan_context
    assert "刘表" in plan_context


def test_command_context_formatting():
    """Verify that _build_command_context formats correctly with decision and deceased characters."""
    ws = WorldState()
    ws.year = 208
    ws.season_index = 2
    ws.turn = 3
    ws.player_faction_id = "cao"

    ws.factions["cao"] = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        strength=30000,
        economy=55,
        morale=75,
        treasury=10000,
        food=5000,
        territories=["xuchang"],
    )

    ws.territories["xuchang"] = TerritoryState(id="xuchang", name="许昌", owner_id="cao")
    ws.characters["caocao"] = CharacterState(id="caocao", name="曹操", faction_id="cao", alive=True)

    cmd_context = _build_command_context(ws, "整顿内政")

    assert "领地：许昌" in cmd_context
    assert "主公决策" in cmd_context
    assert "整顿内政" in cmd_context
    assert "## 已亡故/不活跃人物" in cmd_context
