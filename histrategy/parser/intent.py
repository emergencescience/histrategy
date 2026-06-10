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


INTENT_PARSE_SYSTEM = """你是《三國志略》的军令官（Command Parser）。玩家用自由文本描述战略意图，你需要将其解析为结构化命令。

## 支持的命令类型

- **recruit**: 招募士兵。params: territory(领土ID), unit_type(infantry/cavalry/archer/navy), amount(数量)
- **move**: 移动军队。params: destination(目标领土ID)
- **attack**: 攻击敌方。params: target_territory(目标领土ID)
- **develop**: 发展领土。params: territory(领土ID)
- **tax**: 调整税率。params: rate(0.1-0.5)
- **train**: 训练军队。params: territory(领土ID)
- **spy**: 派遣细作。params: target_faction(目标势力ID)
- **trade**: 贸易。params: target_faction(目标势力ID), resource(food/gold)
- **rest**: 休整。无params
- **appoint**: 任命官员。params: character(人物ID), role(governor/commander)
- **dismiss**: 解任官员。params: character(人物ID)
- **negotiate**: 外交谈判。params: target_faction(目标势力ID), proposal(提案)
- **research**: 研究科技。params: tech(科技名)

## 关键领土ID参考

- 曹操领地: xuchang(许昌), luoyang(洛阳), ye(邺城), wancheng(宛城), changshan(常山)
- 刘备领地: xinye(新野), pingyuan(平原)
- 孙权领地: jianye(建业), wu(吴郡), kuaiji(会稽), chaisang(柴桑)
- 刘表领地: xiangyang(襄阳), jiangling(江陵)

## 解析规则

1. 将玩家的自由文本翻译为结构化的命令
2. 自动推断领土ID：如"在许昌招兵" → territory: xuchang
3. 自动推断势力ID：如"与曹操结盟" → target_faction: cao
4. 如果玩家文本无法对应任何支持的命令 → 返回空列表 []
5. 语言是中文，命令type必须用英文

## 输出格式

严格输出JSON:
{
  "commands": [
    {"type": "recruit", "params": {"territory": "xinye", "unit_type": "infantry", "amount": 500}},
    {"type": "develop", "params": {"territory": "xinye"}}
  ]
}

如果没有匹配的命令，输出 {"commands": []}"""

# ─── Territory name → ID mapping ───────────────────────────────

TERRITORY_NAME_MAP: dict[str, str] = {
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
    "新野": "xinye",
    "xinye": "xinye",
    "平原": "pingyuan",
    "pingyuan": "pingyuan",
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
}

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
                max_tokens=1024,
            )
        except Exception:
            # Fallback to plain chat with JSON extraction
            try:
                result = self.llm.chat(
                    messages,
                    temperature=0.1,
                    max_tokens=1024,
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
                commands.append(
                    Command(
                        type="attack",
                        params={"target_territory": target},
                        faction_id=faction_id,
                    )
                )

        # Move
        if any(kw in text_lower for kw in ("移动", "行军", "调兵", "移师")):
            dest = self._extract_territory(text) or ""
            if dest:
                commands.append(
                    Command(
                        type="move",
                        params={"destination": dest},
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
        """Replace known names with their IDs for LLM parsing."""
        result = text
        for name, tid in TERRITORY_NAME_MAP.items():
            if len(name) > 1:  # Skip single-char to avoid false matches
                result = result.replace(name, f"{name}({tid})")
        for name, fid in FACTION_NAME_MAP.items():
            if len(name) > 1:
                result = result.replace(name, f"{name}({fid})")
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
        ):
            return None

        params = cmd_data.get("params", {})
        if not isinstance(params, dict):
            params = {}

        return Command(
            type=cmd_type,
            params=params,
            faction_id=faction_id,
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
        match = re.search(r"(\d+)[千百]?", text)
        if match:
            return int(match.group(1))
        # "三千" → 3000, "五百" → 500
        match_cn = re.search(r"([一二三四五六七八九十])([千百十])", text)
        if match_cn:
            digit = cn_nums.get(match_cn.group(1), 1)
            unit = match_cn.group(2)
            if unit == "千":
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
