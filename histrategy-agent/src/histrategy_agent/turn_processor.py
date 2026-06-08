"""
TurnProcessor — processes one game turn end-to-end.

Pipeline:
  player input → LLM intent parse (or keyword fallback)
  → validate → execute → LLM narrative (or template fallback)
  → LLM suggestions (or heuristic fallback)

When LLM is unavailable, falls back to keyword parsing and template narratives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from histrategy_engine import Command, Season, WorldState

from .session import GameSession
from .state_bridge import StateBridge
from .llm_adapter import get_llm


@dataclass
class TurnResult:
    """Output of processing one turn."""
    narrative: str
    world_snapshot: dict
    suggestions: list[str]
    events: list[str]
    map_ascii: str
    raw_world_state: WorldState


# ─── LLM System Prompts ────────────────────────────────

INTENT_SYSTEM = """你是《三國志略》的意图解析器。将玩家的自然语言输入解析为游戏指令。

## 指令类型
- attack: 进攻/攻击/征讨某地
- recruit: 招募/征兵（可指定兵种：步兵/infantry 骑兵/cavalry 弓兵/archer 水军/navy，数量默认1000）
- move: 移动/进军到某地
- develop: 开发/发展/建设/贸易/整顿某地
- diplomacy: 外交行动（结盟ally/断交break_ally/和亲marry）
- tax: 调整税收/税率
- info: 查看状态/情报/天下大势

## 领地ID
xinye=新野, wancheng=宛城, xuchang=许昌, luoyang=洛阳, ye=邺城, ji=蓟县,
xiangyang=襄阳, jiangling=江陵, chengdu=成都, hanshui=汉中,
jianye=建业, chaisang=柴桑, wu=吴郡, xiapi=下邳

## 势力ID（重要：玩家不能与自己的势力互动）
shu=刘备, cao=曹操, wu=孙权, liubiao=刘表, liuzhang=刘璋

## 核心规则
- **永远不要返回玩家自己的势力ID作为target**（如刘表玩家不能target=liubiao）
- 如果玩家描述宏观战略，提取其中最具体的一条可执行行动
- 「保境安民」→ develop，「扩充军队」→ recruit，「操练水军」→ recruit navy
- 「与X结亲/和亲」→ diplomacy ally
- 「整顿吏治」→ develop，「发展贸易」→ develop
- 默认招募数量1000

返回纯JSON：{"action": "...", "target": "...", "params": {...}}"""

NARRATIVE_SYSTEM = """你是《三國志略》的史官。根据本回合发生的事件，以文白相间的三国演义体写一段简短的回合叙事（2-3句话）。

## 风格要求
- 文白相间，有历史感
- 提及具体地名、人名、数字
- 体现三国时代的气息
- 不超过100字
- 如果行动失败，写出失败的原因和影响
- 提及NPC势力的动向

返回JSON: {"narrative": "..."}"""

SUGGESTIONS_SYSTEM = """你是《三國志略》的军师。根据当前天下形势，为主公提供3-5条战略建议。

## 规则
- 每条建议10-20字，具体可执行
- 基于实际局势（兵力、经济、外交、敌情）
- 不要建议与已方结盟
- 包含军事、内政、外交多维度
- 优先紧迫事项

返回JSON: {"suggestions": ["...", "...", "..."]}"""


class TurnProcessor:
    """Processes one turn end-to-end."""

    def __init__(self):
        self._llm = get_llm()

    @property
    def _has_llm(self) -> bool:
        return self._llm.is_available

    # ─── Main pipeline ─────────────────────────────────

    def process(self, session: GameSession, player_input: str) -> TurnResult:
        bridge = StateBridge(session.world_state)
        faction_id = session.player_faction_id

        # 1. Parse intent (LLM → keyword fallback)
        intent = self._parse_intent(player_input, faction_id)

        # Ensure target is in params for actions that need it
        if intent.get("target") and not intent.get("params", {}).get("target"):
            intent.setdefault("params", {})["target"] = intent["target"]

        # 2. Execute command
        command = Command(
            type=intent["action"], params=intent.get("params", {}), faction_id=faction_id)
        result = bridge.execute_command(command)

        # 3. Advance NPC factions
        npc_actions = bridge.advance_npc_factions()

        # 4. Build events
        events = []
        if result.get("message"):
            events.append(result["message"])
        for na in npc_actions:
            for action in na.get("actions", []):
                events.append(f"{na['faction_name']}: {action}")

        # 5. Generate narrative (LLM → template fallback)
        narrative = self._generate_narrative(intent, result, npc_actions, faction_id)

        # 6. Build suggestions (LLM → heuristic fallback)
        world_snapshot = bridge.get_world_snapshot(faction_id)
        suggestions = self._build_suggestions(session.world_state, faction_id, world_snapshot)

        # 7. Advance turn
        session.turn_number += 1
        session.world_state.turn_number = session.turn_number
        seasons = list(Season)
        current_idx = seasons.index(session.world_state.season)
        if session.turn_number % 2 == 0:
            next_idx = (current_idx + 1) % 4
            session.world_state.season = seasons[next_idx]
            if next_idx == 0:
                session.world_state.year += 1

        return TurnResult(
            narrative=narrative, world_snapshot=world_snapshot,
            suggestions=suggestions, events=events,
            map_ascii="", raw_world_state=session.world_state)

    # ─── Intent parsing ────────────────────────────────

    def _parse_intent(self, text: str, faction_id: str) -> dict:
        """Parse intent: LLM first, keyword fallback."""
        if self._has_llm:
            result = self._llm_intent(text, faction_id)
            # Reject LLM results that have empty target on actions that need one
            if result and self._valid_intent(result):
                return result
        return self._keyword_intent(text, faction_id)

    def _valid_intent(self, result: dict) -> bool:
        """Check if LLM intent is actually valid."""
        action = result.get("action", "")
        target = result.get("target", "")
        params_target = result.get("params", {}).get("target", "")
        # Actions requiring a target
        if action in ("attack", "move", "develop", "diplomacy"):
            if not target and not params_target:
                return False  # Fall back to keyword
        return True

    def _llm_intent(self, text: str, faction_id: str) -> dict | None:
        """Use LLM to understand player intent."""
        user_msg = f"玩家势力: {faction_id}\n玩家输入: {text}\n\n请解析为JSON指令。"
        result = self._llm.chat_structured([
            {"role": "system", "content": INTENT_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.1, max_tokens=512)
        if not result or "action" not in result:
            return None
        # Prevent self-targeting
        target = result.get("target", "")
        if target == faction_id and result.get("action") == "diplomacy":
            # Find another valid target
            alt = result.get("params", {}).get("target", "")
            if alt == faction_id:
                return None  # fallback to keyword
        return result

    def _keyword_intent(self, text: str, faction_id: str) -> dict:
        """Keyword-based intent parser (offline fallback)."""
        text_lower = text.lower().strip()

        if any(kw in text for kw in ["状态", "情报", "status", "info", "查看", "天下大势"]):
            return {"action": "info", "target": "", "params": {}}

        if any(kw in text for kw in ["进攻", "攻击", "打", "attack", "攻", "攻打", "征讨"]):
            target = self._extract_territory(text)
            return {"action": "attack", "target": target, "params": {"target": target}}

        if any(kw in text for kw in ["招募", "征兵", "recruit", "征", "招"]):
            unit_type = "infantry"
            for kw, ut in [("骑兵", "cavalry"), ("骑", "cavalry"), ("弓兵", "archer"),
                           ("弓", "archer"), ("水军", "navy"), ("步兵", "infantry")]:
                if kw in text:
                    unit_type = ut
                    break
            amount = self._extract_number(text) or 1000
            return {"action": "recruit", "target": unit_type,
                    "params": {"unit_type": unit_type, "amount": amount}}

        if any(kw in text for kw in ["移动", "前往", "进军", "move"]):
            target = self._extract_territory(text)
            return {"action": "move", "target": target, "params": {"target": target}}

        if any(kw in text for kw in ["开发", "发展", "develop", "建设"]):
            target = self._extract_territory(text)
            return {"action": "develop", "target": target, "params": {"target": target}}

        if any(kw in text for kw in ["断交", "毁约", "解盟"]):
            target = self._extract_faction(text, faction_id)
            return {"action": "diplomacy", "target": target,
                    "params": {"target": target, "action": "break_ally"}}

        if any(kw in text for kw in ["结盟", "外交", "联盟", "ally", "同盟"]):
            target = self._extract_faction(text, faction_id)
            return {"action": "diplomacy", "target": target,
                    "params": {"target": target, "action": "ally"}}

        if any(kw in text for kw in ["税收", "征税", "税率", "税"]):
            import re
            rate_match = re.search(r"(\d+)%", text)
            rate = int(rate_match.group(1)) / 100.0 if rate_match else 0.3
            return {"action": "tax", "target": "", "params": {"rate": rate}}

        return {"action": "info", "target": "", "params": {"raw_text": text}}

    # ─── Narrative generation ──────────────────────────

    def _generate_narrative(self, intent: dict, result: dict,
                            npc_actions: list[dict], faction_id: str) -> str:
        if self._has_llm:
            llm_result = self._llm_narrative(intent, result, npc_actions, faction_id)
            if llm_result:
                return llm_result
        return self._offline_narrative(intent, result)

    def _llm_narrative(self, intent: dict, result: dict,
                       npc_actions: list[dict], faction_id: str) -> str | None:
        npc_summary = "; ".join(
            f"{na['faction_name']}: {', '.join(na['actions'])}"
            for na in npc_actions[:5] if na.get("actions"))
        user_msg = (
            f"玩家势力: {faction_id}\n"
            f"行动类型: {intent.get('action')}\n"
            f"结果: {'成功' if result.get('success') else '失败'} — {result.get('message', '')}\n"
            f"NPC动向: {npc_summary or '无'}"
        )
        r = self._llm.chat_structured([
            {"role": "system", "content": NARRATIVE_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.8, max_tokens=512)
        return r.get("narrative", "") if r else None

    def _offline_narrative(self, action: dict, result: dict) -> str:
        action_type = action.get("action", "unknown")
        msg = result.get("message", "")
        success = result.get("success")
        templates = {
            "attack": f"我军发起进攻！{msg}。将士们奋勇冲杀，战场烟尘蔽日。" if success else f"进攻计划受阻。{msg}",
            "recruit": f"征兵令下，{msg}。新兵们整装待发。" if success else f"招募失败。{msg}",
            "move": f"大军开拔，{msg}。沿途百姓夹道相迎。" if success else f"进军受阻。{msg}",
            "develop": f"发展内政，{msg}。百姓安居乐业，国力日渐强盛。" if success else f"开发失败。{msg}",
            "diplomacy": f"使者奉命出使，{msg}。" if success else f"外交行动失败。{msg}",
            "tax": f"调整税收，{msg}。" if success else f"税收调整失败。{msg}",
            "info": "天下大势，分久必合，合久必分。",
            "unknown": "主公之意，臣等揣摩中...请明示具体指令。",
        }
        return templates.get(action_type, f"执行完成。{msg}")

    # ─── Suggestions ───────────────────────────────────

    def _build_suggestions(self, world_state: WorldState, faction_id: str,
                           world_snapshot: dict) -> list[str]:
        if self._has_llm:
            llm_result = self._llm_suggestions(world_state, faction_id, world_snapshot)
            if llm_result:
                return llm_result
        return self._heuristic_suggestions(world_state, faction_id)

    def _llm_suggestions(self, world_state: WorldState, faction_id: str,
                         snapshot: dict) -> list[str] | None:
        user_msg = (
            f"势力: {snapshot.get('faction_name', faction_id)}\n"
            f"领地数: {snapshot.get('territory_count', 0)}\n"
            f"总兵力: {snapshot.get('total_troops', 0)}\n"
            f"金库: {snapshot.get('treasury', 0)}\n"
            f"粮草: {snapshot.get('food', 0)}\n"
            f"盟友: {snapshot.get('allies', [])}\n"
            f"敌对边境: {[e['territory_name'] for e in snapshot.get('enemy_borders', [])]}"
        )
        r = self._llm.chat_structured([
            {"role": "system", "content": SUGGESTIONS_SYSTEM},
            {"role": "user", "content": user_msg},
        ], temperature=0.7, max_tokens=512)
        if r and "suggestions" in r:
            suggestions = r["suggestions"]
            # Ensure 3-5 unique suggestions
            seen = set()
            unique = []
            for s in suggestions:
                if s not in seen:
                    seen.add(s)
                    unique.append(s)
            # Remove self-targeting
            faction = world_state.factions.get(faction_id)
            faction_name = faction.name if faction else faction_id
            unique = [s for s in unique if faction_name not in s or "结盟" not in s]
            unique.append("休整一回合")
            return unique[:5]
        return None

    def _heuristic_suggestions(self, world_state: WorldState, faction_id: str) -> list[str]:
        suggestions = []
        faction = world_state.factions.get(faction_id)
        if not faction:
            return ["查看天下大势", "休整一回合"]

        total_troops = sum(
            a.total_troops for a in world_state.armies.values() if a.faction_id == faction_id)
        if total_troops < 5000:
            suggestions.append("招募步兵充实兵力")

        for tid in faction.territories:
            territory = world_state.territories.get(tid)
            if not territory:
                continue
            for nid in territory.neighbors:
                neighbor = world_state.territories.get(nid)
                if neighbor and neighbor.owner_id and neighbor.owner_id != faction_id:
                    rel = faction.relations.get(neighbor.owner_id, 0)
                    if rel < 0:
                        suggestions.append(f"进攻{neighbor.name}夺取领土")
                        break
            if suggestions:
                break

        if faction.food < 3000:
            suggestions.append("开发农业提高粮食产量")

        for fid, rel in faction.relations.items():
            if -20 <= rel <= 30 and fid != faction_id:
                target = world_state.factions.get(fid)
                if target and target.is_active:
                    suggestions.append(f"与{target.name}结盟共抗强敌")
                    break

        suggestions.append("查看天下大势")
        suggestions.append("休整一回合")

        # Deduplicate
        seen = set()
        unique = []
        for s in suggestions:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique[:5]

    # ─── Keyword helpers ──────────────────────────────

    def _extract_territory(self, text: str) -> str:
        territory_keywords = {
            "新野": "xinye", "宛城": "wancheng", "许昌": "xuchang",
            "洛阳": "luoyang", "邺城": "ye", "蓟县": "ji",
            "襄阳": "xiangyang", "江陵": "jiangling", "成都": "chengdu",
            "汉中": "hanshui", "建业": "jianye", "柴桑": "chaisang",
            "吴郡": "wu", "下邳": "xiapi",
        }
        # Sort by length descending to avoid "ye" matching inside "jianye"
        for cn_name in sorted(territory_keywords, key=len, reverse=True):
            if cn_name in text:
                return territory_keywords[cn_name]
        return ""

    def _extract_number(self, text: str) -> int | None:
        import re
        match = re.search(r"(\d+)", text)
        if match:
            n = int(match.group(1))
            return n if 0 < n < 100000 else None
        return None

    def _extract_faction(self, text: str, self_id: str) -> str:
        faction_keywords = {
            "刘备": "shu", "蜀": "shu",
            "曹操": "cao", "曹": "cao", "魏": "cao",
            "孙权": "wu", "吴": "wu", "东吴": "wu",
            "刘表": "liubiao", "荆州": "liubiao",
            "刘璋": "liuzhang", "益州": "liuzhang",
        }
        matches = []
        for kw, fid in faction_keywords.items():
            if kw in text and fid != self_id:
                matches.append((len(kw), fid))
        # Return the longest match (excludes self)
        if matches:
            return sorted(matches, reverse=True)[0][1]
        return ""
