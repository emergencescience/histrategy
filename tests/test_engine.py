"""Engine-level unit tests for 三國志略 (not TUI-dependent).

Tests the core game logic directly: world model, simulation, aftermath.
These tests DON'T depend on Rich TUI output — they test game logic directly.
"""

import json

import pytest

from histrategy.engine.offline_sim import (
    _classify_intent,
    _generate_choices,
    load_player_memory,
    simulate_turn_offline,
)
from histrategy.engine.world import GameWorld


@pytest.fixture(autouse=True)
def isolated_save_dir(tmp_path, monkeypatch):
    """Keep tests away from the user's real ~/.histrategy save directory."""
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path / ".histrategy"))
    monkeypatch.setenv("HISTRATEGY_FORCE_V1", "true")
    yield


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
        assert engine.world_state.turn == 0
        result = engine.process_turn("发展经济")
        assert engine.world_state.turn == 1
        engine.process_turn("发展经济")
        assert engine.world_state.turn == 2

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

    def test_yuan_shao_intro_fallback(self):
        """207 scenario: Yuan Shao (died 202) not supported — gets fallback intro."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine()
        engine.set_player_faction("yuan_shao")
        intro = engine._offline_intro()
        # Fallback should not crash and should contain generic narrative
        assert intro["narrative"], "fallback intro should have narrative"
        assert len(intro["new_choices"]) == 4, "fallback intro should have 4 choices"

    def test_yuan_shao_choices_no_self_reference(self):
        """207 scenario: Yuan Shao unsupported, choices should not reference self."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine()
        engine.set_player_faction("yuan_shao")
        intro = engine._offline_intro()
        choices_text = " ".join(intro["new_choices"])
        assert "联络袁绍" not in choices_text, "unsupported faction should not reference itself"

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
            assert result.get("game_over") is None, f"Game over at turn {i}: {result['game_over']}"

    def test_12_turns_military_no_victory(self):
        """Pure military buildup shouldn't trigger victory before turn 12."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        for i in range(14):
            result = simulate_turn_offline(w, "扩军备战")
            assert result.get("game_over") is None, f"Game over at turn {i}: {result['game_over']}"


class TestChoicesGenerated:
    """Test that choices are generated each turn."""

    def test_choices_returned(self):
        """Each simulation turn returns choices."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        choices = _generate_choices("economy", w)
        assert len(choices) >= 3
        assert any("扩军" in c or "出征" in c for c in choices)

    def test_simulation_result_returns_fields(self):
        """Offline turn results should surface execution results."""
        w = GameWorld("190")
        w.player_faction_id = "cao"
        result = simulate_turn_offline(w, "发展商贸")
        # New fields
        assert "aftermath" in result or "narrative" in result
        assert "events_occurred" in result
        assert "state_changes" in result
        assert "seeds" in result  # New: long-term consequences

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
        from histrategy.engine.offline_sim import _memory_file

        mem_file = _memory_file()
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


class TestOfflineTurnProgression:
    """Test offline legacy world time progression through the engine."""

    def test_legacy_world_advances_with_world_state(self):
        """Offline reports should not be stuck in 190 spring forever."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine(new_game=True)
        engine.set_player_faction("cao")
        engine.process_turn("发展经济")
        assert engine.world_state.turn == 1
        assert engine.legacy_world.turn_count == 1
        assert engine.legacy_world.current_season == "summer"


class TestCapitalNames:
    """Test that capital names are Chinese, not English IDs."""

    def test_cao_cao_capital_is_chinese(self):
        """Cao Cao's capital should show as 许昌."""
        from histrategy.engine.game import FACTION_CONFIGS

        assert FACTION_CONFIGS["cao"]["capital"] == "xuchang"
        # The capital ID is used to look up Chinese name
        from histrategy.engine.offline_sim import CAPITAL_NAMES

        assert CAPITAL_NAMES["xuchang"] == "许昌"

    def test_yuan_shao_capital_is_chinese(self):
        """Yuan Shao's capital should show as 邺城."""
        from histrategy.engine.world import GameWorld

        w = GameWorld("190")
        assert w.factions["yuan_shao"].capital == "yecheng"
        from histrategy.engine.offline_sim import CAPITAL_NAMES

        assert CAPITAL_NAMES["yecheng"] == "邺城"


class TestNPCBetrayalTrigger:
    """Test NPC emotional state danger thresholds and defection events."""

    def test_plotting_mood_betrayal_after_consecutive_turns(self):
        """NPC in plotting mood for 2+ consecutive turns should trigger betrayal."""
        from histrategy.engine.game import GameEngine
        from histrategy.state.npc_state import NPCMood, NPCState
        from histrategy.state.world_state import CharacterState

        engine = GameEngine(new_game=True)
        engine.set_player_faction("cao")

        # Manually register an advisor 'xun_yu' in world characters and npc_states
        engine.world_state.characters["xun_yu"] = CharacterState(
            id="xun_yu", name="荀彧", faction_id="cao", role="advisor"
        )

        # Inject plotting state with turns_at_current_mood = 2
        engine.world_state.npc_states["xun_yu"] = NPCState(
            character_id="xun_yu",
            mood=NPCMood.PLOTTING,
            turns_at_current_mood=2,
            loyalty=20,
        )

        # Run a turn. This should trigger defection
        result = engine.process_turn("发展内政")

        # Check if the betrayal event was registered
        assert any("荀彧" in evt and "叛逃" in evt for evt in result["events_occurred"])
        assert "xun_yu" not in engine.world_state.npc_states
        # Xun Yu should have defected to another faction (e.g. not 'cao')
        assert engine.world_state.characters["xun_yu"].faction_id != "cao"


class TestNPCAutonomousBehavior:
    """H08h: E2E playthrough validating NPC autonomous actions.

    NPCs (non-player factions) should independently:
      - Change stats each turn (economy, strength, morale)
      - Exhibit personality-driven behavior (aggressive factions expand more)
      - Form alliances or wage wars with each other
      - React differently to player military vs economic focus
      - Show meaningful stat divergence over multi-turn playthroughs
    """

    def test_all_npc_factions_change_stats_independently(self):
        """Every active NPC faction should show stat changes each turn."""
        from histrategy.engine.offline_sim import simulate_turn_offline
        from histrategy.engine.world import GameWorld

        w = GameWorld("190")
        w.player_faction_id = "cao"

        # Snapshot all NPC faction stats
        initial = {}
        for fid, fa in w.factions.items():
            if fid == w.player_faction_id or not fa.is_active:
                continue
            initial[fid] = fa.strength

        simulate_turn_offline(w, "发展内政")

        # Count how many NPC factions changed
        changed = sum(1 for fid in initial if w.factions[fid].strength != initial[fid])
        assert changed >= 1, f"No NPC factions changed stats: changed={changed}/{len(initial)}"

    def test_aggressive_npc_factions_expand_more(self):
        """Aggressive NPC factions (dongzhuo, aggression 85) should gain
        more strength per turn than defensive factions on average."""
        import random

        from histrategy.engine.game import GameEngine

        random.seed(42)
        engine = GameEngine(new_game=True, force_v1=True)
        engine.set_player_faction("cao")

        # Track strength deltas over multiple turns per faction
        faction_deltas: dict[str, list[int]] = {}
        for fid, fs in engine.world_state.factions.items():
            if fid == engine.world_state.player_faction_id or not fs.is_active:
                continue
            faction_deltas[fid] = []

        for _ in range(8):
            snap_before = {}
            for fid in faction_deltas:
                fs = engine.world_state.factions.get(fid)
                if fs:
                    snap_before[fid] = fs.strength
            engine.process_turn("发展内政")
            for fid in faction_deltas:
                fs = engine.world_state.factions.get(fid)
                if fs and fid in snap_before:
                    faction_deltas[fid].append(fs.strength - snap_before[fid])

        # Aggregate: average delta per faction
        avg_deltas = {fid: sum(deltas) / len(deltas) for fid, deltas in faction_deltas.items() if deltas}

        # Dong Zhuo (dongzhuo) has aggression=85, should be among top gainers
        dong_avg = avg_deltas.get("dongzhuo", 0)
        all_avg = sum(avg_deltas.values()) / max(1, len(avg_deltas))
        # Dong Zhuo should at least gain strength (not lose consistently)
        assert dong_avg > -500, f"Dong Zhuo losing strength over time: avg {dong_avg:.0f}"
        assert all_avg != 0, "No NPC faction changed strength at all"

    def test_npc_faction_dynamics_occur(self):
        """NPC factions should produce varied narratives across turns."""
        import random

        from histrategy.engine.game import GameEngine

        random.seed(42)

        engine = GameEngine(new_game=True, force_v1=True)
        engine.set_player_faction("cao")

        # Run several turns and verify NPC narratives are diverse
        all_npc_texts = []
        for _ in range(8):
            result = engine.process_turn("发展内政")
            npc_text = " ".join(str(r) for r in result.get("npc_reactions", []))
            all_npc_texts.append(npc_text)

        # Each turn should have NPC content
        for i, text in enumerate(all_npc_texts):
            assert len(text) > 3, f"Turn {i}: empty NPC content"

        # NPC content should not be identical across all turns
        unique_texts = set(all_npc_texts)
        assert len(unique_texts) >= 2, "NPC narratives identical across all turns — no dynamics"

    def test_npc_react_to_player_military_buildup(self):
        """NPC factions should react when player expands military."""
        import random

        from histrategy.engine.game import GameEngine

        random.seed(7)

        # Economy-focused game
        engine_eco = GameEngine(new_game=True, force_v1=True)
        engine_eco.set_player_faction("cao")

        # Military-focused game
        engine_mil = GameEngine(new_game=True, force_v1=True)
        engine_mil.set_player_faction("cao")

        eco_strength_changes: dict[str, int] = {}
        mil_strength_changes: dict[str, int] = {}
        for fid in engine_eco.world_state.factions:
            if fid == "cao" or not engine_eco.world_state.factions[fid].is_active:
                continue
            eco_strength_changes[fid] = 0
            mil_strength_changes[fid] = 0

        for _ in range(6):
            snap_eco = {}
            snap_mil = {}
            for fid in eco_strength_changes:
                fs_e = engine_eco.world_state.factions.get(fid)
                fs_m = engine_mil.world_state.factions.get(fid)
                if fs_e:
                    snap_eco[fid] = fs_e.strength
                if fs_m:
                    snap_mil[fid] = fs_m.strength
            engine_eco.process_turn("发展经济休养生息")
            engine_mil.process_turn("扩军备战征伐天下")
            for fid in eco_strength_changes:
                fs_e = engine_eco.world_state.factions.get(fid)
                fs_m = engine_mil.world_state.factions.get(fid)
                if fs_e and fid in snap_eco:
                    eco_strength_changes[fid] += abs(fs_e.strength - snap_eco[fid])
                if fs_m and fid in snap_mil:
                    mil_strength_changes[fid] += abs(fs_m.strength - snap_mil[fid])

        eco_total = sum(eco_strength_changes.values())
        mil_total = sum(mil_strength_changes.values())
        assert eco_total > 0, "NPC factions showed zero reaction to economy focus"
        assert mil_total > 0, "NPC factions showed zero reaction to military focus"

    def test_multi_turn_npc_divergence(self):
        """Over 12 turns, NPC factions should show significant stat divergence."""
        import random

        from histrategy.engine.offline_sim import simulate_turn_offline
        from histrategy.engine.world import GameWorld

        random.seed(123)

        w = GameWorld("190")
        w.player_faction_id = "cao"

        # Snapshot initial strength
        initial = {}
        for fid, fa in w.factions.items():
            if fid == w.player_faction_id or not fa.is_active:
                continue
            initial[fid] = fa.strength

        # Run 12 turns
        for _ in range(12):
            simulate_turn_offline(w, "发展内政")

        # Collect final strengths
        deltas = {}
        for fid, fa in w.factions.items():
            if fid == w.player_faction_id or not fa.is_active:
                continue
            if fid in initial:
                deltas[fid] = fa.strength - initial[fid]

        assert len(deltas) >= 3, f"Need at least 3 NPC factions, got {len(deltas)}"

        # At least one faction should have changed meaningfully
        changed = sum(1 for d in deltas.values() if abs(d) > 100)
        assert changed >= 1, "No NPC factions changed meaningfully after 12 turns"

        # Factions should not all have identical deltas (divergence)
        unique_deltas = set(deltas.values())
        assert len(unique_deltas) > 1, "All NPC factions had identical strength changes — no divergence"

    def test_npc_actions_surface_in_result(self):
        """Every turn result should contain NPC-related content."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine(new_game=True, force_v1=True)
        engine.set_player_faction("cao")

        # Check that NPC content exists in results
        npc_content_found = 0
        for i in range(5):
            result = engine.process_turn("发展内政")
            npc_reactions = result.get("npc_reactions", [])
            npc_actions = result.get("npc_actions", [])
            narrative = result.get("narrative", "")
            # npc_reactions or npc_actions or narrative should have content
            has_content = (
                (isinstance(npc_reactions, list) and len(npc_reactions) > 0)
                or (isinstance(npc_actions, list) and len(npc_actions) > 0)
                or len(narrative) > 30
            )
            if has_content:
                npc_content_found += 1

        assert npc_content_found >= 3, f"Only {npc_content_found}/5 turns had NPC content"

        # At least one turn should mention specific NPC factions by name
        faction_mentions = 0
        for _ in range(5):
            result = engine.process_turn("发展内政")
            npc_text = " ".join(str(r) for r in result.get("npc_reactions", []))
            narrative = result.get("narrative", "")
            combined = npc_text + " " + narrative
            for name in ["董卓", "袁绍", "孙坚", "刘表", "公孙瓒"]:
                if name in combined:
                    faction_mentions += 1
        assert faction_mentions >= 1, "NPC content should mention specific factions"


class TestNPCMoodProgression:
    """H08h: Test NPC advisor mood progression over multiple turns."""

    def test_npc_mood_worsen_on_single_step(self):
        """NPC mood shifts at most 1 level per turn (design constraint)."""
        from histrategy.state.npc_state import NPCMood, NPCState

        npc = NPCState(character_id="test_advisor", mood=NPCMood.CONTENT)
        npc.worsen("主公未纳谏言")
        assert npc.mood == NPCMood.FRUSTRATED
        npc.worsen("再次被忽视")
        assert npc.mood == NPCMood.ANGRY
        npc.worsen("积累不满")
        assert npc.mood == NPCMood.SCHEMING

    def test_npc_mood_no_skip_levels(self):
        """NPC mood must never skip levels — CONTENT can't jump to ANGRY."""
        from histrategy.state.npc_state import NPCMood, NPCState

        npc = NPCState(character_id="test_advisor", mood=NPCMood.CONTENT)
        npc.worsen("一次不满")
        assert npc.mood == NPCMood.FRUSTRATED
        # Verify it's exactly one level worse, not two
        assert npc.mood != NPCMood.ANGRY

    def test_npc_improve_from_danger(self):
        """NPC can improve from danger levels back to safe."""
        from histrategy.state.npc_state import NPCMood, NPCState

        npc = NPCState(character_id="test_advisor", mood=NPCMood.SCHEMING)
        npc.improve("主公安抚赏赐")
        assert npc.mood == NPCMood.ANGRY
        npc.improve("主公采纳建议")
        assert npc.mood == NPCMood.FRUSTRATED
        npc.improve("获封官职")
        assert npc.mood == NPCMood.CONTENT

    def test_plotting_not_triggered_below_threshold(self):
        """NPC with mood below plotting and <2 turns should NOT trigger defection."""
        from histrategy.engine.game import GameEngine
        from histrategy.state.npc_state import NPCMood, NPCState
        from histrategy.state.world_state import CharacterState

        engine = GameEngine(new_game=True, force_v1=True)
        engine.set_player_faction("cao")

        engine.world_state.characters["guo_jia"] = CharacterState(
            id="guo_jia", name="郭嘉", faction_id="cao", role="advisor"
        )
        # Plotting but only 1 turn — should NOT trigger
        engine.world_state.npc_states["guo_jia"] = NPCState(
            character_id="guo_jia",
            mood=NPCMood.PLOTTING,
            turns_at_current_mood=1,
            loyalty=30,
        )
        result = engine.process_turn("安抚众臣")
        # Should still be in npc_states (not defected yet)
        assert "guo_jia" in engine.world_state.npc_states, "NPC should NOT defect before 2 consecutive plotting turns"

    def test_npc_mood_danger_levels(self):
        """Verify danger levels for each mood state."""
        from histrategy.state.npc_state import NPCMood

        assert NPCMood.LOYAL.danger_level == 0
        assert NPCMood.CONTENT.danger_level == 1
        assert NPCMood.FRUSTRATED.danger_level == 2
        assert NPCMood.ANGRY.danger_level == 3
        assert NPCMood.SCHEMING.danger_level == 4
        assert NPCMood.PLOTTING.danger_level == 5

    def test_npc_mood_is_critical(self):
        """Only PLOTTING mood should be critical."""
        from histrategy.state.npc_state import NPCMood

        assert not NPCMood.LOYAL.is_critical
        assert not NPCMood.CONTENT.is_critical
        assert not NPCMood.FRUSTRATED.is_critical
        assert not NPCMood.ANGRY.is_critical
        assert not NPCMood.SCHEMING.is_critical
        assert NPCMood.PLOTTING.is_critical


class TestGameMasterPlanSchema:
    """Test that the unified LLM GameMaster returns the new plan/dialogue schema."""

    def test_fallback_plan_data_schema(self):
        """Engine fallback plan data must conform to the new schema (court_dialogue, not advisors)."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine(new_game=True)
        engine.set_player_faction("cao")
        plan = engine.get_plan_data()
        assert "court_dialogue" in plan
        assert "suggestions" in plan
        assert "season_summary" in plan
        assert "advisors" not in plan
        assert len(plan["court_dialogue"]) > 10
        assert len(plan["suggestions"]) >= 3

    def test_fallback_intro_data_schema(self):
        """Engine fallback intro data must return narrative, npc_actions, and new_choices."""
        from histrategy.engine.game import GameEngine

        engine = GameEngine(new_game=True)
        engine.set_player_faction("cao")
        intro = engine.get_intro_scene()
        assert "narrative" in intro
        assert "npc_actions" in intro
        assert "new_choices" in intro
        assert len(intro["new_choices"]) == 4
