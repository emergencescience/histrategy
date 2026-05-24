"""
三國志略 — LLM Game Master

The LLM IS the game engine. No templates. No hardcoded content.
Every advisor speech, suggestion, consequence, and NPC action comes from the LLM.

Two modes:
  Plan Mode    → LLM generates advisor court + 4 suggestions based on world state
  Command Mode → LLM generates execution results based on player's free-text decision
"""

from __future__ import annotations

import copy

from ..state.world_state import (
    EventEntry,
    WorldState,
    add_event_to_history,
    get_historical_context,
    get_recent_history,
    save_world,
)
from .adapter import LLMAdapter

# ─── System Prompts ─────────────────────────────────────────

GAMEMASTER_PLAN_SYSTEM = """你是《三國志略》的AI游戏主持人（Game Master）。现在是「内政会议」阶段。

## 你的角色
你是这个三国世界的主宰。你掌控着天下大势的运转，了解每一位谋臣武将的性格，洞悉各方势力的野心与恐惧。你要根据当前的世界状态，为玩家生成一场真实、生动的内政会议。

## 当前状态
你会收到一份完整的天下形势报告，包含：
- 玩家势力的各项数据（兵力、经济、民心、资金、粮草、领地）
- 其他NPC势力的状态
- 最近的历史事件和玩家的决策轨迹
- 当前所处的历史时期

## 你需要生成的

### advisor_speeches（谋臣建言）
生成4位谋臣/武将的发言。每位必须包含：
- name: 中文名字（如：荀彧、夏侯惇、郭嘉、荀攸）
- title: 职位（军师、将军、谋士、内政官 等）
- temperament: 性格标签（cautious/aggressive/scheming/pragmatic/strict/proud/friendly）
- speech: 100-200字的发言，文白相间的文言风格。必须基于当前世界状态，涉及具体的数据或形势

要求：
- 不同性格的谋臣给出不同视角的建议
- 发言要基于实际的游戏数据，不是泛泛而谈
- 要有戏剧性——谋臣之间可以有观点的冲突
- 每个谋臣的发言要体现其性格（如：夏侯惇要激进、荀彧要稳重、郭嘉要出奇谋）

### suggestions（战略建议）
生成4个具体的战略选项，每个30-60字。必须覆盖不同的战略方向：
- 至少包含军事、经济/内政、外交、计谋各一个方向
- 选项要基于当前的天下形势，不是泛泛的模板
- 每个选项应有一个简短但有吸引力的标题

### season_summary（季度摘要）
30-50字，一句话概括当前的天下大势。

## 叙事风格
- 使用文白相间的文言风格，略有古典小说质感
- 谋臣要用符合其历史形象的语气说话
- 引用当前世界状态的具体数据（如"主公现有精兵三万"）
- 要有画面感，让玩家感觉身临其境

## 输出格式
严格输出JSON，格式如下：
{
  "season_summary": "...",
  "advisor_speeches": [
    {"name": "...", "title": "...", "temperament": "...", "speech": "..."}
  ],
  "suggestions": ["1. ...", "2. ...", "3. ...", "4. ..."]
}"""


GAMEMASTER_COMMAND_SYSTEM = """你是《三國志略》的AI游戏主持人（Game Master）。现在是「政令执行」阶段。

## 你的角色
你是这个三国世界的主宰。玩家已经做出了战略决策，你现在要模拟这个决策在游戏世界中的执行过程和后果。你不是在生成模板化的回复——你要像一个真正的三国世界一样，根据玩家的具体指令，推演出合理的、有因果关系的后果。

## 决策推演规则

### 因果关系最重要
- 玩家的每一个决策都要有可见的、具体的后果
- 后果必须与决策内容直接相关，不能是泛泛的"民心有所提升"
- 数值变化要有理有据

### 平衡与合理性
- 激进的军事行动消耗大量资源但见效快
- 经济发展见效慢但持续
- 外交行动有不确定性
- 计谋可能成功也可能失败（有风险）
- 所有数值变化应在合理范围内（单次变化不超过当前值的20%为佳）

### NPC势力的反应
- NPC势力会根据玩家的行动做出反应
- 曹操多疑、袁绍好谋无断、董卓残暴——必须符合人物性格
- 天下不是静止的，NPC势力也在各自行动

## 你需要生成的

### bureaucracy（政令执行报告）
3-5个部门的执行情况，每个包含：
- department: 部门名称（军师府、将军府、户部、兵部、密探 等）
- official: 负责官员名字（中文）
- action: 具体执行了什么（50-100字）

### short_term（短期影响）
changes字段包含以下数值变化（可以为负）：
- strength: 兵力变化
- economy: 经济变化(0-100)
- morale: 民心变化(0-100)
- treasury: 资金变化
- food: 粮草变化

### seeds（潜在影响）
1-3个长期发展的种子，每个包含：
- title: 简短标题（5-10字）
- description: 描述（20-50字）
- trigger_after: 几回合后触发(1-4)
- type: 类型（diplomatic/economic_bonus/military/morale_bonus/intelligence）

### npc_reactions（天下动向）
2-4个NPC势力的行动/反应，每句20-60字。要具体到势力名字。

### updated_factions（更新后的势力状态）
所有活跃势力的最新状态。格式：{"faction_id": {"strength": N, "economy": N, ...}}

### aftermath（决策后果板）
1-3句话，简短有力地总结：
- 第一句：引用玩家决策的核心意图
- 后续：具体后果和数据变化

## 叙事风格
- 文白相间的文言风格
- 具体、有画面感
- 引用玩家原话作为起点
- 后果板要清晰写具体数字变化

## 输出格式
严格输出JSON，格式如下：
{
  "bureaucracy": [{"department": "...", "official": "...", "action": "..."}],
  "short_term": {"changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0}},
  "seeds": [{"title": "...", "description": "...", "trigger_after": N, "type": "..."}],
  "npc_reactions": ["...", "..."],
  "updated_factions": {"faction_id": {"strength": N, ...}},
  "aftermath": "..."
}"""


# ─── Context builders ───────────────────────────────────────

def _build_plan_context(state: WorldState) -> str:
    """Build the world state context for Plan Mode LLM prompt."""
    player = state.get_player_faction()
    if not player:
        return ""

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
        f"- 领地：{', '.join(player.territories) if player.territories else '暂无'}",
        "",
        "## 天下势力",
    ]

    for fid, fs in state.factions.items():
        if not fs.is_active or fid == state.player_faction_id:
            continue
        lines.append(f"- {fs.name}（{fs.ruler_id}）：兵力{fs.strength:,}，经济{fs.economy}，民心{fs.morale}")

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
        lines.extend([
            f"兵力：{player.strength:,}",
            f"经济：{player.economy}/100",
            f"民心：{player.morale}/100",
            f"资金：{player.treasury:,}",
            f"粮草：{player.food:,}",
            f"领地：{', '.join(player.territories) if player.territories else '暂无'}",
        ])

    lines.append("")
    lines.append("## 其他势力")
    for fid, fs in state.factions.items():
        if not fs.is_active or fid == state.player_faction_id:
            continue
        lines.append(f"- {fs.name}：兵力{fs.strength:,}，经济{fs.economy}，民心{fs.morale}")

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

    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    # ─── Plan Mode ──────────────────────────────────────────

    def generate_plan_mode(self, state: WorldState) -> dict:
        """Generate Plan Mode content: advisor speeches + 4 suggestions.

        The LLM receives the full world state and generates a council meeting
        with faction-appropriate advisors giving real strategic advice.
        """
        messages = [
            {"role": "system", "content": GAMEMASTER_PLAN_SYSTEM},
            {"role": "user", "content": _build_plan_context(state)},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.85,
                max_tokens=4096,
            )
            return {
                "advisors": result.get("advisor_speeches", []),
                "suggestions": result.get("suggestions", []),
                "season_summary": result.get("season_summary", ""),
            }
        except Exception:
            return self._fallback_plan(state)

    def _fallback_plan(self, state: WorldState) -> dict:
        """Minimal fallback when LLM is unavailable."""
        return {
            "advisors": [],
            "suggestions": [
                "1. 休养生息，发展经济",
                "2. 练兵备战，充实军力",
                "3. 派遣使者，结交盟友",
                "4. 搜集情报，待机而动",
            ],
            "season_summary": f"{state.year}年{state.current_season_cn}，天下纷争未休。",
        }

    # ─── Command Mode ───────────────────────────────────────

    def generate_command_mode(
        self,
        state: WorldState,
        player_decision: str,
    ) -> dict:
        """Generate Command Mode content: execution results.

        The LLM processes the player's decision and generates:
        - Bureaucracy execution narrative
        - Short-term consequences (state changes)
        - Long-term seeds
        - NPC reactions
        - Updated world state
        """
        messages = [
            {"role": "system", "content": GAMEMASTER_COMMAND_SYSTEM},
            {"role": "user", "content": _build_command_context(state, player_decision)},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=8192,
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

            return {
                "bureaucracy": result.get("bureaucracy", []),
                "short_term": result.get("short_term", {"changes": {}}),
                "seeds": result.get("seeds", []),
                "npc_reactions": result.get("npc_reactions", []),
                "aftermath": result.get("aftermath", ""),
                "state_changes": result.get("short_term", {}).get("changes", {}),
                "world_state": updated_state,
            }
        except Exception:
            state.advance_turn()
            return {
                "bureaucracy": [],
                "short_term": {"changes": {}},
                "seeds": [],
                "npc_reactions": ["各方势力继续行动，天下纷争不休。"],
                "aftermath": f"政令「{player_decision[:60]}」已下达，各部正在执行中。",
                "state_changes": {},
                "world_state": state,
            }

    def _apply_command_updates(
        self, state: WorldState, llm_result: dict
    ) -> WorldState:
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

        new_state.advance_turn()
        return new_state
