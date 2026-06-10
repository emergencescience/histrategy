"""Tests for SabotageEngine — assassinate and bribe commands."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from histrategy_engine.military.sabotage import (
    SabotageEngine,
    SabotageType,
)
from histrategy_engine.world import (
    Army,
    Character,
    FactionState,
    Territory,
    WorldState,
)


def make_test_world() -> WorldState:
    """Create a minimal WorldState with two factions and characters."""
    ws = WorldState()

    cao = FactionState(
        id="cao",
        name="曹操军",
        ruler_id="caocao",
        capital="xuchang",
        territories=["xuchang"],
        treasury=50000,
        food=30000,
        legitimacy=50,
    )
    cao.tax_rate = 0.3

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

    ws.factions = {"cao": cao, "shu": shu}
    ws.player_faction_id = "cao"

    zhugeliang = Character(
        id="zhugeliang",
        name="诸葛亮",
        faction_id="shu",
        loyalty=95,
        politics=98,
        leadership=92,
        intelligence=100,
    )
    guanyu = Character(
        id="guanyu",
        name="关羽",
        faction_id="shu",
        loyalty=98,
        politics=60,
        leadership=95,
        intelligence=75,
    )
    fazheng = Character(
        id="fazheng",
        name="法正",
        faction_id="shu",
        loyalty=50,
        politics=85,
        leadership=60,
        intelligence=88,
    )
    caocao_char = Character(
        id="caocao",
        name="曹操",
        faction_id="cao",
        loyalty=100,
        politics=95,
        leadership=98,
        intelligence=96,
    )

    ws.characters = {
        "zhugeliang": zhugeliang,
        "guanyu": guanyu,
        "fazheng": fazheng,
        "caocao": caocao_char,
    }

    ws.armies = {
        "army_shu_1": Army(
            id="army_shu_1",
            faction_id="shu",
            location="xinye",
            commander_id="zhugeliang",
            morale=80,
        ),
        "army_shu_2": Army(
            id="army_shu_2",
            faction_id="shu",
            location="xinye",
            commander_id="guanyu",
            morale=95,
        ),
    }

    ws.territories = {
        "xuchang": Territory(
            id="xuchang",
            name="许昌",
            owner_id="cao",
            climate_zone="central",
            population=200000,
            fertility=80,
            development=50,
        ),
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            climate_zone="central",
            population=30000,
            fertility=60,
            development=30,
        ),
    }

    return ws


class TestSabotageEngine:
    """Tests for SabotageEngine."""

    def setup_method(self):
        self.engine = SabotageEngine()
        self.rng = random.Random(42)

    def test_assassinate_low_loyalty_high_probability(self):
        """Low loyalty target should have high assassination success probability."""
        ws = make_test_world()
        # shu faction has default caution=0.5
        prob = self.engine._calculate_probability(
            ws.characters["fazheng"],
            SabotageType.ASSASSINATE,
            faction_caution=ws.factions["shu"].caution,
        )
        # loyalty=50: loyalty_mod=+0.30, caution=0.5: -0.15, politics=85: -0.085
        # base 0.15 + 0.30 - 0.15 - 0.085 = 0.215
        assert 0.15 < prob < 0.35

    def test_assassinate_high_loyalty_low_probability(self):
        """Very loyal target should be nearly impossible to assassinate."""
        ws = make_test_world()
        prob = self.engine._calculate_probability(
            ws.characters["zhugeliang"],
            SabotageType.ASSASSINATE,
            faction_caution=ws.factions["shu"].caution,
        )
        # loyalty=95: -0.15, caution=0.5: -0.15, politics=98: -0.098
        # base 0.15 - 0.15 - 0.15 - 0.098 = -0.248 → clamped to 0.01
        assert prob == 0.01

    def test_assassinate_cannot_target_own_faction(self):
        ws = make_test_world()
        result = self.engine.attempt_assassinate("cao", "caocao", ws, rng=self.rng)
        assert not result.success
        assert "己方武将" in result.effect_description

    def test_assassinate_missing_target(self):
        ws = make_test_world()
        result = self.engine.attempt_assassinate("cao", "nonexistent", ws, rng=self.rng)
        assert not result.success
        assert "不存在" in result.effect_description

    def test_assassinate_makes_character_dead(self):
        """A successful assassination kills the target."""
        ws = make_test_world()
        # Make target extremely vulnerable: set faction caution to 0
        ws.factions["shu"].caution = 0.0
        ws.characters["fazheng"].loyalty = 0
        self.rng = random.Random(42)

        result = self.engine.attempt_assassinate("cao", "fazheng", ws, rng=self.rng)
        if result.success:
            assert not ws.characters["fazheng"].alive
            assert "暗杀身亡" in result.effect_description

    def test_assassinate_halves_army_morale(self):
        """On successful assassination, commander's army morale is halved."""
        ws = make_test_world()
        ws.factions["shu"].caution = 0.0
        ws.characters["guanyu"].loyalty = 0
        self.rng = random.Random(42)

        result = self.engine.attempt_assassinate("cao", "guanyu", ws, rng=self.rng)
        if result.success:
            army = ws.armies["army_shu_2"]
            assert army.morale <= 48  # 95 * 0.5 = 47
            assert army.commander_id == ""

    def test_bribe_high_loyalty_low_probability(self):
        ws = make_test_world()
        prob = self.engine._calculate_probability(
            ws.characters["guanyu"],
            SabotageType.BRIBE,
            faction_caution=ws.factions["shu"].caution,
        )
        assert prob == 0.01

    def test_bribe_moderate_loyalty(self):
        ws = make_test_world()
        prob = self.engine._calculate_probability(
            ws.characters["fazheng"],
            SabotageType.BRIBE,
            faction_caution=ws.factions["shu"].caution,
        )
        assert 0.5 < prob < 0.7

    def test_bribe_defection(self):
        """On successful bribe, character switches factions."""
        ws = make_test_world()
        ws.factions["shu"].caution = 0.0
        ws.characters["fazheng"].loyalty = 10
        self.rng = random.Random(42)

        result = self.engine.attempt_bribe("cao", "fazheng", ws, rng=self.rng)
        if result.success:
            assert ws.characters["fazheng"].faction_id == "cao"
            assert result.character_defected
            assert result.new_faction_id == "cao"
            assert "策反" in result.effect_description

    def test_probability_bounds(self):
        """Probabilities should always be between 0.01 and 0.80."""
        ws = make_test_world()
        for sab_type in (SabotageType.ASSASSINATE, SabotageType.BRIBE):
            for loy in range(0, 101, 25):
                char = Character(id="test", name="Test", faction_id="shu", loyalty=loy, politics=50)
                prob = self.engine._calculate_probability(char, sab_type, faction_caution=0.5)
                assert 0.01 <= prob <= 0.80, f"{sab_type} loy={loy}: {prob}"

    def test_cost(self):
        engine = SabotageEngine()
        assert engine.get_cost(SabotageType.ASSASSINATE) == 800
        assert engine.get_cost(SabotageType.BRIBE) == 1200
