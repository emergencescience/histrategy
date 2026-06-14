"""
V1 纯 LLM 仿真引擎 — deepseek-v4-pro 直接推演世界状态。

V1 不做任何确定性计算，所有状态变化由单次 LLM 调用完成。
输入：所有势力状态 + 全部指令
输出：新状态 + 叙事 + 事件

Usage:
    engine = V1Simulator(llm)
    result = engine.simulate(world_state, faction_decisions, turn_memory)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState

    from histrategy.llm.adapter import LLMAdapter

logger = logging.getLogger("histrategy.v1")

# 加载系统提示词
_PROMPT_DIR = Path(__file__).parent.parent / "llm" / "prompts"
_SYSTEM_PROMPT = (_PROMPT_DIR / "v1_simulator.md").read_text(encoding="utf-8")


def _build_context(
    ws: WorldState,
    faction_decisions: dict[str, dict],
    turn_memory: list[dict],
) -> str:
    """构建 V1 仿真上下文。

    将世界状态和所有势力决策打包为 LLM 可理解的文本。
    不做战争迷雾 — 所有信息公开。
    """
    parts: list[str] = []

    # 1. 当前世界状态
    parts.append("## 当前世界状态\n")
    for fid, faction in ws.factions.items():
        if not faction.is_active:
            continue
        territories_str = (
            "、".join([ws.territories[tid].name for tid in faction.territories if tid in ws.territories]) or "无领地"
        )
        parts.append(
            f"### {faction.name} ({fid})\n"
            f"- 城池: {territories_str}\n"
            f"- 人口: {getattr(faction, 'population', '?')}\n"
            f"- 兵力: {getattr(faction, 'strength_actual', 0)}\n"
            f"- 粮草: {faction.food}\n"
            f"- 库金: {faction.treasury}\n"
            f"- 民心: {getattr(faction, 'morale_actual', 50)}\n"
            f"- 税率: {int(getattr(faction, 'tax_rate', 0.3) * 100)}%\n"
        )
        # 当前生效的政策
        policies = getattr(faction, "policies", {})
        if policies:
            policy_lines = [f"- 政策: {json.dumps(policies, ensure_ascii=False)}"]
            parts.append("\n".join(policy_lines))

    # 2. 各势力决策
    parts.append("\n## 本季度决策\n")
    for fid, decision_info in faction_decisions.items():
        faction = ws.factions.get(fid)
        name = faction.name if faction else fid
        decision_text = decision_info.get("decision", "") if isinstance(decision_info, dict) else str(decision_info)
        commands = decision_info.get("commands", []) if isinstance(decision_info, dict) else []

        parts.append(f"### {name} ({fid})\n决策: {decision_text}")
        if commands:
            parts.append("结构化命令: " + json.dumps(commands, ensure_ascii=False))

    # 3. 回合记忆（最近几轮摘要）
    if turn_memory:
        parts.append("\n## 历史摘要\n")
        for i, summary in enumerate(turn_memory[-4:]):
            parts.append(f"Q{summary.get('quarter', i + 1)}: {json.dumps(summary, ensure_ascii=False)}")

    return "\n".join(parts)


class V1Simulator:
    """V1 纯 LLM 仿真引擎。

    与 V3 的混合引擎不同，V1 不做任何确定性计算。
    世界状态完全由 LLM 推理生成。
    """

    def __init__(self, llm: LLMAdapter | None = None):
        self.llm = llm
        self._available = llm is not None and llm.is_available

    @property
    def is_available(self) -> bool:
        return self._available

    def simulate(
        self,
        ws: WorldState,
        faction_decisions: dict[str, dict],
        turn_memory: list[dict] | None = None,
        room_id: str = "",
        quarter_number: int = 0,
    ) -> dict:
        """Execute V1 simulation — single LLM call handles all state evolution.

        Args:
            ws: Current world state
            faction_decisions: {faction_id: {decision: str, commands: list}}
            turn_memory: Turn memory (recent round summaries)
            room_id: Game room ID for DB logging
            quarter_number: Current quarter for DB logging

        Returns:
            {
                "narrative": str,
                "factions": dict,
                "events": list[str],
                "battles": list[dict],
                "diplomacy": list[dict],
                "knowledge_cards": list[dict],
                "token_usage": dict,
            }
        """
        if not self.is_available:
            return self._fallback(ws, faction_decisions)

        context = _build_context(ws, faction_decisions, turn_memory or [])

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        try:
            response = self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=16384,
                metadata={
                    "category": "v1_simulate",
                    "room_id": room_id,
                    "quarter_number": quarter_number,
                },
            )
            result = self._parse_response(response)
            result["token_usage"] = {
                "prompt_tokens": len(context) // 3,  # rough estimate
                "completion_tokens": len(response) // 3,
                "total_tokens": (len(context) + len(response)) // 3,
            }

            # ── Log simulation events to DB (H14b) ──
            if room_id:
                self._log_sim_events_to_db(room_id, quarter_number, result)

            return result
        except Exception as e:
            logger.error(f"V1 simulation failed: {e}")
            return self._fallback(ws, faction_decisions)

    @staticmethod
    def _log_sim_events_to_db(room_id: str, quarter_number: int, result: dict) -> None:
        """Log simulation events (battles, diplomacy, events) to the DB."""
        try:
            from histrategy.db.models import log_sim_event

            # Log events (black swans, natural disasters, etc.)
            for event_text in result.get("events", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="black_swan" if "灾" in event_text or "祸" in event_text or "变" in event_text else "state_mutation",
                    event_data={"description": event_text},
                )

            # Log battles
            for battle in result.get("battles", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="baseline",
                    event_data={"type": "battle", "info": battle},
                )

            # Log diplomacy
            for dip in result.get("diplomacy", []):
                log_sim_event(
                    room_id=room_id,
                    quarter_number=quarter_number,
                    event_type="baseline",
                    event_data={"type": "diplomacy", "info": dip},
                )
        except Exception as e:
            logger.warning(f"Failed to log sim events to DB: {e}")

    def _parse_response(self, response: str) -> dict:
        """解析 LLM 输出的 JSON。"""
        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        text = response.strip()

        # 去掉 ```json ... ``` 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个完整的 JSON 对象
            brace_start = text.find("{")
            brace_count = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    brace_count += 1
                elif text[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except json.JSONDecodeError:
                            break
            logger.warning(f"V1: failed to parse LLM response (len={len(response)}), using fallback")
            return {
                "narrative": "V1 解析失败",
                "factions": {},
                "events": [],
                "battles": [],
                "diplomacy": [],
                "knowledge_cards": [],
            }

    def _fallback(self, ws: WorldState, faction_decisions: dict) -> dict:
        """V1 不可用时的回退：简单确定性计算。"""
        factions = {}
        for fid, faction in ws.factions.items():
            if not faction.is_active:
                continue
            factions[fid] = {
                "population": getattr(faction, "population", 0),
                "troops": getattr(faction, "strength_actual", 0),
                "food": faction.food,
                "treasury": faction.treasury,
                "morale": getattr(faction, "morale_actual", 50),
                "territories": [
                    {"id": tid, "name": ws.territories[tid].name if tid in ws.territories else tid}
                    for tid in faction.territories
                ],
                "policies": {},
                "is_active": True,
            }
        return {
            "narrative": "（离线模式：无 LLM 可用，状态未变化）",
            "factions": factions,
            "events": [],
            "battles": [],
            "diplomacy": [],
            "knowledge_cards": [],
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


# ── V1 状态写入 DB ──────────────────────────────────


def _apply_v1_state_to_world(ws: WorldState, v1_factions: dict) -> WorldState:
    """将 V1 输出的状态写回 WorldState。

    V1 输出的是 JSON dict，需要小心地映射回 WorldState 对象。
    只更新数值字段，不改变结构。
    """
    for fid, data in v1_factions.items():
        if fid not in ws.factions:
            continue
        faction = ws.factions[fid]

        # 数值更新
        if "population" in data:
            faction.population = data["population"]
        if "troops" in data:
            faction.strength_actual = data["troops"]
        if "food" in data:
            faction.food = data["food"]
        if "treasury" in data:
            faction.treasury = data["treasury"]
        if "morale" in data:
            faction.morale_actual = data["morale"]
        if "policies" in data:
            faction.policies = data["policies"]
        if "is_active" in data:
            faction.is_active = data["is_active"]

        # 城池易手
        if "territories" in data:
            new_territory_ids = [t["id"] if isinstance(t, dict) else t for t in data["territories"]]
            # 城池易手：新占城池从原所有者移除
            for tid in new_territory_ids:
                if tid not in faction.territories:
                    # 从原所有者移除
                    for other_fid, other_f in ws.factions.items():
                        if other_fid != fid and tid in other_f.territories:
                            other_f.territories.remove(tid)
            faction.territories = new_territory_ids

    return ws


def save_v1_state_to_db(
    room_id: str,
    quarter_number: int,
    ws: WorldState,
    v1_result: dict,
    old_state: dict | None = None,
):
    """将 V1 仿真结果写入数据库（game_state + turn_delta + policy_state）。

    Args:
        old_state: 仿真前的状态快照 {fid: {population, troops, food, treasury, morale}}
                   用于计算 turn_delta。若为 None 则跳过 delta 写入。
    """
    try:
        from histrategy.db.models import save_game_state, save_policy_state, save_turn_delta
        from histrategy.engine.faction_slot import LLM_NPC_FACTIONS

        for fid, data in v1_result.get("factions", {}).items():
            # Only save tracked factions (cao/shu/wu + player's faction)
            if fid not in LLM_NPC_FACTIONS and fid not in (old_state or {}):
                continue
            faction = ws.factions.get(fid)
            if not faction:
                continue

            # ── 保存完整状态快照 (game_state) ──
            save_game_state(
                room_id=room_id,
                quarter_number=quarter_number,
                faction_id=fid,
                population=data.get("population", 0),
                troops=data.get("troops", 0),
                food=data.get("food", 0),
                treasury=data.get("treasury", 0),
                morale=data.get("morale", 50),
                territories=data.get("territories", []),
                policies=data.get("policies", {}),
                is_active=data.get("is_active", True),
            )

            # ── 保存五项增量 (turn_delta) ──
            if old_state and fid in old_state:
                old = old_state[fid]
                delta_map = [
                    ("population", old.get("population", 0), data.get("population", 0)),
                    ("troops", old.get("troops", 0), data.get("troops", 0)),
                    ("food", old.get("food", 0), data.get("food", 0)),
                    ("treasury", old.get("treasury", 0), data.get("treasury", 0)),
                    ("morale", old.get("morale", 50), data.get("morale", 50)),
                ]
                for delta_type, old_val, new_val in delta_map:
                    if old_val == new_val:
                        continue  # 跳过无变化项
                    save_turn_delta(
                        room_id=room_id,
                        quarter_number=quarter_number,
                        faction_id=fid,
                        delta_type=delta_type,
                        old_value=old_val,
                        new_value=new_val,
                        reason="V1 LLM simulation",
                        source="llm",
                    )

            # ── 保存政策变更 (policy_state) ──
            policies = data.get("policies", {})
            if policies:
                for policy_name, policy_info in policies.items():
                    if isinstance(policy_info, dict):
                        save_policy_state(
                            room_id=room_id,
                            quarter_number=quarter_number,
                            faction_id=fid,
                            policy_type=policy_info.get("type", "law"),
                            policy_name=policy_name,
                            policy_level=policy_info.get("level", 1),
                            params=policy_info.get("params", {}),
                            status=policy_info.get("status", "active"),
                        )

    except Exception as e:
        logger.warning(f"V1 DB save failed (non-fatal): {e}")
