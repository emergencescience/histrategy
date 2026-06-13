"""
DecisionBus — 对称决策收集总线。

在对称多人引擎中，每个季度需要收集所有活跃 FactionSlot 的决策。
DecisionBus 负责：
1. 收集人类玩家的已提交决策（通过 API 的 pending_decision）
2. 并行调用 LLM 为每个主要 NPC 生成独立决策
3. 为次要 NPC 使用启发式规则
4. 超时处理：未提交的人类玩家自动转为 AI 决策

多人类玩家交互：
    使用前端轮询（polling）检查等待状态，而非 WebSocket。
    客户端定期调用 GET /api/rooms/{id}/status 检查是否全员就绪。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from .faction_slot import FactionSlot

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

    from .game_room import GameRoom

logger = logging.getLogger("histrategy.decision_bus")

# 决策收集超时（秒）
DEFAULT_DECISION_TIMEOUT = 300  # 5分钟


class DecisionResult:
    """一个 faction 的决策收集结果。"""

    __slots__ = (
        "faction_id",
        "decision_text",
        "commands",
        "source",
        "latency_ms",
        "error",
    )

    def __init__(
        self,
        faction_id: str,
        decision_text: str = "",
        commands: list | None = None,
        source: str = "unknown",
        latency_ms: float = 0,
        error: str | None = None,
    ):
        self.faction_id = faction_id
        self.decision_text = decision_text
        self.commands = commands or []
        self.source = source  # "human" | "llm" | "heuristic" | "auto_timeout"
        self.latency_ms = latency_ms
        self.error = error

    def __repr__(self) -> str:
        return (
            f"DecisionResult({self.faction_id}, "
            f"source={self.source}, "
            f"latency={self.latency_ms:.0f}ms" + (f", error={self.error}" if self.error else "") + ")"
        )


def collect_all_decisions(
    room: GameRoom,
    world_state: WorldState,
    llm: LLMAdapter | None = None,
    turn_memory: list[dict] | None = None,
    timeout: int = DEFAULT_DECISION_TIMEOUT,
) -> dict[str, DecisionResult]:
    """收集本季度所有活跃 faction 的决策。

    这是对称多人引擎的核心入口。调用者（API层或CLI）调用此函数，
    等待所有决策就绪后，再将结果喂给 resolve_quarter()。

    Args:
        room: 游戏房间（包含所有 FactionSlot）
        world_state: 当前世界状态
        llm: LLM 适配器（为 NPC 生成决策）
        turn_memory: 回合记忆
        timeout: 超时秒数（超时后未提交的人类自动 AI 决策）

    Returns:
        {faction_id: DecisionResult}
    """
    results: dict[str, DecisionResult] = {}
    start_time = time.time()

    # 1. 收集人类玩家已提交的决策
    for slot in room.human_slots():
        if slot.has_submitted():
            results[slot.faction_id] = DecisionResult(
                faction_id=slot.faction_id,
                decision_text=slot.pending_decision or "",
                commands=slot.pending_commands,
                source="human",
            )

    # 2. 并行 LLM 调用：为主要 NPC 生成独立决策
    # 但如果 AI slot 已经有预生成的 pending_decision（来自 _trigger_npc_decisions），
    # 直接复用——避免对 NPC 重复调 LLM
    pre_submitted_ai = [
        s for s in room.major_ai_slots()
        if s.faction_id not in results and s.has_submitted()
    ]
    for s in pre_submitted_ai:
        results[s.faction_id] = DecisionResult(
            faction_id=s.faction_id,
            decision_text=s.pending_decision or "",
            commands=s.pending_commands,
            source="llm",
        )
    major_ai = [
        s for s in room.major_ai_slots()
        if s.faction_id not in results
    ]
    if major_ai and llm:
        _collect_ai_decisions_parallel(
            major_ai,
            world_state,
            llm,
            turn_memory or [],
            results,
        )
    elif major_ai:
        # LLM not available → heuristic fallback for major NPCs too
        for slot in major_ai:
            decision, commands = _generate_heuristic_decision(
                world_state,
                slot.faction_id,
            )
            results[slot.faction_id] = DecisionResult(
                faction_id=slot.faction_id,
                decision_text=decision,
                commands=commands,
                source="heuristic",
            )

    # 3. 启发式：为次要 NPC 生成决策
    for slot in room.minor_ai_slots():
        if slot.faction_id not in results:
            decision, commands = _generate_heuristic_decision(
                world_state,
                slot.faction_id,
            )
            results[slot.faction_id] = DecisionResult(
                faction_id=slot.faction_id,
                decision_text=decision,
                commands=commands,
                source="heuristic",
            )

    # 4. 超时处理：未提交的人类玩家 → AI 自动决策
    elapsed = time.time() - start_time
    if elapsed > timeout:
        for slot in room.human_slots():
            if slot.faction_id not in results:
                logger.warning(
                    f"Human player {slot.occupant_id} for faction {slot.faction_id} timed out after {elapsed:.0f}s"
                )
                if llm:
                    decision, commands = _generate_llm_decision(
                        world_state,
                        slot.faction_id,
                        llm,
                        turn_memory or [],
                        slot,
                    )
                    source = "auto_timeout_llm"
                else:
                    decision, commands = _generate_heuristic_decision(
                        world_state,
                        slot.faction_id,
                    )
                    source = "auto_timeout_heuristic"
                results[slot.faction_id] = DecisionResult(
                    faction_id=slot.faction_id,
                    decision_text=decision,
                    commands=commands,
                    source=source,
                )
                # 更新 slot
                slot.submit_decision(decision, commands)

    return results


def _collect_ai_decisions_parallel(
    ai_slots: list[FactionSlot],
    world_state: WorldState,
    llm: LLMAdapter,
    turn_memory: list[dict],
    results: dict[str, DecisionResult],
):
    """并行调用 LLM 为多个 NPC 生成决策。"""
    from histrategy.llm.npc_decision_engine import NPCDecisionEngine

    engine = NPCDecisionEngine(llm)

    def _generate_one(slot: FactionSlot) -> DecisionResult:
        t0 = time.time()
        try:
            decision, commands = engine.generate(
                world_state,
                slot.faction_id,
                turn_memory,
                slot,
            )
            latency = (time.time() - t0) * 1000
            return DecisionResult(
                faction_id=slot.faction_id,
                decision_text=decision,
                commands=commands,
                source="llm",
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.time() - t0) * 1000
            logger.error(f"NPC decision failed for {slot.faction_id}: {e}")
            # 回退到启发式
            decision, commands = _generate_heuristic_decision(
                world_state,
                slot.faction_id,
            )
            return DecisionResult(
                faction_id=slot.faction_id,
                decision_text=decision,
                commands=commands,
                source="heuristic_fallback",
                latency_ms=latency,
                error=str(e),
            )

    with ThreadPoolExecutor(max_workers=len(ai_slots)) as executor:
        futures = {executor.submit(_generate_one, slot): slot for slot in ai_slots}
        for future in as_completed(futures):
            result = future.result()
            results[result.faction_id] = result
            # 更新 slot
            slot = futures[future]
            slot.submit_decision(result.decision_text, result.commands)


def _generate_llm_decision(
    ws: WorldState,
    faction_id: str,
    llm: LLMAdapter,
    turn_memory: list[dict],
    slot: FactionSlot | None = None,
) -> tuple[str, list]:
    """同步 LLM 决策（用于超时回退）。"""
    from histrategy.llm.npc_decision_engine import NPCDecisionEngine

    engine = NPCDecisionEngine(llm)
    return engine.generate(ws, faction_id, turn_memory, slot)


def _generate_heuristic_decision(
    ws: WorldState,
    faction_id: str,
) -> tuple[str, list]:
    """启发式决策（用于次要NPC和LLM回退）。"""
    faction = ws.factions.get(faction_id)
    if not faction or not faction.is_active:
        return "休整", []

    commands: list[dict] = []
    parts: list[str] = []

    strength = getattr(faction, "strength_actual", 0)
    treasury = faction.treasury
    food = faction.food

    # 招募：兵力低于10000且有资金
    if strength < 10000 and treasury > 2000:
        amount = min(3000, treasury // 2)
        commands.append(
            {
                "type": "conscript",
                "params": {"amount": amount},
                "reasoning": "补充兵力",
            }
        )
        parts.append(f"征兵{amount}")

    # 发展：资金充裕时开发首都
    if treasury > 5000 and food > 3000:
        capital = faction.capital or (faction.territories[0] if faction.territories else None)
        if capital:
            commands.append(
                {
                    "type": "develop",
                    "params": {"territory": capital},
                    "reasoning": "发展经济",
                }
            )
            parts.append(f"开发{capital}")

    # 税收到30%以上降低
    if faction.tax_rate > 0.35:
        commands.append(
            {
                "type": "tax",
                "params": {"tax_rate": 0.3},
                "reasoning": "减轻民负",
            }
        )
        parts.append("降低税率至三成")

    decision = "、".join(parts) + "。" if parts else "休整观望。"
    return decision, commands
