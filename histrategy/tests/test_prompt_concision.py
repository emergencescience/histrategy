"""LLM 输出长度的契约测试（2026-10-04）。

背景：生产 provider 是豆包（火山方舟 endpoint ep-20260731233019-dnsbd），
输出偏啰嗦 —— 实测 NPC 的 `decision` 字段能写到 1000+ 字符，
`global_narrative` 也常顶到上限。用户裁定：**继续用 JSON，但把输出长度砍掉约一半**。

长度预算散落在多个 prompt 文件里，改一个漏一个不会有任何报错，只会让
"啰嗦" 悄悄回来。所以把预算钉成测试：prompt 里的数字一旦被改回去，这里就红。
"""
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
P = REPO / "histrategy" / "llm" / "prompts"
S = REPO / "scenarios"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── NPC 决策：`decision` 字段原来完全没有长度上限，是"啰嗦"的最大来源 ──
NPC_DECISION_FILES = [
    P / "npc_decision.md",
    P / "npc_decision_en.md",
    S / "rome-triumvirate" / "prompts" / "npc_decision_zh.md",
    S / "rome-triumvirate" / "prompts" / "npc_decision_en.md",
]


@pytest.mark.parametrize("path", NPC_DECISION_FILES, ids=lambda p: p.name)
def test_npc_decision_has_hard_concision_rules(path):
    txt = _read(path)
    assert "1200" in txt, "npc_decision 总输出上限应已从 2000 砍到 1200"
    assert "2000 字符" not in txt, "旧的 2000 字符上限仍在"
    assert "篇幅减半" in txt or "HALVE THE LENGTH" in txt, "缺少'篇幅减半'硬指令"
    assert "≤ 120 字" in txt or "<= 70 words" in txt, "decision 字段缺少长度上限"


# ── 叙事类 prompt：字数预算必须已减半 ──
@pytest.mark.parametrize(
    "path,expected,forbidden",
    [
        (P / "global_narrative.md", "90-150 字", "180-300 字"),
        (S / "nanming" / "prompts" / "global_narrative_zh.md", "90-150 字", "180-300 字"),
        (P / "global_narrative_en.md", "60-120 words", "120-240 words"),
        (P / "narrative.md", "60-125 字", "120-250 字"),
        (S / "nanming" / "prompts" / "narrative_zh.md", "60-125 字", "120-250 字"),
        (P / "narrative_en.md", "45-90 words", "90-180 words"),
        (P / "plan_suggestions.md", "150-250字", "300-500字"),
    ],
)
def test_narrative_length_budgets_halved(path, expected, forbidden):
    txt = _read(path)
    assert expected in txt, f"{path.name}: 期望新预算 {expected!r}"
    assert forbidden not in txt, f"{path.name}: 旧预算 {forbidden!r} 仍在"


@pytest.mark.parametrize(
    "path,expected,forbidden",
    [
        (P / "advisor.md", "50-100字", "100-200字"),
        (P / "advisor.md", "50字内", "100字内"),
        (P / "advisor_en.md", "50-100 words", "100-200 words"),
        (P / "advisor_en.md", "under 50 words", "under 100 words"),
    ],
)
def test_advisor_length_budgets_halved(path, expected, forbidden):
    txt = _read(path)
    assert expected in txt, f"{path.name}: 期望 {expected!r}"
    assert forbidden not in txt, f"{path.name}: 旧预算 {forbidden!r} 仍在"


# ── 玩家政令解析：notes 以前被要求"保留玩家原文"，等于鼓励抄写 ──
def test_policy_parser_notes_are_capped():
    sys_path = REPO / "histrategy" / "policy" / "policy_parser.py"
    txt = _read(sys_path)
    assert "notes ≤ 30 字" in txt, "policy_parse 缺少 notes 长度上限"
    assert "不要抄写玩家原文" in txt, "policy_parse 缺少'不要照抄原文'约束"
