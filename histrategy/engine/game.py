"""
三國志略 — Game Engine

The engine orchestrates the GameMaster (LLM-driven), world state,
and player memory. It provides a unified interface for the CLI.

v2 mode: Uses histrategy-engine package (Map/Character/Domestic/Military/
Decision/Turn/History engines) + NarrativeEngine for read-only narration.
Falls back to v1 when histrategy-engine is not importable.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

# ─── v1 imports (always available) ────────────────────────────────
from ..engine.world import GameWorld
from ..engine.world_sim_interface import WorldSimEngine
from ..llm.adapter import LLMAdapter
from ..llm.game_master import GameMaster
from ..state.world_state import (
    FactionState,
    WorldState,
    has_existing_game,
    load_world,
    save_world,
)

if TYPE_CHECKING:
    from histrategy_engine.ai import DecisionEngine
    from histrategy_engine.character import CharacterEngine
    from histrategy_engine.domestic import DomesticEngine
    from histrategy_engine.history import HistoryEngine
    from histrategy_engine.map import MapEngine
    from histrategy_engine.military import MilitaryEngine
    from histrategy_engine.turn import TurnController
    from histrategy_engine.world import TurnResult
    from histrategy_engine.world import WorldState as V2WorldState

# ─── v2 engine (always available) ────────────────────────────────

from histrategy_engine import (
    CharacterEngine,
    DecisionEngine,
    DomesticEngine,
    HistoryEngine,
    MapEngine,
    MilitaryEngine,
    TurnController,
)
from histrategy_engine import (
    WorldState as V2WorldState,
)
from histrategy_engine.world import TurnResult

# ─── Macro engine: first-turn hard-coded suggestions ───────────
# Skip LLM call on turn 0 — all factions start from the same 207 scenario
# Saves ~18s latency with flash model, ~40s with pro model

FIRST_TURN_SUGGESTIONS = {
    "cao": [
        "【南征荆州】整编水师于邺城玄武池，命于禁毛玠督练，准备南征刘表",
        "【安抚河北】降低冀州税率至20%，安抚新附之民，巩固河北后方",
        "【屯田许昌】在许昌周边推行军屯，储备南征粮草",
        "【劝降孙权】遣使赴江东，以朝廷名义封孙权为讨虏将军，试探其意",
    ],
    "shu": [
        "【三顾茅庐】携关羽张飞再赴隆中，以诚心感动诸葛亮，求问天下大计",
        "【练兵新野】在新野招募训练新兵，扩充军力以备不时之需",
        "【结好刘表】遣简雍赴襄阳，以宗室之谊请求刘表支援粮草军械",
        "【北境设防】命赵云巡视新野北境，设烽火台警戒宛城曹军动向",
    ],
    "wu": [
        "【水军扩建】命周瑜在鄱阳湖大造战船，扩编水军至三万",
        "【稳定山越】派程普鲁肃安抚山越诸部，巩固江东后方",
        "【联刘抗曹】遣鲁肃赴新野，以吊刘表之名探刘备虚实，商议联盟",
        "【发展江东】降低吴郡会稽税率，鼓励农商，充实府库",
    ],
}


def create_initial_world(player_faction_id: str) -> WorldState:
    """Create a fresh world state for a new game (v1).

    Faction data is loaded from the scenario JSON (e.g. 207_liubei.json)
    rather than hardcoded Python dicts.
    """
    from ..engine.log_exporter import clear_session_log
    from .loader import load_scenario

    clear_session_log()

    state = WorldState()
    state.scenario = "three-kingdoms"
    state.player_faction_id = player_faction_id

    scenario = load_scenario("207")
    factions_data = scenario.get("factions", {}) if scenario else {}

    for fid, fd in factions_data.items():
        state.factions[fid] = FactionState(
            id=fid,
            name=fd["name"],
            ruler_id=fd.get("ruler", ""),
            capital=fd.get("capital", ""),
            strength=fd.get("strength", 5000),
            economy=fd.get("economy", 50),
            morale=fd.get("morale_actual", 50),
            treasury=fd.get("treasury", 5000),
            food=fd.get("food", 3000),
            territories=list(fd.get("territories", [])),
        )

    save_world(state)
    return state


# ─── V2 faction maps ──────────────────────────────────────────────

V2_FACTION_MAP: dict[str, str] = {
    "cao": "cao",
    "wei": "cao",
    "shu": "shu",
    "wu": "wu",
    "liubei": "shu",
    "caocao": "cao",
    "sunquan": "wu",
    "sunjian": "wu",
}


class GameEngine:
    """
    Main game engine orchestrating world state and LLM interaction.

    v2 mode (default when histrategy-engine is available):
      Uses the 7-engine physics backend + NarrativeEngine for narration.

    v1 fallback (when histrategy-engine is not importable):
      Uses GameMaster (LLM) or offline_sim (template-based).
    """

    def __init__(
        self,
        llm: LLMAdapter | None = None,
        scenario: str = "three-kingdoms",
        new_game: bool = False,
        sim_engine: WorldSimEngine | None = None,
        force_v1: bool = False,
    ):
        self.llm = llm
        self.scenario = scenario
        force_v1_env = os.environ.get("HISTRATEGY_FORCE_V1", "").lower() in ("true", "1")
        self._use_v2 = not force_v1 and not force_v1_env
        self._use_v3 = False
        self._use_macro = False

        # Detect scenario language early (needed by NarrativeEngine in _build_engine_stack)
        self._scenario_language = "zh"
        try:
            from .scenario_loader import ScenarioLoader

            sl = ScenarioLoader(scenario)
            config = sl._load_toml()
            lang = config.get("display", {}).get("language", "zh")
            if lang in ("en", "zh"):
                self._scenario_language = lang
        except Exception:
            pass

        # ─── v2 initialization ────────────────────────────────
        if self._use_v2:
            self._init_v2(scenario, new_game)
        else:
            self._init_v1(llm, scenario, new_game, sim_engine)

    # ─── v2 initialization ────────────────────────────────────

    def _build_engine_stack(self, llm=None):
        """Initialize all sub-engines: map, character, domestic, military,
        decision, turn, history, narrative, intent, v3 sim, and macro policy.
        """
        from .loader import resolve_knowledge_path

        knowledge_path = resolve_knowledge_path()
        self._knowledge_path = knowledge_path

        # Initialize all 7 engines
        self.map_engine = MapEngine()
        self.char_engine = CharacterEngine()
        self.domestic_engine = DomesticEngine()
        self.military_engine = MilitaryEngine()
        self.decision_engine = DecisionEngine()

        # Turn controller orchestrates the 5 core engines
        # NPC Planner for FOW-aware NPC AI (optional LLM-based strategic advisor)
        npc_planner = None
        try:
            from histrategy_engine.ai.npc_planner import NPCPlanner

            advisor = None
            if llm and llm.is_available:
                try:
                    from ..llm.advisor import StrategicAdvisor

                    advisor = StrategicAdvisor(llm)
                except Exception:
                    pass

            npc_planner = NPCPlanner(
                decision_engine=self.decision_engine,
                advisor=advisor,
            )
        except Exception:
            pass

        self.turn_controller = TurnController(
            map_engine=self.map_engine,
            char_engine=self.char_engine,
            domestic_engine=self.domestic_engine,
            military_engine=self.military_engine,
            decision_engine=self.decision_engine,
            npc_planner=npc_planner,
        )

        # History engine + RAG
        try:
            self.history_engine = HistoryEngine(knowledge_path)
        except Exception:
            self.history_engine = None

        # Narrative engine (LLM or offline)
        self.narrative_engine = None
        self.intent_parser = None
        self.command_validator = None
        # v3: LLM simulation layer
        self.world_simulator = None
        self.guardrail = None
        self.turn_memory = None

        # macro: quarterly policy simulation
        self._macro_parser = None
        self._macro_validator = None
        self._quarterly_engine = None
        self._macro_sim = None
        self._black_swan = None
        self._knowledge_base = None

        # Detect v3 early — needed before IntentParser init
        from ..engine.engine_switch import EngineMode, detect_engine_mode

        engine_mode = detect_engine_mode()
        self._use_v3 = engine_mode == EngineMode.V3
        self._use_macro = self._use_v3

        if llm and llm.is_available:
            from ..llm.narrative import NarrativeEngine

            lang = getattr(self, "_scenario_language", "zh")
            self.narrative_engine = NarrativeEngine(llm, language=lang)

            # IntentParser: use fast model in v3 mode for speed
            if self._use_v3:
                intent_model = os.environ.get("HISTRATEGY_INTENT_MODEL", "deepseek-v4-flash")
                try:
                    from ..llm.adapter import LLMAdapter as _LLM

                    self._intent_llm = _LLM(model=intent_model)
                except Exception:
                    self._intent_llm = llm
                from ..parser.intent import IntentParser

                self.intent_parser = IntentParser(self._intent_llm)
            else:
                from ..parser.intent import IntentParser

                self.intent_parser = IntentParser(llm)

            from ..parser.validator import CommandValidator

            self.command_validator = CommandValidator(self.map_engine)
        else:
            # Offline mode: still have parser/validator (keyword-based)
            from ..parser.intent import IntentParser

            self.intent_parser = IntentParser(None)  # keyword fallback

            from ..parser.validator import CommandValidator

            self.command_validator = CommandValidator(self.map_engine)

        # v3 init: LLM simulation layer
        if self._use_v3 and llm and llm.is_available:
            from ..engine.guardrail import GuardrailValidator
            from ..engine.state_applier import StateApplier, TurnMemory
            from ..llm.world_simulator import WorldSimulator

            # WorldSimulator uses a fast model (no reasoning overhead)
            v3_fast_model = os.environ.get("HISTRATEGY_FAST_MODEL", "deepseek-chat")
            try:
                from ..llm.adapter import LLMAdapter as _LLM

                self._v3_llm = _LLM(
                    model=v3_fast_model,
                    api_key=llm.api_key if llm.api_key else None,
                    api_base=llm.api_base if llm.api_base else None,
                )
            except Exception:
                self._v3_llm = llm  # fallback to default

            self.world_simulator = WorldSimulator(self._v3_llm)
            self.guardrail = GuardrailValidator()
            self.state_applier = StateApplier()
            self.turn_memory = TurnMemory()

        # ── macro: quarterly policy engine ──
        self._turn_summaries: list[dict] = []  # recent turn summaries for LLM context
        if self._use_macro and llm and llm.is_available:
            from ..engine.black_swan import BlackSwanInjector
            from ..engine.knowledge_layer import KnowledgeBase
            from ..engine.macro_policy_engine import MacroPolicyEngine
            from ..engine.quarterly_engine import QuarterlyEngine
            from ..policy.policy_parser import PolicyParser
            from ..policy.policy_validator import PolicyValidator

            # PolicyParser uses the default LLM
            self._macro_parser = PolicyParser(llm)
            self._macro_validator = PolicyValidator()
            self._quarterly_engine = QuarterlyEngine()
            self._black_swan = BlackSwanInjector()

            # MacroPolicyEngine uses chat model for creative simulation
            macro_model = os.environ.get("HISTRATEGY_MACRO_MODEL", "deepseek-chat")
            try:
                from ..llm.adapter import LLMAdapter as _LLM
                from ..state.world_state import get_data_dir as _get_data_dir

                _room_dir = str(_get_data_dir())
                self._macro_llm = _LLM(
                    model=macro_model,
                    api_key=llm.api_key if llm and llm.api_key else None,
                    api_base=llm.api_base if llm and llm.api_base else None,
                    data_dir=_room_dir,
                )
            except Exception:
                self._macro_llm = llm
            self._macro_sim = MacroPolicyEngine(self._macro_llm, scenario=self.scenario, lang=self._scenario_language)
            self._knowledge_base = KnowledgeBase()

            # Replace IntentParser with PolicyParser in macro mode
            self.intent_parser = None  # Not used in macro mode

    def _init_v2(self, scenario: str, new_game: bool) -> None:
        """Initialize the v2 engine stack."""
        self._build_engine_stack(self.llm)

        # Try to load existing game or create new
        if not new_game:
            loaded = self._try_load_v2_save()
            if loaded:
                self.world_state_v2 = loaded
                self.game_started = True
            else:
                self.world_state_v2 = V2WorldState()
                self.game_started = False
        else:
            self.world_state_v2 = V2WorldState()
            self.game_started = False

        # v1 compat: not used in v2 mode
        self.world_state = None
        self._legacy_world = None
        self.sim_engine = None

        self._setup_rules_logging()

    def _setup_rules_logging(self) -> None:
        """Setup rule execution logging targeting logs/rules_execution.log in active session."""
        import logging

        from ..state.world_state import get_data_dir

        try:
            log_dir = get_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            rules_log_file = log_dir / "rules_execution.log"

            logger = logging.getLogger("histrategy_engine.rules")
            logger.setLevel(logging.INFO)

            # Avoid duplicate handlers for the same file
            has_handler = any(
                isinstance(h, logging.FileHandler) and h.baseFilename == str(rules_log_file.resolve())
                for h in logger.handlers
            )
            if not has_handler:
                # Remove existing file handlers (to redirect to current room log directory)
                logger.handlers = [h for h in logger.handlers if not isinstance(h, logging.FileHandler)]

                fh = logging.FileHandler(rules_log_file, encoding="utf-8")
                fh.setLevel(logging.INFO)
                formatter = logging.Formatter("%(asctime)s - %(message)s")
                fh.setFormatter(formatter)
                logger.addHandler(fh)
        except Exception as e:
            import sys

            print(f"[Warning] Failed to setup rules logging: {e}", file=sys.stderr)

    def _try_load_v2_save(self) -> V2WorldState | None:
        """Attempt to load a v2 game save from disk."""
        import json
        import os as _os

        save_dir = os.environ.get("HISTRATEGY_DATA_DIR", _os.path.expanduser("~/.histrategy"))
        v2_save = _os.path.join(save_dir, "world_v2.json")
        if not _os.path.isfile(v2_save):
            return None

        try:
            with open(v2_save) as f:
                data = json.load(f)
            # Reconstruct from saved JSON (simplified: rebuild from factions)
            return self._rebuild_from_save(data)
        except Exception:
            return None

    def _rebuild_from_save(self, data: dict) -> V2WorldState:
        """Rebuild a V2WorldState from saved JSON data with full state restoration."""
        from .loader import build_world_state

        faction_id = data.get("player_faction_id") or data.get("faction_id", "shu")
        scenario_id = data.get("scenario", "three-kingdoms")

        # Build fresh base world state from scenario data
        ws = build_world_state(faction_id, scenario_id, self._knowledge_path)

        # ── Restore time ──
        ws.year = data.get("year", ws.year)
        ws.turn_number = data.get("turn_number", ws.turn_number)
        ws.player_deviation = data.get("player_deviation", 0.0)
        season_val = data.get("season", "winter")
        from histrategy_engine.world import Season

        season_map = {
            "spring": Season.SPRING,
            "summer": Season.SUMMER,
            "autumn": Season.AUTUMN,
            "winter": Season.WINTER,
        }
        ws.season = season_map.get(season_val, Season.WINTER)

        # ── Restore factions (including new ones from gameplay) ──
        saved_factions = data.get("factions", {})
        from histrategy_engine.world import FactionState

        for fid, sf in saved_factions.items():
            if fid in ws.factions:
                f = ws.factions[fid]
            else:
                # New faction created during gameplay (e.g. rebellion, splinter)
                # Create a minimal faction and let saved data fill it in
                f_obj = FactionState(
                    id=fid,
                    name=sf.get("name", fid),
                    ruler_id=sf.get("ruler_id", ""),
                )
                ws.factions[fid] = f_obj
                f = ws.factions[fid]

            f.name = sf.get("name", f.name)
            f.ruler_id = sf.get("ruler_id", f.ruler_id)
            f.capital = sf.get("capital", f.capital)
            f.territories = list(sf.get("territories", f.territories))
            f.is_active = sf.get("is_active", f.is_active)
            f.prestige = sf.get("prestige", f.prestige)
            f.legitimacy = sf.get("legitimacy", f.legitimacy)
            f.strength_actual = sf.get("strength_actual", f.strength_actual)
            f.economy_actual = sf.get("economy_actual", f.economy_actual)
            f.morale_actual = sf.get("morale_actual", f.morale_actual)
            f.treasury = sf.get("treasury", f.treasury)
            f.food = sf.get("food", f.food)
            f.tax_rate = sf.get("tax_rate", f.tax_rate)
            f.relations = sf.get("relations", f.relations)
            f.allies = list(sf.get("allies", f.allies))
            f.enemies = list(sf.get("enemies", f.enemies))
            if "tech_levels" in sf:
                f.tech_levels = sf["tech_levels"]
            # Restore NPC personality traits
            for attr in ("aggression", "cunning", "caution", "diplomacy", "development_focus", "mercy"):
                if attr in sf:
                    setattr(f, attr, sf[attr])
            # Restore estimated stats (seen by other factions via intel)
            f.strength_estimated = sf.get("strength_estimated", f.strength_estimated)
            f.economy_estimated = sf.get("economy_estimated", f.economy_estimated)
            f.morale_estimated = sf.get("morale_estimated", f.morale_estimated)
            # Restore espionage state
            if "spy_network" in sf:
                f.spy_network = sf["spy_network"]
            if "intel_level" in sf:
                f.intel_level = sf["intel_level"]
            if "active_plans" in sf:
                f.active_plans = list(sf["active_plans"])

        # ── Restore territory ownership ──
        territory_owners = data.get("territory_owners", {})
        for tid, owner_id in territory_owners.items():
            if tid in ws.territories:
                ws.territories[tid].owner_id = owner_id

        # ── Restore character overrides ──
        char_overrides = data.get("character_overrides", {})
        for cid, co in char_overrides.items():
            if cid in ws.characters:
                c = ws.characters[cid]
                c.faction_id = co.get("faction_id", c.faction_id)
                c.location = co.get("location", c.location)
                c.loyalty = co.get("loyalty", c.loyalty)
                if "is_alive" in co and hasattr(c, "is_alive"):
                    c.is_alive = co["is_alive"]

        # ── Restore armies ──
        saved_armies = data.get("armies", {})
        from histrategy_engine.world import Army, UnitType

        ws.armies = {}
        for aid, sa in saved_armies.items():
            units = {}
            for unit_str, cnt in sa.get("units", {}).items():
                try:
                    ut = UnitType(unit_str)
                    units[ut] = cnt
                except ValueError:
                    pass
            ws.armies[aid] = Army(
                id=aid,
                faction_id=sa.get("faction_id", ""),
                location=sa.get("location", ""),
                commander_id=sa.get("commander_id", ""),
                units=units,
                morale=sa.get("morale", 80),
                supply=sa.get("supply", 30),
                training=sa.get("training", 1.0),
            )

        # ── Restore event history ──
        ws.completed_events = set(data.get("completed_events", []))
        ws.averted_events = set(data.get("averted_events", []))

        # ── Restore history engine state ──
        if self.history_engine:
            for evt_id in data.get("history_triggered", []):
                self.history_engine._triggered_events.add(evt_id)
            for evt_id, reason in data.get("history_averted", {}).items():
                if evt_id not in self.history_engine._averted_events:
                    self.history_engine._averted_events[evt_id] = reason
            self.history_engine._blocked_downstream = set(data.get("history_blocked", []))

        return ws

    @classmethod
    def from_dict(cls, data: dict, llm=None) -> GameEngine:
        """Create a GameEngine from a saved world state dict.

        Builds the full v2 engine stack and restores the world state from the dict.
        Use this to resume a game from orchestrator-stored save data.
        """
        engine = cls.__new__(cls)
        engine.llm = llm
        engine.scenario = data.get("scenario", "three-kingdoms")

        engine._use_v2 = True

        engine._build_engine_stack(llm)

        # Restore world state from saved data
        engine.world_state_v2 = engine._rebuild_from_save(data)
        engine.game_started = True

        engine._setup_rules_logging()

        return engine

    def _save_v2(self) -> None:
        """Save the v2 world state to disk with full serialization."""
        import json
        import os as _os

        save_dir = os.environ.get("HISTRATEGY_DATA_DIR", _os.path.expanduser("~/.histrategy"))
        _os.makedirs(save_dir, exist_ok=True)
        v2_save = _os.path.join(save_dir, "world_v2.json")
        data = self.to_dict()
        with open(v2_save, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        """Serialize the full v2 world state to a JSON-safe dict.

        Includes factions, territories (ownership only), characters (loyalty/location),
        armies, and event history — everything needed to restore from save.
        """
        ws = self.world_state_v2
        data: dict = {
            "year": ws.year,
            "season": ws.season.value,
            "turn_number": ws.turn_number,
            "scenario": ws.scenario,
            "player_faction_id": ws.player_faction_id,
            "player_deviation": ws.player_deviation,
            "factions": {
                fid: {
                    "name": f.name,
                    "ruler_id": f.ruler_id,
                    "capital": f.capital,
                    "territories": list(f.territories),
                    "is_active": f.is_active,
                    "prestige": f.prestige,
                    "legitimacy": f.legitimacy,
                    "strength_actual": f.strength_actual,
                    "economy_actual": f.economy_actual,
                    "morale_actual": f.morale_actual,
                    "strength_estimated": f.strength_estimated,
                    "economy_estimated": f.economy_estimated,
                    "morale_estimated": f.morale_estimated,
                    "treasury": f.treasury,
                    "food": f.food,
                    "tax_rate": f.tax_rate,
                    "relations": dict(f.relations) if f.relations else {},
                    "tech_levels": dict(f.tech_levels) if f.tech_levels else {},
                    "allies": list(f.allies) if f.allies else [],
                    "enemies": list(f.enemies) if f.enemies else [],
                    "spy_network": dict(f.spy_network) if f.spy_network else {},
                    "intel_level": getattr(f, "intel_level", 50),
                    "active_plans": list(f.active_plans) if f.active_plans else [],
                    "aggression": getattr(f, "aggression", 0.5),
                    "cunning": getattr(f, "cunning", 0.5),
                    "caution": getattr(f, "caution", 0.5),
                    "diplomacy": getattr(f, "diplomacy", 0.5),
                    "development_focus": getattr(f, "development_focus", 0.5),
                    "mercy": getattr(f, "mercy", 0.5),
                }
                for fid, f in ws.factions.items()
            },
            # Territory ownership (only what changes — not full territory data)
            "territory_owners": {tid: t.owner_id for tid, t in ws.territories.items()},
            # Character overrides (only what deviates from base)
            "character_overrides": {
                cid: {
                    "faction_id": c.faction_id,
                    "location": c.location,
                    "loyalty": c.loyalty,
                    "is_alive": getattr(c, "is_alive", True),
                }
                for cid, c in ws.characters.items()
            },
            # Armies
            "armies": {
                aid: {
                    "faction_id": a.faction_id,
                    "location": a.location,
                    "commander_id": a.commander_id,
                    "units": {ut.value: cnt for ut, cnt in a.units.items()} if a.units else {},
                    "morale": a.morale,
                    "supply": a.supply,
                    "training": getattr(a, "training", 1.0),
                }
                for aid, a in (ws.armies or {}).items()
            },
            # Event history
            "completed_events": list(ws.completed_events) if ws.completed_events else [],
            "averted_events": list(ws.averted_events) if ws.averted_events else [],
            # History engine state
            "history_triggered": list(self.history_engine._triggered_events) if self.history_engine else [],
            "history_averted": (
                dict(self.history_engine._averted_events.items())
                if self.history_engine and hasattr(self.history_engine, "_averted_events")
                else {}
            ),
            "history_blocked": (
                list(self.history_engine._blocked_downstream)
                if self.history_engine and hasattr(self.history_engine, "_blocked_downstream")
                else []
            ),
        }
        return data

    # ─── v1 initialization (unchanged) ────────────────────────

    def _init_v1(self, llm, scenario, new_game, sim_engine) -> None:
        """Original v1 initialization path."""
        self._use_v2 = False

        if sim_engine is not None:
            self.sim_engine = sim_engine
        elif llm is not None:
            from ..engine.resilient_sim_engine import ResilientSimEngine
            from ..llm.llm_sim_engine import LLMSimEngine

            self.sim_engine = ResilientSimEngine(LLMSimEngine(llm))
        else:
            from ..engine.offline_sim_engine import OfflineSimEngine

            self.sim_engine = OfflineSimEngine()

        if not new_game and has_existing_game():
            loaded = load_world()
            if loaded:
                self.world_state = loaded
                self.game_started = True
            else:
                self.world_state = WorldState()
                self.game_started = False
        else:
            self.world_state = WorldState()
            self.game_started = False

        self._legacy_world = None
        self.world_state_v2 = None

    # ─── Legacy world compat ──────────────────────────────────

    @property
    def legacy_world(self):
        if self._use_v2:
            return None
        if hasattr(self, "sim_engine") and self.sim_engine is not None:
            engine = self.sim_engine
            if hasattr(engine, "_primary"):
                engine = engine._primary
            if hasattr(engine, "_legacy_world") and engine._legacy_world is not None:
                return engine._legacy_world
        return self._legacy_world

    @legacy_world.setter
    def legacy_world(self, value):
        if self._use_v2:
            return
        self._legacy_world = value
        if hasattr(self, "sim_engine") and self.sim_engine is not None:
            engine = self.sim_engine
            if hasattr(engine, "_primary"):
                engine = engine._primary
            if hasattr(engine, "_legacy_world"):
                engine._legacy_world = value

    @property
    def has_existing_save(self) -> bool:
        return self.game_started

    def set_player_faction(self, faction_id: str):
        """Initialize or set the player faction, creating the world state."""
        if self._use_v2:
            self._set_player_faction_v2(faction_id)
        else:
            self._set_player_faction_v1(faction_id)

    def _set_player_faction_v2(self, faction_id: str) -> None:
        """v2 path: build WorldState from scenario data via ScenarioLoader."""
        from .scenario_loader import ScenarioLoader

        mapped = V2_FACTION_MAP.get(faction_id, faction_id)
        scenario_id = self.scenario

        loader = ScenarioLoader(scenario_id)
        try:
            self.world_state_v2 = loader.build_world_state(mapped)
        except FileNotFoundError:
            # Fall back to legacy loader for scenarios without scenario.toml
            from .loader import build_world_state

            self.world_state_v2 = build_world_state(mapped, scenario_id, self._knowledge_path)

        # Cache the loader for later use (prompts, format_year, etc.)
        self.scenario_loader = loader

        # Load territories and characters into engines
        self.map_engine.load_territories(self.world_state_v2.territories)
        self.char_engine.load_characters(self.world_state_v2.characters)

        self.game_started = True
        self._save_v2()

    def _set_player_faction_v1(self, faction_id: str) -> None:
        """v1 path: original faction setup."""
        self.world_state = create_initial_world(faction_id)
        self.game_started = True

        self.legacy_world = GameWorld(scenario=self.scenario)
        self.legacy_world.player_faction_id = faction_id

    # ─── Intro Scene ──────────────────────────────────────────

    def get_intro_scene(self) -> dict:
        """Get the introductory scene for a new game."""
        if not self.game_started:
            return self._fallback_intro()

        if self._use_v2:
            return self._intro_v2()
        else:
            return self._intro_v1()

    def _intro_v2(self) -> dict:
        """v2 intro: template-based, no LLM — fast load."""
        ws = self.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return self._fallback_intro()

        # Resolve capital name from territory data
        capital_name = player.capital
        capital_territory = ws.territories.get(player.capital)
        if capital_territory and capital_territory.name:
            capital_name = capital_territory.name

        # Use faction-specific deterministic suggestions for intro
        faction_suggestions = FIRST_TURN_SUGGESTIONS.get(
            ws.player_faction_id,
            FIRST_TURN_SUGGESTIONS["cao"],
        )
        suggestions = [
            s.split("】", 1)[0] + "】" + s.split("】", 1)[1].split("，")[0] + "等" if "】" in s else s[:30]
            for s in faction_suggestions
        ]

        narrative = (
            (
                f"### 天下大势\\n"
                f"建安{ws.year - 196}年（公元{ws.year}年），汉室倾颓，诸侯并起。\\n"
                f"曹操迎天子于许昌，挟天子以令诸侯，已据中原大半。\\n"
                f"孙权继父兄之业，稳坐江东。\\n\\n"
                f"### 主公处境\\n"
                f"你，{player.name}，以{capital_name}为根基，"
                f"麾下兵卒{player.strength_actual}，粮草{player.food}，资金{player.treasury}。\\n"
                f"当审时度势，谋定而后动。"
            )
            if getattr(self, "_scenario_language", "zh") != "en"
            else (
                f"### The Realm\\n"
                f"Year {ws.year - 196} of Jian'an (AD {ws.year}). The Han dynasty crumbles; warlords rise across the land.\\n"
                f"Cao Cao holds the Emperor at Xuchang, commanding the realm in name, and controls most of the Central Plains.\\n"
                f"Sun Quan, heir to his father and brother's legacy, rules firmly over Jiangdong.\\n\\n"
                f"### Your Position\\n"
                f"You are {player.name}, ruling from {capital_name}. "
                f"You command {player.strength_actual} troops, with {player.food} bushels of grain and {player.treasury} gold in the treasury.\\n"
                f"Survey the realm and plan your next move."
            )
        )

        npc_actions = []
        for fid, fs in ws.factions.items():
            if not fs.is_active or fid == ws.player_faction_id:
                continue
            npc_actions.append(f"{fs.name}据有{len(fs.territories)}城，兵力{fs.strength_actual:,}。")

        return {
            "narrative": narrative,
            "npc_actions": npc_actions,
            "new_choices": suggestions,
            "state_changes": {},
            "events_occurred": [],
        }

    def _intro_v1(self) -> dict:
        """v1 intro: use offline template for instant load."""
        return self._offline_intro()

    # ─── Plan Data ────────────────────────────────────────────

    def get_plan_data(self) -> dict:
        """Get the current turn's plan data."""
        if not self.game_started:
            return self._fallback_plan_data()

        if self._use_v2:
            return self._plan_v2()
        else:
            return self._plan_v1()

    def _plan_v2(self) -> dict:
        """v2 plan: use NarrativeEngine to generate suggestions."""
        ws = self.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return self._fallback_plan_data()

        # Snapshot token counter before LLM call
        _tok_before = 0
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _tok_before = llm.total_all_tokens

        # Generate suggestions from narrative engine
        if ws.turn_number <= 1:
            # ── First turn: hard-coded suggestions (no LLM needed) ──
            from histrategy.engine.game import FIRST_TURN_SUGGESTIONS

            suggestions = FIRST_TURN_SUGGESTIONS.get(
                ws.player_faction_id,
                FIRST_TURN_SUGGESTIONS["cao"],
            )
        elif self.narrative_engine and self.narrative_engine.is_available:
            with _suppress_stderr():
                suggestions = self.narrative_engine.generate_plan_suggestions(ws, ws.player_faction_id)
        else:
            suggestions = self._offline_v2_suggestions()

        # Track LLM token usage for plan mode
        _plan_tokens = 0
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _plan_tokens = max(llm.total_all_tokens - _tok_before, 0)

        # Build court dialogue from engine state
        court_parts: list[str] = []
        court_parts.append(
            f"【{ws.year}年{ws.season.cn} · 内政会议】\n\n"
            f"群臣趋前侍立。{player.name}端坐于{player.capital}府衙正堂，"
            f"审视天下局势。\n"
        )

        # Add strategic context
        court_parts.append(
            f"当前兵力{player.strength_actual:,}，粮草{player.food:,}，"
            f"资金{player.treasury:,}。领地{len(player.territories)}处。\n"
        )

        # Mention neighboring threats
        for tid in player.territories:
            t = ws.territories.get(tid)
            if t:
                for nid in t.neighbors:
                    nt = ws.territories.get(nid)
                    if nt and nt.owner_id and nt.owner_id != ws.player_faction_id:
                        nf = ws.factions.get(nt.owner_id)
                        if nf and nf.is_active:
                            rel = nf.relations.get(ws.player_faction_id, 0)
                            rel_str = "敌对" if rel < -30 else ("中立" if rel < 30 else "友好")
                            court_parts.append(f"边境警报：{nid}（{nt.name}）方向，{nf.name}军为{rel_str}关系。")

        season_summary = f"{ws.year}年{ws.season.cn}，天下纷争未休，{player.name}当何去何从？"

        return {
            "court_dialogue": "\n".join(court_parts),
            "suggestions": suggestions,
            "season_summary": season_summary,
            "_usage": {"plan_tokens": _plan_tokens},
        }

    def _plan_v1(self) -> dict:
        """v1 plan path (unchanged)."""
        pressure_hint = ""
        if hasattr(self, "sim_engine") and self.sim_engine is not None:
            engine = self.sim_engine
            if hasattr(engine, "_primary"):
                engine = engine._primary
            if hasattr(engine, "_narrative_director"):
                pressure_hint = engine._narrative_director.get_pressure_hint(
                    self.world_state.turn, self.world_state.player_deviation
                )

        if self.llm is not None:
            gm = GameMaster(self.llm, lang=getattr(self, "_scenario_language", "zh"))
            return gm.generate_plan_mode(self.world_state, pressure_hint=pressure_hint)
        else:
            return self._fallback_plan_data()

    # ─── Turn Processing ──────────────────────────────────────

    def process_turn(self, player_decision: str) -> dict:
        """Process a player's decision and return results.

        v2: IntentParser → CommandValidator → TurnController.execute_turn() →
            NarrativeEngine.generate_turn_narrative()
        v1: WorldSimEngine.simulate()
        symmetric: GameRoom → DecisionBus → QuarterlyResolver (multi-faction)
        """
        if not self.game_started:
            return self._fallback_intro()

        # ── Symmetric multi-faction path (HISTRATEGY_SYMMETRIC=1) ──
        if os.environ.get("HISTRATEGY_SYMMETRIC") == "1":
            return self.process_turn_symmetric(player_decision)

        if self._use_v3:
            if self.world_simulator:
                return self._process_turn_v3(player_decision)
            if self._macro_sim:
                return self._process_turn_macro(player_decision)
        if self._use_v2:
            return self._process_turn_v2(player_decision)
        return self._process_turn_v1(player_decision)

    def set_debug_context(self, session_id: str, jwt_token: str = "") -> None:
        """Set session context for Postgres debug logging (called from API layer)."""
        self._debug_session_id = session_id
        self._debug_jwt = jwt_token
        import logging

        short_sid = session_id[:12] if len(session_id) > 12 else session_id
        logging.getLogger("histrategy").info(f"Debug context set: session={short_sid}...")

    def _process_turn_v2(self, player_decision: str) -> dict:
        """v2 turn processing pipeline."""
        ws = self.world_state_v2
        current_year = ws.year
        current_season = ws.season

        # Step 1: Parse player intent into commands
        player_commands = []
        if self.intent_parser:
            player_commands = self.intent_parser.parse(player_decision, ws.player_faction_id)

        # Store for simulation history logging
        self._last_player_decision = player_decision
        self._last_player_commands = list(player_commands)

        # Step 2: Validate commands
        if self.command_validator:
            player_commands = self.command_validator.validate(player_commands, ws)

        # Step 3: Execute turn via TurnController
        turn_result = self.turn_controller.execute_turn(
            ws,
            player_commands=player_commands,
            year=ws.year,
            turn_number=ws.turn_number,
        )

        # Step 4: Check historical events
        proposals = []
        if self.history_engine:
            try:
                # Sync completed/averted events with history_engine
                for evt_id in ws.completed_events:
                    self.history_engine._triggered_events.add(evt_id)
                for evt_id in ws.averted_events:
                    if evt_id not in self.history_engine._averted_events:
                        self.history_engine._averted_events[evt_id] = "Restored from world state"
                    self.history_engine.block_downstream(evt_id)

                proposals = self.history_engine.check_events(
                    current_year, current_season, ws, deviation=ws.player_deviation
                )
                for prop in proposals:
                    apply_event_effects(ws, prop.effects.get("effects", {}))
                    turn_result.history_events.append(
                        {
                            "event_id": prop.event_id,
                            "title": prop.title,
                            "outcome": prop.effects.get("outcome", "default"),
                            "description": prop.effects.get("outcome_description", ""),
                            "effects": prop.effects.get("effects", {}),
                        }
                    )
            except Exception:
                pass

        # Step 5 & 6: Generate narrative and plan suggestions (Parallelized)
        narrative_text = ""
        new_choices = []

        # Snapshot cumulative LLM token counters before parallel calls
        _tok_snap = {"total": 0}
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _tok_snap["total"] = llm.total_all_tokens

        averted_list = list(ws.averted_events)
        if self.history_engine:
            averted_list = list(set(averted_list) | self.history_engine._blocked_downstream)

        room_id = getattr(self, "_room_id", "default")

        if self.narrative_engine and self.narrative_engine.is_available:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Submit both tasks
                future_narrative = executor.submit(
                    self.narrative_engine.generate_turn_narrative,
                    turn_result,
                    deviation=ws.player_deviation,
                    averted_events=averted_list,
                    world_state=ws,
                    room_id=room_id,
                )
                future_suggestions = executor.submit(
                    self.narrative_engine.generate_plan_suggestions, ws, ws.player_faction_id
                )

                # Retrieve results with error fallback
                try:
                    with _suppress_stderr():
                        narrative_text = future_narrative.result(timeout=30)
                except Exception:
                    narrative_text = self._offline_v2_narrative(turn_result)

                try:
                    with _suppress_stderr():
                        new_choices = future_suggestions.result(timeout=30)
                except Exception:
                    new_choices = self._offline_v2_suggestions()
        else:
            narrative_text = self._offline_v2_narrative(turn_result)
            new_choices = self._offline_v2_suggestions()

        # Step 7: Build result dict
        player = ws.factions.get(ws.player_faction_id)
        game_over = None
        if not player or not player.is_active or player.strength_actual <= 0:
            game_over = {
                "type": "defeat",
                "message": ("# 势力覆灭\n\n你的势力已经不复存在。\n乱世之中，成王败寇。\n\n感谢游玩《三國志略》。"),
            }

        # Check if all territory has been unified
        active_factions = [fid for fid, f in ws.factions.items() if f.is_active and f.strength_actual > 0]
        if len(active_factions) == 1 and active_factions[0] == ws.player_faction_id:
            game_over = {
                "type": "victory",
                "message": (
                    "# 天下一统\n\n"
                    "经过多年的征战，你终于平定了天下。\n"
                    "海内归一，万民归心。\n\n"
                    "你就是这个时代最伟大的君主！\n\n"
                    "感谢游玩《三國志略》。"
                ),
            }

        # Extract state changes from resource_changes
        resource_changes = turn_result.resource_changes.get(ws.player_faction_id, {})

        # Track LLM token usage via cumulative counters (works across parallel calls)
        _usage = {
            "command_tokens": 0,  # Narrative + Suggestions (all LLM calls this turn)
            "plan_tokens": 0,  # Suggestions generation
            "npc_tokens": 0,  # NPC AI (not yet tracked separately)
            "sim_tokens": 0,  # Deterministic simulation (free)
        }
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _usage["command_tokens"] = max(llm.total_all_tokens - _tok_snap.get("total", 0), 0)

        # Generate a concise aftermath from resource changes + key events
        aftermath_parts = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        if resource_changes.get("food_delta", 0) != 0:
            sign = "+" if resource_changes["food_delta"] > 0 else ""
            label = "Food" if is_en else "粮草"
            aftermath_parts.append(f"{label}{sign}{resource_changes['food_delta']}")
        if resource_changes.get("tax_revenue", 0) != 0:
            sign = "+" if resource_changes["tax_revenue"] > 0 else ""
            label = "Gold" if is_en else "资金"
            aftermath_parts.append(f"{label}{sign}{resource_changes['tax_revenue']}")
        if resource_changes.get("strength_delta", 0) != 0:
            sign = "+" if resource_changes["strength_delta"] > 0 else ""
            label = "Troops" if is_en else "兵力"
            aftermath_parts.append(f"{label}{sign}{resource_changes['strength_delta']}")
        if resource_changes.get("morale_delta", 0) != 0:
            sign = "+" if resource_changes["morale_delta"] > 0 else ""
            label = "Morale" if is_en else "民心"
            aftermath_parts.append(f"{label}{sign}{resource_changes['morale_delta']}")

        # Extract the last 2-3 sentences of narrative as summary
        if narrative_text:
            import re as _re

            sentences = _re.split(r"[。！？]", narrative_text)
            sentences = [s.strip() for s in sentences if s.strip()]
            summary_sentences = sentences[-2:] if len(sentences) > 2 else sentences[-1:]
            aftermath_text = "。".join(summary_sentences) + "。"
        else:
            aftermath_text = "The realm is calm, all is under control.\n" if is_en else "局势已定，天下大势尽在掌握。\n"

        if aftermath_parts:
            prefix = "This turn: " if is_en else "本回合："
            sep = ", " if is_en else "，"
            suffix = ". " if is_en else "。"
            aftermath_text = prefix + sep.join(aftermath_parts) + suffix + "\n\n" + aftermath_text

        result = {
            "narrative": narrative_text,
            "aftermath": aftermath_text,
            "bureaucracy": [
                {"department": "军机处", "official": "参军", "action": f"执行{len(player_commands)}项军令"}
            ],
            "state_changes": {
                "food": resource_changes.get("food_delta", 0),
                "treasury": resource_changes.get("tax_revenue", 0),
            },
            "_usage": _usage,
            "seeds": [
                {"title": evt["title"], "description": evt.get("description", "")[:80]}
                for evt in self.history_engine.all_events
                if evt["id"] not in self.history_engine._triggered_events
                and evt["id"] not in self.history_engine.averted_events
                and evt["id"] not in self.history_engine._blocked_downstream
                and abs(evt["year"] - ws.year) <= 1
            ]
            if self.history_engine
            else [],
            "npc_reactions": [],
            "npc_actions": [],
            "events_occurred": turn_result.character_events,
            "new_choices": new_choices,
            "game_over": game_over,
            "world_state": ws,
        }

        # Score the turn for deviation
        if player and self.history_engine:
            try:
                if ws.player_deviation > 0.0:
                    if is_en:
                        result["aftermath"] = (
                            f"[Historian's Note: Historical Deviation {ws.player_deviation:.2f}]\n\n"
                            + result["aftermath"]
                        )
                    else:
                        result["aftermath"] = (
                            f"【史官注：历史偏离度 {ws.player_deviation:.2f}】\n\n" + result["aftermath"]
                        )
            except Exception:
                pass

        # Save state
        self._save_v2()

        # Log turn
        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(
                ws.turn_number,
                ws.year,
                ws.season.value,
                player_decision,
                result,
            )
        except Exception:
            pass

        self._log_simulation_history()

        return result

    def _process_turn_v3(self, player_decision: str) -> dict:
        """v3 turn processing pipeline — LLM-driven simulation with guardrails.

        1. Parse intent (same as v2)
        2. Execute deterministic baseline (same as v2)
        3. LLM WorldSimulator generates nonlinear delta
        4. GuardrailValidator checks delta
        5. StateApplier applies validated delta
        6. NarrativeEngine generates story with full context
        """
        ws = self.world_state_v2
        current_year = ws.year
        current_season = ws.season

        # Step 1: Parse player intent (same as v2)
        player_commands = []
        if self.intent_parser:
            player_commands = self.intent_parser.parse(player_decision, ws.player_faction_id)
        self._last_player_decision = player_decision
        self._last_player_commands = list(player_commands)

        # Step 2: Validate commands (same as v2)
        if self.command_validator:
            player_commands = self.command_validator.validate(player_commands, ws)

        # ── v3: Auto-mobilize ──────────────────────────────────
        # When player says "attack with 60K from wancheng" but only 5K
        # army exists, auto-transfer faction reserves to the army.
        _auto_mobilize_for_attack(player_commands, ws)

        # Step 3: Execute deterministic baseline (same as v2 — TurnController)
        baseline_result = self.turn_controller.execute_turn(
            ws,
            player_commands=player_commands,
            year=ws.year,
            turn_number=ws.turn_number,
        )

        # Step 4: History events (same as v2)
        proposals = []
        if self.history_engine:
            try:
                for evt_id in ws.completed_events:
                    self.history_engine._triggered_events.add(evt_id)
                for evt_id in ws.averted_events:
                    if evt_id not in self.history_engine._averted_events:
                        self.history_engine._averted_events[evt_id] = "Restored"
                    self.history_engine.block_downstream(evt_id)
                proposals = self.history_engine.check_events(
                    current_year, current_season, ws, deviation=ws.player_deviation
                )
                for prop in proposals:
                    apply_event_effects(ws, prop.effects.get("effects", {}))
                    baseline_result.history_events.append(
                        {
                            "event_id": prop.event_id,
                            "title": prop.title,
                            "outcome": prop.effects.get("outcome", "default"),
                            "description": prop.effects.get("outcome_description", ""),
                            "effects": prop.effects.get("effects", {}),
                        }
                    )
            except Exception:
                pass

        # ── v3: LLM Simulation Layer ──

        # Capture pre-turn morale for all factions (v2 may have changed it)
        pre_morale: dict[str, int] = {}
        for fid, f in ws.factions.items():
            if getattr(f, "is_active", True):
                pre_morale[fid] = getattr(f, "morale_actual", 50)

        # Build memory context
        room_id = getattr(self, "_room_id", "default")
        turn_history: list[dict] = []
        epoch_effects: list[dict] = []
        if self.turn_memory:
            self.turn_memory.clean_future_turns(room_id, ws.turn_number)
            turn_history = self.turn_memory.get_recent_turns(room_id, n=10)
            epoch_effects = self.turn_memory.get_persistent_effects(room_id)

        # Step 5: LLM nonlinear simulation
        llm_delta = {}
        _v3_tokens = {"prompt": 0, "completion": 0, "total": 0}
        if self.world_simulator and self.world_simulator.llm_available:
            # Track v3 LLM tokens for usage reporting
            v3_llm = getattr(self.world_simulator, "llm", None)
            _v3_pre = v3_llm.total_all_tokens if v3_llm and hasattr(v3_llm, "total_all_tokens") else 0

            llm_delta = self.world_simulator.simulate(
                ws,
                player_commands,
                player_decision,
                baseline_result,
                turn_history,
                epoch_effects,
                pre_morale=pre_morale,
            )

            if v3_llm and hasattr(v3_llm, "total_all_tokens"):
                _v3_tokens["total"] = v3_llm.total_all_tokens - _v3_pre

        # Step 6: Guardrail validation
        guardrail_result = {"accepted": True, "sanitized_delta": llm_delta, "warnings": []}
        if self.guardrail and llm_delta:
            guardrail_result = self.guardrail.validate(llm_delta, ws, baseline_result)

        # Step 7: Apply validated delta
        state_summary: dict = {}
        if guardrail_result["accepted"] and guardrail_result["sanitized_delta"]:
            state_summary = self.state_applier.apply(guardrail_result["sanitized_delta"], ws)

        # Update baseline_result with LLM overrides for narrative generation
        baseline_result.player_decision = player_decision
        baseline_result.player_commands = list(player_commands)
        sanitized = guardrail_result["sanitized_delta"]
        baseline_result._v3_delta = sanitized  # accessible by NarrativeEngine

        # Step 8: Record turn memory
        season_cn = current_season.cn if hasattr(current_season, "cn") else str(current_season)

        # Collect persistent effects from morale events
        persistent_effects = []
        if sanitized:
            for me in sanitized.get("morale_events", []):
                note = me.get("persistent_note", "")
                if note:
                    persistent_effects.append(
                        {
                            "note": note,
                            "turn": ws.turn_number,
                            "faction": me.get("faction", ""),
                        }
                    )

        # Build key events list
        key_events = []
        for bo in sanitized.get("battle_overrides", []):
            key_events.append(f"战斗@{bo.get('location', '?')}: {bo.get('llm_result', '?')}")
        for pe in sanitized.get("political_events", []):
            key_events.append(f"政事@{pe.get('faction', '?')}: {pe.get('type', '?')}")
        for me in sanitized.get("morale_events", []):
            ch = me.get("change", 0)
            if abs(ch) >= 3:
                key_events.append(f"民心@{me.get('faction', '?')}: {ch:+d} ({me.get('reason', '?')[:30]})")

        player = ws.factions.get(ws.player_faction_id)
        state_snapshot = {
            "morale": getattr(player, "morale_actual", 0) if player else 0,
            "territories": len(player.territories) if player else 0,
            "strength": getattr(player, "strength_actual", 0) if player else 0,
            "treasury": player.treasury if player else 0,
            "food": player.food if player else 0,
        }

        if self.turn_memory and player_decision:
            self.turn_memory.record_turn(
                room_id,
                ws.turn_number,
                current_year,
                season_cn,
                player_decision,
                outcome_summary="; ".join(key_events) if key_events else "平和无事",
                key_events=key_events,
                state_snapshot=state_snapshot,
                persistent_effects=persistent_effects,
            )

        # ── Narrative Generation ──

        narrative_text = ""
        new_choices: list[str] = []
        averted_list = list(ws.averted_events)
        if self.history_engine:
            averted_list = list(set(averted_list) | self.history_engine._blocked_downstream)

        # Build v3-aware narrative
        narrative_seeds = sanitized.get("narrative_seeds", []) if sanitized else []
        npc_actions_list = sanitized.get("npc_actions", []) if sanitized else []

        if self.narrative_engine and self.narrative_engine.is_available:
            # Inject v3 delta into baseline_result so narrative engine includes it
            if sanitized:
                _inject_v3_into_baseline(baseline_result, sanitized)

            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_narrative = executor.submit(
                    self.narrative_engine.generate_turn_narrative,
                    baseline_result,
                    deviation=ws.player_deviation,
                    averted_events=averted_list,
                    world_state=ws,
                    room_id=room_id,
                )
                future_suggestions = executor.submit(
                    self.narrative_engine.generate_plan_suggestions, ws, ws.player_faction_id
                )

                try:
                    with _suppress_stderr():
                        narrative_text = future_narrative.result(timeout=30)
                except Exception:
                    narrative_text = ""

                try:
                    with _suppress_stderr():
                        new_choices = future_suggestions.result(timeout=30)
                except Exception:
                    new_choices = self._offline_v2_suggestions()
        else:
            new_choices = self._offline_v2_suggestions()

        # Build v3-style narrative from seeds if available, otherwise fall back to v2
        if narrative_seeds:
            # Build narrative header
            header_lines = [
                f"### {current_year}年{season_cn} · 大事纪",
                f"建安{current_year - 196}年{season_cn}，天下纷争未休。",
                "",
            ]
            # Resource summary
            if player:
                player.food - state_snapshot.get("food", player.food)
                player.treasury - state_snapshot.get("treasury", player.treasury)
                header_lines.append(
                    f"**{player.name}** | 兵力{player.strength_actual:,} | "
                    f"资金{player.treasury:,} | 粮草{player.food:,} | "
                    f"民心{getattr(player, 'morale_actual', '?')}"
                )
                header_lines.append("")

            # v3 narrative seeds as the main body
            body_lines = []
            for seed in narrative_seeds[:8]:
                body_lines.append(f"> {seed}")
            body_lines.append("")

            # NPC activity summary
            if npc_actions_list:
                npc_lines = ["**天下动向**"]
                for na in npc_actions_list[:4]:
                    faction_id = na.get("faction", "?")
                    faction_obj = ws.factions.get(faction_id)
                    faction_name = faction_obj.name if faction_obj else faction_id
                    action_cn = {
                        "attack": "进攻",
                        "defend": "防守",
                        "recruit": "募兵",
                        "develop": "发展",
                        "ally": "结盟",
                        "strategic_retreat": "撤退",
                        "wait": "休整",
                    }.get(na.get("action", ""), na.get("action", ""))
                    reason = na.get("reasoning", "")
                    npc_lines.append(f"- {faction_name}**{action_cn}**：{reason}")
                body_lines.append("")
                body_lines.extend(npc_lines)

            # Political events
            pol_events = sanitized.get("political_events", []) if sanitized else []
            if pol_events:
                body_lines.append("")
                body_lines.append("**朝堂政事**")
                for pe in pol_events[:3]:
                    desc = pe.get("description", "")
                    if desc:
                        body_lines.append(f"- {desc}")

            narrative_text = "\n".join(header_lines) + "\n".join(body_lines)
            if narrative_text and not narrative_text.endswith("\n"):
                narrative_text += "\n"
        elif not narrative_text:
            narrative_text = self._offline_v2_narrative(baseline_result)

        # Build aftermath/summary
        aftermath_parts = []
        if player:
            player_morale = getattr(player, "morale_actual", 0)
            aftermath_parts.append(f"民心{player_morale}")
            aftermath_parts.append(f"兵力{player.strength_actual:,}")
        if key_events:
            aftermath_parts.append(" | ".join(key_events[:3]))
        aftermath_text = "。".join(aftermath_parts) + "。" if aftermath_parts else "局势已定。"

        # Token usage tracking (v3-specific)
        _main_usage = {}
        if self.narrative_engine and self.narrative_engine.is_available:
            llm_narr = getattr(self.narrative_engine, "llm", None)
            if llm_narr and hasattr(llm_narr, "total_all_tokens"):
                _main_usage["narrative_tokens"] = 0  # tracked in main llm

        _usage = {
            "intent_tokens": 0,  # IntentParser (in main llm)
            "command_tokens": 0,  # CommandValidator (free)
            "npc_tokens": 0,  # NPC AI (not separately tracked)
            "sim_tokens": _v3_tokens.get("total", 0),  # v3 WorldSimulator
            "narrative_tokens": 0,
        }

        # ── Build result dict (v2-compatible + v3 extras) ──

        game_over = None
        if not player or not player.is_active or getattr(player, "strength_actual", 0) <= 0:
            game_over = {
                "type": "defeat",
                "message": "# 势力覆灭\n\n你的势力已经不复存在。\n乱世之中，成王败寇。\n\n感谢游玩《三國志略》。",
            }

        active_factions = [
            fid for fid, f in ws.factions.items() if f.is_active and getattr(f, "strength_actual", 0) > 0
        ]
        if len(active_factions) == 1 and active_factions[0] == ws.player_faction_id:
            game_over = {
                "type": "victory",
                "message": "# 天下一统\n\n经过多年的征战，你终于平定了天下。",
            }

        self._save_v2()

        # Log turn
        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(ws.turn_number, current_year, season_cn, player_decision, {})
        except Exception:
            pass

        self._log_simulation_history()

        return {
            "narrative": narrative_text,
            "aftermath": aftermath_text,
            "summary": aftermath_text,
            "bureaucracy": [
                {"department": "军机处", "official": "参军", "action": f"执行{len(player_commands)}项军令"}
            ],
            "state_changes": state_summary,
            "new_choices": new_choices,
            "events_occurred": [],
            "npc_actions": [na.get("reasoning", "") for na in npc_actions_list],
            "seeds": [{"title": "v3 推演", "description": s[:80]} for s in narrative_seeds[:4]],
            "npc_reactions": [],
            "game_over": game_over,
            "world_state": ws,
            "_usage": _usage,
            "v3_metadata": {
                "delta_accepted": guardrail_result["accepted"],
                "warnings": len(guardrail_result.get("warnings", [])),
                "narrative_seeds": len(narrative_seeds),
                "llm_delta_keys": list(llm_delta.keys()) if llm_delta else [],
                "sim_tokens": _v3_tokens.get("total", 0),
            },
        }

    def _normalize_seeds(self, raw_seeds: list) -> list[dict]:
        """Normalize narrative_seeds from LLM — strings → {title: str} dicts."""
        result = []
        for s in raw_seeds or []:
            if isinstance(s, dict):
                result.append(s)
            elif isinstance(s, str):
                result.append({"title": s, "trigger_after": "?", "description": ""})
        return result

    def _process_turn_macro(self, player_decision: str) -> dict:
        """Macro historical engine — quarterly policy simulation.

        Pipeline: PolicyParser → PolicyValidator → QuarterlyEngine
        → BlackSwanInjector → MacroPolicyEngine → Narrative
        """
        ws = self.world_state_v2

        # --- Debug logger: collect LLM calls & sim events for Postgres ---
        _debug_log = None
        _session_id = getattr(self, "_debug_session_id", "")
        if _session_id:
            from ..engine.debug_logger import TurnLogCollector

            _debug_log = TurnLogCollector(
                _session_id,
                ws.turn_number + 1,
                jwt_token=getattr(self, "_debug_jwt", ""),
            )
            _debug_log.event(
                "turn_start",
                {
                    "turn": ws.turn_number + 1,
                    "year": ws.year,
                    "season": str(ws.season),
                    "player_decision": player_decision[:200],
                },
            )
            import logging

            logging.getLogger("histrategy").info(
                f"Debug log initialized for session={_session_id[:12]}... turn={ws.turn_number + 1}"
            )

        # Step 1: Parse player policy
        policy_commands = []
        if self._macro_parser:
            policy_commands = self._macro_parser.parse(player_decision, ws.player_faction_id)
        self._last_player_decision = player_decision

        # Step 2: Validate
        if self._macro_validator:
            policy_commands = self._macro_validator.validate(policy_commands, ws)

        # Step 3: Deterministic quarterly baseline
        quarter = 0
        season_str = str(ws.season).lower()
        for name, q in [
            ("spring", 0),
            ("summer", 1),
            ("autumn", 2),
            ("winter", 3),
            ("春", 0),
            ("夏", 1),
            ("秋", 2),
            ("冬", 3),
        ]:
            if name in season_str:
                quarter = q
                break

        baseline = self._quarterly_engine.execute_quarter(
            ws,
            policy_commands,
            ws.year,
            quarter,
        )
        baseline.player_decision = player_decision

        # Step 4: Black swan events
        bs_proposals = []
        if self._black_swan and self.history_engine:
            try:
                bs_proposals = self._black_swan.check_events(
                    ws.year,
                    ws.season,
                    ws,
                    deviation=ws.player_deviation,
                    history_engine=self.history_engine,
                )
                for prop in bs_proposals:
                    if prop.get("triggered"):
                        self._black_swan.inject_event(
                            prop["event_id"],
                            prop.get("effects", {}),
                            ws,
                        )
                        if _debug_log:
                            _debug_log.event(
                                "black_swan",
                                {
                                    "event_id": prop["event_id"],
                                    "effects": prop.get("effects", {}),
                                },
                            )
            except Exception as e:
                import logging

                logging.getLogger("histrategy").warning(f"Black swan check/inject failed: {e}")

        # Step 5: LLM MacroPolicyEngine
        llm_delta = {}
        _sim_tokens = 0
        if self._macro_sim and self._macro_sim.llm_available:
            mlm = getattr(self._macro_sim, "llm", None)
            _pre = mlm.total_all_tokens if mlm and hasattr(mlm, "total_all_tokens") else 0

            llm_delta = self._macro_sim.simulate(
                ws,
                policy_commands,
                player_decision,
                baseline,
                bs_proposals,
                turn_memory=getattr(self, "_turn_summaries", [])[-8:],  # last 8 quarters
            )

            if mlm and hasattr(mlm, "total_all_tokens"):
                _sim_tokens = mlm.total_all_tokens - _pre

            if _debug_log and _sim_tokens > 0:
                _debug_log.llm(
                    call_type="macro_simulate",
                    provider=getattr(mlm, "provider", "") if mlm else "",
                    model=getattr(mlm, "model", "") if mlm else "",
                    total_tokens=_sim_tokens,
                    latency_ms=0,
                )

        # Step 6: Apply LLM delta
        if llm_delta:
            for me in llm_delta.get("morale_events", []):
                fid = me.get("faction", "")
                ch = me.get("change", 0)
                if fid in ws.factions and ch:
                    cur = getattr(ws.factions[fid], "morale_actual", 50)
                    ws.factions[fid].morale_actual = max(0, min(100, cur + ch))
            # Normalize faction/territory IDs from LLM output
            faction_id_map = _build_faction_id_map(ws)
            territory_id_map = _build_territory_id_map(ws)
            for br in llm_delta.get("battle_results", []):
                if br.get("territory_captured"):
                    loc_raw = br.get("location", "")
                    att_raw = br.get("attacker", "")
                    loc = territory_id_map.get(loc_raw, loc_raw)
                    att = faction_id_map.get(att_raw, att_raw)
                    if loc in ws.territories and att in ws.factions:
                        old = ws.territories[loc].owner_id
                        ws.territories[loc].owner_id = att
                        if old in ws.factions and loc in ws.factions[old].territories:
                            ws.factions[old].territories.remove(loc)
                        if loc not in ws.factions[att].territories:
                            ws.factions[att].territories.append(loc)
                        # Absorb ~20% of defender's troops stationed in captured city
                        if old and old in ws.factions:
                            old_faction = ws.factions[old]
                            absorbed = int(old_faction.strength_actual * 0.2 / max(len(old_faction.territories), 1))
                            if absorbed > 0:
                                old_faction.strength_actual -= absorbed
                                ws.factions[att].strength_actual = (
                                    getattr(ws.factions[att], "strength_actual", 0) + absorbed
                                )
            # Auto-surrender: factions with morale < 15 and ≤ 1 territory
            for fid, f in list(ws.factions.items()):
                if fid == ws.player_faction_id:
                    continue
                if getattr(f, "is_active", True) and getattr(f, "morale_actual", 50) < 15 and len(f.territories) <= 1:
                    f.is_active = False
                    # Transfer last territory to nearest neighbor
                    if f.territories:
                        last_t = f.territories[0]
                        neighbors = getattr(ws.territories[last_t], "neighbors", [])
                        for nid in neighbors:
                            if nid in ws.territories:
                                n_owner = ws.territories[nid].owner_id
                                if n_owner in ws.factions and getattr(ws.factions[n_owner], "is_active", True):
                                    ws.territories[last_t].owner_id = n_owner
                                    if last_t not in ws.factions[n_owner].territories:
                                        ws.factions[n_owner].territories.append(last_t)
                                    break
            for br in llm_delta.get("battle_results", []):
                if not br.get("territory_captured") and br.get("defender_faction"):
                    # Handle "defeated" factions — mark inactive
                    def_raw = br.get("defender_faction", "") or br.get("defender", "")
                    def_id = faction_id_map.get(def_raw, def_raw)
                    if (
                        def_id in ws.factions
                        and def_id != ws.player_faction_id
                        and (br.get("result") in ("attack_win", "rout") or br.get("is_total_defeat"))
                    ):
                        ws.factions[def_id].is_active = False
                        # Transfer remaining territories to victor
                        att_raw = br.get("attacker", "")
                        att = faction_id_map.get(att_raw, att_raw)
                        if att in ws.factions:
                            for t_loc in list(ws.factions[def_id].territories):
                                ws.territories[t_loc].owner_id = att
                                ws.factions[def_id].territories.remove(t_loc)
                                if t_loc not in ws.factions[att].territories:
                                    ws.factions[att].territories.append(t_loc)

        # Step 6.5: Apply NPC faction independent actions
        if llm_delta:
            npc_faction_actions = llm_delta.get("npc_faction_actions", [])
            for nfa in npc_faction_actions:
                fid = nfa.get("faction", "")
                fid = faction_id_map.get(fid, fid)
                if fid not in ws.factions or fid == ws.player_faction_id:
                    continue
                faction = ws.factions[fid]
                action_type = nfa.get("action_type", "none")
                params = nfa.get("params", {})

                if action_type == "conscript":
                    amount = params.get("amount", 5000)
                    cost = int(amount * 0.5)
                    if faction.treasury >= cost:
                        faction.strength_actual = getattr(faction, "strength_actual", 0) + amount
                        faction.treasury -= cost
                elif action_type == "develop":
                    # Boost economy in a random territory
                    if faction.territories:
                        faction.treasury -= params.get("cost", 300)
                        faction.economy_actual = min(100, getattr(faction, "economy_actual", 50) + 5)
                elif action_type == "diplomacy":
                    target = nfa.get("target", "")
                    target = faction_id_map.get(target, target)
                    if target in ws.factions:
                        rel_delta = params.get("relation_delta", 10)
                        # Update relations if the faction has a relations dict
                        if hasattr(faction, "relations"):
                            cur = faction.relations.get(target, 0)
                            faction.relations[target] = max(-100, min(100, cur + rel_delta))
                elif action_type == "tax":
                    # NPC adjusts tax rate
                    new_rate = params.get("rate", 0.3)
                    if hasattr(faction, "tax_rate"):
                        faction.tax_rate = max(0.05, min(0.6, new_rate))

        # Step 7: Generate narrative (from LLM seeds + faction state)
        narrative_text = ""
        new_choices = []

        # Build macro-aware narrative from LLM delta
        narrative_parts = []
        if llm_delta:
            seeds = llm_delta.get("narrative_seeds", [])
            for s in seeds:
                narrative_parts.append(f"### {s}")

            battles = llm_delta.get("battle_results", [])
            for b in battles:
                n = b.get("narrative", "")
                if n:
                    narrative_parts.append(f"> {n}")

            diplo = llm_delta.get("diplomatic_reactions", [])
            for d in diplo:
                act = d.get("action", "")
                if act:
                    narrative_parts.append(f"**{d.get('faction', '?')}**: {act}")

            polit = llm_delta.get("political_events", [])
            for p in polit:
                desc = p.get("description", "")
                if desc:
                    narrative_parts.append(f"🏛 {desc}")

            # NPC faction independent actions
            npc_fa = llm_delta.get("npc_faction_actions", [])
            for nfa in npc_fa:
                narr = nfa.get("narrative", "")
                if narr:
                    narrative_parts.append(f"⚡ {narr}")

        narrative_text = (
            "\n\n".join(narrative_parts)
            if narrative_parts
            else (
                "All is quiet across the realm.\n"
                if getattr(self, "_scenario_language", "zh") == "en"
                else "天下大势，波澜不惊。\n"
            )
        )

        # Generate plan suggestions
        if ws.turn_number <= 1:
            # ── First turn: hard-coded suggestions (no LLM needed) ──
            new_choices = FIRST_TURN_SUGGESTIONS.get(
                ws.player_faction_id,
                FIRST_TURN_SUGGESTIONS["cao"],
            )
        elif self.narrative_engine and self.narrative_engine.is_available:
            with contextlib.suppress(Exception):
                new_choices = self.narrative_engine.generate_plan_suggestions(ws, ws.player_faction_id)

        # Step 8: Aftermath (from actual faction state, not stale baseline)
        pf = ws.factions.get(ws.player_faction_id)
        parts = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        if pf:
            if is_en:
                parts.append(f"Gold:{pf.treasury}")
                parts.append(f"Food:{pf.food}")
                parts.append(f"Morale:{getattr(pf, 'morale_actual', '?')}")
                territories = list(pf.territories) if pf.territories else []
                parts.append(f"Territories:{len(territories)}")
            else:
                parts.append(f"资金:{pf.treasury}")
                parts.append(f"粮草:{pf.food}")
                parts.append(f"民心:{getattr(pf, 'morale_actual', '?')}")
                territories = list(pf.territories) if pf.territories else []
                parts.append(f"领地:{len(territories)}")
        aftermath = "This quarter: " if is_en else "本季度："
        sep = ", " if is_en else "，"
        aftermath += sep.join(parts) + ("." if is_en else "。")

        # Add LLM narrative summary if available
        if narrative_parts and len(narrative_parts) > 1:
            suffix = "." if is_en else "。"
            aftermath += f" {narrative_parts[0].replace('### ', '')}{suffix}"

        # Knowledge cards
        kcards = []
        if llm_delta:
            kcards = self._knowledge_base.get_cards_for_events(llm_delta.get("knowledge_cards", []))
        ksummaries = []
        for kc in kcards[:3]:
            if isinstance(kc, dict):
                topic = kc.get("topic", "")
                logic = kc.get("engine_logic", "")
            else:
                topic = getattr(kc, "topic", "")
                logic = getattr(kc, "engine_logic", "")
            if topic:
                ksummaries.append(f"📚 {topic}: {logic}")

        # NPC data — normalize to plain strings (portal frontend expects strings,
        # React crashes with "a.match is not a function" on dict objects)
        npc_acts_raw = llm_delta.get("npc_actions", []) if llm_delta else []
        npc_acts = []
        for a in npc_acts_raw:
            if isinstance(a, dict):
                faction = a.get("faction", "?")
                action = a.get("action", a.get("reasoning", str(a)))
                npc_acts.append(f"{faction}: {action}")
            elif isinstance(a, str):
                npc_acts.append(a)
        npc_reacts_raw = llm_delta.get("diplomatic_reactions", []) if llm_delta else []
        npc_reacts = []
        for r in npc_reacts_raw:
            if isinstance(r, dict):
                faction = r.get("faction", "?")
                action = r.get("action", "")
                if action:
                    npc_reacts.append(f"{faction}: {action}")
            elif isinstance(r, str):
                npc_reacts.append(r)
        # Also include npc_faction_actions as NPC actions for frontend
        npc_fa = llm_delta.get("npc_faction_actions", []) if llm_delta else []
        for nfa in npc_fa:
            narr = nfa.get("narrative", "")
            if narr:
                npc_acts.append(f"{nfa.get('faction', '?')}: {narr}")

        # Game over?
        pf = ws.factions.get(ws.player_faction_id)
        game_over = not getattr(pf, "is_active", True) if pf else False

        result = {
            "narrative": narrative_text,
            "aftermath": aftermath,
            "bureaucracy": [
                {
                    "department": "尚书台",
                    "official": "尚书令",
                    "action": f"执行{len(policy_commands)}项策令",
                }
            ],
            "state_changes": {
                "food": baseline.resource_changes.get(ws.player_faction_id, {}).get("food_delta", 0),
                "treasury": baseline.resource_changes.get(ws.player_faction_id, {}).get("tax_revenue", 0),
                "morale": baseline.morale_delta.get(ws.player_faction_id, 0),
            },
            "_usage": {"command_tokens": _sim_tokens, "plan_tokens": 0, "npc_tokens": 0, "sim_tokens": _sim_tokens},
            "seeds": self._normalize_seeds(llm_delta.get("narrative_seeds", []) if llm_delta else []),
            "npc_reactions": npc_reacts,
            "npc_actions": npc_acts,
            "events_occurred": [p.get("event_id", "") for p in bs_proposals if p.get("triggered")],
            "new_choices": new_choices,
            "game_over": game_over,
            "world_state": ws,
            "knowledge_cards": ksummaries,
            "black_swan_events": [p["event_id"] for p in bs_proposals if p.get("triggered")],
        }

        # Advance turn and season
        ws.turn_number += 1
        from histrategy_engine.world import Season as _Season

        _seasons = list(_Season)
        try:
            _idx = _seasons.index(ws.season)
            ws.season = _seasons[(_idx + 1) % len(_seasons)]
            if ws.season == _seasons[0]:  # wrapped around → new year
                ws.year += 1
        except (ValueError, IndexError):
            pass

        # ── Record turn summary for LLM context in future turns ──
        narrative_seeds = llm_delta.get("narrative_seeds", []) if llm_delta else []
        summary_text = "; ".join(narrative_seeds[:2]) if narrative_seeds else narrative_text[:200]
        if not hasattr(self, "_turn_summaries"):
            self._turn_summaries = []
        season_val = ws.season.cn if hasattr(ws.season, "cn") else ws.season
        self._turn_summaries.append(
            {
                "outcome_summary": (
                    f"[{ws.year}年{season_val}] "
                    f"{player_decision[:200]}{'...' if len(player_decision) > 200 else ''}"
                    f" → {summary_text[:300]}{'...' if len(summary_text) > 300 else ''}"
                ),
                "turn": ws.turn_number,
            }
        )
        # Keep only last 8 turns to bound context growth
        if len(self._turn_summaries) > 8:
            self._turn_summaries = self._turn_summaries[-8:]

        # Attach debug log data to result for API layer to persist
        if _debug_log:
            result["_debug_log"] = {
                "llm_calls": _debug_log._llm_calls,
                "sim_events": _debug_log._sim_events,
            }

        self._save_v2()
        return result

    # ── Symmetric Multiplayer Path ───────────────────────────
    # Bridges new GameRoom/FactionSlot/DecisionBus/QuarterlyResolver
    # with the existing API response format. The single-player flow
    # internally uses this symmetric architecture for true NPC autonomy.

    def process_turn_symmetric(self, player_decision: str) -> dict:
        """Process a turn using the symmetric multi-faction architecture.

        Internally creates a GameRoom with 1 human + N AI slots,
        each AI generates its own independent LLM decision,
        then all decisions are resolved together in one quarter.
        """
        import uuid as _uuid

        from ..engine.decision_bus import collect_all_decisions
        from ..engine.game_room import GameRoom, RoomPhase
        from ..engine.quarterly_resolver import QuarterlyResolver

        ws = self.world_state_v2
        faction_id = ws.player_faction_id

        # ── Build GameRoom from engine state ──
        room = GameRoom(
            id=getattr(self, "_room_id", str(_uuid.uuid4())),
            scenario=self.scenario,
            year=ws.year,
            season=ws.season.cn if hasattr(ws.season, "cn") else str(ws.season),
            quarter_number=ws.turn_number,
            phase=RoomPhase.WAITING,
        )

        # Add human slot
        from ..engine.faction_slot import create_ai_slot, create_human_slot

        room.slots[faction_id] = create_human_slot(faction_id)

        # Add AI slots for other active factions
        for fid, f in ws.factions.items():
            if fid == faction_id or not getattr(f, "is_active", True):
                continue
            room.slots[fid] = create_ai_slot(fid)

        # Carry forward turn summaries
        if hasattr(self, "_turn_summaries"):
            room.turn_summaries = list(self._turn_summaries[-8:])

        room.start_game()

        # ── Submit human decision ──
        human_slot = room.slots.get(faction_id)
        if human_slot:
            human_slot.submit_decision(player_decision)

        # ── Collect all decisions (AI via parallel LLM) ──
        llm = getattr(self.narrative_engine, "llm", None) if self.narrative_engine else None
        if not llm and hasattr(self, "_macro_sim"):
            llm = getattr(self._macro_sim, "llm", None)

        decisions = collect_all_decisions(
            room,
            ws,
            llm=llm,
            turn_memory=room.turn_summaries,
            lang=getattr(room, "metadata", {}).get("lang", "zh"),
        )

        # ── Resolve quarter ──
        resolver = QuarterlyResolver(
            intent_parser=getattr(self, "_macro_parser", None),
            turn_controller=self.turn_controller,
            history_engine=self.history_engine,
            macro_policy_engine=getattr(self, "_macro_sim", None),
            narrative_engine=self.narrative_engine,
            black_swan_injector=getattr(self, "_black_swan", None),
            guardrail_validator=getattr(self, "guardrail_validator", None),
            state_applier=getattr(self, "state_applier", None),
        )

        quarterly = resolver.resolve(room, ws, decisions, llm=llm)

        # ── Add turn summary ──
        if quarterly.turn_summary:
            if not hasattr(self, "_turn_summaries"):
                self._turn_summaries = []
            self._turn_summaries.append(quarterly.turn_summary)
            if len(self._turn_summaries) > 8:
                self._turn_summaries = self._turn_summaries[-8:]

        # ── Collect NPC actions for response ──
        npc_actions = []
        is_en = getattr(self, "_scenario_language", "zh") == "en"
        for fid, dr in decisions.items():
            if fid != faction_id:
                faction = ws.factions.get(fid)
                if faction:
                    name = faction.name_en if is_en and faction.name_en else faction.name
                else:
                    name = fid
                npc_actions.append(f"{name}: {dr.decision_text[:80]}")

        # ── Advance season/year ──
        from histrategy_engine.world import Season as _Season

        _seasons = list(_Season)
        try:
            _idx = _seasons.index(ws.season)
            ws.season = _seasons[(_idx + 1) % len(_seasons)]
            if ws.season == _seasons[0]:
                ws.year += 1
        except (ValueError, IndexError):
            pass
        ws.turn_number += 1

        # ── Game over check ──
        game_over = None
        pf = ws.factions.get(faction_id)
        if not pf or not pf.is_active:
            game_over = True

        # ── Build response in old format ──
        narrative = quarterly.narratives.get(faction_id, "天下大势，波澜不惊。\n")

        # Per-faction narratives summary
        if len(quarterly.narratives) > 1:
            other_narratives = []
            for fid, narr in quarterly.narratives.items():
                if fid != faction_id and narr:
                    faction = ws.factions.get(fid)
                    name = faction.name if faction else fid
                    other_narratives.append(f"**{name}**: {narr[:120]}")
            if other_narratives:
                narrative += "\n\n---\n**天下动向**\n\n" + "\n\n".join(other_narratives[:3])

        aftermath = "; ".join(npc_actions[:3]) if npc_actions else "天下平静。"

        result = {
            "narrative": narrative,
            "aftermath": aftermath,
            "bureaucracy": [
                {
                    "department": "尚书台",
                    "official": "尚书令",
                    "action": f"执行{len(decisions)}个势力策令",
                }
            ],
            "state_changes": quarterly.state_changes.get(faction_id, {}),
            "_usage": {"command_tokens": 0, "plan_tokens": 0, "npc_tokens": 0, "sim_tokens": 0},
            "seeds": [],
            "npc_reactions": [],
            "npc_actions": npc_actions,
            "events_occurred": [e.get("event_id", "") for e in quarterly.history_events],
            "new_choices": [],
            "game_over": game_over,
            "world_state": ws,
            "knowledge_cards": [],
        }

        self._save_v2()
        return result

    def _process_turn_v1(self, player_decision: str) -> dict:
        """v1 turn processing (unchanged)."""
        sim_result = self.sim_engine.simulate(self.world_state, player_decision)

        if sim_result.world_state:
            self.world_state = sim_result.world_state

        result_dict = {
            "narrative": sim_result.narrative,
            "aftermath": sim_result.aftermath,
            "bureaucracy": sim_result.bureaucracy,
            "state_changes": (
                sim_result.state_changes or (sim_result.short_term.get("changes", {}) if sim_result.short_term else {})
            ),
            "seeds": sim_result.seeds,
            "npc_reactions": sim_result.npc_reactions or sim_result.npc_actions or [],
            "events_occurred": sim_result.events_occurred or [],
            "game_over": sim_result.game_over,
            "world_state": sim_result.world_state,
        }

        # Process NPC dramatic events
        from ..engine.npc_events import process_npc_drastic_events

        npc_evt_res = process_npc_drastic_events(self.world_state)

        if npc_evt_res["events_occurred"]:
            result_dict["events_occurred"].extend(npc_evt_res["events_occurred"])
            result_dict["npc_reactions"].extend(npc_evt_res["npc_reactions"])
            sc = result_dict["state_changes"]
            for k, val in npc_evt_res["state_changes"].items():
                if val:
                    sc[k] = sc.get(k, 0) + val
            betrayal_aftermaths = "\n\n" + "\n".join(npc_evt_res["events_occurred"])
            result_dict["aftermath"] = (result_dict["aftermath"] or "") + betrayal_aftermaths
            save_world(self.world_state)

        try:
            from ..engine.log_exporter import append_to_session_log

            append_to_session_log(
                self.world_state.turn,
                self.world_state.year,
                self.world_state.current_season,
                player_decision,
                result_dict,
            )
        except Exception:
            pass

        self._log_simulation_history()

        return result_dict

    def _log_simulation_history(self) -> None:
        """Write a snapshot of all factions' numerical states to simulation_history.jsonl."""
        try:
            import json
            from datetime import datetime

            from ..state.world_state import get_data_dir

            log_dir = get_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            history_file = log_dir / "simulation_history.jsonl"

            faction_data = {}

            if self._use_v2 and self.world_state_v2 is not None:
                ws = self.world_state_v2
                turn_number = ws.turn_number
                year = ws.year
                season = ws.season.cn if hasattr(ws.season, "cn") else ws.season.value
                player_faction = ws.player_faction_id

                for fid, f in ws.factions.items():
                    faction_data[fid] = {
                        "name": f.name,
                        "capital": f.capital,
                        "territories": list(f.territories) if f.territories else [],
                        "strength": getattr(f, "strength_actual", getattr(f, "strength", 0)),
                        "economy": getattr(f, "economy_actual", getattr(f, "economy", 0)),
                        "morale": getattr(f, "morale_actual", getattr(f, "morale", 0)),
                        "treasury": f.treasury,
                        "food": f.food,
                        "is_active": getattr(f, "is_active", True),
                    }
            elif self.world_state is not None:
                ws = self.world_state
                turn_number = ws.turn
                year = ws.year
                season = ws.current_season
                player_faction = ws.player_faction_id

                for fid, f in ws.factions.items():
                    faction_data[fid] = {
                        "name": f.name,
                        "capital": f.capital,
                        "territories": list(f.territories) if f.territories else [],
                        "strength": getattr(f, "strength", 0),
                        "economy": getattr(f, "economy", 0),
                        "morale": getattr(f, "morale", 0),
                        "treasury": getattr(f, "treasury", 0),
                        "food": getattr(f, "food", 0),
                        "is_active": getattr(f, "is_active", True),
                    }
            else:
                return

            entry = {
                "timestamp": datetime.now().isoformat(),
                "turn_number": turn_number,
                "year": year,
                "season": season,
                "player_faction": player_faction,
                "factions": faction_data,
                "player_decision": getattr(self, "_last_player_decision", ""),
                "player_commands": [
                    {
                        "type": getattr(c, "type", ""),
                        "params": getattr(c, "params", {}),
                        "notes": getattr(c, "notes", ""),
                    }
                    for c in getattr(self, "_last_player_commands", [])
                ],
            }

            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Failed to write simulation history log: %s", e)

    # ─── Fallbacks ────────────────────────────────────────────

    def _fallback_intro(self) -> dict:
        if self._scenario_language == "en":
            scenario = getattr(self, "scenario", "three-kingdoms")
            if "rome" in scenario:
                return {
                    "narrative": "Rome, 44 BC. Caesar is dead. The Republic teeters on the brink of civil war.",
                    "npc_actions": [
                        "Octavian crosses the Adriatic, claiming Caesar's legacy",
                        "Antony consolidates power in Rome",
                    ],
                    "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0},
                    "events_occurred": [],
                    "new_choices": ["1. Develop economy", "2. Prepare for war", "3. Seek allies", "4. Gather intelligence"],
                }
            return {
                "narrative": "The year is 207 AD. The Han dynasty crumbles; warlords vie for supremacy.",
                "npc_actions": [
                    "Cao Cao pacifies the north, eyeing the south",
                    "Sun Quan fortifies Jiangdong as Zhou Yu drills the navy",
                ],
                "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0},
                "events_occurred": [],
                "new_choices": ["1. Develop economy", "2. Prepare for war", "3. Seek allies", "4. Gather intelligence"],
            }
        return {
            "narrative": "建安十二年（公元207年），汉室倾颓，群雄逐鹿。",
            "npc_actions": ["曹操平定北方，虎视江南", "孙权坐断江东，周瑜操练水军"],
            "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0},
            "events_occurred": [],
            "new_choices": ["1. 发展经济", "2. 整军备战", "3. 结交盟友", "4. 搜集情报"],
        }

    def _fallback_plan_data(self) -> dict:
        player_name = "主公"
        if self._use_v2 and self.world_state_v2:
            player = self.world_state_v2.factions.get(self.world_state_v2.player_faction_id)
            if player:
                player_name = player.name
        elif self.world_state:
            player = self.world_state.get_player_faction()
            if player:
                player_name = player.name

        court_msg = f"【内政会议】\n\n群臣趋前侍立。时局动荡，军资匮乏，众将皆望向{player_name}，等待决断。"
        return {
            "court_dialogue": court_msg,
            "suggestions": [
                "【休养生息】发展内政与农耕",
                "【练兵备战】招募乡勇操练新军",
                "【合纵连横】派遣使者联络群雄",
                "【搜集情报】细作四出打探动向",
            ],
            "season_summary": "天下纷争未休。",
        }

    def _offline_intro(self) -> dict:
        """Faction-specific fallback intro (v1) — 207 建安十二年 scenario."""
        player = self.world_state.get_player_faction()
        if not player:
            return self._fallback_intro()

        faction_key = self.world_state.player_faction_id
        intros = {
            "cao": {
                "name": "曹操",
                "alias": "孟德",
                "location": "许昌",
                "desc": "挟天子以令诸侯，已平定北方，虎视江南",
                "advisors": "荀彧（文若）运筹帷幄，程昱（仲德）深谋远虑",
                "generals": "夏侯惇、曹仁、张辽、徐晃等猛将",
            },
            "shu": {
                "name": "刘备",
                "alias": "玄德",
                "location": "新野",
                "desc": "寄居荆州刘表帐下，屯兵新野小城，求贤若渴",
                "advisors": "徐庶（元直）暂为军师，简雍（宪和）奔走联络",
                "generals": "关羽（云长）、张飞（翼德）、赵云（子龙）",
            },
            "wu": {
                "name": "孙权",
                "alias": "仲谋",
                "location": "建业",
                "desc": "继父兄之业，坐断东南，待时而动",
                "advisors": "周瑜（公瑾）为大都督，鲁肃（子敬）谋划长远",
                "generals": "程普、黄盖、甘宁、周泰等江东宿将",
            },
        }

        info = intros.get(faction_key, intros["cao"])
        intro = (
            f"建安十二年（公元207年），天下三分之势初成。\n\n"
            f"曹操已平河北，虎视荆襄；孙权坐断江东，兵精粮足。\n\n"
            f"你，{info['name']}，字{info['alias']}，{info['desc']}。\n\n"
            f"帐下：{info['advisors']}。\n"
            f"武将：{info['generals']}听候调遣。\n"
        )

        choices = {
            "shu": [
                "1. 三顾茅庐，请诸葛亮出山辅佐",
                "2. 在新野整顿军备，操练兵马",
                "3. 派孙乾去江东联络孙权结盟",
                "4. 搜集荆州情报，关注曹操动向",
            ],
            "cao": [
                "1. 整编水师，准备南征荆州",
                "2. 安抚河北，巩固新占领土",
                "3. 派使者给孙权送劝降书",
                "4. 屯田许昌，储备粮草",
            ],
            "wu": [
                "1. 召集群臣商议抗曹之策",
                "2. 发展江东水军，建造战船",
                "3. 派鲁肃去荆州探查虚实",
                "4. 巩固江东六郡，稳定后方",
            ],
        }

        return {
            "narrative": intro,
            "npc_actions": [
                "曹操在邺城开凿玄武池训练水师",
                "孙权据江东，周瑜日夜操练水军",
                "刘表病重，荆州暗流涌动",
            ],
            "state_changes": {},
            "events_occurred": [],
            "new_choices": choices.get(
                faction_key,
                [
                    "1. 发展经济和军力",
                    "2. 派使者联络盟友",
                    "3. 整军备战",
                    "4. 搜集情报",
                ],
            ),
        }

    def _offline_v2_suggestions(self) -> list[str]:
        """Offline suggestions from engine state."""
        ws = self.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return ["【固本培元】发展内政，积蓄实力。"]

        suggestions = []
        if player.food < 3000 and player.territories:
            suggestions.append(f"【劝课农桑】发展{player.territories[0]}的农业，提升粮食产量。")
        if player.strength_actual < 10000 and player.treasury > 2000 and player.territories:
            suggestions.append(f"【征募乡勇】在{player.territories[0]}招募步兵，增强军力。")
        if not suggestions and player.territories:
            suggestions.append(f"【固本培元】发展{player.territories[0]}，提升开发度。")
        suggestions.append("【合纵连横】审视外交局势，联络盟友。")
        return suggestions[:4]

    def _offline_v2_narrative(self, turn_result: TurnResult) -> str:
        """Offline narrative from turn result."""
        from ..llm.narrative import NarrativeEngine

        dummy = NarrativeEngine(None, language=getattr(self, "_scenario_language", "zh"))
        return dummy._offline_narrative(turn_result)


def _suppress_stderr():
    """Context manager to suppress stderr during optional LLM calls."""
    import sys as _sys

    class _Suppress:
        def __enter__(self):
            self._stderr = _sys.stderr
            _sys.stderr = open(os.devnull, "w")
            return self

        def __exit__(self, *args):
            _sys.stderr.close()
            _sys.stderr = self._stderr

    return _Suppress()


def _inject_v3_into_baseline(baseline_result, v3_delta: dict) -> None:
    """Inject v3 delta events into baseline for narrative generation."""
    if not hasattr(baseline_result, "character_events"):
        baseline_result.character_events = []
    if not hasattr(baseline_result, "diplomatic_events"):
        baseline_result.diplomatic_events = []

    # Add political events as character/diplomatic events
    for pe in v3_delta.get("political_events", []):
        baseline_result.character_events.append(
            {
                "event": pe.get("type", "court_dispute"),
                "description": pe.get("description", ""),
                "faction": pe.get("faction", ""),
            }
        )

    # Add npc actions as diplomatic events
    for na in v3_delta.get("npc_actions", []):
        baseline_result.diplomatic_events.append(
            {
                "faction": na.get("faction", ""),
                "action": na.get("action", ""),
                "target": na.get("target", ""),
                "reason": na.get("reasoning", ""),
            }
        )

    # Add morale events
    for me in v3_delta.get("morale_events", []):
        baseline_result.character_events.append(
            {
                "event": "morale_change",
                "faction": me.get("faction", ""),
                "change": me.get("change", 0),
                "reason": me.get("reason", ""),
            }
        )


def _auto_mobilize_for_attack(commands: list, world_state) -> None:
    """Auto-mobilize faction reserves for attack commands in v3 mode.

    When a player says "attack with 60K from wancheng" but only 5K army
    exists, transfer faction.strength_actual reserves to the army.
    """
    from histrategy_engine.world import UnitType

    faction = world_state.factions.get(world_state.player_faction_id)
    if not faction:
        return

    for cmd in commands:
        if getattr(cmd, "type", "") != "attack":
            continue
        source = cmd.params.get("source_territory", "")
        requested = cmd.params.get("amount", 0)
        if not source or not requested:
            continue

        army = None
        for a in world_state.armies.values():
            if a.location == source and a.faction_id == world_state.player_faction_id:
                army = a
                break
        if not army:
            continue

        current = army.total_troops
        reserves = faction.strength_actual - current
        needed = min(requested - current, reserves)

        if needed > 0 and needed <= reserves:
            infantry_needed = int(needed * 0.9)
            cavalry_needed = needed - infantry_needed
            army.units[UnitType.INFANTRY] = army.units.get(UnitType.INFANTRY, 0) + infantry_needed
            army.units[UnitType.CAVALRY] = army.units.get(UnitType.CAVALRY, 0) + cavalry_needed
            faction.strength_actual -= needed


def _build_faction_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → faction pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "曹操"),
    annotated names (e.g. "曹操(cao)"), or bare pinyin IDs.
    """
    id_map: dict[str, str] = {}
    for fid, f in ws.factions.items():
        id_map[fid] = fid  # "cao" → "cao"
        if hasattr(f, "name") and f.name:
            id_map[f.name] = fid  # "曹操" → "cao"
    return id_map


def _build_territory_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → territory pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "襄阳"),
    or bare pinyin IDs (e.g. "xiangyang").
    """
    id_map: dict[str, str] = {}
    for tid, t in ws.territories.items():
        id_map[tid] = tid  # "xiangyang" → "xiangyang"
        if hasattr(t, "name") and t.name:
            id_map[t.name] = tid  # "襄阳" → "xiangyang"
    return id_map


def apply_event_effects(world_state: V2WorldState, effects: dict) -> None:
    """Apply the outcomes/effects of a triggered historical event directly to WorldState."""
    from histrategy_engine.world import FactionState

    def transfer_territory(tid: str, fid: str):
        if tid in world_state.territories:
            old_owner_id = world_state.territories[tid].owner_id
            world_state.territories[tid].owner_id = fid
            # Remove from old owner's territories list
            if old_owner_id and old_owner_id in world_state.factions:
                old_faction = world_state.factions[old_owner_id]
                if tid in old_faction.territories:
                    old_faction.territories.remove(tid)
            # Add to new owner's territories list
            if fid and fid in world_state.factions:
                new_faction = world_state.factions[fid]
                if tid not in new_faction.territories:
                    new_faction.territories.append(tid)

    for key, value in effects.items():
        # 1. Advisor joining
        # e.g., "liubei_advisor": "zhugeliang"
        if key.endswith("_advisor") and value and value != "none":
            faction_id = key.split("_")[0]
            faction_id = V2_FACTION_MAP.get(faction_id, faction_id)
            char = world_state.characters.get(value)
            if char:
                char.faction_id = faction_id
                char.loyalty = 95
                char.alive = True
                ruler_id = world_state.factions.get(faction_id, FactionState()).ruler_id
                ruler = world_state.characters.get(ruler_id)
                if ruler:
                    char.location = ruler.location

        # 2. Characters dying/status changes
        # e.g., "guanyu_dead": True, "zhangfei_dead": True
        elif key.endswith("_dead") and value is True:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.alive = False

        # 3. Locations
        # e.g., "liubei_location": "jiangkou"
        elif key.endswith("_location") and value:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.location = value

        # 4. Territory ownership
        # e.g., "jingzhou_owner": "cao" or "liubei" or "sunquan"
        elif key == "jingzhou_owner" and value:
            target_fid = V2_FACTION_MAP.get(value, value)
            for tid in ["xiangyang", "jiangling", "jiangxia", "changsha", "lingling", "wuling", "guiyang", "nanyang"]:
                transfer_territory(tid, target_fid)

        # e.g. "liubei_controls": "yizhou"
        elif key.endswith("_controls") and value:
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            if value == "yizhou":
                for tid in ["chengdu", "hanshui", "hanzhong", "ziyang", "baqi"]:
                    transfer_territory(tid, target_fid)
            elif value == "jingzhou":
                for tid in [
                    "xiangyang",
                    "jiangling",
                    "jiangxia",
                    "changsha",
                    "lingling",
                    "wuling",
                    "guiyang",
                    "nanyang",
                ]:
                    transfer_territory(tid, target_fid)

        # e.g., "liubei_territories_add": ["wuling", "changsha", "lingling", "guiyang"]
        elif key.endswith("_territories_add") and isinstance(value, list):
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            for tid in value:
                transfer_territory(tid, target_fid)

        # 5. Relations
        # e.g., "sunliu_relation": "+20" or "-10"
        elif key.endswith("_relation") and value:
            f1_f2 = key.rsplit("_", 1)[0]
            f1, f2 = None, None
            if "sunliu" in f1_f2 or "sun_liu" in f1_f2:
                f1, f2 = "wu", "shu"
            if f1 and f2:
                try:
                    delta = int(value)
                    fac1 = world_state.factions.get(f1)
                    if fac1:
                        fac1.relations[f2] = max(-100, min(100, fac1.relations.get(f2, 0) + delta))
                    fac2 = world_state.factions.get(f2)
                    if fac2:
                        fac2.relations[f1] = max(-100, min(100, fac2.relations.get(f1, 0) + delta))
                except Exception:
                    pass

        # 6. Army/Power losses
        elif key.endswith("_army") and value == "devastated":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.3))
        elif key.endswith("_power") and value == "crippled":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.4))
                faction.treasury = max(500, int(faction.treasury * 0.5))
                faction.food = max(500, int(faction.food * 0.5))
