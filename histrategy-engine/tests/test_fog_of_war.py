"""Tests for LocalWorldStateProjector — fog-of-war projection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from histrategy_engine.ai.fog_of_war import (
    LocalWorldStateProjector,
)
from histrategy_engine.world import (
    Army,
    Character,
    FactionState,
    Season,
    Territory,
    WorldState,
)


def make_multi_faction_world() -> WorldState:
    """Create a WorldState with 3 factions for fog-of-war testing."""
    ws = WorldState()
    ws.year = 207
    ws.season = Season.WINTER
    ws._turn_number = 1  # v2 engine uses turn_number

    # Factions
    cao = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        territories=["xuchang", "wancheng"],
        treasury=50000,
        food=30000,
        legitimacy=50,
        allies=[],
        enemies=["shu"],
    )
    cao.strength_actual = 150000
    cao.economy_actual = 80
    cao.morale_actual = 75

    shu = FactionState(
        id="shu",
        name="刘备军",
        ruler_id="liubei",
        capital="xinye",
        territories=["xinye"],
        treasury=3000,
        food=2000,
        legitimacy=40,
        allies=[],
        enemies=["cao"],
    )
    shu.strength_actual = 5000
    shu.economy_actual = 30
    shu.morale_actual = 70

    wu = FactionState(
        id="wu",
        name="孙权军",
        ruler_id="sunquan",
        capital="jianye",
        territories=["jianye", "wujun", "yuzhang"],
        treasury=20000,
        food=15000,
        legitimacy=60,
        allies=["shu"],
        enemies=["cao"],
    )
    wu.strength_actual = 60000
    wu.economy_actual = 70
    wu.morale_actual = 80

    ws.factions = {"cao": cao, "shu": shu, "wu": wu}
    ws.player_faction_id = "shu"

    # Characters
    zhugeliang = Character(
        id="zhugeliang",
        name="诸葛亮",
        faction_id="shu",
        loyalty=95,
        leadership=92,
        politics=98,
        intelligence=100,
    )
    zhaoyun = Character(
        id="zhaoyun",
        name="赵云",
        faction_id="shu",
        loyalty=90,
        leadership=88,
        politics=50,
        intelligence=70,
        is_commanding=True,
    )
    caocao_c = Character(
        id="caocao",
        name="曹操",
        faction_id="cao",
        loyalty=100,
        leadership=98,
        politics=95,
        intelligence=96,
    )
    simayi = Character(
        id="simayi",
        name="司马懿",
        faction_id="cao",
        loyalty=70,
        leadership=85,
        politics=92,
        intelligence=98,
        is_governor=True,
    )
    ws.characters = {
        "zhugeliang": zhugeliang,
        "zhaoyun": zhaoyun,
        "caocao": caocao_c,
        "simayi": simayi,
    }

    # Territories with adjacency
    xuchang = Territory(
        id="xuchang",
        name="许昌",
        owner_id="cao",
        climate_zone="central",
        population=200000,
        fertility=80,
        development=50,
        neighbors=["wancheng"],
    )
    wancheng = Territory(
        id="wancheng",
        name="宛城",
        owner_id="cao",
        climate_zone="central",
        population=80000,
        fertility=60,
        development=35,
        neighbors=["xuchang", "xinye"],
    )
    xinye = Territory(
        id="xinye",
        name="新野",
        owner_id="shu",
        climate_zone="central",
        population=30000,
        fertility=60,
        development=30,
        neighbors=["wancheng"],
    )
    jianye = Territory(
        id="jianye",
        name="建业",
        owner_id="wu",
        climate_zone="south",
        population=100000,
        fertility=70,
        development=55,
        neighbors=["wujun"],
    )
    wujun = Territory(
        id="wujun",
        name="吴郡",
        owner_id="wu",
        climate_zone="south",
        population=80000,
        fertility=75,
        development=40,
        neighbors=["jianye"],
    )
    yuzhang = Territory(
        id="yuzhang",
        name="豫章",
        owner_id="wu",
        climate_zone="south",
        population=60000,
        fertility=50,
        development=25,
        neighbors=["wujun"],
    )
    ws.territories = {
        "xuchang": xuchang,
        "wancheng": wancheng,
        "xinye": xinye,
        "jianye": jianye,
        "wujun": wujun,
        "yuzhang": yuzhang,
    }

    # Armies
    ws.armies = {
        "army_cao_1": Army(
            id="army_cao_1",
            faction_id="cao",
            location="wancheng",
            commander_id="caocao",
            morale=85,
            units={},
        ),
        "army_shu_1": Army(
            id="army_shu_1",
            faction_id="shu",
            location="xinye",
            commander_id="zhaoyun",
            morale=80,
            units={},
        ),
        "army_wu_1": Army(
            id="army_wu_1", faction_id="wu", location="jianye", commander_id="", morale=90, units={}
        ),
        "army_hidden": Army(
            id="army_hidden",
            faction_id="cao",
            location="xuchang",
            commander_id="simayi",
            morale=90,
            units={},
        ),
    }
    # Set troop counts
    ws.armies["army_cao_1"].units["infantry"] = 20000  # 20000 on border
    ws.armies["army_shu_1"].units["infantry"] = 5000
    ws.armies["army_wu_1"].units["infantry"] = 30000
    ws.armies["army_hidden"].units["infantry"] = 30000  # hidden in distant capital

    return ws


class TestLocalWorldStateProjector:
    """Tests for fog-of-war projection."""

    def setup_method(self):
        self.projector = LocalWorldStateProjector()

    def test_own_faction_full_visibility(self):
        """Own faction should see all its own data."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        assert local.my_treasury == 3000
        assert local.my_food == 2000
        assert local.my_strength == 5000
        assert local.my_economy == 30
        assert local.my_morale == 70
        assert "xinye" in local.my_territories
        assert len(local.my_characters) == 2  # zhugeliang, zhaoyun

    def test_border_faction_range_estimate(self):
        """Border faction should show range estimate."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        cao_view = local.perceived_factions.get("cao")
        assert cao_view is not None
        assert cao_view.is_border
        # 150000 ± 15% = 127500 ~ 172500
        assert "~" in cao_view.estimated_strength

    def test_distant_faction_vague_description(self):
        """Distant (non-border) faction should show vague description."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        wu_view = local.perceived_factions.get("wu")
        assert wu_view is not None
        assert not wu_view.is_border
        # Should be vague, not exact
        assert "数万" in wu_view.estimated_strength or "~" not in wu_view.estimated_strength

    def test_allied_faction_accurate(self):
        """Allied faction should show accurate numbers."""
        ws = make_multi_faction_world()
        # shu and wu are allies
        local = self.projector.project(ws, "shu")

        wu_view = local.perceived_factions.get("wu")
        assert wu_view is not None
        assert wu_view.is_allied
        assert wu_view.estimated_strength == "60,000"

    def test_hidden_armies_not_visible(self):
        """Armies in distant territories (non-border) should be hidden."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        # army_hidden is in xuchang (Cao's capital, not bordering Shu)
        assert "army_hidden" not in local.visible_armies

    def test_border_army_visible_with_fuzz(self):
        """Armies on border should be visible with estimate range."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        # army_cao_1 is in wancheng (border territory)
        assert "army_cao_1" in local.visible_armies
        assert "estimated_troops" in local.visible_armies["army_cao_1"]

    def test_own_army_visible_exact(self):
        """Own armies should show exact numbers."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        assert "army_shu_1" in local.visible_armies
        assert "troops" in local.visible_armies["army_shu_1"]

    def test_border_garrisons(self):
        """Border garrisons should have estimates."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        # wancheng borders xinye — should have garrison estimate
        assert "wancheng" in local.border_garrisons

    def test_ally_does_not_see_hidden_enemy_armies(self):
        """Even allies should not see non-border enemy armies."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "wu")

        # wu is allied with shu, but shouldn't see Cao's hidden army in xuchang
        assert "army_hidden" not in local.visible_armies
        # But should see shu's army (allied)
        assert "army_shu_1" in local.visible_armies


class TestProjectionCorrectness:
    """Verify that projection systematically hides correct information."""

    def setup_method(self):
        self.projector = LocalWorldStateProjector()

    def test_enemy_treasury_hidden(self):
        """Distant enemy's treasury should never be exposed."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        # Cao (border) and Wu (distant) — neither should expose treasury
        for pf in local.perceived_factions.values():
            # No treasury field in PerceivedFaction
            assert not hasattr(pf, "treasury")

    def test_enemy_food_hidden(self):
        """Distant enemy's food should never be exposed."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")

        for pf in local.perceived_factions.values():
            assert not hasattr(pf, "food")

    def test_serialization(self):
        """to_dict should produce valid structure."""
        ws = make_multi_faction_world()
        local = self.projector.project(ws, "shu")
        d = local.to_dict()

        assert "my" in d
        assert "perceived" in d
        assert "visible_armies" in d
        assert d["my"]["treasury"] == 3000
