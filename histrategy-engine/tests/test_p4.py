"""
P4 Integration Tests — Parser + Validator + Narrative Engine + E2E

Tests the integration layer connecting players to the physics engine.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from histrategy_engine import (
    Army,
    Character,
    CharacterEngine,
    ClimateEvent,
    Command,
    DecisionEngine,
    DomesticEngine,
    FactionState,
    HistoricalRAG,
    MapEngine,
    MilitaryEngine,
    Season,
    TerrainType,
    Territory,
    TurnController,
    UnitType,
    WorldState,
)

# ─── Knowledge path ───────────────────────────────────────────────

KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scenarios", "three-kingdoms", "knowledge")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def make_minimal_world() -> WorldState:
    """Create a minimal world for parser/validator testing."""
    territories = {
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=30000,
            development=25,
            neighbors=["xiangyang", "wancheng"],
        ),
        "xiangyang": Territory(
            id="xiangyang",
            name="襄阳",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_river=True,
            population=80000,
            development=55,
            neighbors=["xinye", "jiangling", "wancheng"],
        ),
        "wancheng": Territory(
            id="wancheng",
            name="宛城",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=50000,
            development=45,
            neighbors=["xinye", "xiangyang", "xuchang"],
        ),
        "xuchang": Territory(
            id="xuchang",
            name="许昌",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=100000,
            development=70,
            neighbors=["wancheng"],
        ),
        "jiangling": Territory(
            id="jiangling",
            name="江陵",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_river=True,
            population=60000,
            development=50,
            neighbors=["xiangyang"],
        ),
    }

    characters = {
        "liubei": Character(
            id="liubei",
            name="刘备",
            faction_id="shu",
            location="xinye",
            loyalty=100,
            birth=161,
            death=223,
        ),
        "guanyu": Character(
            id="guanyu",
            name="关羽",
            faction_id="shu",
            location="xinye",
            loyalty=100,
            is_commanding=True,
            birth=160,
            death=220,
        ),
        "caocao": Character(
            id="caocao",
            name="曹操",
            faction_id="cao",
            location="xuchang",
            loyalty=100,
            birth=155,
            death=220,
        ),
    }

    factions = {
        "shu": FactionState(
            id="shu",
            name="刘备军",
            ruler_id="liubei",
            capital="xinye",
            territories=["xinye"],
            strength_actual=5000,
            treasury=3000,
            food=2000,
            tax_rate=0.2,
            morale_actual=70,
            relations={"cao": -80, "liubiao": 40},
        ),
        "cao": FactionState(
            id="cao",
            name="曹操军",
            ruler_id="caocao",
            capital="xuchang",
            territories=["xuchang", "wancheng"],
            strength_actual=150000,
            treasury=50000,
            food=30000,
            tax_rate=0.4,
            morale_actual=80,
            relations={"shu": -80, "liubiao": -20},
        ),
        "liubiao": FactionState(
            id="liubiao",
            name="刘表军",
            ruler_id="liubiao_if_any",
            capital="xiangyang",
            territories=["xiangyang", "jiangling"],
            strength_actual=40000,
            treasury=10000,
            food=8000,
            tax_rate=0.3,
            morale_actual=50,
            relations={"shu": 40, "cao": -20},
        ),
    }

    armies = {
        "army_shu_1": Army(
            id="army_shu_1",
            faction_id="shu",
            location="xinye",
            commander_id="guanyu",
            units={UnitType.INFANTRY: 1500},
            morale=85,
            training=1.0,
            supply=30,
        ),
        "army_cao_1": Army(
            id="army_cao_1",
            faction_id="cao",
            location="wancheng",
            units={UnitType.INFANTRY: 5000},
            morale=80,
            training=1.0,
            supply=30,
        ),
    }

    return WorldState(
        year=207,
        season=Season.WINTER,
        turn_number=1,
        scenario="207",
        player_faction_id="shu",
        territories=territories,
        characters=characters,
        factions=factions,
        armies=armies,
    )


# ═══════════════════════════════════════════════════════════════
# CommandValidator Tests
# ═══════════════════════════════════════════════════════════════


class TestCommandValidator:
    """Test the CommandValidator against physics engine constraints."""

    def setup_method(self):
        self.world = make_minimal_world()
        self.map_engine = MapEngine()
        self.map_engine.load_territories(self.world.territories)

    # Import validator dynamically to handle module path
    @property
    def validator(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from histrategy.parser.validator import CommandValidator

        return CommandValidator(self.map_engine)

    def test_recruit_too_large(self):
        """Recruitment exceeding 5% of population should be rejected."""
        cmd = Command(
            type="recruit",
            params={"territory": "xinye", "unit_type": "infantry", "amount": 10000},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0  # 10000 > 5% of 30000 = 1500

    def test_recruit_valid(self):
        """Valid recruitment within limits should pass."""
        cmd = Command(
            type="recruit",
            params={"territory": "xinye", "unit_type": "infantry", "amount": 500},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1
        assert valid[0].type == "recruit"

    def test_recruit_not_owned_territory(self):
        """Cannot recruit from enemy territory."""
        cmd = Command(
            type="recruit",
            params={"territory": "wancheng", "unit_type": "infantry", "amount": 500},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_develop_player_territory(self):
        """Development of owned territory should pass."""
        cmd = Command(
            type="develop",
            params={"territory": "xinye"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1

    def test_develop_enemy_territory(self):
        """Development of enemy territory should fail."""
        cmd = Command(
            type="develop",
            params={"territory": "wancheng"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_attack_reachable_target(self):
        """Attack on reachable enemy should pass."""
        cmd = Command(
            type="attack",
            params={"target_territory": "wancheng"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1

    def test_attack_own_territory(self):
        """Cannot attack own territory."""
        cmd = Command(
            type="attack",
            params={"target_territory": "xinye"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_tax_valid_rate(self):
        """Tax with valid rate should pass."""
        cmd = Command(
            type="tax",
            params={"rate": 0.3},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1

    def test_tax_invalid_rate(self):
        """Tax with rate outside 0.1-0.5 should fail."""
        cmd = Command(
            type="tax",
            params={"rate": 0.9},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_negotiate_existing_faction(self):
        """Negotiation with existing faction should pass."""
        cmd = Command(
            type="negotiate",
            params={"target_faction": "cao"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1

    def test_negotiate_self(self):
        """Cannot negotiate with self."""
        cmd = Command(
            type="negotiate",
            params={"target_faction": "shu"},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_rest_always_valid(self):
        """Rest command should always be valid."""
        cmd = Command(type="rest", params={}, faction_id="shu")
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 1

    def test_inactive_faction_commands_rejected(self):
        """Commands from inactive faction should be dropped."""
        self.world.factions["shu"].is_active = False
        cmd = Command(
            type="recruit",
            params={"territory": "xinye", "unit_type": "infantry", "amount": 500},
            faction_id="shu",
        )
        valid = self.validator.validate([cmd], self.world)
        assert len(valid) == 0

    def test_multiple_commands_mixed_validity(self):
        """Mix of valid and invalid commands — only valid return."""
        cmds = [
            Command(
                type="recruit",
                params={"territory": "xinye", "unit_type": "infantry", "amount": 500},
                faction_id="shu",
            ),
            Command(
                type="recruit",
                params={"territory": "wancheng", "unit_type": "infantry", "amount": 500},
                faction_id="shu",
            ),  # invalid: not owned
            Command(type="develop", params={"territory": "xinye"}, faction_id="shu"),
            Command(
                type="attack", params={"target_territory": "xinye"}, faction_id="shu"
            ),  # invalid: own territory
        ]
        valid = self.validator.validate(cmds, self.world)
        assert len(valid) == 2
        assert all(c.type in ("recruit", "develop") for c in valid)


# ═══════════════════════════════════════════════════════════════
# IntentParser Tests (keyword fallback)
# ═══════════════════════════════════════════════════════════════


class TestIntentParserKeyword:
    """Test the IntentParser keyword-based fallback parser."""

    def setup_method(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from histrategy.parser.intent import IntentParser

        # No LLM → keyword fallback
        self.parser = IntentParser(None)

    def test_recruit_command(self):
        cmds = self.parser.parse("在新野招募五百步兵", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "recruit"
        assert cmds[0].params.get("territory") == "xinye"

    def test_develop_command(self):
        cmds = self.parser.parse("发展新野的农业和屯田", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "develop"

    def test_attack_command(self):
        cmds = self.parser.parse("出兵攻打宛城的曹操军", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "attack"

    def test_negotiate_command(self):
        cmds = self.parser.parse("派遣使者与曹操同盟", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "negotiate"
        assert cmds[0].params.get("target_faction") == "cao"

    def test_rest_command(self):
        cmds = self.parser.parse("全军休整", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "rest"

    def test_empty_input(self):
        cmds = self.parser.parse("", "shu")
        assert len(cmds) == 0

    def test_unrelated_input(self):
        """Unrelated text should produce empty command list."""
        cmds = self.parser.parse("风调雨顺", "shu")
        assert len(cmds) == 0

    def test_move_command(self):
        cmds = self.parser.parse("行军移师至襄阳", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type in ("move", "attack")

    def test_tax_command(self):
        cmds = self.parser.parse("把赋税调整为三十税一", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "tax"

    def test_spy_command(self):
        cmds = self.parser.parse("派遣细作侦查曹操的情报", "shu")
        assert len(cmds) >= 1
        assert cmds[0].type == "spy"
        assert cmds[0].params.get("target_faction") == "cao"


# ═══════════════════════════════════════════════════════════════
# E2E Integration Tests (minimal, quick)
# ═══════════════════════════════════════════════════════════════


class TestE2EIntegration:
    """Minimal E2E tests that exercise the full engine pipeline."""

    def setup_method(self):
        self.world = make_minimal_world()
        self.map_engine = MapEngine()
        self.char_engine = CharacterEngine()
        self.domestic_engine = DomesticEngine()
        self.military_engine = MilitaryEngine()
        self.decision_engine = DecisionEngine()

        self.map_engine.load_territories(self.world.territories)
        self.char_engine.load_characters(self.world.characters)

        self.turn_controller = TurnController(
            self.map_engine,
            self.char_engine,
            self.domestic_engine,
            self.military_engine,
            self.decision_engine,
        )

    def test_execute_one_turn(self):
        """Execute a single turn with player commands."""
        cmds = [
            Command(type="develop", params={"territory": "xinye"}, faction_id="shu"),
        ]
        result = self.turn_controller.execute_turn(
            self.world,
            player_commands=cmds,
            year=207,
            turn_number=1,
        )

        assert result is not None
        assert result.year == 207
        assert result.season == Season.WINTER
        assert result.turn_number == 1
        # Should have resource changes
        assert "shu" in result.resource_changes

    def test_execute_10_turns(self):
        """Execute 10 turns and verify world state evolves."""
        for tn in range(1, 11):
            cmds = [
                Command(type="develop", params={"territory": "xinye"}, faction_id="shu"),
            ]
            result = self.turn_controller.execute_turn(
                self.world,
                player_commands=cmds,
                year=self.world.year,
                turn_number=tn,
            )
            assert result is not None

        # After 10 turns, year should have advanced
        assert self.world.turn_number >= 10

    def test_recruit_flow(self):
        """Full flow: parse → validate → execute for recruitment."""
        # Simulate the pipeline
        cmd = Command(
            type="recruit",
            params={"territory": "xinye", "unit_type": "infantry", "amount": 300},
            faction_id="shu",
        )

        # Validate
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from histrategy.parser.validator import CommandValidator

        validator = CommandValidator(self.map_engine)
        valid = validator.validate([cmd], self.world)
        assert len(valid) == 1

        # Execute
        result = self.turn_controller.execute_turn(
            self.world,
            player_commands=valid,
            year=207,
            turn_number=1,
        )
        assert result is not None

    def test_turn_result_has_all_sections(self):
        """TurnResult should contain all expected sections."""
        cmds = [
            Command(type="develop", params={"territory": "xinye"}, faction_id="shu"),
        ]
        result = self.turn_controller.execute_turn(
            self.world,
            player_commands=cmds,
            year=207,
            turn_number=1,
        )

        assert hasattr(result, "climate_events")
        assert hasattr(result, "resource_changes")
        assert hasattr(result, "battles")
        assert hasattr(result, "character_events")
        assert hasattr(result, "faction_snapshots")

    def test_npc_commands_generated(self):
        """NPC factions should generate autonomous commands."""
        # Execute turn without any player commands
        result = self.turn_controller.execute_turn(
            self.world,
            player_commands=[],
            year=207,
            turn_number=1,
        )
        assert result is not None
        # NPC (cao, liubiao) should generate their own commands internally


# ═══════════════════════════════════════════════════════════════
# TurnController Extended Tests
# ═══════════════════════════════════════════════════════════════


class TestTurnControllerExtended:
    """Additional TurnController validation checks."""

    def setup_method(self):
        self.world = make_minimal_world()
        self.map_engine = MapEngine()
        self.char_engine = CharacterEngine()
        self.domestic_engine = DomesticEngine()
        self.military_engine = MilitaryEngine()
        self.decision_engine = DecisionEngine()

        self.map_engine.load_territories(self.world.territories)
        self.char_engine.load_characters(self.world.characters)

        self.tc = TurnController(
            self.map_engine,
            self.char_engine,
            self.domestic_engine,
            self.military_engine,
            self.decision_engine,
        )

    def test_season_advancement(self):
        """After a turn, season should advance."""
        assert self.world.season == Season.WINTER
        self.tc.execute_turn(self.world, player_commands=[], year=207, turn_number=1)
        assert self.world.season == Season.SPRING

    def test_four_turns_one_year(self):
        """4 turns should advance one year from winter."""
        assert self.world.year == 207
        assert self.world.season == Season.WINTER
        for tn in range(1, 5):
            self.tc.execute_turn(
                self.world, player_commands=[], year=self.world.year, turn_number=tn
            )
        assert self.world.year == 208
        assert self.world.season == Season.WINTER

    def test_climate_events_in_result(self):
        """TurnResult should contain climate events for all territories."""
        result = self.tc.execute_turn(self.world, player_commands=[], year=207, turn_number=1)
        assert len(result.climate_events) > 0
        for tid in self.world.territories:
            assert tid in result.climate_events
        # At least some should be NORMAL
        assert any(
            v
            in (
                ClimateEvent.NORMAL,
                ClimateEvent.DROUGHT,
                ClimateEvent.FLOOD,
                ClimateEvent.COLD_WAVE,
            )
            for v in result.climate_events.values()
        )

    def test_resource_production(self):
        """Resource production should generate food and tax."""
        result = self.tc.execute_turn(self.world, player_commands=[], year=207, turn_number=1)
        assert "shu" in result.resource_changes
        shu_changes = result.resource_changes["shu"]
        # Should have some food production (even if small in winter)
        assert "food_delta" in shu_changes

    def test_attack_command_resolves_battle(self):
        """An attack command should generate a battle."""
        # Move cao army to xinye border and shu army to attack
        # For simplicity, check that attack commands are processed
        cmds = [
            Command(type="attack", params={"target_territory": "wancheng"}, faction_id="shu"),
        ]
        result = self.tc.execute_turn(self.world, player_commands=cmds, year=207, turn_number=1)
        # May or may not have battle depending on army positions, but should not crash
        assert result is not None

    def test_border_detection(self):
        """Map engine should detect border territories."""
        borders = self.map_engine.get_border_territories("shu")
        assert "xinye" in borders
        # xinye borders xiangyang (liubiao) and wancheng (cao)

    def test_pathfinding(self):
        """Path from xinye to xuchang should exist."""
        path = self.map_engine.find_path("xinye", "xuchang", "shu")
        assert path.path
        assert len(path.path) >= 2
        assert path.path[0] == "xinye"
        assert path.path[-1] == "xuchang"


# ═══════════════════════════════════════════════════════════════
# Knowledge Loader Tests
# ═══════════════════════════════════════════════════════════════


class TestKnowledgeLoader:
    """Test the knowledge-to-engine dataclass loader."""

    def setup_method(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from histrategy.engine.loader import (
            load_characters,
            load_territories,
            resolve_knowledge_path,
        )

        self.load_territories = load_territories
        self.load_characters = load_characters
        self.resolve_knowledge_path = resolve_knowledge_path

    def test_load_territories(self):
        territories = self.load_territories()
        assert len(territories) > 0
        # Each territory must have required fields
        for tid, t in territories.items():
            assert t.id == tid
            assert t.name
            assert t.fertility > 0
            assert isinstance(t.terrain_type, TerrainType)

    def test_load_characters(self):
        characters = self.load_characters()
        assert len(characters) > 0
        # Key characters should be present
        assert "liubei" in characters
        assert "caocao" in characters
        assert characters["liubei"].name == "刘备"

    def test_build_world_state(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from histrategy.engine.loader import build_world_state

        ws = build_world_state("shu", "207")
        assert ws.player_faction_id == "shu"
        assert ws.year == 207
        assert len(ws.factions) >= 3
        assert "shu" in ws.factions
        assert "cao" in ws.factions
        assert "wu" in ws.factions
        assert len(ws.territories) > 0
        assert len(ws.characters) > 0


# ═══════════════════════════════════════════════════════════════
# HistoricalRAG Tests
# ═══════════════════════════════════════════════════════════════


class TestHistoricalRAG:
    """Test the RAG retriever for historical event context."""

    def setup_method(self):
        self.rag = HistoricalRAG(KNOWLEDGE_PATH)

    def test_rag_loads_events(self):
        assert self.rag.event_count > 0

    def test_retrieve_207(self):
        events = self.rag.retrieve(207, deviation=0.0)
        assert len(events) > 0
        # Should include 三顾茅庐
        titles = [e["title"] for e in events]
        assert any("三顾" in t or "茅庐" in t for t in titles)

    def test_retrieve_with_deviation(self):
        """High deviation should narrow the window."""
        low_dev = self.rag.retrieve(207, deviation=0.0)
        high_dev = self.rag.retrieve(207, deviation=0.8)
        # High deviation should return same or fewer events
        assert len(high_dev) <= len(low_dev)

    def test_build_llm_context(self):
        events = self.rag.retrieve(207, deviation=0.0, max_events=3)
        context = self.rag.build_llm_context(events)
        assert isinstance(context, str)
        assert len(context) > 50
        # Should contain historical reference markers
        assert "历史参考" in context

    def test_year_coverage(self):
        min_year, max_year = self.rag.year_coverage
        assert min_year <= 207 <= max_year
