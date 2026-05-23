"""Engine-level unit tests for 三國志略 (not TUI-dependent).

Tests the core game logic directly: world model, simulation, aftermath.
These tests DON'T depend on Rich TUI output — they test game logic directly.
"""
import json, os, tempfile
from pathlib import Path

import pytest

from histrategy.engine.world import GameWorld
from histrategy.engine.offline_sim import (
    simulate_turn_offline, _classify_intent, _compute_aftermath,
    _compute_base_effects, _get_action_narrative, load_player_memory,
    _check_game_over, _generate_choices,
)


@pytest.fixture(autouse=True)
def clean_memory():
    """Clean memory file before each test."""
    mem = Path.home() / ".histrategy" / "player_memory.json"
    if mem.exists():
        mem.unlink()
    yield
    if mem.exists():
        mem.unlink()


class TestWorldModel:
    """Test the game world model directly."""

    def test_world_creation(self):
        """World loads with correct number of entities."""
        w = GameWorld("190")
        assert len(w.characters) >= 20
        assert len(w.factions) >= 8
        assert len(w.regions) >= 19

    def test_faction_specific_stats(self):
        """Each faction has unique starting stats."""
        w = GameWorld("190")
        assert w.factions["cao"].strength == 30000
        assert w.factions["yuan_shao"].strength == 80000
        assert w.factions["shu"].morale == 90
        assert w.factions["wu"].economy == 50

    def test_faction_personality(self):
        """Character personalities inform faction behavior."""
        w = GameWorld("190")
        cao = w.characters["caocao"]
        assert "多疑" in cao.personality
        assert "雄才大略" in cao.personality
        ys = w.characters["yuanshao"]
        assert "好谋无断" in ys.personality


class TestSimulation:
    """Test the offline simulation engine."""

    def test_simulate_returns_narrative(self):
        """Simulation always returns narrative text."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        result = simulate_turn_offline(w, "发展经济")
        assert "narrative" in result
        assert len(result["narrative"]) > 20

    def test_simulate_changes_state(self):
        """Simulation changes game state."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        initial = w.factions["cao"].economy
        simulate_turn_offline(w, "发展经济")
        assert w.factions["cao"].economy != initial

    def test_military_buildup_increases_strength(self):
        """Choosing military should increase faction strength."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        initial = w.factions["cao"].strength
        simulate_turn_offline(w, "扩军备战训练新军")
        assert w.factions["cao"].strength > initial

    def test_turns_advance(self):
        """Game engine advances turns correctly."""
        from histrategy.engine.game import GameEngine
        engine = GameEngine()
        engine.set_player_faction("cao")
        assert engine.world.turn_count == 0
        engine.process_turn("发展经济")
        assert engine.world.turn_count == 1
        engine.process_turn("发展经济")
        assert engine.world.turn_count == 2

    def test_npc_factions_also_change(self):
        """NPC faction stats change over time too."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        initial_dong = w.factions["dongzhuo"].strength
        simulate_turn_offline(w, "发展经济")
        assert w.factions["dongzhuo"].strength != initial_dong


class TestFactionSpecificity:
    """Test that different factions get different content."""

    def test_cao_cao_intro_references_cao(self):
        """Cao Cao intro mentions Cao's advisors."""
        from histrategy.engine.game import GameEngine
        engine = GameEngine()
        engine.set_player_faction("cao")
        intro = engine._offline_intro()
        assert "曹操" in intro["narrative"]
        assert "荀彧" in intro["narrative"]
        assert "夏侯惇" in intro["narrative"]

    def test_yuan_shao_intro_references_yuan(self):
        """Yuan Shao intro mentions his own advisors, not Cao's."""
        from histrategy.engine.game import GameEngine
        engine = GameEngine()
        engine.set_player_faction("yuan_shao")
        intro = engine._offline_intro()
        assert "袁绍" in intro["narrative"]
        assert "田丰" in intro["narrative"]
        assert "颜良" in intro["narrative"]
        assert "曹操" not in intro["narrative"].split("你，")[1] if "你，" in intro["narrative"] else True

    def test_yuan_shao_first_choices(self):
        """Yuan Shao should not see '联络袁绍' as an option."""
        from histrategy.engine.game import GameEngine
        engine = GameEngine()
        engine.set_player_faction("yuan_shao")
        intro = engine._offline_intro()
        choices_text = " ".join(intro["new_choices"])
        assert "联络袁绍" not in choices_text
        assert "盟主" in choices_text

    def test_liu_bei_intro_references_guan_yu(self):
        """Liu Bei intro mentions Guan Yu and Zhang Fei."""
        from histrategy.engine.game import GameEngine
        engine = GameEngine()
        engine.set_player_faction("shu")
        intro = engine._offline_intro()
        assert "刘备" in intro["narrative"]
        assert "关羽" in intro["narrative"]
        assert "张飞" in intro["narrative"]


class TestAftermath:
    """Test the aftermath consequence system."""

    def test_aftermath_for_ally_request(self):
        """Typing '联合袁绍' should give alliance consequence."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        result = simulate_turn_offline(w, "联合袁绍讨伐董卓")
        aftermath = result.get("aftermath", "")
        assert len(aftermath) > 5
        assert "袁绍" in aftermath or "董卓" in aftermath

    def test_aftermath_for_spy(self):
        """Typing spy-related words should give intel consequence."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        result = simulate_turn_offline(w, "派细作潜入长安侦查")
        aftermath = result.get("aftermath", "")
        assert "细作" in aftermath or "密报" in aftermath or "情报" in aftermath

    def test_narrative_reflects_player_words(self):
        """The narrative should quote the player's decision."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        result = simulate_turn_offline(w, "联合孙权共抗曹操")
        narrative = result["narrative"]
        assert "联合孙权" in narrative or "孙权" in narrative


class TestIntentClassification:
    """Test the intent classifier."""

    def test_military_keywords(self):
        """Military keywords classify correctly."""
        assert _classify_intent("讨伐董卓") == "military"
        assert _classify_intent("出征") == "military"
        assert _classify_intent("攻打长安") == "military"

    def test_economy_keywords(self):
        """Economy keywords classify correctly."""
        assert _classify_intent("发展经济") == "economy"
        assert _classify_intent("屯田养兵") == "economy"
        assert _classify_intent("兴修水利") == "economy"

    def test_diplomacy_keywords(self):
        """Diplomacy keywords classify correctly."""
        assert _classify_intent("联合袁绍") in ("diplomacy", "military")
        assert _classify_intent("派出使者") == "diplomacy"


class TestNoPrematureVictory:
    """Test that game doesn't end too early."""

    def test_12_turns_no_victory(self):
        """Pure economy development shouldn't trigger victory before turn 12."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        for i in range(14):  # 14 turns of economy
            result = simulate_turn_offline(w, "发展经济")
            assert result.get("game_over") is None, \
                f"Game over at turn {i}: {result['game_over']}"

    def test_12_turns_military_no_victory(self):
        """Pure military buildup shouldn't trigger victory before turn 12."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        for i in range(14):
            result = simulate_turn_offline(w, "扩军备战")
            assert result.get("game_over") is None, \
                f"Game over at turn {i}: {result['game_over']}"


class TestChoicesGenerated:
    """Test that choices are generated each turn."""

    def test_choices_returned(self):
        """Each simulation turn returns choices."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        choices = _generate_choices("economy", w)
        assert len(choices) >= 3
        assert any("扩军" in c or "出征" in c for c in choices)

    def test_choices_depend_on_state(self):
        """Choices should change based on faction state."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        w.factions["cao"].economy = 20  # Low economy
        choices = _generate_choices("economy", w)
        choice_text = " ".join(choices)
        assert "休养生息" in choice_text


class TestMemorySystem:
    """Test the memory/save system."""

    def test_memory_file_created(self):
        """Playing should create a memory file with decisions."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        simulate_turn_offline(w, "发展经济")
        sim2 = simulate_turn_offline(w, "扩军备战")
        mem_file = Path.home() / ".histrategy" / "player_memory.json"
        assert mem_file.exists()
        data = json.loads(mem_file.read_text())
        assert len(data["decisions"]) == 2
        assert data["decisions"][0]["decision"] == "发展经济"

    def test_memory_persists_across_calls(self):
        """Memory persists between calls to simulate_turn_offline."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        # First call
        mem1 = load_player_memory()
        assert len(mem1["decisions"]) == 0
        # Play some turns
        for i in range(3):
            simulate_turn_offline(w, f"决策{i}")
        # Memory should have 3 entries
        mem2 = load_player_memory()
        assert len(mem2["decisions"]) >= 3


class TestCapitalNames:
    """Test that capital names are Chinese, not English IDs."""

    def test_cao_capital_is_chinese(self):
        """Cao Cao's capital should show as 许昌."""
        from histrategy.engine.game import FACTION_INTROS
        assert FACTION_INTROS["cao"]["capital_name"] == "许昌"

    def test_yuan_shao_capital_is_chinese(self):
        """Yuan Shao's capital should show as 邺城."""
        from histrategy.engine.game import FACTION_INTROS
        assert FACTION_INTROS["yuan_shao"]["capital_name"] == "邺城"
