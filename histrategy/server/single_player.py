"""
三國志略 — 单人模式 API

薄封装层：单人模式 = 多人房间系统 + 1个人类 + 2个AI NPC
对外暴露旧版 GameCreatedResponse / CommandResponse 格式，
前端体验与之前完全一致。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy.engine.game_room import GameRoom

logger = logging.getLogger("histrategy.single_player")

# 旧 faction key → 内部 ID 映射（已统一为短码，保留映射仅为兼容）
from histrategy.engine.faction_slot import FACTION_ID_TO_DISPLAY, normalize_faction_id

FACTION_KEY_TO_ID = {"cao": "cao", "shu": "shu", "wu": "wu"}
FACTION_KEY_TO_DISPLAY = FACTION_ID_TO_DISPLAY  # {"cao": "caocao", "shu": "liubei", "wu": "sunquan"}

# 轮询参数
RESOLVE_POLL_INTERVAL = 2.0  # 秒
RESOLVE_TIMEOUT = 180.0  # 秒（LLM 最长等待时间）


# ── Public API ────────────────────────────────────────────────────────────────


def start(
    faction: str, scenario: str = "three-kingdoms", language_style: str = "vernacular", lang: str = "zh"
) -> dict:
    """创建单人游戏。

    内部：创建 1人类+2AI 房间 → 初始化世界 → 触发 NPC → 返回 intro

    Args:
        faction: 势力 key (cao | shu | wu)
        scenario: 剧本 (默认 207)
        language_style: 语言风格 (classical | vernacular)
        lang: 界面语言 (zh | en)

    Returns:
        GameCreatedResponse 格式:
        {game_id, scenario, faction, intro: {narrative, npc_actions, ...}, faction_status}
    """
    from histrategy.server.room_manager import (
        _get_room,
        create_room,
    )

    internal_fid = FACTION_KEY_TO_ID.get(faction, faction)
    display_fid = FACTION_KEY_TO_DISPLAY.get(faction, faction)

    # 1. 创建房间：1 个人类（用 pre_assigned）+ AI NPC 自动填充
    result = create_room(

        scenario=scenario,
        pre_assigned={display_fid: "Player"},
        metadata={"lang": lang},
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "创建房间失败")}

    room_id = result["room_id"]
    room = _get_room(room_id)
    if not room:
        return {"ok": False, "error": "房间创建后无法加载"}

    # 2. 构建 intro（初始叙事）
    intro = _build_intro(room, internal_fid, language_style, lang)

    # 3. 构建 faction_status
    faction_status = _build_faction_status(room, internal_fid)

    return {
        "game_id": room_id,
        "scenario": scenario,
        "faction": faction,
        "intro": intro,
        "faction_status": faction_status,
    }


def command(game_id: str, decision: str, lang: str = "zh") -> dict:
    """执行玩家命令（阻塞等待 LLM 推演完成）。

    Args:
        game_id: 房间 ID
        decision: 玩家自然语言决策
        lang: 语言 (zh | en)。优先使用显式传入的值，否则从房间 metadata 读取。
    """
    from histrategy.server.room_manager import (
        _get_room,
        submit_decision,
    )

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏不存在"}

    # Auto-detect lang from room metadata if not explicitly passed
    if lang == "zh":
        room_lang = getattr(room, "metadata", {}).get("lang", "zh")
        if room_lang and room_lang != "zh":
            lang = room_lang

    # 找到人类势力
    human_fid = _find_human_faction(room)
    if not human_fid:
        return {"ok": False, "error": "找不到人类势力"}

    # 记录提交前的 quarter（必须在 submit_decision 之前！）
    prev_quarter = room.quarter_number

    # 1. 提交决策 → 同步 resolve（submit_decision 内部调用 _resolve_and_advance）
    from histrategy.server.room_manager import _trigger_npc_decisions

    submit_result = submit_decision(game_id, human_fid, decision)
    if not submit_result.get("ok"):
        return {"ok": False, "error": submit_result.get("error", "提交决策失败")}

    # 2. 检查 resolve 是否已完成（同步调用，应该已经完成）
    # 不需要轮询 — submit_decision 内部是同步的 _resolve_and_advance
    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏在推演中丢失"}

    if room.quarter_number <= prev_quarter:
        # NPC 决策可能还没生成完（异步线程延迟）
        # 尝试同步触发 NPC 决策并 resolve
        logger.info(f"Room {game_id}: quarter unchanged ({prev_quarter}) — triggering NPC decisions sync")
        try:
            _trigger_npc_decisions(room)
            submit_decision(game_id, human_fid, decision)
        except Exception as e:
            logger.warning(f"Room {game_id}: sync NPC trigger failed: {e}")

        room = _get_room(game_id)
        if not room or room.quarter_number <= prev_quarter:
            return {"ok": False, "error": "推演失败，请重试"}

    # 3. 读取推演结果
    narratives = getattr(room, "_last_narratives", {})
    npc_actions = getattr(room, "_last_npc_actions", [])

    narrative = narratives.get(human_fid, "")
    if not narrative:
        # fallback: 用第一个有内容的叙事
        for n in narratives.values():
            if n:
                narrative = n
                break

    # 4. 构建 state_changes（从 world_state 提取当前状态作为变化）
    faction_status = _build_faction_status(room, human_fid)

    # 5. 构建建议
    suggestions = _build_suggestions(room, human_fid, lang)

    return {
        "game_id": game_id,
        "narrative": narrative or "天下无事。",
        "aftermath": _build_aftermath(faction_status, lang),
        "state_changes": {},  # LLM 推演的变化反映在 faction_status 中
        "events_occurred": _extract_events(room),
        "npc_actions": npc_actions,
        "new_suggestions": suggestions,
        "game_over": None,
        "faction_status": faction_status,
        "year": faction_status.get("year", 207),
        "season": faction_status.get("season", "春"),
        "turn": faction_status.get("turn", 0),
    }


def status(game_id: str) -> dict:
    """获取游戏状态。

    Args:
        game_id: 房间 ID

    Returns:
        {game_id, year, season, turn, faction_status, npc_actions, is_waiting}
    """
    from histrategy.server.room_manager import _get_room

    room = _get_room(game_id)
    if not room:
        return {"ok": False, "error": "游戏不存在"}

    human_fid = _find_human_faction(room)
    faction_status = _build_faction_status(room, human_fid) if human_fid else {}
    npc_actions = getattr(room, "_last_npc_actions", [])

    return {
        "game_id": game_id,
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
        "faction_status": faction_status,
        "npc_actions": npc_actions,
        "is_waiting": room.phase.value == "waiting",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_human_faction(room: GameRoom) -> str | None:
    """找到房间中的人类势力 ID。"""
    for fid, slot in room.slots.items():
        if slot.is_human():
            return fid
    return None


def _build_intro(room: GameRoom, faction_id: str, language_style: str, lang: str = "zh") -> dict:
    """构建初始介绍（old IntroScene 格式）。"""
    # 根据 faction 生成介绍叙事
    narrative = _get_intro_narrative(faction_id, language_style, lang)
    is_en = lang == "en"

    return {
        "narrative": narrative,
        "npc_actions": [],  # NPC 的初始行动（在第一回合推演后才有）
        "new_choices": ["Develop Economy", "Military Action", "Recruit Talent", "Consolidate"]
        if is_en
        else ["发展内政", "对外用兵", "广纳贤才", "休养生息"],
        "state_changes": {},
        "events_occurred": [],
    }


def _get_intro_narrative(faction_id: str, language_style: str, lang: str = "zh") -> str:
    """获取初始叙事文本。"""
    # English narratives
    en_narratives = {
        "cao": "Spring of 207 AD. Cao Cao has pacified the north, controlling the Central Plains with the Emperor as his puppet. His strategists are legion, his generals unmatched. Yet Liu Biao holds Jing Province, Sun Quan rules Jiangdong, and Liu Bei camps at Xinye — the realm remains divided. This spring, Cao Cao summons his court at Xuchang to plan the southern campaign.",
        "shu": "Spring of 207 AD. Liu Bei shelters in the small town of Xinye. Though his army counts barely a few thousand, his heart burns for the Han dynasty. Guan Yu, Zhang Fei, and Zhao Yun are warriors worth a thousand men each — but he lacks a strategist. Word reaches him of a genius recluse at Longzhong named Zhuge Liang. Liu Bei resolves to visit him in person — three times if necessary.",
        "wu": "Spring of 207 AD. Sun Quan inherited his father's and brother's legacy, ruling the six commanderies of Jiangdong. Zhang Zhao governs civil affairs, Zhou Yu commands the fleet, and the Yangtze River is his moat. But Cao Cao glares from the north and Liu Biao presses from the west. Sun Quan knows: survival requires more than defense.",
        "octavian": "44 BC. Julius Caesar lies dead on the Senate floor, and the Roman Republic teeters on the edge of chaos. An 18-year-old named Octavian — Caesar's adopted son and heir — crosses the Adriatic from Apollonia. He has no army, no allies, and no experience. But he has one thing more powerful than legions: the name Gaius Julius Caesar Octavianus. All of Rome watches: can this boy hold the ashes of Caesar's legacy?",
        "antony": "44 BC. Caesar is dead. As his most trusted general, Mark Antony controls Rome and Caesar's legions. But the Senate despises him, Caesar's young heir Octavian challenges his authority, and the Gallic provinces are his last bargaining chip. Antony must choose: stay in Rome and risk everything, or march to Gaul and gather his forces?",
        "cleopatra": "44 BC. News of Caesar's assassination reaches Alexandria. Cleopatra VII, Pharaoh of Egypt, has lost her most powerful Roman protector. She commands the richest granary in the Mediterranean — but in a world run by Roman warlords, what power does a woman truly hold? She must find a new ally among Caesar's successors, or watch Egypt be devoured.",
        "senate": "44 BC. Brutus and Cassius plunged their daggers into Caesar and cried 'The Republic is saved!' — but the people of Rome did not cheer. The Senate holds the eastern provinces, but Antony's legions are marching. The Republic is dying. The only question left: who will strike the final blow?",
    }

    if lang == "en" and faction_id in en_narratives:
        return en_narratives[faction_id]
    narratives = {
        "cao": {
            "classical": "建安十二年春，曹操已平河北，拥兖豫之地，挟天子以令诸侯。帐下谋士如云，猛将如雨，然南方刘表、孙权、刘备各据州郡，天下未定。是岁，曹操于许昌大会群臣，问计于荀彧、郭嘉诸谋士。",
            "vernacular": "公元207年，曹操已平定北方，坐拥中原。挟天子以令诸侯，麾下谋士如云、猛将如雨。然而南方刘表占据荆州，孙权坐断江东，刘备屯兵新野——天下一统的大业，仍前路漫漫。这一年春天，曹操在许昌大会群臣，准备迈出南下的第一步。",
        },
        "shu": {
            "classical": "建安十二年春，刘备寄居新野，虽兵微将寡，然心怀汉室，志在天下。麾下关羽、张飞、赵云皆万人敌，唯缺谋主。闻隆中有贤士诸葛亮，刘备决意三顾茅庐。",
            "vernacular": "公元207年，刘备寄居新野小城。虽然兵力不过数千，但他心怀汉室，志在天下。关羽、张飞、赵云皆是万人敌的猛将，但缺少一位运筹帷幄的军师。听说隆中有一位奇才诸葛亮，刘备决定亲自去拜访。",
        },
        "wu": {
            "classical": "建安十二年春，孙权承父兄基业，坐领江东六郡。内有张昭、周瑜等文武之才，外有长江天险，然北有曹操虎视，西有刘表为邻，孙权日夜思量进取之策。",
            "vernacular": "公元207年，孙权继承父兄的基业，统领江东六郡。文有张昭，武有周瑜，更有长江天险作为屏障。但北方的曹操虎视眈眈，西边的刘表也是一大威胁。孙权深知，偏安一隅终非长久之计。",
        },
        # ── Rome: Ashes of Caesar (44 BC) ──
        "octavian": {
            "classical": "公元前44年，尤利乌斯·恺撒在庞培剧院遇刺身亡，罗马共和国陷入空前的权力真空。年仅18岁的屋大维被遗嘱指定为继承人，从阿波罗尼亚渡海返回意大利。他既无军队，也无政治经验，却拥有恺撒之名——这是罗马最锋利的武器。",
            "vernacular": "公元前44年，恺撒遇刺，罗马陷入混乱。18岁的屋大维突然成了恺撒的继承人。他没有军队，没有盟友，只有一个名字——盖乌斯·尤利乌斯·恺撒·屋大维。整个罗马都在注视着他：这个少年能守住恺撒留下的余烬吗？",
        },
        "antony": {
            "classical": "公元前44年，恺撒遇刺后，其最信任的将军马克·安东尼控制了罗马城。他手握恺撒的军团与财富，却面临元老院的敌意和恺撒继承人的挑战。高卢行省是安东尼最大的筹码——但控制高卢意味着放弃罗马。",
            "vernacular": "公元前44年，恺撒死了。作为他最信任的将军，安东尼控制了罗马城和恺撒的军团。但麻烦才刚刚开始——元老院恨他，恺撒的继承人屋大维在挑战他的权威，而高卢行省是他最后的底牌。安东尼必须做出选择：留下控制罗马，还是去高卢集结军队？",
        },
        "cleopatra": {
            "classical": "公元前44年，恺撒遇刺的消息传到亚历山大里亚，克利奥帕特拉七世失去了罗马最强的庇护者。作为埃及法老，她控制着罗马最重要的粮仓，却身处一个由罗马男人主导的世界。她必须在恺撒的继承者们之间，找到新的盟友。",
            "vernacular": "公元前44年，恺撒死了。对克利奥帕特拉来说，这不只是失去一个情人，更是失去罗马最强的保护伞。她是埃及的法老，控制着罗马的粮仓——但在这个由罗马男人主导的世界里，一个女人如何生存？她必须在这场内战中，找到正确的那一方。",
        },
        "senate": {
            "classical": "公元前44年，布鲁图斯和卡西乌斯刺杀了恺撒，高呼'共和国万岁'——却发现罗马人民并不感谢他们。元老院控制着东部行省，但安东尼的军团正在逼近。共和国已垂死，问题是：谁将给它最后一击？",
            "vernacular": "公元前44年，布鲁图斯和卡西乌斯刺杀了恺撒。他们以为人民会欢呼共和国的重生——但人民只是沉默。元老院控制着东部行省，但安东尼的军团正在逼近。共和国已经垂死，问题只是：谁来做最后的刽子手？",
        },
    }

    faction_narratives = narratives.get(faction_id)
    if faction_narratives:
        return faction_narratives.get(language_style, faction_narratives.get("vernacular", ""))
    # Fallback: generic intro for unknown factions
    return f"历史进入了关键的时刻。你将以{faction_id}势力的身份，在这乱世中书写自己的篇章。"


def _build_faction_status(room: GameRoom, faction_id: str) -> dict:
    """构建 faction_status（old FactionStatus 格式）。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None

    if not faction:
        return {
            "name": faction_id,
            "faction_id": faction_id,
            "strength": 0,
            "food": 0,
            "treasury": 0,
            "territories": [],
            "morale": 50,
            "is_active": False,
            "year": room.year,
            "season": room.season,
            "turn": room.quarter_number,
        }

    territories = []
    pop_sum = 0
    for tid in getattr(faction, "territories", []) or []:
        tid_str = getattr(tid, "id", None) or str(tid)
        territories.append(tid_str)
        # Sum territory populations from ws
        if ws and hasattr(ws, "territories"):
            t_obj = ws.territories.get(tid_str)
            if t_obj:
                pop_sum += getattr(t_obj, "population", 0) or 0

    return {
        "name": getattr(faction, "name", faction_id),
        "faction_id": faction_id,
        "strength": getattr(faction, "strength", 0) or getattr(faction, "strength_actual", 0) or 0,
        "food": int(getattr(faction, "food", 0) or 0),
        "treasury": int(getattr(faction, "treasury", 0) or 0),
        "territories": territories,
        "morale": getattr(faction, "morale", 50) or getattr(faction, "morale_actual", 50) or 50,
        "is_active": getattr(faction, "is_active", True),
        "population": pop_sum,
        "year": room.year,
        "season": room.season,
        "turn": room.quarter_number,
    }


def _build_aftermath(faction_status: dict, lang: str = "zh") -> str:
    """构建 aftermath 文本。"""
    if lang == "en":
        return (
            f"Troops {faction_status.get('strength', 0):,}. "
            f"Food {faction_status.get('food', 0):,}. "
            f"Treasury {faction_status.get('treasury', 0):,}. "
            f"Morale {faction_status.get('morale', 50)}. "
            f"Population {faction_status.get('population', 0):,}."
        )
    return (
        f"兵力{faction_status.get('strength', 0):,}。"
        f"粮草{faction_status.get('food', 0):,}。"
        f"资金{faction_status.get('treasury', 0):,}。"
        f"民心{faction_status.get('morale', 50)}。"
        f"人口{faction_status.get('population', 0):,}。"
    )


def _extract_events(room: GameRoom) -> list[str]:
    """提取历史事件。"""
    events = []
    turn_summaries = getattr(room, "turn_summaries", [])
    if turn_summaries:
        last = turn_summaries[-1]
        if isinstance(last, dict):
            outcome = last.get("outcome_summary", "")
            if outcome and "→" in outcome:
                events_part = outcome.split("→")[-1].strip()
                if events_part and events_part != "天下无事":
                    events = [e.strip() for e in events_part.split(";") if e.strip()]
    return events


def _build_suggestions(room: GameRoom, faction_id: str, lang: str = "zh") -> list[str]:
    """生成策略建议。"""
    ws = room.world_state
    faction = ws.factions.get(faction_id) if ws else None
    suggestions = []
    is_en = lang == "en"

    if faction:
        food = getattr(faction, "food", 0) or 0
        treasury = getattr(faction, "treasury", 0) or 0
        morale = getattr(faction, "morale_actual", 50) or 50
        strength = getattr(faction, "strength_actual", 0) or 0
        territories = len(getattr(faction, "territories", []) or [])

        if food < 5000:
            suggestions.append(
                "Low food — develop agriculture, establish supply lines" if is_en else "粮草不足，宜发展农业、推行屯田"
            )
        if treasury < 5000:
            suggestions.append(
                "Low treasury — cut spending, develop trade" if is_en else "资金短缺，宜降低开支、发展商业"
            )
        if morale < 40:
            suggestions.append(
                "Low morale — reduce taxes, appease the people" if is_en else "民心不稳，宜减轻赋税、安抚百姓"
            )
        if strength < 5000:
            suggestions.append(
                "Low troops — recruit soldiers, train forces" if is_en else "兵力薄弱，宜招募新兵、训练士卒"
            )
        if territories <= 1:
            suggestions.append("Small territory — seek expansion opportunities" if is_en else "领地狭小，宜伺机扩张")

    # 通用建议
    if len(suggestions) < 3:
        defaults = (
            ["Hold council for strategic advice", "Send spies to assess rivals", "Develop new technologies"]
            if is_en
            else ["召开朝会听取谋士建议", "派遣细作探查邻国动向", "发展科技树解锁新政"]
        )
        for d in defaults:
            if d not in suggestions:
                suggestions.append(d)
            if len(suggestions) >= 3:
                break

    return suggestions[:3]
