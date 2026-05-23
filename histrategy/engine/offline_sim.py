"""Offline rule-based NPC simulator — engaging even without an LLM.

Design philosophy: state-driven emergent narrative.
Each turn builds on previous decisions. The world has memory.
"""
from __future__ import annotations

import random
import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..engine.world import GameWorld, Faction


# ─── Event chains ──────────────────────────────────────────────

EVENT_CHAINS = {
    "讨董之盟": {  # triggers when player chooses anti-Dong Zhuo action
        "stages": [
            {
                "min_turn": 1, "max_turn": 3,
                "title": "讨董檄文传遍天下",
                "narrative": "你的讨董檄文传遍天下，各路诸侯纷纷响应。袁绍在邺城被推举为盟主，\n"
                             "集结了关东十一路诸侯的大军。董卓闻讯大惊，召集李傕、郭汜等\n"
                             "西凉将领商议对策。",
                "effects": {"morale": 5, "economy": -2, "strength": 5000, "treasury": -500},
                "npc_reactions": {
                    "yuanshao": {"morale": 10, "strength": 10000},
                    "dongzhuo": {"morale": -5},
                    "yuanshu": {"strength": 3000},
                },
            },
            {
                "min_turn": 3, "max_turn": 6,
                "title": "诸侯各怀鬼胎",
                "narrative": "联军虽然声势浩大，但诸侯各怀鬼胎。袁术断孙坚粮草，袁绍按兵不动，\n"
                             "联盟内部出现裂痕。董卓见联军不和，决定迁都长安，\n"
                             "临走前焚烧洛阳，劫掠百姓。",
                "effects": {"morale": -3, "economy": -5},
                "npc_reactions": {
                    "dongzhuo": {"economy": -10, "morale": -10},
                    "yuanshao": {"morale": -3},
                    "yuanshu": {"morale": -5},
                },
            },
            {
                "min_turn": 5, "max_turn": 10,
                "title": "联盟瓦解，群雄割据",
                "narrative": "关东联军终于分崩离析。诸侯们不再理会讨董大业，转而互相吞并。\n"
                             "天下进入真正的群雄割据时代——弱者被吞并，强者愈强。\n"
                             "这时，一个名叫刘表的荆州刺史正在南方悄然崛起……",
                "effects": {"morale": -5, "economy": -3},
                "npc_reactions": {
                    "liubiao": {"strength": 8000, "economy": 5},
                    "gongsunzan": {"strength": 5000},
                },
            },
        ],
    },
    "中原争霸": {
        "stages": [
            {
                "min_turn": 8, "max_turn": 15,
                "title": "曹操迎献帝",
                "narrative": "献帝逃出长安，流落洛阳废墟之中。这是一个千载难逢的机会——\n"
                             "谁能迎奉天子，谁就能号令诸侯！\n"
                             "你接到密报：袁绍的谋士沮授也曾建议迎驾，但袁绍犹豫不决。",
                "effects": {"morale": 8, "economy": 3},
                "npc_reactions": {
                    "yuanshao": {"morale": -5},
                    "liubiao": {},
                },
            },
            {
                "min_turn": 12, "max_turn": 20,
                "title": "奉天子以令不臣",
                "narrative": "你成功将献帝迎至许昌。天子下诏封你为丞相，百官朝拜。\n"
                             "从此你以朝廷的名义号令诸侯——这是曹操一生中最明智的决定。\n"
                             "袁绍后悔莫及，但为时已晚。",
                "effects": {"morale": 15, "economy": 5, "treasury": 2000},
                "npc_reactions": {
                    "yuanshao": {"morale": -10},
                    "liubiao": {"morale": -3},
                    "dongzhuo": {"economy": -5},
                },
            },
        ],
    },
}

# ─── Random events with consequences ──────────────────────────

RANDOM_EVENTS = [
    {
        "title": "天降祥瑞",
        "narrative": "有百姓在田间发现了一株五色祥云缠绕的禾苗，大家都说这是上天\n"
                     "赐福的征兆。各地儒生纷纷上书称颂你的德政。",
        "effects": {"morale": 8, "economy": 3},
        "condition": lambda f: f.morale > 50,
    },
    {
        "title": "流民潮",
        "narrative": "北方战乱加剧，大批流民涌入你的领地。他们拖家带口，\n"
                     "面黄肌瘦，急需安置。这既是负担，也是人口增长的机遇。",
        "effects": {"morale": -5, "economy": -3, "strength": 2000},  # refugees = potential recruits
        "condition": lambda f: True,
    },
    {
        "title": "瘟疫横行",
        "narrative": "突如其来的瘟疫在领地蔓延。百姓纷纷求医问药，但郎中也束手无策。\n"
                     "你需要下令采取防疫措施，同时安抚民心。",
        "effects": {"morale": -10, "economy": -5, "strength": -3000},
        "condition": lambda f: f.economy < 40,
    },
    {
        "title": "名士来投",
        "narrative": "一位著名的隐士听闻你的贤名，不远千里前来投靠。\n"
                     "他举止不凡，谈吐间透露出非凡的见识。",
        "effects": {"morale": 5, "economy": 3},
        "condition": lambda f: f.morale > 60 and f.economy > 40,
    },
    {
        "title": "商路畅通",
        "narrative": "来自西域的商队带来了珍奇的货物——良马、玉石、香料。\n"
                     "你下令开辟专门的市场，并征收合理的商税。",
        "effects": {"treasury": 1500, "economy": 5, "morale": 2},
        "condition": lambda f: f.economy > 30,
    },
    {
        "title": "边境冲突",
        "narrative": "边境守军报告：有敌对势力的斥候在边境附近活动。\n"
                     "他们似乎在测绘地形，搜集情报。",
        "effects": {"morale": -2, "strength": 1000},
        "condition": lambda f: True,
    },
    {
        "title": "蝗灾",
        "narrative": "铺天盖地的蝗虫从东方飞来，所过之处庄稼化为乌有。\n"
                     "今年的收成恐怕要损失大半了。",
        "effects": {"food": -2000, "economy": -8, "morale": -5},
        "condition": lambda f: f.food > 1000,
    },
    {
        "title": "大丰收",
        "narrative": "风调雨顺，五谷丰登。粮仓堆积如山，百姓喜笑颜开。\n"
                     "这是难得的丰年，你决定减免部分赋税以收民心。",
        "effects": {"food": 3000, "economy": 8, "morale": 5, "treasury": 500},
        "condition": lambda f: f.economy > 30,
    },
    {
        "title": "工匠献技",
        "narrative": "一位来自荆州的巧匠献上新式农具和攻城器械的图纸。\n"
                     "这些设计精巧实用，可以大幅提升生产效率和军事实力。",
        "effects": {"economy": 5, "strength": 2000},
        "condition": lambda f: f.economy > 35,
    },
    {
        "title": "权臣欺主",
        "narrative": "朝中有奸佞之徒在背后中伤你，散布流言说你图谋不轨。\n"
                     "虽然天子目前仍然信任你，但流言的种子已经埋下。",
        "effects": {"morale": -5},
        "condition": lambda f: f.strength > 40000,
    },
]

# ─── Season narratives ─────────────────────────────────────────

SEASON_FLAVOR = {
    "spring": [
        "春风拂面，万物复苏。田野间农民开始春耕，军营中将士们操练不息。",
        "春日迟迟，卉木萋萋。又到了征兵备战的季节，各州郡都在加紧训练。",
        "春雷乍响，惊蛰已至。新的一年开始了，天下大势又将如何演变？",
    ],
    "summer": [
        "烈日当空，蝉鸣不绝。酷暑中，军士们汗流浃背，仍在坚持操练。",
        "盛夏时节，粮草消耗大增。好在今年的庄稼长势喜人。",
        "炎炎夏日，各路诸侯的使者在各地奔波，合纵连横。",
    ],
    "autumn": [
        "秋高气爽，正是用兵之时。历史上无数决定性的战役都在这个季节打响。",
        "金秋时节，稻谷飘香。各州郡开始征收粮草，为来年的征战做准备。",
        "秋风萧瑟，落叶纷纷。有经验的老兵说这预示着一个寒冷的冬天。",
    ],
    "winter": [
        "北风呼啸，大雪纷飞。行军补给变得异常困难，但这也正是奇袭的好时机。",
        "寒冬腊月，将士们围炉取暖。边境的报告说，敌人的活动也减少了。",
        "白雪皑皑，天地苍茫。你在温暖的军帐中，听着谋士们的建议。",
    ],
}

# ─── Victory/defeat thresholds ─────────────────────────────────

VICTORY_THRESHOLD = {
    "strength": 80000,   # 兵力超过 8 万
    "economy": 85,       # 经济超过 85
    "morale": 90,        # 民心超过 90
    "territories": 10,   # 控制 10 个以上的州
}

DEFEAT_THRESHOLD = {
    "strength": 0,       # 兵力归零
    "morale": 0,         # 民心归零
}


# ─── Main simulation function ──────────────────────────────────

def simulate_turn_offline(world: "GameWorld", player_decision: str) -> dict:
    """Simulate a turn using state-driven narrative logic."""
    player = world.get_player_faction()
    if not player:
        return _empty_result()

    decision_lower = player_decision.lower()

    # ── Parse intent ──
    intent = _classify_intent(decision_lower)

    # ── Calculate base effects ──
    base_effects = _compute_base_effects(intent, player)
    narrative_parts = [_get_season_intro(world)]

    # ── Check event chains (narrative arcs spanning multiple turns) ──
    active_chain = _get_active_chain(world)
    if active_chain:
        chain_narrative, chain_effects = _process_event_chain(world, active_chain)
        narrative_parts.append(chain_narrative)
        _merge_effects(base_effects, chain_effects)

    # ── Action-specific narrative ──
    narrative_parts.append(_get_action_narrative(intent, player.name))

    # ── Random events ──
    if random.random() < 0.55:  # slightly more than half the turns
        event = random.choice(RANDOM_EVENTS)
        if event["condition"](player):
            narrative_parts.append(f"\n⚡ **{event['title']}**")
            narrative_parts.append(event["narrative"])
            _merge_effects(base_effects, event["effects"])

    # ── NPC actions ──
    npc_actions, npc_changes = _simulate_npcs(world, intent, base_effects)

    # ── Check for faction interaction events (rivalry, alliance) ──
    rivalry_events = _generate_rivalry_events(world)
    if rivalry_events:
        for re in rivalry_events:
            narrative_parts.append(f"\n🔥 {re['narrative']}")
            _merge_effects(base_effects, re["effects"])
            npc_actions.append(re["npc_msg"])

    # ── Apply effects ──
    _apply_effects(player, base_effects)
    for fa_id, changes in npc_changes.items():
        if fa_id in world.factions:
            fa = world.factions[fa_id]
            for k, v in changes.items():
                if hasattr(fa, k):
                    current = getattr(fa, k)
                    if isinstance(current, int):
                        setattr(fa, k, max(0, current + v))

    # ── Generate stat summary ──
    narrative_parts.append("")
    for key, label in [("strength", "兵力"), ("economy", "经济"),
                        ("morale", "民心"), ("treasury", "资金"),
                        ("food", "粮草")]:
        change = base_effects.get(key, 0)
        if change != 0:
            new_val = getattr(player, key, 0)
            narrative_parts.append(f"{label}：{change:+d} → {new_val:,}")

    # ── Check win/loss ──
    game_over = _check_game_over(world)
    if game_over:
        narrative_parts.append(f"\n\n{'═' * 50}")
        narrative_parts.append(game_over["message"])
        return {
            "narrative": "\n".join(narrative_parts),
            "npc_actions": npc_actions,
            "state_changes": {},
            "events_occurred": [],
            "new_choices": ["1. 🏁 重新开始", "2. 🏁 退出游戏"],
            "game_over": game_over,
        }

    # ── Events from knowledge base ──
    events_occurred = []
    for event in world.get_available_events()[:2]:
        events_occurred.append(event.title)
        world.mark_event_occurred(event.title)

    narrative = "\n".join(narrative_parts)

    # ── Generate contextual choices ──
    choices = _generate_choices(intent, world)

    return {
        "narrative": narrative,
        "npc_actions": npc_actions if npc_actions else ["天下局势正在微妙变化中……"],
        "state_changes": {
            k: getattr(player, k, 0)
            for k in ["strength", "economy", "morale", "treasury", "food"]
        },
        "events_occurred": events_occurred,
        "new_choices": choices,
        "game_over": None,
    }


# ─── Helper functions ──────────────────────────────────────────

def _classify_intent(text: str) -> str:
    """Classify player intent into a strategy category."""
    military_kw = ["兵", "军", "战", "攻", "打", "讨", "伐", "征",
                   "袭", "击", "破", "灭", "杀", "将", "帅", "武"]
    economy_kw = ["经济", "农", "粮", "钱", "税", "发展", "内政",
                  "建设", "商", "耕", "屯", "富", "财"]
    diplomacy_kw = ["联", "交", "盟", "使", "和", "谈", "亲",
                    "结", "连", "通", "聘"]
    defense_kw = ["守", "防", "固", "保", "筑", "城", "壁",
                  "垒", "寨", "御"]
    spy_kw = ["间", "谍", "刺", "暗", "潜", "细", "查", "探",
              "密", "秘"]
    recruit_kw = ["征", "募", "招", "练", "训", "养", "士"]

    score = {"military": 0, "economy": 0, "diplomacy": 0,
             "defense": 0, "spy": 0, "recruit": 0}

    for kw in military_kw:
        if kw in text:
            score["military"] += 1
    for kw in economy_kw:
        if kw in text:
            score["economy"] += 1
    for kw in diplomacy_kw:
        if kw in text:
            score["diplomacy"] += 1
    for kw in defense_kw:
        if kw in text:
            score["defense"] += 1
    for kw in spy_kw:
        if kw in text:
            score["spy"] += 1
    for kw in recruit_kw:
        if kw in text:
            score["recruit"] += 1

    # Heuristic: if option number is given, map it
    if text.strip().isdigit():
        option_map = {"1": "military", "2": "economy",
                      "3": "diplomacy", "4": "defense",
                      "5": "spy", "6": "economy"}
        return option_map.get(text.strip(), "balanced")

    best = max(score, key=score.get)
    return best if score[best] > 0 else "balanced"


def _compute_base_effects(intent: str, player: "Faction") -> dict:
    """Compute base state changes for the chosen strategy."""
    effects = {"strength": 0, "economy": 0, "morale": 0,
               "treasury": 0, "food": 0}

    if intent == "military":
        effects["strength"] = random.randint(3000, 8000)
        effects["treasury"] = -random.randint(800, 2000)
        effects["food"] = -random.randint(200, 600)
        effects["morale"] = random.randint(1, 4)
        effects["economy"] = -random.randint(1, 3)
    elif intent == "economy":
        effects["economy"] = random.randint(4, 10)
        effects["food"] = random.randint(500, 1500)
        effects["treasury"] = random.randint(300, 800)
        effects["morale"] = random.randint(2, 5)
    elif intent == "diplomacy":
        effects["morale"] = random.randint(1, 4)
        effects["treasury"] = -random.randint(200, 500)
        effects["economy"] = random.randint(1, 3)
    elif intent == "defense":
        effects["morale"] = random.randint(2, 5)
        effects["strength"] = random.randint(1000, 3000)
        effects["treasury"] = -random.randint(300, 800)
        effects["food"] = -random.randint(100, 300)
    elif intent == "spy":
        effects["treasury"] = -random.randint(300, 1000)
        effects["morale"] = random.randint(0, 2)
        effects["strength"] = 500  # intel helps strategic planning
    else:  # balanced
        effects["economy"] = random.randint(1, 4)
        effects["morale"] = random.randint(1, 3)
        effects["treasury"] = random.randint(100, 300)
        effects["food"] = random.randint(100, 300)

    return effects


def _merge_effects(base: dict, addition: dict) -> None:
    """Merge additional effects into base effects dict."""
    for k, v in addition.items():
        if k in base:
            base[k] = base.get(k, 0) + v
        else:
            base[k] = v


def _apply_effects(player: "Faction", effects: dict) -> None:
    """Apply effects to a faction."""
    attr_map = {
        "strength": "strength",
        "economy": "economy",
        "morale": "morale",
        "treasury": "treasury",
        "food": "food",
    }
    for key, attr in attr_map.items():
        change = effects.get(key, 0)
        if change != 0:
            current = getattr(player, attr, 0)
            new_val = current + change
            if attr in ("economy", "morale"):
                new_val = max(0, min(100, new_val))
            else:
                new_val = max(0, new_val)
            setattr(player, attr, new_val)


def _get_season_intro(world: "GameWorld") -> str:
    """Get a narrative intro for the current season."""
    season = world.current_season
    flavors = SEASON_FLAVOR.get(season, ["季节更替，天下依旧纷争不断。"])
    return f"【{world.current_year}年 · {'春夏秋冬'[['spring','summer','autumn','winter'].index(season)]}季】\n{random.choice(flavors)}"


def _get_action_narrative(intent: str, faction_name: str) -> str:
    """Get a narrative description of the player's action."""
    narratives = {
        "military": f"你下令征募新军，加紧操练。{faction_name}的铁骑声震彻云霄，\n"
                     "各地青壮年纷纷投军报效。军需官忙得不可开交，粮草辎重堆积如山。",
        "economy": f"你推行仁政，减免赋税，兴修水利，鼓励农耕。\n"
                   "百姓安居乐业，田野间一片繁忙景象。商人开始聚集，市集日渐繁荣。",
        "diplomacy": f"你派出精干使节，携带厚礼与书信，出使各方势力。\n"
                     "外交的帷幕缓缓拉开——有人将因此成为你的盟友，有人将成为你的敌人。",
        "defense": f"你巡视边境，下令加固城防工事。将士们日夜操练，\n"
                   "箭塔和城墙不断加固。边境百姓看到守军的威严，稍稍安心。",
        "spy": f"你秘密召见情报主管，面授机宜。数名精锐细作连夜出发，\n"
               "潜入各方势力的腹地。他们的回报将决定你下一步的棋局。",
        "recruit": f"你下令开仓放粮，招募贤才。消息传开，\n"
                   "各地豪杰纷纷前来投奔。你的帐下日益充实。",
    }
    return narratives.get(intent, f"你采取了稳健的治理方针，各方面都在稳步发展。")


def _simulate_npcs(world: "GameWorld", player_intent: str,
                   player_effects: dict) -> tuple[list[str], dict]:
    """Simulate NPC faction actions for this turn."""
    actions = []
    changes = {}

    for fa_id, fa in world.factions.items():
        if fa.id == world.player_faction_id or not fa.is_active:
            continue

        change = {}

        # Natural drift
        change["strength"] = random.randint(-1000, 3000)
        if random.random() < 0.3:
            change["economy"] = random.randint(-3, 5)
        if random.random() < 0.2:
            change["morale"] = random.randint(-5, 5)

        # Aggressive expansion
        if fa.aggression > 60 and random.random() < 0.35:
            bonus = random.randint(2000, 6000)
            change["strength"] = change.get("strength", 0) + bonus
            if random.random() < 0.3:
                actions.append(f"⚔ {fa.name}正在积极扩张，吞并了周边的小势力。")
            else:
                actions.append(f"⚔ {fa.name}在边境频繁调动军队，似有大规模军事行动。")

        # Player's military buildup causes tension
        if player_intent == "military" and fa.aggression > 50:
            change["strength"] = change.get("strength", 0) + random.randint(1000, 4000)
            if random.random() < 0.2:
                actions.append(f"⚠ 你的扩军行动引起了{fa.name}的警觉，他们也在加强军备。")

        # Player's diplomatic efforts
        if player_intent == "diplomacy" and fa.aggression < 40:
            change["morale"] = change.get("morale", 0) + 2
            if random.random() < 0.2:
                actions.append(f"✉ {fa.name}对你的使者以礼相待，表示愿意建立友好关系。")

        changes[fa_id] = change

    return actions, changes


def _get_active_chain(world: "GameWorld") -> Optional[dict]:
    """Get the active event chain and stage for the current game state."""
    # Simple tracking: use world.history_log to check if a chain is active
    log_text = "\n".join(world.history_log) if world.history_log else ""

    for chain_name, chain in EVENT_CHAINS.items():
        stages_completed = sum(1 for s in chain["stages"]
                               if s["title"] in log_text)
        if stages_completed < len(chain["stages"]):
            next_stage = chain["stages"][stages_completed]
            if (next_stage["min_turn"] <= world.turn_count <= next_stage["max_turn"]
                    and chain_name not in log_text):
                return {
                    "name": chain_name,
                    "stage": next_stage,
                    "stage_index": stages_completed,
                }
    return None


def _process_event_chain(world: "GameWorld",
                         chain: dict) -> tuple[str, dict]:
    """Process an active event chain stage."""
    stage = chain["stage"]
    world.history_log.append(f"[事件链] {chain['name']}: {stage['title']}")
    return f"\n📜 **{stage['title']}**\n{stage['narrative']}", stage["effects"]


def _generate_rivalry_events(world: "GameWorld") -> list[dict]:
    """Generate emergent rivalry/alliance events between NPCs."""
    events = []
    player = world.get_player_faction()
    if not player:
        return events

    # Between strong NPCs
    strong_npcs = [
        f for f in world.factions.values()
        if f.is_active and f.id != world.player_faction_id and f.strength > 30000
    ]

    if len(strong_npcs) >= 2 and random.random() < 0.15:
        a, b = random.sample(strong_npcs, 2)
        if random.random() < 0.5:
            events.append({
                "narrative": f"{a.name}与{b.name}因边境冲突爆发了局部战争！"
                             f"这场战争可能会改变北方的势力格局。",
                "effects": {"economy": -1, "morale": -1},
                "npc_msg": f"🔥 {a.name}与{b.name}正在交战中！",
            })
        else:
            events.append({
                "narrative": f"有消息称{a.name}与{b.name}秘密结成了同盟。"
                             f"这对你来说可能不是好消息……",
                "effects": {"morale": -2},
                "npc_msg": f"🔗 {a.name}与{b.name}结成了同盟，对你形成包围之势。",
            })

    return events


def _generate_choices(intent: str, world: "GameWorld") -> list[str]:
    """Generate contextual choices based on game state."""
    player = world.get_player_faction()
    if not player:
        return ["1. 发展经济", "2. 扩充军备", "3. 外交结盟"]

    choices = []
    # Military options
    if player.strength < 50000:
        choices.append("1. 🗡 扩军备战，加紧训练")
    else:
        choices.append("1. 🗡 率军出征，讨伐不臣")

    # Economic options
    if player.economy < 40:
        choices.append("2. 🌾 休养生息，恢复生产")
    elif player.economy < 70:
        choices.append("2. 🌾 发展经济，鼓励商贸")
    else:
        choices.append("2. 🌾 改革税制，充实府库")

    # Diplomatic options  
    choices.append("3. 🤝 派使者出访各方势力")

    # Defense
    if player.strength > 20000 and player.strength < 40000:
        choices.append("4. 🏰 加固城防，巩固领地")
    else:
        choices.append("4. 🏰 巡查边境，安抚百姓")

    # Intel
    if player.treasury > 3000:
        choices.append("5. 🕵 派出细作，搜集情报")

    # Strategic
    choices.append("6. 📜 按兵不动，静观其变")

    return choices[:6]


def _check_game_over(world: "GameWorld") -> Optional[dict]:
    """Check if the game should end."""
    player = world.get_player_faction()
    if not player:
        return None

    # Victory by strength
    if player.strength >= VICTORY_THRESHOLD["strength"]:
        return {
            "type": "victory",
            "message": f"🎉 **大业已成！**\n\n"
                       f"你的军队已经达到了{VICTORY_THRESHOLD['strength']:,}人，\n"
                       f"天下无人能与你抗衡。诸侯纷纷遣使纳贡，\n"
                       f"天子下诏加封你为魏王，赞拜不名，剑履上殿。\n\n"
                       f"你用了{world.turn_count}个回合（约{world.turn_count * 3}个月），\n"
                       f"从一个地方军阀成长为天下霸主。\n"
                       f"史书会如何记载你的一生？\n\n"
                       f"🏆 **最终评分**：{_calculate_score(world)}",
        }

    # Victory by economy + morale (benevolent ruler path)
    if (player.economy >= VICTORY_THRESHOLD["economy"]
            and player.morale >= VICTORY_THRESHOLD["morale"]):
        return {
            "type": "victory",
            "message": f"🎉 **盛世明君！**\n\n"
                       f"在你的治理下，百姓安居乐业，路不拾遗，夜不闭户。\n"
                       f"商旅往来不绝，田野一片丰收景象。\n"
                       f"天下百姓歌颂你的仁德，四方英才纷纷来投。\n"
                       f"你用了{world.turn_count}个回合，\n"
                       f"将一方土地治理成了人间乐土。\n\n"
                       f"🏆 **最终评分**：{_calculate_score(world)}",
        }

    # Defeat by depleted morale
    if player.morale <= DEFEAT_THRESHOLD["morale"]:
        return {
            "type": "defeat",
            "message": f"💀 **民心尽失！**\n\n"
                       f"你的暴政终于引发了民变。各地百姓揭竿而起，\n"
                       f"你的军队也开始倒戈。在熊熊烈火中，\n"
                       f"你望着曾经辉煌的宫殿化为灰烬……\n\n"
                       f"你坚持了{world.turn_count}个回合。\n"
                       f"历史记住了一个失败的统治者。\n\n"
                       f"🏆 **最终评分**：{_calculate_score(world)}",
        }

    # Defeat by army destroyed
    if player.strength <= DEFEAT_THRESHOLD["strength"]:
        return {
            "type": "defeat",
            "message": f"💀 **军队覆灭！**\n\n"
                       f"你的大军在最后一战中全军覆没。敌人踏着将士们的尸体\n"
                       f"攻入了你的都城。你在亲卫的掩护下突围，\n"
                       f"但天下之大，已无你容身之处……\n\n"
                       f"你坚持了{world.turn_count}个回合。\n"
                       f"你的故事成为了乱世中又一个悲歌。\n\n"
                       f"🏆 **最终评分**：{_calculate_score(world)}",
        }

    return None


def _calculate_score(world: "GameWorld") -> int:
    """Calculate final score."""
    player = world.get_player_faction()
    if not player:
        return 0

    score = 0
    score += player.strength // 1000 * 10
    score += player.economy * 5
    score += player.morale * 5
    score += player.treasury // 100
    score += len([r for r in world.regions.values() if r.owner == player.id]) * 50
    score += world.turn_count * 2  # survival bonus

    return min(1000, score)


def _empty_result() -> dict:
    return {
        "narrative": "局势不明，请重新决策。",
        "npc_actions": [],
        "state_changes": {},
        "events_occurred": [],
        "new_choices": ["1. 联络袁绍", "2. 发展经济", "3. 征兵备战"],
        "game_over": None,
    }
