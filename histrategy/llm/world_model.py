"""
三國志略 — LLM-driven World Model

The LLM acts as the "game master" (DM) — given the full world state
and player's action, it generates the next state, narrative, and choices.

This replaces template-driven simulation with true emergent gameplay:
- Player input directly influences outcomes (20%+ player agency)
- Historical events occur ~50% of the time as background events
- World state evolves organically turn by turn
- Every decision creates visible, trackable consequences

Key Insight: The LLM outputs the COMPLETE updated world state each turn.
This means consequences are real, emergent, and persistent.
"""

from __future__ import annotations

from ..state.world_state import (
    HISTORICAL_TIMELINE_190,
    EventEntry,
    WorldState,
    add_event_to_history,
    get_historical_context,
    get_recent_history,
    save_world,
)
from .adapter import LLMAdapter

# ─── System Prompt for the World Model ─────────────────────

WORLD_MODEL_SYSTEM_PROMPT = """你是《三國志略》的AI游戏主持人（Game Master / 说书人）。

你的核心任务是：
1. 接收玩家的战略决策 + 当前世界状态
2. 推演这个决策的后果（经济、军事、外交、内政）
3. 让其他NPC势力也按他们的性格行动
4. 输出更新后的世界状态 + 叙事 + 下一轮选项

## 历史与玩家创造力的平衡
- 约50%的重大历史事件可以按照真实历史发生（作为背景事件）
- 约20-30%的事件应该因玩家决策而改变
- 玩家的每一个决策都必须有可见、可追踪的后果

## 世界状态更新规则
- 每一回合必须输出完整的更新后的世界状态
- 所有数值变化必须有因有果（在narrative中体现）
- 玩家势力的变化幅度取决于决策的激进程度
- NPC势力会响应玩家行动，也会主动行动

## 叙事风格
- 使用文白相间的文言风格，略有古典小说质感
- advisor_feedback 要像军师即时进言：先说明你如何理解玩家意图，再指出风险和可执行落点
- 每个后果都要具体（不要笼统的"民心有所提升"）
- 引用玩家的原话作为决策的起点
- 决策后果板要清晰写具体数字变化

## 输出格式
你必须严格输出JSON，包含以下字段：
- advisor_feedback: 幕府参议（先理解玩家战略，不改变状态），包含 understanding, strategic_read, risks, recommended_execution, clarifying_question
- narrative: 本季度的叙事文本（文言风格，300-800字）
- aftermath: 决策后果板（简短，引用玩家原话 + 具体后果）
- state_changes: 玩家势力变化 {strength, economy, morale, treasury, food 的变化值}
- npc_actions: 其他势力的行动列表（每个势力1句，2-4个）
- choices: 下一轮的3-4个战略选项（每个30字以内）
- updated_factions: 更新后的所有势力状态（完整覆盖旧状态）
- new_events: 发生的新事件列表
- historical_deviation: 本次决策与历史轨道的偏差程度 "historical" / "minor_deviation" / "major_deviation"
"""


def _build_faction_context(state: WorldState) -> str:
    """Build a detailed faction context for the LLM prompt."""
    player = state.get_player_faction()
    if not player:
        return ""

    lines = [
        f"## 玩家势力：{player.name}（{state.year}年{state.current_season_cn}）",
        f"- 兵力：{player.strength:,}",
        f"- 经济：{player.economy}/100",
        f"- 民心：{player.morale}/100",
        f"- 资金：{player.treasury:,}",
        f"- 粮草：{player.food:,}",
        f"- 领地：{', '.join(player.territories) if player.territories else '暂无'}",
    ]

    return "\n".join(lines)


def _build_all_factions_context(state: WorldState) -> str:
    """Build a summary of all active factions."""
    lines = ["## 天下势力"]
    for fid, fs in state.factions.items():
        if not fs.is_active:
            continue
        if fid == state.player_faction_id:
            continue
        lines.append(f"- {fs.name}（{fs.ruler_id}）：兵力{fs.strength:,}，经济{fs.economy}，民心{fs.morale}")
    return "\n".join(lines)


def _build_memory_context() -> str:
    """Build player decision history context."""
    history = get_recent_history(5)
    if not history:
        return "暂无决策历史。"

    lines = ["## 最近决策回顾"]
    for ev in history:
        decision = ev.get("player_decision", "")
        desc = ev.get("description", "")
        if decision:
            lines.append(f"- 你的决策「{decision}」→ {desc[:80]}")
    return "\n".join(lines)


# ─── World Model ───────────────────────────────────────────


class WorldModel:
    """
    LLM-driven world model for 三國志略.

    Each turn, the LLM receives:
      1. System prompt (this prompt)
      2. Historical context for the current year
      3. Current world state (structured JSON)
      4. Player's decision history (last 5)
      5. Player's current decision

    The LLM produces:
      1. Updated world state (complete)
      2. Narrative
      3. New choices
      4. NPC actions
    """

    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    def generate_turn(
        self,
        state: WorldState,
        player_decision: str,
    ) -> dict:
        """Generate the next turn using the LLM world model.

        Args:
            state: Current world state
            player_decision: Player's strategic decision (raw text)

        Returns:
            dict with narrative, aftermath, choices, and updated world state
        """
        # Build the prompt
        messages = [
            {"role": "system", "content": WORLD_MODEL_SYSTEM_PROMPT},
            self._build_context_message(state),
            self._build_decision_message(player_decision),
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=8192,
            )

            # Apply the LLM's state updates to our WorldState
            updated_state = self._apply_state_updates(state, result)

            # Record the event
            event = EventEntry(
                year=state.year,
                season=state.current_season,
                turn=state.turn,
                description=result.get("narrative", "")[:200],
                type="decision",
                faction_id=state.player_faction_id,
                is_historical=False,
                player_involved=True,
                player_decision=player_decision[:100],
            )
            save_world(updated_state)
            add_event_to_history(event)

            # Build the return dict
            return {
                "narrative": result.get("narrative", ""),
                "advisor_feedback": result.get("advisor_feedback", {}),
                "aftermath": result.get("aftermath", ""),
                "npc_actions": result.get("npc_actions", []),
                "state_changes": result.get("state_changes", {}),
                "new_choices": result.get("choices", [
                    "1. 继续当前策略",
                    "2. 休养生息",
                    "3. 派使者联络盟友",
                ]),
                "events_occurred": result.get("new_events", []),
                "historical_deviation": result.get("historical_deviation", "historical"),
                "world_state": updated_state,
            }

        except Exception:
            # Fallback: advance time and return a basic response
            state.advance_turn()
            return {
                "narrative": "（系统正在重整旗鼓。天下大势依旧运转，但军情延误了…）",
                "advisor_feedback": {
                    "understanding": f"幕府已收到主公之令：「{player_decision[:80]}」。",
                    "strategic_read": ["此令已记录为本季度战略意图，但 AI 推演暂未完成。"],
                    "risks": ["军情延误会降低本季度反馈精度。"],
                    "recommended_execution": ["可重新提交更明确的政令，或继续等待军情。"],
                    "clarifying_question": None,
                },
                "aftermath": f"⚡ 你的决策：「{player_decision[:80]}」\n  因军情延误，暂未收到回报。",
                "npc_actions": ["各方势力继续行动，天下纷争不休。"],
                "state_changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0},
                "new_choices": [
                    "1. 继续等待军情",
                    "2. 派出斥候探查各方动向",
                    "3. 重新部署战略",
                ],
                "events_occurred": [],
                "historical_deviation": "unknown",
                "world_state": state,
            }

    def generate_intro(self, state: WorldState) -> dict:
        """Generate the introductory scene for a new game."""
        player = state.get_player_faction()
        if not player:
            return self._fallback_intro()

        messages = [
            {"role": "system", "content": WORLD_MODEL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
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
                    f"历史背景：{HISTORICAL_TIMELINE_190[0]}\n\n"
                    f"请生成三國志略的开局叙事，介绍当前天下大势和玩家势力的处境。\n"
                    f"不要输出state_changes（这是第一回合，数值已经设定好）。\n"
                    f"输出narrative（500-800字文言风格）、npc_actions（3-5个）、choices（4个选项）。"
                ),
            },
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=4096,
            )

            return {
                "narrative": result.get("narrative", ""),
                "advisor_feedback": result.get("advisor_feedback", {}),
                "npc_actions": result.get("npc_actions", []),
                "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                                  "treasury": 0, "food": 0, "npc_changes": {}},
                "events_occurred": [],
                "new_choices": result.get("choices", [
                    "1. 发布檄文，联络天下英雄",
                    "2. 发展经济，积蓄力量",
                    "3. 结交盟友，共图大业",
                    "4. 加强军备，整兵待战",
                ]),
            }
        except Exception:
            return self._fallback_intro()

    def _fallback_intro(self) -> dict:
        """Fallback intro if LLM fails."""
        return {
            "narrative": (
                "初平元年（190 AD），汉室倾颓，诸侯并起。\n"
                "董卓挟持天子，暴虐无道，天下英雄莫不愤慨。\n"
                "曹操在兖州散尽家财，发矫诏号召天下诸侯共讨董卓。\n"
                "袁绍据河北四州，被推举为讨董盟主。\n"
                "这是一个英雄辈出的时代——你的每一个决策，都将改变天下的命运。"
            ),
            "npc_actions": [
                "董卓挟天子以令诸侯，作威作福",
                "曹操在兖州招兵买马，联络诸侯",
                "孙坚整军备战，准备北上讨董",
            ],
            "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                              "treasury": 0, "food": 0, "npc_changes": {}},
            "events_occurred": [],
            "new_choices": [
                "1. 发布讨董檄文，联络诸侯",
                "2. 先巩固领地，发展经济和军力",
                "3. 派使者联络袁绍，争取支持",
                "4. 坐观成败，等待时机",
            ],
        }

    def _build_context_message(self, state: WorldState) -> dict:
        """Build the context message with world state and history."""
        player_faction = _build_faction_context(state)
        all_factions = _build_all_factions_context(state)
        historical = get_historical_context(state.year)
        recent_memories = _build_memory_context()

        context = (
            f"## 当前时间\n"
            f"{state.year}年{state.current_season_cn} | 第{state.turn}回合\n\n"
            f"## 历史参考\n"
            f"真实历史中这一时期的重大事件：\n"
            f"{historical}\n"
            f"请参考但不必完全遵循——玩家的决策可以改变历史。\n\n"
            f"{player_faction}\n\n"
            f"{all_factions}\n\n"
            f"{recent_memories}\n\n"
            f"注意：你必须输出完整的 updated_factions，覆盖所有势力的最新状态。"
        )

        return {"role": "user", "content": context}

    def _build_decision_message(self, decision: str) -> dict:
        return {
            "role": "user",
            "content": (
                f"## 主公决策\n"
                f"你的决策：{decision}\n\n"
                f"请根据这个决策模拟本季度的推演。输出完整的updated_factions和narrative。"
            ),
        }

    def _apply_state_updates(
        self, state: WorldState, llm_result: dict
    ) -> WorldState:
        """Apply LLM-generated state updates to the world state."""
        # Create a deep copy to avoid mutating the original
        import copy
        new_state = copy.deepcopy(state)

        # Apply player state changes
        changes = llm_result.get("state_changes", {})
        player = new_state.get_player_faction()
        if player:
            for key, val in changes.items():
                if key == "npc_changes":
                    continue
                if hasattr(player, key):
                    current = getattr(player, key)
                    setattr(player, key, current + val)

        # Apply updated factions from LLM (full override)
        updated_factions = llm_result.get("updated_factions", {})
        if updated_factions:
            for fid, fs_data in updated_factions.items():
                if fid in new_state.factions:
                    fs = new_state.factions[fid]
                    for key, val in fs_data.items():
                        if hasattr(fs, key):
                            setattr(fs, key, val)

        # Update historical deviation
        dev = llm_result.get("historical_deviation", "historical")
        if dev == "minor_deviation":
            new_state.player_deviation += 0.05
        elif dev == "major_deviation":
            new_state.player_deviation += 0.15

        new_state.player_deviation = min(new_state.player_deviation, 1.0)

        # Advance turn
        new_state.advance_turn()

        return new_state

