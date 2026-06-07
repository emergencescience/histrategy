"""E2E headless test — exercises all engines including History + RAG.

Scenarios:
  1. 刘备历史路线 (207-223, historical path)
  2. 刘备替代路线 (stay in Jingzhou, don't enter Shu)
  3. 曹操视角 (unify China)
  4. 孙权视角 (Red Cliffs + Jingzhou game)

Each scenario outputs to logs/e2e-scenario-*.log
"""
import os
import sys

sys.path.insert(0, "/opt/data/repos/histrategy/histrategy-engine/src")

from histrategy_engine import (
    Army,
    Character,
    CharacterEngine,
    ClimateEvent,
    ClimateSystem,
    Command,
    DecisionEngine,
    DomesticEngine,
    FactionState,
    HistoricalRAG,
    HistoryEngine,
    MapEngine,
    MilitaryEngine,
    Season,
    TerrainType,
    Territory,
    TurnController,
    TurnResult,
    UnitType,
    WorldState,
)

# ─── Logging setup ───
log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(log_dir, exist_ok=True)

KNOWLEDGE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "histrategy-knowledge"
)


def header(text: str) -> str:
    return f"\n{'=' * 60}\n{text}\n{'=' * 60}"


def write_log(filename: str, lines: list[str]):
    filepath = os.path.join(log_dir, filename)
    with open(filepath, "w") as f:
        f.write("\n".join(lines))
    print(f"  -> Log written: {filepath}")


# ═══════════════════════════════════════════════════════════════
# Scenario 1: 刘备历史路线 (207-223)
# ═══════════════════════════════════════════════════════════════


def scenario_1_liubei_historical():
    print(header("Scenario 1: 刘备历史路线 (207冬 → 223春)"))
    log = []

    # Setup engines
    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    hist_eng = HistoryEngine(KNOWLEDGE_PATH)
    rag = HistoricalRAG(KNOWLEDGE_PATH)

    # Build initial world state
    territories = {
        "xinye": Territory(id="xinye", name="新野", owner_id="shu",
            fertility=6, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=30000, development=25,
            neighbors=["xiangyang", "wancheng"]),
        "xiangyang": Territory(id="xiangyang", name="襄阳", owner_id="liubiao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=80000, development=55,
            neighbors=["xinye", "jiangling", "wancheng"]),
        "wancheng": Territory(id="wancheng", name="宛城", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=50000, development=45,
            neighbors=["xinye", "xiangyang", "xuchang"]),
        "xuchang": Territory(id="xuchang", name="许昌", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=100000, development=70,
            neighbors=["wancheng"]),
        "jiangling": Territory(id="jiangling", name="江陵", owner_id="liubiao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=60000, development=50,
            neighbors=["xiangyang"]),
        "jiangkou": Territory(id="jiangkou", name="江口", owner_id="",
            fertility=5, terrain_type=TerrainType.RIVER, climate_zone="central",
            has_river=True, population=15000, development=20,
            neighbors=["xiangyang", "jiangling"]),
    }

    characters = {
        "liubei": Character(id="liubei", name="刘备", alias="玄德",
            leadership=80, might=70, intelligence=72, politics=82, charisma=99,
            faction_id="shu", location="xinye", loyalty=100,
            birth=161, death=223),
        "guanyu": Character(id="guanyu", name="关羽", alias="云长",
            leadership=95, might=98, intelligence=75, politics=62, charisma=88,
            faction_id="shu", location="xinye", loyalty=100, is_commanding=True,
            birth=160, death=220),
        "zhangfei": Character(id="zhangfei", name="张飞", alias="翼德",
            leadership=85, might=98, intelligence=45, politics=30, charisma=50,
            faction_id="shu", location="xinye", loyalty=98,
            birth=165, death=221),
        "zhugeliang": Character(id="zhugeliang", name="诸葛亮", alias="孔明",
            leadership=92, might=32, intelligence=100, politics=98, charisma=90,
            faction_id="", location="longzhong", loyalty=50,
            birth=181, death=234),
        "zhaoyun": Character(id="zhaoyun", name="赵云", alias="子龙",
            leadership=89, might=95, intelligence=76, politics=67, charisma=82,
            faction_id="shu", location="xinye", loyalty=95,
            birth=168, death=229),
        "caocao": Character(id="caocao", name="曹操", alias="孟德",
            leadership=98, might=72, intelligence=93, politics=94, charisma=92,
            faction_id="cao", location="xuchang", loyalty=100,
            birth=155, death=220),
        "sunquan": Character(id="sunquan", name="孙权", alias="仲谋",
            leadership=75, might=60, intelligence=82, politics=88, charisma=85,
            faction_id="wu", location="jianye", loyalty=100,
            birth=182, death=252),
        "zhouyu": Character(id="zhouyu", name="周瑜", alias="公瑾",
            leadership=95, might=65, intelligence=94, politics=80, charisma=85,
            faction_id="wu", location="chaisang", loyalty=90, is_commanding=True,
            birth=175, death=210),
        "liubiao": Character(id="liubiao", name="刘表", alias="景升",
            leadership=55, might=30, intelligence=68, politics=75, charisma=70,
            faction_id="liubiao", location="xiangyang", loyalty=100,
            birth=142, death=208),
    }

    factions = {
        "shu": FactionState(id="shu", name="刘备军", ruler_id="liubei",
            capital="xinye", territories=["xinye"],
            strength_actual=5000, treasury=3000, food=2000,
            tax_rate=0.2, morale_actual=70, prestige=35,
            relations={"cao": -80, "wu": 20, "liubiao": 40}),
        "cao": FactionState(id="cao", name="曹操军", ruler_id="caocao",
            capital="xuchang", territories=["xuchang", "wancheng"],
            strength_actual=150000, treasury=50000, food=30000,
            tax_rate=0.4, morale_actual=80, prestige=90,
            relations={"shu": -80, "wu": -30, "liubiao": -20}),
        "wu": FactionState(id="wu", name="孙权军", ruler_id="sunquan",
            capital="jianye", territories=[],
            strength_actual=60000, treasury=15000, food=10000,
            tax_rate=0.3, morale_actual=75, prestige=60,
            relations={"shu": 20, "cao": -30, "liubiao": -10}),
        "liubiao": FactionState(id="liubiao", name="刘表军", ruler_id="liubiao",
            capital="xiangyang", territories=["xiangyang", "jiangling"],
            strength_actual=40000, treasury=10000, food=8000,
            tax_rate=0.3, morale_actual=50, prestige=50,
            relations={"shu": 40, "cao": -20, "wu": -10}),
    }

    armies = {
        "army_shu_1": Army(id="army_shu_1", faction_id="shu", location="xinye",
            commander_id="guanyu",
            units={UnitType.INFANTRY: 1500},
            morale=85, training=1.0, supply=30),
        "army_cao_1": Army(id="army_cao_1", faction_id="cao", location="wancheng",
            commander_id="caocao",
            units={UnitType.INFANTRY: 8000, UnitType.CAVALRY: 2000},
            morale=80, training=1.0, supply=30),
    }

    map_eng.load_territories(territories)
    char_eng.load_characters(characters)

    world = WorldState(
        year=207, season=Season.WINTER, turn_number=1,
        scenario="207", player_faction_id="shu",
        territories=territories, characters=characters, factions=factions, armies=armies,
        player_deviation=0.0,
    )

    log.append(f"Histrategy E2E — Scenario 1: 刘备历史路线")
    log.append(f"起始: 公元{world.year}年{world.season.cn}")
    log.append(f"RAG 年份覆盖: {rag.year_coverage}")
    log.append(f"知识库事件数: {hist_eng.event_count}")

    # Sim 207冬 → 223春 turns
    for turn_num in range(1, 60):
        year_before = world.year
        season_before = world.season

        # Get historical events for this turn
        proposals = hist_eng.check_events(world.year, world.season, world, deviation=world.player_deviation)

        for p in proposals:
            log.append(f"  [Event] {world.year}年{world.season.cn} — {p.title}: {p.narrative_hint[:60]}")

        # RAG context
        rag_events = rag.retrieve(world.year, deviation=world.player_deviation, max_events=4)

        # Player commands — historical path
        cmds = _get_liubei_historical_commands(world)

        # Execute turn
        result = tc.execute_turn(world, player_commands=cmds, year=world.year, turn_number=turn_num)

        # Apply historical scripted changes
        _apply_liubei_historical_script(world, turn_num)

        # Log significant events
        if result.battles:
            for b in result.battles:
                log.append(f"  [Battle] {world.year}年{world.season.cn} — {b.result.value}: {b.attacker_id} vs {b.defender_id}")

        for ce in result.character_events:
            if "death" in str(ce.get("type", "")):
                log.append(f"  [Death] {ce.get('character_name', '?')} 去世")

        # Stop at 223 spring
        if world.year >= 223 and world.season == Season.SPRING:
            break

    # Final RAG summary
    ctx = hist_eng.get_historical_context(223, deviation=world.player_deviation)
    log.append(f"\n{ctx}")

    log.append(f"\n最终状态: {world.year}年{world.season.cn}")
    log.append(f"刘备领土: {[territories[t].name for t in factions['shu'].territories]}")
    log.append(f"触发事件: {hist_eng.triggered_count}  未触发: {hist_eng.averted_count}")
    log.append(f"RAG LLM Context: {rag.build_llm_context(rag_events)}")

    write_log("e2e-scenario-1-liubei-historical.log", log)


def _get_liubei_historical_commands(world: WorldState) -> list[Command]:
    """Return historically accurate commands for Liu Bei."""
    cmds: list[Command] = []
    faction = world.factions.get("shu")
    if not faction:
        return cmds

    year = world.year

    # Early game (207-208): survive, recruit
    if year <= 208:
        if faction.food < 3000 and faction.territories:
            cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="shu"))
        elif faction.treasury > 1000 and faction.territories:
            cmds.append(Command(type="recruit", params={
                "territory": faction.territories[0], "unit_type": "infantry", "amount": 300
            }, faction_id="shu"))

    # Mid game (209-214): expand south, then west
    elif 209 <= year <= 214:
        if faction.strength_actual < 10000 and faction.treasury > 2000 and faction.territories:
            cmds.append(Command(type="recruit", params={
                "territory": faction.territories[0], "unit_type": "infantry", "amount": 500
            }, faction_id="shu"))
        elif faction.territories:
            cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="shu"))

    # Late game (215-223): consolidate
    elif year >= 215:
        if faction.territories:
            cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="shu"))
        if faction.food > 3000 and faction.treasury > 2000 and faction.territories:
            cmds.append(Command(type="recruit", params={
                "territory": faction.territories[0], "unit_type": "infantry", "amount": 300
            }, faction_id="shu"))

    return cmds


def _apply_liubei_historical_script(world: WorldState, turn_num: int):
    """Apply scripted historical changes to drive the simulation along historical path."""
    # 诸葛亮加入 (turn ~3)
    if turn_num == 3:
        zgl = world.characters.get("zhugeliang")
        if zgl and not zgl.faction_id:
            zgl.faction_id = "shu"
            zgl.location = "xinye"
            zgl.loyalty = 95
            zgl.is_governor = True

    # 刘表死亡，曹操接管荆州 (turn ~7)
    if turn_num == 7:
        liubiao = world.characters.get("liubiao")
        if liubiao:
            liubiao.alive = False
        lb = world.factions.get("liubiao")
        if lb:
            lb.is_active = False
        # Cao takes Xiangyang
        if "xiangyang" in world.territories:
            world.territories["xiangyang"].owner_id = "cao"
            if "cao" in world.factions:
                cao_f = world.factions["cao"]
                if "xiangyang" not in cao_f.territories:
                    cao_f.territories.append("xiangyang")

    # 赤壁之战 (turn ~11)
    if turn_num == 11:
        # Sun-Liu alliance forms
        if "wu" in world.factions:
            wu = world.factions["wu"]
            wu.relations["shu"] = 60
        if "shu" in world.factions:
            world.factions["shu"].relations["wu"] = 60

    # 荆南四郡 (turn ~15)
    if turn_num == 15:
        if "shu" in world.factions:
            shu = world.factions["shu"]
            for tid in ["jiangkou"]:
                if tid in world.territories and world.territories[tid].owner_id != "shu":
                    world.territories[tid].owner_id = "shu"
                    if tid not in shu.territories:
                        shu.territories.append(tid)

    # 入蜀 (turn ~25)
    if turn_num == 25:
        pangtong = world.characters.get("pangtong")
        if pangtong and pangtong.faction_id == "wu":
            pangtong.faction_id = "shu"
        # Add Chengdu-like territory
        if "shu" in world.factions:
            shu = world.factions["shu"]

    # 汉中 (turn ~40)
    # 关羽北伐 (turn ~45)
    # 夷陵 (turn ~52)
    # 托孤 (turn ~58)


# ═══════════════════════════════════════════════════════════════
# Scenario 2: 刘备替代路线 — 不入蜀
# ═══════════════════════════════════════════════════════════════


def scenario_2_liubei_alt_jingzhou():
    print(header("Scenario 2: 刘备替代路线 — 不入蜀，全力经营荆州"))
    log = []

    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    hist_eng = HistoryEngine(KNOWLEDGE_PATH)
    rag = HistoricalRAG(KNOWLEDGE_PATH)

    territories = {
        "xinye": Territory(id="xinye", name="新野", owner_id="shu",
            fertility=6, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=30000, development=25,
            neighbors=["xiangyang", "wancheng"]),
        "xiangyang": Territory(id="xiangyang", name="襄阳", owner_id="shu",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=80000, development=55,
            neighbors=["xinye", "jiangling", "wancheng"]),
        "wancheng": Territory(id="wancheng", name="宛城", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=50000, development=45,
            neighbors=["xinye", "xiangyang", "xuchang"]),
        "xuchang": Territory(id="xuchang", name="许昌", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=100000, development=70,
            neighbors=["wancheng"]),
        "jiangling": Territory(id="jiangling", name="江陵", owner_id="shu",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=60000, development=50,
            neighbors=["xiangyang"]),
        "changsha": Territory(id="changsha", name="长沙", owner_id="",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="south",
            population=40000, development=35,
            neighbors=["jiangling"]),
    }

    characters = {
        "liubei": Character(id="liubei", name="刘备", alias="玄德",
            leadership=80, might=70, intelligence=72, politics=82, charisma=99,
            faction_id="shu", location="xiangyang", loyalty=100,
            birth=161, death=223),
        "guanyu": Character(id="guanyu", name="关羽", alias="云长",
            leadership=95, might=98, intelligence=75, politics=62, charisma=88,
            faction_id="shu", location="xiangyang", loyalty=100, is_commanding=True,
            birth=160, death=220),
        "zhangfei": Character(id="zhangfei", name="张飞", alias="翼德",
            leadership=85, might=98, intelligence=45, politics=30, charisma=50,
            faction_id="shu", location="xinye", loyalty=98,
            birth=165, death=221),
        "zhugeliang": Character(id="zhugeliang", name="诸葛亮", alias="孔明",
            leadership=92, might=32, intelligence=100, politics=98, charisma=90,
            faction_id="shu", location="xiangyang", loyalty=95, is_governor=True,
            birth=181, death=234),
        "zhaoyun": Character(id="zhaoyun", name="赵云", alias="子龙",
            leadership=89, might=95, intelligence=76, politics=67, charisma=82,
            faction_id="shu", location="jiangling", loyalty=95,
            birth=168, death=229),
        "caocao": Character(id="caocao", name="曹操", alias="孟德",
            leadership=98, might=72, intelligence=93, politics=94, charisma=92,
            faction_id="cao", location="xuchang", loyalty=100,
            birth=155, death=220),
        "sunquan": Character(id="sunquan", name="孙权", alias="仲谋",
            leadership=75, might=60, intelligence=82, politics=88, charisma=85,
            faction_id="wu", location="jianye", loyalty=100,
            birth=182, death=252),
    }

    factions = {
        "shu": FactionState(id="shu", name="刘备军", ruler_id="liubei",
            capital="xiangyang", territories=["xiangyang", "jiangling", "xinye"],
            strength_actual=20000, treasury=8000, food=10000,
            tax_rate=0.25, morale_actual=80, prestige=50,
            relations={"cao": -80, "wu": 30}),
        "cao": FactionState(id="cao", name="曹操军", ruler_id="caocao",
            capital="xuchang", territories=["xuchang", "wancheng"],
            strength_actual=140000, treasury=45000, food=25000,
            tax_rate=0.4, morale_actual=75, prestige=90,
            relations={"shu": -80, "wu": -30}),
        "wu": FactionState(id="wu", name="孙权军", ruler_id="sunquan",
            capital="jianye", territories=[],
            strength_actual=55000, treasury=12000, food=8000,
            tax_rate=0.3, morale_actual=70, prestige=55,
            relations={"shu": 30, "cao": -30}),
    }

    armies = {
        "army_shu_1": Army(id="army_shu_1", faction_id="shu", location="xiangyang",
            commander_id="guanyu",
            units={UnitType.INFANTRY: 3000, UnitType.CAVALRY: 300},
            morale=88, training=1.0, supply=30),
        "army_shu_2": Army(id="army_shu_2", faction_id="shu", location="jiangling",
            commander_id="zhaoyun",
            units={UnitType.INFANTRY: 1500, UnitType.ARCHER: 500},
            morale=85, training=1.0, supply=30),
        "army_cao_1": Army(id="army_cao_1", faction_id="cao", location="wancheng",
            commander_id="caocao",
            units={UnitType.INFANTRY: 8000, UnitType.CAVALRY: 2000},
            morale=80, training=1.0, supply=30),
    }

    map_eng.load_territories(territories)
    char_eng.load_characters(characters)

    world = WorldState(
        year=209, season=Season.SPRING, turn_number=1,
        scenario="alt_jingzhou", player_faction_id="shu",
        territories=territories, characters=characters, factions=factions, armies=armies,
        player_deviation=0.5,
    )

    log.append("Histrategy E2E — Scenario 2: 刘备替代路线")
    log.append("路径: 赤壁后不入蜀，全力经营荆州，与孙权博弈")
    log.append(f"起始: 公元{world.year}年{world.season.cn}  偏离度: {world.player_deviation}")
    log.append(f"RAG 年份覆盖: {rag.year_coverage}")

    # High deviation → smaller RAG window
    rag_events = rag.retrieve(world.year, deviation=world.player_deviation)
    log.append(f"RAG 检索 (dev={world.player_deviation:.1f}): {len(rag_events)} events")
    log.append(rag.build_llm_context(rag_events[:4]))

    for turn_num in range(1, 20):
        proposals = hist_eng.check_events(world.year, world.season, world, deviation=world.player_deviation)
        for p in proposals:
            log.append(f"  [AltEvent] {world.year}年{world.season.cn} — {p.title}: {p.narrative_hint[:60]}")

        cmds = _get_jingzhou_focus_commands(world)
        result = tc.execute_turn(world, player_commands=cmds, year=world.year, turn_number=turn_num)

        if result.battles:
            log.append(f"  [Battle] {result.battles[0].result.value}")

        if world.year >= 218:
            break

    log.append(f"\n最终: {world.year}年{world.season.cn}")
    log.append(f"刘备领土: {factions['shu'].territories}")
    log.append(f"触发: {hist_eng.triggered_count}  未触发: {hist_eng.averted_count}  阻断: {hist_eng.blocked_count}")

    write_log("e2e-scenario-2-liubei-alt-jingzhou.log", log)


def _get_jingzhou_focus_commands(world: WorldState) -> list[Command]:
    cmds: list[Command] = []
    faction = world.factions.get("shu")
    if not faction:
        return cmds
    if faction.territories:
        cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="shu"))
    if faction.treasury > 2000 and faction.territories:
        cmds.append(Command(type="recruit", params={
            "territory": faction.territories[0], "unit_type": "infantry", "amount": 500
        }, faction_id="shu"))
    return cmds


# ═══════════════════════════════════════════════════════════════
# Scenario 3: 曹操视角 — 统一天下
# ═══════════════════════════════════════════════════════════════


def scenario_3_caocao_unification():
    print(header("Scenario 3: 曹操视角 — 统一天下"))
    log = []

    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    hist_eng = HistoryEngine(KNOWLEDGE_PATH)
    rag = HistoricalRAG(KNOWLEDGE_PATH)

    territories = {
        "xuchang": Territory(id="xuchang", name="许昌", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=100000, development=70,
            neighbors=["wancheng", "luoyang"]),
        "wancheng": Territory(id="wancheng", name="宛城", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=50000, development=45,
            neighbors=["xinye", "xiangyang", "xuchang"]),
        "luoyang": Territory(id="luoyang", name="洛阳", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=80000, development=60,
            neighbors=["xuchang", "ye"]),
        "ye": Territory(id="ye", name="邺城", owner_id="cao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="north",
            population=120000, development=75,
            neighbors=["luoyang", "changshan"]),
        "changshan": Territory(id="changshan", name="常山", owner_id="cao",
            fertility=6, terrain_type=TerrainType.MOUNTAIN, climate_zone="north",
            horse_resource=True, population=40000, development=40,
            neighbors=["ye"]),
        "xinye": Territory(id="xinye", name="新野", owner_id="shu",
            fertility=6, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=30000, development=25,
            neighbors=["xiangyang", "wancheng"]),
        "xiangyang": Territory(id="xiangyang", name="襄阳", owner_id="liubiao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=80000, development=55,
            neighbors=["xinye", "jiangling", "wancheng"]),
        "jiangling": Territory(id="jiangling", name="江陵", owner_id="liubiao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=60000, development=50,
            neighbors=["xiangyang"]),
    }

    characters = {
        "caocao": Character(id="caocao", name="曹操", alias="孟德",
            leadership=98, might=72, intelligence=93, politics=94, charisma=92,
            faction_id="cao", location="xuchang", loyalty=100,
            birth=155, death=220),
        "xunyu": Character(id="xunyu", name="荀彧", alias="文若",
            leadership=55, might=32, intelligence=96, politics=98, charisma=82,
            faction_id="cao", location="xuchang", loyalty=90, is_governor=True,
            birth=163, death=212),
        "zhangliao": Character(id="zhangliao", name="张辽", alias="文远",
            leadership=93, might=92, intelligence=82, politics=65, charisma=78,
            faction_id="cao", location="wancheng", loyalty=95, is_commanding=True,
            birth=169, death=222),
        "liubei": Character(id="liubei", name="刘备", alias="玄德",
            leadership=80, might=70, intelligence=72, politics=82, charisma=99,
            faction_id="shu", location="xinye", loyalty=100,
            birth=161, death=223),
        "guanyu": Character(id="guanyu", name="关羽", alias="云长",
            leadership=95, might=98, intelligence=75, politics=62, charisma=88,
            faction_id="shu", location="xinye", loyalty=100, is_commanding=True,
            birth=160, death=220),
        "liubiao": Character(id="liubiao", name="刘表", alias="景升",
            leadership=55, might=30, intelligence=68, politics=75, charisma=70,
            faction_id="liubiao", location="xiangyang", loyalty=100,
            birth=142, death=208),
    }

    factions = {
        "cao": FactionState(id="cao", name="曹操军", ruler_id="caocao",
            capital="xuchang",
            territories=["xuchang", "wancheng", "luoyang", "ye", "changshan"],
            strength_actual=150000, treasury=50000, food=30000,
            tax_rate=0.4, morale_actual=80, prestige=90,
            relations={"shu": -80, "liubiao": -20}),
        "shu": FactionState(id="shu", name="刘备军", ruler_id="liubei",
            capital="xinye", territories=["xinye"],
            strength_actual=5000, treasury=3000, food=2000,
            tax_rate=0.2, morale_actual=70, prestige=35,
            relations={"cao": -80}),
        "liubiao": FactionState(id="liubiao", name="刘表军", ruler_id="liubiao",
            capital="xiangyang", territories=["xiangyang", "jiangling"],
            strength_actual=30000, treasury=8000, food=6000,
            tax_rate=0.3, morale_actual=45, prestige=45,
            relations={"cao": -20}),
    }

    armies = {
        "army_cao_1": Army(id="army_cao_1", faction_id="cao", location="wancheng",
            commander_id="zhangliao",
            units={UnitType.INFANTRY: 10000, UnitType.CAVALRY: 3000},
            morale=85, training=1.0, supply=30),
        "army_cao_2": Army(id="army_cao_2", faction_id="cao", location="xuchang",
            commander_id="caocao",
            units={UnitType.INFANTRY: 5000, UnitType.CAVALRY: 1000},
            morale=90, training=1.0, supply=30),
        "army_shu_1": Army(id="army_shu_1", faction_id="shu", location="xinye",
            commander_id="guanyu",
            units={UnitType.INFANTRY: 1500},
            morale=85, training=1.0, supply=30),
    }

    map_eng.load_territories(territories)
    char_eng.load_characters(characters)

    world = WorldState(
        year=207, season=Season.WINTER, turn_number=1,
        scenario="207", player_faction_id="cao",
        territories=territories, characters=characters, factions=factions, armies=armies,
        player_deviation=0.1,
    )

    log.append("Histrategy E2E — Scenario 3: 曹操视角")
    log.append("目标: 南下荆州，统一天下")
    log.append(f"起始: 公元{world.year}年{world.season.cn}")
    log.append(f"曹操领地: {list(factions['cao'].territories)}")
    log.append(f"曹操兵力: {factions['cao'].strength_actual}")

    for turn_num in range(1, 15):
        proposals = hist_eng.check_events(world.year, world.season, world, deviation=world.player_deviation)
        for p in proposals:
            log.append(f"  [CaoEvent] {world.year}年{world.season.cn} — {p.title}")

        # Cao aggressive strategy
        cmds = _get_caocao_commands(world)
        result = tc.execute_turn(world, player_commands=cmds, year=world.year, turn_number=turn_num)

        if result.battles:
            for b in result.battles:
                log.append(f"  [CaoBattle] {b.result.value}: {b.attacker_id} vs {b.defender_id}")
                if b.territory_captured:
                    log.append(f"    -> 领地易手: {b.location}")

        if world.year >= 210:
            break

    log.append(f"\n最终: {world.year}年{world.season.cn}")
    log.append(f"曹操领地: {[territories[t].name for t in factions['cao'].territories]}")
    log.append(f"历史事件触发: {hist_eng.triggered_count}")

    write_log("e2e-scenario-3-caocao.log", log)


def _get_caocao_commands(world: WorldState) -> list[Command]:
    cmds: list[Command] = []
    faction = world.factions.get("cao")
    if not faction:
        return cmds

    # Aggressive: attack neighboring enemies
    cao_territories = list(world.territories.keys())
    for tid in faction.territories:
        t = world.territories.get(tid)
        if not t:
            continue
        for nid in t.neighbors:
            nt = world.territories.get(nid)
            if nt and nt.owner_id not in ("", "cao", faction.id):
                # Attack non-owned territory
                cmds.append(Command(type="attack", params={
                    "target_territory": nid
                }, faction_id="cao"))
                return cmds

    if faction.territories:
        cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="cao"))
    return cmds


# ═══════════════════════════════════════════════════════════════
# Scenario 4: 孙权视角 — 赤壁 + 荆州博弈
# ═══════════════════════════════════════════════════════════════


def scenario_4_sunquan_redcliffs():
    print(header("Scenario 4: 孙权视角 — 赤壁 + 荆州博弈"))
    log = []

    map_eng = MapEngine()
    char_eng = CharacterEngine()
    dom_eng = DomesticEngine()
    mil_eng = MilitaryEngine()
    dec_eng = DecisionEngine()
    tc = TurnController(map_eng, char_eng, dom_eng, mil_eng, dec_eng)
    hist_eng = HistoryEngine(KNOWLEDGE_PATH)
    rag = HistoricalRAG(KNOWLEDGE_PATH)

    territories = {
        "jianye": Territory(id="jianye", name="建业", owner_id="wu",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="south",
            has_river=True, has_coast=True, population=70000, development=55,
            neighbors=["wu", "chaisang"]),
        "wu": Territory(id="wu", name="吴郡", owner_id="wu",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="south",
            has_coast=True, population=50000, development=45,
            neighbors=["jianye", "kuaiji"]),
        "kuaiji": Territory(id="kuaiji", name="会稽", owner_id="wu",
            fertility=6, terrain_type=TerrainType.COAST, climate_zone="south",
            has_coast=True, population=40000, development=35,
            neighbors=["wu"]),
        "chaisang": Territory(id="chaisang", name="柴桑", owner_id="wu",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="south",
            has_river=True, population=40000, development=40,
            neighbors=["jianye", "jiangkou"]),
        "jiangkou": Territory(id="jiangkou", name="江口", owner_id="",
            fertility=5, terrain_type=TerrainType.RIVER, climate_zone="central",
            has_river=True, population=15000, development=20,
            neighbors=["chaisang", "xiangyang", "jiangling"]),
        "xiangyang": Territory(id="xiangyang", name="襄阳", owner_id="cao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=80000, development=55,
            neighbors=["xinye", "jiangling", "jiangkou", "wancheng"]),
        "jiangling": Territory(id="jiangling", name="江陵", owner_id="cao",
            fertility=8, terrain_type=TerrainType.PLAINS, climate_zone="central",
            has_river=True, population=60000, development=50,
            neighbors=["xiangyang", "jiangkou"]),
        "wancheng": Territory(id="wancheng", name="宛城", owner_id="cao",
            fertility=7, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=50000, development=45,
            neighbors=["xinye", "xiangyang"]),
        "xinye": Territory(id="xinye", name="新野", owner_id="shu",
            fertility=6, terrain_type=TerrainType.PLAINS, climate_zone="central",
            population=30000, development=25,
            neighbors=["xiangyang", "wancheng"]),
    }

    characters = {
        "sunquan": Character(id="sunquan", name="孙权", alias="仲谋",
            leadership=75, might=60, intelligence=82, politics=88, charisma=85,
            faction_id="wu", location="jianye", loyalty=100,
            birth=182, death=252),
        "zhouyu": Character(id="zhouyu", name="周瑜", alias="公瑾",
            leadership=95, might=65, intelligence=94, politics=80, charisma=85,
            faction_id="wu", location="chaisang", loyalty=90, is_commanding=True,
            birth=175, death=210),
        "lusu": Character(id="lusu", name="鲁肃", alias="子敬",
            leadership=65, might=42, intelligence=90, politics=92, charisma=80,
            faction_id="wu", location="jianye", loyalty=85,
            birth=172, death=217),
        "lvmeng": Character(id="lvmeng", name="吕蒙", alias="子明",
            leadership=90, might=78, intelligence=85, politics=70, charisma=65,
            faction_id="wu", location="chaisang", loyalty=82,
            birth=178, death=220),
        "caocao": Character(id="caocao", name="曹操", alias="孟德",
            leadership=98, might=72, intelligence=93, politics=94, charisma=92,
            faction_id="cao", location="xuchang", loyalty=100,
            birth=155, death=220),
        "liubei": Character(id="liubei", name="刘备", alias="玄德",
            leadership=80, might=70, intelligence=72, politics=82, charisma=99,
            faction_id="shu", location="xinye", loyalty=100,
            birth=161, death=223),
        "zhugeliang": Character(id="zhugeliang", name="诸葛亮", alias="孔明",
            leadership=92, might=32, intelligence=100, politics=98, charisma=90,
            faction_id="shu", location="xinye", loyalty=95,
            birth=181, death=234),
        "guanyu": Character(id="guanyu", name="关羽", alias="云长",
            leadership=95, might=98, intelligence=75, politics=62, charisma=88,
            faction_id="shu", location="xinye", loyalty=100, is_commanding=True,
            birth=160, death=220),
    }

    factions = {
        "wu": FactionState(id="wu", name="孙权军", ruler_id="sunquan",
            capital="jianye",
            territories=["jianye", "wu", "kuaiji", "chaisang"],
            strength_actual=60000, treasury=15000, food=10000,
            tax_rate=0.3, morale_actual=75, prestige=60,
            relations={"cao": -30, "shu": 20}),
        "cao": FactionState(id="cao", name="曹操军", ruler_id="caocao",
            capital="xuchang",
            territories=["wancheng", "xiangyang", "jiangling"],
            strength_actual=120000, treasury=40000, food=25000,
            tax_rate=0.4, morale_actual=75, prestige=90,
            relations={"wu": -30, "shu": -80}),
        "shu": FactionState(id="shu", name="刘备军", ruler_id="liubei",
            capital="xinye", territories=["xinye"],
            strength_actual=5000, treasury=3000, food=2000,
            tax_rate=0.2, morale_actual=70, prestige=35,
            relations={"cao": -80, "wu": 20}),
    }

    armies = {
        "army_wu_1": Army(id="army_wu_1", faction_id="wu", location="chaisang",
            commander_id="zhouyu",
            units={UnitType.INFANTRY: 3000, UnitType.NAVY: 2000},
            morale=85, training=1.0, supply=30),
        "army_wu_2": Army(id="army_wu_2", faction_id="wu", location="jianye",
            commander_id="lusu",
            units={UnitType.INFANTRY: 2000, UnitType.ARCHER: 1000},
            morale=80, training=1.0, supply=30),
        "army_cao_1": Army(id="army_cao_1", faction_id="cao", location="wancheng",
            commander_id="caocao",
            units={UnitType.INFANTRY: 10000, UnitType.CAVALRY: 2000, UnitType.NAVY: 5000},
            morale=75, training=1.0, supply=30),
        "army_shu_1": Army(id="army_shu_1", faction_id="shu", location="xinye",
            commander_id="guanyu",
            units={UnitType.INFANTRY: 1500},
            morale=85, training=1.0, supply=30),
    }

    map_eng.load_territories(territories)
    char_eng.load_characters(characters)

    world = WorldState(
        year=208, season=Season.SUMMER, turn_number=1,
        scenario="wu_redcliffs", player_faction_id="wu",
        territories=territories, characters=characters, factions=factions, armies=armies,
        player_deviation=0.1,
    )

    log.append("Histrategy E2E — Scenario 4: 孙权视角")
    log.append("背景: 赤壁前夕，曹操南下占据荆州，威胁江东")
    log.append(f"起始: 公元{world.year}年{world.season.cn}")
    log.append(f"孙权领地: {list(factions['wu'].territories)}")

    # RAG context for Sun Quan
    rag_events = rag.retrieve(world.year, deviation=world.player_deviation)
    log.append(f"\nRAG 历史参考 ({len(rag_events)} events):")
    log.append(rag.build_llm_context(rag_events[:4]))

    for turn_num in range(1, 20):
        proposals = hist_eng.check_events(world.year, world.season, world, deviation=world.player_deviation)
        for p in proposals:
            log.append(f"  [WuEvent] {world.year}年{world.season.cn} — {p.title}")
            # Check alternatives
            alternatives = hist_eng.get_alternative_chain(p.event_id)
            if alternatives:
                log.append(f"    Alternatives: {[a['description'][:40] for a in alternatives[:2]]}")

        cmds = _get_sunquan_commands(world)
        result = tc.execute_turn(world, player_commands=cmds, year=world.year, turn_number=turn_num)

        if result.battles:
            for b in result.battles:
                log.append(f"  [WuBattle] {b.result.value}: {b.attacker_id} vs {b.defender_id}")
                if b.territory_captured:
                    log.append(f"    -> {b.location} 被攻克!")

        for ce in result.character_events:
            if "death" in str(ce.get("type", "")):
                log.append(f"  [WuDeath] {ce.get('character_name', '?')} 去世")

        if world.year >= 212:
            break

    ctx = hist_eng.get_historical_context(210, deviation=world.player_deviation)
    log.append(f"\n最终历史上下文:\n{ctx}")

    log.append(f"\n最终: {world.year}年{world.season.cn}")
    log.append(f"孙权领地: {[territories[t].name for t in factions['wu'].territories]}")

    write_log("e2e-scenario-4-sunquan.log", log)


def _get_sunquan_commands(world: WorldState) -> list[Command]:
    cmds: list[Command] = []
    faction = world.factions.get("wu")
    if not faction:
        return cmds

    # Defensive/expansionist: attack adjacent non-allied territories
    for tid in faction.territories:
        t = world.territories.get(tid)
        if not t:
            continue
        for nid in t.neighbors:
            nt = world.territories.get(nid)
            if nt and nt.owner_id == "cao":
                cmds.append(Command(type="attack", params={
                    "target_territory": nid
                }, faction_id="wu"))
                return cmds

    if faction.territories:
        cmds.append(Command(type="develop", params={"territory": faction.territories[0]}, faction_id="wu"))
    if faction.treasury > 2000:
        cmds.append(Command(type="recruit", params={
            "territory": faction.territories[0], "unit_type": "infantry", "amount": 500
        }, faction_id="wu"))
    return cmds


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("三國志略 v2 · E2E Scenarios (P3)")
    print("History Engine + RAG + Knowledge Base")
    print("=" * 60)

    try:
        scenario_1_liubei_historical()
    except Exception as e:
        print(f"Scenario 1 ERROR: {e}")
        import traceback; traceback.print_exc()

    try:
        scenario_2_liubei_alt_jingzhou()
    except Exception as e:
        print(f"Scenario 2 ERROR: {e}")
        import traceback; traceback.print_exc()

    try:
        scenario_3_caocao_unification()
    except Exception as e:
        print(f"Scenario 3 ERROR: {e}")
        import traceback; traceback.print_exc()

    try:
        scenario_4_sunquan_redcliffs()
    except Exception as e:
        print(f"Scenario 4 ERROR: {e}")
        import traceback; traceback.print_exc()

    print("\n" + "=" * 60)
    print("All E2E scenarios complete. Logs in histrategy-engine/logs/")
    print("=" * 60)
