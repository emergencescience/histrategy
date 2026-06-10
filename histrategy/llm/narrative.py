"""
Narrative Engine — read-only LLM narrative generation for 三國志略 v2.

Consumes physics engine output (TurnResult) and produces 文白相间
(classical/vernacular hybrid) historical chronicle text. Never modifies game state.

Integrates with histrategy-engine's HistoricalRAG for time-windowed event context.
Offline fallback returns deterministic text when no LLM key is available.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import TurnResult, WorldState

    from .adapter import LLMAdapter

# ─── Knowledge path resolution ──────────────────────────────────


def _resolve_knowledge_path() -> str:
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "histrategy-knowledge"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "histrategy-knowledge"),
    ]
    for p in candidates:
        if os.path.isdir(os.path.join(p, "timeline")):
            return os.path.abspath(p)
    # Fallback for installed package
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "histrategy-knowledge"))


# ─── Narrative generation prompt (read-only, no state mutation) ──

NARRATIVE_SYSTEM = """你是《三國志略》的史官。你负责将一回合的物理引擎运行结果撰写成史书纪事。

## 核心规则

1. **你绝不修改任何数据** — 你只读取并描述 TurnResult 中的事实
2. **文白相间** — 采用《三国志》裴松之注或《资治通鉴》的史书风格，以文言叙事为主，穿插白话解释
3. **数据自然嵌入** — 将关键数值变化以括号夹注形式自然融入叙事，如"（募兵三千，耗金千五百）"
4. **长度 200-400 字** — 精炼如史，不拖沓
5. **忠实于物理引擎输出** — 不虚构未发生的事件，不编造不存在的人物
6. **尊重当前世界物理状态** — 严格遵循输入中给出的势力城池分布及亡故人物列表。不可描写已被列为亡故/不活跃的人物（例如董卓、刘表已死，切勿描写其活动）；不可描写错误的领土归属关系（例如刘备已失新野，切勿描写刘备在新野驻守或活动）。

## TurnResult 结构说明

- **year / season / turn_number**: 当前时间
- **climate_events**: 各领土气候事件（drought/flood/bumper_harvest/cold_wave等）
- **resource_changes**: 各势力资源变化（food_delta, tax_revenue, treasury_spent）
- **battles**: 战斗结果（attack/defend, casualties, territory_captured）
- **diplomatic_events**: 外交事件
- **character_events**: 人物事件（natural_death, loyalty_impact, defection）
- **history_events**: 历史事件触发
- **faction_snapshots**: 各势力当前状态快照

## 输出格式

严格输出纯文本（不是 JSON），直接写出纪事。按以下结构：

### [年份] [季节] · 大事纪
（总览当前天下动态，1-2句）

### 天时气候
（从 climate_events 中提取关键气候变化，对异常气候多加着墨）

### 兵争武事
（若有 battles，逐一简要描述战果，含死伤数据）

### 人物变易
（若有 character_events，记录死讯、叛逃等）

### 天下态势
（从 faction_snapshots 中选取1-2个关键势力变化）

### 史官评曰
（1-2句简短评语）"""


PLAN_SUGGESTIONS_SYSTEM = """你是《三國志略》的军师谋主。玩家需要基于当前物理引擎状态制定战略。

## 核心规则

1. **严格基于当前物理状态** — 不能建议不可能的操作（如没有领土时征兵）
2. **具体、可执行** — 每条建议必须指向具体的领土、兵种、目标势力
3. **包含风险和收益评估**
4. **格式：【策略名】— 具体描述**
5. **生成3-4条建议，300-500字总计**

## 你需要考虑的因素

- 兵力对比：相邻势力谁的兵更多
- 资源状况：粮草是否充足，资金是否宽裕
- 领土位置：与敌对势力相邻的边境领土
- 季节影响：冬季行军消耗1.5倍粮草
- 气候风险：当前领土的气候事件

## 输出格式

每行一条建议，格式：
【策略名称】— 具体描述（含可量化数据）
"""


class NarrativeEngine:
    """Read-only narrative generator for the histrategy v2 physics engine.

    Produces historical chronicle text and strategic suggestions from engine output
    without modifying game state. Uses HistoricalRAG for time-windowed event context.

    Offline fallback generates deterministic text when no LLM key is available.
    """

    def __init__(self, llm_adapter: LLMAdapter | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available

        # Initialize RAG
        self._knowledge_path = _resolve_knowledge_path()
        self._rag = None
        if os.path.isdir(self._knowledge_path):
            try:
                from histrategy_engine.history.rag import HistoricalRAG

                self._rag = HistoricalRAG(self._knowledge_path)
            except Exception:
                pass

    @property
    def is_available(self) -> bool:
        return self.llm_available

    @property
    def rag_available(self) -> bool:
        return self._rag is not None

    # ── Turn Narrative ────────────────────────────────────────

    def generate_turn_narrative(
        self,
        turn_result: TurnResult,
        deviation: float = 0.0,
        averted_events: list[str] | None = None,
        world_state: WorldState | None = None,
    ) -> str:
        """Generate a historical chronicle narrative from a turn's physics results.

        Args:
            turn_result: The complete output from TurnController.execute_turn()
            deviation: The player's historical deviation score.
            averted_events: List of event IDs that were averted.
            world_state: Complete game world state (optional) for detailed context.

        Returns:
            A 文白相间 historical narrative string (200-400 chars).
            Falls back to deterministic text if LLM unavailable.
        """
        if not self.llm_available or not self.llm:
            return self._offline_narrative(turn_result)

        # Build the prompt context from the TurnResult and WorldState
        context = self._build_narrative_context(
            turn_result,
            deviation=deviation,
            averted_events=averted_events,
            world_state=world_state,
        )

        messages = [
            {"role": "system", "content": NARRATIVE_SYSTEM},
            {"role": "user", "content": context},
        ]

        try:
            result = self.llm.chat(
                messages,
                temperature=0.75,
                max_tokens=2048,
            )
            return result.strip()
        except Exception:
            return self._offline_narrative(turn_result)

    def _build_narrative_context(
        self,
        tr: TurnResult,
        deviation: float = 0.0,
        averted_events: list[str] | None = None,
        world_state: WorldState | None = None,
    ) -> str:
        """Build a structured text context from a TurnResult for LLM input."""
        lines: list[str] = []
        lines.append(f"## 当前时间\n{tr.year}年{tr.season.cn} | 第{tr.turn_number}回合\n")

        # Climate events
        if tr.climate_events:
            lines.append("## 天时气候")
            for tid, event in tr.climate_events.items():
                if event.value != "normal":
                    lines.append(f"- {tid}: {event.value}")
            if all(e.value == "normal" for e in tr.climate_events.values()):
                lines.append("全境风调雨顺")
            lines.append("")

        # Resource changes
        if tr.resource_changes:
            lines.append("## 资源变化")
            for fid, changes in tr.resource_changes.items():
                parts = []
                if changes.get("food_delta", 0):
                    parts.append(f"粮草{changes['food_delta']:+d}")
                if changes.get("tax_revenue", 0):
                    parts.append(f"税收+{changes['tax_revenue']}")
                if changes.get("treasury_spent", 0):
                    parts.append(f"支出-{changes['treasury_spent']}")
                if parts:
                    lines.append(f"- {fid}: {', '.join(parts)}")
            lines.append("")

        # Battles
        if tr.battles:
            lines.append("## 兵争武事")
            for b in tr.battles:
                lines.append(f"- {b.location}: {b.attacker_id} vs {b.defender_id} → {b.result.value}")
                if b.territory_captured:
                    lines.append(f"  → 领地易手: {b.location} 归 {b.attacker_id}")
                atk_loss = sum(b.attacker_casualties.values())
                def_loss = sum(b.defender_casualties.values())
                lines.append(f"  伤亡: 攻方{atk_loss} 守方{def_loss}")
            lines.append("")

        # Character events
        if tr.character_events:
            lines.append("## 人物变易")
            for evt in tr.character_events:
                t = evt.get("type", "?")
                name = evt.get("character_name", "?")
                if t == "natural_death":
                    lines.append(f"- {name} 寿终正寝")
                elif t == "defection":
                    lines.append(f"- {name} 叛逃")
                elif t == "loyalty_impact":
                    lines.append(f"- {name} 忠诚度变化 {evt.get('delta', 0):+d}")
                else:
                    lines.append(f"- {name}: {t}")
            lines.append("")

        # Faction snapshots & territories grounding
        if world_state:
            lines.append("## 天下势力及控制城池")
            for fid, fs in world_state.factions.items():
                if not fs.is_active:
                    continue
                ruler_name = "未知"
                if fs.ruler_id in world_state.characters:
                    ruler_name = world_state.characters[fs.ruler_id].name
                else:
                    ruler_name = fs.ruler_id

                t_names = []
                for tid in fs.territories:
                    t = world_state.territories.get(tid)
                    if t:
                        t_names.append(t.name)

                tech_strs = []
                if hasattr(fs, "tech_levels") and fs.tech_levels:
                    for tech_name, val in fs.tech_levels.items():
                        tech_strs.append(f"{tech_name}Lvl.{val}")
                tech_info = f"，科技: {', '.join(tech_strs)}" if tech_strs else ""

                lines.append(
                    f"- {fs.name}（君主: {ruler_name}）: 兵力{fs.strength_actual:,}，"
                    f"资金{fs.treasury:,}，粮草{fs.food:,}。控制城池: {', '.join(t_names) if t_names else '无'}{tech_info}"
                )
            lines.append("")

            # List deceased figures to avoid revival hallucinations
            dead_names = [c.name for c in world_state.characters.values() if not c.alive]
            if "dongzhuo" not in world_state.characters or not world_state.characters["dongzhuo"].alive:
                if "董卓" not in dead_names:
                    dead_names.append("董卓")
            if "liubiao" not in world_state.characters or not world_state.characters["liubiao"].alive:
                if "刘表" not in dead_names:
                    dead_names.append("刘表")

            if dead_names:
                lines.append("## 已亡故/不活跃人物（不可在此回合复活或出现活跃事迹）")
                lines.append(f"- {', '.join(dead_names)}")
                lines.append("")
        elif tr.faction_snapshots:
            lines.append("## 天下态势")
            for fid, fs in tr.faction_snapshots.items():
                if not fs.is_active:
                    continue
                lines.append(
                    f"- {fs.name}: 兵力{fs.strength_actual:,} 领地{len(fs.territories)} "
                    f"资金{fs.treasury:,} 粮草{fs.food:,}"
                )
            lines.append("")

        lines.append("请将以上数据撰写为史书纪事。")

        # Inject RAG context if available
        rag_ctx = self._get_rag_context(tr.year, deviation=deviation, averted_events=averted_events)
        if rag_ctx:
            lines.insert(2, rag_ctx)

        return "\n".join(lines)

    def _offline_narrative(self, tr: TurnResult) -> str:
        """Deterministic offline narrative from TurnResult data."""
        parts: list[str] = []

        # Header
        parts.append(f"### {tr.year}年{tr.season.cn} · 大事纪")
        parts.append(f"建安{tr.year - 196}年{tr.season.cn}，天下纷争未休。")

        # Climate
        not_normal = {tid: ev for tid, ev in tr.climate_events.items() if ev.value != "normal"}
        if not_normal:
            events_cn = {
                "drought": "大旱",
                "flood": "洪水",
                "pestilence": "瘟疫",
                "bumper_harvest": "丰年",
                "cold_wave": "寒潮",
            }
            climate_desc = "；".join(f"{tid}遭{events_cn.get(ev.value, ev.value)}" for tid, ev in not_normal.items())
            parts.append(f"\n### 天时气候\n{climate_desc}。")
        else:
            parts.append("\n### 天时气候\n是岁风调雨顺，五谷丰登。")

        # Battles
        if tr.battles:
            parts.append("\n### 兵争武事")
            battle_results_cn = {
                "decisive_victory": "大破之",
                "victory": "击败之",
                "draw": "两军相持不下",
                "defeat": "败绩",
                "decisive_defeat": "大败而归",
            }
            for b in tr.battles:
                atk_loss = sum(b.attacker_casualties.values())
                def_loss = sum(b.defender_casualties.values())
                result_cn = battle_results_cn.get(b.result.value, "交战")
                parts.append(
                    f"{b.attacker_id}军攻{b.defender_id}于{b.location}，{result_cn}。"
                    f"攻方折兵{atk_loss}，守方损兵{def_loss}。"
                )
                if b.territory_captured:
                    parts.append(f"{b.location}易手，归{b.attacker_id}所有。")

        # Character events
        deaths = [e for e in tr.character_events if "death" in str(e.get("type", ""))]
        if deaths:
            parts.append("\n### 人物变易")
            for e in deaths:
                name = e.get("character_name", "?")
                year = e.get("year", tr.year)
                parts.append(f"{name}于{year}年病故。")

        # Resource summary
        if tr.resource_changes:
            parts.append("\n### 天下态势")
            for fid, changes in tr.resource_changes.items():
                food = changes.get("food_delta", 0)
                tax = changes.get("tax_revenue", 0)
                spent = changes.get("treasury_spent", 0)
                if food or tax or spent:
                    parts.append(f"{fid}: 粮草{food:+d} 税收+{tax} 支出{spent}")

        parts.append(f"\n### 史官评曰\n{tr.year}年{tr.season.cn}之局，诸君且观后变。")

        return "\n".join(parts)

    # ── Plan Suggestions ──────────────────────────────────────

    def generate_plan_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        """Generate strategic suggestions based on physics engine state.

        Args:
            world_state: Current world state from the physics engine
            faction_id: The faction to generate suggestions for

        Returns:
            List of 3-4 strategic suggestions (or generic offline fallback)
        """
        faction = world_state.factions.get(faction_id)
        if not faction or not faction.is_active:
            return ["【势力覆灭】你的势力已不存在。"]

        if not self.llm_available or not self.llm:
            return self._offline_suggestions(world_state, faction_id)

        context = self._build_suggestion_context(world_state, faction_id)

        messages = [
            {"role": "system", "content": PLAN_SUGGESTIONS_SYSTEM},
            {"role": "user", "content": context},
        ]

        try:
            result = self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=2048,
            )
            return self._parse_suggestions(result.strip())
        except Exception:
            return self._offline_suggestions(world_state, faction_id)

    def _build_suggestion_context(self, world_state: WorldState, faction_id: str) -> str:
        """Build context for the plan suggestions prompt."""
        faction = world_state.factions.get(faction_id)
        if not faction:
            return ""

        lines: list[str] = [
            f"## 当前时间\n{world_state.year}年{world_state.season.cn} | 第{world_state.turn_number}回合\n",
            f"## 玩家势力: {faction.name}",
            f"- 兵力: {faction.strength_actual:,}",
            f"- 经济: {faction.economy_actual}/100",
            f"- 民心: {faction.morale_actual}/100",
            f"- 资金: {faction.treasury:,}",
            f"- 粮草: {faction.food:,}",
            f"- 首都: {faction.capital}",
            f"- 领地: {', '.join(faction.territories) if faction.territories else '暂无'}",
            f"- 税率: {faction.tax_rate:.0%}",
            "",
            "## 其他势力",
        ]

        for fid, fs in world_state.factions.items():
            if not fs.is_active or fid == faction_id:
                continue
            lines.append(
                f"- {fs.name}: 兵力{fs.strength_actual:,} "
                f"领地{len(fs.territories)} 关系{fs.relations.get(faction_id, 0):+d}"
            )

        # Add territory details for player faction
        lines.append("")
        lines.append("## 领土详情")
        for tid in faction.territories:
            t = world_state.territories.get(tid)
            if t:
                lines.append(
                    f"- {t.name} ({t.id}): 人口{t.population:,} 开发{t.development} "
                    f"肥沃度{t.fertility} 地形{t.terrain_type.value}"
                )
                if t.neighbors:
                    neighbor_names = [
                        f"{world_state.territories[n].name}({world_state.territories[n].owner_id or '空'})"
                        if n in world_state.territories
                        else n
                        for n in t.neighbors[:5]
                    ]
                    lines.append(f"  邻接: {', '.join(neighbor_names)}")

        # RAG context
        rag_ctx = self._get_rag_context(world_state.year)
        if rag_ctx:
            lines.insert(2, rag_ctx)

        lines.append("\n请基于以上物理状态，为该势力生成3-4条具体可执行的战略建议。")

        return "\n".join(lines)

    def _parse_suggestions(self, text: str) -> list[str]:
        """Parse LLM response into a list of suggestion strings."""
        suggestions: list[str] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Lines starting with 【 or containing 】 are suggestions
            if "【" in line:
                suggestions.append(line)
            elif line[0].isdigit() and ". " in line:
                suggestions.append(line.split(". ", 1)[1])
        return suggestions[:4] if suggestions else [text[:200]]

    def _offline_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        """Deterministic strategy suggestions based on physics engine state."""
        faction = world_state.factions.get(faction_id)
        if not faction:
            return []

        suggestions: list[str] = []
        territories = faction.territories

        # Resource assessment
        food_low = faction.food < 2000
        troops_low = faction.strength_actual < 5000
        treasury_ok = faction.treasury > 2000

        if food_low and territories:
            suggestions.append(
                f"【劝课农桑】发展{territories[0]}的农业，提升粮食产量。当前粮草仅{faction.food}，亟需补充。"
            )
        elif troops_low and treasury_ok and territories:
            suggestions.append(
                f"【征募乡勇】在{territories[0]}招募步兵，增强军力。当前仅{faction.strength_actual}兵卒，不足以御敌。"
            )

        # Expansion check
        for tid in territories:
            t = world_state.territories.get(tid)
            if not t:
                continue
            for nid in t.neighbors:
                nt = world_state.territories.get(nid)
                if nt and nt.owner_id != faction_id and nt.owner_id:
                    suggestions.append(
                        f"【兵锋东指】攻取{nid}（{nt.name}），当前属{nt.owner_id}。"
                        f"侦察显示该地人口{nt.population}，可充实国力。"
                    )
                    break
                elif nt and not nt.owner_id:
                    suggestions.append(f"【据土略地】派军占据{nid}（{nt.name}），该地现为空城。")
                    break
            if len(suggestions) >= 2:
                break

        # Diplomacy
        neighbors = set()
        for tid in territories:
            t = world_state.territories.get(tid)
            if t:
                for nid in t.neighbors:
                    nt = world_state.territories.get(nid)
                    if nt and nt.owner_id and nt.owner_id != faction_id:
                        neighbors.add(nt.owner_id)

        for nfid in list(neighbors)[:1]:
            nf = world_state.factions.get(nfid)
            if nf:
                rel = nf.relations.get(faction_id, 0)
                if rel >= 0:
                    suggestions.append(f"【遣使修好】派使者加强与{nf.name}的盟约关系。当前关系{rel:+d}，联合可抗强敌。")

        # Ensure 3-4 suggestions
        if len(suggestions) < 3 and territories:
            suggestions.append(f"【固本培元】发展{territories[0]}至更高开发度，提升税收和粮食产量。")
        if len(suggestions) < 3:
            suggestions.append("【远交近攻】审视外交局势，联合远方势力对抗近邻。")
        if len(suggestions) < 3:
            suggestions.append("【厉兵秣马】招募兵勇，操练新军，等待时机。")

        return suggestions[:4]

    # ── RAG Integration ────────────────────────────────────────

    def _get_rag_context(self, year: int, deviation: float = 0.0, averted_events: list[str] | None = None) -> str:
        """Retrieve and format RAG context for the given year."""
        if not self._rag:
            return ""
        try:
            events = self._rag.retrieve(year, deviation=deviation, max_events=5, averted_events=averted_events)
            if events:
                return self._rag.build_llm_context(events)
        except Exception:
            pass
        return ""

    def get_rag_instance(self):
        """Expose the RAG instance for external use."""
        return self._rag
