"""
三國志略 — Game Engine

The engine orchestrates the WorldModel (LLM-driven), world state,
and player memory. It provides a unified interface for the CLI.

Key changes from v1:
- Uses LLM-driven WorldModel instead of template-driven offline sim
- World state is stored as structured JSON in ~/.histrategy/
- Player memory auto-loads on game start
- Every player decision has visible, LLM-generated consequences
"""

from __future__ import annotations

from ..engine.offline_sim import simulate_turn_offline
from ..engine.world import GameWorld
from ..engine.world_sim_interface import WorldSimEngine
from ..llm.adapter import LLMAdapter
from ..llm.world_model import WorldModel
from ..state.world_state import (
    FactionState,
    WorldState,
    has_existing_game,
    load_world,
    save_world,
)

# ─── Initial faction configurations ────────────────────────

FACTION_CONFIGS = {
    "cao": {
        "name": "曹操", "ruler": "caocao",
        "capital": "xuchang", "territories": ["xuchang"],
        "strength": 30000, "economy": 55, "morale": 75,
        "treasury": 10000, "food": 5000,
    },
    "shu": {
        "name": "刘备", "ruler": "liubei",
        "capital": "pingyuan", "territories": ["pingyuan"],
        "strength": 5000, "economy": 35, "morale": 90,
        "treasury": 3000, "food": 2000,
    },
    "wu": {
        "name": "孙坚", "ruler": "sunjian",
        "capital": "changsha", "territories": ["changsha"],
        "strength": 20000, "economy": 50, "morale": 80,
        "treasury": 8000, "food": 4000,
    },
    "yuan_shao": {
        "name": "袁绍", "ruler": "yuanshao",
        "capital": "yecheng", "territories": ["yecheng", "jizhou"],
        "strength": 80000, "economy": 75, "morale": 70,
        "treasury": 15000, "food": 8000,
    },
}

NPC_FACTION_CONFIGS = {
    "dongzhuo": {"name": "董卓", "ruler": "dongzhuo",
                 "capital": "luoyang", "territories": ["luoyang", "changan"],
                 "strength": 150000, "economy": 80, "morale": 40,
                 "treasury": 50000, "food": 30000},
    "caocao": {"name": "曹操", "ruler": "caocao",
               "capital": "xuchang", "territories": ["xuchang"],
               "strength": 30000, "economy": 55, "morale": 75,
               "treasury": 10000, "food": 5000},
    "yuanshao": {"name": "袁绍", "ruler": "yuanshao",
                  "capital": "yecheng", "territories": ["yecheng", "jizhou"],
                  "strength": 80000, "economy": 75, "morale": 70,
                  "treasury": 15000, "food": 8000},
    "sunjian": {"name": "孙坚", "ruler": "sunjian",
                "capital": "changsha", "territories": ["changsha"],
                "strength": 20000, "economy": 50, "morale": 80,
                "treasury": 8000, "food": 4000},
    "liubiao": {"name": "刘表", "ruler": "liubiao",
                "capital": "xiangyang", "territories": ["xiangyang", "jiangling"],
                "strength": 30000, "economy": 60, "morale": 65,
                "treasury": 12000, "food": 7000},
    "gongsunzan": {"name": "公孙瓒", "ruler": "gongsunzan",
                   "capital": "beiping", "territories": ["beiping"],
                   "strength": 40000, "economy": 45, "morale": 70,
                   "treasury": 6000, "food": 4000},
}


def create_initial_world(player_faction_id: str) -> WorldState:
    """Create a fresh world state for a new game."""
    from ..engine.log_exporter import clear_session_log
    clear_session_log()

    state = WorldState()
    state.scenario = "190"
    state.player_faction_id = player_faction_id

    # Add player faction
    pfc = FACTION_CONFIGS.get(player_faction_id)
    if pfc:
        state.factions[player_faction_id] = FactionState(
            id=player_faction_id, **{k: v for k, v in pfc.items() if k != "ruler"},
            ruler_id=pfc["ruler"],
        )

    # Add NPC factions (skip the one the player chose)
    for fid, fc in NPC_FACTION_CONFIGS.items():
        # Map the player's faction to the NPC version
        skip = False
        fc["ruler"]
        if player_faction_id == "cao" and fid == "caocao" or player_faction_id == "shu" and fid == "liubei" or player_faction_id == "wu" and fid == "sunjian" or player_faction_id == "yuan_shao" and fid == "yuanshao":
            skip = True

        if not skip:
            state.factions[fid] = FactionState(
                id=fid, **{k: v for k, v in fc.items() if k != "ruler"},
                ruler_id=fc["ruler"],
            )

    # Save initial world state
    save_world(state)

    return state


class GameEngine:
    """
    Main game engine orchestrating world state and LLM interaction.

    - On startup: auto-loads existing game from ~/.histrategy/ if present
    - Turn processing: uses WorldModel (LLM) when available, fallback to offline
    - State persistence: saves to disk after every turn
    """

    def __init__(self, llm: LLMAdapter | None = None, scenario: str = "190",
                 new_game: bool = False, sim_engine: WorldSimEngine | None = None):
        self.llm = llm
        self.scenario = scenario

        # Load or initialize the engine
        if sim_engine is not None:
            self.sim_engine = sim_engine
        elif llm is not None:
            from ..llm.llm_sim_engine import LLMSimEngine
            from ..engine.resilient_sim_engine import ResilientSimEngine
            self.sim_engine = ResilientSimEngine(LLMSimEngine(llm))
        else:
            from ..engine.offline_sim_engine import OfflineSimEngine
            self.sim_engine = OfflineSimEngine()

        # Try to load existing game, unless new_game is requested
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

        self._legacy_world = None  # Keep for backward compat with offline_sim

    @property
    def legacy_world(self):
        if hasattr(self, "sim_engine"):
            engine = self.sim_engine
            if hasattr(engine, "_primary"):
                engine = engine._primary
            if hasattr(engine, "_legacy_world") and engine._legacy_world is not None:
                return engine._legacy_world
        return self._legacy_world

    @legacy_world.setter
    def legacy_world(self, value):
        self._legacy_world = value
        # Also sync to offline engine if present
        if hasattr(self, "sim_engine"):
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
        self.world_state = create_initial_world(faction_id)
        self.game_started = True

        # Also init legacy world for backward compat
        self.legacy_world = GameWorld(scenario=self.scenario)
        self.legacy_world.player_faction_id = faction_id

    def get_intro_scene(self) -> dict:
        """Get the introductory scene."""
        if not self.game_started:
            return self._fallback_intro()

        if self.llm is not None:
            model = WorldModel(self.llm)
            return model.generate_intro(self.world_state)
        else:
            # Offline mode: use faction-specific intro
            return self._offline_intro()

    def get_plan_data(self) -> dict:
        """Get the current turn's plan data (advisor speeches, suggestions, season summary)."""
        if not self.game_started:
            return self._fallback_plan_data()

        # Retrieve pressure hint if narrative director is present
        pressure_hint = ""
        if hasattr(self, "sim_engine"):
            engine = self.sim_engine
            # If it's a ResilientSimEngine, get the primary engine
            if hasattr(engine, "_primary"):
                engine = engine._primary
            if hasattr(engine, "_narrative_director"):
                pressure_hint = engine._narrative_director.get_pressure_hint(
                    self.world_state.turn, self.world_state.player_deviation
                )

        from ..llm.game_master import GameMaster
        if self.llm is not None:
            gm = GameMaster(self.llm)
            return gm.generate_plan_mode(self.world_state, pressure_hint=pressure_hint)
        else:
            return self._fallback_plan_data()

    def _fallback_plan_data(self) -> dict:
        player = self.world_state.get_player_faction()
        ruler_name = player.name if player else "主公"
        court_msg = (
            f"【{self.world_state.year}年{self.world_state.current_season_cn} · 内政会议】\n\n"
            f"群臣趋前侍立。时局动荡，军资匮乏，众将皆望向{ruler_name}，等待决断。"
        )
        return {
            "court_dialogue": court_msg,
            "suggestions": [
                "【休养生息】发展内政与农耕",
                "【练兵备战】招募乡勇操练新军",
                "【合纵连横】派遣使者联络群雄",
                "【搜集情报】细作四出打探动向",
            ],
            "season_summary": f"{self.world_state.year}年{self.world_state.current_season_cn}，天下纷争未休。",
        }

    def process_turn(self, player_decision: str) -> dict:
        """Process a player's decision and return results using the WorldSimEngine.

        Automatically logs the turn to current_session_log.json.
        """
        if not self.game_started:
            return self._fallback_intro()

        # Run simulation
        sim_result = self.sim_engine.simulate(self.world_state, player_decision)

        # Update local state reference
        if sim_result.world_state:
            self.world_state = sim_result.world_state

        result_dict = {
            "narrative": sim_result.narrative,
            "aftermath": sim_result.aftermath,
            "bureaucracy": sim_result.bureaucracy,
            "state_changes": sim_result.state_changes or (sim_result.short_term.get("changes", {}) if sim_result.short_term else {}),
            "seeds": sim_result.seeds,
            "npc_reactions": sim_result.npc_reactions or sim_result.npc_actions or [],
            "events_occurred": sim_result.events_occurred or [],
            "game_over": sim_result.game_over,
            "world_state": sim_result.world_state,
        }

        # Process NPC dramatic events (e.g. defection / betrayal)
        from ..engine.npc_events import process_npc_drastic_events
        npc_evt_res = process_npc_drastic_events(self.world_state)
        
        if npc_evt_res["events_occurred"]:
            result_dict["events_occurred"].extend(npc_evt_res["events_occurred"])
            result_dict["npc_reactions"].extend(npc_evt_res["npc_reactions"])
            
            # Merge state changes
            sc = result_dict["state_changes"]
            for k, val in npc_evt_res["state_changes"].items():
                if val:
                    sc[k] = sc.get(k, 0) + val
            
            # Add dramatic message to aftermath
            betrayal_aftermaths = "\n\n" + "\n".join(npc_evt_res["events_occurred"])
            result_dict["aftermath"] = (result_dict["aftermath"] or "") + betrayal_aftermaths
            
            # Save world since we modified faction/character stats directly
            save_world(self.world_state)

        # Log this turn to the active session log
        from ..engine.log_exporter import append_to_session_log
        append_to_session_log(
            self.world_state.turn,
            self.world_state.year,
            self.world_state.current_season,
            player_decision,
            result_dict,
        )

        return result_dict

    def _fallback_intro(self) -> dict:
        return {
            "narrative": "初平元年（190 AD），汉室倾颓，群雄逐鹿。",
            "npc_actions": ["董卓挟天子以令诸侯"],
            "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                              "treasury": 0, "food": 0},
            "events_occurred": [],
            "new_choices": ["1. 发布檄文", "2. 发展经济", "3. 结交盟友"],
        }

    def _offline_intro(self) -> dict:
        """Faction-specific fallback intro."""
        player = self.world_state.get_player_faction()
        if not player:
            return self._fallback_intro()

        faction_key = self.world_state.player_faction_id
        # Use inline data
        intros = {
            "cao": {
                "name": "曹操", "alias": "孟德", "location": "兖州",
                "desc": "散尽家财在兖州起兵，号召天下英雄共讨董卓",
                "advisors": "荀彧（文若）运筹帷幄，郭嘉（奉孝）奇谋百出",
                "generals": "夏侯惇、曹仁等猛将",
            },
            "shu": {
                "name": "刘备", "alias": "玄德", "location": "平原县",
                "desc": "以汉室宗亲之名，与关羽、张飞桃园结义，在平原县栖身",
                "advisors": "简雍（宪和）出谋划策，孙乾（公祐）奔走联络",
                "generals": "关羽（云长）、张飞（翼德）两位义弟",
            },
            "wu": {
                "name": "孙坚", "alias": "文台", "location": "长沙",
                "desc": "人称『江东猛虎』，在长沙厉兵秣马，准备北上讨董",
                "advisors": "程普（德谋）为军师，朱治（君理）运筹帷幄",
                "generals": "程普、黄盖、韩当、祖茂等江东宿将",
            },
            "yuan_shao": {
                "name": "袁绍", "alias": "本初", "location": "邺城",
                "desc": "四世三公之后，被推举为讨董盟主，据有冀、青、幽、并四州",
                "advisors": "田丰（元皓）运筹帷幄，沮授（则注）献奇谋",
                "generals": "颜良、文丑两员河北上将，张郃、高览等猛将",
            },
        }

        info = intros.get(faction_key, intros["cao"])

        intro = (
            f"初平元年（190 AD），董卓废少帝立献帝，暴虐无道，天下震动。\n"
            f"\n"
            f"你，{info['name']}，字{info['alias']}，{info['desc']}。\n"
            f"\n"
            f"你的帐下已有数位谋臣武将：{info['advisors']}，\n"
            f"更有{info['generals']}听候调遣。\n"
            f"\n"
            f"然而天下大势并不乐观：\n"
            f"- 董卓挟天子在洛阳，拥西凉铁骑十五万\n"
            f"- 袁绍据河北四州，兵多将广\n"
            f"- 刘表坐拥荆州，保持中立\n"
            f"- 孙坚在长沙厉兵秣马\n"
            f"\n"
            f"这是一个英雄辈出的时代。你的每一个决策，都将改变天下的命运。"
        )

        choices = {
            "yuan_shao": [
                "1. 以盟主身份号令诸侯，共讨董卓",
                "2. 先巩固河北四州，发展实力",
                "3. 派使者联络曹操、刘备等势力",
                "4. 坐观成败，让诸侯先去消耗董卓",
            ],
            "shu": [
                "1. 响应讨董号召，带关羽张飞投奔联军",
                "2. 在平原县招兵买马，积蓄实力",
                "3. 派简雍去徐州联络陶谦",
                "4. 投靠公孙瓒，借势发展",
            ],
            "wu": [
                "1. 率军北上，响应讨董联盟",
                "2. 先平定江东山越，巩固后方",
                "3. 联合刘表，共抗董卓",
                "4. 据长江天险，坐观天下变化",
            ],
        }

        return {
            "narrative": intro,
            "npc_actions": [
                "董卓挟天子以令诸侯，作威作福",
                f"{info['name']}在{info['location']}招兵买马",
                "孙坚整军备战，准备北上讨董",
            ],
            "state_changes": {
                "strength": player.strength,
                "economy": player.economy,
                "morale": player.morale,
                "treasury": player.treasury,
                "food": player.food,
            },
            "events_occurred": [],
            "new_choices": choices.get(faction_key, [
                "1. 发布讨董檄文，联络诸侯",
                "2. 先巩固领地，发展经济和军力",
                "3. 派使者联络袁绍，争取盟主之位",
                "4. 坐观成败",
            ]),
        }
