"""The 三國志略 game engine - orchestrates world + LLM."""

from __future__ import annotations

import json
from typing import Optional

from ..engine.world import GameWorld
from ..engine.offline_sim import simulate_turn_offline
from ..llm.adapter import LLMAdapter
from ..llm.prompts import GAME_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT


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
            return {
                "narrative": f"初平元年（190 AD），董卓乱政，天下动荡。曹操在兖州散家财起兵，号召天下诸侯共讨董卓。作为曹操，你将在这个群雄逐鹿的时代书写自己的传奇。\n\n（注：由于 {str(e)}，系统暂无法加载AI叙事。请先决策。）",
                "npc_actions": ["董卓挟天子以令诸侯", "袁绍在河北集结兵力", "孙坚在长沙厉兵秣马"],
                "state_changes": {"strength": 30000, "economy": 55, "morale": 75, "treasury": 10000, "food": 5000, "npc_changes": {}},
                "events_occurred": [],
                "new_choices": [
                    "1. 发布讨董檄文，联络诸侯",
                    "2. 先巩固兖州，发展经济和军力",
                    "3. 派使者联络袁绍，争取盟主之位",
                    "4. 派人潜入洛阳，营救汉献帝",
                ],
            }

    def _offline_intro(self) -> dict:
        """Generate an intro scene using the offline simulator."""
        intro = f"""初平元年（190 AD），董卓废少帝立献帝，暴虐无道，天下震动。

你，曹操，字孟德，散尽家财在兖州起兵，号召天下英雄共讨董卓。

你的帐下已有数位谋臣武将：荀彧（文若）运筹帷幄，郭嘉（奉孝）奇谋百出，
更有夏侯惇、曹仁等猛将听候调遣。

然而天下大势并不乐观：
- 董卓挟天子在长安，拥西凉铁骑十五万
- 袁绍据河北四州，兵多将广，被推举为讨董盟主
- 袁术在南阳虎视眈眈
- 刘表坐拥荆州，保持中立
- 孙坚在长沙厉兵秣马
- 刘备、关羽、张飞三兄弟在平原县栖身

这是一个英雄辈出的时代。你的每一个决策，都将改变天下的命运。"""

        return {
            "narrative": intro,
            "npc_actions": [
                "董卓在长安挟天子以令诸侯，作威作福",
                "袁绍在邺城发出檄文，召集各路诸侯",
                "孙坚整军备战，准备北上讨董",
            ],
            "state_changes": {
                "strength": 30000, "economy": 55, "morale": 75,
                "treasury": 10000, "food": 5000,
                "npc_changes": {},
            },
            "events_occurred": [],
            "new_choices": [
                "1. 发布讨董檄文，联络诸侯",
                "2. 先巩固兖州，发展经济和军力",
                "3. 派使者联络袁绍，争取盟主之位",
                "4. 派人潜入洛阳，营救汉献帝",
            ],
        }
