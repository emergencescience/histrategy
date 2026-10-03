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

import re

# 与前端 parseAdvisorStrategies 的正则保持逐字一致（CN/EN 双格式）
_STRATEGY_RE = re.compile(
    r"【(上策|中策|下策|Upper Strategy|Middle Strategy|Lower Strategy)】"
    r"\s*([^\n]*)\n\s*(?:策令|Decree|Command)[：:]\s*([^\n【]+)"
)

_TIER_NORM = {
    "上策": "上策",
    "中策": "中策",
    "下策": "下策",
    "Upper Strategy": "上策",
    "Middle Strategy": "中策",
    "Lower Strategy": "下策",
}

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
    for m in _STRATEGY_RE.finditer(text):
        tier = _TIER_NORM.get(m.group(1), m.group(1))
        title = _BRACKETS.sub("", m.group(2) or "").strip()
        command = _BRACKETS.sub("", m.group(3) or "").strip()
        if command:
            cards.append({"tier": tier, "title": title, "command": command})
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
    strategies = parse_advisor_strategies(text)
    return {
        "type": "strategies",
        "analysis": extract_analysis(text),
        "intercepts": extract_intercepts(text),
        "strategies": strategies,
        "parsed": bool(strategies),
    }
