"""回归保护：军师输出语言（英文页面说中文的 bug）。

真实故障（2026-10-03，房间 b1600eec /en/ 页面）：
英文页上三策的**档位与标题是英文，但「策令」那三行是中文**。审计确认：
后端的 analysis/标题/Decree 标记都是英文格式（`【Upper Strategy】` + `Decree:`），
**唯独 Decree 的正文是中文** —— 全页可见中文恰好只有那三行。

根因（三层，均已修）：
  1. `prompts/advisor_en.md`（system prompt）**通篇没有语言约束** → 模型自由裁量；
     同一 prompt 同参数，我 curl 得到英文、页面得到中文（不稳定）。
  2. `server/api.py` 的英文 user 指令里**混着中文占位符**（`〈title ≤8 words〉`、
     `〈one executable command〉`），且该 system prompt 声明的输出格式
     （STRICT JSON）与端点实际要的三策文本格式并不一致 —— 格式指令全在 user message。
  3. 端点**根本没接收 `lang` 参数**（`api_advisor_stream(room_id, faction_id, goal)`），
     前端发的 `&lang=en` 被 FastAPI 静默忽略，语言只看房间 metadata；
     房间元数据一旦缺失或与页面不一致，就没有纠正手段。
"""
import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.server.api import _resolve_advisor_lang  # noqa: E402

PROMPTS = REPO / "histrategy" / "llm" / "prompts"
API = REPO / "histrategy" / "server" / "api.py"
HAN = re.compile(r"[\u4e00-\u9fff]")


class _Room:
    def __init__(self, metadata):
        self.metadata = metadata


def test_page_lang_wins_over_room_metadata():
    """页面语言必须优先 —— 房间 metadata 可能缺失或与当前页面不符。"""
    assert _resolve_advisor_lang("en", _Room({"lang": "zh"})) == "en"
    assert _resolve_advisor_lang("zh", _Room({"lang": "en"})) == "zh"


def test_falls_back_to_room_metadata_then_zh():
    assert _resolve_advisor_lang("", _Room({"lang": "en"})) == "en"
    assert _resolve_advisor_lang("", _Room(None)) == "zh"
    assert _resolve_advisor_lang("", _Room({})) == "zh"


def test_malformed_metadata_does_not_crash():
    """metadata 若是字符串/异常类型，不得抛异常（旧写法 `getattr(...).get` 会炸）。"""
    assert _resolve_advisor_lang("", _Room("not-a-dict")) == "zh"
    assert _resolve_advisor_lang("", _Room(None)) == "zh"


def test_normalizes_whitespace_and_case():
    assert _resolve_advisor_lang("  EN ", _Room(None)) == "en"


def test_helper_is_not_a_coroutine():
    """必须同步可调用：端点用同步赋值取它，若写成 async 会把协程当字符串用。

    （这个 bug 真发生过 —— 语法检查抓不到，只有运行时调用才会暴露。）
    """
    import inspect

    assert not inspect.iscoroutinefunction(_resolve_advisor_lang)
    assert isinstance(_resolve_advisor_lang("en", _Room(None)), str)


def test_english_system_prompt_pins_the_language():
    """英文 system prompt 必须显式规定输出语言，否则模型会漂回中文。"""
    txt = (PROMPTS / "advisor_en.md").read_text(encoding="utf-8")
    assert re.search(r"Language\s*\(STRICT\)", txt), "缺少语言铁律小节"
    assert "including the `Decree:` line" in txt or "Decree" in txt
    assert "English" in txt


def test_chinese_system_prompt_pins_the_language():
    txt = (PROMPTS / "advisor.md").read_text(encoding="utf-8")
    assert "语言（硬性）" in txt
    assert "一律用中文" in txt


def test_english_user_instruction_has_no_chinese_placeholders():
    """英文分支里不得残留中文占位符 —— 那正是模型把策令写成中文的诱因。

    用 **AST** 抽取 `_stream_advice` 里 `if is_en:` 分支的全部字符串常量，
    而不是按文本锚点截取 —— 这样重构（例如把 query 拆成 base + extra）不会误报，
    但"英文分支混进汉字"这种实质问题一定被抓到。
    """
    tree = ast.parse(API.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_stream_advice"
    )

    def _strings(nodes):
        out = []
        for n in nodes:
            for sub in ast.walk(n):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
        return out

    # 可能有多个 `if is_en:`（目标注入、格式指令各一处）—— 取含格式指令的那个，
    # 且**只看 if 分支本体**（If 节点的 ast.walk 会把 else 分支也算进去，那是中文的）。
    candidates = [
        _strings(node.body)
        for node in ast.walk(fn)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "is_en"
    ]
    en_strs = next((s for s in candidates if any("Output STRICTLY" in x for x in s)), None)
    assert en_strs is not None, "未找到英文格式指令（结构变化需同步本测试）"
    han = [s for s in en_strs if HAN.search(s)]
    assert not han, f"英文分支残留汉字: {han[:3]}"


def test_english_user_instruction_tells_the_model_to_write_english():
    src = API.read_text(encoding="utf-8")
    assert "LANGUAGE: write the analysis, the titles AND every Decree in English" in src


def test_stream_endpoint_accepts_lang_param():
    """端点必须接收 lang，否则前端的 &lang=en 会被 FastAPI 静默忽略。"""
    src = API.read_text(encoding="utf-8")
    assert 'def api_advisor_stream(room_id: str, faction_id: str = "", goal: str = "", lang: str = "")' in src
    assert 'def api_advisor(room_id: str, faction_id: str = "", goal: str = "", lang: str = "")' in src
