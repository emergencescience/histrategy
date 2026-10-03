"""回归保护：军师进言的结构化帧（T2）。

背景：`/advisor-stream` 原先只发自由文本，前端再正则解析成三张卡片 —— 同一份格式
前后端各解析一遍（必然漂移），且无法承载 PRD 要求的多领域多命令方案。
本模块把解析搬到服务端，在 `[DONE]` 之前多发一帧
`{"type":"strategies","analysis":...,"intercepts":[...],"strategies":[...]}`。

**向后兼容**：现有前端对非字符串帧 `continue` 跳过，故先发帧不会破坏线上前端。

其中 `test_matches_frontend_typescript_implementation` 会**真的调用前端那份 TS 实现**
（抽出函数、剥掉类型标注、用 node 跑）做逐样例比对 —— 避免"自己跟自己比"。
node 不可用时自动跳过。
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.llm.advisor_strategies import (  # noqa: E402
    build_structured_advice,
    extract_analysis,
    extract_custom_plan,
    extract_intercepts,
    parse_advisor_strategies,
)

PROMPTS = REPO / "histrategy" / "llm" / "prompts"
TS_SRC = Path("/opt/data/repos/surprisal-portal/src/lib/histrategy-play-view.ts")

CN = """当前形势：我据新野一城，兵不满万，曹军已得荆襄之势。宜先固本，再图进取。

【上策】联孙抗曹
策令：遣使携金五百赴江东，与孙权订立共抗曹操之盟

【中策】屯田扩军
策令：税率降至 0.15，于新野推行屯田制，招募新兵三千

【下策】结刘表援
策令：遣使往刘表处借粮二千石
"""

EN = """The realm is divided. We hold Xinye with scarce troops.

【Upper Strategy】Ally with Wu
Decree: send an envoy to Sun Quan with 500 gold to forge an alliance

【Middle Strategy】Farming and Levies
Command: lower tax to 0.15 and recruit 3000 troops in Xinye

【Lower Strategy】Court Liu Biao
Decree: request 2000 shi of grain from Liu Biao
"""

INTERCEPT = """「吕宋」不在当前地图，此令无法执行。可改攻交州，方向一致且在地图内。

【上策】南取交州
策令：自番禺出兵三千攻取交州
"""


def test_parses_chinese_three_strategies():
    cards = parse_advisor_strategies(CN)
    assert [c["tier"] for c in cards] == ["上策", "中策", "下策"]
    assert cards[0]["title"] == "联孙抗曹"
    assert "五百" in cards[0]["command"]


def test_parses_english_three_strategies_and_normalizes_tier():
    cards = parse_advisor_strategies(EN)
    assert [c["tier"] for c in cards] == ["上策", "中策", "下策"], "英文档位要归一成中文档位"
    assert cards[1]["title"] == "Farming and Levies", "Middle Strategy 应识别"


def test_malformed_input_yields_no_cards_not_garbage():
    """散文式进言（不符合格式）应返回空表，让 UI 优雅退化，而不是编出卡片。"""
    assert parse_advisor_strategies("眼下宜静观其变，敌我不明，不宜妄动。") == []


def test_analysis_is_prose_before_first_card():
    a = extract_analysis(CN)
    assert a.startswith("当前形势")
    assert "【上策】" not in a, "分析里不该含卡片格式"
    # 无法解析时整段都算分析（散文仍要展示，不能丢）
    prose = "眼下宜静观其变。"
    assert extract_analysis(prose) == prose


def test_intercepts_detects_out_of_map_goal():
    got = extract_intercepts(INTERCEPT)
    assert any("不在当前地图" in s for s in got)
    assert extract_intercepts(CN) == [], "普通战况描述不得被误判为拦截"


def test_structured_frame_shape():
    frame = build_structured_advice(CN)
    assert frame["type"] == "strategies"
    assert frame["parsed"] is True
    assert len(frame["strategies"]) == 3
    assert frame["intercepts"] == []
    assert isinstance(frame["analysis"], str) and frame["analysis"]
    # 必须可 JSON 序列化（要经 SSE 发送）
    json.dumps(frame, ensure_ascii=False)


CUSTOM_CN = """主公但有吩咐，臣必效死。

【上策】屯粮固本
策令：于新野推行屯田制

【下策】结援江东
策令：遣使赴吴结盟

【玩家决策解析】你说"休养生息"——我理解为：不扩军、减税、全力屯田
策令：税率降至 0.15
策令：新野、江夏推行屯田制
策令：本季不募兵（休养生息不含扩军）
"""


def test_player_plan_block_is_parsed_as_fourth_option():
    """第 4 块「玩家决策解析」必须被识别成一个独立档位（PRD 的第三选项）。"""
    cards = parse_advisor_strategies(CUSTOM_CN)
    assert [c["tier"] for c in cards] == ["上策", "下策", "玩家决策解析"]
    plan = extract_custom_plan(CUSTOM_CN)
    assert plan is not None
    assert "休养生息" in plan["understanding"]
    assert len(plan["commands"]) == 3, "模糊意图应被拆成多条具体政令"


def test_multi_command_block_exposes_commands_list():
    """一块多条政令时给出 commands 数组；单条时保持旧形状（向后兼容）。"""
    last = parse_advisor_strategies(CUSTOM_CN)[-1]
    assert len(last["commands"]) == 3
    assert last["command"] == last["commands"][0], "command 仍应是第一条（旧前端读它）"
    single = parse_advisor_strategies("【上策】A\n策令：甲")
    assert "commands" not in single[0], "单命令块不应新增字段"


def test_english_alias_maps_to_player_plan():
    txt = "【Your Plan】You want to be bolder.\nDecree: recruit 3000\nDecree: march on Fancheng"
    cards = parse_advisor_strategies(txt)
    assert cards[0]["tier"] == "玩家决策解析"
    assert len(cards[0]["commands"]) == 2


def test_structured_frame_carries_custom_plan():
    frame = build_structured_advice(CUSTOM_CN)
    assert frame["custom"] is not None
    assert len(frame["custom"]["commands"]) == 3
    # strategies 只装军师方案：同一块不得在 strategies 与 custom 里各出现一次
    assert [s["tier"] for s in frame["strategies"]] == ["上策", "下策"]
    assert "玩家决策解析" not in [s["tier"] for s in frame["strategies"]]
    json.dumps(frame, ensure_ascii=False)


def test_old_three_option_output_still_parses():
    """旧格式（只有上/中/下策）必须继续工作。"""
    old = "【上策】A\n策令：甲\n\n【中策】B\n策令：乙\n\n【下策】C\n策令：丙"
    assert [c["tier"] for c in parse_advisor_strategies(old)] == ["上策", "中策", "下策"]
    assert build_structured_advice(old)["custom"] is None


def test_prompts_require_the_fourth_block():
    """两个 system prompt 都必须含第 4 块规则，且覆盖三种输入形态。"""
    cn = (PROMPTS / "advisor.md").read_text(encoding="utf-8")
    assert "玩家决策解析（第四块" in cn
    for kw in ("明确命令", "模糊意图", "提问", "不要复述"):
        assert kw in cn, f"中文 prompt 缺少: {kw}"
    en = (PROMPTS / "advisor_en.md").read_text(encoding="utf-8")
    assert "Player's Plan (fourth block" in en
    for kw in ("Explicit order", "Vague intent", "Question", "Do not paraphrase"):
        assert kw in en, f"英文 prompt 缺少: {kw}"


def test_user_instruction_asks_for_the_fourth_block():
    src = (REPO / "histrategy" / "server" / "api.py").read_text(encoding="utf-8")
    assert "【玩家决策解析】〈一句话说出你如何理解主公的原话" in src
    assert "【Your Plan】<one line: how you interpreted the commander" in src


def _frontend_parser_js(tmp: Path) -> str | None:
    """抽出前端 TS 函数、剥掉类型标注，生成可在 node 里跑的 JS。"""
    if not TS_SRC.exists():
        return None
    src = TS_SRC.read_text(encoding="utf-8")
    start = src.index("export function parseAdvisorStrategies")
    end = src.index("\n}", start) + 2
    out = ["function parseAdvisorStrategies(text) {"]
    for line in src[start:end].split("\n")[1:]:
        if "const cards:" in line:
            line = re.sub(r"const cards:.*?=\s*", "const cards = ", line)
        if re.match(r"\s*let m:", line):
            line = "  let m;"
        if "const tierNorm:" in line:
            line = re.sub(r"const tierNorm:.*?=\s*", "const tierNorm = ", line)
        out.append(line)
    js = "\n".join(out)
    path = tmp / "ts_parser.js"
    path.write_text(
        js
        + "\nconst text = require('fs').readFileSync(process.argv[2], 'utf8');"
        + "\nprocess.stdout.write(JSON.stringify(parseAdvisorStrategies(text)));\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.mark.skipif(
    shutil.which("node") is None or not TS_SRC.exists(),
    reason="需要 node 与前端仓库（surprisal-portal）才能做跨实现比对",
)
def test_matches_frontend_typescript_implementation(tmp_path):
    """逐样例比对：后端 Python 版是否与**前端真实的 TS 实现**行为一致。

    这比"自己跟自己比"有意义 —— 两份实现在同一份格式上必须给出相同结果，
    否则服务端帧与前端卡片会不一致（玩家看到的东西两处不同）。
    """
    js_path = _frontend_parser_js(tmp_path)
    assert js_path
    fixtures = {"cn": CN, "en": EN, "intercept": INTERCEPT, "malformed": "眼下宜静观其变。"}
    for name, text in fixtures.items():
        f = tmp_path / f"{name}.txt"
        f.write_text(text, encoding="utf-8")
        r = subprocess.run(["node", js_path, str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"node 执行失败: {r.stderr[:200]}"
        ts_cards = json.loads(r.stdout)
        assert parse_advisor_strategies(text) == ts_cards, f"[{name}] 前后端解析结果不一致"


# ─────────────────────────────────────────────────────────────
# parse_option_commands：在**解析阶段**就把各选项政令解析成结构化 commands
# （原先只有提交后 /command 回包才带，玩家决策时看不到"我这条会做什么"）
# ─────────────────────────────────────────────────────────────
def test_parse_option_commands_shape_and_order():
    from histrategy.llm.advisor_strategies import parse_option_commands

    frame = {
        "type": "strategies",
        "custom": {"understanding": "x", "commands": ["降低税率至0.15", "派使者缔结盟约"]},
        "strategies": [
            {"tier": "上策", "title": "t", "command": "征兵五千"},
            {"tier": "下策", "title": "t", "command": ""},          # 空命令：应跳过
            {"tier": "下策", "title": "t", "command": "征兵三千加固城防"},
        ],
    }
    out = parse_option_commands(frame, "shu", None)
    assert out is not None and out["type"] == "parsed_commands"
    # 下标对齐契约：输出与输入同长同序，前端据此把 chips 挂到对应选项
    assert len(out["custom"]) == 2, "custom 应按政令逐条一一对应"
    assert len(out["strategies"]) == 3, "strategies 应与输入同长（按下标对齐）"
    assert out["strategies"][1] == [], "空命令处应留空列表占位（保持下标对齐）"
    assert out["strategies"][0] and out["strategies"][2]
    for bucket in (out["custom"], out["strategies"]):
        for cmds in bucket:
            assert isinstance(cmds, list)
            for c in cmds:
                assert set(c) >= {"type", "params"}, c


def test_parse_option_commands_returns_none_without_commands():
    from histrategy.llm.advisor_strategies import parse_option_commands

    assert parse_option_commands({"custom": {}, "strategies": []}, "shu", None) is None
    assert parse_option_commands({}, "shu", None) is None


def test_parse_option_commands_survives_a_failing_entry(monkeypatch):
    """单条解析失败只丢该条 —— 这是增强信息，不该拖垮整条军师流。"""
    import histrategy.llm.advisor_strategies as mod

    calls = {"n": 0}
    real_parse = None
    try:
        from histrategy.parser.intent import IntentParser

        real_parse = IntentParser.parse
    except Exception:
        pass

    def _boom(self, text, faction_id):
        calls["n"] += 1
        if "炸" in text:
            raise RuntimeError("boom")
        return real_parse(self, text, faction_id)

    monkeypatch.setattr("histrategy.parser.intent.IntentParser.parse", _boom, raising=False)
    frame = {"custom": {"commands": ["炸一条"]}, "strategies": [{"command": "征兵五千"}]}
    out = mod.parse_option_commands(frame, "shu", None)
    assert out is not None, "一条失败不该让整帧消失"
    assert out["custom"] == [[]], "失败的那条应为空列表"
    assert out["strategies"][0], "同帧里其它条目仍应解析成功"


def test_parsed_commands_uses_the_same_parser_as_the_game(monkeypatch):
    """必须复用 IntentParser（同一份解析逻辑），不得另写第三份实现。

    前后端各有一份解析实现已经够危险了；这里做源码级约束。
    """
    import pathlib
    import re as _re

    src = pathlib.Path(mod_path := __file__).parent.parent / "llm" / "advisor_strategies.py"
    text = src.read_text(encoding="utf-8")
    assert "from histrategy.parser.intent import IntentParser" in text
    assert _re.search(r"IntentParser\(llm_adapter\)\.parse\(", text), "应使用 IntentParser(...).parse(...)"
    assert mod_path  # 占位，避免 lint 报未使用
