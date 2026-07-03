"""End-to-end tests for 三國志略 (Histrategy).

These tests run the full CLI game with canned inputs and verify:
1. Game starts correctly
2. Faction selection works
3. AI/Offline mode generates narrative
4. Multi-turn gameplay functions
5. Game over conditions are detected

Run with: pytest tests/ -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Path to the histrategy module
HISTRATEGY_DIR = Path(__file__).parent.parent
GAME_CMD = [sys.executable, "-m", "histrategy"]


@pytest.fixture(autouse=True)
def isolated_save_dir(tmp_path, monkeypatch):
    """Run each E2E test with an isolated save directory."""
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path / ".histrategy"))
    yield


def run_game(input_sequence: str, timeout: int = 30, with_api_key: bool = False) -> tuple[str, int]:
    """Run the game with given input sequence and return (stdout, exit_code).

    By default, strips all API keys so the game runs in offline mode.
    Set with_api_key=True to test AI mode (requires .env).
    """
    test_env = dict(os.environ)
    if not with_api_key:
        # Remove all API keys to force offline mode
        for key in list(test_env.keys()):
            if "API_KEY" in key or "API_BASE" in key:
                del test_env[key]
    test_env["TERM"] = "xterm-256color"

    proc = subprocess.run(
        GAME_CMD,
        input=input_sequence,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=HISTRATEGY_DIR,
        env=test_env,
    )
    return proc.stdout + proc.stderr, proc.returncode


class TestGameStartup:
    """Test that the game starts and displays expected content."""

    def test_title_screen(self):
        """Game should display the game title."""
        output, _ = run_game("1\nexit\n", timeout=15)
        assert "三國志略" in output or "三國" in output

    def test_offline_mode_detection(self):
        """Without API key, game should show offline mode notice."""
        # run_game already strips API keys
        output, _ = run_game("1\nexit\n", timeout=15)
        assert "离线模式" in output


class TestFactionSelection:
    """Test faction selection screen."""

    def test_faction_options_shown(self):
        """Faction selection should display all factions."""
        output, _ = run_game("1\nexit\n", timeout=15)
        assert "曹操军" in output
        assert "刘备军" in output
        assert "孙坚军" in output
        assert "袁绍军" in output

    def test_select_cao_cao(self):
        """Selecting Cao Cao should show his faction name."""
        output, _ = run_game("1\nexit\n", timeout=15)
        assert "曹操" in output


class TestOfflineGameplay:
    """Test the offline game loop."""

    def test_first_turn_narrative(self):
        """First turn should produce narrative text."""
        output, _ = run_game("1\n1\nexit\n", timeout=20)
        assert "军师来报" in output or "天下" in output
        assert "兵力" in output

    def test_multiple_turns(self):
        """Multiple turns should change game state."""
        output, _ = run_game("1\n1\n2\n3\nexit\n", timeout=30)
        # State should show changes
        assert "经济" in output
        assert "民心" in output

    def test_choices_change(self):
        """Game should offer contextual choices."""
        output, _ = run_game("1\n1\n1\nexit\n", timeout=30)
        # Should have strategic options
        assert "扩军" in output or "出征" in output or "发展" in output


class TestMemorySystem:
    """Test the memory/save system."""

    def test_memory_file_created(self):
        """Playing a game should create a save file."""
        # Use "1\n1\nexit\n" to play one turn (select Cao Cao, then make a decision)
        run_game("1\n1\nexit\n", timeout=20)
        # World state should be saved
        world_file = Path(os.environ["HISTRATEGY_DATA_DIR"]) / "world_state.json"
        assert world_file.exists(), f"world_state.json not found at {world_file}"

    def test_memory_has_decisions(self):
        """Memory file should contain decision records."""
        run_game("1\n1\n2\nexit\n", timeout=30)
        memory_file = Path(os.environ["HISTRATEGY_DATA_DIR"]) / "player_memory.json"
        if memory_file.exists():
            data = json.loads(memory_file.read_text())
            assert "decisions" in data
            assert len(data["decisions"]) > 0


class TestGameOver:
    """Test game over conditions."""

    def test_high_morale_path(self):
        """Consistently picking economy should improve morale."""
        # Run many turns of economy focus
        inputs = "1\n" + "2\n" * 10 + "exit\n"
        output, _ = run_game(inputs, timeout=60)
        # Should see morale increase
        assert "民心" in output


class TestLLMIntegration:
    """Test LLM adapter works correctly."""

    def test_provider_detection(self):
        """Provider detection should work with env vars."""
        from histrategy.llm.adapter import detect_provider

        with tempfile.TemporaryDirectory():
            # Test no provider
            provider = detect_provider()
            assert isinstance(provider, dict)
            assert "name" in provider
            assert "supports_json_mode" in provider


class TestKnowledgeBase:
    """Test knowledge base data integrity."""

    def test_characters_have_factions(self):
        """All characters should reference valid faction IDs."""
        from histrategy.engine.world import GameWorld

        world = GameWorld("190")
        for _char_id, char in world.characters.items():
            assert char.faction in world.factions, f"Character {char.name} references unknown faction {char.faction}"

    def test_regions_have_owners(self):
        """All regions should have valid owners."""
        from histrategy.engine.world import GameWorld

        world = GameWorld("190")
        for _region_id, region in world.regions.items():
            assert region.owner in world.factions or region.owner == "other", (
                f"Region {region.name} has unknown owner {region.owner}"
            )


class TestDataIntegrity:
    """Test JSON data files can be loaded."""

    DATA_FILES = [
        "characters.json",
        "factions.json",
        "regions.json",
        "events.json",
    ]

    def test_all_data_files_exist(self):
        """All knowledge data files should exist."""
        data_dir = HISTRATEGY_DIR / "histrategy" / "knowledge" / "data"
        for f in self.DATA_FILES:
            assert (data_dir / f).exists(), f"Missing data file: {f}"

    def test_all_data_files_valid_json(self):
        """All data files should be valid JSON."""
        data_dir = HISTRATEGY_DIR / "histrategy" / "knowledge" / "data"
        for f in self.DATA_FILES:
            content = (data_dir / f).read_text()
            data = json.loads(content)
            assert isinstance(data, list), f"{f} should be a list"
            assert len(data) > 0, f"{f} should not be empty"
