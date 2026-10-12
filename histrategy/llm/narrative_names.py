"""叙事层名称归一化 —— 原始 ID / 拼音名 不得进入正文。

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

* 领地中文名来自已加载的 ``WorldState.territories[tid].name``（每个剧本自带
  ``territories.json``），静态表只作 fallback，最后才退回原始 ID。
* 人物中文名来自剧本人物册（``id`` / ``name`` / ``alias`` / ``name_en``，
  外加由 id 推出的拼音形式 ``gu_yong`` → ``Gu Yong``）。

**查不到的人物名一律丢弃**，不把拼音放进正文。丢弃是安全的：
``state_applier`` 对 ``political_events`` 只记日志、不改状态
（见 ``state_applier.py``：\"Political events (log only, no state mutation)\"），
所以这些键本来就只是叙事调料。
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
    "territory_display_name",
    "faction_display_name",
    "normalize_macro_delta_for_narrative",
]

_TERRITORY_KEYS = {"territory", "territories", "location", "capital", "target", "source"}
_FACTION_KEYS = {"faction", "attacker", "defender"}
_CHARACTER_LOYALTY_KEYS = {"character_loyalty", "character_loyalties", "loyalty"}


def normalize_key(value: object) -> str:
    """把任意写法折叠成比较用的键：小写、下划线/连字符/多空格 → 单空格。"""
    return re.sub(r"[\s_\-]+", " ", str(value).strip().lower())


def _pinyin_form(char_id: str) -> str:
    """``gu_yong`` → ``Gu Yong``（模型把 id 直译成英文名时的常见形态）。"""
    return " ".join(part.capitalize() for part in str(char_id).split("_") if part)


def build_character_name_index(world_state) -> dict[str, str]:
    """构建「任意写法 → 中文正名」的索引。

    索引来自当前剧本的人物册，因此对新剧本自动生效，无需维护词表。
    """
    index: dict[str, str] = {}
    characters = getattr(world_state, "characters", None) or {}
    for char_id, char in characters.items():
        canon = getattr(char, "name", "") or str(char_id)
        forms = {
            str(char_id),
            str(char_id).replace("_", ""),      # zheng_zhilong ← zhengzhilong
            _pinyin_form(str(char_id)),
            getattr(char, "name", "") or "",
            getattr(char, "alias", "") or "",
            getattr(char, "name_en", "") or "",
        }
        for form in forms:
            key = normalize_key(form)
            if key and key not in index:
                index[key] = canon
    return index


def canonical_character_name(raw: object, index: dict[str, str]) -> str | None:
    """把模型给出的人物名解析成中文正名；解析不到返回 ``None``（调用方应丢弃）。"""
    if raw is None:
        return None
    key = normalize_key(raw)
    if not key:
        return None
    if key in index:
        return index[key]
    # "Gu Yong" → gu_yong（索引里 id 以裸 id 形式登记）
    compact = key.replace(" ", "_")
    if compact in index:
        return index[compact]
    return None


def _static_territory_map() -> dict[str, str]:
    try:
        from histrategy.engine.names import _TERRITORY_ZH

        return _TERRITORY_ZH
    except ImportError:  # pragma: no cover — 引擎不可用时无 fallback
        return {}


def territory_display_name(territory_id: object, world_state=None) -> str:
    """领地 ID → 中文显示名。

    解析顺序：**已加载的 WorldState 领地对象** → 静态表 → 原始文本。
    第一条是数据驱动的，所以罗马/南明/三国一视同仁；查不到时宁可回退，
    也不猜（避免把中性城池写错归属或名字）。
    """
    if territory_id is None:
        return ""
    tid = str(territory_id)
    if world_state is not None:
        territory = (getattr(world_state, "territories", None) or {}).get(tid)
        name = getattr(territory, "name", None) if territory is not None else None
        if name:
            return str(name)
    static = _static_territory_map().get(tid)
    if static:
        return str(static)
    return tid


def faction_display_name(faction_id: object, world_state=None) -> str:
    """势力 ID → 中文/官方显示名（数据驱动，查不到则原样返回）。"""
    if faction_id is None:
        return ""
    fid = str(faction_id)
    if world_state is not None:
        faction = (getattr(world_state, "factions", None) or {}).get(fid)
        name = getattr(faction, "name", None) if faction is not None else None
        if name:
            return str(name)
    try:
        from histrategy.engine.names import _FACTION_ZH

        if fid in _FACTION_ZH:
            return str(_FACTION_ZH[fid])
    except ImportError:  # pragma: no cover
        pass
    return fid


def _is_territory_key(key: str) -> bool:
    k = str(key).lower()
    return k in _TERRITORY_KEYS or "territor" in k


def _norm_value(value, world_state):
    if isinstance(value, str):
        return territory_display_name(value, world_state)
    if isinstance(value, list):
        return [_norm_value(v, world_state) for v in value]
    return value


def normalize_macro_delta_for_narrative(macro_delta, world_state=None) -> tuple[dict, list[str]]:
    """返回 ``(归一化后的副本, 被丢弃的人物名列表)``。

    * 任何名字里带 ``territor`` 的键、以及 ``location``/``capital``/``target``/
      ``source`` 这类位置键 → 领地中文名；
    * ``character_loyalty`` 的键 → 人物中文正名；查不到则**从副本中删除**，
      并把原名记进第二个返回值，便于日志观察模型编了哪些人。

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
                        canon = canonical_character_name(raw_name, index)
                        if canon is None:
                            dropped.append(str(raw_name))
                            continue
                        resolved[canon] = delta
                    node[key] = resolved
                elif _is_territory_key(key):
                    node[key] = _norm_value(value, world_state)
                elif str(key).lower() in _FACTION_KEYS and isinstance(value, str):
                    # 势力键同样不该漏英文 id（"cao ⚔ shu" 这类），
                    # 解析不到时 faction_display_name 原样返回，不会误改。
                    node[key] = faction_display_name(value, world_state)
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
