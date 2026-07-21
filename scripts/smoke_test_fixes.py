"""
Smoke test: verify nanming balance fixes work correctly.
Tests the three bug fixes without LLM calls.
"""
import sys
sys.path.insert(0, '/opt/data/repos/histrategy')

from histrategy.engine.state_applier import (
    _apply_npc_faction_action,
    _settle_battle,
    _attacker_borders_territory,
    _NPC_CONSCRIPT_MAX_RATE,
    _npc_conscript_streak,
    _initial_faction_population,
)


def make_mock_ws():
    """Create a minimal WorldState for testing."""
    from unittest.mock import MagicMock
    ws = MagicMock()
    ws.player_faction_id = "nanming"
    
    # Territories
    ws.territories = {
        "nanjing": MagicMock(population=300000, owner_id="nanming", neighbors=["zhejiang", "wuchang"]),
        "zhejiang": MagicMock(population=100000, owner_id="nanming", neighbors=["nanjing"]),
        "beijing": MagicMock(population=200000, owner_id="qing", neighbors=["jinan", "shengjing"]),
        "jinan": MagicMock(population=80000, owner_id="qing", neighbors=["beijing", "kaifeng"]),
        "kaifeng": MagicMock(population=60000, owner_id="nanming", neighbors=["jinan", "luoyang"]),
        "shengjing": MagicMock(population=50000, owner_id="qing", neighbors=["beijing"]),
    }
    
    # Factions
    ws.factions = {
        "nanming": MagicMock(
            is_active=True, territories=["nanjing", "zhejiang", "kaifeng"],
            strength_actual=80000, treasury=50000, food=45000,
            morale_actual=65, tax_rate=0.3,
        ),
        "qing": MagicMock(
            is_active=True, territories=["beijing", "jinan", "shengjing"],
            strength_actual=120000, treasury=40000, food=35000,
            morale_actual=72, tax_rate=0.3,
        ),
    }
    return ws


def test_npc_conscript_capped():
    """BUG 1 FIX: NPC conscription must be capped by population."""
    ws = make_mock_ws()
    fmap = {"qing": "qing", "nanming": "nanming"}
    
    # Clear module-level state
    _npc_conscript_streak.clear()
    _initial_faction_population.clear()
    
    summary = {"npc_actions": 0}
    
    # Qing tries to conscript 100k — should be capped at 5% of total pop
    # Qing total pop: 200k+80k+50k=330k, 5% = 16500
    action = {
        "faction": "qing",
        "action_type": "conscript",
        "params": {"amount": 100000},
    }
    old_strength = ws.factions["qing"].strength_actual
    _apply_npc_faction_action(action, ws, fmap, summary)
    
    new_strength = ws.factions["qing"].strength_actual
    max_expected = int(330000 * 0.05)  # 16500
    added = new_strength - old_strength
    
    assert added <= max_expected + 100, (
        f"NPC conscript NOT capped! Added {added}, max expected {max_expected}"
    )
    print(f"  PASS: Qing conscript capped: {old_strength} → {new_strength} (+{added}, max={max_expected})")


def test_labor_floor_blocks_conscript():
    """Labor floor: below 25% original pop, conscription blocked."""
    ws = make_mock_ws()
    fmap = {"qing": "qing"}
    
    _npc_conscript_streak.clear()
    _initial_faction_population.clear()
    
    # First set initial pop to 100000
    _initial_faction_population["qing"] = 330000
    # Now drop all territory pop to 10% of original
    for t in ws.territories.values():
        if t.owner_id == "qing":
            t.population = int(t.population * 0.1)
    
    summary = {"npc_actions": 0}
    old_strength = ws.factions["qing"].strength_actual
    
    action = {
        "faction": "qing",
        "action_type": "conscript",
        "params": {"amount": 5000},
    }
    _apply_npc_faction_action(action, ws, fmap, summary)
    
    # Should NOT have recruited anything
    assert ws.factions["qing"].strength_actual == old_strength, (
        f"Labor floor violated! Conscript allowed when pop was below 25%"
    )
    print("  PASS: Labor floor blocks conscription when pop < 25% of original")


def test_territory_adjacency_blocked():
    """BUG 2 FIX: Non-adjacent territory capture blocked."""
    ws = make_mock_ws()
    fmap = {"qing": "qing", "nanming": "nanming"}
    tmap = {k: k for k in ws.territories}
    
    summary = {"battles_settled": 0, "territories_captured": 0, "troops_lost": 0}
    
    # Qing tries to capture nanjing (not adjacent to any qing territory)
    battle = {
        "location": "nanjing",
        "attacker": "qing",
        "defender": "nanming",
        "territory_captured": True,
        "result": "attack_win",
        "casualties": {"attacker": 2000, "defender": 5000},
    }
    _settle_battle(battle, ws, fmap, tmap, summary)
    
    # Nanjing should NOT be captured (Qing borders: beijing, jinan, shengjing — none neighbor nanjing)
    assert summary["territories_captured"] == 0, (
        f"Non-adjacent territory capture was allowed! Nanjing was captured."
    )
    print("  PASS: Non-adjacent territory capture blocked")


def test_territory_adjacency_allowed():
    """Adjacent territory capture should succeed."""
    ws = make_mock_ws()
    fmap = {"qing": "qing", "nanming": "nanming"}
    tmap = {k: k for k in ws.territories}
    
    summary = {"battles_settled": 0, "territories_captured": 0, "troops_lost": 0}
    
    # Qing captures kaifeng (jinan borders kaifeng → adjacency OK)
    battle = {
        "location": "kaifeng",
        "attacker": "qing",
        "defender": "nanming",
        "territory_captured": True,
        "result": "attack_win",
        "casualties": {"attacker": 1000, "defender": 2000},
    }
    _settle_battle(battle, ws, fmap, tmap, summary)
    
    assert summary["territories_captured"] == 1, (
        f"Adjacent territory capture was blocked! Kaifeng should have been captured."
    )
    print("  PASS: Adjacent territory capture succeeds")


def test_attacker_borders():
    """_attacker_borders_territory helper works correctly."""
    ws = make_mock_ws()
    
    # Qing borders kaifeng (jinan is qing, jinan neighbors kaifeng)
    assert _attacker_borders_territory("qing", "kaifeng", ws), "Qing should border kaifeng"
    # Qing does NOT border nanjing
    assert not _attacker_borders_territory("qing", "nanjing", ws), "Qing should NOT border nanjing"
    # Qing does NOT border zhejiang
    assert not _attacker_borders_territory("qing", "zhejiang", ws), "Qing should NOT border zhejiang"
    print("  PASS: Adjacency helper correct")


if __name__ == "__main__":
    print("=== Smoke Testing Nanming Balance Fixes ===\n")
    
    tests = [
        ("NPC conscript capped", test_npc_conscript_capped),
        ("Labor floor blocks conscript", test_labor_floor_blocks_conscript),
        ("Non-adjacent territory blocked", test_territory_adjacency_blocked),
        ("Adjacent territory allowed", test_territory_adjacency_allowed),
        ("Adjacency helper", test_attacker_borders),
    ]
    
    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} — {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {name} — {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Result: {passed} passed, {failed} failed out of {len(tests)}")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("All fixes verified!")
