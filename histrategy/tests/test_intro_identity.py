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

# 世界里持有领地的势力（见 scenarios/three-kingdoms/knowledge/initial_state.json）。
# 其中只有 cao/shu/wu 可玩、参与 AI 决策；liubiao/liuzhang 仅据地（见文件末尾的模型说明）。
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


from histrategy.engine.helpers import (  # noqa: E402
    EARLY_TURNS_SUGGESTIONS,
    FIRST_TURN_SUGGESTIONS,
    GENERIC_EARLY_SUGGESTIONS,
)
from histrategy.engine.intro_plan import _resolve_early_suggestions  # noqa: E402

# ─────────────────────────────────────────────────────────────
# 势力分层的**事实模型**（founder 2026-10-03 明确）：
#   三国剧本只有 3 股需要 npc_decision 的势力：魏 / 蜀 / 吴（也是仅有的可玩势力）。
#   刘表、刘璋只是**据地势力**：地图上持有领地，但既不可选、也不参与 AI 决策。
# 下面把这条模型钉住 —— 免得有人（包括我）再为不可选势力写专属内容，或反过来
# 让不该决策的势力拿到决策。
# ─────────────────────────────────────────────────────────────
from histrategy.engine.faction_slot import (  # noqa: E402
    LLM_NPC_FACTIONS,
    PLAYABLE_FACTIONS,
)

SELECTABLE = {"cao": "曹操", "shu": "刘备", "wu": "孙权"}
INERT = {"liubiao": "刘表", "liuzhang": "刘璋"}  # 据地势力：不可选、不决策
ALL_WORLD = {**SELECTABLE, **INERT}

# 各家的"独有地名/符号"，用来判定有没有串用别人的方略
FACTION_MARKERS = {
    "cao": ("邺城", "许昌", "玄武池", "南征荆州"),
    "shu": ("新野", "隆中", "诸葛亮"),
    "wu": ("鄱阳湖", "建业", "周瑜"),
}


def test_three_kingdoms_has_exactly_three_decision_factions():
    """三国只有魏蜀吴需要 npc_decision，也只有这三家可玩。"""
    assert PLAYABLE_FACTIONS == ["cao", "shu", "wu"], PLAYABLE_FACTIONS
    assert LLM_NPC_FACTIONS == {"cao", "shu", "wu"}, LLM_NPC_FACTIONS


def test_territory_holders_are_not_decision_factions():
    """刘表/刘璋在世界里持有领地，但**不在**可玩/决策集合里（founder 的模型）。"""
    for fid in INERT:
        assert fid not in PLAYABLE_FACTIONS, f"{fid} 不该可玩"
        assert fid not in LLM_NPC_FACTIONS, f"{fid} 不该参与 AI 决策"


@pytest.mark.parametrize("fid", sorted(SELECTABLE))
def test_selectable_faction_has_its_own_turn1_suggestions(fid):
    got = _resolve_early_suggestions("three-kingdoms", fid, 1, "zh")
    assert got, f"{fid}: 可玩势力必须有专属开局建议"


@pytest.mark.parametrize("fid", sorted(INERT))
def test_inert_faction_has_no_own_package(fid):
    """据地势力**不写**专属内容（不做无用功）；它们靠中性兜底。"""
    assert _resolve_early_suggestions("three-kingdoms", fid, 1, "zh") == []
    assert fid not in FIRST_TURN_SUGGESTIONS


def test_selectable_packages_are_distinct():
    """可玩三家的方略必须各不相同 —— 串用别人整套的最直接形式是"两家一模一样"。"""
    pkgs = {fid: tuple(_resolve_early_suggestions("three-kingdoms", fid, 1, "zh")) for fid in SELECTABLE}
    for fid, pkg in pkgs.items():
        assert pkg, f"{fid} 没有专属方略"
    assert len(set(pkgs.values())) == len(pkgs), f"有势力共用同一套方略: {pkgs}"


def test_the_original_symptom_markers_still_detect_caos_package():
    """**正向对照**：先证明"标记法"真能认出曹操那套（否则下面的负向断言是空转）。"""
    caos = " ".join(_resolve_early_suggestions("three-kingdoms", "cao", 1, "zh"))
    assert "南征刘表" in caos and "邺城" in caos, f"曹操的方略里应含这些标记: {caos[:80]}"


@pytest.mark.parametrize("fid", sorted(INERT))
def test_inert_factions_never_get_anyones_package(fid):
    """据地势力（刘表/刘璋）不得拿到任何一家的整套方略。

    原 bug：刘表拿到曹操那套，第一条就是「【南征荆州】整编水师于邺城玄武池…
    准备南征刘表」—— 建议他打自己。用上一条已证有效的标记来判定。
    """
    own = _resolve_early_suggestions("three-kingdoms", fid, 1, "zh")
    effective = " ".join(own if own else GENERIC_EARLY_SUGGESTIONS["zh"])
    for m in ("邺城", "玄武池", "南征刘表", "南征荆州", "鄱阳湖", "隆中对策"):
        assert m not in effective, f"{fid} 拿到了别人的方略（含「{m}」）: {effective[:88]}"


def test_generic_fallback_is_neutral_lang_aware_and_never_named():
    assert set(GENERIC_EARLY_SUGGESTIONS) >= {"zh", "en"}
    for lang, items in GENERIC_EARLY_SUGGESTIONS.items():
        assert items, lang
        blob = " ".join(items)
        for name in ("曹操", "刘备", "孙权", "Cao Cao", "Liu Bei", "Sun Quan"):
            assert name not in blob, f"通用建议里点名了 {name}（就不是通用建议了）"


def test_english_suggestions_contain_no_han_characters():
    """原兜底是中文的，英文玩家也会收到中文方略。"""
    import re as _re

    for fid in sorted(SELECTABLE):
        got = _resolve_early_suggestions("three-kingdoms", fid, 1, "en")
        assert got, f"{fid}: 缺英文开局建议"
        han = _re.findall(r"[\u4e00-\u9fff]+", " ".join(got))
        assert not han, f"{fid} 的英文建议里混入汉字: {han[:3]}"


def test_three_call_sites_no_longer_fall_back_to_cao():
    """三处调用点都不得再以曹操为默认值 —— 源码级断言，防止回退。"""
    for rel in ("engine/intro_plan.py", "engine/turn_processor.py"):
        src = (REPO / "histrategy" / rel).read_text(encoding="utf-8")
        assert 'FIRST_TURN_SUGGESTIONS["cao"]' not in src, f"{rel} 又回退到曹操的方略了"
        assert "GENERIC_EARLY_SUGGESTIONS" in src, f"{rel} 未接入通用兜底"


def test_first_turn_alias_still_covers_the_three_selectable_factions():
    assert set(FIRST_TURN_SUGGESTIONS) == set(SELECTABLE)
    for fid in SELECTABLE:
        assert EARLY_TURNS_SUGGESTIONS["three-kingdoms"][fid][1]["zh"]
