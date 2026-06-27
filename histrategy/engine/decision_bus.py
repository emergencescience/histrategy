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
    lang: str = "zh",
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
        lang: 语言 (zh | en)

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
    pre_submitted_ai = [s for s in room.major_ai_slots() if s.faction_id not in results and s.has_submitted()]
    for s in pre_submitted_ai:
        results[s.faction_id] = DecisionResult(
            faction_id=s.faction_id,
            decision_text=s.pending_decision or "",
            commands=s.pending_commands,
            source="llm",
        )
    major_ai = [s for s in room.major_ai_slots() if s.faction_id not in results]
    if major_ai and llm:
        _collect_ai_decisions_parallel(
            major_ai,
            world_state,
            llm,
            turn_memory or [],
            results,
            room_id=getattr(room, "id", ""),
            quarter_number=getattr(room, "quarter_number", 0),
            scenario=getattr(room, "scenario", None),
            lang=lang,
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
                    f"Human faction {slot.faction_id} timed out after {elapsed:.0f}s"
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
    room_id: str = "",
    quarter_number: int = 0,
    scenario: str | None = None,
    lang: str = "zh",
):
    """并行调用 LLM 为多个 NPC 生成决策。"""
    from histrategy.llm.npc_decision_engine import NPCDecisionEngine

    engine = NPCDecisionEngine(llm, scenario=scenario, language=lang)

    # Attach conditional history engine if scenario rules exist
    try:
        from histrategy.engine.conditional_history import ConditionalHistoryEngine

        _hist = ConditionalHistoryEngine(scenario, language=lang)
        if _hist.event_count > 0:
            engine.set_history_engine(_hist)
    except Exception:
        pass  # history injection is optional — don't block NPC decisions

    def _generate_one(slot: FactionSlot) -> DecisionResult:
        t0 = time.time()
        try:
            decision, commands = engine.generate(
                world_state,
                slot.faction_id,
                turn_memory,
                slot,
                room_id=room_id,
                quarter_number=quarter_number,
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

    _NPC_LLM_TIMEOUT = 60  # 每个 NPC 的 LLM 调用超时（秒）
    with ThreadPoolExecutor(max_workers=len(ai_slots)) as executor:
        futures = {executor.submit(_generate_one, slot): slot for slot in ai_slots}
        for future in as_completed(futures):
            slot = futures[future]
            try:
                result = future.result(timeout=_NPC_LLM_TIMEOUT)
            except TimeoutError:
                logger.error(
                    f"NPC LLM call timed out ({_NPC_LLM_TIMEOUT}s) for {slot.faction_id} — "
                    f"falling back to heuristic"
                )
                decision, commands = _generate_heuristic_decision(
                    world_state,
                    slot.faction_id,
                )
                result = DecisionResult(
                    faction_id=slot.faction_id,
                    decision_text=decision,
                    commands=commands,
                    source="heuristic_timeout",
                    latency_ms=_NPC_LLM_TIMEOUT * 1000,
                    error="LLM call timed out",
                )
            results[result.faction_id] = result
            # 更新 slot
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
    """启发式决策（用于次要NPC和LLM回退）。

    Context-aware heuristic that considers:
    - Neighbor threats (troop ratios, hostile relations)
    - Strategic defense when outnumbered
    - Opportunistic attack when stronger
    - Development during peace
    - Tax/economic management
    """
    faction = ws.factions.get(faction_id)
    if not faction or not faction.is_active:
        return "休整", []

    commands: list[dict] = []
    parts: list[str] = []

    def _cmd(type_: str, params: dict, reasoning: str) -> dict:
        return {"type": type_, "params": params, "reasoning": reasoning, "faction_id": faction_id}

    strength = getattr(faction, "strength_actual", 0)
    treasury = getattr(faction, "treasury", 0)
    food = getattr(faction, "food", 0)
    morale = getattr(faction, "morale_actual", 50)
    territories = list(getattr(faction, "territories", []))
    capital = getattr(faction, "capital", territories[0] if territories else None)
    relations = getattr(faction, "relations", {})

    # ── Analyze neighbors ──────────────────────────────────
    neighbors = _resolve_heuristic_neighbors(ws, faction_id)
    hostile_neighbors = []
    for nid in neighbors:
        nf = ws.factions.get(nid)
        if nf is None or not getattr(nf, "is_active", True):
            continue
        n_strength = getattr(nf, "strength_actual", 0)
        rel = relations.get(nid, 0)
        if rel < -30:
            hostile_neighbors.append((nid, nf, n_strength))

    # ── Priority 1: Emergency conscription ──
    if strength < 3000 and treasury > 1000:
        amount = min(5000, treasury // 2)
        if amount >= 1000:
            commands.append(_cmd("conscript", {"amount": amount}, "危急存亡之秋，紧急扩军备战"))
            parts.append(f"紧急征兵{amount}")

    # ── Priority 2: Standard recruitment ──
    elif strength < 10000 and treasury > 2000:
        amount = min(5000, treasury // 2)
        commands.append(_cmd("conscript", {"amount": amount}, "补充兵力"))
        parts.append(f"征兵{amount}")

    # ── Priority 3: Attack weak hostile neighbor ──
    attack_made = False
    if hostile_neighbors:
        hostile_neighbors.sort(key=lambda x: x[2])
        for nid, nf, n_strength in hostile_neighbors:
            if strength > n_strength * 1.5 and strength > 5000:
                n_territories = list(getattr(nf, "territories", []))
                target = n_territories[0] if n_territories else None
                if target:
                    commands.append(
                        _cmd("attack", {"target": target, "target_faction": nid}, f"趁敌弱，先发制人进攻{nid}")
                    )
                    parts.append(f"出兵攻打{nid}")
                    attack_made = True
                    break

    # ── Priority 4: Defend against stronger hostiles ──
    if hostile_neighbors and not attack_made:
        stronger = [(nid, nf, s) for nid, nf, s in hostile_neighbors if s > strength]
        if stronger:
            strongest = max(stronger, key=lambda x: x[2])
            border = _resolve_heuristic_border(ws, faction_id, strongest[0])
            commands.append(
                _cmd(
                    "defend",
                    {"target": strongest[0], "border": border},
                    f"敌强我弱，固守{border or '边境'}防御{strongest[0]}",
                )
            )
            parts.append(f"固守{border or '边境'}以御{strongest[0]}")

    # ── Priority 5: Development ──
    if not attack_made and treasury > 3000 and food > 2000 and capital and not hostile_neighbors:
        commands.append(_cmd("develop", {"territory": capital}, "发展经济"))
        parts.append(f"开发{capital}")

    # ── Priority 6: Tax adjustment ──
    if morale < 30 and getattr(faction, "tax_rate", 0.3) > 0.25:
        new_rate = max(0.15, getattr(faction, "tax_rate", 0.3) - 0.10)
        commands.append(_cmd("tax", {"tax_rate": round(new_rate, 2)}, "减税安民"))
        parts.append(f"减税至{int(new_rate * 100)}%")
    elif getattr(faction, "tax_rate", 0.3) > 0.35:
        commands.append(_cmd("tax", {"tax_rate": 0.3}, "减轻民负"))
        parts.append("降低税率至三成")

    decision = "；".join(parts) + "。" if parts else "休整观望，静待时机。"
    return decision, commands


def _resolve_heuristic_neighbors(ws: WorldState, faction_id: str) -> list[str]:
    """Get neighboring faction IDs for heuristic decisions."""
    faction = ws.factions.get(faction_id)
    if not faction:
        return []
    my_territories = set(getattr(faction, "territories", []))
    neighbor_factions: set[str] = set()
    for tid in my_territories:
        territory = ws.territories.get(tid)
        if territory and getattr(territory, "neighbors", None):
            for nid in territory.neighbors:
                nt = ws.territories.get(nid)
                if nt and getattr(nt, "owner_id", "") != faction_id:
                    neighbor_factions.add(getattr(nt, "owner_id", ""))
    return [n for n in neighbor_factions if n]


def _resolve_heuristic_border(ws: WorldState, faction_id: str, neighbor_id: str) -> str | None:
    """Find the border territory between two factions."""
    faction = ws.factions.get(faction_id)
    neighbor = ws.factions.get(neighbor_id)
    if not faction or not neighbor:
        return None
    my_territories = set(getattr(faction, "territories", []))
    neighbor_territories = set(getattr(neighbor, "territories", []))
    for tid in my_territories:
        territory = ws.territories.get(tid)
        if territory and hasattr(territory, "neighbors"):
            for nid in territory.neighbors:
                if nid in neighbor_territories:
                    return tid
    return None
