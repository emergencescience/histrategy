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
    extract_intercepts,
    parse_advisor_strategies,
)

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
