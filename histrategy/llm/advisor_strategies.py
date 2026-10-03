"""军师进言的**结构化解析**（服务端）。

为什么需要它：`/api/rooms/{id}/advisor-stream` 目前只发**自由文本**帧，前端再把这
段文本正则解析成三张卡片（`surprisal-portal/src/lib/histrategy-play-view.ts`
的 `parseAdvisorStrategies`）。这带来三个问题：
  1. **同一份格式被解析两次**（前后端各一份实现，必然漂移）
  2. 前端拿到的只有 `{tier, title, command}` 单条命令文本，无法承载 PRD 要求的
     **多领域多命令方案**（`strategies[].commands`）
  3. 军师的"拦截解释"（如"吕宋不在当前地图"）只能混在散文里，UI 无法醒目标注

本模块把这段解析搬到**服务端**，让流式响应在 `[DONE]` 之前多发一帧结构化数据：

    data: {"type": "strategies", "analysis": "...", "intercepts": [...],
           "strategies": [{"tier": "上策", "title": "...", "command": "..."}]}

**向后兼容**：现有前端对非字符串帧直接 `continue` 跳过（`page.tsx` 的
`if (typeof chunk !== "string") continue;`），所以先发这一帧不会破坏线上前端。

格式（与 `server/api.py` 的 prompt 约定、前端正则**保持一致**）：
    【上策】〈标题〉
    策令：〈一句可直接执行的政令〉

    【Upper Strategy】〈title〉
    Decree: 〈one executable command〉
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import re

# 与前端 parseAdvisorStrategies 的正则保持逐字一致（CN/EN 双格式）
_STRATEGY_RE = re.compile(
    r"【(上策|中策|下策|玩家决策解析|Upper Strategy|Middle Strategy|Lower Strategy|"
    r"Your Plan|Player's Plan|Your Decision)】"
    r"\s*([^\n]*)\n\s*(?:策令|Decree|Command)[：:]\s*([^\n【]+)"
)

# 一块里可能有**多条**政令（玩家决策解析尤其需要：模糊意图要拆成多领域政策）。
# 按块头切分，再收集该块内所有「策令：」行。
_BLOCK_SPLIT_RE = re.compile(
    r"【(上策|中策|下策|玩家决策解析|Upper Strategy|Middle Strategy|Lower Strategy|"
    r"Your Plan|Player's Plan|Your Decision)】"
)
_CMD_LINE_RE = re.compile(r"^\s*(?:策令|Decree|Command)[：:]\s*(.+)$")

_TIER_NORM = {
    "上策": "上策",
    "中策": "中策",
    "下策": "下策",
    "Upper Strategy": "上策",
    "Middle Strategy": "中策",
    "Lower Strategy": "下策",
}

# 「玩家决策解析」及其英文别名 → 统一档位名（与既有做法一致：前端按档位配色，
# 英文页再用 tierLabel 显示 "Your Plan"）。
CUSTOM_TIER = "玩家决策解析"
_TIER_NORM[CUSTOM_TIER] = CUSTOM_TIER
for _alias in ("Your Plan", "Player's Plan", "Your Decision"):
    _TIER_NORM[_alias] = "玩家决策解析"

# 《》〈〉<> 都是 prompt 里的占位符括号，真输出里出现即属噪音，去掉
_BRACKETS = re.compile(r"[〈〉<>《》]")

# "拦截解释"的启发式标记 —— 军师点破玩家目标不可行时会用这些说法。
# 说明：这是**文本启发式**，不是语义判定。宁可漏报（漏报只是不显示琥珀条，
# 分析文字本身仍在），也不要把普通战况描述误判成拦截。
_INTERCEPT_MARKERS = (
    "不在当前地图",
    "无法执行",
    "不存在于",
    "无法实现",
    "不可行",
    "此令无法",
    "做不到",
    "not on this map",
    "cannot be executed",
    "infeasible",
    "impossible",
    "does not exist",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?;；\n])")


def parse_advisor_strategies(text: str) -> list[dict]:
    """把三策文本解析成 `[{tier, title, command}]`；不符合格式就返回 `[]`。

    与前端 `parseAdvisorStrategies` 行为一致（同正则、同归一化、同"命令为空则丢弃"）。
    """
    if not text:
        return []
    cards: list[dict] = []
    # 先按块切分，以便收集"每块多命令"；兼容旧格式（每块恰好一条）。
    marks = list(_BLOCK_SPLIT_RE.finditer(text))
    for i, m in enumerate(marks):
        tier = _TIER_NORM.get(m.group(1), m.group(1))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        lines = body.split("\n")
        title = _BRACKETS.sub("", lines[0] if lines else "").strip()
        commands: list[str] = []
        for line in lines:
            cm = _CMD_LINE_RE.match(line)
            if cm:
                cmd = _BRACKETS.sub("", cm.group(1)).strip()
                if cmd:
                    commands.append(cmd)
        if not commands:
            continue
        card = {"tier": tier, "title": title, "command": commands[0]}
        if len(commands) > 1:
            card["commands"] = commands
        cards.append(card)
    return cards


def extract_analysis(text: str) -> str:
    """取第一张卡片之前的散文部分作为「军师分析」。

    没有卡片时整段都算分析（此时解析失败，散文仍应展示而不是丢掉）。
    """
    if not text:
        return ""
    m = _STRATEGY_RE.search(text)
    head = text[: m.start()] if m else text
    return head.strip()


def extract_intercepts(text: str) -> list[str]:
    """从军师文字里挑出「目标不可行」的解释句（启发式，见模块注释）。"""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(text):
        s = raw.strip().lstrip("-•*# ").strip()
        if not s or len(s) < 8:
            continue
        low = s.lower()
        if any(mk.lower() in low for mk in _INTERCEPT_MARKERS):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out[:3]


def extract_custom_plan(text: str) -> dict | None:
    """取出「玩家决策解析」这一块（玩家意图 → 具体政令）。

    与上策/下策不同，这一块是**把主公的话翻译成可执行方案**，因此可能含多条政令。
    返回 None 表示这次进言里没有这一块（旧行为：只有三策）。
    """
    for card in parse_advisor_strategies(text):
        if card["tier"] == CUSTOM_TIER:
            return {
                "title": card["title"],
                "understanding": card["title"],   # 块头那句＝"我怎么理解你的话"
                "commands": card.get("commands", [card["command"]]),
            }
    return None


def build_structured_advice(text: str) -> dict:
    """把一段军师进言文本转成结构化帧。

    Returns:
        {
          "type": "strategies",
          "analysis": str,          # 卡片前的散文（常驻展示）
          "intercepts": [str],      # 目标不可行的解释（UI 醒目提示）
          "strategies": [{tier, title, command}],
          "parsed": bool,           # 是否解析出至少一张卡片
        }

    注意：`strategies[].commands`（多领域多命令、预校验）**尚未在此产出**。
    现有实现只在卡片上带单条 `command` 文本；把它变成命令数组需要走意图解析
    （前端目前用 `/api/intent/precompute` 做，点卡片时可跳过 ~20s 的 LLM 解析）。
    该项是后续工作，此处**不伪造**字段。
    """
    all_blocks = parse_advisor_strategies(text)
    # `strategies` 只装**军师给的方案**（上策/下策）；「玩家决策解析」单独走 `custom`，
    # 否则同一块会在两个字段里各出现一次，前端还得自己去重。
    strategies = [c for c in all_blocks if c["tier"] != CUSTOM_TIER]
    custom = extract_custom_plan(text)
    return {
        "type": "strategies",
        "analysis": extract_analysis(text),
        "intercepts": extract_intercepts(text),
        "strategies": strategies,
        "custom": custom,
        "parsed": bool(strategies) or custom is not None,
    }


def parse_option_commands(
    frame: dict,
    faction_id: str,
    llm_adapter=None,
    max_workers: int = 4,
) -> dict | None:
    """把每个选项的政令**解析成结构化 commands**，供前端在**提交前**显示"这条会做什么"。

    为什么需要提前解析：原先只有提交后 `/command` 的回包才带 parsed commands
    （前端因此显示 PARSED negotiate | military_posture 这类小标签）。
    也就是说玩家在**做决策时**看不到自己那条会被理解成什么 —— 而
    "我以为我发了屯田令，实际被解析成别的东西" 正是这套决策流要治的病。

    做法：与 intent_cache.precompute_and_cache 用**同一个** `IntentParser`（不是另写一份
    解析逻辑，避免前后端第三份实现漂移），各选项**并行**解析，返回：

        {"type": "parsed_commands",
         "custom": [[{"type": "invest", "params": {...}}, ...], ...],   # 按政令逐条
         "strategies": [[...], ...]}                                     # 按上策/下策

    **下标对齐**：两个列表都与输入同长、同序（candidate[i] ↔ 输出[i]），
    空命令/解析失败处留空列表 []，这样前端可以直接按下标把 chips 挂到对应选项上。

    解析失败不抛异常（返回该条为空列表），因为这只是**增强信息**，不该拖垮整条军师流。
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs: list[tuple[str, int, str]] = []
    for i, txt in enumerate((frame.get("custom") or {}).get("commands") or []):
        if str(txt or "").strip():
            jobs.append(("custom", i, str(txt)))
    for i, s in enumerate(frame.get("strategies") or []):
        txt = (s or {}).get("command") or ""
        if str(txt).strip():
            jobs.append(("strategies", i, str(txt)))
    if not jobs:
        return None

    def _parse_one(text: str) -> list[dict]:
        try:
            from histrategy.parser.intent import IntentParser
            from histrategy.server.intent_cache import _serialize_commands

            cmds = IntentParser(llm_adapter).parse(text, faction_id)
            out: list[dict] = []
            for c in _serialize_commands(cmds)[:4]:
                out.append({"type": c.get("type", ""), "params": c.get("params", {})})
            return out
        except Exception:
            logger.warning("parse_option_commands: 单条解析失败 text=%r", str(text)[:48], exc_info=True)
            return []

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs)))) as ex:
        results = list(ex.map(_parse_one, [j[2] for j in jobs]))

    frame_out: dict = {"type": "parsed_commands", "custom": [], "strategies": []}
    for (kind, idx, _), parsed in zip(jobs, results):
        bucket = frame_out[kind]
        while len(bucket) <= idx:
            bucket.append([])
        bucket[idx] = parsed
    return frame_out
