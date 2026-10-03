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
