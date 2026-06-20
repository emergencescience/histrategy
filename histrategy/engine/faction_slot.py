"""
对称势力槽位 — 人类玩家和AI NPC使用完全相同的FactionSlot数据模型。

这是对称多人引擎的核心抽象。FactionSlot不区分人类还是AI——
它只是一个"谁来控制这个势力"的槽位。人类打字提交决策，AI通过LLM生成决策，
但对引擎而言，两者都是"提交了一个decision"。

OccupantType:
    HUMAN  — 人类玩家通过API/UI提交决策
    AI_NPC — AI通过NPCDecisionEngine独立LLM调用生成决策
    OPEN   — 等待人类加入（仅大厅阶段）

NPC数量限制：
    主要势力 (cao/shu/wu) 使用LLM独立决策
    次要势力 (liubiao/liuzhang/machao/zhanglu) 使用启发式规则
    防止过多LLM调用导致行为偏离历史和成本膨胀
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OccupantType(Enum):
    HUMAN = "human"
    AI_NPC = "ai_npc"
    OPEN = "open"


# ── 势力 ID 映射 ────────────────────────────────────
# 用户界面使用全名（caocao/liubei/sunquan），内部引擎使用短ID（cao/shu/wu）
# 这是 histrategy_engine pip 包使用的 faction ID，不能改
FACTION_DISPLAY_TO_ID: dict[str, str] = {
    "caocao": "cao",
    "liubei": "shu",
    "sunquan": "wu",
}
FACTION_ID_TO_DISPLAY: dict[str, str] = {v: k for k, v in FACTION_DISPLAY_TO_ID.items()}

# 三大势力（cao/shu/wu 作为内部 ID，caocao/liubei/sunquan 作为显示名）
# 只有这三大势力使用 LLM 独立决策（Three Kingdoms 默认）
LLM_NPC_FACTIONS = {"cao", "shu", "wu", "liuzhang"}
LLM_NPC_DISPLAY = {"caocao", "liubei", "sunquan"}

# 场景感知的 NPC 势力映射（非 TK 场景的 NPC 势力从场景配置动态加载，
# 此映射仅作为 room_manager 中 create_room 的 fallback）
SCENARIO_NPC_FACTIONS: dict[str, set[str]] = {
    "rome-triumvirate": {"senate", "octavian", "antony", "cleopatra"},
}

def get_npc_factions(scenario: str) -> set[str]:
    """返回指定场景的 LLM NPC 势力集合（场景感知）。"""
    return SCENARIO_NPC_FACTIONS.get(scenario, LLM_NPC_FACTIONS)

# 用户可见的势力列表（全名）
PLAYABLE_FACTIONS = ["caocao", "liubei", "sunquan"]


@dataclass
class FactionSlot:
    """对称的势力槽位。

    无论occupant_type是HUMAN还是AI_NPC，状态机完全对称：
    1. 等待决策 → pending_decision = None
    2. 提交决策 → pending_decision = "..." + pending_commands = [...]
    3. 季度执行 → 清空pending，推进到下一季度
    """

    faction_id: str  # "cao" | "shu" | "wu" | "liubiao" | ...
    occupant_type: OccupantType = OccupantType.OPEN
    occupant_id: str | None = None  # user_id (HUMAN) | None (AI/OPEN)

    # AI NPC 配置
    ai_model: str | None = None  # LLM model override
    ai_temperature: float = 0.7  # 创造性温度

    # 当前季度决策
    pending_decision: str | None = None  # 原始自然语言决策
    pending_commands: list | None = None  # 解析后的结构化命令 (list[Command])

    # 状态
    is_active: bool = True

    def __post_init__(self):
        if isinstance(self.occupant_type, str):
            self.occupant_type = OccupantType(self.occupant_type)

    # ── 类型判断 ──────────────────────────────────

    def is_human(self) -> bool:
        return self.occupant_type == OccupantType.HUMAN

    def is_ai(self) -> bool:
        return self.occupant_type == OccupantType.AI_NPC

    def is_open(self) -> bool:
        return self.occupant_type == OccupantType.OPEN

    # ── 决策状态 ──────────────────────────────────

    def has_submitted(self) -> bool:
        """本季度是否已提交决策。"""
        return self.pending_decision is not None

    def submit_decision(self, decision: str, commands: list | None = None):
        """提交本季度决策。"""
        self.pending_decision = decision
        self.pending_commands = commands

    def clear_decision(self):
        """清空本季度决策（季度推进后调用）。"""
        self.pending_decision = None
        self.pending_commands = None

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "faction_id": self.faction_id,
            "occupant_type": self.occupant_type.value,
            "occupant_id": self.occupant_id,
            "ai_model": self.ai_model,
            "ai_temperature": self.ai_temperature,
            "is_active": self.is_active,
            "pending_decision": self.pending_decision,
            "pending_commands": self.pending_commands,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FactionSlot:
        slot = cls(
            faction_id=data["faction_id"],
            occupant_type=OccupantType(data.get("occupant_type", "open")),
            occupant_id=data.get("occupant_id"),
            ai_model=data.get("ai_model"),
            ai_temperature=data.get("ai_temperature", 0.7),
            is_active=data.get("is_active", True),
        )
        # 恢复已提交的决策（服务器重启后不丢失 NPC/人类提交的决策）
        slot.pending_decision = data.get("pending_decision")
        slot.pending_commands = data.get("pending_commands")
        return slot

    def __repr__(self) -> str:
        occupant = f"{self.occupant_type.value}:{self.occupant_id or '?'}"
        status = "⌛" if not self.has_submitted() else "✓"
        return f"FactionSlot({self.faction_id}, {occupant}, {status})"


# ── 工厂函数 ──────────────────────────────────────


def create_human_slot(faction_id: str, user_id: str) -> FactionSlot:
    """创建一个人类玩家槽位。"""
    return FactionSlot(
        faction_id=faction_id,
        occupant_type=OccupantType.HUMAN,
        occupant_id=user_id,
    )


def create_ai_slot(faction_id: str, temperature: float = 0.7) -> FactionSlot:
    """创建一个AI NPC槽位。

    默认使用LLM独立决策（主要势力），次要势力由调用方
    决定是否降级为启发式规则。
    """
    return FactionSlot(
        faction_id=faction_id,
        occupant_type=OccupantType.AI_NPC,
        ai_temperature=temperature,
    )


def create_open_slot(faction_id: str) -> FactionSlot:
    """创建一个等待玩家加入的开放槽位。"""
    return FactionSlot(
        faction_id=faction_id,
        occupant_type=OccupantType.OPEN,
    )
