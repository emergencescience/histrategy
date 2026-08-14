"""Shared faction/territory display-name maps and ID extraction helpers.

Migrated from the deprecated ``histrategy.engine.fast_path`` module
(fast-path deterministic simulation was removed). These symbols are still
used across the codebase (single_player, quarterly_resolver, room_manager)
for faction display names, territory Chinese names, and suggestion-id
extraction.
"""

from __future__ import annotations

import re


def extract_suggestion_id(decision: str) -> str | None:
    """Extract [suggestion_id] prefix from a decision string.

    Supports both EARLY_TURNS format (e.g. [faction_t1_action])
    and advisor-card format (e.g. [sug_1719000000_0]).
    """
    m = re.match(r'^\[([a-z0-9_]+)\]', decision)
    return m.group(1) if m else None


_FACTION_ZH = {
    "nanming": "南明",
    "qing": "大清",
    "nongminjun": "农民军",
    "zheng": "郑氏",
    # Three Kingdoms
    "cao": "曹操",
    "shu": "刘备",
    "wu": "孙权",
    "liubiao": "刘表",
    "zhanglu": "张鲁",
    "liuzhang": "刘璋",
    "machao": "马超",
    # Rome Triumvirate
    "octavian": "屋大维",
    "antony": "安东尼",
    "cleopatra": "克利奥帕特拉",
    "senate": "元老院",
    "sextus_pompey": "塞克斯图斯·庞培",
    "lepidus": "雷必达",
}

_FACTION_EN = {
    "nanming": "Southern Ming",
    "qing": "Qing Empire",
    "nongminjun": "Peasant Army",
    "zheng": "Zheng Clan",
    # Rome Triumvirate
    "octavian": "Octavian",
    "antony": "Mark Antony",
    "cleopatra": "Cleopatra VII",
    "senate": "Roman Senate",
    "sextus_pompey": "Sextus Pompey",
    "lepidus": "Lepidus",
    # Three Kingdoms
    "cao": "Cao Cao",
    "shu": "Liu Bei",
    "wu": "Sun Quan",
    "liubiao": "Liu Biao",
    "zhanglu": "Zhang Lu",
    "liuzhang": "Liu Zhang",
    "machao": "Ma Chao",
}

_TERRITORY_ZH = {
    "shandong": "山东", "henan": "河南", "nanjing": "南京",
    "zhejiang": "浙江", "jiangxi": "江西", "huguang": "湖广",
    "fujian": "福建", "guangdong": "广东", "guangxi": "广西",
    "yunnan": "云南", "sichuan": "四川", "beijing": "北京",
    "shengjing": "盛京", "shanxi": "山西", "shaanxi": "陕西",
    "gansu": "甘肃", "yangzhou": "扬州", "xiangyang": "襄阳",
    "taiwan": "台湾",
    # nanming region split (H22a)
    "wuchang": "武昌", "huguang_west": "湖广西部", "huguang_south": "湖广南部",
    "jinan": "济南", "dengzhou": "登州",
    "kaifeng": "开封", "luoyang": "洛阳", "henan_east": "河南东部",
    "chengdu": "成都", "hanzhong": "汉中",
    # three-kingdoms
    "xinye": "新野", "xuchang": "许昌", "ye": "邺城",
    "jiangxia": "江夏",
    "wancheng": "宛城", "beihai": "北海", "ji": "蓟",
    "puyang": "濮阳", "xiapi": "下邳", "changshan": "常山",
    "jianye": "建业", "wu": "吴", "chaisang": "柴桑",
    "lujiang": "庐江", "kuaiji": "会稽", "yuzhang": "豫章",
    "danyang": "丹阳", "jiangkou": "江口", "jiangling": "江陵",
    "changsha": "长沙", "hanshui": "汉水",
}
