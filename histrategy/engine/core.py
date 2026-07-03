"""GameEngine core: initialization, engine stack, save/load, faction setup."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

# ─── v1 imports (always available) ────────────────────────────────
from ..engine.world import GameWorld
from ..engine.world_sim_interface import WorldSimEngine
from ..state.world_state import (
    WorldState,
    has_existing_game,
    load_world,
)

if TYPE_CHECKING:
    from histrategy_engine.ai import DecisionEngine
    from histrategy_engine.character import CharacterEngine
    from histrategy_engine.domestic import DomesticEngine
    from histrategy_engine.history import HistoryEngine
    from histrategy_engine.map import MapEngine
    from histrategy_engine.military import MilitaryEngine
    from histrategy_engine.turn import TurnController
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
from histrategy_engine import WorldState as V2WorldState

from .faction_slot import FACTION_LEGACY_MAP as V2_FACTION_MAP  # noqa: F401
from .helpers import (
    create_initial_world,
)


class _ResilientSimEngine(WorldSimEngine):
    """Auto-fallback wrapper: try primary (LLM), fall back to offline on failure.

    This is intentionally kept simple — it's a thin compatibility shim that
    ensures the game loop never breaks when the LLM API is unavailable.
    Replaces the former engine/resilient_sim_engine.py module.
    """

    def __init__(self, primary: WorldSimEngine, fallback: WorldSimEngine) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def engine_id(self) -> str:
        return f"resilient({self._primary.engine_id})"

    @property
    def requires_llm(self) -> bool:
        return False  # Always has a non-LLM fallback

    def simulate(self, state, player_action):
        import logging
        logger = logging.getLogger(__name__)

        if self._primary.requires_llm and not self._primary.health_check():
            logger.warning(
                "Primary engine %s unavailable, using fallback %s",
                self._primary.engine_id,
                self._fallback.engine_id,
            )
            result = self._fallback.simulate(state, player_action)
            result.narrative = f"[离线模式] {result.narrative}"
            return result

        try:
            return self._primary.simulate(state, player_action)
        except Exception as exc:
            logger.warning(
                "Primary engine %s failed (%s), using fallback %s",
                self._primary.engine_id,
                exc,
                self._fallback.engine_id,
            )
            result = self._fallback.simulate(state, player_action)
            result.narrative = f"[离线模式] {result.narrative}"
            return result


class GameEngineCore:
    """Core engine: initialization, engine stack, save/load, faction setup."""

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
        self._use_v2 = not force_v1
        self._use_v3 = False

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
        if self._use_v3 and llm and llm.is_available:
            from ..engine.black_swan import BlackSwanInjector
            from ..engine.knowledge_layer import KnowledgeBase
            from ..engine.macro_policy_engine import MacroPolicyEngine
            from ..engine.quarterly_engine import QuarterlyEngine
            from ..policy.policy_parser import PolicyParser
            from ..policy.policy_validator import PolicyValidator

            # PolicyParser uses the default LLM
            self._macro_parser = PolicyParser(llm)
            self._macro_validator = PolicyValidator()
            self._quarterly_engine = QuarterlyEngine(scenario=self.scenario)
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
            from ..llm.llm_sim_engine import LLMSimEngine
            from ..engine.offline_sim_engine import OfflineSimEngine

            primary = LLMSimEngine(llm)
            fallback = OfflineSimEngine()
            self.sim_engine = _ResilientSimEngine(primary, fallback)
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
        self.game_started = True

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

        self._save_v2()

    def _set_player_faction_v1(self, faction_id: str) -> None:
        """v1 path: original faction setup."""
        self.world_state = create_initial_world(faction_id, self.scenario)

        self.legacy_world = GameWorld(scenario=self.scenario)
        self.legacy_world.player_faction_id = faction_id

    # ─── Intro Scene ──────────────────────────────────────────
    def set_debug_context(self, session_id: str) -> None:
        """Set session context for debug logging (called from API layer)."""
        self._debug_session_id = session_id
        import logging

        short_sid = session_id[:12] if len(session_id) > 12 else session_id
        logging.getLogger("histrategy").info(f"Debug context set: session={short_sid}...")

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

