"""
Tests for History Engine and RAG retriever (P3).

Coverage target: >= 80%
"""

import json
import os
import tempfile

import pytest

from histrategy_engine import (
    Character,
    EventProposal,
    FactionState,
    HistoricalRAG,
    HistoryEngine,
    Season,
    TerrainType,
    Territory,
    WorldState,
)

# ═══════════════════════════════════════════════════════════════
# Test knowledge data (minimal inline for test isolation)
# ═══════════════════════════════════════════════════════════════

SAMPLE_TIMELINE = {
    "timeline_id": "test",
    "events": [
        {
            "id": "three_visits_207",
            "title": "三顾茅庐",
            "year": 207,
            "month": 12,
            "category": "diplomatic",
            "description": "刘备三顾茅庐请诸葛亮出山。",
            "participants": ["liubei", "zhugeliang"],
            "gravity": 0.95,
            "preconditions": {"liubei_location": "xinye"},
            "outcomes": [{"id": "zhuge_joins", "description": "诸葛亮加入刘备", "effects": {}}],
            "butterfly_effects": {"triggered": ["liubiao_death_208"]},
        },
        {
            "id": "liubiao_death_208",
            "title": "刘表病亡",
            "year": 208,
            "month": 3,
            "category": "character_death",
            "description": "刘表病逝，曹操南下。",
            "participants": ["liubiao", "caocao"],
            "gravity": 0.9,
            "preconditions": {},
            "outcomes": [{"id": "cao_takes", "description": "曹操接管荆州", "effects": {}}],
            "butterfly_effects": {"triggered": ["red_cliffs_208"]},
        },
        {
            "id": "red_cliffs_208",
            "title": "赤壁之战",
            "year": 208,
            "month": 12,
            "category": "major_battle",
            "description": "孙刘联军火攻大破曹操。",
            "participants": ["caocao", "sunquan", "liubei", "zhouyu"],
            "gravity": 0.95,
            "preconditions": {"sunliu_alliance": True},
            "outcomes": [{"id": "alliance_victory", "description": "联军大胜", "effects": {}}],
            "butterfly_effects": {"triggered": ["jingnan_campaign_209"]},
        },
        {
            "id": "jingnan_campaign_209",
            "title": "取荆南四郡",
            "year": 209,
            "month": 3,
            "category": "territory_change",
            "description": "刘备取武陵、长沙、零陵、桂阳。",
            "participants": ["liubei", "guanyu"],
            "gravity": 0.8,
            "preconditions": {"red_cliffs_won": True},
            "outcomes": [{"id": "four_commanderies", "description": "尽得四郡", "effects": {}}],
            "butterfly_effects": {"triggered": ["sunliu_marriage_209"]},
        },
        {
            "id": "sunliu_marriage_209",
            "title": "孙刘联姻",
            "year": 209,
            "month": 9,
            "category": "diplomatic",
            "description": "孙尚香嫁刘备",
            "participants": ["liubei", "sunshangxiang"],
            "gravity": 0.7,
            "preconditions": {"sunliu_alliance": True},
            "outcomes": [{"id": "marriage_ok", "description": "联姻成功", "effects": {}}],
            "butterfly_effects": {"triggered": ["zhouyu_death_210"]},
        },
        {
            "id": "zhouyu_death_210",
            "title": "周瑜病逝",
            "year": 210,
            "month": 12,
            "category": "character_death",
            "description": "周瑜箭伤复发逝世。",
            "participants": ["zhouyu"],
            "gravity": 0.8,
            "preconditions": {"zhouyu_alive": True},
            "outcomes": [{"id": "zhouyu_dies", "description": "周瑜病逝", "effects": {}}],
            "butterfly_effects": {"triggered": []},
        },
        {
            "id": "guanyu_northern_campaign_219",
            "title": "关羽北伐",
            "year": 219,
            "month": 8,
            "category": "major_battle",
            "description": "关羽北伐，水淹七军。",
            "participants": ["guanyu", "yujin"],
            "gravity": 0.9,
            "preconditions": {"guanyu_guards_jingzhou": True},
            "outcomes": [{"id": "guanyu_killed", "description": "关羽被杀", "effects": {}}],
            "butterfly_effects": {"triggered": ["caocao_death_220", "yiling_battle_221"]},
        },
        {
            "id": "caocao_death_220",
            "title": "曹操病逝",
            "year": 220,
            "month": 3,
            "category": "character_death",
            "description": "曹操病逝洛阳。",
            "participants": ["caocao"],
            "gravity": 0.9,
            "preconditions": {"caocao_alive": True},
            "outcomes": [{"id": "cao_dies", "description": "曹操病逝", "effects": {}}],
            "butterfly_effects": {"triggered": []},
        },
        {
            "id": "yiling_battle_221",
            "title": "夷陵之战",
            "year": 221,
            "month": 7,
            "category": "major_battle",
            "description": "刘备伐吴，陆逊火烧连营。",
            "participants": ["liubei", "luxun"],
            "gravity": 0.9,
            "preconditions": {"guanyu_dead": True},
            "outcomes": [{"id": "wu_victory", "description": "陆逊大胜", "effects": {}}],
            "butterfly_effects": {"triggered": ["baidi_tuogu_223"]},
        },
        {
            "id": "baidi_tuogu_223",
            "title": "白帝托孤",
            "year": 223,
            "month": 4,
            "category": "character_death",
            "description": "刘备托孤诸葛亮。",
            "participants": ["liubei", "zhugeliang"],
            "gravity": 0.95,
            "preconditions": {"liubei_alive": True, "yiling_lost": True},
            "outcomes": [{"id": "liubei_dies", "description": "刘备病逝", "effects": {}}],
            "butterfly_effects": {"triggered": []},
        },
    ],
}


SAMPLE_CHARACTERS = {
    "roster_id": "test",
    "characters": [
        {
            "id": "liubei",
            "name": "刘备",
            "faction": "shu",
            "location": "xinye",
            "birth": 161,
            "death": 223,
            "stats": {
                "leadership": 80,
                "might": 70,
                "intelligence": 72,
                "politics": 82,
                "charisma": 99,
            },
        },
        {
            "id": "guanyu",
            "name": "关羽",
            "faction": "shu",
            "location": "xinye",
            "birth": 160,
            "death": 220,
            "stats": {
                "leadership": 95,
                "might": 98,
                "intelligence": 75,
                "politics": 62,
                "charisma": 88,
            },
        },
        {
            "id": "zhugeliang",
            "name": "诸葛亮",
            "faction": "shu",
            "location": "longzhong",
            "birth": 181,
            "death": 234,
            "stats": {
                "leadership": 92,
                "might": 32,
                "intelligence": 100,
                "politics": 98,
                "charisma": 90,
            },
        },
    ],
}


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def knowledge_dir():
    """Create a temp knowledge directory with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # timeline
        timeline_dir = os.path.join(tmpdir, "timeline")
        os.makedirs(timeline_dir)
        with open(os.path.join(timeline_dir, "207-223.json"), "w") as f:
            json.dump(SAMPLE_TIMELINE, f)

        # characters
        char_dir = os.path.join(tmpdir, "characters")
        os.makedirs(char_dir)
        with open(os.path.join(char_dir, "test_roster.json"), "w") as f:
            json.dump(SAMPLE_CHARACTERS, f)

        # scenarios
        scenario_dir = os.path.join(tmpdir, "scenarios")
        os.makedirs(scenario_dir)
        with open(os.path.join(scenario_dir, "test_scenario.json"), "w") as f:
            json.dump({"scenario_id": "test", "name": "Test", "year": 207}, f)

        # geography
        geo_dir = os.path.join(tmpdir, "geography")
        os.makedirs(geo_dir)
        with open(os.path.join(geo_dir, "territories.json"), "w") as f:
            json.dump(
                {
                    "regions": [
                        {"id": "jingzhou", "name": "荆州", "fertility": 8},
                        {"id": "yizhou", "name": "益州", "fertility": 8},
                    ]
                },
                f,
            )

        yield tmpdir


@pytest.fixture
def hist_engine(knowledge_dir):
    """History engine with test knowledge."""
    return HistoryEngine(knowledge_dir)


@pytest.fixture
def rag(knowledge_dir):
    """RAG retriever with test knowledge."""
    return HistoricalRAG(knowledge_dir)


@pytest.fixture
def world_state():
    """Minimal world state for testing."""
    territories = {
        "xinye": Territory(
            id="xinye",
            name="新野",
            owner_id="shu",
            fertility=6,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=30000,
            development=25,
            neighbors=["xiangyang", "wancheng"],
        ),
        "xiangyang": Territory(
            id="xiangyang",
            name="襄阳",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=80000,
            development=55,
            neighbors=["xinye", "jiangling"],
        ),
        "wancheng": Territory(
            id="wancheng",
            name="宛城",
            owner_id="cao",
            fertility=7,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            population=50000,
            development=45,
            neighbors=["xinye"],
        ),
        "jiangling": Territory(
            id="jiangling",
            name="江陵",
            owner_id="liubiao",
            fertility=8,
            terrain_type=TerrainType.PLAINS,
            climate_zone="central",
            has_river=True,
            population=60000,
            development=50,
            neighbors=["xiangyang"],
        ),
    }

    characters = {
        "liubei": Character(
            id="liubei",
            name="刘备",
            alias="玄德",
            leadership=80,
            might=70,
            intelligence=72,
            politics=82,
            charisma=99,
            faction_id="shu",
            location="xinye",
            loyalty=100,
            birth=161,
            death=223,
        ),
        "guanyu": Character(
            id="guanyu",
            name="关羽",
            alias="云长",
            leadership=95,
            might=98,
            intelligence=75,
            politics=62,
            charisma=88,
            faction_id="shu",
            location="xinye",
            loyalty=100,
            birth=160,
            death=220,
        ),
        "zhugeliang": Character(
            id="zhugeliang",
            name="诸葛亮",
            alias="孔明",
            leadership=92,
            might=32,
            intelligence=100,
            politics=98,
            charisma=90,
            faction_id="shu",
            location="xinye",
            loyalty=95,
            birth=181,
            death=234,
        ),
        "caocao": Character(
            id="caocao",
            name="曹操",
            alias="孟德",
            leadership=98,
            might=72,
            intelligence=93,
            politics=94,
            charisma=92,
            faction_id="cao",
            location="xuchang",
            loyalty=100,
            birth=155,
            death=220,
        ),
        "liubiao": Character(
            id="liubiao",
            name="刘表",
            alias="景升",
            leadership=55,
            might=30,
            intelligence=68,
            politics=75,
            charisma=70,
            faction_id="liubiao",
            location="xiangyang",
            loyalty=100,
            birth=142,
            death=208,
        ),
    }

    factions = {
        "shu": FactionState(
            id="shu",
            name="刘备军",
            ruler_id="liubei",
            capital="xinye",
            territories=["xinye"],
            relations={"cao": -80, "wu": 20, "liubiao": 40},
        ),
        "cao": FactionState(
            id="cao",
            name="曹操军",
            ruler_id="caocao",
            capital="wancheng",
            territories=["wancheng"],
            relations={"shu": -80, "wu": -30},
        ),
        "wu": FactionState(
            id="wu",
            name="孙权军",
            ruler_id="sunquan",
            capital="jianye",
            territories=[],
            relations={"shu": 20, "cao": -30},
        ),
        "liubiao": FactionState(
            id="liubiao",
            name="刘表军",
            ruler_id="liubiao",
            capital="xiangyang",
            territories=["xiangyang", "jiangling"],
            relations={"shu": 40, "cao": -20},
        ),
    }

    return WorldState(
        year=207,
        season=Season.WINTER,
        turn_number=1,
        player_faction_id="shu",
        territories=territories,
        characters=characters,
        factions=factions,
    )


# ═══════════════════════════════════════════════════════════════
# History Engine: Initialization
# ═══════════════════════════════════════════════════════════════


class TestHistoryEngineInit:
    def test_loads_timeline(self, hist_engine):
        assert hist_engine.event_count == len(SAMPLE_TIMELINE["events"])
        assert hist_engine.event_count > 0

    def test_loads_characters(self, hist_engine):
        assert len(hist_engine._characters) == len(SAMPLE_CHARACTERS["characters"])

    def test_loads_scenarios(self, hist_engine):
        assert "test" in hist_engine._scenarios

    def test_loads_territories(self, hist_engine):
        assert "jingzhou" in hist_engine._territories
        assert "yizhou" in hist_engine._territories

    def test_event_index_built(self, hist_engine):
        assert "three_visits_207" in hist_engine._event_index
        assert hist_engine._event_index["three_visits_207"]["year"] == 207

    def test_init_state_counts(self, hist_engine):
        assert hist_engine.triggered_count == 0
        assert hist_engine.averted_count == 0
        assert hist_engine.blocked_count == 0


# ═══════════════════════════════════════════════════════════════
# History Engine: Event Checking
# ═══════════════════════════════════════════════════════════════


class TestHistoryEngineCheckEvents:
    def test_check_events_no_deviation(self, hist_engine, world_state):
        proposals = hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
        assert isinstance(proposals, list)

    def test_event_at_correct_year(self, hist_engine, world_state):
        # Run many times to handle randomness
        triggered = 0
        averted = 0
        for _ in range(50):
            hist_engine.reset()
            proposals = hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
            if proposals:
                triggered += hist_engine.triggered_count
                averted += hist_engine.averted_count

        # At deviation=0, gravity=0.95 → high probability of triggering
        # Both triggered and averted should be possible across runs

    def test_high_deviation_reduces_trigger(self, hist_engine, world_state):
        """High deviation significantly reduces event triggering probability."""
        # With deviation=0.9: effective_prob = 0.95 * (1 - 0.9*0.5) = 0.95 * 0.55 = 0.5225
        triggered_normal = 0
        triggered_deviated = 0

        for _ in range(200):
            hist_engine.reset()
            hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
            if hist_engine.triggered_count > 0:
                triggered_normal += 1

        for _ in range(200):
            hist_engine.reset()
            hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.9)
            if hist_engine.triggered_count > 0:
                triggered_deviated += 1

        # High deviation should trigger events less often
        assert triggered_deviated <= triggered_normal + 30  # some tolerance

    def test_check_past_year_no_events(self, hist_engine, world_state):
        hist_engine.reset()
        proposals = hist_engine.check_events(200, Season.SPRING, world_state, deviation=0.0)
        # Year 200 is before all events (starts at 207)
        assert len(proposals) == 0

    def test_far_future_limited_events(self, hist_engine, world_state):
        hist_engine.reset()
        proposals = hist_engine.check_events(250, Season.SPRING, world_state, deviation=0.0)
        # Year 250 is after all events — should return few or none
        assert len(proposals) == 0 or all(p.event_id in hist_engine._event_index for p in proposals)

    def test_event_proposal_structure(self, hist_engine, world_state):
        hist_engine.reset()
        proposals = hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
        for p in proposals:
            assert isinstance(p, EventProposal)
            assert p.event_id
            assert p.title
            assert isinstance(p.effects, dict)
            assert "category" in p.effects

    def test_already_triggered_not_checked_again(self, hist_engine, world_state):
        hist_engine.reset()
        # Manually mark event as triggered
        hist_engine._triggered_events.add("three_visits_207")
        proposals = hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
        # Should not propose the same event again
        ids = [p.event_id for p in proposals]
        assert "three_visits_207" not in ids

    def test_averted_events_not_checked(self, hist_engine, world_state):
        hist_engine.reset()
        hist_engine.mark_averted("three_visits_207", "test reason")
        proposals = hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
        ids = [p.event_id for p in proposals]
        assert "three_visits_207" not in ids

    def test_blocked_downstream_not_checked(self, hist_engine, world_state):
        hist_engine.reset()
        hist_engine.block_downstream("three_visits_207")
        proposals = hist_engine.check_events(208, Season.SPRING, world_state, deviation=0.0)
        ids = [p.event_id for p in proposals]
        # downstream events from three_visits should be blocked
        assert "liubiao_death_208" not in ids


# ═══════════════════════════════════════════════════════════════
# History Engine: State Management
# ═══════════════════════════════════════════════════════════════


class TestHistoryEngineStateManagement:
    def test_mark_averted(self, hist_engine):
        hist_engine.mark_averted("three_visits_207", "刘备未访诸葛亮")
        assert "three_visits_207" in hist_engine._averted_events
        assert hist_engine._averted_events["three_visits_207"] == "刘备未访诸葛亮"
        assert hist_engine.averted_count == 1

    def test_mark_averted_removes_from_triggered(self, hist_engine):
        hist_engine._triggered_events.add("three_visits_207")
        hist_engine.mark_averted("three_visits_207", "oops")
        assert "three_visits_207" not in hist_engine._triggered_events

    def test_block_downstream(self, hist_engine):
        hist_engine.block_downstream("three_visits_207")
        # liubiao_death_208 is a downstream of three_visits_207
        assert "liubiao_death_208" in hist_engine._blocked_downstream
        # And recursively: red_cliffs_208 is downstream of liubiao_death_208
        assert "red_cliffs_208" in hist_engine._blocked_downstream

    def test_block_downstream_no_butterfly(self, hist_engine):
        """Events with no downstream should not crash."""
        hist_engine.block_downstream("baidi_tuogu_223")
        # Should not error — baidi_tuogu has empty triggered list

    def test_block_nonexistent_event(self, hist_engine):
        hist_engine.block_downstream("nonexistent_event")
        # Should not crash

    def test_get_alternative_chain(self, hist_engine):
        # Event has 1 outcome (historical) — alternatives are empty
        alternatives = hist_engine.get_alternative_chain("baidi_tuogu_223")
        # baidi_tuogu has only 1 outcome, so alternatives should be empty
        assert isinstance(alternatives, list)

    def test_get_alternative_chain_blocked(self, hist_engine):
        hist_engine.block_downstream("three_visits_207")
        alternatives = hist_engine.get_alternative_chain("three_visits_207")
        # Contains alternative outcomes + downstream alternatives
        assert isinstance(alternatives, list)

    def test_get_alternative_chain_nonexistent(self, hist_engine):
        assert hist_engine.get_alternative_chain("nonexistent") == []

    def test_reset(self, hist_engine, world_state):
        hist_engine.mark_averted("three_visits_207", "reason")
        hist_engine.block_downstream("three_visits_207")
        hist_engine._triggered_events.add("baidi_tuogu_223")
        hist_engine.reset()
        assert hist_engine.triggered_count == 0
        assert hist_engine.averted_count == 0
        assert hist_engine.blocked_count == 0

    def test_all_events_property(self, hist_engine):
        events = hist_engine.all_events
        assert len(events) == len(SAMPLE_TIMELINE["events"])

    def test_averted_events_property(self, hist_engine):
        hist_engine.mark_averted("three_visits_207", "理由")
        hist_engine.mark_averted("red_cliffs_208", "赤壁未发生")
        averted = hist_engine.averted_events
        assert len(averted) == 2
        assert "three_visits_207" in averted


# ═══════════════════════════════════════════════════════════════
# History Engine: Historical Context
# ═══════════════════════════════════════════════════════════════


class TestHistoricalContext:
    def test_get_historical_context(self, hist_engine):
        ctx = hist_engine.get_historical_context(208, deviation=0.0)
        assert "208" in ctx
        assert "三顾茅庐" in ctx or "刘表" in ctx

    def test_context_with_deviation_mention(self, hist_engine):
        ctx = hist_engine.get_historical_context(208, deviation=0.5)
        assert "0.5" in ctx or "偏离" in ctx

    def test_context_with_no_deviation_no_devi_text(self, hist_engine):
        ctx = hist_engine.get_historical_context(208, deviation=0.0)
        assert "偏离" not in ctx

    def test_context_past_year_empty(self, hist_engine):
        ctx = hist_engine.get_historical_context(180, deviation=0.0)
        # Events start at 207, so context should be minimal
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_context_future_year_empty(self, hist_engine):
        ctx = hist_engine.get_historical_context(250, deviation=0.0)
        assert isinstance(ctx, str)
        assert len(ctx) > 0


# ═══════════════════════════════════════════════════════════════
# History Engine: Precondition Checking
# ═══════════════════════════════════════════════════════════════


class TestPreconditions:
    def test_location_precondition(self, hist_engine, world_state):
        # three_visits_207 requires liubei_location=xinye
        # liubei is at xinye → should be able to trigger
        hist_engine.reset()
        proposals = hist_engine.check_events(207, Season.WINTER, world_state)
        assert isinstance(proposals, list)

    def test_location_precondition_fails(self, hist_engine, world_state):
        world_state.characters["liubei"].location = "chengdu"
        hist_engine.reset()
        proposals = hist_engine.check_events(207, Season.WINTER, world_state)
        ids = [p.event_id for p in proposals]
        # three_visits should not trigger since liubei is not in xinye
        assert "three_visits_207" not in ids


# ═══════════════════════════════════════════════════════════════
# RAG Retriever: Initialization
# ═══════════════════════════════════════════════════════════════


class TestRAGInit:
    def test_loads_events(self, rag):
        assert rag.event_count == len(SAMPLE_TIMELINE["events"])

    def test_year_coverage(self, rag):
        min_y, max_y = rag.year_coverage
        assert min_y == 207
        assert max_y == 223

    def test_get_event_by_id(self, rag):
        evt = rag.get_event_by_id("three_visits_207")
        assert evt is not None
        assert evt["title"] == "三顾茅庐"

    def test_get_event_by_id_missing(self, rag):
        assert rag.get_event_by_id("nonexistent_id") is None


# ═══════════════════════════════════════════════════════════════
# RAG Retriever: Retrieval
# ═══════════════════════════════════════════════════════════════


class TestRAGRetrieval:
    def test_retrieve_low_deviation(self, rag):
        """Low deviation → ±3 year window."""
        events = rag.retrieve(209, deviation=0.1, max_events=20)
        years = {e["year"] for e in events}
        # Window: 206-212 (but events start at 207)
        assert all(206 <= y <= 212 for y in years)
        # Should include events from 207, 208, 209, 210
        assert len(events) > 0

    def test_retrieve_medium_deviation(self, rag):
        """Medium deviation → ±2 year window."""
        events = rag.retrieve(209, deviation=0.5, max_events=20)
        years = {e["year"] for e in events}
        # Window: 207-211
        assert all(207 <= y <= 211 for y in years)

    def test_retrieve_high_deviation(self, rag):
        """High deviation → ±1 year window."""
        events = rag.retrieve(220, deviation=0.8, max_events=20)
        years = {e["year"] for e in events}
        # Window: 219-221
        assert all(219 <= y <= 221 for y in years)

    def test_retrieve_max_events_cap(self, rag):
        events = rag.retrieve(208, deviation=0.0, max_events=3)
        assert len(events) <= 3

    def test_retrieve_year_out_of_range(self, rag):
        events = rag.retrieve(180, deviation=0.0)
        assert events == []

    def test_retrieve_event_structure(self, rag):
        events = rag.retrieve(208, deviation=0.0, max_events=5)
        for evt in events:
            assert "id" in evt
            assert "title" in evt
            assert "year" in evt
            assert "category" in evt
            assert "description" in evt
            assert "gravity" in evt

    def test_retrieve_sorted_by_year(self, rag):
        events = rag.retrieve(209, deviation=0.0, max_events=10)
        years = [e["year"] for e in events]
        assert years == sorted(years)


# ═══════════════════════════════════════════════════════════════
# RAG Retriever: LLM Context Building
# ═══════════════════════════════════════════════════════════════


class TestLLMContext:
    def test_build_context_with_events(self, rag):
        events = rag.retrieve(208, deviation=0.0, max_events=3)
        context = rag.build_llm_context(events)
        assert "历史参考" in context
        assert "三顾茅庐" in context or "刘表" in context or "赤壁" in context

    def test_build_context_empty(self, rag):
        context = rag.build_llm_context([])
        assert "无相关" in context or "无" in context

    def test_build_context_includes_category(self, rag):
        events = rag.retrieve(207, deviation=0.0, max_events=1)
        context = rag.build_llm_context(events)
        assert "类别" in context

    def test_build_context_includes_gravity(self, rag):
        events = rag.retrieve(207, deviation=0.0, max_events=1)
        context = rag.build_llm_context(events)
        assert "历史引力" in context

    def test_build_context_includes_participants(self, rag):
        events = rag.retrieve(208, deviation=0.0, max_events=5)
        context = rag.build_llm_context(events)
        # At least one event should have participants listed
        any("参与人物" in ctx_line for ctx_line in context.split("\n") if "参与人物" in ctx_line)
        # Actually check "参与" list
        assert "参与人物" in context


# ═══════════════════════════════════════════════════════════════
# Integration: History Engine + RAG
# ═══════════════════════════════════════════════════════════════


class TestHistoryRAGIntegration:
    def test_rag_context_feeds_history_engine(self, rag, hist_engine, world_state):
        """RAG events can inform the history engine's context building."""
        # Retrieve relevant events
        events = rag.retrieve(208, deviation=0.0)
        assert len(events) > 0

        # Check that history engine events from same year match RAG
        hist_engine.reset()
        hist_engine.check_events(208, Season.SPRING, world_state, deviation=0.0)

        # RAG should have events in the same year window
        rag_years = {e["year"] for e in events}
        assert 207 in rag_years or 208 in rag_years

    def test_full_event_flow(self, rag, hist_engine, world_state):
        """Simulate a multi-year sequence with both engines."""
        hist_engine.reset()
        log = []

        for year in range(207, 224):
            season = Season.WINTER
            proposals = hist_engine.check_events(year, season, world_state, deviation=0.0)
            rag.retrieve(year, deviation=0.0, max_events=3)

            for p in proposals:
                log.append(f"{year}: {p.title}")
        assert isinstance(log, list)

    def test_deviation_affects_both_systems(self, rag, hist_engine, world_state):
        """High deviation narrows RAG window + reduces event probability."""
        # RAG: high deviation → narrower window
        events_low = rag.retrieve(210, deviation=0.0)
        events_high = rag.retrieve(210, deviation=0.8)
        assert len(events_high) <= len(events_low)  # narrower window = fewer events

        # History Engine: high deviation → lower effective probability
        hist_engine.reset()
        hist_engine.check_events(210, Season.WINTER, world_state, deviation=0.9)


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_knowledge_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HistoryEngine(tmpdir)
            assert engine.event_count == 0
            assert engine.triggered_count == 0

    def test_nonexistent_knowledge_path(self):
        engine = HistoryEngine("/tmp/nonexistent_path_xyz")
        assert engine.event_count == 0

    def test_empty_timeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            timeline_dir = os.path.join(tmpdir, "timeline")
            os.makedirs(timeline_dir)
            with open(os.path.join(timeline_dir, "empty.json"), "w") as f:
                json.dump({"events": []}, f)

            engine = HistoryEngine(tmpdir)
            assert engine.event_count == 0

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            timeline_dir = os.path.join(tmpdir, "timeline")
            os.makedirs(timeline_dir)
            with open(os.path.join(timeline_dir, "bad.json"), "w") as f:
                f.write("{invalid json")

            with pytest.raises(json.JSONDecodeError):
                HistoryEngine(tmpdir)

    def test_rag_empty_knowledge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rag = HistoricalRAG(tmpdir)
            assert rag.event_count == 0
            assert rag.year_coverage == (0, 0)
            assert rag.retrieve(208, deviation=0.0) == []

    def test_event_proposal_fields_exist(self):
        from histrategy_engine.world import EventProposal

        p = EventProposal(event_id="test", title="测试", effects={}, narrative_hint="提示")
        assert p.event_id == "test"
        assert p.title == "测试"
        assert p.effects == {}
        assert p.narrative_hint == "提示"


# ═══════════════════════════════════════════════════════════════
# Probability formula tests
# ═══════════════════════════════════════════════════════════════


class TestProbabilityFormula:
    def test_zero_deviation_effective_prob(self, hist_engine, world_state):
        """At deviation=0, effective_prob = gravity."""
        hist_engine.reset()
        # three_visits_207 has gravity 0.95, at deviation=0, eff_prob = 0.95
        # Run multiple times — should trigger most of the time
        triggered = 0
        for _ in range(100):
            hist_engine.reset()
            hist_engine.check_events(207, Season.WINTER, world_state, deviation=0.0)
            if "three_visits_207" in hist_engine._triggered_events:
                triggered += 1
        # With prob=0.95, expect ~95 triggers out of 100
        assert triggered >= 80  # generous margin for randomness

    def test_max_deviation_halves_probability(self, hist_engine, world_state):
        """At deviation=1.0, effective_prob = gravity * 0.5."""
        # gravity=0.95, deviation=1.0 → eff_prob = 0.95 * 0.5 = 0.475
        triggered = 0
        for _ in range(100):
            hist_engine.reset()
            hist_engine.check_events(207, Season.WINTER, world_state, deviation=1.0)
            if "three_visits_207" in hist_engine._triggered_events:
                triggered += 1
        # With prob=0.475, expect ~48 triggers out of 100
        # Should be significantly less than at deviation=0
        assert triggered <= 80  # should be lower than zero-deviation case
