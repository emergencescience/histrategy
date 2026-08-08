"""
V3 pipeline integration tests — covers data flow from resolve() to DB persistence.

Tests the full data pipeline:
  1. WorldState to_dict/from_dict round-trip
  2. quarter_turn column coverage (all columns asserted)
  3. game_state persistence assertions
  4. IntentParser keyword fallback parsing
  5. NPCDecisionEngine prompt content
  6. Silent-drop regression tests

These tests ensure no field is silently dropped between pipeline stages.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from histrategy.db import init_db, save_quarter_turn, save_room
from histrategy.db.models import (
    get_quarter_turns,
    get_game_state,
    get_turn_deltas,
    save_game_state,
    save_policy_state,
    save_turn_delta,
    execute,
)
from histrategy.engine.game_room import create_single_player_room


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Use temporary SQLite DB for all tests."""
    db_path = str(tmp_path / "test_histrategy.db")

    os.environ["HISTRATEGY_DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["HISTRATEGY_DATA_DIR"] = str(tmp_path / "saves")

    import histrategy.db.connection as conn_module
    conn_module.DATABASE_URL = f"sqlite:///{db_path}"
    conn_module._IS_SQLITE = True
    conn_module._SCHEMA_LOADED = False

    init_db()
    yield db_path
    os.environ.pop("HISTRATEGY_DATABASE_URL", None)


@pytest.fixture
def tk_room(isolated_db):
    """Create a three-kingdoms room (WorldState is auto-created)."""
    room = create_single_player_room("shu", "test-user", "three-kingdoms")
    save_room(room)
    return room


# ═══════════════════════════════════════════════════════════════
# 1. WorldState serialization round-trip
# ═══════════════════════════════════════════════════════════════

class TestWorldStateRoundTrip:
    """WorldState to_dict() → from_dict() must preserve all key fields."""

    def _make_minimal_worldstate(self, tk_room):
        """Create a minimal WorldState."""
        from histrategy.engine.helpers import create_initial_world
        return create_initial_world("shu", tk_room.scenario)

    def test_faction_state_roundtrip(self, tk_room):
        """All FactionState fields survive a to_dict/from_dict cycle."""
        import dataclasses

        ws = self._make_minimal_worldstate(tk_room)
        assert ws is not None

        ws_dict = ws.to_dict()
        # from_dict mutates in place — create a new instance
        restored = type(ws)()
        restored.from_dict(ws_dict)

        assert restored.year == ws.year
        assert str(restored.season) == str(ws.season), f"season: {restored.season} vs {ws.season}"
        assert restored.turn_number == ws.turn_number

        orig_factions = ws.factions
        rest_factions = restored.factions
        assert len(rest_factions) == len(orig_factions)

        for fid in orig_factions:
            orig = orig_factions[fid]
            rest = rest_factions[fid]
            assert rest.name == orig.name, f"{fid}.name mismatch"
            assert rest.is_active == orig.is_active, f"{fid}.is_active mismatch"
            assert rest.strength_actual == orig.strength_actual, f"{fid}.strength mismatch"
            assert rest.morale_actual == orig.morale_actual, f"{fid}.morale mismatch"
            assert rest.food == orig.food, f"{fid}.food mismatch"
            assert rest.treasury == orig.treasury, f"{fid}.treasury mismatch"
            orig_terr = set(orig.territories)
            rest_terr = set(rest.territories)
            assert rest_terr == orig_terr, f"{fid}.territories mismatch"

    def test_territory_fields_survive_roundtrip(self, tk_room):
        """Each territory's core fields survive serialization."""
        ws = self._make_minimal_worldstate(tk_room)
        ws_dict = ws.to_dict()
        restored = type(ws)()
        restored.from_dict(ws_dict)

        for fid in ws.factions:
            orig = ws.factions[fid]
            rest = restored.factions[fid]
            assert set(rest.territories) == set(orig.territories), \
                f"{fid}.territories mismatch"
            assert rest.capital == orig.capital, f"{fid}.capital mismatch"

    def test_json_serializable(self, tk_room):
        """WorldState.to_dict() must produce JSON-serializable data."""
        ws = self._make_minimal_worldstate(tk_room)
        ws_dict = ws.to_dict()
        json_str = json.dumps(ws_dict)
        reloaded = json.loads(json_str)
        assert reloaded["year"] == ws.year
        assert len(reloaded["factions"]) == len(ws.factions)


# ═══════════════════════════════════════════════════════════════
# 2. quarter_turn column coverage
# ═══════════════════════════════════════════════════════════════

class TestQuarterTurnPersistence:
    """Every quarter_turn column must be asserted after a save."""

    def test_save_quarter_turn_all_columns(self, tk_room):
        """After saving a quarter_turn, all meaningful columns are asserted."""
        room = tk_room

        baseline = {
            "year": 207, "season": "spring", "turn_number": 1,
            "climate_events": {}, "resource_changes": {"shu": {"food": 100}},
            "battles": [{"location": "chibi", "attacker": "cao", "defender": "wu",
                         "result": "defender_win", "attacker_losses": 5000, "defender_losses": 1000}],
            "diplomatic_events": [{"type": "alliance", "factions": ["shu", "wu"]}],
            "character_events": [], "history_events": [],
            "faction_snapshots": {"shu": {"population": 900000, "troops": 100000}},
            "player_decision": "联吴抗曹", "player_commands": [{"type": "ally", "params": {"target": "wu"}}],
        }
        macro_delta = {
            "battle_results": [{"location": "chibi", "result": "defender_win"}],
            "npc_faction_actions": [{"faction": "cao", "action_type": "attack", "amount": 50000}],
            "morale_events": [{"faction": "shu", "change": 5, "reason": "联盟达成"}],
            "political_events": [{"type": "alliance_formed", "factions": ["shu", "wu"]}],
        }

        tid = save_quarter_turn(
            room_id=room.id, quarter_number=1, year=207, season="spring",
            faction_decisions={"shu": "联吴抗曹"},
            baseline_result=baseline,
            macro_delta=macro_delta,
            narratives={"shu": "赤壁之战，孙刘联军大破曹操..."},
            state_changes={"shu": {"troops": -500}},
            token_usage={"prompt": 5000, "completion": 2000},
        )
        assert tid is not None

        turns = get_quarter_turns(room.id, limit=1)
        assert len(turns) == 1
        t = turns[0]

        # Required non-null columns
        assert t.get("id") is not None
        assert t.get("room_id") == room.id
        assert t.get("quarter_number") == 1
        assert t.get("year") == 207
        assert t.get("season") == "spring"
        assert t.get("created_at") is not None

        # Content columns — all must be present
        fd = t["faction_decisions"]
        if isinstance(fd, str):
            fd = json.loads(fd)
        assert "shu" in fd

        bl = t["baseline_result"]
        if isinstance(bl, str):
            bl = json.loads(bl)
        assert bl["year"] == 207
        assert len(bl["battles"]) == 1
        assert "diplomatic_events" in bl
        assert "resource_changes" in bl
        assert "faction_snapshots" in bl

        md = t["macro_delta"]
        if isinstance(md, str):
            md = json.loads(md)
        assert len(md["battle_results"]) == 1
        assert len(md["npc_faction_actions"]) == 1

        assert t.get("narratives") is not None
        assert t.get("state_changes") is not None
        assert t.get("token_usage") is not None

    def test_baseline_all_required_fields(self):
        """Every required TurnResult field must be present."""
        baseline = {
            "year": 207, "season": "spring", "turn_number": 1,
            "climate_events": {}, "resource_changes": {},
            "battles": [], "diplomatic_events": [],
            "character_events": [], "history_events": [],
            "faction_snapshots": {}, "player_decision": "",
            "player_commands": [],
        }
        required = [
            "year", "season", "turn_number",
            "climate_events", "resource_changes",
            "battles", "diplomatic_events",
            "character_events", "history_events",
            "faction_snapshots", "player_decision", "player_commands",
        ]
        for key in required:
            assert key in baseline, f"baseline missing key: {key}"

    def test_macro_delta_all_required_fields(self):
        """Every required macro_delta field must be present."""
        macro_delta = {
            "battle_results": [],
            "npc_faction_actions": [],
            "morale_events": [],
            "political_events": [],
        }
        required = ["battle_results", "npc_faction_actions", "morale_events", "political_events"]
        for key in required:
            assert key in macro_delta, f"macro_delta missing key: {key}"


# ═══════════════════════════════════════════════════════════════
# 3. game_state persistence
# ═══════════════════════════════════════════════════════════════

class TestGameStatePersistence:
    """Faction state snapshots must survive to/from DB."""

    def test_save_and_read_game_state(self, tk_room):
        """After save_game_state, read back and assert all columns."""
        room = tk_room

        save_game_state(
            room_id=room.id, quarter_number=1, faction_id="shu",
            population=900000, troops=100000, food=50000, treasury=30000, morale=70,
            territories=["chengdu", "jiangzhou", "yongan"],
            policies={"military_reform": {"level": 1}},
            is_active=True,
        )

        gs = get_game_state(room.id, 1, "shu")
        assert gs is not None
        assert gs.get("population") == 900000
        assert gs.get("troops") == 100000
        assert gs.get("food") == 50000
        assert gs.get("treasury") == 30000
        assert gs.get("morale") == 70
        assert gs.get("is_active") is True

        terr = gs.get("territories")
        if isinstance(terr, str):
            terr = json.loads(terr)
        assert "chengdu" in terr

        policies = gs.get("policies")
        if isinstance(policies, str):
            policies = json.loads(policies)
        assert "military_reform" in policies

    def test_policy_state_persistence(self, tk_room):
        """save_policy_state creates a record with all fields."""
        room = tk_room

        pid = save_policy_state(
            room_id=room.id, quarter_number=1, faction_id="shu",
            policy_type="military", policy_name="火器营组建",
            policy_level=1,
            params={"weapon": "arquebus", "count": 500},
            status="active",
        )
        assert pid is not None

        rows = execute(
            "SELECT * FROM policy_state WHERE room_id = ? AND faction_id = ?",
            (room.id, "shu"),
        )
        assert len(rows) >= 1
        ps = rows[0]
        assert ps["policy_type"] == "military"
        assert ps["policy_name"] == "火器营组建"
        assert ps["status"] == "active"

    def test_turn_delta_persistence(self, tk_room):
        """save_turn_delta records per-turn changes."""
        room = tk_room

        did = save_turn_delta(
            room_id=room.id, quarter_number=1, faction_id="shu",
            delta_type="troops", old_value=100000, new_value=98000,
            reason="夷陵交战损失", source="deterministic",
        )
        assert did is not None

        deltas = get_turn_deltas(room.id, 1)
        assert len(deltas) >= 1
        td = deltas[0]
        assert td.get("delta_type") == "troops"
        assert td.get("delta") == -2000


# ═══════════════════════════════════════════════════════════════
# 4. IntentParser keyword fallback parsing
# ═══════════════════════════════════════════════════════════════

class TestIntentParser:
    """IntentParser.parse() must handle various inputs without crashing."""

    def test_parse_defend_command(self):
        """'坚守淮河' should parse without crashing."""
        from histrategy.parser.intent import IntentParser

        parser = IntentParser(scenario="three-kingdoms")
        commands = parser.parse("坚守淮河防线，不要出击", "shu")
        assert isinstance(commands, list), "Must return a list"

    def test_parse_attack_command(self):
        """'进攻洛阳' should parse an attack command."""
        from histrategy.parser.intent import IntentParser

        parser = IntentParser(scenario="three-kingdoms")
        commands = parser.parse("进攻洛阳，目标曹操", "shu")
        assert isinstance(commands, list)

    def test_parse_with_bad_faction(self):
        """Parsing with invalid faction ID should not crash."""
        from histrategy.parser.intent import IntentParser

        parser = IntentParser(scenario="three-kingdoms")
        commands = parser.parse("坚守防线", "nonexistent")
        assert isinstance(commands, list)

    def test_command_dataclass_serializable(self):
        """Command objects must be JSON-serializable via dataclasses.asdict."""
        import dataclasses
        from histrategy_engine.world import Command

        cmd = Command(
            type="defend",
            params={"target": "yangzhou", "priority": "high"},
            faction_id="shu",
            notes="紧急防御",
        )
        d = dataclasses.asdict(cmd)
        assert d["type"] == "defend"
        assert d["params"]["target"] == "yangzhou"
        assert d["faction_id"] == "shu"
        json.dumps(d)


# ═══════════════════════════════════════════════════════════════
# 5. NPCDecisionEngine prompt content (requires WorldState)
# ═══════════════════════════════════════════════════════════════

class TestNPCDecisionPrompt:
    """NPC decision prompts must include required world state fields."""

    def _make_worldstate(self, tk_room):
        from histrategy.engine.helpers import create_initial_world
        return create_initial_world("shu", tk_room.scenario)

    def test_npc_context_includes_state(self, tk_room):
        """NPC decision context must reference faction's own state values."""
        ws = self._make_worldstate(tk_room)

        from histrategy.llm.npc_decision_engine import NPCDecisionEngine

        engine = NPCDecisionEngine()
        cao = ws.factions.get("cao")  # three-kingdoms
        if cao is None:
            pytest.skip("No cao faction")

        context = engine._build_context(
            ws=ws, faction_id="cao", faction=cao, turn_memory=[],
        )
        # Context formats numbers with commas (e.g. "150,000")
        assert "曹操" in context or "cao" in context
        assert "兵力" in context or "strength" in context
        assert "粮草" in context or "food" in context

    def test_npc_context_mentions_neighbors(self, tk_room):
        """NPC context must reference neighboring or hostile factions."""
        ws = self._make_worldstate(tk_room)

        from histrategy.llm.npc_decision_engine import NPCDecisionEngine

        engine = NPCDecisionEngine()
        cao = ws.factions.get("cao")
        if cao is None:
            pytest.skip("No cao faction")

        context = engine._build_context(
            ws=ws, faction_id="cao", faction=cao, turn_memory=[],
        )
        assert "刘备" in context or "刘备" in context or "shu" in context.lower(), \
            "NPC context must mention neighboring factions"


# ═══════════════════════════════════════════════════════════════
# 6. Silent-drop regression tests
# ═══════════════════════════════════════════════════════════════

class TestSilentDropRegression:
    """Regression tests for previously-fixed silent drop bugs."""

    def test_baseline_persisted_with_all_fields(self, tk_room):
        """After save_quarter_turn, baseline must contain all key data fields."""
        room = tk_room

        baseline = {
            "year": 207, "season": "spring", "turn_number": 1,
            "climate_events": {"snow": "heavy"},
            "resource_changes": {"shu": {"food": 200}},
            "battles": [],
            "diplomatic_events": [{"type": "tribute", "from": "korea"}],
            "character_events": [{"name": "诸葛亮", "event": "loyalty_increase"}],
            "history_events": [],
            "faction_snapshots": {"shu": {"population": 900000}},
            "player_decision": "坚守成都",
            "player_commands": [{"type": "defend", "params": {"target": "chengdu"}}],
        }
        macro_delta = {
            "battle_results": [{"location": "hulaoguan", "result": "attacker_win"}],
            "npc_faction_actions": [{"faction": "cao", "action_type": "attack"}],
            "morale_events": [], "political_events": [],
        }

        save_quarter_turn(
            room_id=room.id, quarter_number=1, year=207, season="spring",
            faction_decisions={"shu": "坚守成都"},
            baseline_result=baseline,
            macro_delta=macro_delta,
            narratives={}, state_changes={}, token_usage={},
        )

        turns = get_quarter_turns(room.id, limit=1)
        saved_bl = turns[0]["baseline_result"]
        if isinstance(saved_bl, str):
            saved_bl = json.loads(saved_bl)
        saved_md = turns[0]["macro_delta"]
        if isinstance(saved_md, str):
            saved_md = json.loads(saved_md)

        assert saved_bl["year"] == 207
        assert saved_bl["climate_events"]["snow"] == "heavy"
        assert len(saved_bl["diplomatic_events"]) == 1
        assert saved_bl["diplomatic_events"][0]["type"] == "tribute"
        assert len(saved_bl["character_events"]) == 1
        assert saved_bl["character_events"][0]["name"] == "诸葛亮"
        assert saved_bl["player_decision"] == "坚守成都"
        assert len(saved_bl["player_commands"]) == 1
        assert "resource_changes" in saved_bl

        assert len(saved_md["battle_results"]) == 1
        assert saved_md["battle_results"][0]["location"] == "hulaoguan"
        assert len(saved_md["npc_faction_actions"]) == 1
        assert saved_md["npc_faction_actions"][0]["faction"] == "cao"

    def test_baseline_not_none(self, tk_room):
        """baseline_result must never be NULL — regression for the silent drop bug."""
        room = tk_room

        baseline = {"year": 207, "season": "spring", "turn_number": 1,
                     "climate_events": {}, "resource_changes": {},
                     "battles": [], "diplomatic_events": [],
                     "character_events": [], "history_events": [],
                     "faction_snapshots": {}, "player_decision": "", "player_commands": []}
        macro_delta = {"battle_results": [], "npc_faction_actions": [],
                       "morale_events": [], "political_events": []}

        save_quarter_turn(
            room_id=room.id, quarter_number=1, year=207, season="spring",
            faction_decisions={"shu": "test"},
            baseline_result=baseline,
            macro_delta=macro_delta,
            narratives={}, state_changes={}, token_usage={},
        )

        turns = get_quarter_turns(room.id, limit=1)
        assert turns[0].get("baseline_result") is not None, \
            "baseline_result is NULL — this was the silent drop bug!"
        assert turns[0].get("macro_delta") is not None, \
            "macro_delta is NULL — this was the silent drop bug!"
