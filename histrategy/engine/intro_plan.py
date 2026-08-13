"""GameEngine intro/plan mixin: scene generation, plan data, fallbacks."""
from __future__ import annotations

from ..llm.game_master import GameMaster
from .helpers import EARLY_TURNS_SUGGESTIONS, FIRST_TURN_SUGGESTIONS, _suppress_stderr


def _resolve_early_suggestions(scenario: str, faction_id: str, turn: int, lang: str) -> list[str]:
    """Resolve suggestions from EARLY_TURNS_SUGGESTIONS dict.

    Args:
        scenario: Scenario ID (e.g. 'three-kingdoms', 'rome-triumvirate')
        faction_id: Faction identifier
        turn: Turn number (1-based, 1-4 supported)
        lang: Language ('zh' or 'en')

    Returns:
        List of suggestion strings, or empty list if not found.
    """
    scenario_data = EARLY_TURNS_SUGGESTIONS.get(scenario, {})
    faction_data = scenario_data.get(faction_id, {})
    turn_data = faction_data.get(turn, {})
    return turn_data.get(lang, turn_data.get("zh", []))


class IntroPlanMixin:
    """Mixin providing intro scene and plan data methods for GameEngine."""

    # ── Scenario-aware intro narrative builders ──────────────────

    _ERA_FALLBACKS = {
        "nanming": (
            "崇祯十七年（公元{year}年），李自成破北京，崇祯帝殉国。\n"
            "吴三桂开关引清军入主中原，天下板荡。\n"
            "弘光帝朱由崧在南京匆匆即位，江北四镇各自为政。\n"
            "大清摄政王多尔衮坐镇北京，虎视江南。\n\n"
        ),
        "rome-triumvirate": (
            "罗马建城{auc}年（公元前{year}年），凯撒遇刺，共和国分崩离析。\n"
            "屋大维、安东尼、雷必达三雄并立，各怀异志。\n"
            "地中海世界的命运悬于一线。\n\n"
        ),
    }
    _ERA_FALLBACKS_EN = {
        "nanming": (
            "Year AD {year}. Li Zicheng's rebels have taken Beijing; the Chongzhen Emperor is dead.\n"
            "Wu Sangui has opened the Shanhai Pass — Qing banners now flood the Central Plains.\n"
            "The Hongguang court scrambles to hold Nanjing; Dorgon watches from Beijing.\n\n"
        ),
        "rome-triumvirate": (
            "{year} BC (AUC {auc}). Caesar lies dead; the Republic fractures.\n"
            "Octavian, Antony, and Lepidus — the Second Triumvirate — divide the Roman world.\n"
            "The fate of the Mediterranean hangs by a thread.\n\n"
        ),
    }

    def _build_intro_narrative(self, player, capital_name: str, ws) -> str:
        """Build scenario-aware intro narrative (zh)."""
        scenario = getattr(self, "scenario", "three-kingdoms")
        era = self._ERA_FALLBACKS.get(scenario)
        if era:
            auc = ws.year + 753 if scenario == "rome-triumvirate" else 0
            era_text = era.format(year=ws.year, auc=auc) if "{auc}" in era else era.format(year=ws.year)
        else:
            # Default Three Kingdoms
            era_text = (
                f"建安{ws.year - 196}年（公元{ws.year}年），汉室倾颓，诸侯并起。\n"
                f"曹操迎天子于许昌，挟天子以令诸侯，已据中原大半。\n"
                f"孙权继父兄之业，稳坐江东。\n\n"
            )
        return (
            f"### 天下大势\n{era_text}"
            f"### 主公处境\n"
            f"你，{player.name}，以{capital_name}为根基，"
            f"麾下兵卒{player.strength_actual}，粮草{player.food}，资金{player.treasury}。\n"
            f"当审时度势，谋定而后动。"
        )

    def _build_intro_narrative_en(self, player, capital_name: str, ws) -> str:
        """Build scenario-aware intro narrative (en)."""
        scenario = getattr(self, "scenario", "three-kingdoms")
        era = self._ERA_FALLBACKS_EN.get(scenario)
        if era:
            auc = ws.year + 753 if scenario == "rome-triumvirate" else 0
            era_text = era.format(year=ws.year, auc=auc) if "{auc}" in era else era.format(year=ws.year)
        else:
            era_text = (
                f"Year {ws.year - 196} of Jian'an (AD {ws.year}). "
                f"The Han dynasty crumbles; warlords rise across the land.\n"
                f"Cao Cao holds the Emperor at Xuchang, commanding the realm in name, "
                f"and controls most of the Central Plains.\n"
                f"Sun Quan, heir to his father and brother's legacy, rules firmly over Jiangdong.\n\n"
            )
        return (
            f"### The Realm\n{era_text}"
            f"### Your Position\n"
            f"You are {player.name}, ruling from {capital_name}. "
            f"You command {player.strength_actual} troops, with {player.food} bushels of grain "
            f"and {player.treasury} gold in the treasury.\n"
            f"Survey the realm and plan your next move."
        )

    # ── Public API ────────────────────────────────────────────────

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

        # Use faction-specific deterministic suggestions for intro (turn 1)
        faction_suggestions = _resolve_early_suggestions(
            getattr(self, "scenario", "three-kingdoms"),
            ws.player_faction_id,
            1,
            getattr(self, "_scenario_language", "zh"),
        )
        if not faction_suggestions:
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
                self._build_intro_narrative(player, capital_name, ws)
            )
            if getattr(self, "_scenario_language", "zh") != "en"
            else (
                self._build_intro_narrative_en(player, capital_name, ws)
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
        turn_num = getattr(ws, "turn_number", 1) or 1
        if turn_num <= 4:
            # ── Early turns (1-4): hard-coded per-scenario suggestions (no LLM) ──
            early = _resolve_early_suggestions(
                getattr(self, "scenario", "three-kingdoms"),
                ws.player_faction_id,
                turn_num,
                getattr(self, "_scenario_language", "zh"),
            )
            if early:
                suggestions = early
            else:
                # Fallback: use FIRST_TURN_SUGGESTIONS for backward compat
                suggestions = FIRST_TURN_SUGGESTIONS.get(
                    ws.player_faction_id,
                    FIRST_TURN_SUGGESTIONS.get("cao", []),
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
        scenario = getattr(self, "scenario", "three-kingdoms")
        if scenario in self._ERA_FALLBACKS:
            return {
                "narrative": self._ERA_FALLBACKS[scenario].format(year=207),
                "npc_actions": [],
                "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0},
                "events_occurred": [],
                "new_choices": ["1. 发展经济", "2. 整军备战", "3. 结交盟友", "4. 搜集情报"],
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

        scenario = getattr(self, "scenario", "three-kingdoms")
        if scenario in self._ERA_FALLBACKS:
            # Generic fallback for non-three-kingdoms scenarios
            intro = (
                self._ERA_FALLBACKS[scenario].format(year=207)
                + "\n你，执掌一方势力。\n\n"
                + "当审时度势，谋定而后动。\n"
            )
        else:
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
