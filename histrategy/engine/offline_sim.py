"""Offline rule-based NPC simulator - fallback when no LLM is available."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.world import GameWorld


def simulate_turn_offline(world: "GameWorld", player_decision: str) -> dict:
    """Simulate a turn using rule-based logic instead of an LLM."""
    player = world.get_player_faction()
    if not player:
        return _empty_result()

    decision_lower = player_decision.lower()

    # --- Parse player decision keywords ---
    is_military = any(kw in decision_lower for kw in ["兵", "军", "战", "攻", "打", "讨", "伐", "战"])
    is_economy = any(kw in decision_lower for kw in ["经济", "农", "粮", "钱", "税", "发展", "内政", "建设"])
    is_diplomacy = any(kw in decision_lower for kw in ["联", "交", "盟", "使", "和", "谈", "亲"])
    is_defense = any(kw in decision_lower for kw in ["守", "防", "固", "保", "筑", "城"])
    is_spy = any(kw in decision_lower for kw in ["间", "谍", "刺", "暗", "潜", "细"])
    
    # --- Apply state changes based on decision ---
    strength_change = 0
    economy_change = 0
    morale_change = 0
    treasury_change = 0
    food_change = 0
    
    if is_military:
        strength_change = random.randint(3000, 8000)
        treasury_change = -random.randint(800, 2000)
        food_change = -random.randint(300, 800)
        morale_change = random.randint(2, 5)
        economy_change = -random.randint(1, 3)
        decision_type = "军事"
    elif is_economy:
        economy_change = random.randint(5, 12)
        food_change = random.randint(500, 1500)
        treasury_change = random.randint(300, 1000)
        morale_change = random.randint(3, 7)
        strength_change = 0
        decision_type = "内政"
    elif is_diplomacy:
        morale_change = random.randint(2, 6)
        treasury_change = -random.randint(200, 600)
        economy_change = random.randint(1, 4)
        strength_change = 0
        decision_type = "外交"
    elif is_defense:
        morale_change = random.randint(3, 6)
        strength_change = random.randint(1000, 3000)
        treasury_change = -random.randint(400, 1000)
        food_change = -random.randint(100, 400)
        decision_type = "防御"
    elif is_spy:
        morale_change = 0
        treasury_change = -random.randint(500, 1500)
        decision_type = "情报"
    else:
        # Balanced approach
        economy_change = random.randint(2, 6)
        morale_change = random.randint(1, 4)
        treasury_change = random.randint(100, 400)
        decision_type = "综合"

    # --- Simulate NPC actions ---
    npc_actions = []
    npc_changes = {}
    
    for fa_id, fa in world.factions.items():
        if fa.id == world.player_faction_id or not fa.is_active:
            continue
        
        # Each NPC faction makes some moves
        npc_change = {}
        
        # Natural growth/decline
        if random.random() < 0.6:
            npc_change["strength"] = fa.strength + random.randint(-2000, 5000)
        if random.random() < 0.4:
            npc_change["economy"] = max(0, min(100, fa.economy + random.randint(-3, 5)))
        if random.random() < 0.3:
            npc_change["morale"] = max(0, min(100, fa.morale + random.randint(-5, 5)))
        
        # Aggressive factions expand
        if fa.aggression > 60 and random.random() < 0.4:
            npc_actions.append(f"{fa.name}正在积极扩张势力。")
            npc_change["strength"] = npc_change.get("strength", fa.strength) + random.randint(2000, 8000)
            if random.random() < 0.3:
                npc_actions.append(f"有消息称{fa.name}吞并了周边的小势力。")
        
        npc_changes[fa_id] = npc_change
    
    # Random events
    random_events = [
        "各地流民涌入你的领地，带来了人口但也带来了治安问题。",
        "商人带来了远方的货物，市场一片繁荣。",
        "天降大雨，今年的收成有望丰收。",
        "边境传来消息，有盗匪出没，劫掠百姓。",
        "有隐士前来投靠，献上治国良策。",
        "你的使者从洛阳归来，带来了朝廷的最新动向。",
    ]
    
    # --- Build narrative ---
    season_names = {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}
    season_cn = season_names.get(world.current_season, world.current_season)
    
    narrative_parts = [
        f"【{world.current_year}年{season_cn} · {decision_type}方略】",
    ]
    
    if is_military:
        narrative_parts.append(f"你下令征募新军，扩充兵力。各地青壮年纷纷响应，{player.name}的军力得到显著增强。但同时，军饷和粮草的消耗也在增加。")
    elif is_economy:
        narrative_parts.append(f"你推行休养生息之策，减免赋税，兴修水利。百姓安居乐业，田野间一片繁忙景象。府库日渐充实。")
    elif is_diplomacy:
        narrative_parts.append(f"你派出使者，携带厚礼前往各方势力进行联络。外交渠道逐渐打开，消息纷纷传回。")
    elif is_defense:
        narrative_parts.append(f"你下令加固城防，训练守军。边境各城寨的防御工事得到加强，军民士气高涨。")
    elif is_spy:
        narrative_parts.append(f"你秘密派出细作，潜入各方势力的核心地带搜集情报。")
    else:
        narrative_parts.append(f"你采取了稳健的治理方针，各方面都在稳步发展。")
    
    narrative_parts.append("")
    
    if random.random() < 0.5:
        narrative_parts.append(f"📌 {random.choice(random_events)}")
    
    # State summary
    new_strength = max(0, player.strength + strength_change)
    new_economy = max(0, min(100, player.economy + economy_change))
    new_morale = max(0, min(100, player.morale + morale_change))
    new_treasury = max(0, player.treasury + treasury_change)
    new_food = max(0, player.food + food_change)
    
    narrative_parts.append(f"\n兵力变动：{strength_change:+d} → {new_strength:,}")
    narrative_parts.append(f"经济变动：{economy_change:+d} → {new_economy}")
    narrative_parts.append(f"民心变动：{morale_change:+d} → {new_morale}")
    
    narrative = "\n".join(narrative_parts)
    
    # --- Build choices ---
    choices = [
        "1. 继续扩军备战，准备出征",
        "2. 发展内政，积蓄实力",
        "3. 派使者结交盟友",
        "4. 加固城防，以守为攻",
        "5. 派出间谍，搜集情报",
        "6. 按兵不动，静观其变",
    ]
    
    # --- Events ---
    events_occurred = []
    available_events = world.get_available_events()
    for event in available_events[:2]:  # Max 2 events per turn
        events_occurred.append(event.title)
        world.mark_event_occurred(event.title)
    
    return {
        "narrative": narrative,
        "npc_actions": npc_actions if npc_actions else ["各方势力都在紧锣密鼓地准备着。"],
        "state_changes": {
            "strength": new_strength,
            "economy": new_economy,
            "morale": new_morale,
            "treasury": new_treasury,
            "food": new_food,
            "npc_changes": npc_changes,
        },
        "events_occurred": events_occurred,
        "new_choices": choices,
    }


def _empty_result() -> dict:
    return {
        "narrative": "局势不明，请重新决策。",
        "npc_actions": [],
        "state_changes": {},
        "events_occurred": [],
        "new_choices": ["1. 联络袁绍", "2. 发展经济", "3. 征兵备战"],
    }
