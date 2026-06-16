"""
QuarterlyResolver — 对称多 faction 季度引擎。

替代旧的 GameEngine._process_turn_macro()。
接收所有 faction 的决策，统一执行季度模拟：

1. 解析所有势力决策（人类 → IntentParser，AI → 已预解析）
2. 确定性基线 (TurnController multi-faction)
3. 黑天鹅事件注入 (BlackSwanInjector)
4. LLM 宏观模拟 (MacroPolicyEngine with all decisions)
5. Per-faction 叙事生成 (parallel NarrativeEngine)
6. 状态持久化 (SQL)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from .decision_bus import DecisionResult

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.engine.game_room import GameRoom
    from histrategy.llm.adapter import LLMAdapter

logger = logging.getLogger("histrategy.quarterly")

# ── 内部引擎引用（延迟导入以避免循环依赖） ──


class QuarterlyResolver:
    """对称多 faction 季度引擎。

    这是整个对称多人引擎的「执行核心」。接收一个 GameRoom
    和所有 faction 的决策，执行完整的季度模拟。

    注意：此引擎对「单人类 + 多AI」和「多人类 + 多AI」
    一视同仁——它只看到 FactionSlot 和 DecisionResult。
    """

    def __init__(
        self,
        intent_parser=None,
        turn_controller=None,
        history_engine=None,
        macro_policy_engine=None,
        narrative_engine=None,
        black_swan_injector=None,
        guardrail_validator=None,
        state_applier=None,
    ):
        self.intent_parser = intent_parser
        self.turn_controller = turn_controller
        self.history_engine = history_engine
        self.macro_policy_engine = macro_policy_engine
        self.narrative_engine = narrative_engine
        self.black_swan_injector = black_swan_injector
        self.guardrail_validator = guardrail_validator
        self.state_applier = state_applier

    def resolve(
        self,
        room: GameRoom,
        world_state: WorldState,
        decisions: dict[str, DecisionResult],
        llm: LLMAdapter | None = None,
    ) -> QuarterlyResult:
        """执行一个季度的完整模拟。

        Args:
            room: 游戏房间
            world_state: 当前世界状态（会被原地修改）
            decisions: 所有 faction 的决策 {faction_id: DecisionResult}
            llm: LLM 适配器

        Returns:
            QuarterlyResult: 包含叙事、状态变更、事件等
        """
        t_start = time.time()
        results = QuarterlyResult()

        # ── Step 1: 解析所有势力决策 ──
        all_commands: dict[str, list] = {}
        all_decisions: dict[str, str] = {}
        for faction_id, dr in decisions.items():
            all_decisions[faction_id] = dr.decision_text
            if dr.commands:
                # AI 已预解析
                all_commands[faction_id] = dr.commands
            elif self.intent_parser:
                # 人类决策 → IntentParser
                try:
                    parsed = self.intent_parser.parse(dr.decision_text, faction_id)
                    all_commands[faction_id] = parsed
                except Exception as e:
                    logger.warning(f"Intent parse failed for {faction_id}: {e}")
                    all_commands[faction_id] = []

        # ── Step 2: 确定性基线 ──
        baseline = None
        if self.turn_controller:
            try:
                baseline = self._execute_baseline(
                    world_state,
                    all_commands,
                    room,
                )
            except Exception as e:
                logger.error(f"TurnController failed: {e}")
                baseline = _empty_baseline(world_state)

        # ── Step 3: 黑天鹅事件 ──
        bs_proposals = []
        if self.black_swan_injector and self.history_engine:
            try:
                from histrategy.engine.game import apply_event_effects

                proposals = self.history_engine.check_events(
                    world_state.year,
                    getattr(world_state, 'season', 0),
                    world_state,
                    deviation=getattr(world_state, "player_deviation", 0.0),
                )
                for prop in proposals:
                    effects = prop.effects.get("effects", {})
                    apply_event_effects(world_state, effects)
                bs_proposals = proposals
                results.history_events = [
                    {
                        "event_id": p.event_id,
                        "title": p.title,
                        "description": p.effects.get("outcome_description", ""),
                    }
                    for p in proposals
                ]
            except Exception as e:
                logger.warning(f"BlackSwanInjector failed: {e}")

        # ── Step 4: LLM 宏观模拟 ──
        macro_delta = {}
        if self.macro_policy_engine and llm:
            try:
                macro_delta = self._run_macro_simulation(
                    world_state,
                    all_commands,
                    all_decisions,
                    baseline,
                    bs_proposals,
                    room,
                )
            except Exception as e:
                logger.error(f"MacroPolicyEngine failed: {e}")

        # ── Step 5: Guardrail 验证 + 状态应用 ──
        if macro_delta and self.guardrail_validator:
            try:
                macro_delta = self.guardrail_validator.validate(
                    macro_delta,
                    world_state,
                )
            except Exception as e:
                logger.warning(f"GuardrailValidator failed: {e}")

        if macro_delta and self.state_applier:
            try:
                self.state_applier.apply(macro_delta, world_state)
            except Exception as e:
                logger.error(f"StateApplier failed: {e}")

        # ── Step 6: Per-faction 叙事生成 ──
        if self.narrative_engine:
            try:
                results.narratives = self._generate_narratives(
                    world_state,
                    all_commands,
                    all_decisions,
                    baseline,
                    macro_delta,
                    room,
                )
            except Exception as e:
                logger.error(f"Narrative generation failed: {e}")

        # ── Step 7: 状态收集 ──
        results.state_changes = _extract_state_changes(world_state, decisions)
        results.total_latency_ms = (time.time() - t_start) * 1000

        # ── Step 8: 回合摘要 ──
        results.turn_summary = _build_turn_summary(
            room,
            world_state,
            all_decisions,
            results,
        )

        return results

    def _execute_baseline(
        self,
        ws: WorldState,
        all_commands: dict[str, list],
        room: GameRoom,
    ):
        """执行确定性基线（TurnController multi-faction）。

        Runs execute_turn() ONCE with all faction commands combined,
        then advances season ONCE (TurnController handles the advance).
        """
        # 尝试 multi-faction 模式
        if hasattr(self.turn_controller, "execute_multi_faction_turn"):
            return self.turn_controller.execute_multi_faction_turn(
                ws,
                all_commands,
                year=ws.year,
                turn_number=ws.turn,
            )

        # 回退：合并所有 faction 的 commands，调用一次 execute_turn
        # 注意：execute_turn() 内部会 _advance_season，所以这里只需调用一次
        combined_commands = []
        for faction_id, commands in all_commands.items():
            for cmd in commands:
                # Inject faction_id if missing (dict form)
                if isinstance(cmd, dict) and "faction_id" not in cmd:
                    cmd = {**cmd, "faction_id": faction_id}
                combined_commands.append(cmd)

        try:
            return self.turn_controller.execute_turn(
                ws,
                player_commands=combined_commands,
                year=ws.year,
                turn_number=getattr(ws, 'turn_number', getattr(ws, 'turn', 1)),
            )
        except Exception as e:
            logger.warning(f"Baseline execution failed: {e}")
        return _empty_baseline(ws)

    def _run_macro_simulation(
        self,
        ws,
        all_commands,
        all_decisions,
        baseline,
        bs_proposals,
        room,
    ) -> dict:
        """运行 LLM 宏观模拟。"""
        # 构建玩家策令文本（主要faction的决策）
        player_faction = None
        for slot in room.active_slots():
            if slot.is_human():
                player_faction = slot.faction_id
                break
        if not player_faction:
            player_faction = next(iter(all_decisions.keys()), None)

        player_decision = all_decisions.get(player_faction, "")
        player_commands = all_commands.get(player_faction, [])

        # NPC 行动（非玩家 faction）
        npc_actions = []
        for fid, decision in all_decisions.items():
            if fid != player_faction:
                npc_actions.append(
                    {
                        "faction": fid,
                        "action": decision,
                    }
                )

            return self.macro_policy_engine.simulate(
                ws,
                policy_commands=player_commands,
                player_decision=player_decision,
                baseline=baseline or _empty_baseline(ws),
                history_events=[{"event_id": p.event_id, "title": p.title} for p in bs_proposals] if bs_proposals else [],
                turn_memory=room.turn_summaries[-8:] if room.turn_summaries else [],
                room_id=room.id,
            )

    def _generate_narratives(
        self,
        ws,
        all_commands,
        all_decisions,
        baseline,
        macro_delta,
        room,
    ) -> dict[str, str]:
        """并行生成每个 faction 视角的叙事。"""
        narratives: dict[str, str] = {}

        def _narrate_one(faction_id: str) -> tuple[str, str]:
            try:
                narrative = self.narrative_engine.generate_faction_narrative(
                    ws,
                    faction_id,
                    baseline,
                    macro_delta,
                    decision=all_decisions.get(faction_id, ""),
                    commands=all_commands.get(faction_id, []),
                    room_id=room.id,
                )
                return faction_id, narrative or ""
            except Exception as e:
                logger.warning(f"Narrative failed for {faction_id}: {e}")
                return faction_id, ""

        factions = list(all_decisions.keys())
        if not factions:
            return narratives
        with ThreadPoolExecutor(max_workers=min(len(factions), 4)) as executor:
            futures = {executor.submit(_narrate_one, fid): fid for fid in factions}
            for future in as_completed(futures):
                fid, narrative = future.result()
                narratives[fid] = narrative

        return narratives


# ── Result Data Class ──────────────────────────────


class QuarterlyResult:
    """季度模拟的完整结果。"""

    __slots__ = (
        "narratives",
        "state_changes",
        "history_events",
        "total_latency_ms",
        "turn_summary",
        "game_over",
    )

    def __init__(self):
        self.narratives: dict[str, str] = {}  # faction_id → 叙事文本
        self.state_changes: dict[str, dict] = {}  # faction_id → 资源变化
        self.history_events: list[dict] = []
        self.total_latency_ms: float = 0
        self.turn_summary: dict = {}
        self.game_over: dict | None = None


# ── Helpers ────────────────────────────────────────


def _empty_baseline(ws: WorldState):
    """创建一个空的基线结果（当 TurnController 不可用时）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        battles=[],
        resource_changes={},
        character_events=[],
        history_events=[],
        season_name=str(getattr(getattr(ws, 'season', None), 'cn', None) or getattr(ws, 'season', '?')),
        year=ws.year,
        tax_revenue={},
        food_delta={},
        population_delta={},
        morale_delta={},
    )


def _extract_state_changes(
    ws: WorldState,
    decisions: dict[str, DecisionResult],
) -> dict[str, dict]:
    """提取所有 faction 的状态变更摘要。"""
    changes = {}
    for faction_id, _dr in decisions.items():
        faction = ws.factions.get(faction_id)
        if not faction:
            continue
        changes[faction_id] = {
            "strength": getattr(faction, "strength_actual", 0),
            "treasury": faction.treasury,
            "food": faction.food,
            "morale": getattr(faction, "morale_actual", 50),
            "territories": list(faction.territories) if faction.territories else [],
            "is_active": faction.is_active,
        }
    return changes


def _build_turn_summary(
    room: GameRoom,
    ws: WorldState,
    all_decisions: dict[str, str],
    results: QuarterlyResult,
) -> dict:
    """构建回合摘要（用于后续 LLM 上下文）。"""
    season_cn = ws.current_season_cn
    decision_summaries = []
    for fid, decision in all_decisions.items():
        short = decision[:60] + "..." if len(decision) > 60 else decision
        faction = ws.factions.get(fid)
        name = faction.name if faction else fid
        decision_summaries.append(f"{name}: {short}")

    events_str = (
        "; ".join(e.get("title", "") for e in results.history_events[:3]) if results.history_events else "天下无事"
    )

    return {
        "outcome_summary": (f"[{ws.year}年{season_cn}] " + " | ".join(decision_summaries[:3]) + f" → {events_str}"),
        "turn": ws.turn,
        "year": ws.year,
        "season": season_cn,
    }
