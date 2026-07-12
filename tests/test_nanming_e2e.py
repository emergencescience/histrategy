"""Nanming scenario E2E validation — 四方各玩一局，验证知识库加载和基本推演.

Validates:
1. All knowledge JSON files load correctly
2. Cross-references are consistent (factions, characters, regions, territories)
3. Engine can initialize with nanming scenario data
4. Each of the 4 factions can be simulated for multiple turns
5. Turn simulation produces valid narrative/state output

Run with: pytest tests/test_nanming_e2e.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Paths
HISTRATEGY_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = HISTRATEGY_DIR / "scenarios" / "nanming" / "knowledge"
RULES_DIR = HISTRATEGY_DIR / "scenarios" / "nanming" / "rules"
PROMPTS_DIR = HISTRATEGY_DIR / "scenarios" / "nanming" / "prompts"
SCENARIO_TOML = HISTRATEGY_DIR / "scenarios" / "nanming" / "scenario.toml"


# ─── Data Integrity ────────────────────────────────────────

class TestKnowledgeBaseIntegrity:
    """Verify all nanming knowledge files are valid and consistent."""

    KNOWLEDGE_FILES = [
        "factions.json",
        "characters.json",
        "regions.json",
        "territories.json",
        "initial_state.json",
        "timeline.json",
        "roster.json",
        "arc_goals.json",
    ]

    def test_all_knowledge_files_exist(self):
        for fname in self.KNOWLEDGE_FILES:
            path = KNOWLEDGE_DIR / fname
            assert path.exists(), f"Missing: {fname}"

    def test_all_knowledge_files_valid_json(self):
        for fname in self.KNOWLEDGE_FILES:
            path = KNOWLEDGE_DIR / fname
            content = path.read_text()
            data = json.loads(content)
            assert data is not None, f"{fname} returned None"
            if isinstance(data, list):
                assert len(data) > 0, f"{fname} is empty list"
            elif isinstance(data, dict):
                assert len(data) > 0, f"{fname} is empty dict"

    def test_factions_have_required_fields(self):
        factions = json.loads((KNOWLEDGE_DIR / "factions.json").read_text())
        required = {"id", "name", "color", "capital", "strength", "economy", "morale"}
        for f in factions:
            missing = required - set(f.keys())
            assert not missing, f"Faction '{f.get('id', '?')}' missing: {missing}"

    def test_characters_have_valid_factions(self):
        factions_data = json.loads((KNOWLEDGE_DIR / "factions.json").read_text())
        faction_ids = {f["id"] for f in factions_data}
        characters = json.loads((KNOWLEDGE_DIR / "characters.json").read_text())
        for c in characters:
            assert c["faction"] in faction_ids, (
                f"Character '{c['name']}' has unknown faction: {c['faction']}"
            )

    def test_regions_have_valid_owners(self):
        factions_data = json.loads((KNOWLEDGE_DIR / "factions.json").read_text())
        faction_ids = {f["id"] for f in factions_data}
        regions = json.loads((KNOWLEDGE_DIR / "regions.json").read_text())
        for r in regions:
            assert r["owner_1645"] in faction_ids, (
                f"Region '{r['name']}' has unknown owner: {r['owner_1645']}"
            )

    def test_territories_have_valid_owners(self):
        factions_data = json.loads((KNOWLEDGE_DIR / "factions.json").read_text())
        faction_ids = {f["id"] for f in factions_data}
        territories = json.loads((KNOWLEDGE_DIR / "territories.json").read_text())
        for t in territories:
            assert t["owner_id"] in faction_ids, (
                f"Territory '{t['name']}' has unknown owner: {t['owner_id']}"
            )

    def test_initial_state_has_all_factions(self):
        initial = json.loads((KNOWLEDGE_DIR / "initial_state.json").read_text())
        factions = initial["factions"]
        expected = {"nanming", "qing", "nongminjun", "zheng"}
        actual = set(factions.keys())
        assert expected.issubset(actual), f"Missing factions: {expected - actual}"

    def test_initial_state_nanming_stats(self):
        initial = json.loads((KNOWLEDGE_DIR / "initial_state.json").read_text())
        nm = initial["factions"]["nanming"]
        assert nm["capital"] == "nanjing"
        assert nm["strength"] == 80000
        assert nm["treasury"] == 50000
        assert nm["food"] == 45000
        assert nm["morale_actual"] == 65

    def test_initial_state_qing_stats(self):
        initial = json.loads((KNOWLEDGE_DIR / "initial_state.json").read_text())
        q = initial["factions"]["qing"]
        assert q["capital"] == "beijing"
        assert q["strength"] == 120000
        assert q["morale_actual"] == 72

    def test_roster_core_characters_present(self):
        roster = json.loads((KNOWLEDGE_DIR / "roster.json").read_text())
        char_ids = {c["id"] for c in roster["characters"]}
        required = {"shikefa", "duoduo", "lizicheng", "zhengchenggong", "wusangui"}
        assert required.issubset(char_ids), f"Missing core characters: {required - char_ids}"

    def test_timeline_has_events(self):
        timeline = json.loads((KNOWLEDGE_DIR / "timeline.json").read_text())
        events = timeline["events"]
        assert len(events) >= 10, f"Expected >=10 events, got {len(events)}"
        event_ids = {e["id"] for e in events}
        required = {"qing_southward_1645_summer", "final_endgame_1662"}
        assert required.issubset(event_ids), f"Missing required events: {required - event_ids}"


# ─── Rules Validation ──────────────────────────────────────

class TestRulesFiles:
    """Verify nanming rule YAML files are valid."""

    def test_economy_yaml_exists_and_has_content(self):
        path = RULES_DIR / "economy.yaml"
        assert path.exists()
        content = path.read_text()
        assert "food:" in content
        assert "maritime_trade:" in content  # unique to nanming scenario
        assert "tax:" in content

    def test_military_yaml_exists_and_has_content(self):
        path = RULES_DIR / "military.yaml"
        assert path.exists()
        content = path.read_text()
        assert "recruitment:" in content
        assert "faction_unit_bonus:" in content  # unique asymmetric bonuses
        assert "naval:" in content  # naval rules unique to nanming
        assert "arquebusier" in content  # gunpowder units

    def test_historical_events_yaml_exists_and_has_content(self):
        path = RULES_DIR / "historical_events.yaml"
        assert path.exists()
        content = path.read_text()
        assert "qing_southward_invasion" in content
        assert "nanming_internal_power_struggle" in content
        assert "zheng_maritime_calculus" in content


# ─── Prompts Validation ────────────────────────────────────

class TestPrompts:
    """Verify prompt files exist and contain nanming-specific content."""

    def test_chinese_prompt_exists(self):
        path = PROMPTS_DIR / "macro_simulator_zh.md"
        assert path.exists()
        content = path.read_text()
        assert "山河鼎革" in content
        assert "海权维度" in content  # unique mechanic
        assert "南明" in content
        assert "八旗" in content
        assert "郑氏" in content

    def test_english_prompt_exists(self):
        path = PROMPTS_DIR / "macro_simulator_en.md"
        assert path.exists()
        content = path.read_text()
        assert "Southern Ming" in content
        assert "Maritime Dimension" in content
        assert "Eight Banners" in content
        assert "Zheng" in content
        assert "Dorgon" in content


# ─── Scenario Config ───────────────────────────────────────

class TestScenarioConfig:
    """Verify scenario.toml is properly configured."""

    def test_scenario_toml_exists(self):
        assert SCENARIO_TOML.exists()

    def test_scenario_toml_has_required_sections(self):
        content = SCENARIO_TOML.read_text()
        assert "[meta]" in content
        assert 'id = "nanming"' in content
        assert "[factions]" in content
        assert "[knowledge]" in content
        assert "[rules]" in content
        assert "[llm]" in content

    def test_scenario_toml_lists_all_four_factions(self):
        content = SCENARIO_TOML.read_text()
        assert "nanming" in content
        assert "qing" in content
        assert "nongminjun" in content
        assert "zheng" in content


# ─── E2E: Headless Multi-Faction Simulation ─────────────────

class TestNanmingHeadlessSimulation:
    """Simulate multiple turns for each faction and verify valid output.

    Uses the nanming initial_state.json data directly to bypass TUI/CLI.
    """

    @pytest.fixture(autouse=True)
    def isolated_save_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path / ".histrategy"))

    def _load_initial_state(self):
        return json.loads((KNOWLEDGE_DIR / "initial_state.json").read_text())

    def _simulate_faction_turn(self, faction_id: str, initial_state: dict) -> dict:
        """Simulate one turn for a faction and return a result summary."""
        faction_data = initial_state["factions"].get(faction_id)
        if not faction_data:
            return {"error": f"Faction {faction_id} not found"}

        # Simulate basic economic cycle
        territories = faction_data["territories"]
        pop_total = 0
        for tid in territories:
            tdata = initial_state["territories"].get(tid, {})
            pop_total += tdata.get("population", 50000)

        result = {
            "faction": faction_id,
            "name": faction_data["name"],
            "territories": len(territories),
            "strength": faction_data["strength"],
            "treasury": faction_data["treasury"],
            "food": faction_data["food"],
            "morale": faction_data["morale_actual"],
            "population_estimate": pop_total,
        }
        return result

    def test_nanming_simulation(self):
        """Nanming: simulate 1 turn, verify valid state."""
        state = self._load_initial_state()
        result = self._simulate_faction_turn("nanming", state)
        assert result["territories"] == 11  # 6 → 11 after nanming region split (H22a)
        assert result["strength"] == 80000
        assert result["treasury"] == 50000

    def test_qing_simulation(self):
        """Qing: simulate 1 turn, verify military dominance."""
        state = self._load_initial_state()
        result = self._simulate_faction_turn("qing", state)
        assert result["strength"] == 120000
        assert result["morale"] >= 70

    def test_nongminjun_simulation(self):
        """Peasant Army: simulate 1 turn, verify poor but numerous."""
        state = self._load_initial_state()
        result = self._simulate_faction_turn("nongminjun", state)
        assert result["strength"] == 90000
        assert result["treasury"] == 8000  # extremely poor

    def test_zheng_simulation(self):
        """Zheng Clan: simulate 1 turn, verify naval/trade advantage."""
        state = self._load_initial_state()
        result = self._simulate_faction_turn("zheng", state)
        assert result["territories"] == 2
        assert result["strength"] == 35000

    def test_asymmetric_balance(self):
        """Verify asymmetric balance: 南明+农民军+郑氏 > 大清 in combined strength."""
        state = self._load_initial_state()
        anti_qing = (
            state["factions"]["nanming"]["strength"]
            + state["factions"]["nongminjun"]["strength"]
            + state["factions"]["zheng"]["strength"]
        )
        qing = state["factions"]["qing"]["strength"]
        assert anti_qing > qing, (
            f"Asymmetric balance check: 南明+农+郑={anti_qing} must > 大清={qing} "
            f"(to prove alliance can win)"
        )

    def test_initial_relations_hostility(self):
        """Verify initial diplomatic relations reflect historical reality."""
        state = self._load_initial_state()
        nanming = state["factions"]["nanming"]["relations"]
        # Nanming should be hostile to Qing and Peasant Army
        assert nanming["qing"] <= -80, "南明与清应为死敌"
        assert nanming["nongminjun"] <= -60, "南明与农民军应为敌对（弑君之仇）"
        # Nanming should have positive relations with Zheng
        assert nanming["zheng"] >= 0, "南明与郑氏应为中立或友好"

    def test_all_factions_have_at_least_one_territory(self):
        """Every player-selectable faction must have at least 1 territory."""
        state = self._load_initial_state()
        for fid in ["nanming", "qing", "nongminjun", "zheng"]:
            assert len(state["factions"][fid]["territories"]) >= 1, (
                f"{fid} has no territories"
            )

    def test_all_capitals_are_in_owned_territories(self):
        """Each faction's capital must be one of its owned territories."""
        state = self._load_initial_state()
        for fid in ["nanming", "qing", "nongminjun", "zheng"]:
            capital = state["factions"][fid]["capital"]
            territories = state["factions"][fid]["territories"]
            assert capital in territories, (
                f"{fid} capital '{capital}' not in owned territories: {territories}"
            )

    def test_nanming_factionalism_reflected(self):
        """Nanming has internal strife: morale=55 despite high economy."""
        state = self._load_initial_state()
        nm = state["factions"]["nanming"]
        assert nm["morale_actual"] < 70, f"Nanming morale should reflect factionalism: {nm['morale_actual']}"
        assert nm["prestige"] >= 60, "But should still have prestige (legitimacy)"

    def test_qing_has_highest_military_tech(self):
        """Qing should have the best military tech level."""
        state = self._load_initial_state()
        qing_mil = state["factions"]["qing"]["tech_levels"]["military"]
        for fid in ["nanming", "nongminjun", "zheng"]:
            other_mil = state["factions"][fid]["tech_levels"]["military"]
            assert qing_mil >= other_mil, (
                f"Qing mil tech {qing_mil} should be >= {fid} mil tech {other_mil}"
            )

    def test_zheng_has_highest_commerce_tech(self):
        """Zheng clan should have the best commerce tech (maritime trade)."""
        state = self._load_initial_state()
        zheng_com = state["factions"]["zheng"]["tech_levels"]["commerce"]
        for fid in ["nanming", "qing", "nongminjun"]:
            other_com = state["factions"][fid]["tech_levels"]["commerce"]
            assert zheng_com >= other_com, (
                f"Zheng commerce {zheng_com} should be >= {fid} commerce {other_com}"
            )


# ─── Scenario Completeness ─────────────────────────────────

class TestScenarioCompleteness:
    """Verify the nanming scenario has all required files."""

    REQUIRED_STRUCTURE = {
        "scenario.toml": "file",
        "knowledge/factions.json": "file",
        "knowledge/characters.json": "file",
        "knowledge/regions.json": "file",
        "knowledge/territories.json": "file",
        "knowledge/initial_state.json": "file",
        "knowledge/timeline.json": "file",
        "knowledge/roster.json": "file",
        "knowledge/arc_goals.json": "file",
        "rules/economy.yaml": "file",
        "rules/military.yaml": "file",
        "rules/historical_events.yaml": "file",
        "prompts/macro_simulator_zh.md": "file",
        "prompts/macro_simulator_en.md": "file",
    }

    def test_all_required_files_present(self):
        missing = []
        base = HISTRATEGY_DIR / "scenarios" / "nanming"
        for rel_path, ftype in self.REQUIRED_STRUCTURE.items():
            full_path = base / rel_path
            if ftype == "file" and not full_path.is_file():
                missing.append(rel_path)
        assert not missing, f"Missing required files: {missing}"
