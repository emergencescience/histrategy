"""叙事层名称归一化 —— 原始 ID / 拼音名 不得进入正文（按语言分别处理）。

背景（2026-10-12，生产房间 8f9c5147… 与 d6272dbf… 实测）：

1. **人物名泄漏**：macro_simulator 的契约要求 ``character_loyalty`` 的键用
   人物 **id**（见 ``macro_policy_engine.py`` 的 schema 示例 ``{"xunyu": -5}``），
   但模型实际输出了拼音 / 英文名 ——
   ``{'Cao Ren': -3, 'Le Jin': -2}`` / ``{'Zhang Zhao': -5, 'Gu Yong': -3}``。
   这份 JSON 过去被 ``str(macro_delta)`` 原样塞进叙事提示词，于是正文写成
   「主和派张昭、**顾 Yong** 各失忠五、三分」。

2. **领地 ID 泄漏**：``state_changes.faction_stats[].territory_names`` 由
   ``quarterly_resolver._resolve_territory_name()`` 生成，它只查一张**硬编码**的
   静态表（``engine/names.py::_TERRITORY_ZH``）。三国缺 ``jiangzhou``/``nanjun``；
   罗马剧本 19/19 全部缺失 —— 于是英文 ID 混进中文列表，并在前端 HUD 露底。

本模块用**数据**而不是词表来修：

* 领地/势力名来自已加载的 ``WorldState``（每个剧本自带 ``territories.json`` /
  ``factions.json``，对新剧本天然生效）；静态表只作 fallback，最后退回原始 ID。
* 人物名来自剧本人物册（``id`` / 去下划线 id / 拼音形式 / ``name`` / ``alias``
  / ``name_en``）。

**语言是必须区分的**（2026-10-12 用户指出「英文读者会不会读到中文」）：
``language == "en"`` 时优先取 ``name_en``，取不到就**保持原样**（原文至少是拉丁
字母，与改动前行为一致）；只有中文叙事才归一到中文，且中文叙事里**查不到的人物
名一律丢弃**——绝不让拼音混进中文正文。丢弃是安全的：``state_applier`` 对
``political_events`` 只记日志、不改状态（见 ``state_applier.py``：
\"Political events (log only, no state mutation)\"），这些键本来就只是叙事调料。

生产实测：全库 5,799 条叙事提示词里英文叙事 = **0** 条，所以这条语言分支目前
是给未来英文玩家兜底的，不是修一个正在发生的故障。
"""

from __future__ import annotations

import copy
import logging
import re

logger = logging.getLogger("histrategy.narrative_names")

__all__ = [
    "normalize_key",
    "build_character_name_index",
    "canonical_character_name",
    "character_display_name",
    "territory_display_name",
    "faction_display_name",
    "normalize_macro_delta_for_narrative",
]

_TERRITORY_KEYS = {"territory", "territories", "location", "capital", "target", "source"}
_FACTION_KEYS = {"faction", "attacker", "defender"}
_CHARACTER_LOYALTY_KEYS = {"character_loyalty", "character_loyalties", "loyalty"}

_CJK = re.compile(r"[\u4e00-\u9fff]")


def normalize_key(value: object) -> str:
    """把任意写法折叠成比较用的键：小写、下划线/连字符/多空格 → 单空格。"""
    return re.sub(r"[\s_\-]+", " ", str(value).strip().lower())


def _pinyin_form(char_id: str) -> str:
    """``gu_yong`` → ``Gu Yong``（模型把 id 直译成英文名时的常见形态）。"""
    return " ".join(part.capitalize() for part in str(char_id).split("_") if part)


def _first_cjk(*candidates) -> str | None:
    """取第一个含汉字的候选名（用于中文叙事，避免把拉丁名混进中文正文）。"""
    for candidate in candidates:
        if candidate and _CJK.search(str(candidate)):
            return str(candidate)
    return None


def build_character_name_index(world_state) -> dict[str, tuple[str, str]]:
    """构建「任意写法 → (中文正名, 英文正名)」的索引。

    索引来自当前剧本的人物册，因此对新剧本自动生效，无需维护词表。
    英文名缺失时第二项为空串（三国剧本即如此）。
    """
    index: dict[str, tuple[str, str]] = {}
    characters = getattr(world_state, "characters", None) or {}
    for char_id, char in characters.items():
        zh = getattr(char, "name", "") or str(char_id)
        en = getattr(char, "name_en", "") or ""
        forms = {
            str(char_id),
            str(char_id).replace("_", ""),      # zheng_zhilong ← zhengzhilong
            _pinyin_form(str(char_id)),
            getattr(char, "name", "") or "",
            getattr(char, "alias", "") or "",
            en,
        }
        for form in forms:
            key = normalize_key(form)
            if key and key not in index:
                index[key] = (zh, en)
    return index


def _lookup(raw: object, index: dict):
    if raw is None:
        return None
    key = normalize_key(raw)
    if not key:
        return None
    if key in index:
        return index[key]
    # "Gu Yong" → gu_yong（索引里 id 以裸 id 形式登记）
    return index.get(key.replace(" ", "_"))


def canonical_character_name(raw: object, index: dict) -> str | None:
    """把模型给出的人物名解析成中文正名；解析不到返回 ``None``（调用方应丢弃）。"""
    hit = _lookup(raw, index)
    if hit is None:
        return None
    return hit[0] if isinstance(hit, tuple) else str(hit)


def character_display_name(raw: object, index: dict, is_en: bool = False) -> str | None:
    """人物显示名（语言感知）。

    * ``is_en``：优先英文正名；查不到就**保持原样**（拉丁原文可读，等同改动前行为）。
    * 中文：归一到中文正名；查不到返回 ``None``（调用方丢弃，避免「顾 Yong」）。
    """
    hit = _lookup(raw, index)
    if is_en:
        if hit is None:
            return str(raw)
        zh, en = hit if isinstance(hit, tuple) else (str(hit), "")
        return en or str(raw)
    return canonical_character_name(raw, index)


def _static_territory_map() -> dict[str, str]:
    try:
        from histrategy.engine.names import _TERRITORY_ZH

        return _TERRITORY_ZH
    except ImportError:  # pragma: no cover — 引擎不可用时无 fallback
        return {}


def _static_faction_map() -> dict[str, str]:
    try:
        from histrategy.engine.names import _FACTION_ZH

        return _FACTION_ZH
    except ImportError:  # pragma: no cover
        return {}


def territory_display_name(territory_id: object, world_state=None, is_en: bool = False) -> str:
    """领地 ID → 显示名（语言感知）。

    * ``is_en``：``name_en`` → 原始 ID（罗马/南明有 name_en；三国没有，故保持原样）。
    * 中文：已加载领地对象的 ``name`` → 静态表 → 原始 ID，且只接受含汉字的候选。
    """
    if territory_id is None:
        return ""
    tid = str(territory_id)
    territory = (getattr(world_state, "territories", None) or {}).get(tid) if world_state is not None else None

    if is_en:
        en = getattr(territory, "name_en", None) if territory is not None else None
        return str(en) if en else tid

    return _first_cjk(
        getattr(territory, "name", None) if territory is not None else None,
        _static_territory_map().get(tid),
    ) or tid


def faction_display_name(faction_id: object, world_state=None, is_en: bool = False) -> str:
    """势力 ID → 显示名（语言感知，规则同领地）。"""
    if faction_id is None:
        return ""
    fid = str(faction_id)
    faction = (getattr(world_state, "factions", None) or {}).get(fid) if world_state is not None else None

    if is_en:
        en = getattr(faction, "name_en", None) if faction is not None else None
        return str(en) if en else fid

    return _first_cjk(
        _static_faction_map().get(fid),
        getattr(faction, "name", None) if faction is not None else None,
    ) or fid


def _is_territory_key(key: str) -> bool:
    k = str(key).lower()
    return k in _TERRITORY_KEYS or "territor" in k


def _norm_value(value, world_state, is_en):
    if isinstance(value, str):
        return territory_display_name(value, world_state, is_en)
    if isinstance(value, list):
        return [_norm_value(v, world_state, is_en) for v in value]
    return value


def normalize_macro_delta_for_narrative(
    macro_delta, world_state=None, is_en: bool = False
) -> tuple[dict, list[str]]:
    """返回 ``(归一化后的副本, 被丢弃的人物名列表)``。

    * 任何名字里带 ``territor`` 的键、以及 ``location``/``capital``/``target``/
      ``source`` 这类位置键 → 领地显示名；
    * 势力键 → 势力显示名；
    * ``character_loyalty`` 的键 → 人物显示名。中文叙事里查不到的**从副本中删除**
      并记进第二个返回值（便于日志观察模型编了哪些人）；英文叙事里保留原样。

    只改副本，绝不改真状态。
    """
    dropped: list[str] = []
    if not isinstance(macro_delta, dict):
        return macro_delta, dropped

    index = build_character_name_index(world_state) if world_state is not None else {}
    out = copy.deepcopy(macro_delta)

    def walk(node):
        if isinstance(node, dict):
            for key in list(node.keys()):
                value = node[key]
                if str(key).lower() in _CHARACTER_LOYALTY_KEYS and isinstance(value, dict):
                    resolved = {}
                    for raw_name, delta in value.items():
                        display = character_display_name(raw_name, index, is_en)
                        if display is None:
                            dropped.append(str(raw_name))
                            continue
                        resolved[display] = delta
                    node[key] = resolved
                elif _is_territory_key(key):
                    node[key] = _norm_value(value, world_state, is_en)
                elif str(key).lower() in _FACTION_KEYS and isinstance(value, str):
                    # 势力键同样不该漏英文 id（"cao ⚔ shu" 这类）；中英各自解析，
                    # 解析不到时原样返回，不会误改。
                    node[key] = faction_display_name(value, world_state, is_en)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)
    if dropped:
        logger.warning(
            "macro_delta 含 %d 个无法归一到中文正名的人物键，已从叙事副本中剔除：%s",
            len(dropped),
            ", ".join(sorted(set(dropped))),
        )
    return out, dropped
