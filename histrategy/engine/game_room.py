"""
对称多人游戏房间 — 替代 GameSession 的多人架构核心。

GameRoom 拥有一组对称的 FactionSlot，不区分人类还是AI——
所有势力通过相同的状态机提交决策，由 DecisionBus 统一收集。

RoomPhase:
    LOBBY     — 等待玩家加入（仅大厅阶段）
    WAITING   — 等待所有 faction 提交本季度决策
    RESOLVING — 正在执行季度引擎（拒绝新提交）
    FINISHED  — 游戏结束
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .faction_slot import (
    FactionSlot,
    HEURISTIC_NPC_FACTIONS,
    LLM_NPC_FACTIONS,
    OccupantType,
    create_ai_slot,
    create_open_slot,
)

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


class RoomPhase(Enum):
    LOBBY = "lobby"          # 等待玩家加入
    WAITING = "waiting"      # 等待所有 faction 提交本季度决策
    RESOLVING = "resolving"  # 正在执行季度引擎（拒绝新提交）
    FINISHED = "finished"    # 游戏结束


@dataclass
class GameRoom:
    """一局游戏——拥有 N 个对称的 FactionSlot。

    与旧版 GameSession 的核心区别：
    - 没有 player_faction_id —— 所有势力对称
    - 没有单一「玩家」概念 —— 每个 FactionSlot 独立提交决策
    - 通过 RoomPhase 状态机驱动多 faction 季度循环
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    host_user_id: str | None = None
    scenario: str = "207"
    year: int = 207
    season: str = "春"
    quarter_number: int = 0
    phase: RoomPhase = RoomPhase.LOBBY
    slots: dict[str, FactionSlot] = field(default_factory=dict)  # faction_id → slot
    world_state: WorldState | None = None

    # 等待超时配置（秒）
    decision_timeout: int = 300       # 人类玩家提交决策的超时

    # 回合记忆（最近 N 个季度的摘要，供 LLM 上下文使用）
    turn_summaries: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.phase, str):
            self.phase = RoomPhase(self.phase)

    # ── 提交状态查询 ──────────────────────────────

    def all_slots_submitted(self) -> bool:
        """本季度所有活跃 slot 是否都已提交决策。"""
        active = [s for s in self.slots.values() if s.is_active]
        if not active:
            return True
        return all(s.has_submitted() for s in active)

    def pending_slots(self) -> list[str]:
        """本季度尚未提交决策的 faction_id 列表。"""
        return [
            fid for fid, s in self.slots.items()
            if s.is_active and not s.has_submitted()
        ]

    # ── 类型分组 ──────────────────────────────────

    def human_slots(self) -> list[FactionSlot]:
        """所有人类玩家槽位。"""
        return [s for s in self.slots.values() if s.is_human()]

    def ai_slots(self) -> list[FactionSlot]:
        """所有 AI NPC 槽位。"""
        return [s for s in self.slots.values() if s.is_ai()]

    def major_ai_slots(self) -> list[FactionSlot]:
        """主要 NPC 势力（cao/shu/wu）—— 使用 LLM 独立决策。"""
        return [
            s for s in self.slots.values()
            if s.is_ai() and s.faction_id in LLM_NPC_FACTIONS
        ]

    def minor_ai_slots(self) -> list[FactionSlot]:
        """次要 NPC 势力 —— 使用启发式规则。"""
        return [
            s for s in self.slots.values()
            if s.is_ai() and s.faction_id in HEURISTIC_NPC_FACTIONS
        ]

    def active_slots(self) -> list[FactionSlot]:
        """所有活跃槽位（无论人类/AI）。"""
        return [s for s in self.slots.values() if s.is_active]

    # ── 季度推进 ──────────────────────────────────

    def advance_quarter(self):
        """推进到下一季度，清空所有 pending，进入 WAITING。"""
        self.quarter_number += 1
        for slot in self.slots.values():
            slot.clear_decision()
        self.phase = RoomPhase.WAITING

    # ── 游戏生命周期 ──────────────────────────────

    def start_game(self):
        """从 LOBBY 进入 WAITING 状态，开始第一个季度。

        在单人模式中 room 可能已经是 WAITING（通过工厂函数创建），
        此调用仍然是安全的（幂等）。
        """
        if self.phase == RoomPhase.LOBBY:
            self.phase = RoomPhase.WAITING

    # ── 玩家管理 ──────────────────────────────────

    def has_human_player(self) -> bool:
        """是否至少有一个人类玩家。"""
        return any(s.is_human() for s in self.slots.values())

    def is_empty(self) -> bool:
        """是否没有任何参与者（无人类、无AI）。"""
        return len(self.slots) == 0

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "host_user_id": self.host_user_id,
            "scenario": self.scenario,
            "year": self.year,
            "season": self.season,
            "quarter_number": self.quarter_number,
            "phase": self.phase.value,
            "slots": {fid: s.to_dict() for fid, s in self.slots.items()},
            "decision_timeout": self.decision_timeout,
            "turn_summaries": self.turn_summaries,
        }

    @classmethod
    def from_dict(cls, data: dict, world_state: WorldState | None = None) -> "GameRoom":
        """从字典重建 GameRoom（不含 world_state，需单独加载）。"""
        room = cls(
            id=data["id"],
            host_user_id=data.get("host_user_id"),
            scenario=data.get("scenario", "207"),
            year=data.get("year", 207),
            season=data.get("season", "春"),
            quarter_number=data.get("quarter_number", 0),
            phase=RoomPhase(data.get("phase", "lobby")),
            decision_timeout=data.get("decision_timeout", 300),
            turn_summaries=data.get("turn_summaries", []),
            world_state=world_state,
        )
        # 从 from_dict 重建时 pending 不恢复（已在上季度结算）
        for fid, sd in data.get("slots", {}).items():
            slot = FactionSlot.from_dict(sd)
            slot.pending_decision = None
            slot.pending_commands = None
            room.slots[fid] = slot
        return room

    def __repr__(self) -> str:
        human_count = len(self.human_slots())
        ai_count = len(self.ai_slots())
        return (
            f"GameRoom({self.id}, phase={self.phase.value}, "
            f"Q{self.quarter_number}, {human_count}H+{ai_count}AI, "
            f"pending={self.pending_slots()})"
        )


# ── 工厂函数 ──────────────────────────────────────


def create_single_player_room(
    faction_id: str,
    user_id: str,
    scenario: str = "207",
) -> GameRoom:
    """创建单人模式的 GameRoom。

    玩家占据一个 faction，其他两大势力自动填充为 AI NPC。
    次要势力（刘表/刘璋/张鲁/马超）使用启发式规则。
    """
    from .faction_slot import create_human_slot

    room = GameRoom(scenario=scenario)
    room.slots[faction_id] = create_human_slot(faction_id, user_id)

    # 其他主要势力 → AI NPC
    for fid in LLM_NPC_FACTIONS:
        if fid != faction_id:
            room.slots[fid] = create_ai_slot(fid)

    # 次要势力 → AI NPC（启发式）
    for fid in HEURISTIC_NPC_FACTIONS:
        room.slots[fid] = create_ai_slot(fid)

    room.phase = RoomPhase.WAITING
    return room


def create_multi_player_room(
    host_user_id: str,
    faction_ids: list[str],
    scenario: str = "207",
) -> GameRoom:
    """创建多人模式的 GameRoom。

    指定势力设为 OPEN 等待玩家加入，其余设为 AI NPC。
    """
    room = GameRoom(host_user_id=host_user_id, scenario=scenario)

    # 指定势力 → OPEN（等待玩家加入）
    for fid in faction_ids:
        room.slots[fid] = create_open_slot(fid)

    # 未指定势力 → AI NPC
    all_factions = set(LLM_NPC_FACTIONS) | set(HEURISTIC_NPC_FACTIONS)
    for fid in all_factions:
        if fid not in room.slots:
            room.slots[fid] = create_ai_slot(fid)

    # 如果 host 自己也选了势力，立即加入
    room.phase = RoomPhase.LOBBY
    return room
