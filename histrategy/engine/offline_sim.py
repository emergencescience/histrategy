"""Offline simulator — OpenClaw-inspired: knowledge-driven, memory-rich.

Design philosophy (小龙虾/OpenClaw):
1. 知识驱动: 使用 knowledge/data 中的人物性格/势力关系/地域数据
2. 记忆系统: 回顾历史决策，生成连贯叙事弧
3. 本地文件: 存档/读档/玩家档案
4. 能力系统: 势力有独特技能和特质
"""
from __future__ import annotations

import json
import math
import random
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..state.world_state import get_data_dir

if TYPE_CHECKING:
    from ..engine.world import GameWorld, Faction


# ─── Load knowledge base ────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "knowledge" / "data"

def _load_knowledge(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []

CHARACTERS = _load_knowledge("characters.json")
FACTIONS_RAW = _load_knowledge("factions.json")
REGIONS_RAW = _load_knowledge("regions.json")
EVENTS_RAW = _load_knowledge("events.json")


# ─── Character personality-driven behaviors ─────────────────────

PERSONALITY_EFFECTS = {
    "雄才大略": {"economy": 1, "morale": 1},
    "多疑": {"morale": -1, "strength": 500},
    "用人唯才": {"economy": 1},
    "仁德": {"morale": 2},
    "坚毅": {"morale": 1},
    "重义气": {"morale": 1},
    "勇猛": {"strength": 2000},
    "忠烈": {"morale": 1},
    "好谋无断": {"morale": -1},
    "自大": {"morale": -1},
    "残暴": {"morale": -3, "economy": -1, "strength": 1000},
    "跋扈": {"morale": -2},
    "骄奢": {"economy": -1, "morale": -1, "treasury": -200},
    "优柔寡断": {"strength": -500},
    "善于笼络人心": {"morale": 2, "economy": 1},
    "不拘小节": {"economy": 1},
    "霸道": {"morale": -1, "strength": 2000},
    "果断": {"strength": 1000},
    "目光短浅": {"economy": -1},
    "贪欲": {"treasury": -200, "morale": -1},
}

PERSONALITY_NARRATIVES = {
    "雄才大略": "你的雄才大略令天下震动，英雄豪杰纷纷来投。",
    "多疑": "你生性多疑，下令加强宫中戒备，同时派出亲信监视各方动向。",
    "仁德": "你的仁德之名传遍天下，百姓箪食壶浆以迎王师。",
    "残暴": "你的暴政令百姓敢怒不敢言，各地反抗暗流涌动。",
}

# ─── Memory system ──────────────────────────────────────────────

MEMORY_FILE = get_data_dir() / "player_memory.json"


def _memory_file() -> Path:
    return get_data_dir() / "player_memory.json"


def load_player_memory() -> dict:
    """Load narrative memory from disk."""
    path = _memory_file()
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"decisions": [], "events": [], "faction_relations": {}, "achievements": []}


def save_player_memory(memory: dict):
    """Save narrative memory to disk."""
    path = _memory_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def add_memory_entry(memory: dict, turn: int, year: int, season: str,
                     decision: str, narrative_snippet: str, event: str = ""):
    """Add a turn entry to narrative memory."""
    entry = {
        "turn": turn,
        "year": year,
        "season": season,
        "decision": decision[:100],
        "narrative": narrative_snippet[:200],
    }
    if event:
        entry["event"] = event
    memory["decisions"].append(entry)

    # Keep last 50 entries (memory management)
    if len(memory["decisions"]) > 50:
        memory["decisions"] = memory["decisions"][-50:]

    save_player_memory(memory)


def get_recent_memories(memory: dict, n: int = 5) -> list[dict]:
    """Get the n most recent memories."""
    return memory["decisions"][-n:]


# ─── Event chains (knowledge-aware) ────────────────────────────

EVENT_CHAINS = {
    "讨董之盟": {
        "stages": [
            {
                "title": "讨董檄文传遍天下",
                "narrative_template": (
                    "你的讨董檄文传遍天下，各路诸侯纷纷响应。\n"
                    "袁绍在{ye_city}被推举为盟主，集结了关东十一路诸侯的大军。\n"
                    "{dong_reaction}"
                ),
                "effects": {"morale": 5, "economy": -2, "strength": 5000, "treasury": -500},
                "npc_effects": {"yuan_shao": {"morale": 10, "strength": 10000},
                                "dongzhuo": {"morale": -5}},
            },
            {
                "title": "诸侯各怀鬼胎",
                "narrative_template": (
                    "联军虽然声势浩大，但诸侯各怀鬼胎。\n"
                    "{yuan_shu_behavior}\n"
                    "联盟内部出现裂痕。董卓见联军不和，决定迁都长安，\n"
                    "临走前焚烧洛阳，劫掠百姓。\n"
                    "{player_impact}"
                ),
                "effects": {"morale": -3, "economy": -5},
                "npc_effects": {"dongzhuo": {"economy": -10, "morale": -10},
                                "yuan_shao": {"morale": -3}},
            },
            {
                "title": "联盟瓦解，群雄割据",
                "narrative_template": (
                    "关东联军终于分崩离析。诸侯们不再理会讨董大业，\n"
                    "转而互相吞并。{new_power_rise}\n"
                    "天下进入真正的群雄割据时代——弱者被吞并，强者愈强。"
                ),
                "effects": {"morale": -5, "economy": -3},
                "npc_effects": {"liu_biao": {"strength": 8000, "economy": 5},
                                "other": {"strength": 3000}},
            },
        ],
    },
}


# ─── Random events (knowledge-aware) ──────────────────────────

RANDOM_EVENTS = [
    {
        "title": "名士来投",
        "narrative_template": "一位{style}的隐士听闻你的贤名，不远千里前来投靠。他名叫{name}，谈吐间透露出非凡的见识。",
        "effects": {"morale": 5, "economy": 3},
        "condition": lambda f, m: f.morale > 55,
    },
    {
        "title": "流民潮",
        "narrative_template": "北方战乱加剧，大批流民涌入你的领地。他们拖家带口，面黄肌瘦，急需安置。",
        "effects": {"morale": -4, "economy": -3, "strength": 2000},
        "condition": lambda f, m: True,
    },
    {
        "title": "边境冲突",
        "narrative_template": "边境守军报告：{enemy}的斥候在{direction}附近活动。他们似乎在测绘地形，搜集情报。",
        "effects": {"morale": -2, "strength": 1000},
        "condition": lambda f, m: True,
    },
    {
        "title": "大丰收",
        "narrative_template": "风调雨顺，五谷丰登。粮仓堆积如山，百姓喜笑颜开。这是难得的{adjective}丰年。",
        "effects": {"food": 3000, "economy": 8, "morale": 5, "treasury": 500},
        "condition": lambda f, m: f.economy > 30 and random.random() < 0.4,
    },
]


CAPITAL_NAMES = {
    "xuchang": "许昌", "pingyuan": "平原", "changsha": "长沙",
    "yecheng": "邺城", "changan": "长安", "luoyang": "洛阳",
}

# ─── Season narratives (regional-aware) ────────────────────────

TENDENCY_CN = {
    "hostile": "好战", "neutral": "中立", "calculating": "善谋",
    "friendly": "友善", "pragmatic": "务实", "arrogant": "傲慢",
    "defensive": "守成",
}

# ─── Season narratives (regional-aware) ────────────────────────

SEASON_FLAVOR = {
    "spring": [
        "春风拂面，万物复苏。{capital}的百姓开始春耕。",
        "春雷乍响，惊蛰已至。{leader}在{capital}召开军事会议。",
        "春日迟迟，卉木萋萋。{faction}的将士们在城外的校场上操练不息。",
    ],
    "summer": [
        "烈日当空，蝉鸣不绝。{capital}的市集上商旅往来不绝。",
        "盛夏时节，{faction}的粮草消耗大增。",
        "炎炎夏日，{leader}的使者在各地奔波，合纵连横。",
    ],
    "autumn": [
        "秋高气爽，正是用兵之时。{leader}登高望远，胸中自有百万兵。",
        "金秋时节，{region}一带稻谷飘香。",
        "秋风萧瑟，有经验的老兵说这预示着一个寒冷的冬天。",
    ],
    "winter": [
        "北风呼啸，大雪纷飞。{capital}城头的旗帜在寒风中猎猎作响。",
        "寒冬腊月，将士们围炉取暖。{leader}在军帐中与谋士们彻夜长谈。",
        "白雪皑皑，{region}已是一片银装素裹。",
    ],
}


# ─── Main simulation ───────────────────────────────────────────

def simulate_turn_offline(world: "GameWorld", player_decision: str) -> dict:
    """Knowledge-driven offline simulation with memory."""
    player = world.get_player_faction()
    if not player:
        return _empty_result()

    # Load memory
    memory = load_player_memory()

    # Classify intent
    intent = _classify_intent(player_decision.lower())

    # Get character-driven effects
    char_effects = _get_character_effects(player)
    base_effects = _compute_base_effects(intent, player)

    # Merge character effects
    for k, v in char_effects.items():
        base_effects[k] = base_effects.get(k, 0) + v

    narrative_parts = []
    narrative_parts.append(_get_knowledge_intro(world, player))

    # ── Check event chains ──
    chain_result = _process_event_chain_knowledge(world, player, memory)
    if chain_result:
        narrative_parts.append(chain_result)

    # ── Personality-driven narrative ──
    personality_lines = _get_personality_narrative(player, base_effects)
    if personality_lines:
        narrative_parts.extend(personality_lines)

    # ── Action narrative (input-aware) ──
    narrative_parts.append(_get_action_narrative(intent, player, world, player_decision))

    # ── Aftermath: show specific consequence of player's words ──
    aftermath_text = _compute_aftermath(player_decision, world, player)
    # Displayed as separate panel in CLI, not part of narrative
    advisor_feedback = _generate_advisor_feedback(player_decision, world, player, intent)

    # ── Random knowledge-driven events ──
    event_result = _try_random_event(player, memory, world)
    if event_result:
        narrative_parts.append(f"\n⚡ **{event_result['title']}**")
        narrative_parts.append(event_result["narrative"])
        _merge_effects(base_effects, event_result["effects"])

    # ── NPC actions (personality-driven) ──
    npc_actions, npc_changes = _simulate_npcs_knowledge(world, intent, player)

    # ── Inter-faction dynamics ──
    rivalry = _generate_faction_dynamics(world, player)
    for r in rivalry:
        narrative_parts.append(f"\n🔥 {r['narrative']}")
        _merge_effects(base_effects, r["effects"])
        npc_actions.append(r["npc_msg"])

    # ── Reference past memories ──
    recent = get_recent_memories(memory, 3)
    if recent and random.random() < 0.25:
        past = random.choice(recent)
        past_narrative = past.get("narrative", "")
        # Use first meaningful sentence instead of raw [:30]
        past_snippet = ""
        for sep in ["。", "！", "？", "\n"]:
            if sep in past_narrative:
                past_snippet = past_narrative.split(sep)[0] + sep
                break
        if not past_snippet:
            past_snippet = past_narrative[:40]
        if past_snippet:
            narrative_parts.append(
                f"\n📖 回想起来，自「{past_snippet}」已经过去了……"
            )

    # ── Apply effects ──
    _apply_effects(player, base_effects)
    for fa_id, changes in npc_changes.items():
        _apply_npc_changes(world, fa_id, changes)

    # ── Stats summary ──
    narrative_parts.append("")
    for key, label in [("strength", "兵力"), ("economy", "经济"),
                        ("morale", "民心"), ("treasury", "资金"),
                        ("food", "粮草")]:
        change = base_effects.get(key, 0)
        if change:
            new_val = getattr(player, key, 0)
            narrative_parts.append(f"{label}：{change:+d} → {new_val:,}")

    # ── Save memory ──
    intro = narrative_parts[1] if len(narrative_parts) > 1 else narrative_parts[0] if narrative_parts else ""
    add_memory_entry(memory, world.turn_count, world.current_year,
                     world.current_season, player_decision, intro)

    # ── Check game over ──
    game_over = _check_game_over(world, memory)
    if game_over:
        narrative_parts.append(f"\n\n{'═' * 50}")
        narrative_parts.append(game_over["message"])
        return _make_result(narrative_parts, npc_actions, {}, [], game_over,
                            aftermath_text, advisor_feedback)

    # ── Events from knowledge base ──
    events_occurred = _check_knowledge_events(world)
    choices = _generate_choices(intent, world)

    return _make_result(narrative_parts, npc_actions, {}, events_occurred,
                        aftermath=aftermath_text,
                        advisor_feedback=advisor_feedback,
                        choices=choices)


# ─── Knowledge helpers ─────────────────────────────────────────

def _get_character_effects(faction: "Faction") -> dict:
    """Get state effects from the ruler's personality traits."""
    effects = {}
    ruler_data = None
    for c in CHARACTERS:
        if c["id"] == faction.ruler_id:
            ruler_data = c
            break
    if not ruler_data:
        return effects

    for trait in ruler_data.get("personality", []):
        trait_effects = PERSONALITY_EFFECTS.get(trait, {})
        for k, v in trait_effects.items():
            effects[k] = effects.get(k, 0) + v

    return effects


def _get_knowledge_intro(world: "GameWorld", faction: "Faction") -> str:
    """Season intro that uses knowledge data."""
    region_data = None
    for r in REGIONS_RAW:
        # Match by region id or by capital name match
        if r["id"] == faction.capital or r["capital"] == faction.capital:
            region_data = r
            break

    capital_name = region_data["capital"] if region_data else CAPITAL_NAMES.get(faction.capital, faction.capital)
    # Don't overwrite with English fallback — keep Chinese name

    leader_data = None
    for c in CHARACTERS:
        if c["id"] == faction.ruler_id:
            leader_data = c
            break

    leader_name = leader_data["name"] if leader_data else faction.name
    flavors = SEASON_FLAVOR.get(world.current_season, ["季节更替，天下依旧纷争不断。"])
    flavor = random.choice(flavors)

    try:
        return f"【{world.current_year}年 · {'春夏秋冬'[['spring','summer','autumn','winter'].index(world.current_season)]}季】\n" + \
               flavor.format(capital=capital_name, leader=leader_name,
                             faction=faction.name, region=capital_name)
    except (KeyError, ValueError):
        return f"【{world.current_year}年 · {world.current_season}季】\n{flavor}"


def _get_personality_narrative(faction: "Faction", effects: dict) -> list[str]:
    """Generate narrative based on character personality."""
    lines = []
    leader_data = None
    for c in CHARACTERS:
        if c["id"] == faction.ruler_id:
            leader_data = c
            break
    if not leader_data:
        return lines

    for trait in leader_data.get("personality", []):
        narration = PERSONALITY_NARRATIVES.get(trait)
        if narration and random.random() < 0.35:
            lines.append(f"💭 {narration}")
            break

    return lines


def _process_event_chain_knowledge(world: "GameWorld", player: "Faction",
                                   memory: dict) -> Optional[str]:
    """Process active event chains with knowledge-aware templates."""
    log_text = "\n".join(world.history_log)
    decision_text = " ".join(d.get("decision", "") for d in memory["decisions"])

    # Determine if player is anti-Dong Zhuo
    pro_coalition = any(kw in decision_text for kw in ["讨董", "联盟", "袁绍", "联军"])

    for chain_name, chain in EVENT_CHAINS.items():
        # Check if ALL stages of this chain are already completed
        all_done = True
        for s in chain["stages"]:
            if s["title"] not in log_text:
                all_done = False
                break
        if all_done:
            continue

        stages_done = sum(1 for s in chain["stages"] if s["title"] in log_text)
        if stages_done < len(chain["stages"]):
            stage = chain["stages"][stages_done]
            template = stage["narrative_template"]

            # Fill knowledge-aware template vars

            # Fill knowledge-aware template vars
            dong_char = None
            yuan_shao_char = None
            for c in CHARACTERS:
                if c["id"] == "dongzhuo": dong_char = c
                if c["id"] == "yuanshao": yuan_shao_char = c

            ye_city = "邺城"
            dong_react = "董卓闻讯大惊，召集李傕、郭汜等西凉将领商议对策。"
            yuan_shu_behavior = "袁术断孙坚粮草，"
            player_impact = ""
            new_power = "一个名叫刘表的荆州刺史正在南方悄然崛起……"

            # Apply personality effects
            if dong_char and "残暴" in dong_char.get("personality", []):
                dong_react = "董卓勃然大怒，下令屠杀洛阳富户，准备迁都长安。"
            if yuan_shao_char and "好谋无断" in yuan_shao_char.get("personality", []):
                yuan_shu_behavior = "袁术断孙坚粮草，袁绍按兵不动，"

            try:
                # Record this stage as completed
                world.history_log.append(f"[事件链] {chain_name}: {stage['title']}")
                return f"\n📜 **{stage['title']}**\n" + \
                       template.format(ye_city=ye_city, dong_reaction=dong_react,
                                       yuan_shu_behavior=yuan_shu_behavior,
                                       player_impact=player_impact,
                                       new_power_rise=new_power)
            except KeyError:
                world.history_log.append(f"[事件链] {chain_name}: {stage['title']}")
                return f"\n📜 **{stage['title']}**\n" + stage["narrative_template"]

    return None


def _try_random_event(player: "Faction", memory: dict,
                      world: "GameWorld") -> Optional[dict]:
    """Try to trigger a random event with knowledge-aware narrative."""
    if random.random() > 0.45:
        return None

    event = random.choice(RANDOM_EVENTS)
    if not event["condition"](player, memory):
        return None

    # Fill knowledge-aware template
    enemies = [f for f in world.factions.values()
               if f.is_active and f.id != world.player_faction_id]
    enemy_name = random.choice(enemies).name if enemies else "敌军"
    directions = ["东方", "西方", "北方", "南方", "西北", "东北"]
    stylenames = ["清瘦", "仙风道骨", "儒雅", "豪迈", "朴拙"]
    names_list = ["徐庶", "庞德公", "司马徽", "崔州平", "石广元"]
    adjectives = ["难得", "罕见", "十年一遇", "百年难遇"]

    template = event.get("narrative_template", event.get("narrative", ""))
    try:
        narrative = template.format(
            enemy=enemy_name, direction=random.choice(directions),
            style=random.choice(stylenames), name=random.choice(names_list),
            adjective=random.choice(adjectives),
        )
    except KeyError:
        narrative = template

    return {
        "title": event["title"],
        "narrative": narrative,
        "effects": event["effects"],
    }


def _simulate_npcs_knowledge(world: "GameWorld", player_intent: str,
                             player: "Faction") -> tuple[list[str], dict]:
    """Simulate NPCs using faction personality data."""
    actions = []
    changes = {}

    for fa_id, fa in world.factions.items():
        if fa.id == world.player_faction_id or not fa.is_active:
            continue

        # Find raw faction data for diplomacy_tendency
        raw_faction = None
        for rf in FACTIONS_RAW:
            if rf["id"] == fa.id:
                raw_faction = rf
                break

        change = {"strength": random.randint(-1000, 3000)}
        if random.random() < 0.3:
            change["economy"] = random.randint(-3, 5)

        # Personality-driven behaviors
        tendency = raw_faction.get("diplomacy_tendency", "neutral") if raw_faction else "neutral"
        aggression = raw_faction.get("aggression", 50) if raw_faction else 50

        # Aggressive factions expand
        if aggression > 60 and random.random() < 0.35:
            bonus = random.randint(2000, 6000)
            change["strength"] = change.get("strength", 0) + bonus
            actions.append(f"⚔ {fa.name}（{TENDENCY_CN.get(tendency, tendency)}）在边境频繁调动军队。")

        # Defensive factions fortify
        if tendency == "defensive" and random.random() < 0.25:
            change["strength"] = change.get("strength", 0) + 1000
            change["morale"] = change.get("morale", 0) + 2

        # Hostile factions react to military buildup
        if (tendency == "hostile" and player_intent == "military"):
            change["strength"] = change.get("strength", 0) + random.randint(2000, 5000)

        # Friendly factions are open to diplomacy
        if tendency == "friendly" and player_intent == "diplomacy":
            change["morale"] = change.get("morale", 0) + 3
            if random.random() < 0.25:
                actions.append(f"✉ {fa.name}对你的使者以礼相待，表示愿意结盟。")

        # Arrogant factions are dismissive
        if tendency == "arrogant":
            change["morale"] = change.get("morale", 0) - 2

        changes[fa_id] = change

    return actions, changes


def _generate_faction_dynamics(world: "GameWorld",
                               player: "Faction") -> list[dict]:
    """Generate emergent faction dynamics (wars, alliances)."""
    events = []
    strong = [f for f in world.factions.values()
              if f.is_active and f.id != world.player_faction_id and f.strength > 25000]

    if len(strong) >= 2 and random.random() < 0.12:
        a, b = random.sample(strong, 2)

        # Find personality traits
        a_raw, b_raw = None, None
        for rf in FACTIONS_RAW:
            if rf["id"] == a.id: a_raw = rf
            if rf["id"] == b.id: b_raw = rf

        a_tendency = a_raw.get("diplomacy_tendency", "neutral") if a_raw else "neutral"
        b_tendency = b_raw.get("diplomacy_tendency", "neutral") if b_raw else "neutral"

        if random.random() < 0.5 or a_tendency == "hostile" or b_tendency == "hostile":
            events.append({
                "narrative": f"{a.name}（{TENDENCY_CN.get(a_tendency, a_tendency)}）与{b.name}（{TENDENCY_CN.get(b_tendency, b_tendency)}）因边境冲突爆发了局部战争！",
                "effects": {"economy": -1, "morale": -1},
                "npc_msg": f"🔥 {a.name} 与 {b.name} 正在交战中！",
            })
        else:
            events.append({
                "narrative": f"有消息称{a.name}与{b.name}秘密结成了同盟。",
                "effects": {"morale": -2},
                "npc_msg": f"🔗 {a.name} 与 {b.name} 结成了同盟。",
            })

    return events


def _check_knowledge_events(world: "GameWorld") -> list[str]:
    """Check and trigger knowledge-base events."""
    occurred = []
    for event in world.get_available_events()[:2]:
        occurred.append(event.title)
        world.mark_event_occurred(event.title)
    return occurred


def _check_game_over(world: "GameWorld", memory: dict) -> Optional[dict]:
    """Check win/loss conditions with memory-based scoring."""
    player = world.get_player_faction()
    if not player:
        return None

    # Determine ruler name
    ruler_name = "你"
    for c in CHARACTERS:
        if c["id"] == player.ruler_id:
            ruler_name = c["name"]
            break

    turns = world.turn_count

    # Min 12 turns before any victory
    if turns < 12:
        return None

    if player.strength >= 120000:
        return {
            "type": "victory",
            "message": (
                f"🎉 **大业已成！**\n\n"
                f"{ruler_name}的军队已达 120,000 人，\n"
                f"天下无人能与你抗衡。诸侯纷纷遣使纳贡，\n"
                f"史书记载：{ruler_name}用了{turns}个回合（约{turns*3}个月）\n"
                f"从一方诸侯成长为天下霸主。\n\n"
                f"🏆 **最终评分**：{_calculate_score(world, memory, ruler_name)}"
            ),
        }

    if player.economy >= 85 and player.morale >= 90 and player.strength >= 50000:
        return {
            "type": "victory",
            "message": (
                f"🎉 **盛世明君！**\n\n"
                f"在{ruler_name}的治理下，百姓安居乐业，路不拾遗。\n"
                f"四方英才纷纷来投。\n"
                f"你用了{turns}个回合，将一方土地治理成了人间乐土。\n\n"
                f"🏆 **最终评分**：{_calculate_score(world, memory, ruler_name)}"
            ),
        }

    if player.morale <= 0:
        return {
            "type": "defeat",
            "message": (
                f"💀 **民心尽失！**\n\n"
                f"{ruler_name}的暴政终于引发了民变。各地百姓揭竿而起，\n"
                f"在熊熊烈火中，{ruler_name}望着曾经辉煌的宫殿化为灰烬……\n"
                f"坚持了{turns}个回合。\n\n"
                f"🏆 **最终评分**：{_calculate_score(world, memory, ruler_name)}"
            ),
        }

    if player.strength <= 0:
        return {
            "type": "defeat",
            "message": (
                f"💀 **军队覆灭！**\n\n"
                f"{ruler_name}的大军在最后一战中全军覆没。\n"
                f"敌人踏着将士们的尸体攻入了都城。\n"
                f"坚持了{turns}个回合。\n\n"
                f"🏆 **最终评分**：{_calculate_score(world, memory, ruler_name)}"
            ),
        }

    return None


def _calculate_score(world: "GameWorld", memory: dict, ruler: str) -> str:
    """Calculate final score with tiered ranks."""
    player = world.get_player_faction()
    if not player:
        return "0 — 无名小卒"

    base = 0
    base += player.strength // 1000 * 10
    base += player.economy * 5
    base += player.morale * 5
    base += player.treasury // 100
    base += len([r for r in world.regions.values() if r.owner == player.id]) * 50
    base += world.turn_count * 2
    base += len(memory.get("decisions", [])) * 5
    base = min(1000, base)

    ranks = [
        (900, "👑 千古一帝"),
        (700, "⭐ 一代枭雄"),
        (500, "📜 名垂青史"),
        (300, "📖 一方诸侯"),
        (100, "📋 乱世平民"),
    ]
    rank = "💀 过眼云烟"
    for threshold, title in ranks:
        if base >= threshold:
            rank = title
            break

    return f"{base}/1000 — {rank}"


# ─── Helper functions ──────────────────────────────────────────

def _classify_intent(text: str) -> str:
    # Multi-char keywords (higher priority)
    economy_bigrams = ["发展经济", "屯田", "兴修水利", "内政", "建设", "发展"]
    military_bigrams = ["讨伐", "征伐", "扩军", "备战", "出征", "攻打", "出兵", "北伐"]
    diplomacy_bigrams = ["联合", "结盟", "联盟", "出使", "和亲", "连横", "合纵", "结交"]
    defense_bigrams = ["加固", "城防", "防守", "防御", "固守", "坚守"]
    spy_bigrams = ["情报", "间谍", "细作", "侦查", "刺探", "密报"]

    military = ["兵", "军", "战", "攻", "讨", "伐", "征", "袭", "击", "破", "灭"]
    economy = ["经济", "农", "粮", "钱", "税", "商", "耕", "屯", "富"]
    diplomacy = ["联", "交", "盟", "使", "和", "谈", "亲", "结", "连", "通"]
    defense = ["守", "防", "固", "保", "筑", "城", "壁", "垒", "御"]
    spy = ["间", "谍", "刺", "暗", "潜", "细", "查", "探", "密"]

    # Bigrams get 3x weight
    score = {}
    for k, v in [("economy", economy_bigrams), ("military", military_bigrams),
                  ("diplomacy", diplomacy_bigrams), ("defense", defense_bigrams),
                  ("spy", spy_bigrams)]:
        score[k] = sum(3 for kw in v if kw in text)

    # Single chars get 1x weight, but subtract if already counted by bigrams
    for k, v in [("military", military), ("economy", economy),
                  ("diplomacy", diplomacy), ("defense", defense),
                  ("spy", spy)]:
        score[k] = score.get(k, 0) + sum(1 for kw in v if kw in text)

    if text.strip().isdigit():
        return {1: "military", 2: "economy", 3: "diplomacy",
                4: "defense", 5: "spy"}.get(int(text.strip()), "economy")

    best = max(score, key=score.get)
    return best if score[best] > 0 else "economy"


def _compute_base_effects(intent: str, player: "Faction") -> dict:
    effects = {"strength": 0, "economy": 0, "morale": 0, "treasury": 0, "food": 0}
    if intent == "military":
        effects.update(strength=random.randint(2000, 5000), treasury=-random.randint(500, 1500),
                       food=-random.randint(200, 500), morale=random.randint(0, 2),
                       economy=-random.randint(0, 2))
    elif intent == "economy":
        effects.update(economy=random.randint(1, 4), food=random.randint(200, 800),
                       treasury=random.randint(100, 500), morale=random.randint(1, 3),
                       strength=random.randint(0, 500))
    elif intent == "diplomacy":
        effects.update(morale=random.randint(0, 2), treasury=-random.randint(100, 300),
                       economy=random.randint(0, 2), strength=random.randint(0, 500))
    elif intent == "defense":
        effects.update(morale=random.randint(1, 3), strength=random.randint(500, 2000),
                       treasury=-random.randint(200, 500), food=-random.randint(100, 200))
    elif intent == "spy":
        effects.update(treasury=-random.randint(200, 500), strength=random.randint(0, 300))
    else:
        effects.update(economy=random.randint(0, 2), morale=random.randint(0, 2),
                       treasury=random.randint(50, 200), food=random.randint(50, 200))
    return effects


def _get_action_narrative(intent: str, player: "Faction",
                          world: "GameWorld", player_decision: str = "") -> str:
    """Generate action narrative that reflects what the player actually said."""
    ruler = "君主"
    for c in CHARACTERS:
        if c["id"] == player.ruler_id:
            ruler = c["name"]
            break

    capital = player.capital
    for r in REGIONS_RAW:
        if r["id"] == capital or r["capital"] == capital:
            capital = r["capital"]
            break

    # Extract a short summary of what player said for the narrative
    decision_short = player_decision
    # Remove "选择第N个方案" prefix for cleaner reading
    if "选择第" in decision_short and "个方案" in decision_short:
        decision_short = "你做出了战略选择"
    # Truncate for display
    if len(decision_short) > 30:
        decision_short = decision_short[:30] + "…"

    narratives = {
        "military": (
            f"你采纳了「{decision_short}」的战略。{ruler}下令征募新军，加紧操练。\n"
            f"各地青壮年纷纷投军报效，军需官忙得不可开交。"
        ),
        "economy": (
            f"你推行「{decision_short}」的方略，减免赋税，兴修水利。{capital}一带\n"
            f"百姓安居乐业，田野间一片繁忙景象。"
        ),
        "diplomacy": (
            f"你决定「{decision_short}」。精干使节携带厚礼与书信，\n"
            f"出使各方势力。外交的帷幕缓缓拉开。"
        ),
        "defense": (
            f"你下令「{decision_short}」。{ruler}巡视边境，\n"
            f"加固城防工事，{capital}城头的旗帜在风中飘扬。"
        ),
        "spy": (
            f"你密令「{decision_short}」。数名精锐细作连夜出发，\n"
            f"消失在夜色中——他们的回报将决定下一步的棋局。"
        ),
    }
    return narratives.get(intent,
        f"{ruler}决定「{decision_short}」。采取了稳健的治理方针，各方面稳步发展。")


def _compute_aftermath(player_decision: str, world: "GameWorld",
                      player: "Faction") -> str:
    """Generate specific consequences based on player's actual words."""
    text = player_decision.lower()
    effects = []

    # Keyword → consequence mapping
    keyword_map = [
        (["讨董", "讨伐", "伐董", "攻打董卓"], "讨董檄文传遍天下，袁绍为首的关东联军声势大振"),
        (["联孙", "联合孙", "孙坚", "结盟孙"], "孙坚表示愿意与你结盟，江东猛虎成为你的有力后援"),
        (["联袁", "联合袁", "袁绍", "结盟袁"], "袁绍对你的使者以礼相待，表示愿意协同作战"),
        (["联刘", "联合刘", "刘备", "刘表"], "你的使者抵达荆州，对方表示愿意保持友好关系"),
        (["屯田", "开垦", "修水利", "兴农"], "庄稼长势喜人，各地粮仓开始充盈"),
        (["征兵", "扩军", "训练", "操练"], "新兵陆续报到，{capital}城外的校场上喊杀声震天"),
        (["征伐", "出征", "派出军队"], "大军开拔，旌旗蔽日，百姓夹道相送"),
        (["情报", "间谍", "细作", "侦查"], "细作传回密报：{enemy}正在边境集结兵力"),
        (["称帝", "称王", "建国", "自立"], "此议时机未到，谋士们纷纷劝谏不可操之过急"),
        (["禅让", "让位", "退位"], "此言一出，帐下一片哗然——大业未成，何以言退？"),
        (["联姻", "婚", "和亲", "嫁女"], "联姻之事需要慎重，你决定先派使者试探对方意向"),
    ]

    capital = player.capital
    for r in REGIONS_RAW:
        if r["id"] == capital or r["capital"] == capital:
            capital = r["capital"]
            break

    # Find enemies for filler
    enemies = [f for f in world.factions.values()
               if f.is_active and f.id != world.player_faction_id]
    enemy_name = random.choice(enemies).name if enemies else "敌军"

    for keywords, consequence in keyword_map:
        if any(kw in text for kw in keywords):
            try:
                effects.append(consequence.format(capital=capital, enemy=enemy_name))
            except KeyError:
                effects.append(consequence)
            break  # Only one consequence per turn

    if not effects:
        # Generic consequence based on intent
        intent = _classify_intent(text)
        generic = {
            "military": "军队开始调动，战争的阴影笼罩大地。",
            "economy": "政令下达各州郡，官员们开始执行你的决策。",
            "diplomacy": "使节们日夜兼程，赶赴各方势力的都城。",
            "defense": "边境各寨的守军提高了警惕。",
            "spy": "情报网正在织就……",
        }
        effects.append(generic.get(intent, "你的决策传遍各州郡，文武官员各司其职。"))

    return " ".join(effects)


def _generate_advisor_feedback(
    player_decision: str,
    world: "GameWorld",
    player: "Faction",
    intent: Optional[str] = None,
) -> dict:
    """Generate an immediate, strategy-aware advisor response.

    This is deliberately deterministic-ish and non-mutating: it helps the
    player feel understood before the seasonal report resolves outcomes.
    """
    text = player_decision.lower()
    intent = intent or _classify_intent(text)

    ruler_name = "主公"
    for c in CHARACTERS:
        if c["id"] == player.ruler_id:
            ruler_name = c["name"]
            break

    domains: list[str] = []
    strategic_read: list[str] = []
    risks: list[str] = []
    execution: list[str] = []

    def add_domain(name: str):
        if name not in domains:
            domains.append(name)

    if any(kw in text for kw in ["皇帝", "天子", "汉室", "正统", "大义", "旗帜"]):
        add_domain("legitimacy")
        strategic_read.append("以天子与汉室名义重建合法性，可争取士人和观望诸侯。")
        risks.append("过早高举天子大义会让袁绍、董卓等势力警惕你的政治野心。")
        execution.append("先用诏令、檄文和安民告示塑造秩序叙事，避免立刻挑战盟主权威。")

    if any(kw in text for kw in ["民众", "百姓", "流民", "人心", "民心", "教育", "识字", "算数"]):
        add_domain("governance")
        strategic_read.append("你是在把民众视为劳力、兵源和政治支持，而不只是税粮来源。")
        risks.append("安置流民与兴学短期消耗粮草和官吏能力，执行过急会扰动地方豪强。")
        execution.append("将流民分为屯田、工役、军籍三类，并提拔可靠吏员登记户籍。")

    if any(kw in text for kw in ["市场", "贸易", "商", "商贸", "商旅", "大市场", "货殖"]):
        add_domain("economy")
        strategic_read.append("统一市场叙事能把战争目标转化为商旅、工匠和城市百姓能理解的利益。")
        risks.append("统一度量衡、税卡和市令会触碰地方豪强与既得税吏的利益。")
        execution.append("先修护商道、平粮价、减重复关税，让商旅成为你的情报与财政网络。")

    if any(kw in text for kw in ["诸侯", "鬼胎", "各方", "袁绍", "董卓", "刘表", "孙坚"]):
        add_domain("intelligence")
        strategic_read.append("你已意识到诸侯联盟并非铁板一块，关键在于识别谁怕董卓、谁怕你坐大。")
        risks.append("若情报不足就公开表态，可能同时得罪盟友和敌人。")
        execution.append("派商旅、使者和细作分别探查诸侯粮道、将领矛盾与盟约可信度。")

    if any(kw in text for kw in ["编入军", "征兵", "训练", "军部", "出兵", "讨伐", "统一"]):
        add_domain("military")
        strategic_read.append("军事整合可以把流民压力转为兵源，但需要粮草和军纪支撑。")
        risks.append("仓促扩军会稀释训练质量，且可能降低民心与粮草安全。")
        execution.append("先设屯田兵与郡县预备队，精锐部曲用于机动作战。")

    if any(kw in text for kw in ["人才", "提拔", "任用", "贤", "担任要位", "官"]):
        add_domain("personnel")
        strategic_read.append("提拔有才能之人能提高执行力，也能向寒门与流民释放上升通道。")
        risks.append("破格用人会引起旧吏与地方士族不满，需要用考课和功劳压服反对。")
        execution.append("设临时考课，按屯田、治安、军纪三项授职，先小任后大用。")

    if not strategic_read:
        generic = {
            "military": "此策重在扩张军势，短期可增强威慑，长期取决于粮道与军纪。",
            "economy": "此策重在稳固内政，能改善财政和民生，但见效慢于军事行动。",
            "diplomacy": "此策重在借外势破局，关键是分清盟友的真实利益。",
            "defense": "此策重在保存实力，适合局势未明时稳住根基。",
            "spy": "此策重在先知先觉，能降低误判，但需要持续投入。",
        }
        add_domain(intent)
        strategic_read.append(generic.get(intent, "此策可行，但需要拆成更明确的政令、目标和执行顺序。"))
        risks.append("命令若过于宽泛，地方官只能按旧例执行，难以形成真正的新战略。")
        execution.append("把本季度目标限定为一到两件可验收的政务或军务。")

    if not risks:
        risks.append("最大风险在于目标过多，执行官吏各取所需，导致效果被摊薄。")
    if not execution:
        execution.append("先选一郡试行，再根据粮草、民心和诸侯反应扩展。")

    decision_short = player_decision.strip()
    if len(decision_short) > 48:
        decision_short = decision_short[:48] + "..."

    return {
        "understanding": f"幕府以为，{ruler_name}此令的核心不是一句「{decision_short}」，而是要把{_join_domains(domains)}转成可执行的季度政略。",
        "strategic_read": strategic_read[:4],
        "risks": risks[:3],
        "recommended_execution": execution[:3],
        "clarifying_question": None,
    }


def _join_domains(domains: list[str]) -> str:
    labels = {
        "military": "军事",
        "economy": "经济",
        "diplomacy": "外交",
        "legitimacy": "合法性",
        "governance": "治理",
        "intelligence": "情报",
        "personnel": "任官",
        "defense": "防务",
        "spy": "密探",
    }
    if not domains:
        return "战略意图"
    return "、".join(labels.get(d, d) for d in domains)


def _merge_effects(base: dict, addition: dict) -> None:
    for k, v in addition.items():
        base[k] = base.get(k, 0) + v


def _apply_effects(player: "Faction", effects: dict) -> None:
    clamped = {"economy": (0, 100), "morale": (0, 100)}
    for key, attr in [("strength", "strength"), ("economy", "economy"),
                       ("morale", "morale"), ("treasury", "treasury"),
                       ("food", "food")]:
        change = effects.get(key, 0)
        if change:
            current = getattr(player, attr, 0)
            new_val = current + change
            if attr in clamped:
                lo, hi = clamped[attr]
                new_val = max(lo, min(hi, new_val))
            else:
                new_val = max(0, new_val)
            setattr(player, attr, new_val)


def _apply_npc_changes(world: "GameWorld", fa_id: str, changes: dict) -> None:
    if fa_id in world.factions:
        fa = world.factions[fa_id]
        for k, v in changes.items():
            if hasattr(fa, k):
                current = getattr(fa, k)
                if isinstance(current, int):
                    setattr(fa, k, max(0, current + v))


def _generate_choices(intent: str, world: "GameWorld") -> list[str]:
    player = world.get_player_faction()
    if not player:
        return ["1. 发展经济", "2. 扩充军备", "3. 外交结盟"]

    choices = []
    choices.append("1. 🗡 扩军备战" if player.strength < 50000 else "1. 🗡 率军出征")

    if player.economy < 40:
        choices.append("2. 🌾 休养生息")
    elif player.economy < 70:
        choices.append("2. 🌾 发展商贸")
    else:
        choices.append("2. 🌾 改革税制")

    choices.append("3. 🤝 出使各方")

    if player.strength < 40000:
        choices.append("4. 🏰 加固城防")
    else:
        choices.append("4. 🏰 安抚边境")

    if player.treasury > 3000:
        choices.append("5. 🕵 搜集情报")

    choices.append("6. 📜 按兵不动")
    return choices[:6]


def _make_result(narrative_parts: list, npc_actions: list,
                 state: dict, events: list,
                 game_over: Optional[dict] = None,
                 aftermath: str = "",
                 advisor_feedback: Optional[dict] = None,
                 choices: Optional[list[str]] = None) -> dict:
    return {
        "narrative": "\n".join(narrative_parts),
        "npc_actions": npc_actions or ["天下局势正在微妙变化中……"],
        "state_changes": state,
        "events_occurred": events,
        "new_choices": choices or [],
        "game_over": game_over,
        "aftermath": aftermath,
        "advisor_feedback": advisor_feedback or {},
    }


def _empty_result() -> dict:
    return {
        "narrative": "局势不明，请重新决策。",
        "npc_actions": [],
        "state_changes": {},
        "events_occurred": [],
        "new_choices": ["1. 联络袁绍", "2. 发展经济", "3. 征兵备战"],
        "game_over": None,
        "advisor_feedback": {},
    }
