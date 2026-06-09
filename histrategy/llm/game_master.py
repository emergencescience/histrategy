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
    HistoricalMode,
    add_event_to_history,
    get_historical_context,
    get_recent_history,
    save_world,
    HISTORICAL_TIMELINE_207,
)
from .adapter import LLMAdapter

# ─── System Prompts ─────────────────────────────────────────

GAMEMASTER_INTRO_SYSTEM = """你是《三國志略》的AI游戏主持人（Game Master）。现在是「游戏序幕」阶段。

## 你的角色
你负责根据玩家所选择的君主势力，生成一段极具三国历史感、文白相间的精彩开篇叙事。你要向玩家（主公）汇报天下大势与他当前所处的局面，并给出第一回合的初始战略抉择。

## 输出格式
严格输出JSON，格式如下：
{
  "narrative": "...",
  "npc_reactions": ["...", "...", "..."],
  "choices": ["...", "...", "...", "..."]
}
"""

GAMEMASTER_PLAN_SYSTEM = """你是《三國志略》的AI游戏主持人（Game Master）。现在是「内政会议」阶段。

## 你的角色
你是这个三国世界的主宰。你掌控着天下大势的运转，了解每一位谋臣武将的性格，洞悉各方势力的野心与恐惧。你要根据当前的世界状态，为玩家生成一场真实、生动的内政会议。

## 当前状态
你会收到一份完整的天下形势报告，包含：
- 玩家势力的各项数据（兵力、经济、民心、资金、粮草、领地）
- 其他NPC势力的状态
- 最近的历史事件 and 玩家的决策轨迹
- 当前所处的历史时期

## 你需要生成的

### court_dialogue（内政会议记叙与辩论）
以文白相间的史书/演义戏剧体，写一段群臣在公堂上针对当前时局和数据的辩论对话。
要求：
- 发言的谋臣/武将要符合其历史性格与当前情绪（如：简雍诙谐、关羽高傲沉稳、郭嘉好出奇谋、张飞性急、荀彧稳重）。
- 他们之间必须有观点的交锋、反驳、补充或辩论，形成一个有张力、有冲突的对话流（Dialogue Flow）。例如，主战派与主和派的争论，或者经济屯田与出兵讨董的权衡。
- 发言中必须自然地提及当前势力的真实数据（如：“主公现有平原兵精马壮，足有精兵七千，然粮草仅存千石，若长途跋涉……”）。
- 绝不能是几段各自独立的陈述，必须是连贯的对话和公堂场景描写。
- 长度在300-600字为佳。

### suggestions（战略建议）
生成3-4个具体的战略方向选项。
要求：
- 绝不使用模板化的选项（如“发展内政”、“扩军备战”这种干瘪字眼）。
- 必须紧扣上面群臣辩论的争议焦点，将谋士们的提议具象化（例如：“【军师联军策】遣孙乾游说袁绍，合兵共进”、“【内政屯田策】于平原兴修水利，奖励春耕，充实粮饷”）。
- 每个选项应由谋士命名，富有历史厚重感。

### season_summary（季度摘要）
30-50字，概括当前的天下大势，作为会议引子。

## 输出格式
严格输出JSON，格式如下：
{
  "season_summary": "...",
  "court_dialogue": "...",
  "suggestions": ["...", "...", "..."]
}"""


GAMEMASTER_COMMAND_SYSTEM = """你是《三國志略》的AI游戏主持人（Game Master）。现在是「政令执行」阶段。

## 你的角色
你是这个三国世界的主宰。玩家已经做出了战略决策，你现在要模拟这个决策在游戏世界中的执行过程和后果。你要像一个真正的三国世界一样，根据玩家的具体指令，以连贯、大气的编年体史书风格，推演出合理的、有因果关系的后果。

## 决策推演规则

### 彻底消除模板感
- 严禁原封不动地复制玩家的原话（如：“你决定采纳『扩军备战，操练士卒』的战略”）。相反，应用生动的演义叙事予以改写（如：“主公将令既下，关羽、张飞二人即领命归营，于平原校场大张旗鼓、征募乡勇……”）。
- 数据变化应自然融入叙事中，如 “（兵力 +2,664，资金 -550）”。
- 后果必须与决策内容直接相关，数值变化要有理有据。
- 所有数值变化应在合理范围内（单次变化不超过当前值的20%为佳）。

### NPC势力的反应
- NPC势力会根据玩家的行动做出反应，且NPC势力也在自驱运转。
- 曹操多疑、袁绍好谋无断、董卓残暴——必须符合人物性格。

## 你需要生成的

### aftermath（局势推演史书纪实）
一段300-500字的文字，采用文白相间的《三国志》史书或《三国演义》编年体风格，完整记叙这一季度在该政令下势力的遭遇与天下局势的变化。
要求：
- 语言庄重、有历史厚重感。
- 将具体政务的执行细节和数据变化（如兵力增加、粮饷损耗等）以自然的形式（可使用括号或夹注，如：“是岁夏，刘备募平原百姓得精兵两千（兵力 +2,000，资金 -400）”）嵌入在叙事文字中。

### bureaucracy（政令执行 ledger）
3-5个部门的执行情况（用于后台日志与结构化记录），每个包含：
- department: department name
- official: official name
- action: execution description (50-100 characters)

### short_term（短期影响）
changes字段包含以下数值变化（用于后台世界引擎属性结算，必须与叙事中的数字100%对应）：
- strength: 兵力变化
- economy: 经济变化(0-100)
- morale: 民心变化(0-100)
- treasury: 资金变化
- food: 粮草变化

### seeds（潜在影响）
1-3个长期发展的种子（可为空，用于世界引擎触发器逻辑），每个包含：
- title: 简短标题
- description: 描述
- trigger_after: 几回合后触发(1-4)
- type: 类型（diplomatic/economic_bonus/military/morale_bonus/intelligence）

### npc_reactions（天下动向）
2-4个NPC势力的行动/反应，每句20-60字。要具体到势力名字。

### updated_factions（更新后的势力状态）
所有活跃势力的最新状态。格式：{"faction_id": {"strength": N, ...}}

### player_deviation（偏离度更新）
结合本次推演评估历史轨迹的变动。若玩家行为显著违背历史，应提升偏离度（如从 0 提升到 0.2 等）。

## 输出格式
严格输出JSON，格式如下：
{
  "bureaucracy": [{"department": "...", "official": "...", "action": "..."}],
  "short_term": {"changes": {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0}},
  "seeds": [{"title": "...", "description": "...", "trigger_after": N, "type": "..."}],
  "npc_reactions": ["...", "..."],
  "updated_factions": {"faction_id": {"strength": N, ...}},
  "aftermath": "...",
  "player_deviation": 0.0
}"""


# ─── Mode-Specific Prompts ───────────────────────────────────

HISTORICAL_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「正史模式」（偏离度低）：天下局势与历史高度吻合，谋臣们的提议应当尽量符合正史走向或在历史框架内做出合理规划。
- 引导玩家顺应历史的主线事件。
"""

DIVERGENT_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「演义/走向偏离模式」（偏离度中）：历史轨迹已被玩家改变。谋臣们需要意识到历史已经分叉，建言要基于当前的“偏离状态”进行合情合理的推演，而不是生搬硬套正史。
"""

FREEFORM_PLAN_FRAMING = """
## 历史模式运作指南
- 当前为「幻想沙盒模式」（偏离度高）：历史进程已完全脱轨。请抛开任何历史必然性的包袱，纯粹根据各势力实力和人物性格进行合理的利益冲突和争霸建言。
"""

HISTORICAL_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「正史模式」：推演结果需要维持强烈的历史重力。玩家的微调可以影响结果，但大势（如董卓迁都、群雄割据）会产生强烈的牵引力。
"""

DIVERGENT_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「演义/走向偏离模式」：历史已被改变。请在推演中体现蝴蝶效应，展示事件如何以全新的因果逻辑发展。史官会将此记为《建安异录》。
"""

FREEFORM_COMMAND_FRAMING = """
## 历史模式执行指南
- 当前为「幻想沙盒模式」：历史已完全脱轨，属于全自由度沙盒。请根据当前的军事实力、民心等数据进行纯粹的博弈推演，NPC的行为应当完全自驱。
"""


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

    # ─── Intro Mode ─────────────────────────────────────────

    def generate_intro(self, state: WorldState) -> dict:
        """Generate the introductory scene for a new game."""
        player = state.get_player_faction()
        if not player:
            return self._fallback_intro()

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
            f"请以说书人/军师的口吻，生成三国志略的开局叙事（以Markdown格式书写，建议分为‘天下大势’与‘主公处境’两部分，有历史感，300-600字）。\n"
            f"生成3-5条其他NPC势力的开局动向（放在npc_reactions列表中），以及4个极具历史厚重感、切合局势的开局选择（放在choices列表中，如：【发布檄文】响应讨董，【深挖粮饷】稳固后方 等）。"
        )

        messages = [
            {"role": "system", "content": GAMEMASTER_INTRO_SYSTEM},
            {"role": "user", "content": intro_context},
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
                "npc_actions": result.get("npc_reactions", []),
                "new_choices": result.get("choices", [
                    "【发布檄文】联络天下英雄",
                    "【屯田养兵】积蓄钱粮实力",
                    "【合纵连横】派使者联络袁绍",
                    "【招贤纳士】招募在野文武",
                ]),
                "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                                  "treasury": 0, "food": 0, "npc_changes": {}},
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
            "state_changes": {"strength": 0, "economy": 0, "morale": 0,
                              "treasury": 0, "food": 0, "npc_changes": {}},
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

        system_content = GAMEMASTER_PLAN_SYSTEM + "\n" + framing
        if pressure_hint:
            system_content += f"\n\n## 叙事方向牵引指示（请在剧情推演中自然引导，但不要强行套用）：\n{pressure_hint}"

        messages = [
            {"role": "system", "content": system_content},
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

        system_content = GAMEMASTER_COMMAND_SYSTEM + "\n" + framing
        if pressure_hint:
            system_content += f"\n\n## 叙事方向牵引指示（请在剧情推演中自然引导，但不要强行套用）：\n{pressure_hint}"

        messages = [
            {"role": "system", "content": system_content},
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

            # Divergence acknowledgment
            aftermath = result.get("aftermath", "")
            if state.historical_mode == HistoricalMode.HISTORICAL and updated_state.historical_mode != HistoricalMode.HISTORICAL:
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

        except Exception as e:
            import traceback
            traceback.print_exc()
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

        # Apply updated player deviation
        if "player_deviation" in llm_result:
            try:
                new_state.player_deviation = float(llm_result["player_deviation"])
            except (ValueError, TypeError):
                pass

        new_state.advance_turn()
        return new_state

