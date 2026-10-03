"""回归保护：开局自我介绍不得**冒充别的势力**（intro_plan._offline_intro）。

真事故（2026-10-03 发现）：
    info = intros.get(faction_key, intros["cao"])
`intros` 只登记了 cao/shu/wu 三家，于是任何未登记的势力都会静默拿到曹操的档案 ——
玩家以**刘表**开局，开场白却写「你，曹操，字孟德，挟天子以令诸侯，已平定北方，虎视江南」。
（刘璋同理。）这是玩家可见的身份错误，而它此前被当成"LLM 抖动"长期挂在失败基线里。

为什么补这条测试：暴露它的 `tests/test_e2e_liubiao_llm.py::test_intro_scene_liubiao`
是**真调大模型**的用例（红绿靠运气，见该文件的 llm_e2e 标记）。这里补一条**离线、
确定性**的版本：不调模型、不联网，直接把身份断言钉死。
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from histrategy.engine.game import GameEngine  # noqa: E402

# 与 scenarios/three-kingdoms/knowledge/initial_state.json 里的势力对齐
WORLD_FACTIONS = {
    "cao": "曹操",
    "shu": "刘备",
    "wu": "孙权",
    "liubiao": "刘表",
    "liuzhang": "刘璋",
}


def _intro_line(fid: str, tmp_path: Path) -> str:
    """跑一次开局，取出开场白里「你，…」那一行。"""
    e = GameEngine(new_game=True, force_v1=True)
    e.set_player_faction(fid)
    nar = (e.get_intro_scene() or {}).get("narrative", "") or ""
    lines = [ln for ln in nar.split("\n") if ln.startswith("你，")]
    assert lines, f"{fid}: 开场白里没有「你，…」这一行（identity 缺失）"
    return lines[0]


@pytest.mark.parametrize("fid,want", sorted(WORLD_FACTIONS.items()))
def test_intro_names_the_actual_player_faction(fid, want, tmp_path, monkeypatch):
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path))
    line = _intro_line(fid, tmp_path)
    assert want in line, f"{fid}: 开场白没提到正确的主公 {want}: {line}"


@pytest.mark.parametrize("fid", [f for f in WORLD_FACTIONS if f != "cao"])
def test_non_cao_faction_never_poses_as_cao(fid, tmp_path, monkeypatch):
    """非曹操势力绝不能被自我介绍成曹操 —— 这正是当初那条 bug。"""
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path))
    line = _intro_line(fid, tmp_path)
    assert "曹操" not in line, f"{fid}: 又被冒充成曹操了: {line}"


def test_unregistered_faction_falls_back_without_impersonating(tmp_path, monkeypatch):
    """世界里没有的势力（如 zhanglu）走兜底，也**不得**冒充任何既有主公。"""
    monkeypatch.setenv("HISTRATEGY_DATA_DIR", str(tmp_path))
    e = GameEngine(new_game=True, force_v1=True)
    e.set_player_faction("zhanglu")  # 不在 three-kingdoms 世界里
    nar = (e.get_intro_scene() or {}).get("narrative", "") or ""
    assert nar.strip(), "兜底开场白不该是空的"
    assert "你，曹操" not in nar, f"兜底把玩家冒充成曹操: {nar[:120]}"


# ─────────────────────────────────────────────────────────────
# 同一类 bug 的另一条通道：开局**建议**也会冒充别的势力
#   原写法 FIRST_TURN_SUGGESTIONS.get(fid, FIRST_TURN_SUGGESTIONS["cao"])
#   而 FIRST_TURN_SUGGESTIONS 只有 cao/shu/wu → 未登记势力拿到曹操的方略。
#   玩家以刘表开局（该势力原先未登记）得到的第一条建议就是
#   「【南征荆州】整编水师于邺城玄武池…准备南征刘表」—— 建议他去打自己。
# ─────────────────────────────────────────────────────────────
from histrategy.engine.helpers import (  # noqa: E402
    EARLY_TURNS_SUGGESTIONS,
    GENERIC_EARLY_SUGGESTIONS,
    FIRST_TURN_SUGGESTIONS,
)
from histrategy.engine.intro_plan import _resolve_early_suggestions  # noqa: E402


@pytest.mark.parametrize("fid,want", sorted(WORLD_FACTIONS.items()))
def test_every_world_faction_has_its_own_turn1_suggestions(fid, want):
    got = _resolve_early_suggestions("three-kingdoms", fid, 1, "zh")
    assert got, f"{fid}: 回合 1 没有自己的建议 → 会兜底到别人的方略"


@pytest.mark.parametrize("fid", [f for f in WORLD_FACTIONS if f != "cao"])
def test_no_faction_gets_caos_strategy_package(fid):
    """非曹操势力拿到的一整套建议，不得等于曹操那一套（冒充的最直接形式）。"""
    mine = _resolve_early_suggestions("three-kingdoms", fid, 1, "zh")
    caos = _resolve_early_suggestions("three-kingdoms", "cao", 1, "zh")
    assert mine != caos, f"{fid} 拿到的就是曹操的方略"


def test_liubiao_is_not_advised_to_attack_himself():
    """当初那条 bug 的原样症状：刘表的第一条建议是「准备南征刘表」。"""
    got = " ".join(_resolve_early_suggestions("three-kingdoms", "liubiao", 1, "zh"))
    assert "南征刘表" not in got, f"刘表被建议去打自己: {got[:100]}"
    assert "邺城" not in got, f"建议里出现曹操的都城（说明是曹操的方略）: {got[:100]}"


def test_english_players_get_english_suggestions():
    """兜底曾把**中文**的曹操方略发给英文玩家。按语言兜底后不该再出现。

    只查**汉字**：`【】：` 这类全角标点是刻意的风格（既有英文条目也用），不算"混了中文"。
    """
    import re as _re

    got = _resolve_early_suggestions("three-kingdoms", "liubiao", 1, "en")
    assert got, "英文建议为空"
    han = _re.findall(r"[\u4e00-\u9fff]+", " ".join(got))
    assert not han, f"英文建议里混入汉字: {han[:3]}"


def test_generic_fallback_is_neutral_and_lang_aware():
    assert set(GENERIC_EARLY_SUGGESTIONS) >= {"zh", "en"}
    for lang, items in GENERIC_EARLY_SUGGESTIONS.items():
        assert items, lang
        # 中性建议里不得点名任何具体势力
        blob = " ".join(items)
        for name in ("曹操", "刘备", "孙权", "刘表", "刘璋", "Cao Cao", "Liu Bei", "Sun Quan"):
            assert name not in blob, f"通用建议里点名了 {name}（就不是通用建议了）"


def test_three_call_sites_no_longer_fall_back_to_cao():
    """三处调用点都不得再以曹操为默认值 —— 源码级断言，防止回退。"""
    import pathlib

    for rel in ("engine/intro_plan.py", "engine/turn_processor.py"):
        src = (REPO / "histrategy" / rel).read_text(encoding="utf-8")
        assert 'FIRST_TURN_SUGGESTIONS["cao"]' not in src, f"{rel} 又回退到曹操的方略了"
        assert "GENERIC_EARLY_SUGGESTIONS" in src, f"{rel} 未接入通用兜底"


def test_first_turn_alias_still_covers_the_three_original_factions():
    """向后兼容别名不能被这次改动破坏。"""
    assert set(FIRST_TURN_SUGGESTIONS) >= {"cao", "shu", "wu"}
    for fid in ("cao", "shu", "wu"):
        assert EARLY_TURNS_SUGGESTIONS["three-kingdoms"][fid][1]["zh"]
