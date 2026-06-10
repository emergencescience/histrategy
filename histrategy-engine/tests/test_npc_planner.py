"""Tests for NPCPlanner — dual-horizon decision with fog-of-war."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from histrategy_engine.ai import DecisionEngine
from histrategy_engine.ai.fog_of_war import LocalWorldStateProjector
from histrategy_engine.ai.npc_planner import NPCPlanner
from histrategy_engine.world import (
    Army,
    Character,
    FactionState,
    Season,
    Territory,
    WorldState,
)


def make_test_world() -> WorldState:
    """3-faction world: shu (weak) borders cao (strong), allied with wu."""
    ws = WorldState()
    ws.year = 207
    ws.season = Season.WINTER

    cao = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        territories=["xuchang", "wancheng"],
        treasury=50000,
        food=30000,
        legitimacy=50,
    )
    cao.strength_actual = 150000
    cao.economy_actual = 80
    cao.morale_actual = 75
    cao.allies = []
    cao.enemies = ["shu"]

    shu = FactionState(
        id="shu",
        name="刘备军",
        ruler_id="liubei",
        capital="xinye",
        territories=["xinye"],
        treasury=3000,
        food=2000,
        legitimacy=40,
    )
    shu.strength_actual = 5000
    shu.economy_actual = 30
    shu.morale_actual = 70
    shu.allies = ["wu"]
    shu.enemies = ["cao"]

    wu = FactionState(
        id="wu",
        name="孙权军",
        ruler_id="sunquan",
        capital="jianye",
        territories=["jianye"],
        treasury=20000,
        food=15000,
        legitimacy=60,
    )
    wu.strength_actual = 60000
    wu.economy_actual = 70
    wu.morale_actual = 80
    wu.allies = ["shu"]
    wu.enemies = ["cao"]

    ws.factions = {"cao": cao, "shu": shu, "wu": wu}
    ws.player_faction_id = "shu"

    # Territories
    ws.territories = {
        "xuchang": Territory(
            id="xuchang",
            name="许昌",
            owner_id="cao",
            climate_zone="central",
            population=200000,
            fertility=80,
            development=50,
            neighbors=["wancheng"],
        ),
        "wancheng": Territory(
            id="wancheng",
            name="宛城",
            owner_id="cao",
            climate_zone="central",
            population=80000,
            fertility=60,
            development=35,
            neighbors=["xuchang", "xinye"],
        ),
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            climate_zone="central",
            population=30000,
            fertility=60,
            development=30,
            neighbors=["wancheng"],
        ),
        "jianye": Territory(
            id="jianye",
            name="建业",
            owner_id="wu",
            climate_zone="south",
            population=100000,
            fertility=70,
            development=55,
            neighbors=[],
        ),
    }

    # Characters
    ws.characters = {
        "zhugeliang": Character(
            id="zhugeliang",
            name="诸葛亮",
            faction_id="shu",
            loyalty=95,
            leadership=92,
            politics=98,
            intelligence=100,
        ),
        "caocao": Character(
            id="caocao",
            name="曹操",
            faction_id="cao",
            loyalty=100,
            leadership=98,
            politics=95,
            intelligence=96,
        ),
    }

    # Armies
    ws.armies = {
        "army_cao_1": Army(
            id="army_cao_1", faction_id="cao", location="wancheng", commander_id="caocao", morale=85
        ),
    }
    ws.armies["army_cao_1"].units["infantry"] = 20000

    return ws


class TestNPCPlanner:
    """Tests for NPCPlanner with fog-of-war."""

    def setup_method(self):
        self.engine = DecisionEngine()
        self.projector = LocalWorldStateProjector()
        self.planner = NPCPlanner(self.engine, self.projector)

    def test_creates_planner(self):
        planner = NPCPlanner()
        assert planner._engine is not None
        assert planner._projector is not None

    def test_shu_sees_cao_as_threat(self):
        """Shu (5000) borders Cao (150000) → should detect high threat."""
        ws = make_test_world()
        intent = self.planner.evaluate_strategic_position("shu", ws)

        assert intent.objective == "defend"
        assert intent.target_faction == "cao"
        assert intent.aggressiveness < 0.5  # should be cautious

    def test_cao_sees_shu_as_opportunity(self):
        """Cao (150000) borders Shu (5000) → should see opportunity."""
        ws = make_test_world()
        intent = self.planner.evaluate_strategic_position("cao", ws)

        assert intent.objective in ("expand", "maintain")
        # Cao might see opportunity to attack weak Shu

    def test_generates_commands_local(self):
        """Planner should generate commands from projected state."""
        ws = make_test_world()

        # Create a real MapEngine stub
        class FakeMap:
            def get_neighbors(self, tid):
                mapping = {
                    "xinye": ["wancheng"],
                    "wancheng": ["xuchang", "xinye"],
                    "xuchang": ["wancheng"],
                    "jianye": [],
                }
                return mapping.get(tid, [])

        fake_map = FakeMap()
        commands = self.planner.generate_commands_local("shu", ws, fake_map)

        assert isinstance(commands, list)
        # Shu is threatened → should generate defensive commands
        # (recruit or develop)

    def test_parse_range_estimate(self):
        planner = NPCPlanner()
        assert planner._parse_strength_estimate("18,000~22,000") == 20000
        assert planner._parse_strength_estimate("5,000") == 5000
        assert planner._parse_strength_estimate("数万") == 50000
        assert planner._parse_strength_estimate("数千") == 5000
        assert planner._parse_strength_estimate("???") is None
        assert planner._parse_strength_estimate("120,000~140,000") == 130000
