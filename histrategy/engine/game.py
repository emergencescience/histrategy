"""The 三國志略 game engine - orchestrates world + LLM."""

from __future__ import annotations

import json
from typing import Optional

from ..engine.world import GameWorld
from ..engine.offline_sim import simulate_turn_offline
from ..llm.adapter import LLMAdapter
from ..llm.prompts import GAME_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT


FACTION_INTROS = {
    "cao": {
        "name": "曹操", "alias": "孟德",
        "location": "兖州",
        "desc": "散尽家财在兖州起兵，号召天下英雄共讨董卓",
        "advisors": "荀彧（文若）运筹帷幄，郭嘉（奉孝）奇谋百出",
        "generals": "夏侯惇、曹仁等猛将",
        "strength": 30000, "economy": 55, "morale": 75, "treasury": 10000, "food": 5000,
        "capital_name": "许昌",
    },
    "shu": {
        "name": "刘备", "alias": "玄德",
        "location": "平原县",
        "desc": "以汉室宗亲之名，与关羽、张飞桃园结义，在平原县栖身",
        "advisors": "简雍（宪和）出谋划策，孙乾（公祐）奔走联络",
        "generals": "关羽（云长）、张飞（翼德）两位义弟",
        "strength": 5000, "economy": 35, "morale": 90, "treasury": 3000, "food": 2000,
        "capital_name": "平原",
    },
    "wu": {
        "name": "孙坚", "alias": "文台",
        "location": "长沙",
        "desc": '人称"江东猛虎"，在长沙厉兵秣马，准备北上讨董',
        "advisors": "程普（德谋）为军师，朱治（君理）运筹帷幄",
        "generals": "程普、黄盖、韩当、祖茂等江东宿将",
        "strength": 20000, "economy": 50, "morale": 80, "treasury": 8000, "food": 4000,
        "capital_name": "长沙",
    },
    "yuan_shao": {
        "name": "袁绍", "alias": "本初",
        "location": "邺城",
        "desc": "四世三公之后，被推举为讨董盟主，据有冀、青、幽、并四州",
        "advisors": "田丰（元皓）运筹帷幄，沮授（则注）献奇谋",
        "generals": "颜良、文丑两员河北上将，张郃、高览等猛将",
        "strength": 80000, "economy": 75, "morale": 70, "treasury": 15000, "food": 8000,
        "capital_name": "邺城",
    },
}

RULER_ID_MAP = {"caocao": "cao", "liubei": "shu", "sunjian": "wu", "yuanshao": "yuan_shao"}


class GameEngine:
    """Main game engine orchestrating world state and LLM interaction."""

    def __init__(self, llm: Optional[LLMAdapter] = None, scenario: str = "190"):
        self.world = GameWorld(scenario=scenario)
        self.llm = llm
        self.game_started = False

    def set_player_faction(self, faction_id: str):
        self.world.player_faction_id = faction_id
        self.game_started = True

    def build_system_message(self) -> dict:
        return {"role": "system", "content": GAME_SYSTEM_PROMPT}

    def build_state_message(self) -> dict:
        """Build a message with current game state."""
        summary = self.world.get_state_summary()
        regions = self.world.get_regions_table()
        content = f"""以下是当前游戏世界状态：

时间：{self.world.current_year}年 {self.world.current_season}
回合：{self.world.turn_count}

玩家势力信息：
- 势力：{summary['player_faction']['name']}
- 君主：{summary['player_faction']['ruler']}
- 兵力：{summary['player_faction']['strength']:,}
- 经济：{summary['player_faction']['economy']}/100
- 民心：{summary['player_faction']['morale']}/100
- 资金：{summary['player_faction']['treasury']:,}
- 粮草：{summary['player_faction']['food']:,}
- 领地：{', '.join(summary['player_faction']['territories'])}

你的谋士武将：
{chr(10).join(f"- {c['name']}（字{c['alias']}）：擅长{c['skills']}，忠诚度{c['loyalty']}" for c in summary['player_characters'])}

天下势力一览：
{chr(10).join(f"- {f['name']}：兵力{f['strength']:,}，领地{f['territory_count']}处，经济{f['economy']}/100" for f in summary['all_factions'])}

全境地图：
{chr(10).join(f"  {r['name']} - {r['owner']}" for r in sorted(regions, key=lambda x: x['name']))}

已完成的历史事件：{', '.join(summary['completed_events']) if summary['completed_events'] else '无'}
"""
        return {"role": "user", "content": content}

    def build_decision_message(self, player_decision: str) -> dict:
        return {
            "role": "user",
            "content": f"主公的决策：{player_decision}\n\n请根据主公的决策，模拟这个季度的发展，输出JSON格式的回报。"
        }

    def process_turn(self, player_decision: str) -> dict:
        """Process a player's decision and return the narrative result."""
        # Offline mode: use rule-based simulation
        if self.llm is None:
            return self._offline_turn(player_decision)

        messages = [
            self.build_system_message(),
            {"role": "user", "content": INITIAL_SCENE_PROMPT if self.world.turn_count == 0
             else f"这是上一个季度的结果。"},
        ]

        if self.world.turn_count > 0:
            messages.append(self.build_state_message())

        messages.append(self.build_decision_message(player_decision))

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=4096,
            )

            # Apply state changes
            state_changes = result.get("state_changes", {})
            self.world.apply_effects(player_decision, result.get("narrative", ""), state_changes)

            # Mark events that occurred
            for event_title in result.get("events_occurred", []):
                self.world.mark_event_occurred(event_title)

            # Advance game time
            self.world.advance_turn()
            self.world.history_log.append(
                f"[{self.world.current_year}年{self.world.current_season}] "
                f"主公决策：{player_decision[:50]}..."
            )

            return result

        except Exception as e:
            return {
                "narrative": f"（系统异常：{str(e)}。但天下大势仍在运转。）",
                "npc_actions": ["各方势力继续行动..."],
                "state_changes": {},
                "events_occurred": [],
                "new_choices": ["1. 继续当前策略", "2. 重新尝试获取军情"],
            }

    def _offline_turn(self, player_decision: str) -> dict:
        """Process a turn using the offline rule-based simulator."""
        result = simulate_turn_offline(self.world, player_decision)

        state_changes = result.get("state_changes", {})
        self.world.apply_effects(player_decision, result.get("narrative", ""), state_changes)

        self.world.advance_turn()
        self.world.history_log.append(
            f"[{self.world.current_year}年{self.world.current_season}] "
            f"主公决策：{player_decision[:50]}..."
        )

        return result

    def get_intro_scene(self) -> dict:
        """Get the introductory scene for when the player first starts."""
        if self.llm is None:
            return self._offline_intro()

        messages = [
            self.build_system_message(),
            {"role": "user", "content": INITIAL_SCENE_PROMPT},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=4096,
            )
            self.world.history_log.append(
                f"[{self.world.current_year}年{self.world.current_season}] 初平元年，曹操起兵讨董。"
            )
            return result
        except Exception as e:
            fallback = self._offline_intro()
            return fallback

    def _fallback_intro(self) -> dict:
        """Fallback intro if no faction selected."""
        return {
            "narrative": "初平元年（190 AD），汉室倾颓，群雄逐鹿。",
            "npc_actions": ["董卓挟天子以令诸侯"],
            "state_changes": {"strength": 10000, "economy": 50, "morale": 50,
                              "treasury": 5000, "food": 3000, "npc_changes": {}},
            "events_occurred": [],
            "new_choices": ["1. 发布檄文", "2. 发展经济", "3. 结交盟友"],
        }

    def _offline_intro(self) -> dict:
        """Generate faction-specific intro scene."""
        player = self.world.get_player_faction()
        if not player:
            return self._fallback_intro()

        # Determine which faction intro to use
        key = RULER_ID_MAP.get(player.ruler_id or "", "cao")
        info = FACTION_INTROS.get(key, FACTION_INTROS["cao"])

        intro = (
            f"初平元年（190 AD），董卓废少帝立献帝，暴虐无道，天下震动。\n"
            f"\n"
            f"你，{info['name']}，字{info['alias']}，{info['desc']}。\n"
            f"\n"
            f"你的帐下已有数位谋臣武将：{info['advisors']}，\n"
            f"更有{info['generals']}听候调遣。\n"
            f"\n"
            f"然而天下大势并不乐观：\n"
            f"- 董卓挟天子在长安，拥西凉铁骑十五万\n"
            f"- 袁绍据河北四州，兵多将广，被推举为讨董盟主\n"
            f"- 袁术在南阳虎视眈眈\n"
            f"- 刘表坐拥荆州，保持中立\n"
            f"- 孙坚在长沙厉兵秣马\n"
            f"- 刘备、关羽、张飞三兄弟在平原县栖身\n"
            f"\n"
            f"这是一个英雄辈出的时代。你的每一个决策，都将改变天下的命运。"
        )

        # Faction-specific first-turn choices
        if key == "yuan_shao":
            choices = [
                "1. 以盟主身份号令诸侯，共讨董卓",
                "2. 先巩固河北四州，发展实力",
                "3. 派使者联络曹操、刘备等势力",
                "4. 坐观成败，让诸侯先去消耗董卓",
            ]
        elif key == "shu":
            choices = [
                "1. 响应讨董号召，带关羽张飞投奔联军",
                "2. 在平原县招兵买马，积蓄实力",
                "3. 派简雍去徐州联络陶谦",
                "4. 投靠公孙瓒，借势发展",
            ]
        elif key == "wu":
            choices = [
                "1. 率军北上，响应讨董联盟",
                "2. 先平定江东山越，巩固后方",
                "3. 联合刘表，共抗董卓",
                "4. 据长江天险，坐观天下变化",
            ]
        else:  # cao
            choices = [
                "1. 发布讨董檄文，联络诸侯",
                "2. 先巩固兖州，发展经济和军力",
                "3. 派使者联络袁绍，争取盟主之位",
                "4. 派人潜入洛阳，营救汉献帝",
            ]

        return {
            "narrative": intro,
            "npc_actions": [
                "董卓挟天子以令诸侯，作威作福",
                f"{info['name']}在{info['location']}招兵买马",
                "孙坚整军备战，准备北上讨董",
            ],
            "state_changes": {
                "strength": info["strength"],
                "economy": info["economy"],
                "morale": info["morale"],
                "treasury": info["treasury"],
                "food": info["food"],
                "npc_changes": {},
            },
            "events_occurred": [],
            "new_choices": choices,
        }
