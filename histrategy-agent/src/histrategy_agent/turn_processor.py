"""
TurnProcessor — processes one game turn end-to-end.

Pipeline: player input → intent parse → validate → execute → narrative → suggestions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from histrategy_engine import Command, WorldState

from .session import GameSession
from .state_bridge import StateBridge


@dataclass
class TurnResult:
    """Output of processing one turn."""

    narrative: str  # LLM-generated narrative text
    world_snapshot: dict  # Key facts about current world state
    suggestions: list[str]  # 3-5 suggested next actions
    events: list[str]  # Notable events this turn
    map_ascii: str  # ASCII art map (or empty)
    raw_world_state: WorldState  # Updated world state (for saving)


class TurnProcessor:
    """Processes one turn: player input → engine execution → narrative → output."""

    def __init__(self, llm_adapter=None):
        """llm_adapter: optional LLM client for narrative generation.
        If None, uses offline fallback narrative."""
        self.llm_adapter = llm_adapter

    def process(self, session: GameSession, player_input: str) -> TurnResult:
        """Full pipeline:
        1. Parse intent from player_input
        2. Validate against game rules
        3. Execute via StateBridge
        4. Generate narrative (LLM or fallback)
        5. Build suggestions
        6. Return TurnResult
        """
        bridge = StateBridge(session.world_state)
        intent = self._parse_intent(player_input)

        # Execute the command
        command = Command(
            type=intent["action"],
            params=intent.get("params", {}),
            faction_id=session.player_faction_id,
        )

        result = bridge.execute_command(command)

        # Advance NPC factions
        npc_actions = bridge.advance_npc_factions()

        # Build events list
        events = []
        if result.get("message"):
            events.append(result["message"])
        for na in npc_actions:
            for action in na.get("actions", []):
                events.append(f"{na['faction_name']}: {action}")

        # Generate narrative
        narrative = self._generate_narrative(intent, result, npc_actions)

        # Build suggestions
        suggestions = self._build_suggestions(session.world_state, session.player_faction_id)

        # Get world snapshot
        world_snapshot = bridge.get_world_snapshot(session.player_faction_id)

        # Generate map (deferred to format_engine for rendering)
        map_ascii = ""

        # Update session
        session.turn_number += 1
        session.world_state.turn_number = session.turn_number

        # Advance season (simplified: every 2 turns = 1 season)
        seasons = list(Season)
        current_idx = seasons.index(session.world_state.season)
        if session.turn_number % 2 == 0:
            next_idx = (current_idx + 1) % 4
            session.world_state.season = seasons[next_idx]
            if next_idx == 0:  # back to spring → new year
                session.world_state.year += 1

        return TurnResult(
            narrative=narrative,
            world_snapshot=world_snapshot,
            suggestions=suggestions,
            events=events,
            map_ascii=map_ascii,
            raw_world_state=session.world_state,
        )

    def _parse_intent(self, text: str) -> dict:
        """Simple intent parser using keyword matching.

        Returns {"action": "attack"/"recruit"/"move"/"develop"/"diplomacy"/"info"/"unknown",
                 "target": ..., "params": ...}
        """
        text_lower = text.lower().strip()

        # Info / status
        if any(kw in text for kw in ["状态", "情报", "status", "info", "查看", "天下大势"]):
            return {"action": "info", "target": "", "params": {}}

        # Attack
        if any(kw in text for kw in ["进攻", "攻击", "打", "attack", "攻", "攻打", "征讨"]):
            target = self._extract_territory(text)
            return {
                "action": "attack",
                "target": target,
                "params": {"target": target},
            }

        # Recruit
        if any(kw in text for kw in ["招募", "征兵", "recruit", "征", "招"]):
            unit_type = "infantry"
            if any(kw in text for kw in ["骑兵", "cavalry", "骑"]):
                unit_type = "cavalry"
            elif any(kw in text for kw in ["弓兵", "archer", "弓"]):
                unit_type = "archer"
            elif any(kw in text for kw in ["水军", "navy", "水"]):
                unit_type = "navy"
            elif any(kw in text for kw in ["步兵", "infantry", "步"]):
                unit_type = "infantry"
            amount = self._extract_number(text) or 1000
            return {
                "action": "recruit",
                "target": unit_type,
                "params": {"unit_type": unit_type, "amount": amount},
            }

        # Move
        if any(kw in text for kw in ["移动", "前往", "进军", "move", "移", "去"]):
            target = self._extract_territory(text)
            return {
                "action": "move",
                "target": target,
                "params": {"target": target},
            }

        # Develop
        if any(kw in text for kw in ["开发", "发展", "develop", "建设"]):
            target = self._extract_territory(text)
            return {
                "action": "develop",
                "target": target,
                "params": {"target": target},
            }

        # Diplomacy
        if any(kw in text for kw in ["结盟", "外交", "联盟", "ally", "同盟"]):
            target = self._extract_faction(text)
            return {
                "action": "diplomacy",
                "target": target,
                "params": {"target": target, "action": "ally"},
            }

        # Diplomacy — break alliance
        if any(kw in text for kw in ["断交", "毁约", "解盟"]):
            target = self._extract_faction(text)
            return {
                "action": "diplomacy",
                "target": target,
                "params": {"target": target, "action": "break_ally"},
            }

        # Tax
        if any(kw in text for kw in ["税收", "征税", "税率", "税"]):
            import re
            rate_match = re.search(r"(\d+)%", text)
            rate = int(rate_match.group(1)) / 100.0 if rate_match else 0.3
            return {
                "action": "tax",
                "target": "",
                "params": {"rate": rate},
            }

        # Unknown — let caller decide (LLM handles later)
        return {"action": "unknown", "target": "", "params": {"raw_text": text}}

    def _extract_territory(self, text: str) -> str:
        """Extract territory name from text."""
        territory_keywords = {
            "新野": "xinye", "宛城": "wancheng", "许昌": "xuchang",
            "洛阳": "luoyang", "邺城": "ye", "蓟县": "ji",
            "襄阳": "xiangyang", "江陵": "jiangling", "成都": "chengdu",
            "汉中": "hanshui", "建业": "jianye", "柴桑": "chaisang",
            "吴郡": "wu", "下邳": "xiapi",
        }
        for cn_name, tid in territory_keywords.items():
            if cn_name in text:
                return tid
        return ""

    def _extract_number(self, text: str) -> int | None:
        """Extract a number from text."""
        import re
        match = re.search(r"(\d+)", text)
        if match:
            n = int(match.group(1))
            return n if 0 < n < 100000 else None
        return None

    def _extract_faction(self, text: str) -> str:
        """Extract faction ID from text."""
        faction_keywords = {
            "刘备": "shu", "蜀": "shu", "shu": "shu",
            "曹操": "cao", "曹": "cao", "魏": "cao", "cao": "cao",
            "孙权": "wu", "吴": "wu", "东吴": "wu", "wu": "wu",
            "刘表": "liubiao", "荆州": "liubiao",
            "刘璋": "liuzhang", "益州": "liuzhang", "西川": "liuzhang",
        }
        for kw, fid in faction_keywords.items():
            if kw in text:
                return fid
        return ""

    def _generate_narrative(
        self, intent: dict, result: dict, npc_actions: list[dict]
    ) -> str:
        """Generate narrative — uses LLM if available, otherwise offline."""
        if self.llm_adapter:
            return self._llm_narrative(intent, result, npc_actions)
        return self._offline_narrative(intent, result)

    def _llm_narrative(self, intent: dict, result: dict, npc_actions: list[dict]) -> str:
        """Generate narrative with LLM. Stub for now."""
        return self._offline_narrative(intent, result)

    def _offline_narrative(self, action: dict, result: dict) -> str:
        """Generate simple narrative without LLM."""
        action_type = action.get("action", "unknown")
        msg = result.get("message", "")

        templates = {
            "attack": (
                f"我军发起进攻！{msg}。将士们奋勇冲杀，战场烟尘蔽日。"
                if result.get("success") else
                f"进攻计划受阻。{msg}"
            ),
            "recruit": (
                f"征兵令下，{msg}。新兵们整装待发，准备为统一天下而战。"
                if result.get("success") else
                f"招募失败。{msg}"
            ),
            "move": (
                f"大军开拔，{msg}。沿途百姓夹道相迎。"
                if result.get("success") else
                f"进军受阻。{msg}"
            ),
            "develop": (
                f"发展内政，{msg}。百姓安居乐业，国力日渐强盛。"
                if result.get("success") else
                f"开发失败。{msg}"
            ),
            "diplomacy": (
                f"使者奉命出使，{msg}。"
                if result.get("success") else
                f"外交行动失败。{msg}"
            ),
            "tax": (
                f"调整税收，{msg}。"
                if result.get("success") else
                f"税收调整失败。{msg}"
            ),
            "info": "天下大势，分久必合，合久必分。查看当前局势。",
            "unknown": "使者不解主公之意，请明示具体指令。",
        }
        return templates.get(action_type, f"执行完成。{msg}")

    def _build_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        """Generate 3-5 contextual suggestions based on current state."""
        suggestions = []
        faction = world_state.factions.get(faction_id)
        if not faction:
            return ["查看天下大势", "休整一回合"]

        # Military assessment
        total_troops = sum(
            a.total_troops for a in world_state.armies.values()
            if a.faction_id == faction_id
        )

        if total_troops < 5000:
            suggestions.append("招募步兵充实兵力")

        # Check for adjacent enemies
        for tid in faction.territories:
            territory = world_state.territories.get(tid)
            if not territory:
                continue
            for nid in territory.neighbors:
                neighbor = world_state.territories.get(nid)
                if neighbor and neighbor.owner_id and neighbor.owner_id != faction_id:
                    rel = faction.relations.get(neighbor.owner_id, 0)
                    if rel < 0:
                        nf = world_state.factions.get(neighbor.owner_id)
                        target_name = nf.name if nf else neighbor.owner_id
                        suggestions.append(f"进攻{neighbor.name}夺取领土")
                        break
            if len(suggestions) > 1:
                break

        # Food assessment
        if faction.food < 3000:
            suggestions.append("开发农业提高粮食产量")

        # Diplomacy suggestion
        for fid, rel in faction.relations.items():
            if -20 <= rel <= 30 and fid != faction_id:
                target = world_state.factions.get(fid)
                if target and target.is_active:
                    suggestions.append(f"与{target.name}结盟共抗强敌")
                    break

        # Always include these
        if "查看天下大势" not in suggestions:
            suggestions.append("查看天下大势")
        suggestions.append("休整一回合")

        # Ensure we have exactly 3-5
        while len(suggestions) < 3:
            suggestions.append("查看天下大势")
            break

        return suggestions[:5]


# Need Season import at module level
from histrategy_engine import Season
