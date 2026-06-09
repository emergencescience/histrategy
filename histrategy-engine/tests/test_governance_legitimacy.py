from histrategy_engine.governance.legitimacy import LegitimacyState, update_legitimacy

def test_update_legitimacy_normal_events():
    state = LegitimacyState(current_score=50)
    updated = update_legitimacy(state, ["win_battle", "some_other_event"])
    assert updated.current_score == 55

def test_update_legitimacy_heavy_tax():
    state = LegitimacyState(current_score=50)
    updated = update_legitimacy(state, ["heavy_tax", "heavy_tax"])
    assert updated.current_score == 30

def test_update_legitimacy_clamping():
    state = LegitimacyState(current_score=98)
    updated = update_legitimacy(state, ["win_battle"])
    assert updated.current_score == 100
    
    state2 = LegitimacyState(current_score=5)
    updated2 = update_legitimacy(state2, ["heavy_tax"])
    assert updated2.current_score == 0
