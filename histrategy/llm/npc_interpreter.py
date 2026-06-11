"""NPCInterpreter — Tier 1 LLM NPC batch interpreter.

One LLM call per turn covers ALL court NPCs simultaneously.
Input: world state + player action + current NPC mood states
Output: mood shifts + visible actions for each NPC

Design: NPCs are NOT full agents. They have bounded mood states and
the LLM interprets those states into behavior each turn. This gives
80% of the drama of full agents at ~5% of the cost.

Cost: ~800 input + ~400 output tokens/turn at temperature 0.6
     ≈ $0.001/turn (DeepSeek-V3)
"""

from __future__ import annotations

import logging

from ..state.npc_state import NPCState
from ..state.world_state import WorldState

logger = logging.getLogger(__name__)


NPC_INTERPRETER_SYSTEM = """你是《三國志略》中负责管理NPC内心世界的系统。

## 你的任务
根据以下信息，更新场景中所有关键NPC的心理状态，并生成他们的可见行为。

## 规则
1. **情绪变化最多1级/回合**: 心情只能从当前状态改变一级（好转或恶化）
2. **有因有果**: 每一个心情变化必须有明确原因（与玩家的决策相关）
3. **性格一致**: NPC的行为必须符合其历史性格
4. **预警机制**: 当NPC心情恶化到"不满"时，必须在visible_action中给玩家一个明确的警示
5. **慢慢升级**: 背叛/出走需要至少3回合在恶劣状态才会发生

## 情绪等级（从好到坏）
- loyal: 格外忠心，主动帮助主公
- content: 正常状态
- frustrated: 开始不满，可能有轻微抱怨（需要给玩家警告）
- angry: 明显不满，可能不服从命令
- scheming: 在朝中结党，积极谋划对抗主公
- plotting: 即将叛变或出走（1-2回合内会有行动）

## 输出格式（严格JSON）
{
  "npc_updates": [
    {
      "character_id": "...",
      "mood_shift": -1 | 0 | 1,  // -1=好转, 0=不变, 1=恶化
      "grievance": "...",  // 一句话说明原因（中文）。不变时留空。
      "visible_action": "...",  // 本回合的可见行为（20-60字，中文）。可为空字符串。
      "loyalty_delta": -5 | 0 | 5  // 忠诚度变化
    }
  ]
}
"""


class NPCInterpreter:
    """Tier 1 LLM NPC batch interpreter.

    Processes all court NPCs in one LLM call per turn.
    Returns mood shifts and visible actions without running full agent loops.
    """

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    def interpret(
        self,
        state: WorldState,
        player_action: str,
        npc_states: dict[str, NPCState],
        relevant_character_ids: list[str] | None = None,
    ) -> dict[str, dict]:
        """Run NPC interpretation and return update dicts keyed by character_id.

        Returns:
            Dict mapping character_id → {
                "mood_shift": int,
                "grievance": str,
                "visible_action": str,
                "loyalty_delta": int,
            }
        """
        if not npc_states:
            return {}

        context = self._build_context(state, player_action, npc_states, relevant_character_ids)
        messages = [
            {"role": "system", "content": NPC_INTERPRETER_SYSTEM},
            {"role": "user", "content": context},
        ]

        try:
            metadata = {
                "turn": state.turn,
                "year": state.year,
                "season": state.current_season,
                "category": "npc_interpreter",
                "reason": "interpret",
            }
            result = self._adapter.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.60,
                max_tokens=1200,
                metadata=metadata,
            )
            updates = {}
            for item in result.get("npc_updates", []):
                cid = item.get("character_id", "")
                if cid:
                    updates[cid] = {
                        "mood_shift": int(item.get("mood_shift", 0)),
                        "grievance": item.get("grievance", ""),
                        "visible_action": item.get("visible_action", ""),
                        "loyalty_delta": int(item.get("loyalty_delta", 0)),
                    }
            return updates
        except Exception as exc:
            logger.debug("NPCInterpreter LLM call failed: %s", exc)
            return {}

    def apply_updates(
        self,
        npc_states: dict[str, NPCState],
        updates: dict[str, dict],
    ) -> list[str]:
        """Apply mood updates to npc_states in-place.

        Returns:
            List of visible action strings to surface in the UI.
        """
        visible_actions = []
        for cid, upd in updates.items():
            if cid not in npc_states:
                continue
            npc = npc_states[cid]
            shift = upd.get("mood_shift", 0)
            grievance = upd.get("grievance", "")
            loyalty_delta = upd.get("loyalty_delta", 0)

            if shift > 0:
                npc.worsen(grievance)
            elif shift < 0:
                npc.improve(grievance)
            else:
                npc.turns_at_current_mood += 1

            npc.loyalty = max(0, min(100, npc.loyalty + loyalty_delta))

            action = upd.get("visible_action", "")
            if action:
                visible_actions.append(action)

        return visible_actions

    def get_warning_hints(self, npc_states: dict[str, NPCState]) -> list[str]:
        """Return warning messages for NPCs at danger level.

        These are surfaced in Plan Mode so players can take corrective action.
        """
        warnings = []
        for cid, npc in npc_states.items():
            if npc.mood.is_warning:
                emoji = "⚠️" if npc.mood.is_danger else "💬"
                warnings.append(
                    f"{emoji} {cid} 当前心情：{npc.mood.value}" + (f"（{npc.grievance}）" if npc.grievance else "")
                )
        return warnings

    def _build_context(
        self,
        state: WorldState,
        player_action: str,
        npc_states: dict[str, NPCState],
        relevant_ids: list[str] | None,
    ) -> str:
        player = state.get_player_faction()
        lines = [
            f"## 当前回合: {state.year}年{state.current_season_cn} | 第{state.turn}回合",
            f"## 玩家势力: {player.name if player else '未知'}",
            f"## 本回合玩家决策: 「{player_action}」",
            "",
            "## 当前NPC状态",
        ]

        ids_to_process = relevant_ids or list(npc_states.keys())
        for cid in ids_to_process:
            if cid not in npc_states:
                continue
            npc = npc_states[cid]
            lines.append(
                f"- {cid}: 忠诚={npc.loyalty}, 心情={npc.mood.value}"
                + (f", 不满原因={npc.grievance}" if npc.grievance else "")
                + f", 持续回合={npc.turns_at_current_mood}"
            )

        lines.append("")
        lines.append("请根据玩家的决策，判断每个NPC的心情变化，并生成本回合可见行为。")
        return "\n".join(lines)
