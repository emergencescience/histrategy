"""Tests for the deterministic military settlement layer (H29a-e).

Verifies the fixes for the d02b446 room bugs:
  P1 — combat casualties actually reduce troops
  P2 — territory actually changes hands
  P3 — morale is capped ±15/turn and mean-reverts from extremes
  P4 — territory capture is gated by force ratio, not by narrative alone
"""

from __future__ import annotations

from histrategy_engine.world import FactionState, Territory, WorldState

from histrategy.engine.state_applier import StateApplier


def _make_world():
    """Two-faction world: strong Qing attacking weaker Southern Ming."""
    ws = WorldState(year=1646, turn_number=4)
    ws.player_faction_id = "nanming"
    ws.factions = {
        "nanming": FactionState(
            id="nanming", name="南明", ruler_id="hongguang",
            strength_actual=66000, morale_actual=60, treasury=100000, food=100000,
            territories=["nanjing", "yangzhou"],
        ),
        "qing": FactionState(
            id="qing", name="大清", ruler_id="dorgon",
            strength_actual=108000, morale_actual=80, treasury=70000, food=90000,
            territories=["beijing"],
        ),
    }
    ws.territories = {
        "nanjing": Territory(id="nanjing", name="南京", owner_id="nanming",
                             neighbors=["yangzhou"], population=500000),
        "yangzhou": Territory(id="yangzhou", name="扬州", owner_id="nanming",
                              neighbors=["nanjing"], population=300000),
        "beijing": Territory(id="beijing", name="北京", owner_id="qing",
                             neighbors=["yangzhou"], population=600000),
    }
    return ws


def test_casualties_reduce_troops():
    """P1: a battle must reduce both armies' strength_actual."""
    ws = _make_world()
    a0 = ws.factions["qing"].strength_actual
    d0 = ws.factions["nanming"].strength_actual
    delta = {
        "battle_results": [
            {"location": "yangzhou", "attacker": "qing", "defender": "nanming",
             "result": "attack_win", "territory_captured": True,
             "casualties": {"attacker": {"infantry": 5000}, "defender": {"infantry": 12000}}},
        ],
    }
    summary = StateApplier.apply_macro_delta(delta, ws)
    assert ws.factions["qing"].strength_actual < a0, "attacker took no losses"
    assert ws.factions["nanming"].strength_actual < d0, "defender took no losses"
    assert summary["battles_settled"] == 1
    assert summary["troops_lost"] > 0


def test_stronger_attacker_captures_city():
    """P2/P4: a stronger attacker (108k vs 66k, high morale) takes the city."""
    ws = _make_world()
    delta = {
        "battle_results": [
            {"location": "yangzhou", "attacker": "qing", "defender": "nanming",
             "result": "attack_win", "territory_captured": True,
             "casualties": {"attacker": 4000, "defender": 15000}},
        ],
    }
    summary = StateApplier.apply_macro_delta(delta, ws)
    assert ws.territories["yangzhou"].owner_id == "qing", "city did not change hands"
    assert "yangzhou" not in ws.factions["nanming"].territories
    assert "yangzhou" in ws.factions["qing"].territories
    assert summary["territories_captured"] == 1


def test_stronger_attacker_captures_despite_llm_defeat_narrative():
    """Regression (stalemate bug): the LLM's narrative "result" string must NOT
    gate capture.

    The world_simulator prompt tells the LLM to output result vocabulary
    (decisive_victory/crushing_defeat/...) that never matched the old hardcoded
    ("attack_win", "rout") check. Combined with "historical gravity" bias, the
    LLM narrated "decisive_defeat" for every player attack, and the city never
    changed hands even when the attacker had force superiority. Force ratio is
    the authority — a stronger attacker captures EVEN IF the LLM said "defeat".
    """
    ws = _make_world()
    delta = {
        "battle_results": [
            {"location": "yangzhou", "attacker": "qing", "defender": "nanming",
             "result": "decisive_defeat", "territory_captured": False,  # LLM narrated a loss
             "casualties": {"attacker": 4000, "defender": 15000}},
        ],
    }
    summary = StateApplier.apply_macro_delta(delta, ws)
    assert ws.territories["yangzhou"].owner_id == "qing", (
        "stronger attacker failed to capture because LLM narrated 'decisive_defeat'"
    )
    assert summary["territories_captured"] == 1


def test_weak_attacker_cannot_conquer_by_prose():
    """P4: a much weaker attacker cannot capture a defended city even if the
    LLM narrates a win. Force ratio gates territory transfer."""
    ws = _make_world()
    # Flip it: tiny Southern Ming force attacks the massive Qing capital.
    ws.factions["nanming"].strength_actual = 8000
    ws.factions["qing"].strength_actual = 120000
    ws.factions["qing"].morale_actual = 85
    delta = {
        "battle_results": [
            {"location": "beijing", "attacker": "nanming", "defender": "qing",
             "result": "attack_win", "territory_captured": True,
             "casualties": {"attacker": 500, "defender": 40000}},
        ],
    }
    StateApplier.apply_macro_delta(delta, ws)
    assert ws.territories["beijing"].owner_id == "qing", (
        "weak attacker conquered a strong garrison by narrative — P4 regression"
    )


def test_morale_event_capped_at_15():
    """P3: a single-turn morale swing is clamped to ±15."""
    ws = _make_world()
    ws.factions["qing"].morale_actual = 80
    delta = {"morale_events": [{"faction": "qing", "change": -60, "reason": "player propaganda"}]}
    StateApplier.apply_macro_delta(delta, ws)
    # -60 clamped to -15 → 65 (mean-reversion only kicks in beyond |m-55|>25)
    assert ws.factions["qing"].morale_actual == 65, ws.factions["qing"].morale_actual


def test_morale_mean_reversion_depins_extremes():
    """P3: morale stuck at 0 or 100 gets nudged back toward the center."""
    ws = _make_world()
    ws.factions["qing"].morale_actual = 0
    ws.factions["nanming"].morale_actual = 100
    StateApplier.apply_macro_delta({}, ws)
    assert ws.factions["qing"].morale_actual > 0, "morale stuck at 0"
    assert ws.factions["nanming"].morale_actual < 100, "morale stuck at 100"


def test_npc_conscript_is_deprecated_ignored():
    """NPC conscription is DEPRECATED — LLM conscript actions are ignored.

    NPC recruitment is now handled deterministically by
    QuarterlyEngine.execute_npc_recruitment() (morale × population), NOT via
    LLM-generated conscript actions in npc_faction_actions. A stale LLM
    conscript action must not double-recruit (the double-recruitment bug).
    """
    ws = _make_world()
    t0 = ws.factions["qing"].strength_actual
    tr0 = ws.factions["qing"].treasury
    delta = {"npc_faction_actions": [
        {"faction": "qing", "action_type": "conscript", "params": {"amount": 10000}},
    ]}
    StateApplier.apply_macro_delta(delta, ws)
    # Deprecated: conscript is ignored — no troop change, no treasury spend.
    assert ws.factions["qing"].strength_actual == t0
    assert ws.factions["qing"].treasury == tr0


def test_defender_loses_last_city_stays_active():
    """势力永生：失去最后一座城池后势力仍活跃（流亡军），不判灭亡。"""
    ws = _make_world()
    ws.factions["nanming"].territories = ["yangzhou"]  # single city left
    ws.territories["nanjing"].owner_id = "qing"
    ws.factions["qing"].territories = ["beijing", "nanjing"]
    delta = {"battle_results": [
        {"location": "yangzhou", "attacker": "qing", "defender": "nanming",
         "result": "rout", "territory_captured": True,
         "casualties": {"attacker": 3000, "defender": 20000}},
    ]}
    summary = StateApplier.apply_macro_delta(delta, ws)
    # 城池易主，但势力不灭亡
    assert ws.territories["yangzhou"].owner_id == "qing"
    assert ws.factions["nanming"].is_active is True
    assert summary["factions_defeated"] == 0


def test_guardrail_to_applier_pipeline():
    """Integration (P5): the exact resolver Step-5 sequence.

    guardrail.validate(delta, ws, baseline) must PRESERVE battle_results in its
    sanitized output, and apply_macro_delta must then settle it. This is the
    path that was silently broken (signature mismatch dropped everything).
    """
    from types import SimpleNamespace

    from histrategy.engine.guardrail import GuardrailValidator

    ws = _make_world()
    raw_delta = {
        "battle_results": [
            {"location": "yangzhou", "attacker": "qing", "defender": "nanming",
             "result": "attack_win", "territory_captured": True,
             "casualties": {"attacker": 4000, "defender": 15000}},
        ],
        "morale_events": [{"faction": "nanming", "change": -10}],
        "npc_faction_actions": [{"faction": "qing", "action_type": "conscript", "params": {"amount": 8000}}],
        "narrative_seeds": ["扬州陷落"],
    }
    baseline = SimpleNamespace(battles=[])

    # Step 5a: guardrail (called exactly as the resolver now calls it)
    validation = GuardrailValidator().validate(raw_delta, ws, baseline)
    assert isinstance(validation, dict) and "sanitized_delta" in validation
    sanitized = validation["sanitized_delta"]
    assert len(sanitized["battle_results"]) == 1, "guardrail dropped battle_results (P5 regression)"
    assert len(sanitized["npc_faction_actions"]) == 1

    # Step 5b: applier settles the sanitized delta
    q0 = ws.factions["qing"].strength_actual
    summary = StateApplier.apply_macro_delta(sanitized, ws, baseline)
    assert ws.territories["yangzhou"].owner_id == "qing"
    assert summary["battles_settled"] == 1
    # Qing lost troops in battle but conscripted 8000 net — verify both effects fired
    assert ws.factions["qing"].strength_actual != q0

