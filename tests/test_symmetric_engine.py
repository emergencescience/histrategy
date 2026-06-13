"""
E2E tests for symmetric multiplayer engine.
Tests FactionSlot, GameRoom, DecisionBus, and DB persistence
without requiring LLM API keys (uses heuristic fallback paths).
"""

import pytest

from histrategy.db import init_db, load_room, save_quarter_turn, save_room
from histrategy.engine.decision_bus import DecisionResult
from histrategy.engine.faction_slot import (
    FactionSlot,
    OccupantType,
    create_ai_slot,
    create_human_slot,
    create_open_slot,
)
from histrategy.engine.game_room import (
    GameRoom,
    RoomPhase,
    create_multi_player_room,
    create_single_player_room,
)


class TestFactionSlot:
    """Test FactionSlot data model."""

    def test_create_human_slot(self):
        slot = create_human_slot("cao", "user-1")
        assert slot.faction_id == "cao"
        assert slot.occupant_type == OccupantType.HUMAN
        assert slot.occupant_id == "user-1"
        assert slot.is_human()
        assert not slot.is_ai()
        assert not slot.is_open()
        assert not slot.has_submitted()

    def test_create_ai_slot(self):
        slot = create_ai_slot("wu", temperature=0.9)
        assert slot.faction_id == "wu"
        assert slot.occupant_type == OccupantType.AI_NPC
        assert slot.occupant_id is None
        assert slot.is_ai()
        assert not slot.is_human()
        assert slot.ai_temperature == 0.9
        assert not slot.has_submitted()

    def test_create_open_slot(self):
        slot = create_open_slot("shu")
        assert slot.faction_id == "shu"
        assert slot.occupant_type == OccupantType.OPEN
        assert slot.is_open()
        assert not slot.is_human()
        assert not slot.is_ai()

    def test_submit_and_clear_decision(self):
        slot = create_human_slot("cao", "user-1")
        slot.submit_decision("北伐中原，收复汉室！", [{"type": "attack", "params": {}}])
        assert slot.has_submitted()
        assert slot.pending_decision == "北伐中原，收复汉室！"
        assert len(slot.pending_commands) == 1

        slot.clear_decision()
        assert not slot.has_submitted()
        assert slot.pending_decision is None
        assert slot.pending_commands is None

    def test_serialization_roundtrip(self):
        slot = create_ai_slot("shu", temperature=0.5)
        slot.submit_decision("休整观望")
        d = slot.to_dict()
        restored = FactionSlot.from_dict(d)
        assert restored.faction_id == "shu"
        assert restored.occupant_type == OccupantType.AI_NPC
        assert restored.ai_temperature == 0.5
        # pending_decision is NOT restored from from_dict (cleared after quarter)

    def test_repr(self):
        slot = create_human_slot("cao", "user-1")
        r = repr(slot)
        assert "cao" in r
        assert "human" in r


class TestGameRoom:
    """Test GameRoom data model."""

    def test_create_single_player_room(self):
        room = create_single_player_room("cao", "test-user")
        assert room.phase == RoomPhase.WAITING
        assert len(room.slots) == 3  # 3 major factions (no minor NPCs)
        assert len(room.human_slots()) == 1
        assert len(room.ai_slots()) == 2
        assert len(room.major_ai_slots()) == 2  # wu, shu
        assert len(room.minor_ai_slots()) == 0  # no minor factions

    def test_create_multi_player_room(self):
        room = create_multi_player_room("host-1", ["cao", "shu"])
        assert room.phase == RoomPhase.LOBBY
        assert room.host_user_id == "host-1"
        assert len(room.slots) == 3
        # cao and shu are OPEN, rest are AI
        assert room.slots["cao"].is_open()
        assert room.slots["shu"].is_open()
        assert room.slots["wu"].is_ai()

    def test_all_slots_submitted(self):
        room = create_single_player_room("cao", "test-user")
        assert not room.all_slots_submitted()

        # Submit all decisions
        for slot in room.slots.values():
            slot.submit_decision("test decision")

        assert room.all_slots_submitted()

    def test_pending_slots(self):
        room = create_single_player_room("cao", "test-user")
        pending = room.pending_slots()
        assert len(pending) == 3  # 3 factions

        room.slots["cao"].submit_decision("test")
        pending = room.pending_slots()
        assert len(pending) == 2
        assert "cao" not in pending

    def test_advance_quarter(self):
        room = create_single_player_room("cao", "test-user")
        # Submit all
        for slot in room.slots.values():
            slot.submit_decision("test")
        assert room.all_slots_submitted()

        room.advance_quarter()
        assert room.quarter_number == 1
        assert room.phase == RoomPhase.WAITING
        assert not room.all_slots_submitted()  # all cleared

    def test_start_game_idempotent(self):
        room = create_multi_player_room("host", ["cao"])
        assert room.phase == RoomPhase.LOBBY
        room.start_game()
        assert room.phase == RoomPhase.WAITING
        room.start_game()  # idempotent
        assert room.phase == RoomPhase.WAITING

    def test_active_slots(self):
        room = create_single_player_room("cao", "test-user")
        assert len(room.active_slots()) == 3
        assert len(room.active_slots()) == 3

    def test_has_human_player(self):
        room = create_single_player_room("cao", "test-user")
        assert room.has_human_player()

        room = GameRoom(id="no-human")
        assert not room.has_human_player()

    def test_serialization_roundtrip(self):
        room = create_single_player_room("cao", "test-user")
        d = room.to_dict()
        restored = GameRoom.from_dict(d)
        assert restored.id == room.id
        assert restored.scenario == room.scenario
        assert restored.phase == room.phase
        assert len(restored.slots) == len(room.slots)

    def test_repr(self):
        room = create_single_player_room("cao", "test-user")
        r = repr(room)
        assert "GameRoom" in r
        assert "waiting" in r


class TestDecisionBus:
    """Test DecisionBus and DecisionResult."""

    def test_decision_result_creation(self):
        dr = DecisionResult("cao", "北伐", source="human", latency_ms=100)
        assert dr.faction_id == "cao"
        assert dr.decision_text == "北伐"
        assert dr.source == "human"
        assert dr.latency_ms == 100
        assert dr.error is None

    def test_decision_result_error(self):
        dr = DecisionResult("wu", "", source="heuristic_fallback", error="LLM timeout")
        assert dr.error == "LLM timeout"
        assert dr.decision_text == ""

    def test_decision_result_repr(self):
        dr = DecisionResult("shu", "休整", source="heuristic")
        r = repr(dr)
        assert "shu" in r
        assert "heuristic" in r

    def test_heuristic_decision_generation(self):
        """Verify heuristic fallback produces string output."""
        from histrategy.engine.decision_bus import _generate_heuristic_decision as gen

        # Create a minimal mock world state
        class MockFaction:
            def __init__(self):
                self.name = "测试"
                self.is_active = True
                self.treasury = 10000
                self.food = 5000
                self.territories = ["test_city"]
                self.capital = "test_city"
                self.tax_rate = 0.3
                self.relations = {}
                self.strength_actual = 5000

        class MockWS:
            def __init__(self):
                self.factions = {"test": MockFaction()}
                self.territories = {}

        ws = MockWS()
        decision, commands = gen(ws, "test")
        assert isinstance(decision, str) and len(decision) > 0
        assert isinstance(commands, list)


class TestDBPersistence:
    """Test SQLite persistence layer."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Use isolated DB for each test."""
        import os

        db_path = str(tmp_path / "test_histrategy.db")
        os.environ["HISTRATEGY_DATABASE_URL"] = f"sqlite:///{db_path}"

        # Re-import to pick up new URL
        import histrategy.db.connection as conn_module

        conn_module.DATABASE_URL = f"sqlite:///{db_path}"
        conn_module._IS_SQLITE = True
        conn_module._SCHEMA_LOADED = False

        init_db()
        yield
        # Cleanup
        os.environ.pop("HISTRATEGY_DATABASE_URL", None)

    def test_save_and_load_room(self):
        room = create_single_player_room("shu", "test-user-persist")
        room.quarter_number = 3
        room.turn_summaries = [{"summary": "test quarter"}]

        save_room(room)
        loaded = load_room(room.id)

        assert loaded is not None
        assert loaded.id == room.id
        assert loaded.quarter_number == 3
        assert len(loaded.slots) == 3
        assert loaded.turn_summaries == [{"summary": "test quarter"}]
        assert loaded.slots["shu"].is_human()
        assert loaded.slots["cao"].is_ai()

    def test_load_nonexistent_room(self):
        loaded = load_room("nonexistent-id")
        assert loaded is None

    def test_save_room_updates_existing(self):
        room = create_single_player_room("cao", "test-user")
        save_room(room)

        # Update and save again
        room.quarter_number = 5
        room.turn_summaries = [{"q": 1}, {"q": 2}]
        save_room(room)

        loaded = load_room(room.id)
        assert loaded is not None
        assert loaded.quarter_number == 5
        assert len(loaded.turn_summaries) == 2

    def test_save_quarter_turn(self):
        room = create_single_player_room("cao", "test-user")
        save_room(room)

        tid = save_quarter_turn(
            room.id,
            quarter_number=1,
            year=208,
            season="夏",
            faction_decisions={"cao": {"decision": "南征", "commands": []}},
            token_usage={"npc_cao": 500},
        )
        assert tid is not None
        assert len(tid) > 0

    def test_save_room_with_world_state(self):
        room = create_single_player_room("wu", "test-user")
        ws_dict = {"year": 207, "season": "春", "factions": {}}
        save_room(room, world_state_dict=ws_dict)

        from histrategy.db.models import load_world_state_dict

        loaded_ws = load_world_state_dict(room.id)
        assert loaded_ws is not None
        assert loaded_ws["year"] == 207



class TestNPCTriggerDecisions:
    """Test _trigger_npc_decisions behavior across round transitions."""

    @staticmethod
    def _make_mock_world_state(factions_data: dict[str, dict] | None = None):
        """Create a mock world state sufficient for heuristic NPC decisions."""

        class MockFaction:
            def __init__(self, name, **kwargs):
                self.name = name
                self.is_active = kwargs.get("is_active", True)
                self.strength_actual = kwargs.get("strength", 10000)
                self.treasury = kwargs.get("treasury", 8000)
                self.food = kwargs.get("food", 5000)
                self.territories = kwargs.get("territories", ["capital_city"])
                self.capital = kwargs.get("capital", "capital_city")
                self.tax_rate = kwargs.get("tax_rate", 0.3)
                self.relations = {}

        class MockWS:
            def __init__(self, factions):
                self.factions = factions
                self.territories = {}
                self.year = 207
                self.season = "春"

        if factions_data is None:
            factions_data = {
                "cao": {"name": "曹操", "strength": 50000},
                "wu": {"name": "孙权", "strength": 30000},
                "shu": {"name": "刘备", "strength": 15000},
            }
        return MockWS({fid: MockFaction(**data) for fid, data in factions_data.items()})

    def test_trigger_generates_decisions_for_ai_slots(self):
        """After _trigger_npc_decisions, all AI slots should have pending decisions."""
        room = create_single_player_room("cao", "test-user")
        room.world_state = self._make_mock_world_state()

        # Initially no AI slots have submitted
        for slot in room.ai_slots():
            assert not slot.has_submitted(), f"AI slot {slot.faction_id} should start unsubmitted"

        # Trigger NPC decisions
        from histrategy.server.room_manager import _trigger_npc_decisions
        _trigger_npc_decisions(room)

        # All AI slots should now have submitted decisions
        ai_slots = room.ai_slots()
        assert len(ai_slots) > 0, "Room should have AI slots"
        for slot in ai_slots:
            assert slot.has_submitted(), f"AI slot {slot.faction_id} should have pending_decision after trigger"
            assert isinstance(slot.pending_decision, str) and len(slot.pending_decision) > 0

    def test_no_ai_slots_returns_early(self):
        """If all slots are human, _trigger_npc_decisions should return without error."""
        room = GameRoom(id="all-human", phase=RoomPhase.WAITING)
        room.slots["cao"] = create_human_slot("cao", "p1")
        room.slots["shu"] = create_human_slot("shu", "p2")
        room.slots["wu"] = create_human_slot("wu", "p3")
        room.world_state = self._make_mock_world_state()

        # Should not raise
        from histrategy.server.room_manager import _trigger_npc_decisions
        _trigger_npc_decisions(room)
        # All human — nothing should have been submitted
        for slot in room.slots.values():
            assert not slot.has_submitted()

    def test_advance_quarter_clears_then_trigger_regenerates(self):
        """After advance_quarter clears decisions, _trigger_npc_decisions regenerates fresh ones."""
        room = create_single_player_room("cao", "test-user")
        room.world_state = self._make_mock_world_state()

        from histrategy.server.room_manager import _trigger_npc_decisions
        _trigger_npc_decisions(room)

        # Record first round decisions
        first_decisions = {
            fid: slot.pending_decision
            for fid, slot in room.slots.items() if slot.is_ai()
        }
        assert len(first_decisions) == 2  # shu, wu

        # Advance quarter — should clear ALL decisions
        room.advance_quarter()
        assert room.quarter_number == 1
        for slot in room.slots.values():
            assert not slot.has_submitted(), f"Slot {slot.faction_id} should be cleared after advance_quarter"

        # Re-trigger for next round
        _trigger_npc_decisions(room)
        for slot in room.ai_slots():
            assert slot.has_submitted(), f"AI slot {slot.faction_id} should have new decision for Q{room.quarter_number}"
            # Decision may be the same (heuristic is deterministic) — that's fine
            # The important thing is that it was regenerated

    def test_trigger_without_world_state_is_noop(self):
        """If world_state is None, _trigger_npc_decisions should return without error."""
        room = create_single_player_room("cao", "test-user")
        room.world_state = None

        from histrategy.server.room_manager import _trigger_npc_decisions
        _trigger_npc_decisions(room)
        # No crash, no submissions
        for slot in room.ai_slots():
            assert not slot.has_submitted()

    def test_trigger_only_submits_for_active_slots(self):
        """Inactive (defeated) AI slots should not get decisions."""
        room = create_single_player_room("cao", "test-user")
        room.world_state = self._make_mock_world_state()
        # Mark wu as inactive
        room.slots["wu"].is_active = False

        from histrategy.server.room_manager import _trigger_npc_decisions
        _trigger_npc_decisions(room)

        assert room.slots["shu"].has_submitted(), "Active AI shu should get decision"
        assert not room.slots["wu"].has_submitted(), "Inactive AI wu should NOT get decision"


class TestSymmetricEngineIntegration:
    """Integration tests for the full symmetric flow."""

    def test_single_player_flow_no_llm(self):
        """Test the complete single-player flow using only heuristic decisions."""
        # Create room
        room = create_single_player_room("cao", "test-user")

        # Submit human decision
        room.slots["cao"].submit_decision("南征荆州，统一天下！")

        # Generate AI decisions via heuristic (no LLM needed)
        from histrategy.engine.decision_bus import _generate_heuristic_decision as gen

        # Mock world state minimal enough for heuristic to work
        class MockFaction:
            def __init__(self, name, strength=10000, treasury=8000, food=5000):
                self.name = name
                self.is_active = True
                self.strength_actual = strength
                self.treasury = treasury
                self.food = food
                self.territories = ["test_city"]
                self.capital = "test_city"
                self.tax_rate = 0.35
                self.relations = {}

        class MockTerritory:
            def __init__(self, owner_id):
                self.owner_id = owner_id

        class MockWS:
            def __init__(self):
                self.factions = {
                    "cao": MockFaction("曹操"),
                    "wu": MockFaction("孙权", strength=30000),
                    "shu": MockFaction("刘备", strength=5000, treasury=2000),
                }
                self.territories = {
                    "test_city": MockTerritory("cao"),
                }

        ws = MockWS()

        # Generate decisions for all AI slots
        decisions = {}
        for slot in room.ai_slots():
            if slot.faction_id in ws.factions:
                decision, commands = gen(ws, slot.faction_id)
                slot.submit_decision(decision, commands)
                decisions[slot.faction_id] = DecisionResult(
                    slot.faction_id,
                    decision,
                    commands,
                    source="heuristic",
                )

        # All slots should have submitted
        # (human + all AI)
        submitted = sum(1 for s in room.slots.values() if s.has_submitted())
        assert submitted >= 1  # At minimum the human faction

        # DB persistence roundtrip
        init_db()
        save_room(room)
        loaded = load_room(room.id)
        assert loaded is not None
        assert loaded.id == room.id
        assert len(loaded.slots) == len(room.slots)

        # Advance quarter
        room.advance_quarter()
        assert room.quarter_number == 1
        assert not room.all_slots_submitted()

    def test_multi_player_room_open_slots(self):
        """Test multiplayer room with open slots waiting for players."""
        room = create_multi_player_room("host-user", ["cao", "shu", "wu"])
        assert room.phase == RoomPhase.LOBBY
        assert len(room.slots) == 3

        # Major factions should be OPEN
        assert room.slots["cao"].is_open()
        assert room.slots["shu"].is_open()
        assert room.slots["wu"].is_open()

        # No minor factions — all non-human are major AI NPCs
        assert room.slots["cao"].is_open() or room.slots["cao"].is_human()
        assert room.slots["shu"].is_open() or room.slots["shu"].is_human()
        assert room.slots["wu"].is_open() or room.slots["wu"].is_human()

        # Start game
        room.start_game()
        assert room.phase == RoomPhase.WAITING

        # Simulate a player joining
        room.slots["cao"] = create_human_slot("cao", "player-1")
        room.slots["shu"] = create_human_slot("shu", "player-2")
        assert room.slots["cao"].is_human()
        assert room.slots["shu"].is_human()
        assert len(room.human_slots()) == 2
        # After replacing cao/shu: 2 human + 1 open (wu) + 4 minor AI = 7
        assert len(room.ai_slots()) == 0  # no minor factions


class TestPreAssignedFlow:
    """Test Host pre-assigned faction flow with player_token links."""

    def test_create_room_pre_assigned(self):
        """create_room with pre_assigned should create HUMAN slots with tokens."""
        # Simulate the pre-assigned path of create_room without world_state init or NPC trigger
        import uuid

        from histrategy.engine.faction_slot import (
            FACTION_DISPLAY_TO_ID,
            FACTION_ID_TO_DISPLAY,
            LLM_NPC_FACTIONS,
            create_ai_slot,
            create_human_slot,
        )
        from histrategy.engine.game_room import GameRoom
        pre_assigned = {"caocao": "张三", "liubei": "李四"}
        internal_map = {}
        for display_fid, player_name in pre_assigned.items():
            internal_fid = FACTION_DISPLAY_TO_ID.get(display_fid, display_fid)
            internal_map[internal_fid] = player_name
        internal_ids = list(internal_map.keys())

        room = GameRoom(host_user_id="host-1", scenario="207")
        player_links = []

        for fid in internal_ids:
            player_user_id = "u_" + uuid.uuid4().hex
            player_token = uuid.uuid4().hex
            slot = create_human_slot(fid, player_user_id)
            room.slots[fid] = slot
            player_name = internal_map[fid]
            display_fid = FACTION_ID_TO_DISPLAY.get(fid, fid)
            player_links.append({
                "faction": display_fid,
                "player_name": player_name,
                "player_token": player_token,
                "url": f"/mp?room={room.id}&faction={display_fid}&player_token={player_token}",
            })

        # 未指定的势力 → AI NPC
        for fid in LLM_NPC_FACTIONS:
            if fid not in room.slots:
                room.slots[fid] = create_ai_slot(fid)

        # Check slots are HUMAN for pre-assigned
        assert room.slots["cao"].is_human(), "cao should be HUMAN"
        assert room.slots["shu"].is_human(), "shu should be HUMAN"
        assert room.slots["wu"].is_ai(), "wu should be AI"

        # Check player links have tokens
        assert len(player_links) == 2
        for link in player_links:
            assert "faction" in link
            assert "player_token" in link
            assert "url" in link
            assert "player_token=" in link["url"]
            assert len(link["player_token"]) == 32  # full UUID hex

    def test_enter_room_with_player_token(self):
        """A pre-assigned player can enter using their token."""
        from histrategy.engine.faction_slot import LLM_NPC_FACTIONS, create_ai_slot, create_human_slot
        from histrategy.engine.game_room import GameRoom, RoomPhase
        from histrategy.server.room_manager import _players, _rooms, enter_room

        _rooms.clear()
        _players.clear()

        import uuid
        room = GameRoom(host_user_id="host-1", scenario="207")
        room.phase = RoomPhase.WAITING
        user_id = "u_player1"
        player_token = uuid.uuid4().hex
        room.slots["cao"] = create_human_slot("cao", user_id)
        for fid in LLM_NPC_FACTIONS:
            if fid not in room.slots:
                room.slots[fid] = create_ai_slot(fid)

        _rooms[room.id] = room
        _players[room.id] = {
            user_id: {"role": "player", "display_name": "张三", "player_token": player_token},
        }

        # Player visits via share link
        enter_result = enter_room(
            room_id=room.id,
            faction="caocao",
            player_token=player_token,
            display_name="张三",
        )
        assert enter_result["ok"]
        assert enter_result.get("already_in")  # Matched existing player

    def test_enter_room_wrong_player_blocked(self):
        """A player without token cannot take over a pre-assigned HUMAN slot."""
        from histrategy.engine.faction_slot import LLM_NPC_FACTIONS, create_ai_slot, create_human_slot
        from histrategy.engine.game_room import GameRoom, RoomPhase
        from histrategy.server.room_manager import _players, _rooms, enter_room

        _rooms.clear()
        _players.clear()

        room = GameRoom(host_user_id="host-1", scenario="207")
        room.phase = RoomPhase.WAITING
        user_id = "u_player1"
        room.slots["cao"] = create_human_slot("cao", user_id)
        for fid in LLM_NPC_FACTIONS:
            if fid not in room.slots:
                room.slots[fid] = create_ai_slot(fid)

        _rooms[room.id] = room
        _players[room.id] = {
            user_id: {"role": "player", "display_name": "张三", "player_token": "real_token"},
        }

        # Someone else tries to enter cao with no token
        result = enter_room(
            room_id=room.id,
            faction="caocao",
            display_name="入侵者",
        )
        # Should error because slot is already HUMAN with different occupant
        assert not result["ok"]
        assert "已被其他人占据" in result.get("error", "")

    def test_player_token_matching_and_reconnect(self):
        """Player token matching works correctly for reconnection."""
        from histrategy.server.room_manager import _players, _rooms, enter_room

        _rooms.clear()
        _players.clear()

        # Manually set up a room with a pre-assigned HUMAN slot
        import uuid

        from histrategy.engine.faction_slot import LLM_NPC_FACTIONS, create_ai_slot, create_human_slot
        from histrategy.engine.game_room import GameRoom, RoomPhase

        room = GameRoom(host_user_id="host-1", scenario="207")
        room.phase = RoomPhase.WAITING
        user_id = "u_caocao_player"
        player_token = uuid.uuid4().hex
        room.slots["cao"] = create_human_slot("cao", user_id)
        for fid in LLM_NPC_FACTIONS:
            if fid not in room.slots:
                room.slots[fid] = create_ai_slot(fid)

        _rooms[room.id] = room
        _players[room.id] = {
            user_id: {"role": "player", "display_name": "张三", "player_token": player_token},
        }

        # Player reconnects with correct token
        result = enter_room(
            room_id=room.id,
            faction="caocao",
            player_token=player_token,
            display_name="张三",
        )
        assert result["ok"]
        assert result.get("already_in")  # Found by token

        # Wrong token: should not be able to take over cao slot
        result2 = enter_room(
            room_id=room.id,
            faction="caocao",
            display_name="入侵者",
        )
        assert not result2["ok"]
        assert "已被其他人占据" in result2.get("error", "")

        # Token mismatch but valid for a different slot: should work fine
        result3 = enter_room(
            room_id=room.id,
            player_token="nonexistent_token",
            display_name="访客",
        )
        assert result3["ok"]  # Enters as spectator without faction claim
