"""
三國志略 — Game Engine

The engine orchestrates the GameMaster (LLM-driven), world state,
and player memory. It provides a unified interface for the CLI.

v2 mode: Uses histrategy-engine package (Map/Character/Domestic/Military/
Decision/Turn/History engines) + NarrativeEngine for read-only narration.
Falls back to v1 when histrategy-engine is not importable.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

# ─── v1 imports (always available) ────────────────────────────────

from ..engine.offline_sim import simulate_turn_offline
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
    from histrategy_engine.world import TurnResult, WorldState as V2WorldState
    from histrategy_engine.turn import TurnController
    from histrategy_engine.map import MapEngine
    from histrategy_engine.character import CharacterEngine
    from histrategy_engine.domestic import DomesticEngine
    from histrategy_engine.military import MilitaryEngine
    from histrategy_engine.ai import DecisionEngine
    from histrategy_engine.history import HistoryEngine

# ─── v2 detection ─────────────────────────────────────────────────

_V2_AVAILABLE = False
try:
    from histrategy_engine import (  # noqa: F811
        CharacterEngine,
        DecisionEngine,
        DomesticEngine,
        HistoryEngine,
        MapEngine,
        MilitaryEngine,
        TurnController,
        WorldState as V2WorldState,
    )
    _V2_AVAILABLE = True
except ImportError:
    pass

# ─── Initial faction configurations (v1) ──────────────────────────

FACTION_CONFIGS = {
    "cao": {
        "name": "曹操", "ruler": "caocao",
        "capital": "xuchang", "territories": ["xuchang", "luoyang", "yecheng", "changan"],
        "strength": 80000, "economy": 75, "morale": 75,
        "treasury": 20000, "food": 15000,
    },
    "shu": {
        "name": "刘备", "ruler": "liubei",
        "capital": "xinye", "territories": ["xinye"],
        "strength": 8000, "economy": 30, "morale": 85,
        "treasury": 3000, "food": 3000,
    },
    "wu": {
        "name": "孙权", "ruler": "sunquan",
        "capital": "jianye", "territories": ["jianye", "wujun", "kuaiji", "lujiang"],
        "strength": 50000, "economy": 60, "morale": 80,
        "treasury": 12000, "food": 10000,
    },
}

NPC_FACTION_CONFIGS = {
    "liubiao": {"name": "刘表", "ruler": "liubiao",
                "capital": "xiangyang", "territories": ["xiangyang", "jiangling", "jiangxia"],
                "strength": 40000, "economy": 60, "morale": 55,
                "treasury": 15000, "food": 10000},
    "zhanglu": {"name": "张鲁", "ruler": "zhanglu",
                "capital": "hanshui", "territories": ["hanshui"],
                "strength": 15000, "economy": 40, "morale": 70,
                "treasury": 5000, "food": 5000},
    "liuzhang": {"name": "刘璋", "ruler": "liuzhang",
                 "capital": "chengdu", "territories": ["chengdu", "jiangzhou"],
                 "strength": 35000, "economy": 55, "morale": 50,
                 "treasury": 10000, "food": 8000},
    "machao": {"name": "马超", "ruler": "machao",
               "capital": "tianshui", "territories": ["tianshui", "wuwei"],
               "strength": 25000, "economy": 45, "morale": 75,
               "treasury": 6000, "food": 5000},
}


def create_initial_world(player_faction_id: str) -> WorldState:
    """Create a fresh world state for a new game (v1)."""
    from ..engine.log_exporter import clear_session_log
    clear_session_log()

    state = WorldState()
    state.scenario = "207"
    state.player_faction_id = player_faction_id

    pfc = FACTION_CONFIGS.get(player_faction_id)
    if pfc:
        state.factions[player_faction_id] = FactionState(
            id=player_faction_id, **{k: v for k, v in pfc.items() if k != "ruler"},
            ruler_id=pfc["ruler"],
        )

    for fid, fc in NPC_FACTION_CONFIGS.items():
        # Skip the NPC that matches the player's faction
        skip = False
        if (
            player_faction_id == "cao" and fid == "caocao"
            or player_faction_id == "shu" and fid == "liubei"
            or player_faction_id == "wu" and fid == "sunquan"
        ):
            skip = True

        if not skip:
            state.factions[fid] = FactionState(
                id=fid, **{k: v for k, v in fc.items() if k != "ruler"},
                ruler_id=fc["ruler"],
            )

    save_world(state)
    return state


# ─── V2 faction maps ──────────────────────────────────────────────

V2_FACTION_MAP: dict[str, str] = {
    "cao": "cao",
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

    def __init__(self, llm: LLMAdapter | None = None, scenario: str = "207",
                 new_game: bool = False, sim_engine: WorldSimEngine | None = None,
                 force_v1: bool = False):
        self.llm = llm
        self.scenario = scenario
        force_v1_env = os.environ.get("HISTRATEGY_FORCE_V1", "").lower() in ("true", "1")
        self._use_v2 = _V2_AVAILABLE and not force_v1 and not force_v1_env

        # ─── v2 initialization ────────────────────────────────
        if self._use_v2:
            self._init_v2(scenario, new_game)
        else:
            self._init_v1(llm, scenario, new_game, sim_engine)

    # ─── v2 initialization ────────────────────────────────────

    def _init_v2(self, scenario: str, new_game: bool) -> None:
        """Initialize the v2 engine stack."""
        from .loader import build_world_state, resolve_knowledge_path

        knowledge_path = resolve_knowledge_path()
        self._knowledge_path = knowledge_path

        # Initialize all 7 engines
        self.map_engine = MapEngine()
        self.char_engine = CharacterEngine()
        self.domestic_engine = DomesticEngine()
        self.military_engine = MilitaryEngine()
        self.decision_engine = DecisionEngine()

        # Turn controller orchestrates the 5 core engines
        self.turn_controller = TurnController(
            map_engine=self.map_engine,
            char_engine=self.char_engine,
            domestic_engine=self.domestic_engine,
            military_engine=self.military_engine,
            decision_engine=self.decision_engine,
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

        if self.llm and self.llm.is_available:
            from ..llm.narrative import NarrativeEngine
            self.narrative_engine = NarrativeEngine(self.llm)

            from ..parser.intent import IntentParser
            self.intent_parser = IntentParser(self.llm)

            from ..parser.validator import CommandValidator
            self.command_validator = CommandValidator(self.map_engine)
        else:
            # Offline mode: still have parser/validator (keyword-based)
            from ..parser.intent import IntentParser
            self.intent_parser = IntentParser(None)  # keyword fallback

            from ..parser.validator import CommandValidator
            self.command_validator = CommandValidator(self.map_engine)

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

    def _try_load_v2_save(self) -> V2WorldState | None:
        """Attempt to load a v2 game save from disk."""
        import json
        import os as _os

        save_dir = os.environ.get("HISTRATEGY_DATA_DIR",
                                    _os.path.expanduser("~/.histrategy"))
        v2_save = _os.path.join(save_dir, "world_v2.json")
        if not _os.path.isfile(v2_save):
            return None

        try:
            with open(v2_save, "r") as f:
                data = json.load(f)
            # Reconstruct from saved JSON (simplified: rebuild from factions)
            return self._rebuild_from_save(data)
        except Exception:
            return None

    def _rebuild_from_save(self, data: dict) -> V2WorldState:
        """Rebuild a V2WorldState from saved JSON data."""
        from .loader import build_world_state
        faction_id = data.get("player_faction_id", "shu")
        scenario_id = data.get("scenario", "207")
        return build_world_state(faction_id, scenario_id, self._knowledge_path)

    def _save_v2(self) -> None:
        """Save the v2 world state to disk."""
        import json
        import os as _os

        save_dir = os.environ.get("HISTRATEGY_DATA_DIR",
                                    _os.path.expanduser("~/.histrategy"))
        _os.makedirs(save_dir, exist_ok=True)
        v2_save = _os.path.join(save_dir, "world_v2.json")

        ws = self.world_state_v2
        data = {
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
                    "territories": f.territories,
                    "is_active": f.is_active,
                    "prestige": f.prestige,
                    "legitimacy": f.legitimacy,
                    "strength_actual": f.strength_actual,
                    "economy_actual": f.economy_actual,
                    "morale_actual": f.morale_actual,
                    "treasury": f.treasury,
                    "food": f.food,
                    "tax_rate": f.tax_rate,
                    "relations": f.relations,
                }
                for fid, f in ws.factions.items()
            },
        }

        with open(v2_save, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ─── v1 initialization (unchanged) ────────────────────────

    def _init_v1(self, llm, scenario, new_game, sim_engine) -> None:
        """Original v1 initialization path."""
        self._use_v2 = False

        if sim_engine is not None:
            self.sim_engine = sim_engine
        elif llm is not None:
            from ..llm.llm_sim_engine import LLMSimEngine
            from ..engine.resilient_sim_engine import ResilientSimEngine
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
        """v2 path: build WorldState from knowledge data."""
        from .loader import build_world_state

        mapped = V2_FACTION_MAP.get(faction_id, faction_id)
        scenario_id = "207"

        self.world_state_v2 = build_world_state(mapped, scenario_id, self._knowledge_path)

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

        # Use deterministic template suggestions (LLM reserved for plan phase)
        suggestions = [
            f"【休养生息】发展{player.capital}的内政与农耕",
            f"【练兵备战】招募乡勇操练新军",
            "【合纵连横】派遣使者联络群雄",
            "【搜集情报】细作四出打探动向",
        ]

        narrative = (
            f"### 天下大势\n"
            f"建安{ws.year - 196}年（公元{ws.year}年），汉室倾颓，诸侯并起。\n"
            f"曹操迎天子于许昌，挟天子以令诸侯，已据中原大半。\n"
            f"孙权继父兄之业，稳坐江东。\n\n"
            f"### 主公处境\n"
            f"你，{player.name}，以{player.capital}为根基，"
            f"麾下兵卒{player.strength_actual}，粮草{player.food}，资金{player.treasury}。\n"
            f"当审时度势，谋定而后动。"
        )

        npc_actions = []
        for fid, fs in ws.factions.items():
            if not fs.is_active or fid == ws.player_faction_id:
                continue
            npc_actions.append(
                f"{fs.name}据有{len(fs.territories)}城，"
                f"兵力{fs.strength_actual:,}。"
            )

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

        # Generate suggestions from narrative engine
        if self.narrative_engine and self.narrative_engine.is_available:
            with _suppress_stderr():
                suggestions = self.narrative_engine.generate_plan_suggestions(
                    ws, ws.player_faction_id
                )
        else:
            suggestions = self._offline_v2_suggestions()

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
                            court_parts.append(
                                f"边境警报：{nid}（{nt.name}）方向，"
                                f"{nf.name}军为{rel_str}关系。"
                            )

        season_summary = (
            f"{ws.year}年{ws.season.cn}，"
            f"天下纷争未休，{player.name}当何去何从？"
        )

        return {
            "court_dialogue": "\n".join(court_parts),
            "suggestions": suggestions,
            "season_summary": season_summary,
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
            gm = GameMaster(self.llm)
            return gm.generate_plan_mode(self.world_state, pressure_hint=pressure_hint)
        else:
            return self._fallback_plan_data()

    # ─── Turn Processing ──────────────────────────────────────

    def process_turn(self, player_decision: str) -> dict:
        """Process a player's decision and return results.

        v2: IntentParser → CommandValidator → TurnController.execute_turn() →
            NarrativeEngine.generate_turn_narrative()
        v1: WorldSimEngine.simulate()
        """
        if not self.game_started:
            return self._fallback_intro()

        if self._use_v2:
            return self._process_turn_v2(player_decision)
        else:
            return self._process_turn_v1(player_decision)

    def _process_turn_v2(self, player_decision: str) -> dict:
        """v2 turn processing pipeline."""
        ws = self.world_state_v2
        current_year = ws.year
        current_season = ws.season

        # Step 1: Parse player intent into commands
        player_commands = []
        if self.intent_parser:
            player_commands = self.intent_parser.parse(
                player_decision, ws.player_faction_id
            )

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
                    turn_result.history_events.append({
                        "event_id": prop.event_id,
                        "title": prop.title,
                        "outcome": prop.effects.get("outcome", "default"),
                        "description": prop.effects.get("outcome_description", ""),
                        "effects": prop.effects.get("effects", {}),
                    })
            except Exception as e:
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

        if self.narrative_engine and self.narrative_engine.is_available:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Submit both tasks
                future_narrative = executor.submit(
                    self.narrative_engine.generate_turn_narrative,
                    turn_result,
                    deviation=ws.player_deviation,
                    averted_events=averted_list
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
                "message": (
                    "# 势力覆灭\n\n"
                    "你的势力已经不复存在。\n"
                    "乱世之中，成王败寇。\n\n"
                    "感谢游玩《三國志略》。"
                ),
            }

        # Check if all territory has been unified
        active_factions = [
            fid for fid, f in ws.factions.items() if f.is_active and f.strength_actual > 0
        ]
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
            "command_tokens": 0,   # Narrative + Suggestions (all LLM calls this turn)
            "plan_tokens": 0,      # Suggestions generation
            "npc_tokens": 0,       # NPC AI (not yet tracked separately)
            "sim_tokens": 0,       # Deterministic simulation (free)
        }
        if self.narrative_engine and self.narrative_engine.is_available:
            llm = getattr(self.narrative_engine, "llm", None)
            if llm and hasattr(llm, "total_all_tokens"):
                _usage["command_tokens"] = max(llm.total_all_tokens - _tok_snap.get("total", 0), 0)

        # Generate a concise aftermath from resource changes + key events
        aftermath_parts = []
        if resource_changes.get("food_delta", 0) != 0:
            sign = "+" if resource_changes["food_delta"] > 0 else ""
            aftermath_parts.append(f"粮草{sign}{resource_changes['food_delta']}")
        if resource_changes.get("tax_revenue", 0) != 0:
            sign = "+" if resource_changes["tax_revenue"] > 0 else ""
            aftermath_parts.append(f"资金{sign}{resource_changes['tax_revenue']}")
        if resource_changes.get("strength_delta", 0) != 0:
            sign = "+" if resource_changes["strength_delta"] > 0 else ""
            aftermath_parts.append(f"兵力{sign}{resource_changes['strength_delta']}")
        if resource_changes.get("morale_delta", 0) != 0:
            sign = "+" if resource_changes["morale_delta"] > 0 else ""
            aftermath_parts.append(f"民心{sign}{resource_changes['morale_delta']}")
        
        # Extract the last 2-3 sentences of narrative as summary
        if narrative_text:
            import re as _re
            sentences = _re.split(r"[。！？]", narrative_text)
            sentences = [s.strip() for s in sentences if s.strip()]
            summary_sentences = sentences[-2:] if len(sentences) > 2 else sentences[-1:]
            aftermath_text = "。".join(summary_sentences) + "。"
        else:
            aftermath_text = "局势已定，天下大势尽在掌握。\n"
        
        if aftermath_parts:
            aftermath_text = "本回合：" + "，".join(aftermath_parts) + "。" + "\n\n" + aftermath_text
        
        result = {
            "narrative": narrative_text,
            "aftermath": aftermath_text,
            "bureaucracy": [{
                "department": "军机处",
                "official": "参军",
                "action": f"执行{len(player_commands)}项军令"
            }],
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
            ] if self.history_engine else [],
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
                    result["aftermath"] = (
                        f"【史官注：历史偏离度 {ws.player_deviation:.2f}】\n\n"
                        + result["aftermath"]
                    )
            except Exception:
                pass

        # Save state
        self._save_v2()

        # Log turn
        try:
            from ..engine.log_exporter import append_to_session_log
            append_to_session_log(
                ws.turn_number, ws.year, ws.season.value,
                player_decision, result,
            )
        except Exception:
            pass

        self._log_simulation_history()

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
                sim_result.state_changes or
                (sim_result.short_term.get("changes", {}) if sim_result.short_term else {})
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
                self.world_state.turn, self.world_state.year,
                self.world_state.current_season,
                player_decision, result_dict,
            )
        except Exception:
            pass

        self._log_simulation_history()

        return result_dict

    def _log_simulation_history(self) -> None:
        """Write a snapshot of all factions' numerical states to simulation_history.jsonl."""
        try:
            from ..state.world_state import get_data_dir
            import json
            from datetime import datetime
            
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
                        "is_active": getattr(f, "is_active", True)
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
                        "is_active": getattr(f, "is_active", True)
                    }
            else:
                return
                
            entry = {
                "timestamp": datetime.now().isoformat(),
                "turn_number": turn_number,
                "year": year,
                "season": season,
                "player_faction": player_faction,
                "factions": faction_data
            }
            
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to write simulation history log: %s", e)

    # ─── Fallbacks ────────────────────────────────────────────

    def _fallback_intro(self) -> dict:
        return {
            "narrative": "建安十二年（公元207年），汉室倾颓，群雄逐鹿。",
            "npc_actions": ["曹操平定北方，虎视江南", "孙权坐断江东，周瑜操练水军"],
            "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                              "treasury": 0, "food": 0},
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

        court_msg = (
            f"【内政会议】\n\n"
            f"群臣趋前侍立。时局动荡，军资匮乏，众将皆望向{player_name}，等待决断。"
        )
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
            "cao": {"name": "曹操", "alias": "孟德", "location": "许昌",
                    "desc": "挟天子以令诸侯，已平定北方，虎视江南",
                    "advisors": "荀彧（文若）运筹帷幄，程昱（仲德）深谋远虑",
                    "generals": "夏侯惇、曹仁、张辽、徐晃等猛将"},
            "shu": {"name": "刘备", "alias": "玄德", "location": "新野",
                    "desc": "寄居荆州刘表帐下，屯兵新野小城，求贤若渴",
                    "advisors": "徐庶（元直）暂为军师，简雍（宪和）奔走联络",
                    "generals": "关羽（云长）、张飞（翼德）、赵云（子龙）"},
            "wu": {"name": "孙权", "alias": "仲谋", "location": "建业",
                   "desc": "继父兄之业，坐断东南，待时而动",
                   "advisors": "周瑜（公瑾）为大都督，鲁肃（子敬）谋划长远",
                   "generals": "程普、黄盖、甘宁、周泰等江东宿将"},
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
            "new_choices": choices.get(faction_key, [
                "1. 发展经济和军力",
                "2. 派使者联络盟友",
                "3. 整军备战",
                "4. 搜集情报",
            ]),
        }

    def _offline_v2_suggestions(self) -> list[str]:
        """Offline suggestions from engine state."""
        ws = self.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return ["【固本培元】发展内政，积蓄实力。"]

        suggestions = []
        if player.food < 3000 and player.territories:
            suggestions.append(
                f"【劝课农桑】发展{player.territories[0]}的农业，提升粮食产量。"
            )
        if player.strength_actual < 10000 and player.treasury > 2000 and player.territories:
            suggestions.append(
                f"【征募乡勇】在{player.territories[0]}招募步兵，增强军力。"
            )
        if not suggestions and player.territories:
            suggestions.append(
                f"【固本培元】发展{player.territories[0]}，提升开发度。"
            )
        suggestions.append("【合纵连横】审视外交局势，联络盟友。")
        return suggestions[:4]

    def _offline_v2_narrative(self, turn_result: TurnResult) -> str:
        """Offline narrative from turn result."""
        from ..llm.narrative import NarrativeEngine
        dummy = NarrativeEngine(None)
        return dummy._offline_narrative(turn_result)


def _suppress_stderr():
    """Context manager to suppress stderr during optional LLM calls."""
    import contextlib
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
                for tid in ["xiangyang", "jiangling", "jiangxia", "changsha", "lingling", "wuling", "guiyang", "nanyang"]:
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
