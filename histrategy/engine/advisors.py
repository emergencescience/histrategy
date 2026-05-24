"""
Advisor system for 三國志略 — Plan Mode.

Each faction has unique advisors with distinct personalities,
expertise, and court dynamics. In Plan Mode, advisors give
their perspectives, and 4 contextual suggestions are generated.
"""

from __future__ import annotations

import random
import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..state.world_state import WorldState, FactionState

# ─── Advisor definitions per faction ───────────────────────

ADVISORS = {
    "cao": [
        {
            "id": "xunyu",
            "name": "荀彧",
            "title": "军师",
            "perspective": "strategy",
            "temperament": "cautious",
            "voice": [
                "主公，当下之势，{situation_short}。依彧之见，宜{suggestion_cautious}。",
                "彧以为，{situation_short}。若主公能{suggestion_cautious}，则霸业可期。",
            ],
        },
        {
            "id": "xiahoudun",
            "name": "夏侯惇",
            "title": "将军",
            "perspective": "military",
            "temperament": "aggressive",
            "voice": [
                "主公！末将愿率精锐{target_area}，{suggestion_aggressive}。",
                "与其坐等，不如主动出击！{suggestion_aggressive}，末将愿为先锋！",
            ],
        },
        {
            "id": "guojia",
            "name": "郭嘉",
            "title": "谋士",
            "perspective": "scheme",
            "temperament": "scheming",
            "voice": [
                "奉孝有一计：{suggestion_scheme}。此计若成，{suggestion_reward}。",
                "主公明鉴，{situation_short}。嘉以为，不如{suggestion_scheme}。",
            ],
        },
        {
            "id": "xunyou",
            "name": "荀攸",
            "title": "内政官",
            "perspective": "economy",
            "temperament": "pragmatic",
            "voice": [
                "攸核查府库，{economy_status}。建议{suggestion_economy}，以固根本。",
                "兵马未动，粮草先行。当前{economy_status}，不如{suggestion_economy}。",
            ],
        },
    ],
    "shu": [
        {
            "id": "jianyong",
            "name": "简雍",
            "title": "谋士",
            "perspective": "diplomacy",
            "temperament": "friendly",
            "voice": [
                "主公，雍以为{suggestion_diplomacy}。如能结交，则大事可图。",
                "不如{suggestion_diplomacy}。备以皇叔之名，天下之士必望风而归。",
            ],
        },
        {
            "id": "guanyu",
            "name": "关羽",
            "title": "将军",
            "perspective": "military",
            "temperament": "proud",
            "voice": [
                "兄长安坐，待云长提{suggestion_aggressive}之首级来献！",
                "关某观{target_area}，{suggestion_aggressive}，必可一战定乾坤！",
            ],
        },
        {
            "id": "zhangfei",
            "name": "张飞",
            "title": "将军",
            "perspective": "military",
            "temperament": "aggressive",
            "voice": [
                "哥哥！让我带兵{suggestion_aggressive}！看我不杀他个片甲不留！",
                "整日待在这小县城，憋屈！不如{suggestion_aggressive}！",
            ],
        },
        {
            "id": "sunqian",
            "name": "孙乾",
            "title": "内政官",
            "perspective": "economy",
            "temperament": "pragmatic",
            "voice": [
                "主公，平原县小民寡，{economy_status}。乾以为当{suggestion_economy}。",
                "民以食为天，{economy_status}。不如{suggestion_economy}，以养百姓。",
            ],
        },
    ],
    "wu": [
        {
            "id": "chengpu",
            "name": "程普",
            "title": "军师",
            "perspective": "strategy",
            "temperament": "cautious",
            "voice": [
                "将军，普以为{suggestion_cautious}。江东基业，不可轻举妄动。",
                "{suggestion_cautious}。待时机成熟，再北上讨董不迟。",
            ],
        },
        {
            "id": "huanggai",
            "name": "黄盖",
            "title": "将军",
            "perspective": "military",
            "temperament": "aggressive",
            "voice": [
                "主公，盖愿率水军{suggestion_aggressive}！",
                "末将观{target_area}，{suggestion_aggressive}，必可大胜！",
            ],
        },
        {
            "id": "zhuzhi",
            "name": "朱治",
            "title": "内政官",
            "perspective": "economy",
            "temperament": "pragmatic",
            "voice": [
                "将军，{economy_status}。治以为当{suggestion_economy}。",
                "长沙乃用武之地，{economy_status}。不如{suggestion_economy}。",
            ],
        },
    ],
    "yuan_shao": [
        {
            "id": "tianfeng",
            "name": "田丰",
            "title": "军师",
            "perspective": "strategy",
            "temperament": "cautious",
            "voice": [
                "主公，丰以为{suggestion_cautious}。四州虽广，根基未固。",
                "天下方乱，{suggestion_cautious}。待时机成熟，主公以盟主之尊号令天下！",
            ],
        },
        {
            "id": "yanliang",
            "name": "颜良",
            "title": "将军",
            "perspective": "military",
            "temperament": "aggressive",
            "voice": [
                "主公！良愿率{suggestion_aggressive}！河北上将，天下无敌！",
                "{suggestion_aggressive}！让天下人知道河北军的厉害！",
            ],
        },
        {
            "id": "shenpei",
            "name": "审配",
            "title": "内政官",
            "perspective": "economy",
            "temperament": "strict",
            "voice": [
                "主公，{economy_status}。配已拟定{suggestion_economy}之法。",
                "为今之计，宜{suggestion_economy}。河北钱粮充足，方能成就霸业。",
            ],
        },
        {
            "id": "xuyou",
            "name": "许攸",
            "title": "谋士",
            "perspective": "scheme",
            "temperament": "scheming",
            "voice": [
                "主公，攸有一计：{suggestion_scheme}。",
                "若依攸之计，{suggestion_scheme}，则{target_area}唾手可得！",
            ],
        },
    ],
}


# ─── Context builder functions ──────────────────────────

def _get_situation_short(state: "WorldState", faction: "FactionState") -> str:
    """Brief description of current strategic situation."""
    nearby_threats = []
    for fid, fs in state.factions.items():
        if fid != state.player_faction_id and fs.is_active:
            if fs.strength > faction.strength * 1.5:
                nearby_threats.append(fs.name)

    if nearby_threats:
        return f"{'、'.join(nearby_threats[:2])}等势力日益壮大"
    return "各方势力都在秣马厉兵"


def _get_target_area(state: "WorldState", faction: "FactionState") -> str:
    """Pick a nearby strategic target."""
    targets = {
        "cao": "兖州",
        "shu": "徐州",
        "wu": "荆州",
        "yuan_shao": "冀州",
    }
    return targets.get(state.player_faction_id, "中原")


def _get_suggestion_cautious() -> str:
    """Generate a cautious strategic suggestion."""
    options = [
        "先稳固根本，休养生息，徐图进取",
        "深沟高垒，养精蓄锐，待天下有变",
        "联络各方，广结盟友，以壮大势",
        "暂缓出兵，先整顿内政，积蓄粮草",
    ]
    return random.choice(options)


def _get_suggestion_aggressive() -> str:
    """Generate an aggressive military suggestion."""
    options = [
        "率精兵直取敌方要害",
        "趁其不备，奇袭敌营",
        "大举进兵，一举荡平",
        "发兵征讨，以振军威",
    ]
    return random.choice(options)


def _get_suggestion_scheme() -> str:
    """Generate a scheming suggestion."""
    options = [
        "派细作潜入敌营，离间其君臣",
        "散布流言，使敌自乱阵脚",
        "暗中联络其部将，许以重利",
        "假意求和，实则趁机备战",
    ]
    return random.choice(options)


def _get_suggestion_diplomacy() -> str:
    """Generate a diplomatic suggestion."""
    options = [
        "派使者前往结交，以礼相待",
        "联姻求和，结为同盟",
        "遣使游说，陈说利害",
        "以厚礼相赠，示好于对方",
    ]
    return random.choice(options)


def _get_suggestion_economy() -> str:
    """Generate an economic suggestion."""
    options = [
        "减轻赋税，鼓励农耕",
        "兴修水利，开垦荒地",
        "整顿商税，发展市集",
        "开仓放粮，安抚流民",
    ]
    return random.choice(options)


def _get_reward(aggressive: bool) -> str:
    """What the schemer promises."""
    if aggressive:
        return "可一举克敌"
    return "不战而屈人之兵"


def _get_economy_status(faction: "FactionState") -> str:
    """Describe the economic situation."""
    if faction.economy < 30:
        return "府库空虚，百姓困苦"
    elif faction.economy < 50:
        return "收支勉强平衡"
    elif faction.economy < 70:
        return "府库渐充，百姓安定"
    else:
        return "粮草充足，府库丰盈"


def _get_suggestion_reward() -> str:
    return random.choice(["可收奇效", "大事可成", "事半功倍", "主公可高枕无忧"])


# ─── Main Plan Mode function ─────────────────────────────


def generate_plan_mode(state: "WorldState") -> dict:
    """
    Generate the Plan Mode content: advisor speeches + 4 suggestions.

    Returns:
        {
            "advisors": [{"name": "荀彧", "title": "军师", "speech": "..."}, ...],
            "suggestions": ["1. ...", "2. ...", "3. ...", "4. ..."],
        }
    """
    faction = state.get_player_faction()
    if not faction:
        return {"advisors": [], "suggestions": []}

    fid = state.player_faction_id
    adv_list = ADVISORS.get(fid, [])
    if not adv_list:
        return {"advisors": [], "suggestions": []}

    advisors = []
    for adv in adv_list:
        # Build the speech from templates
        template = random.choice(adv["voice"])
        speech = template.format(
            situation_short=_get_situation_short(state, faction),
            suggestion_cautious=_get_suggestion_cautious(),
            suggestion_aggressive=_get_suggestion_aggressive(),
            suggestion_scheme=_get_suggestion_scheme(),
            suggestion_diplomacy=_get_suggestion_diplomacy(),
            suggestion_economy=_get_suggestion_economy(),
            suggestion_reward=_get_suggestion_reward(),
            economy_status=_get_economy_status(faction),
            target_area=_get_target_area(state, faction),
        )
        advisors.append({
            "name": adv["name"],
            "title": adv["title"],
            "speech": speech,
            "id": adv["id"],
            "temperament": adv["temperament"],
        })

    # Generate 4 contextual suggestions based on advisor perspectives
    suggestions = []
    suggestion_templates = {
        "military": [
            lambda: f"扩军备战，{_get_suggestion_aggressive()}",
            lambda: f"加强边防，招募新军",
        ],
        "economy": [
            lambda: f"发展内政，{_get_suggestion_economy()}",
            lambda: f"减轻赋税，鼓励农商",
        ],
        "diplomacy": [
            lambda: f"派使者{_get_suggestion_diplomacy()}",
            lambda: f"四处联络，合纵连横",
        ],
        "scheme": [
            lambda: f"施展计谋，{_get_suggestion_scheme()}",
            lambda: f"派出细作，搜集各地情报",
        ],
    }

    # Pick 4 diverse suggestions
    perspectives = ["military", "economy", "diplomacy", "scheme"]
    random.shuffle(perspectives)
    for i, persp in enumerate(perspectives[:4]):
        tmpl = random.choice(suggestion_templates[persp])
        suggestions.append(f"{i+1}. {tmpl()}")

    return {
        "advisors": advisors,
        "suggestions": suggestions,
    }
