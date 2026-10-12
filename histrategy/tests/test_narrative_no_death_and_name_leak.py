"""叙事层两条硬约束的回归测试（2026-10-12）。

1. **死讯不入叙事** —— 用户裁定：人物的生死不是玩家需要关心的事。
   生产房间 8f9c5147…（60 回合）里 56/60 季出现「孙坚、袁绍、董卓…俱病故」，
   房间 d6272dbf…（8 回合）Q1「刘表病故」与 Q4「刘表病笃」自相矛盾。
   两个来源都在叙事层：``narrative_context`` 的「人物变易」段与
   ``NarrativeEngine._offline_narrative`` 的「X于Y年病故」句。
   → 这里钉住：引擎事件里纵有 ``natural_death``，渲染结果也不得出现死讯。

2. **原始 ID / 拼音名不得进入正文** —— ``state_changes.territory_names`` 曾
   混入 ``jiangzhou``/``nanjun``（三国静态表漏登记；罗马 19/19 全缺），
   macro_delta 里模型给出的拼音人名（``Gu Yong``/``Zhang Zhao``）曾被
   ``str(macro_delta)`` 原样塞进提示词，正文遂写成「顾 Yong」。
   → 这里钉住：领地名从已加载的世界状态解析；人物键归一到中文正名，
   查不到的从叙事副本里剔除。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from histrategy.engine.quarterly_resolver import _resolve_territory_name
from histrategy.llm.narrative_context import format_baseline_for_narrative
from histrategy.llm.narrative_names import (
    build_character_name_index,
    canonical_character_name,
    normalize_macro_delta_for_narrative,
    territory_display_name,
)

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "scenarios"
PROMPTS = REPO / "histrategy" / "llm" / "prompts"

_CJK = re.compile(r"[\u4e00-\u9fff]")
# 叙事正文里绝不允许出现的死讯措辞
DEATH_WORDS = ["病故", "病逝", "阵亡", "殉国", "寿终", "身死", "战死", "辞世", "殒命"]


def _ws(territories=None, characters=None):
    return SimpleNamespace(
        territories={tid: SimpleNamespace(name=name) for tid, name in (territories or {}).items()},
        characters={
            cid: SimpleNamespace(name=spec["name"], alias=spec.get("alias", ""))
            for cid, spec in (characters or {}).items()
        },
    )


# ── 1. 死讯不入叙事 ─────────────────────────────────────────────────────────


def test_baseline_context_drops_death_events_but_keeps_loyalty():
    baseline = SimpleNamespace(
        character_events=[
            {"type": "natural_death", "character_name": "孙坚", "year": 208},
            {"type": "loyalty_change", "character_name": "荀彧", "delta": -3, "reason": "合法性低落"},
            {"type": "defection", "character_name": "张松", "new_faction": "shu"},
        ],
    )
    out = format_baseline_for_narrative(baseline)
    for word in DEATH_WORDS:
        assert word not in out, f"人物变易段仍输出死讯：{word}"
    assert "孙坚" not in out, "亡故人物仍出现在叙事上下文里"
    assert "忠诚" in out and "荀彧" in out, "忠诚变化被误删"
    assert "叛逃" in out and "张松" in out, "叛逃事件被误删"


def test_narrative_length_budget_and_death_ban_survive_together():
    """两条约束互不挤占：字数预算仍在，且新增了禁死讯规则。"""
    for path, budget in (
        (PROMPTS / "global_narrative.md", "90-150 字"),
        (PROMPTS / "narrative.md", "60-125 字"),
    ):
        txt = path.read_text(encoding="utf-8")
        assert budget in txt
        assert "人物生死不入叙事" in txt, f"{path.name} 缺少禁死讯规则"


@pytest.mark.parametrize(
    "path",
    [
        PROMPTS / "global_narrative.md",
        PROMPTS / "global_narrative_en.md",
        PROMPTS / "narrative.md",
        PROMPTS / "narrative_en.md",
        SCENARIOS / "nanming" / "prompts" / "global_narrative_zh.md",
        SCENARIOS / "nanming" / "prompts" / "narrative_zh.md",
    ],
)
def test_no_prompt_still_asks_for_death_reports(path):
    """契约测试：提示词不得再要求模型记录死讯（否则规则与实现脱节）。"""
    txt = path.read_text(encoding="utf-8")
    for bad in ("记录死讯、叛逃", "人物亡故、叛逃", "character_events, record deaths",
                "record deaths, defections", "deaths, defections, loyalty"):
        assert bad not in txt, f"{path.name} 仍在要求记录死讯：{bad!r}"


# ── 2. 领地名与人物名归一 ───────────────────────────────────────────────────


def test_territory_name_prefers_loaded_world_state():
    """数据驱动优先：即使静态表里没有，也要用已加载领地的中文名。"""
    ws = _ws({"nowhere_city": "无名城"})
    assert territory_display_name("nowhere_city", ws) == "无名城"
    assert _resolve_territory_name("nowhere_city", ws) == "无名城"


def test_territory_name_falls_back_to_static_map():
    """静态表补齐了三国缺失的两块地（生产实测泄漏的正是它们）。"""
    assert _resolve_territory_name("jiangzhou") == "江州"
    assert _resolve_territory_name("nanjun") == "南郡"


@pytest.mark.parametrize("scenario", ["three-kingdoms", "nanming", "rome-triumvirate"])
def test_every_scenario_territory_resolves_to_a_chinese_name(scenario):
    """契约测试：任何剧本的领地 id 都必须解析成中文名，不得回落成英文 id。

    罗马剧本此前 19/19 全部回落（静态表只有三国+南明），这条用例就是
    为那次泄漏钉的钉子。
    """
    data = json.loads((SCENARIOS / scenario / "knowledge" / "territories.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("territories", data)
    entries = entries if isinstance(entries, list) else list(entries.values())
    ws = _ws({t["id"]: t.get("name", "") for t in entries})
    for entry in entries:
        resolved = territory_display_name(entry["id"], ws)
        assert _CJK.search(resolved), f"{scenario}: {entry['id']} 未解析成中文名 → {resolved!r}"


def test_character_name_index_maps_pinyin_forms_and_aliases():
    ws = _ws(characters={"gu_yong": {"name": "顾雍", "alias": "元叹"}})
    index = build_character_name_index(ws)
    assert canonical_character_name("Gu Yong", index) == "顾雍"
    assert canonical_character_name("gu_yong", index) == "顾雍"
    assert canonical_character_name("顾雍", index) == "顾雍"
    assert canonical_character_name("元叹", index) == "顾雍"
    assert canonical_character_name("Zhang Zhao", index) is None
    # 生产实测：模型有时给「去掉下划线的 id」写法
    idx2 = build_character_name_index(_ws(characters={"zheng_zhilong": {"name": "郑芝龙"}}))
    assert canonical_character_name("zhengzhilong", idx2) == "郑芝龙"


def test_macro_delta_is_normalized_and_pinyin_names_are_dropped():
    """生产实测的那份 macro_delta：拼音人名 + 原始领地 id。"""
    ws = _ws(
        territories={"jianye": "建业", "nanjun": "南郡"},
        characters={"gu_yong": {"name": "顾雍", "alias": "元叹"}},
    )
    macro_delta = {
        "battle_results": [
            {"location": "jianye", "attacker": "shu", "defender": "cao", "result": "defense_held"}
        ],
        "morale_events": [{"faction": "wu", "territories_affected": ["jianye", "nanjun"]}],
        "political_events": [
            {
                "faction": "wu",
                "type": "court_intrigue",
                "effects": {"character_loyalty": {"Gu Yong": -3, "Zhang Zhao": -5}},
            }
        ],
    }
    safe, dropped = normalize_macro_delta_for_narrative(macro_delta, ws)

    assert safe["morale_events"][0]["territories_affected"] == ["建业", "南郡"]
    assert safe["political_events"][0]["effects"]["character_loyalty"] == {"顾雍": -3}
    assert dropped == ["Zhang Zhao"], "查不到的人物名应被记录并剔除，而不是写进正文"
    assert safe["battle_results"][0]["location"] == "建业"
    assert safe["battle_results"][0]["attacker"] == "刘备"
    # 原字典不得被就地修改（真状态必须保持不变）
    assert macro_delta["morale_events"][0]["territories_affected"] == ["jianye", "nanjun"]
    assert macro_delta["political_events"][0]["effects"]["character_loyalty"] == {
        "Gu Yong": -3,
        "Zhang Zhao": -5,
    }


# ── 3. 语言感知：英文读者不得读到中文（2026-10-12 用户提问） ──────────────────


def _ws_i18n():
    """罗马式剧本：势力和领地都带 name_en（三国没有 name_en）。"""
    return SimpleNamespace(
        territories={
            "sicilia": SimpleNamespace(name="西西里", name_en="Sicily"),
            "jianye": SimpleNamespace(name="建业", name_en=""),        # 三国式：无 name_en
        },
        factions={
            "octavian": SimpleNamespace(name="屋大维", name_en="Octavian"),
            "cao": SimpleNamespace(name="曹操军", name_en=""),
        },
        characters={
            "octavian": SimpleNamespace(name="屋大维", alias="", name_en="Octavian"),
        },
    )


def test_english_narrative_gets_english_names_not_chinese():
    ws = _ws_i18n()
    macro_delta = {
        "battle_results": [
            {"location": "sicilia", "attacker": "octavian", "defender": "cao", "result": "rout"}
        ],
        "morale_events": [{"faction": "octavian", "territories_affected": ["sicilia", "jianye"]}],
        "political_events": [
            {"faction": "octavian", "effects": {"character_loyalty": {"Octavian": -3, "Mark Antony": -5}}}
        ],
    }
    safe, dropped = normalize_macro_delta_for_narrative(macro_delta, ws, is_en=True)

    assert safe["battle_results"][0]["location"] == "Sicily"      # name_en 优先
    assert safe["battle_results"][0]["attacker"] == "Octavian"
    assert safe["morale_events"][0]["territories_affected"] == ["Sicily", "jianye"]
    # 英文叙事查不到的人物名**保留原样**（拉丁原文可读，等同改动前行为）
    assert safe["political_events"][0]["effects"]["character_loyalty"] == {
        "Octavian": -3,
        "Mark Antony": -5,
    }
    assert dropped == []
    # 铁律：英文叙事里不得出现任何汉字
    assert not re.search(r"[\u4e00-\u9fff]", json.dumps(safe, ensure_ascii=False))


def test_chinese_narrative_still_maps_and_still_drops_pinyin():
    """反过来也要钉住：中文叙事不得因为加了英文分支而退化。"""
    ws = _ws_i18n()
    macro_delta = {
        "battle_results": [{"location": "sicilia", "attacker": "octavian"}],
        "political_events": [{"effects": {"character_loyalty": {"Mark Antony": -5}}}],
    }
    safe, dropped = normalize_macro_delta_for_narrative(macro_delta, ws, is_en=False)

    assert safe["battle_results"][0]["location"] == "西西里"
    assert safe["battle_results"][0]["attacker"] == "屋大维"
    assert safe["political_events"][0]["effects"]["character_loyalty"] == {}
    assert dropped == ["Mark Antony"]


@pytest.mark.parametrize(
    "tid,expected_en,expected_zh",
    [("sicilia", "Sicily", "西西里"), ("jianye", "jianye", "建业")],
)
def test_territory_display_name_is_language_aware(tid, expected_en, expected_zh):
    ws = _ws_i18n()
    assert territory_display_name(tid, ws, is_en=True) == expected_en
    assert territory_display_name(tid, ws, is_en=False) == expected_zh
