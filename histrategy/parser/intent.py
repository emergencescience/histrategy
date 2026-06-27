"""
Intent Parser — converts player free-text into structured Command objects.

Uses a lightweight LLM call to parse natural language into game commands.
Supported command types: recruit, move, attack, develop, tax, train, spy,
trade, rest, appoint, dismiss, negotiate, research.

Keyword-based fallback when no LLM is available.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import Command

    from histrategy.llm.adapter import LLMAdapter


# ─── Name → ID mappings (canonical source: faction_slot.py) ─────
from histrategy.engine.faction_slot import (
    FACTION_NAME_MAP,
    TERRITORY_NAME_MAP,
)
from histrategy.llm.prompt_loader import INTENT_PARSE_SYSTEM


class IntentParser:
    """Parses player free-text into structured Command objects via LLM or keyword fallback."""

    def __init__(self, llm_adapter: LLMAdapter | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available

    def parse(self, raw_text: str, faction_id: str) -> list:
        """Parse natural language text into a list of Command objects.

        Args:
            raw_text: Player's free-text strategic decision
            faction_id: The player faction ID (e.g. "shu", "cao", "wu")

        Returns:
            List of Command objects (from histrategy_engine.world.Command).
            Unsupported or unparseable text yields an empty list.
        """

        text = raw_text.strip()
        if not text:
            return []

        # Pre-process: resolve territory and faction names
        resolved_text = self._resolve_names(text, faction_id)

        if self.llm_available and self.llm:
            try:
                return self._llm_parse(resolved_text, faction_id)
            except Exception:
                return []

        return self._keyword_parse(resolved_text, faction_id)

    def _llm_parse(self, text: str, faction_id: str) -> list:
        """Use LLM to parse text into commands."""

        user_msg = f"## 玩家势力\nfaction_id: {faction_id}\n\n## 玩家指令\n{text}\n\n请解析以上文本为结构化命令。"

        messages = [
            {"role": "system", "content": INTENT_PARSE_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        try:
            result = self.llm.chat_structured(
                messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception:
            # Fallback to plain chat with JSON extraction
            try:
                result = self.llm.chat(
                    messages,
                    temperature=0.1,
                    max_tokens=4096,
                )
                result = self._extract_json(result)
            except Exception:
                return []

        commands_data = result.get("commands", [])
        if not isinstance(commands_data, list):
            return []

        commands: list[Command] = []
        for cmd_data in commands_data:
            cmd = self._build_command(cmd_data, faction_id)
            if cmd:
                commands.append(cmd)

        return commands

    def _keyword_parse(self, text: str, faction_id: str) -> list:
        """Keyword-based fallback parser when no LLM available."""
        from histrategy_engine.world import Command

        commands: list[Command] = []
        text_lower = text.lower()

        # Detect command types via keywords
        # Recruit
        if any(kw in text_lower for kw in ("招兵", "募兵", "征兵", "招募", "扩军")):
            tid = self._extract_territory(text) or ""
            amount = self._extract_number(text) or 500
            unit_type = self._extract_unit_type(text)
            if tid:
                commands.append(
                    Command(
                        type="recruit",
                        params={"territory": tid, "unit_type": unit_type, "amount": amount},
                        faction_id=faction_id,
                    )
                )

        # Develop
        if any(kw in text_lower for kw in ("发展", "开发", "建设", "屯田", "修城", "农")):
            tid = self._extract_territory(text) or ""
            if tid:
                commands.append(
                    Command(
                        type="develop",
                        params={"territory": tid},
                        faction_id=faction_id,
                    )
                )

        # Attack
        if any(kw in text_lower for kw in ("攻击", "进攻", "攻打", "讨伐", "出兵", "讨")):
            target = self._extract_territory(text) or self._extract_target_faction(text) or ""
            if target:
                params = {"target_territory": target}

                # Extract source territory if another territory is mentioned
                mentioned = []
                for name, tid in TERRITORY_NAME_MAP.items():
                    if len(name) > 1 and name in text and tid not in mentioned:
                        mentioned.append(tid)
                if len(mentioned) > 1:
                    for tid in mentioned:
                        if tid != target:
                            params["source_territory"] = tid
                            break

                if any(c.isdigit() or c in "一二三四五六七八九十" for c in text):
                    params["amount"] = self._extract_number(text)

                if any(kw in text for kw in ("骑兵", "马", "骑", "弓", "弩", "水", "步")):
                    params["unit_type"] = self._extract_unit_type(text)

                commands.append(
                    Command(
                        type="attack",
                        params=params,
                        faction_id=faction_id,
                    )
                )

        # Move
        if any(kw in text_lower for kw in ("移动", "行军", "调兵", "移师")):
            dest = self._extract_territory(text) or ""
            if dest:
                params = {"destination": dest}

                # Extract source territory if another territory is mentioned
                mentioned = []
                for name, tid in TERRITORY_NAME_MAP.items():
                    if len(name) > 1 and name in text and tid not in mentioned:
                        mentioned.append(tid)
                if len(mentioned) > 1:
                    for tid in mentioned:
                        if tid != dest:
                            params["source_territory"] = tid
                            break

                if any(c.isdigit() or c in "一二三四五六七八九十" for c in text):
                    params["amount"] = self._extract_number(text)

                if any(kw in text for kw in ("骑兵", "马", "骑", "弓", "弩", "水", "步")):
                    params["unit_type"] = self._extract_unit_type(text)

                commands.append(
                    Command(
                        type="move",
                        params=params,
                        faction_id=faction_id,
                    )
                )

        # Tax
        if any(kw in text_lower for kw in ("税率", "赋税", "征税", "加税", "减税")):
            rate = self._extract_tax_rate(text)
            commands.append(
                Command(
                    type="tax",
                    params={"rate": rate},
                    faction_id=faction_id,
                )
            )

        # Train
        if any(kw in text_lower for kw in ("训练", "操练", "练兵")):
            tid = self._extract_territory(text) or ""
            if tid:
                commands.append(
                    Command(
                        type="train",
                        params={"territory": tid},
                        faction_id=faction_id,
                    )
                )

        # Defend
        if any(kw in text_lower for kw in ("防守", "布防", "防御", "戒备", "镇守", "驻防", "保卫", "设防")):
            tid = self._extract_territory(text) or ""
            if tid:
                params = {"territory": tid}

                if any(c.isdigit() or c in "一二三四五六七八九十" for c in text):
                    params["amount"] = self._extract_number(text)

                if any(kw in text for kw in ("骑兵", "马", "骑", "弓", "弩", "水", "步")):
                    params["unit_type"] = self._extract_unit_type(text)

                commands.append(
                    Command(
                        type="defend",
                        params=params,
                        faction_id=faction_id,
                        notes=f"防御指令: 在{tid}部署防守兵力",
                    )
                )

        # Rest
        if any(kw in text_lower for kw in ("休整", "休息", "修整")):
            commands.append(
                Command(
                    type="rest",
                    params={},
                    faction_id=faction_id,
                )
            )

        # Negotiate
        if any(kw in text_lower for kw in ("联盟", "结盟", "外交", "谈判", "同盟", "遣使", "修好")):
            target = self._extract_target_faction(text) or ""
            if target:
                commands.append(
                    Command(
                        type="negotiate",
                        params={"target_faction": target},
                        faction_id=faction_id,
                    )
                )

        # Spy
        if any(kw in text_lower for kw in ("细作", "间谍", "侦查", "情报")):
            target = self._extract_target_faction(text) or ""
            if target:
                commands.append(
                    Command(
                        type="spy",
                        params={"target_faction": target},
                        faction_id=faction_id,
                    )
                )

        return commands

    # ── Helpers ──────────────────────────────────────────────────

    def _resolve_names(self, text: str, faction_id: str) -> str:
        """Replace known names with their IDs for LLM parsing.

        Only replaces bare names (e.g. '刘备' → '刘备(shu)'), NOT already-resolved
        names (e.g. '刘备(shu)' stays as-is). This prevents double-resolution.

        When a name(id) pattern is detected, BOTH the name and the bare id are
        marked as resolved — so '刘备(shu)' prevents re-resolution of both
        '刘备' and standalone 'shu'.
        """
        result = text

        # Phase 1: detect which names are already resolved.
        # When we find '刘备(shu)', mark both '刘备' AND 'shu' as resolved.
        already_resolved: set[str] = set()
        for name, tid in TERRITORY_NAME_MAP.items():
            if len(name) > 1 and f"{name}({tid})" in result:
                already_resolved.add(name)
                already_resolved.add(tid)  # also mark the bare id as resolved
        for name, fid in FACTION_NAME_MAP.items():
            if len(name) > 1 and f"{name}({fid})" in result:
                already_resolved.add(name)
                already_resolved.add(fid)  # also mark the bare id as resolved

        # Phase 2: replace only unresolved names.
        # After each replacement, mark the inserted ID as resolved to prevent
        # newly-inserted IDs from being re-resolved in subsequent iterations.
        for name, tid in TERRITORY_NAME_MAP.items():
            if len(name) <= 1 or name in already_resolved:
                continue
            result = result.replace(name, f"{name}({tid})")
            already_resolved.add(tid)  # prevent re-resolution of inserted ID

        for name, fid in FACTION_NAME_MAP.items():
            if len(name) <= 1 or name in already_resolved:
                continue
            result = result.replace(name, f"{name}({fid})")
            already_resolved.add(fid)  # prevent re-resolution of inserted ID

        return result

    def _build_command(self, cmd_data: dict, faction_id: str):
        """Build a Command from parsed JSON data, with validation."""
        from histrategy_engine.world import Command

        cmd_type = cmd_data.get("type", "").strip().lower()
        if cmd_type not in (
            "recruit",
            "move",
            "attack",
            "develop",
            "tax",
            "train",
            "spy",
            "trade",
            "rest",
            "appoint",
            "dismiss",
            "negotiate",
            "research",
            "defend",
        ):
            return None

        params = cmd_data.get("params", {})
        if not isinstance(params, dict):
            params = {}

        notes = cmd_data.get("notes", "")
        if not isinstance(notes, str):
            notes = str(notes)

        return Command(
            type=cmd_type,
            params=params,
            faction_id=faction_id,
            notes=notes,
        )

    def _extract_territory(self, text: str) -> str | None:
        """Extract territory ID from text using name map.

        Sorted by name length descending to prefer longest match
        (e.g. 'xinye' over 'ye', 'changsha' over 'sha').
        """
        sorted_names = sorted(TERRITORY_NAME_MAP.items(), key=lambda x: -len(x[0]))
        for name, tid in sorted_names:
            if name in text:
                return tid
        return None

    def _extract_target_faction(self, text: str) -> str | None:
        """Extract faction ID from text."""
        for name, fid in FACTION_NAME_MAP.items():
            if name in text:
                return fid
        return None

    def _extract_number(self, text: str) -> int:
        """Extract a numeric amount from text."""
        # Chinese numerals
        cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        # Match Arabic digits optionally followed by magnitude: "5万" → 50000, "1千" → 1000, "300" → 300
        match = re.search(r"(\d+)\s*([万千百])?", text)
        if match:
            num = int(match.group(1))
            mag = match.group(2)
            if mag == "万":
                num *= 10000
            elif mag == "千":
                num *= 1000
            elif mag == "百":
                num *= 100
            return num
        # "三千" → 3000, "五百" → 500, "五万" → 50000
        match_cn = re.search(r"([一二三四五六七八九十])([万千百十])", text)
        if match_cn:
            digit = cn_nums.get(match_cn.group(1), 1)
            unit = match_cn.group(2)
            if unit == "万":
                return digit * 10000
            elif unit == "千":
                return digit * 1000
            elif unit == "百":
                return digit * 100
            elif unit == "十":
                return digit * 10
        return 500

    def _extract_unit_type(self, text: str) -> str:
        """Extract unit type from text."""
        if any(kw in text for kw in ("骑兵", "马", "骑")):
            return "cavalry"
        if any(kw in text for kw in ("弓箭", "弩", "弓兵", "射手")):
            return "archer"
        if any(kw in text for kw in ("水军", "水师", "船", "舟")):
            return "navy"
        return "infantry"

    def _extract_tax_rate(self, text: str) -> float:
        """Extract tax rate from text (0.1-0.5)."""
        match = re.search(r"(\d+)\s*[%％]", text)
        if match:
            rate = int(match.group(1)) / 100.0
            return max(0.1, min(0.5, rate))
        # "加税" → 0.4, "减税" → 0.2
        if "加" in text:
            return 0.4
        if "减" in text:
            return 0.2
        return 0.3

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM text response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*\n?({.*?})\n?\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return {}
