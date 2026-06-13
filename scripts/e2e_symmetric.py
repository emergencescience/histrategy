"""
E2E test for symmetric multiplayer engine.

Tests:
  1. Single-player symmetric mode (HISTRATEGY_SYMMETRIC=1)
  2. FactionSlot + GameRoom creation
  3. DecisionBus with heuristic NPC fallback
  4. QuarterlyResolver pipeline
  5. DB persistence (SQLite)
  6. Multi-turn simulation

Run:
    HISTRATEGY_SYMMETRIC=1 HISTRATEGY_DATA_DIR=/tmp/histrategy_e2e \
    python scripts/e2e_symmetric.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid


def setup():
    """Setup isolated test environment."""
    test_dir = f"/tmp/histrategy_e2e_{uuid.uuid4().hex[:8]}"
    os.makedirs(test_dir, exist_ok=True)
    os.environ["HISTRATEGY_DATA_DIR"] = test_dir
    os.environ["HISTRATEGY_SYMMETRIC"] = "1"
    # Clear any API key so we test heuristic fallback
    for key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "TONGYI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY"]:
        os.environ.pop(key, None)
    return test_dir


def test_faction_slot():
    """Test FactionSlot creation and state transitions."""
    print("=== Test: FactionSlot ===")
    from histrategy.engine.faction_slot import (
        FactionSlot,
        OccupantType,
        create_human_slot,
        create_ai_slot,
    )

    h = create_human_slot("cao", "user_A")
    assert h.is_human(), "Human slot should be human"
    assert not h.has_submitted(), "New slot should not have submitted"

    h.submit_decision("进攻新野", [{"type": "attack", "params": {"target": "xinye"}}])
    assert h.has_submitted(), "Should have submitted after submit_decision"

    h.clear_decision()
    assert not h.has_submitted(), "Should clear after clear_decision"

    a = create_ai_slot("shu")
    assert a.is_ai(), "AI slot should be AI"

    # Serialization round-trip
    data = h.to_dict()
    restored = FactionSlot.from_dict(data)
    assert restored.faction_id == "cao"
    assert restored.occupant_type == OccupantType.HUMAN
    print("  ✓ FactionSlot OK")


def test_game_room():
    """Test GameRoom creation and lifecycle."""
    print("=== Test: GameRoom ===")
    from histrategy.engine.game_room import (
        GameRoom,
        RoomPhase,
        create_single_player_room,
    )

    room = create_single_player_room("shu", "test_user")
    assert len(room.slots) >= 3, f"Expected ≥3 slots, got {len(room.slots)}"
    assert "shu" in room.slots
    assert room.slots["shu"].is_human()

    # Major factions should be AI
    for fid in ["cao", "wu"]:
        if fid in room.slots:
            assert room.slots[fid].is_ai(), f"{fid} should be AI"

    # Start game
    room.start_game()
    assert room.phase == RoomPhase.WAITING

    # Submit human decision
    room.slots["shu"].submit_decision("三顾茅庐请诸葛亮出山")
    assert room.slots["shu"].has_submitted()

    # Other slots not submitted
    pending = room.pending_slots()
    assert len(pending) > 0, "Should have pending AI factions"

    # Test advancement
    room.advance_quarter()
    assert room.quarter_number == 1
    assert not room.slots["shu"].has_submitted(), "Should clear after advance"

    # Serialization
    data = room.to_dict()
    restored = GameRoom.from_dict(data)
    assert restored.id == room.id
    assert len(restored.slots) == len(room.slots)

    print("  ✓ GameRoom OK")


def test_decision_bus():
    """Test DecisionBus with heuristic fallback."""
    print("=== Test: DecisionBus ===")
    from histrategy.engine.game_room import create_single_player_room
    from histrategy.engine.decision_bus import collect_all_decisions
    from histrategy.engine.game import GameEngine

    # Build a minimal world state
    engine = GameEngine(scenario="207", new_game=True)
    engine.set_player_faction("shu")  # must be called before get_intro_scene/process_turn
    engine.game_started = True
    ws = engine.world_state_v2

    room = create_single_player_room("shu", "test_user")
    room.start_game()
    room.slots["shu"].submit_decision("三顾茅庐")

    # Collect decisions (no LLM → heuristic fallback)
    decisions = collect_all_decisions(room, ws, llm=None, turn_memory=[])

    assert "shu" in decisions, "Human decision should be collected"
    assert decisions["shu"].source == "human"

    # AI factions should get heuristic decisions
    for slot in room.ai_slots():
        fid = slot.faction_id
        assert fid in decisions, f"AI faction {fid} should have a decision"
        dr = decisions[fid]
        assert dr.source in ("heuristic", "llm"), f"AI source should be heuristic or llm, got {dr.source}"
        assert dr.decision_text, f"AI {fid} should have decision text"

    print(f"  ✓ DecisionBus OK ({len(decisions)} factions, {len([d for d in decisions.values() if d.source == 'human'])} human)")
    return engine, room, decisions


def test_quarterly_resolver(engine, room, decisions):
    """Test QuarterlyResolver pipeline."""
    print("=== Test: QuarterlyResolver ===")
    from histrategy.engine.quarterly_resolver import QuarterlyResolver

    ws = engine.world_state_v2
    resolver = QuarterlyResolver(
        intent_parser=engine.intent_parser,
        turn_controller=engine.turn_controller,
        history_engine=engine.history_engine,
        macro_policy_engine=None,  # No LLM
        narrative_engine=engine.narrative_engine,
        black_swan_injector=None,
        guardrail_validator=None,
        state_applier=None,
    )

    result = resolver.resolve(room, ws, decisions, llm=None)

    assert result.total_latency_ms > 0, "Should have latency"
    assert result.turn_summary, "Should have turn summary"
    assert result.state_changes, "Should have state changes"

    print(f"  ✓ QuarterlyResolver OK ({result.total_latency_ms:.0f}ms, "
          f"narratives={len(result.narratives)}, events={len(result.history_events)})")
    return result


def test_db_persistence(test_dir):
    """Test SQLite persistence."""
    print("=== Test: DB Persistence ===")
    from histrategy.db.connection import init_db, execute_one, execute
    from histrategy.db.models import save_room, load_room

    init_db()

    from histrategy.engine.game_room import create_single_player_room

    room = create_single_player_room("cao", "persist_user")
    room.start_game()

    # Save
    save_room(room)
    print(f"  ✓ Room saved: {room.id}")

    # Load
    loaded = load_room(room.id)
    assert loaded is not None, "Should load room"
    assert loaded.id == room.id
    assert len(loaded.slots) == len(room.slots)
    assert loaded.slots["cao"].is_human()
    print(f"  ✓ Room loaded: {len(loaded.slots)} slots, phase={loaded.phase}")

    # Save a quarter turn
    from histrategy.db.models import save_quarter_turn, get_quarter_turns

    turn_id = save_quarter_turn(
        room.id, 1, 207, "春",
        faction_decisions={"cao": {"decision": "进攻新野"}},
        narratives={"cao": "曹操大军压境..."},
    )
    assert turn_id, "Should get turn ID"

    turns = get_quarter_turns(room.id, limit=5)
    assert len(turns) == 1, f"Should have 1 turn, got {len(turns)}"

    # LLM call log
    from histrategy.db.models import log_llm_call
    log_id = log_llm_call(
        room.id, 1, "npc_decision", "deepseek", "deepseek-v4-pro",
        prompt_tokens=500, completion_tokens=200, total_tokens=700,
        system_prompt_type="npc_decision",
        faction_id="wu",
    )
    assert log_id, "Should get log ID"

    # Sim event log
    from histrategy.db.models import log_sim_event
    event_id = log_sim_event(room.id, 1, "black_swan", {"event": "liubiao_death"})
    assert event_id, "Should get event ID"

    print("  ✓ DB persistence OK")


def test_multi_turn():
    """Test multiple turns with symmetric engine."""
    print("=== Test: Multi-Turn ===")
    from histrategy.engine.game import GameEngine

    engine = GameEngine(scenario="207", new_game=True)
    engine.set_player_faction("shu")  # must be called before get_intro_scene/process_turn
    engine.game_started = True

    # Turn 1
    t0 = time.time()
    result1 = engine.process_turn("南征荆州，集结宛城兵力进攻新野")
    t1 = time.time()
    assert result1.get("narrative"), "Should have narrative"
    assert "npc_actions" in result1, "Should have npc_actions"
    print(f"  Turn 1: {t1 - t0:.1f}s, npc_actions={len(result1.get('npc_actions', []))}")

    # Turn 2
    result2 = engine.process_turn("如果新野已克，继续进攻襄阳；否则再次强攻新野")
    t2 = time.time()
    assert result2.get("narrative"), "Should have narrative"
    print(f"  Turn 2: {t2 - t1:.1f}s, npc_actions={len(result2.get('npc_actions', []))}")

    # Turn 3
    result3 = engine.process_turn("稳定内政，降低税率至20%")
    t3 = time.time()
    assert result3.get("narrative"), "Should have narrative"
    print(f"  Turn 3: {t3 - t2:.1f}s")

    # Verify game state (should have advanced 3 turns)
    ws = engine.world_state_v2
    assert ws.turn_number >= 3, f"Expected ≥3 turns, got {ws.turn_number}"

    # Verify no crashes
    assert not result3.get("game_over"), "Game should not be over after 3 turns"

    print("  ✓ Multi-turn OK (3 turns)")
    return engine


def test_file_backup(engine):
    """Test write-only file backup."""
    print("=== Test: File Backup ===")
    from histrategy.db import file_backup
    from histrategy.engine.game_room import GameRoom

    room = GameRoom(id="test_backup_room", host_user_id="test")
    ws_dict = engine.world_state_v2.to_dict() if hasattr(engine.world_state_v2, "to_dict") else {}

    file_backup.write_room_snapshot(room, ws_dict, reason="e2e_test")
    backups = file_backup.list_backups(room.id)
    assert len(backups) >= 1, f"Should have at least 1 backup, got {len(backups)}"
    print(f"  ✓ File backup OK ({len(backups)} files)")

    file_backup.cleanup_old_backups(room.id, keep=5)


def main():
    test_dir = setup()
    print(f"Test dir: {test_dir}")
    print()

    try:
        test_faction_slot()
        test_game_room()
        engine, room, decisions = test_decision_bus()
        test_quarterly_resolver(engine, room, decisions)
        test_db_persistence(test_dir)
        engine2 = test_multi_turn()
        test_file_backup(engine2)

        print()
        print("=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    except Exception as e:
        print()
        print("=" * 60)
        print(f"TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
