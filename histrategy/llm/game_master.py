"""
三國志略 — LLM Game Master

The LLM IS the game engine. No templates. No hardcoded content.
Every advisor speech, suggestion, consequence, and NPC action comes from the LLM.

Two modes:
  Plan Mode    → LLM generates advisor court + 4 suggestions based on world state
  Command Mode → LLM generates execution results based on player's free-text decision
"""

from __future__ import annotations

import contextlib
import copy

from ..state.world_state import (
    HISTORICAL_TIMELINE_207,
    EventEntry,
    HistoricalMode,
    WorldState,
    add_event_to_history,
    get_historical_context,
    get_recent_history,
    save_world,
)
from .adapter import LLMAdapter
from .context_helpers import collect_dead_characters
from .prompt_loader import (
    GAMEMASTER_COMMAND_SYSTEM,
    GAMEMASTER_COMMAND_SYSTEM_EN,
    GAMEMASTER_INTRO_SYSTEM,
    GAMEMASTER_INTRO_SYSTEM_EN,
    GAMEMASTER_PLAN_SYSTEM,
    GAMEMASTER_PLAN_SYSTEM_EN,
)

# ─── System Prompts ─────────────────────────────────────────

# Prompts are now loaded from external files via .prompt_loader


# ─── Mode-Specific Prompts ───────────────────────────────────

HISTORICAL_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「正史模式」（偏离度低）：天下局势与历史高度吻合，
  谋臣们的提议应当尽量符合正史走向或在历史框架内做出合理规划。
- 引导玩家顺应历史的主线事件。
"""

DIVERGENT_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「演义/走向偏离模式」（偏离度中）：历史轨迹已被玩家改变。
  谋臣们需要意识到历史已经分叉，建言要基于当前的“偏离状态”进行合情合理的推演，
  而不是生搬硬套正史。
"""

FREEFORM_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「幻想沙盒模式」（偏离度高）：历史进程已完全脱轨。
  请抛开任何历史必然性的包袱，纯粹根据各势力实力和人物性格进行合理的利益冲突和争霸建言。
"""

HISTORICAL_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「正史模式」：推演结果需要维持强烈的历史重力。
  玩家的微调可以影响结果，但大势（如董卓迁都、群雄割据）会产生强烈的牵引力。
"""

DIVERGENT_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「演义/走向偏离模式」：历史已被改变。
  请在推演中体现蝴蝶效应，展示事件如何以全新的因果逻辑发展。史官会将此记为《建安异录》。
"""

FREEFORM_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「幻想沙盒模式」：历史已完全脱轨，属于全自由度沙盒。
  请根据当前的军事实力、民心等数据进行纯粹的博弈推演，NPC的行为应当完全自驱。
"""


# ─── Context builders ───────────────────────────────────────


def _build_plan_context(state: WorldState) -> str:
    """Build the world state context for Plan Mode LLM prompt."""
    player = state.get_player_faction()
    if not player:
        return ""

    # Resolve territory names for player
    pt_names = []
    for tid in player.territories:
        t = state.territories.get(tid)
        if t:
            pt_names.append(t.name)

    lines = [
        "## 当前时间",
        f"{state.year}年{state.current_season_cn} | 第{state.turn}回合",
        "",
        f"## 玩家势力：{player.name}",
        f"- 兵力：{player.strength:,}",
        f"- 经济：{player.economy}/100",
        f"- 民心：{player.morale}/100",
        f"- 资金：{player.treasury:,}",
        f"- 粮草：{player.food:,}",
        f"- 首都：{player.capital}",
        f"- 领地：{', '.join(pt_names) if pt_names else '暂无'}",
        "",
        "## 天下势力",
    ]

    for fid, fs in state.factions.items():
        if not fs.is_active or fid == state.player_faction_id:
            continue
        t_names = []
        for tid in fs.territories:
            t = state.territories.get(tid)
            if t:
                t_names.append(t.name)
        t_str = ", ".join(t_names) if t_names else "无"
        lines.append(
            f"- {fs.name}（君主: {fs.ruler_id}）：兵力{fs.strength:,}，"
            f"经济{fs.economy}，民心{fs.morale}。控制城池：{t_str}"
        )

    # Resolve deceased characters
    dead_names = collect_dead_characters(state)
    if dead_names:
        lines.append("")
        lines.append("## 已亡故/不活跃人物（不可在此回合复活或出现活跃事迹）")
        lines.append(f"- {', '.join(dead_names)}")

    # Historical context
    historical = get_historical_context(state.year)
    if historical:
        lines.append("")
        lines.append("## 历史参考（可不完全遵循）")
        lines.append(historical)

    # Recent player decisions
    history = get_recent_history(3)
    if history:
        lines.append("")
        lines.append("## 最近决策")
        for ev in history:
            d = ev.get("player_decision", "")
            if d:
                lines.append(f"- 「{d[:60]}」")

    # NPC emotional states
    if state.npc_states:
        lines.append("")
        lines.append("## 臣子/将领情绪与忠诚度")
        for cid, ns in state.npc_states.items():
            char_name = state.characters[cid].name if cid in state.characters else cid
            lines.append(f"- {char_name}：忠诚度 {ns.loyalty}，情绪【{ns.mood.value}】")
            if ns.grievance:
                lines.append(f"  缘由：{ns.grievance}")

    return "\n".join(lines)


def _build_command_context(state: WorldState, player_decision: str) -> str:
    """Build the context for Command Mode LLM prompt."""
    player = state.get_player_faction()

    lines = [
        "## 当前状态",
        f"时间：{state.year}年{state.current_season_cn} | 第{state.turn}回合",
        f"势力：{player.name if player else '未知'}",
    ]

    if player:
        pt_names = []
        for tid in player.territories:
            t = state.territories.get(tid)
            if t:
                pt_names.append(t.name)
        lines.extend(
            [
                f"兵力：{player.strength:,}",
                f"经济：{player.economy}/100",
                f"民心：{player.morale}/100",
                f"资金：{player.treasury:,}",
                f"粮草：{player.food:,}",
                f"领地：{', '.join(pt_names) if pt_names else '暂无'}",
            ]
        )

    lines.append("")
    lines.append("## 其他势力")
    for fid, fs in state.factions.items():
        if not fs.is_active or fid == state.player_faction_id:
            continue
        t_names = []
        for tid in fs.territories:
            t = state.territories.get(tid)
            if t:
                t_names.append(t.name)
        t_str = ", ".join(t_names) if t_names else "无"
        lines.append(
            f"- {fs.name}（君主: {fs.ruler_id}）：兵力{fs.strength:,}，"
            f"经济{fs.economy}，民心{fs.morale}。控制城池：{t_str}"
        )

    # Resolve deceased characters
    dead_names = collect_dead_characters(state)
    if dead_names:
        lines.append("")
        lines.append("## 已亡故/不活跃人物（不可在此回合复活或出现活跃事迹）")
        lines.append(f"- {', '.join(dead_names)}")

    lines.append("")
    lines.append("## 主公决策")
    lines.append(f"「{player_decision}」")
    lines.append("")
    lines.append("请根据以上决策模拟本季度的推演。输出完整的JSON结果。")

    return "\n".join(lines)


# ─── GameMaster ─────────────────────────────────────────────


class GameMaster:
    """
    LLM-driven game master for 三國志略.

    The LLM is the game engine — all advisor speeches, suggestions,
    consequences, narratives, and NPC actions are generated by the LLM.

    Two-phase architecture:
      1. Plan Mode  — council meeting (advisors + suggestions)
      2. Command Mode — execution results (bureaucracy + consequences + seeds)
    """

    def __init__(self, llm: LLMAdapter, lang: str = "zh"):
        self.llm = llm
        self._lang = lang

    def _gm_prompt(self, cn_prompt: str, en_prompt: str) -> str:
        """Return the appropriate gamemaster prompt for the current language."""
        return en_prompt if self._lang == "en" else cn_prompt

    # ─── Intro Mode ─────────────────────────────────────────

    def generate_intro(self, state: WorldState) -> dict:
        """Generate the introductory scene for a new game."""
        player = state.get_player_faction()
        if not player:
            return self._fallback_intro()

        intro_sys = self._gm_prompt(GAMEMASTER_INTRO_SYSTEM, GAMEMASTER_INTRO_SYSTEM_EN)

        intro_context = (
            f"## 游戏开局\n\n"
            f"剧本：{state.scenario}\n"
            f"时间：{state.year}年春季\n\n"
            f"玩家势力：{player.name}\n"
            f"- 兵力：{player.strength:,}\n"
            f"- 经济：{player.economy}/100\n"
            f"- 民心：{player.morale}/100\n"
            f"- 资金：{player.treasury:,}\n"
            f"- 粮草：{player.food:,}\n"
            f"- 首都：{player.capital}\n"
            f"- 领地：{', '.join(player.territories)}\n\n"
            f"历史背景：{HISTORICAL_TIMELINE_207[0]}\n\n"
            f"请以说书人/军师的口吻，生成三国志略的开局叙事（以Markdown格式书写，"
            f"建议分为‘天下大势’与‘主公处境’两部分，有历史感，300-600字）。\n"
            f"生成3-5条其他NPC势力的开局动向（放在npc_reactions列表中），"
            f"以及4个极具历史厚重感、切合局势的开局选择（放在choices列表中，"
            f"如：【发布檄文】响应讨董，【深挖粮饷】稳固后方 等）。"
        )

        messages = [
            {"role": "system", "content": intro_sys},
            {"role": "user", "content": intro_context},
        ]

        try:
            metadata = {
                "turn": state.turn,
                "year": state.year,
                "season": (
                    state.current_season.name if hasattr(state.current_season, "name") else str(state.current_season)
                ),
                "category": "gamemaster",
                "reason": "intro",
                "faction_id": state.player_faction_id,
            }
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=16384,
                metadata=metadata,
            )

            return {
                "narrative": result.get("narrative", ""),
                "npc_actions": result.get("npc_reactions", []),
                "new_choices": result.get(
                    "choices",
                    [
                        "【发布檄文】联络天下英雄",
                        "【屯田养兵】积蓄钱粮实力",
                        "【合纵连横】派使者联络袁绍",
                        "【招贤纳士】招募在野文武",
                    ],
                ),
                "state_changes": {
                    "strength": 0,
                    "economy": 0,
                    "morale": 0,
                    "treasury": 0,
                    "food": 0,
                    "npc_changes": {},
                },
                "events_occurred": [],
            }
        except Exception:
            return self._fallback_intro()

    def _fallback_intro(self) -> dict:
        """Fallback intro if LLM fails."""
        return {
            "narrative": (
                "### 天下大势\n"
                "建安十二年（207 AD），汉室倾颓，群雄逐鹿。\n"
                "曹操已平定北方四州，挟天子以令诸侯，不日即将南征。\n"
                "刘备屯兵新野，得诸葛亮辅佐，如鱼得水。\n"
                "孙权继承父兄基业，坐断江东，国险民附。\n\n"
                "### 主公处境\n"
                "乱世已至，天下三分之势初现。主公当审时度势，谋定而后动。"
            ),
            "npc_actions": [
                "曹操在许昌整军备战，虎视荆襄，大军即将南下",
                "刘备屯兵新野，三顾茅庐请出诸葛亮，正谋划隆中对策",
                "孙权坐镇建业，周瑜训练水师，巩固江东六郡",
            ],
            "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0, "npc_changes": {}},
            "events_occurred": [],
            "new_choices": [
                "【招贤纳士】广募天下英才",
                "【屯田养兵】积蓄钱粮实力",
                "【合纵连横】派使者联络盟友",
                "【厉兵秣马】整军备战以待时机",
            ],
        }

    # ─── Plan Mode ──────────────────────────────────────────

    def generate_plan_mode(
        self,
        state: WorldState,
        pressure_hint: str = "",
    ) -> dict:
        """Generate Plan Mode content: advisor speeches + 4 suggestions.

        The LLM receives the full world state and generates a council meeting
        with faction-appropriate advisors giving real strategic advice.
        """
        mode = state.historical_mode
        if mode == HistoricalMode.HISTORICAL:
            framing = HISTORICAL_PLAN_FRAMING
        elif mode == HistoricalMode.DIVERGENT:
            framing = DIVERGENT_PLAN_FRAMING
        else:
            framing = FREEFORM_PLAN_FRAMING

        system_content = self._gm_prompt(GAMEMASTER_PLAN_SYSTEM, GAMEMASTER_PLAN_SYSTEM_EN) + "\n" + framing
        if pressure_hint:
            system_content += f"\n\n## 叙事方向牵引指示（请在剧情推演中自然引导，但不要强行套用）：\n{pressure_hint}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": _build_plan_context(state)},
        ]

        try:
            metadata = {
                "turn": state.turn,
                "year": state.year,
                "season": (
                    state.current_season.name if hasattr(state.current_season, "name") else str(state.current_season)
                ),
                "category": "gamemaster",
                "reason": "plan",
                "faction_id": state.player_faction_id,
            }
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=16384,
                metadata=metadata,
            )
            return {
                "court_dialogue": result.get("court_dialogue", ""),
                "suggestions": result.get("suggestions", []),
                "season_summary": result.get("season_summary", ""),
            }
        except Exception:
            return self._fallback_plan(state)

    def _fallback_plan(self, state: WorldState) -> dict:
        """Minimal fallback when LLM is unavailable."""
        player = state.get_player_faction()
        ruler_name = player.name if player else "主公"
        court_msg = (
            f"【{state.year}年{state.current_season_cn} · 内政会议】\n\n"
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
            "season_summary": f"{state.year}年{state.current_season_cn}，天下纷争未休。",
        }

    # ─── Command Mode ───────────────────────────────────────

    def generate_command_mode(
        self,
        state: WorldState,
        player_decision: str,
        pressure_hint: str = "",
    ) -> dict:
        """Generate Command Mode content: execution results.

        The LLM processes the player's decision and generates:
        - Bureaucracy execution narrative
        - Short-term consequences (state changes)
        - Long-term seeds
        - NPC reactions
        - Updated world state
        """
        mode = state.historical_mode
        if mode == HistoricalMode.HISTORICAL:
            framing = HISTORICAL_COMMAND_FRAMING
        elif mode == HistoricalMode.DIVERGENT:
            framing = DIVERGENT_COMMAND_FRAMING
        else:
            framing = FREEFORM_COMMAND_FRAMING

        system_content = self._gm_prompt(GAMEMASTER_COMMAND_SYSTEM, GAMEMASTER_COMMAND_SYSTEM_EN) + "\n" + framing
        if pressure_hint:
            system_content += f"\n\n## 叙事方向牵引指示（请在剧情推演中自然引导，但不要强行套用）：\n{pressure_hint}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": _build_command_context(state, player_decision)},
        ]

        try:
            metadata = {
                "turn": state.turn,
                "year": state.year,
                "season": (
                    state.current_season.name if hasattr(state.current_season, "name") else str(state.current_season)
                ),
                "category": "gamemaster",
                "reason": "command",
                "faction_id": state.player_faction_id,
            }
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=16384,
                metadata=metadata,
            )

            # Apply state changes from LLM
            updated_state = self._apply_command_updates(state, result)

            # Record the event
            event = EventEntry(
                year=state.year,
                season=state.current_season,
                turn=state.turn,
                description=result.get("aftermath", "")[:200],
                type="decision",
                faction_id=state.player_faction_id,
                player_involved=True,
                player_decision=player_decision[:100],
            )
            save_world(updated_state)
            add_event_to_history(event)

            # Divergence acknowledgment
            aftermath = result.get("aftermath", "")
            if (
                state.historical_mode == HistoricalMode.HISTORICAL
                and updated_state.historical_mode != HistoricalMode.HISTORICAL
            ):
                divergence_msg = "【史官提笔长叹：历史的轨迹已被彻底改变，此后的纪事，将被记入《建安异录》之中。】\n\n"
                aftermath = divergence_msg + aftermath

            return {
                "bureaucracy": result.get("bureaucracy", []),
                "short_term": result.get("short_term", {"changes": {}}),
                "seeds": result.get("seeds", []),
                "npc_reactions": result.get("npc_reactions", []),
                "aftermath": aftermath,
                "state_changes": result.get("short_term", {}).get("changes", {}),
                "world_state": updated_state,
            }

        except Exception:
            import traceback

            traceback.print_exc()
            state.advance_turn()
            return {
                "bureaucracy": [],
                "short_term": {"changes": {}},
                "seeds": [],
                "npc_reactions": ["各方势力继续行动，天下纷争不休。"],
                "aftermath": (
                    f"政令「{player_decision[:200]}"
                    f"{'...' if len(player_decision) > 200 else ''}」已下达，各部正在执行中。"
                ),
                "state_changes": {},
                "world_state": state,
            }

    def _apply_command_updates(self, state: WorldState, llm_result: dict) -> WorldState:
        """Apply LLM-generated state changes to the world state."""
        new_state = copy.deepcopy(state)

        # Apply player state changes
        changes = llm_result.get("short_term", {}).get("changes", {})
        player = new_state.get_player_faction()
        if player:
            for key in ("strength", "economy", "morale", "treasury", "food"):
                delta = changes.get(key, 0)
                if delta:
                    current = getattr(player, key, 0)
                    new_val = current + delta
                    new_val = max(0, min(100, new_val)) if key in ("economy", "morale") else max(0, new_val)
                    setattr(player, key, new_val)

        # Apply updated NPC factions
        updated = llm_result.get("updated_factions", {})
        for fid, fs_data in updated.items():
            if fid in new_state.factions and fid != new_state.player_faction_id:
                fs = new_state.factions[fid]
                for key, val in fs_data.items():
                    if hasattr(fs, key) and isinstance(val, (int, float)):
                        val = max(0, min(100, int(val))) if key in ("economy", "morale") else max(0, int(val))
                        setattr(fs, key, val)

        # Apply updated player deviation
        if "player_deviation" in llm_result:
            with contextlib.suppress(ValueError, TypeError):
                new_state.player_deviation = float(llm_result["player_deviation"])

        new_state.advance_turn()
        return new_state
