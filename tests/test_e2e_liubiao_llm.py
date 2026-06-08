"""
E2E LLM Mode Test — 刘表战略 (H09f)

Tests the full LLM-driven game loop as Liu Biao:
1. Faction initialization with proper intro scene
2. Plan Mode: court dialogue + strategic suggestions
3. Command Mode: turn processing with narrative + state changes
4. Multi-turn gameplay (3 turns)
5. Validates no crashes, no empty outputs, proper structure

Run with: pytest tests/test_e2e_liubiao_llm.py -v
Requires: DEEPSEEK_API_KEY or OPENAI_API_KEY in environment
"""
import json
import os
import sys
from pathlib import Path

import pytest

HISTRATEGY_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(HISTRATEGY_DIR))


@pytest.fixture(autouse=True)
def isolated_save_dir(tmp_path, monkeypatch):
    """Run each test with an isolated save directory."""
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path / ".histrategy"))
    yield


def has_api_key() -> bool:
    """Check if any LLM API key is available."""
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "TONGYI_API_KEY", "OPENROUTER_API_KEY"):
        if os.environ.get(key):
            return True
    return False


@pytest.mark.skipif(not has_api_key(), reason="No LLM API key available")
class TestLiubiaoLLMMode:
    """E2E tests for Liu Biao faction in LLM-driven mode."""

    def test_intro_scene_liubiao(self):
        """Liu Biao intro scene should mention his faction and territories."""
        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        llm = LLMAdapter()
        assert llm.is_available, "LLM should be available"

        engine = GameEngine(llm=llm, new_game=True, force_v1=True)
        engine.set_player_faction("liubiao")

        intro = engine.get_intro_scene()
        assert intro, "Intro scene should not be empty"

        narrative = intro.get("narrative", "")
        assert len(narrative) > 100, f"Intro narrative too short: {len(narrative)} chars"
        # Should mention Liu Biao or 荆州 or 刘表
        assert any(term in narrative for term in ["刘表", "荆州", "liubiao"]), \
            f"Intro should mention Liu Biao or Jingzhou region: {narrative[:200]}"

        npc_actions = intro.get("npc_actions", [])
        assert len(npc_actions) > 0, "Should have NPC faction descriptions"

        print(f"\n  INTRO NARRATIVE ({len(narrative)} chars): {narrative[:300]}...")
        print(f"  NPC ACTIONS: {json.dumps(npc_actions, ensure_ascii=False)[:200]}...")

    def test_plan_mode_liubiao(self):
        """Plan Mode should generate court dialogue and suggestions for Liu Biao."""
        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        llm = LLMAdapter()
        engine = GameEngine(llm=llm, new_game=True, force_v1=True)
        engine.set_player_faction("liubiao")

        # Skip intro by getting plan data
        plan = engine.get_plan_data()
        assert plan, "Plan data should not be empty"

        court_dialogue = plan.get("court_dialogue", "")
        assert len(court_dialogue) > 50, \
            f"Court dialogue too short: {len(court_dialogue)} chars"

        suggestions = plan.get("suggestions", [])
        assert len(suggestions) >= 2, \
            f"Should have at least 2 suggestions, got {len(suggestions)}"
        assert all(isinstance(s, str) for s in suggestions), \
            "All suggestions should be strings"

        # Check for duplicate suggestions (bug fix from H09e)
        assert len(suggestions) == len(set(suggestions)), \
            f"Duplicate suggestions found: {suggestions}"

        season_summary = plan.get("season_summary", "")
        assert season_summary, "Should have season summary"

        print(f"\n  COURT DIALOGUE ({len(court_dialogue)} chars): {court_dialogue[:300]}...")
        print(f"  SUGGESTIONS ({len(suggestions)}): {json.dumps(suggestions, ensure_ascii=False)[:300]}...")

    def test_command_mode_liubiao(self):
        """Command Mode should process player decisions and return results."""
        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        llm = LLMAdapter()
        engine = GameEngine(llm=llm, new_game=True, force_v1=True)
        engine.set_player_faction("liubiao")

        # Execute a strategic decision for Liu Biao
        decision = "坐镇襄阳，操练水军，结好刘璋，防止曹操南下。"

        result = engine.process_turn(decision)
        assert result, "Command result should not be empty"

        # Check core output fields
        aftermath = result.get("aftermath", "")
        assert len(aftermath) > 50, \
            f"Aftermath narrative too short: {len(aftermath)} chars"

        state_changes = result.get("state_changes", {})
        assert isinstance(state_changes, dict), "State changes should be a dict"

        npc_reactions = result.get("npc_reactions", [])
        assert len(npc_reactions) > 0, "Should have NPC reactions"

        # Check bureaucracy execution
        bureaucracy = result.get("bureaucracy", [])
        if bureaucracy:
            assert isinstance(bureaucracy, list), "Bureaucracy should be a list"

        # Check seeds
        seeds = result.get("seeds", [])
        assert isinstance(seeds, list), "Seeds should be a list"

        print(f"\n  DECISION: {decision}")
        print(f"  AFTERMATH ({len(aftermath)} chars): {aftermath[:300]}...")
        print(f"  STATE CHANGES: {json.dumps(state_changes, ensure_ascii=False)[:200]}...")
        print(f"  NPC REACTIONS: {json.dumps(npc_reactions, ensure_ascii=False)[:200]}...")

        # Verify state was updated
        player = engine.world_state.get_player_faction()
        assert player is not None, "Player faction should exist after turn"
        assert player.is_active, "Liu Biao should still be active"

    def test_multi_turn_liubiao(self):
        """Multi-turn gameplay: 2 turns of Plan → Decision → Command."""
        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        llm = LLMAdapter()
        engine = GameEngine(llm=llm, new_game=True, force_v1=True)
        engine.set_player_faction("liubiao")

        decisions = [
            "休养生息，发展襄阳经济，安抚荆州豪族。",
            "派遣细作北上打探曹操动向，在江陵增筑水寨训练水师。",
        ]

        for turn, decision in enumerate(decisions, 1):
            # Plan mode
            plan = engine.get_plan_data()
            assert plan.get("court_dialogue"), f"Turn {turn}: missing court dialogue"
            assert len(plan.get("suggestions", [])) >= 2, \
                f"Turn {turn}: insufficient suggestions"

            # Command mode
            result = engine.process_turn(decision)
            assert result.get("aftermath"), f"Turn {turn}: missing aftermath"
            assert result.get("npc_reactions"), f"Turn {turn}: missing NPC reactions"

            # Verify faction is alive
            player = engine.world_state.get_player_faction()
            assert player and player.is_active, f"Turn {turn}: Liu Biao eliminated"

            print(f"\n  --- TURN {turn} ---")
            print(f"  Decision: {decision}")
            print(f"  Aftermath: {result['aftermath'][:200]}...")

        # Check that state evolved
        player = engine.world_state.get_player_faction()
        print(f"\n  FINAL STATE: {player.name} | 兵力:{player.strength} | "
              f"经济:{player.economy} | 民心:{player.morale} | "
              f"资金:{player.treasury} | 粮草:{player.food}")

    def test_no_self_allying(self):
        """Regression: Liu Biao should NOT ally with himself (H09e bug fix)."""
        from histrategy.engine.game import GameEngine
        from histrategy.llm.adapter import LLMAdapter

        llm = LLMAdapter()
        engine = GameEngine(llm=llm, new_game=True, force_v1=True)
        engine.set_player_faction("liubiao")

        # Make a decision that might trigger alliance logic
        decision = "与刘表军结盟共同御敌。"

        result = engine.process_turn(decision)
        npc_reactions = result.get("npc_reactions", [])

        for reaction in npc_reactions:
            if isinstance(reaction, str):
                # Should not mention allying with self
                assert "刘表" not in reaction or "结盟" not in reaction, \
                    f"Self-allying detected: {reaction}"

        print(f"\n  SELF-ALLY CHECK PASSED: {len(npc_reactions)} NPC reactions")
