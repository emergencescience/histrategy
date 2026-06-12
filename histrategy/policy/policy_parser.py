"""
Policy Parser — converts player free-text policy decisions into PolicyCommand objects.

Uses an LLM call with structured output to parse natural language
into high-level strategic commands (tax policy, law, diplomacy, war declaration).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from histrategy.policy.policy_types import PolicyCommand, validate_policy_params

if TYPE_CHECKING:
    from histrategy.llm.adapter import LLMAdapter

# ─── Prompt ────────────────────────────────────────────────────

POLICY_PARSE_SYSTEM = """你是《三國志略》的尚书令（Policy Parser）。玩家扮演一位割据君主，用自由文本描述其施政方略。你需要将其解析为结构化策令。

## 支持的策令类型

| type | params | 说明 |
|------|--------|------|
| tax_rate | rate(税率, 0.0-1.0), territory(可选, 默认全部领地) | 设定税率 |
| law | name(法令名), scope(可选), territory(可选) | 颁布/废除法令 |
| appoint | character(人物ID), position(可选) | 任命/罢免官员 |
| diplomacy | target(目标势力), action(结盟alliance/通商trade/联姻marriage/威胁threaten), terms(可选), gift(可选) | 外交行动 |
| declare_war | target(目标势力), reason(可选), casus_belli(可选) | 宣战 |
| sue_peace | target(目标势力), terms(可选), tribute(可选) | 求和/称臣 |
| relocate_capital | to(目标城市) | 迁都 |
| intelligence | target(目标势力), scope(可选) | 情报活动 |
| develop | territory(目标城市), focus(可选: agriculture/commerce/military) | 区域开发 |
| trade | target(目标势力), goods(可选), amount(可选) | 建立贸易 |
| conscript | amount(征兵数量), territory(可选) | 征兵动员 |

## 核心规则

1. 一项玩家决策可能分解为多条策令
2. 法令(law)应该使用历史上真实存在的制度名（如"屯田制"、"九品中正制"、"盐铁专卖"）
3. 每个策令的 notes 字段保留玩家原文中的上下文和意图
4. 人物名必须使用拼音 ID（如 xunyu, zhugeliang, simayi）
5. 势力名用拼音 ID（cao, shu, wu, liubiao, liuzhang, yuanshao）
6. 领土名用拼音 ID（xuchang, wancheng, xinye, jianye, chengdu 等）
7. **重要**: "收编敌军"、"收编荆州水军"、"收容旧部"等描述的是**占领敌军后吸收其部队**，应该用 declare_war + notes 来描述，而不是 conscript。conscript 仅用于从自己领地**新征募平民**入伍（如"征募5000新兵"、"在宛城征兵"）。
8. **conscript 的量**：古代一郡一季最多征募总人口的5%（如新野3万人口→最多1500人）。不要解析出超过这个比例的征兵量。

## 输出格式

每行一个 JSON 对象（不要数组包裹）：

{"type": "tax_rate", "params": {"rate": 0.30}, "notes": "减轻百姓负担，藏富于民"}
{"type": "law", "params": {"name": "屯田制"}, "notes": "利用荒地和无主田，军队屯垦"}
{"type": "declare_war", "params": {"target": "liubiao", "reason": "刘表占据荆州，阻碍统一大业"}, "notes": "趁刘表病危取荆州"}
"""

# ─── Name mapping ──────────────────────────────────────────────

TERRITORY_TO_ID: dict[str, str] = {
    "许昌": "xuchang", "xuchang": "xuchang",
    "洛阳": "luoyang", "luoyang": "luoyang",
    "邺城": "ye", "邺": "ye", "ye": "ye",
    "宛城": "wancheng", "wancheng": "wancheng",
    "常山": "changshan", "changshan": "changshan",
    "蓟县": "ji", "蓟": "ji", "ji": "ji",
    "濮阳": "puyang", "puyang": "puyang",
    "北海": "beihai", "beihai": "beihai",
    "下邳": "xiapi", "xiapi": "xiapi",
    "新野": "xinye", "xinye": "xinye",
    "建业": "jianye", "建業": "jianye", "jianye": "jianye",
    "吴郡": "wu", "吳郡": "wu",
    "会稽": "kuaiji", "會稽": "kuaiji", "kuaiji": "kuaiji",
    "柴桑": "chaisang", "chaisang": "chaisang",
    "庐江": "lujiang", "廬江": "lujiang", "lujiang": "lujiang",
    "豫章": "yuzhang", "yuzhang": "yuzhang",
    "丹阳": "danyang", "danyang": "danyang",
    "襄阳": "xiangyang", "襄陽": "xiangyang", "xiangyang": "xiangyang",
    "江陵": "jiangling", "jiangling": "jiangling",
    "长沙": "changsha", "長沙": "changsha", "changsha": "changsha",
    "江口": "jiangkou", "jiangkou": "jiangkou",
    "成都": "chengdu", "chengdu": "chengdu",
    "汉中": "hanshui", "漢中": "hanshui", "hanshui": "hanshui",
    "江州": "jiangzhou", "jiangzhou": "jiangzhou",
    "南郡": "nanjun", "nanjun": "nanjun",
}

FACTION_TO_ID: dict[str, str] = {
    "曹操": "cao", "曹": "cao", "cao": "cao",
    "刘备": "shu", "蜀": "shu", "刘": "shu", "shu": "shu",
    "孙权": "wu", "吴": "wu", "孙": "wu", "wu": "wu",
    "刘表": "liubiao", "liubiao": "liubiao",
    "刘璋": "liuzhang", "liuzhang": "liuzhang",
    "袁绍": "yuanshao", "yuanshao": "yuanshao",
}

CHARACTER_TO_ID: dict[str, str] = {
    "荀彧": "xunyu", "司马懿": "simayi", "夏侯渊": "xiahouyuan",
    "张郃": "zhanghe", "张辽": "zhangliao", "程昱": "chengyu",
    "诸葛亮": "zhugeliang", "关羽": "guanyu", "张飞": "zhangfei",
    "赵云": "zhaoyun", "庞统": "pangtong", "法正": "fazheng",
    "黄忠": "huangzhong", "魏延": "weiyan",
    "周瑜": "zhouyu", "鲁肃": "lusu", "吕蒙": "lvmeng",
    "陆逊": "luxun", "甘宁": "ganning", "黄盖": "huanggai",
}


class PolicyParser:
    """Parses player natural language into structured PolicyCommand objects."""

    def __init__(self, llm_adapter: LLMAdapter | None = None):
        self.llm = llm_adapter
        self.llm_available = llm_adapter is not None and llm_adapter.is_available

    def parse(self, raw_text: str, faction_id: str) -> list[PolicyCommand]:
        """Parse natural language into policy commands.

        Args:
            raw_text: Player's free-text strategic decision
            faction_id: Player faction ID (e.g. "cao", "shu")

        Returns:
            List of PolicyCommand objects. Empty if unparseable.
        """
        text = raw_text.strip()
        if not text:
            return []

        resolved = self._resolve_names(text)

        if self.llm_available and self.llm:
            try:
                return self._llm_parse(resolved)
            except Exception:
                pass

        return self._keyword_parse(resolved)

    # ── Name resolution ────────────────────────────────────

    def _resolve_names(self, text: str) -> str:
        """Replace Chinese names with pinyin IDs for LLM consistency."""
        import re as _re
        
        # Collect all known name→ID mappings
        all_terms: dict[str, str] = {}
        all_terms.update(TERRITORY_TO_ID)
        all_terms.update(FACTION_TO_ID)
        all_terms.update(CHARACTER_TO_ID)
        
        # Build longest-first sorted unique names (exclude names that == their ID)
        names = sorted(
            [cn for cn, pid in all_terms.items() if cn != pid],
            key=len, reverse=True,
        )
        
        # Single-pass replacement using placeholders to prevent double-matching
        # Strategy: replace each name with a placeholder, then replace placeholders
        placeholders: dict[str, str] = {}
        result = text
        for i, cn in enumerate(names):
            pid = all_terms[cn]
            placeholder = f"__NAME_{i}__"
            escaped = _re.escape(cn)
            result = _re.sub(escaped, placeholder, result)
            placeholders[placeholder] = f"{cn}({pid})"
        
        # Replace placeholders with final annotations
        for placeholder, replacement in placeholders.items():
            result = result.replace(placeholder, replacement)
        
        return result

    # ── LLM parsing ────────────────────────────────────────

    def _llm_parse(self, text: str) -> list[PolicyCommand]:
        messages = [
            {"role": "system", "content": POLICY_PARSE_SYSTEM},
            {"role": "user", "content": f"## 玩家指令\n{text}\n\n请解析为结构化策令。"},
        ]

        # Use plain chat (not chat_structured) because the prompt requests
        # newline-delimited JSON objects (one per line), not a single JSON object.
        response = self.llm.chat(
            messages,
            temperature=0.2,
            max_tokens=2048,
            metadata={
                "category": "policy_parse",
                "reason": "parse_policy",
            },
        )

        return self._parse_llm_response(response)

    def _parse_llm_response(self, result) -> list[PolicyCommand]:
        """Parse LLM response into PolicyCommand list.

        Handles plain text (newline-delimited JSON), dict, and list formats.
        """
        import json as _json

        # Plain text response: parse each line as JSON
        if isinstance(result, str):
            items = []
            for line in result.strip().split("\n"):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        items.append(_json.loads(line))
                    except _json.JSONDecodeError:
                        continue
            if not items:
                # Fallback: try the whole text as JSON
                try:
                    items = _json.loads(result)
                    if isinstance(items, dict):
                        items = [items]
                except _json.JSONDecodeError:
                    return []
        elif isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            if "commands" in result:
                items = result["commands"]
            else:
                items = [result]
        else:
            return []

        commands = []
        for item in items:
            if not isinstance(item, dict):
                continue
            cmd_type = item.get("type", "").strip()
            if cmd_type not in {"tax_rate", "law", "appoint", "diplomacy",
                                 "declare_war", "sue_peace", "relocate_capital",
                                 "intelligence", "develop", "trade", "conscript"}:
                continue
            params = item.get("params", {})
            notes = item.get("notes", "")
            try:
                cmd = PolicyCommand(
                    type=cmd_type,
                    params=params,
                    notes=notes,
                    source_text=item.get("source_text", ""),
                )
                commands.append(cmd)
            except ValueError:
                continue

        return commands

    # ── Name normalization ─────────────────────────────────

    @staticmethod
    def _normalize_id(name: str, mapping: dict[str, str]) -> str:
        """Extract pinyin ID from possibly-annotated name like '刘表(liubiao)'.

        Args:
            name: Raw name from regex match (may contain annotation suffix)
            mapping: Chinese-name → pinyin ID lookup dict

        Returns:
            Pinyin ID if found in mapping, otherwise the raw input.
        """
        # Try direct lookup first
        if name in mapping:
            return mapping[name]
        # Strip annotation like "刘表(liubiao)" → try "刘表" lookup
        if '(' in name and name.endswith(')'):
            paren_idx = name.index('(')
            # Extract the ID part: "刘表(liubiao)" → "liubiao"
            inner_id = name[paren_idx + 1:-1]
            if inner_id in mapping:
                return mapping[inner_id]
            # Try base name: "刘表(liubiao)" → "刘表"
            base_name = name[:paren_idx]
            if base_name in mapping:
                return mapping[base_name]
        return name

    # ── Keyword fallback ───────────────────────────────────

    def _keyword_parse(self, text: str) -> list[PolicyCommand]:
        """Simple keyword-based parsing when no LLM is available."""
        commands = []
        import re

        # Tax rate — match patterns like "税率从40%降至30%", "税率降至30%", "降税至30%"
        # Strategy: find last percentage number appearing after a tax keyword
        tax_matches = re.findall(
            r"税[率收]?\D*(?:从\d+%|降至|下调|上调|调整|降|调|变|改为|设为)\D*(\d+)\s*%",
            text,
        )
        if tax_matches:
            rate = int(tax_matches[-1]) / 100
            commands.append(PolicyCommand(
                type="tax_rate",
                params={"rate": rate},
                notes=f"关键词匹配: 税率{int(rate*100)}%",
                source_text=f"税率{int(rate*100)}%",
            ))

        # War declaration
        war_patterns = [
            (r"对(\S+)宣战", "declare_war"),
            (r"进攻(\S+)", "declare_war"),
            (r"讨伐(\S+)", "declare_war"),
        ]
        for pattern, _ in war_patterns:
            war_match = re.search(pattern, text)
            if war_match:
                target_name = war_match.group(1)
                target_id = self._normalize_id(target_name, FACTION_TO_ID)
                commands.append(PolicyCommand(
                    type="declare_war",
                    params={"target": target_id},
                    notes=f"关键词匹配: 对{target_name}宣战",
                    source_text=war_match.group(0),
                ))
                break

        # Diplomacy — "与X结好", "派使者...与X...", "与X结盟"
        # Allow longer match to handle annotated names like "刘表(liubiao)"
        diplomacy_match = re.search(
            r"(?:与|同|向|和)(\S{1,20}?)(?:结好|结盟|同盟|和解|修好|联姻|通商|媾和)",
            text,
        )
        if diplomacy_match:
            target_name = diplomacy_match.group(1)
            target_id = self._normalize_id(target_name, FACTION_TO_ID)
            action = "alliance" if "盟" in diplomacy_match.group(0) or "好" in diplomacy_match.group(0) else "trade"
            commands.append(PolicyCommand(
                type="diplomacy",
                params={"target": target_id, "action": action},
                notes=f"关键词匹配: 与{target_name}建交",
                source_text=diplomacy_match.group(0),
            ))

        # Conscription — "征募X", "征兵X", "募兵X"
        conscript_match = re.search(r"(?:征募|征召|募兵|征兵|募集)\s*(\d{2,6})", text)
        if conscript_match:
            amount = int(conscript_match.group(1))
            commands.append(PolicyCommand(
                type="conscript",
                params={"amount": amount},
                notes=f"关键词匹配: 征兵{amount}人",
                source_text=conscript_match.group(0),
            ))

        # Law
        law_match = re.search(r"(推行|实行|颁布|废除)(.{2,6}(?:制|法|令))", text)
        if law_match:
            commands.append(PolicyCommand(
                type="law",
                params={"name": law_match.group(2)},
                notes=f"关键词匹配: {law_match.group(0)}",
                source_text=law_match.group(0),
            ))

        return commands
