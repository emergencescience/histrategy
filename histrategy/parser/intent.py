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


def _ensure_scenario_territories(scenario: str | None = None):
    """Lazily populate TERRITORY_NAME_MAP with scenario-specific territory names.

    The base TERRITORY_NAME_MAP only has Three Kingdoms territories.
    Nanming/Rome etc. territories are loaded from scenarios/<id>/knowledge/territories.json.
    """
    if not scenario or getattr(_ensure_scenario_territories, "_loaded", None) == scenario:
        return
    _ensure_scenario_territories._loaded = scenario  # type: ignore[attr-defined]
    try:
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]  # histrategy/ repo root
        tfile = repo_root / "scenarios" / scenario / "knowledge" / "territories.json"
        if not tfile.exists():
            return
        with open(tfile) as f:
            territories = json.load(f)
        for t in territories:
            tid = t["id"]
            name = t.get("name", "")
            # Only add if not already present (don't overwrite existing mappings)
            if name and name not in TERRITORY_NAME_MAP:
                TERRITORY_NAME_MAP[name] = tid
            if tid and tid not in TERRITORY_NAME_MAP:
                TERRITORY_NAME_MAP[tid] = tid
    except Exception as e:
        import logging
        logging.getLogger("histrategy.parser").warning(
            "Failed to load scenario territories for %s: %s", scenario, e
        )


class IntentParser:
    """Parses player free-text into structured Command objects via LLM or keyword fallback."""

    def __init__(self, llm_adapter: LLMAdapter | None = None, scenario: str | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available
        self.scenario = scenario
        # Ensure scenario territory names are loaded for keyword matching
        _ensure_scenario_territories(scenario)

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

        commands = []
        llm_used = False

        if self.llm_available and self.llm:
            try:
                commands = self._llm_parse(resolved_text, faction_id)
                llm_used = True
            except Exception:
                commands = []

        # Always fall back to keyword parsing if LLM returned nothing
        if not commands:
            commands = self._keyword_parse(resolved_text, faction_id)
            if llm_used and commands:
                # LLM failed but keywords worked — log
                import logging
                logging.getLogger("histrategy.parser").info(
                    "LLM parse returned 0 commands for faction=%s, keyword fallback found %d",
                    faction_id, len(commands),
                )

        return commands

    def _llm_parse(self, text: str, faction_id: str) -> list:
        """Use LLM to parse text into commands."""

        user_msg = f"## 玩家势力\nfaction_id: {faction_id}\n\n## 玩家指令\n{text}\n\n请解析以上文本为结构化命令。"

        # Build scenario-aware system prompt with territory/faction IDs
        system_prompt = INTENT_PARSE_SYSTEM

        # Inject current scenario's territory map so LLM knows valid IDs
        territory_refs = []
        for name, tid in sorted(TERRITORY_NAME_MAP.items(), key=lambda x: -len(x[0])):
            if len(name) > 1 and name != tid and not name.startswith("_"):
                territory_refs.append(f"{tid}({name})")
        if territory_refs:
            system_prompt += f"\n\n## 当前可用领土ID\n{', '.join(territory_refs)}"

        # Inject faction map
        faction_refs = []
        for name, fid in sorted(FACTION_NAME_MAP.items(), key=lambda x: -len(x[0])):
            if len(name) > 1 and name != fid:
                faction_refs.append(f"{fid}({name})")
        if faction_refs:
            system_prompt += f"\n\n## 当前势力ID\n{', '.join(faction_refs)}"

        messages = [
            {"role": "system", "content": system_prompt},
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

        # Move (includes 北上, 南下, 东进, 西征, 回师)
        if any(kw in text_lower for kw in ("移动", "行军", "调兵", "移师", "北上", "南下", "东进", "西征", "回师", "进发", "开赴")):
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

        # Spy (includes "策反", "密探", "探虚实")
        if any(kw in text_lower for kw in ("细作", "间谍", "侦查", "情报", "策反", "探虚实", "探", "密探", "窥")):
            target = self._extract_target_faction(text) or ""
            if target:
                commands.append(
                    Command(
                        type="spy",
                        params={"target_faction": target},
                        faction_id=faction_id,
                    )
                )

        # Rest (includes "养精蓄锐", "休养生息")
        if any(kw in text_lower for kw in ("休整", "休息", "修整", "养精蓄锐", "休养生息", "休养", "偃旗息鼓")):
            commands.append(
                Command(
                    type="rest",
                    params={},
                    faction_id=faction_id,
                )
            )

        # Blockade / naval strangle (mapped to defend + notes)
        if any(kw in text_lower for kw in ("封锁", "断绝", "截断", "绝其", "锁断")):
            tid = self._extract_territory(text) or ""
            commands.append(
                Command(
                    type="defend",
                    params={"territory": tid} if tid else {},
                    faction_id=faction_id,
                    notes="封锁/断绝指令: " + (tid if tid else "交通要道"),
                )
            )

        # Amphibious landing (mapped to move)
        if any(kw in text_lower for kw in ("登陆", "抢滩", "渡海", "叩关")):
            tid = self._extract_territory(text) or ""
            if tid:
                amount = self._extract_number(text) if any(c.isdigit() for c in text) else 0
                params: dict = {"destination": tid}
                if amount:
                    params["amount"] = amount
                commands.append(
                    Command(
                        type="move",
                        params=params,
                        faction_id=faction_id,
                        notes=f"两栖登陆: 目标{tid}",
                    )
                )

        # Logistics / supply (mapped to trade)
        if any(kw in text_lower for kw in ("运粮", "补给", "粮道", "供给")):
            tid = self._extract_territory(text) or ""
            commands.append(
                Command(
                    type="trade",
                    params={"resource": "food", "territory": tid} if tid else {"resource": "food"},
                    faction_id=faction_id,
                    notes="后勤补给指令",
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
        """Extract a numeric amount from text.

        Handles:
        - Arabic digits: "5万" → 50000, "300" → 300
        - Simple Chinese: "三千" → 3000, "五百" → 500
        - Special "两": "两万" → 20000, "两千" → 2000
        - Multi-character: "三十五万" → 350000, "十二万" → 120000
        """
        # Chinese numerals (including 两 for 2 and 百 for 100)
        cn_nums = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
        }
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
        # Multi-character Chinese: "三十五万" → 350000, "十二万" → 120000, "两千" → 2000
        # Pattern: optional tens digit + optional unit digit + magnitude
        match_cn = re.search(
            r"([一两二三四五六七八九]十)?([一两二三四五六七八九])?([万千百])",
            text,
        )
        if match_cn:
            tens = match_cn.group(1)  # e.g. "三十" or None
            ones = match_cn.group(2)  # e.g. "五" or None
            unit = match_cn.group(3)  # e.g. "万"

            value = 0
            if tens:
                # "三十" → 30, "十" → 10 (handle bare "十")
                tens_digit = cn_nums.get(tens[0], 1)
                value += tens_digit * 10
            if ones:
                value += cn_nums.get(ones, 0)

            if value == 0:
                value = 1  # bare magnitude with no digits: "万" → 10000

            if unit == "万":
                return value * 10000
            elif unit == "千":
                return value * 1000
            elif unit == "百":
                return value * 100

        # Simple Chinese: "三千" → 3000, "五百" → 500, "五万" → 50000
        match_cn = re.search(r"([一两二三四五六七八九十])([万千百十])", text)
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
