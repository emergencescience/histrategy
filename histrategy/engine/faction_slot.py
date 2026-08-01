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
    主要势力 (cao/shu/wu / octavian/antony/cleopatra/senate) 使用LLM独立决策
    次要势力 (liubiao/yuanshao/liuzhang/dongzhuo) 使用启发式规则
    防止过多LLM调用导致行为偏离历史和成本膨胀

histrategy 不追踪 user_id —— 身份由 orchestrator 代理层处理。
势力槽位仅通过 faction_id 识别「谁在控制这个势力」。

Faction ID 命名约定（统一后）：
    内部引擎统一使用短码：
      三國志略: cao, shu, wu, liubiao, yuanshao, liuzhang, dongzhuo
      Rome:     octavian, antony, cleopatra, senate, sextus_pompey, lepidus,
                decimus_brutus, cassius_brutus
    FACTION_DISPLAY_TO_ID 映射旧名 (caocao→cao, liubei→shu, wei→cao 等) 保证向后兼容。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OccupantType(Enum):
    HUMAN = "human"
    AI_NPC = "ai_npc"
    OPEN = "open"


# ── 势力 ID 映射（canonical source of truth）─────────────────
# 内部引擎统一使用短码 (cao/shu/wu/octavian/antony...)。
# 用户界面和 API 接受全名 (caocao/liubei/sunquan)，
# 通过 FACTION_DISPLAY_TO_ID 映射到内部 ID。
FACTION_DISPLAY_TO_ID: dict[str, str] = {
    "caocao": "cao",
    "liubei": "shu",
    "sunquan": "wu",
    # Underscore variants (API sends "liu_bei" not "liubei")
    "cao_cao": "cao",
    "liu_bei": "shu",
    "sun_quan": "wu",
    # Alternate / legacy names
    "wei": "cao",
    "sunjian": "wu",
}
FACTION_ID_TO_DISPLAY: dict[str, str] = {v: k for k, v in FACTION_DISPLAY_TO_ID.items()}

# 统一 legacy → canonical 映射（供 offline_sim_engine / game.py 等模块引用）
FACTION_LEGACY_MAP: dict[str, str] = {
    "caocao": "cao",
    "liubei": "shu",
    "sunquan": "wu",
    "sunjian": "wu",
    "wei": "cao",
}

# ── 势力显示名 → ID 映射（供 IntentParser 使用）────────────────
# Canonical source of truth for faction name resolution.
# Includes Chinese display names, short forms, and pinyin IDs.
FACTION_NAME_MAP: dict[str, str] = {
    "曹操": "cao",
    "曹军": "cao",
    "曹": "cao",
    "cao": "cao",
    "刘备": "shu",
    "刘军": "shu",
    "刘": "shu",
    "蜀": "shu",
    "shu": "shu",
    "孙权": "wu",
    "孙军": "wu",
    "孙": "wu",
    "吴": "wu",
    "wu": "wu",
    "刘表": "liubiao",
    "liubiao": "liubiao",
    "袁绍": "yuanshao",
    "yuanshao": "yuanshao",
    "董卓": "dongzhuo",
    "dongzhuo": "dongzhuo",
}

# ── 城池名 → ID 映射（供 IntentParser 使用）────────────────
# Maps Chinese territory names and pinyin IDs to canonical territory IDs.
TERRITORY_NAME_MAP: dict[str, str] = {
    # 曹操领地
    "许昌": "xuchang",
    "xuchang": "xuchang",
    "洛阳": "luoyang",
    "luoyang": "luoyang",
    "邺城": "ye",
    "邺": "ye",
    "ye": "ye",
    "宛城": "wancheng",
    "wancheng": "wancheng",
    "常山": "changshan",
    "changshan": "changshan",
    "蓟县": "ji",
    "蓟": "ji",
    "ji": "ji",
    "濮阳": "puyang",
    "puyang": "puyang",
    "北海": "beihai",
    "beihai": "beihai",
    "下邳": "xiapi",
    "xiapi": "xiapi",
    # 刘备领地
    "新野": "xinye",
    "xinye": "xinye",
    "平原": "pingyuan",
    "pingyuan": "pingyuan",
    # 孙权领地
    "建业": "jianye",
    "建業": "jianye",
    "jianye": "jianye",
    "吴郡": "wu",
    "吳郡": "wu",
    "会稽": "kuaiji",
    "會稽": "kuaiji",
    "kuaiji": "kuaiji",
    "柴桑": "chaisang",
    "chaisang": "chaisang",
    "庐江": "lujiang",
    "廬江": "lujiang",
    "lujiang": "lujiang",
    "豫章": "yuzhang",
    "yuzhang": "yuzhang",
    "丹阳": "danyang",
    "danyang": "danyang",
    # 刘表领地
    "襄阳": "xiangyang",
    "襄陽": "xiangyang",
    "xiangyang": "xiangyang",
    "江陵": "jiangling",
    "jiangling": "jiangling",
    "长沙": "changsha",
    "長沙": "changsha",
    "changsha": "changsha",
    "江口": "jiangkou",
    "jiangkou": "jiangkou",
    # 刘璋领地
    "成都": "chengdu",
    "chengdu": "chengdu",
}


def normalize_faction_id(fid: str) -> str:
    """归一化 faction_id：legacy 名 → canonical 短码。"""
    return FACTION_LEGACY_MAP.get(fid, fid)


# Three Kingdoms 主要 NPC 势力（LLM 独立决策）
# liubiao/yuanshao/liuzhang/dongzhuo 是纯 NPC，使用启发式规则，不用 LLM
LLM_NPC_FACTIONS = {"cao", "shu", "wu"}
LLM_NPC_DISPLAY = {"caocao", "liubei", "sunquan"}

# 单人模式 / 默认 AI NPC 势力（包括启发式次要势力）
DEFAULT_AI_FACTIONS = {"cao", "shu", "wu", "liuzhang"}

# 场景感知的 NPC 势力映射
SCENARIO_NPC_FACTIONS: dict[str, set[str]] = {
    "rome-triumvirate": {"senate", "octavian", "antony", "cleopatra"},
}


def get_npc_factions(scenario: str) -> set[str]:
    """返回指定场景的 LLM NPC 势力集合（场景感知）。"""
    return SCENARIO_NPC_FACTIONS.get(scenario, LLM_NPC_FACTIONS)


# 用户可见的势力列表（内部短码，API 层通过 FACTION_ID_TO_DISPLAY 转为显示名）
PLAYABLE_FACTIONS = ["cao", "shu", "wu"]


@dataclass
class FactionSlot:
    """对称的势力槽位。

    无论occupant_type是HUMAN还是AI_NPC，状态机完全对称：
    1. 等待决策 → pending_decision = None
    2. 提交决策 → pending_decision = "..." + pending_commands = [...]
    3. 季度执行 → 清空pending，推进到下一季度

    histrategy 不追踪 user_id —— 身份由 orchestrator 处理。
    势力槽位仅通过 faction_id 识别控制者。
    """

    faction_id: str  # "cao" | "shu" | "wu" | "liubiao" | ...
    occupant_type: OccupantType = OccupantType.OPEN
    display_name: str = ""  # human-readable name (e.g. "曹操")

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
            "display_name": self.display_name,
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
            display_name=data.get("display_name", ""),
            ai_model=data.get("ai_model"),
            ai_temperature=data.get("ai_temperature", 0.7),
            is_active=data.get("is_active", True),
        )
        # 恢复已提交的决策（服务器重启后不丢失 NPC/人类提交的决策）
        slot.pending_decision = data.get("pending_decision")
        slot.pending_commands = data.get("pending_commands")
        return slot

    def __repr__(self) -> str:
        occupant = f"{self.occupant_type.value}"
        status = "⌛" if not self.has_submitted() else "✓"
        return f"FactionSlot({self.faction_id}, {occupant}, {status})"


# ── 工厂函数 ──────────────────────────────────────


def create_human_slot(faction_id: str, display_name: str = "") -> FactionSlot:
    """创建一个人类玩家槽位。histrategy 不追踪 user_id。"""
    return FactionSlot(
        faction_id=faction_id,
        occupant_type=OccupantType.HUMAN,
        display_name=display_name,
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
