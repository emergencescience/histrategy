"""
Scenario Loader — 多场景支持的核心加载器。

从 scenarios/{id}/ 目录加载场景配置和 knowledge 数据。
向后兼容 GameRoom.scenario = "207" → 映射到 three-kingdoms 场景。

Usage:
    loader = ScenarioLoader("three-kingdoms")
    factions = loader.load_factions()
    territories = loader.load_territories()
    config = loader.config  # scenario.toml as dict
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("histrategy.scenario")

# ── Scenario ID Mapping (backward compat) ─────────────────

LEGACY_TO_ID: dict[str, str] = {
    "207": "three-kingdoms",
    "190": "three-kingdoms",  # 190 scenario also maps to three-kingdoms
}

# ── Resolution ────────────────────────────────────────────


def resolve_scenarios_root() -> str:
    """Find the scenarios/ root directory.

    Resolution order:
    1. HISTRATEGY_SCENARIOS_DIR env var
    2. ../scenarios/ relative to histrategy package
    3. ../../scenarios/ relative to histrategy package
    """
    env_dir = os.environ.get("HISTRATEGY_SCENARIOS_DIR", "")
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "scenarios"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scenarios"),
        os.path.join(os.path.dirname(__file__), "..", "scenarios"),
    ]
    for cand in candidates:
        abs_path = os.path.abspath(cand)
        if os.path.isdir(abs_path):
            return abs_path

    raise FileNotFoundError(
        "Cannot locate scenarios/ directory. "
        "Set HISTRATEGY_SCENARIOS_DIR or run from repo root."
    )


def _normalize_scenario_id(raw: str | None) -> str:
    """Normalize scenario ID, mapping legacy IDs to new ones."""
    if not raw:
        return "three-kingdoms"
    return LEGACY_TO_ID.get(raw, raw)


# ── Loader ────────────────────────────────────────────────


@dataclass
class ScenarioConfig:
    """Parsed scenario.toml configuration."""

    meta: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    factions: dict = field(default_factory=dict)
    display: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    db: dict = field(default_factory=dict)

    @classmethod
    def from_toml(cls, path: str) -> ScenarioConfig:
        """Parse scenario.toml into ScenarioConfig.

        Uses a simple TOML parser (no third-party dependency).
        """
        config = cls()
        current_section = "meta"

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Section header
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1].strip()
                    if "." in current_section:
                        current_section = current_section.split(".")[0]
                    continue
                # Key = Value
                if "=" in line:
                    key, _, raw_value = line.partition("=")
                    key = key.strip()
                    raw_value = raw_value.strip()
                    
                    # Extract the actual value (handle quoted strings and inline comments)
                    value = raw_value  # fallback
                    if raw_value.startswith('"'):
                        # Find closing quote
                        end_quote = raw_value.find('"', 1)
                        if end_quote > 0:
                            value = raw_value[1:end_quote]
                    elif raw_value.startswith("'"):
                        end_quote = raw_value.find("'", 1)
                        if end_quote > 0:
                            value = raw_value[1:end_quote]
                    else:
                        # Unquoted: strip inline comment
                        if "#" in raw_value:
                            value = raw_value.split("#")[0].strip()
                        else:
                            value = raw_value
                    # Type coercion (only for string values)
                    if isinstance(value, str):
                        if value in ("true", "True"):
                            value = True
                        elif value in ("false", "False"):
                            value = False
                        elif value.isdigit():
                            value = int(value)
                        elif value.replace(".", "").replace("-", "").isdigit():
                            try:
                                value = float(value)
                            except ValueError:
                                pass

                    section_dict = getattr(config, current_section, {})
                    if isinstance(section_dict, dict):
                        section_dict[key] = value
        return config

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a config value with default."""
        section_dict = getattr(self, section, {})
        if isinstance(section_dict, dict):
            return section_dict.get(key, default)
        return default


class ScenarioLoader:
    """Loads scenario data: config, knowledge, prompts, rules.

    Usage:
        loader = ScenarioLoader("three-kingdoms")
        factions = loader.load_json("factions.json")
        config = loader.config
    """

    def __init__(self, scenario_id: str | None = None):
        self.scenario_id = _normalize_scenario_id(scenario_id)
        self.scenarios_root = resolve_scenarios_root()
        self.scenario_dir = os.path.join(self.scenarios_root, self.scenario_id)

        if not os.path.isdir(self.scenario_dir):
            raise FileNotFoundError(
                f"Scenario '{self.scenario_id}' not found at {self.scenario_dir}"
            )

        # Load config
        toml_path = os.path.join(self.scenario_dir, "scenario.toml")
        if os.path.isfile(toml_path):
            self.config = ScenarioConfig.from_toml(toml_path)
        else:
            logger.warning("scenario.toml not found for %s, using defaults", self.scenario_id)
            self.config = ScenarioConfig()

        self.knowledge_dir = os.path.join(self.scenario_dir, "knowledge")
        self.prompts_dir = os.path.join(self.scenario_dir, "prompts")
        self.rules_dir = os.path.join(self.scenario_dir, "rules")

    # ── Knowledge Loading ────────────────────────────

    def load_json(self, filename: str) -> Any:
        """Load a JSON file from the knowledge directory."""
        filepath = os.path.join(self.knowledge_dir, filename)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(
                f"Knowledge file '{filename}' not found in {self.knowledge_dir}"
            )
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)

    def load_factions(self) -> list[dict]:
        """Load faction definitions."""
        filename = self.config.get("knowledge", "factions_file", "factions.json")
        return self.load_json(filename)

    def load_characters(self) -> list[dict]:
        """Load character definitions."""
        filename = self.config.get("knowledge", "characters_file", "characters.json")
        return self.load_json(filename)

    def load_regions(self) -> list[dict]:
        """Load region/territory definitions."""
        filename = self.config.get("knowledge", "regions_file", "regions.json")
        return self.load_json(filename)

    def load_events(self) -> list[dict]:
        """Load historical event definitions."""
        filename = self.config.get("knowledge", "events_file", "events.json")
        return self.load_json(filename)

    def load_arc_goals(self) -> list[dict]:
        """Load story arc goals."""
        filename = self.config.get("knowledge", "arc_goals_file", "arc_goals.json")
        return self.load_json(filename)

    def load_roster(self) -> dict | list:
        """Load character roster with stats."""
        filename = self.config.get("knowledge", "roster_file", "roster.json")
        return self.load_json(filename)

    def load_territories(self) -> dict | list:
        """Load detailed territory data."""
        filename = self.config.get("knowledge", "territories_file", "territories.json")
        return self.load_json(filename)

    def load_timeline(self) -> dict | list:
        """Load historical timeline."""
        filename = self.config.get("knowledge", "timeline_file", "timeline.json")
        return self.load_json(filename)

    # ── Prompt Loading ───────────────────────────────

    def load_prompt(self, name: str) -> str | None:
        """Load a prompt template file.

        Args:
            name: Prompt name without extension (e.g. 'system', 'plan_mode')
        """
        for ext in (".md", ".txt"):
            filepath = os.path.join(self.prompts_dir, f"{name}{ext}")
            if os.path.isfile(filepath):
                with open(filepath, encoding="utf-8") as f:
                    return f.read()
        return None

    def get_system_prompt(self, engine_version: str = "v3") -> str | None:
        """Get the system prompt for the given engine version."""
        # Try version-specific first, then generic
        prompt = self.load_prompt(f"system_{engine_version}")
        if prompt:
            return prompt
        return self.load_prompt("system")

    # ── Rule Loading ─────────────────────────────────

    def load_rules(self, filename: str | None = None) -> dict | None:
        """Load YAML rule definitions."""
        import yaml

        if filename:
            filepath = os.path.join(self.rules_dir, filename)
            if os.path.isfile(filepath):
                with open(filepath, encoding="utf-8") as f:
                    return yaml.safe_load(f)
            return None

        # Load all rules
        rules = {}
        if os.path.isdir(self.rules_dir):
            for fname in sorted(os.listdir(self.rules_dir)):
                if fname.endswith((".yaml", ".yml")):
                    filepath = os.path.join(self.rules_dir, fname)
                    with open(filepath, encoding="utf-8") as f:
                        rules[fname] = yaml.safe_load(f)
        return rules if rules else None

    # ── Utility ──────────────────────────────────────

    def get_starting_state(self) -> dict:
        """Get initial world state for this scenario."""
        return {
            "scenario": self.scenario_id,
            "year": self.config.get("meta", "start_year", 207),
            "season": self.config.get("meta", "start_season", "冬"),
            "engine_version": self.config.get("engine", "default_version", "v3"),
        }

    def list_available_scenarios() -> list[dict]:
        """List all available scenarios."""
        try:
            root = resolve_scenarios_root()
        except FileNotFoundError:
            return []

        scenarios = []
        for entry in sorted(os.listdir(root)):
            entry_path = os.path.join(root, entry)
            if not os.path.isdir(entry_path):
                continue
            toml_path = os.path.join(entry_path, "scenario.toml")
            if not os.path.isfile(toml_path):
                continue

            try:
                config = ScenarioConfig.from_toml(toml_path)
            except Exception:
                config = ScenarioConfig()

            scenarios.append({
                "id": entry,
                "name": config.get("meta", "name", entry),
                "era": config.get("meta", "era", ""),
                "start_year": config.get("meta", "start_year", 0),
                "icon": config.get("display", "icon", "🎮"),
                "description": config.get("meta", "description", ""),
            })

        return scenarios


# ── Singleton ─────────────────────────────────────────────


_scenario_cache: dict[str, ScenarioLoader] = {}


def get_scenario_loader(scenario_id: str | None = None) -> ScenarioLoader:
    """Get or create a cached ScenarioLoader."""
    sid = _normalize_scenario_id(scenario_id)
    if sid not in _scenario_cache:
        _scenario_cache[sid] = ScenarioLoader(sid)
    return _scenario_cache[sid]


def get_default_scenario_id() -> str:
    """Get the default scenario from env or fallback to three-kingdoms."""
    return os.environ.get("HISTRATEGY_SCENARIO", "three-kingdoms")
