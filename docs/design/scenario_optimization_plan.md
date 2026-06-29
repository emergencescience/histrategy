# Technical Proposal: Scenario Optimization and Architecture Decoupling

This document outlines the technical design and steps required to optimize the game balance, reduce LLM simulation complexity, and improve the user experience for the **Three Kingdoms (three-kingdoms)** and **Ashes of Caesar (rome-triumvirate)** scenarios.

---

## 1. Objectives

1. **Three Kingdoms Scenario**: Shift starting point from **207 Winter** to **208 Spring** to align year calculations with seasons (Q0 = Spring) and provide Liu Bei with a strategic buffer (starting with Zhuge Liang on roster).
2. **Rome Triumvirate Scenario**: Consolidate minor factions to simplify the LLM's cognitive load. Merge `decimus_brutus` and `cassius_brutus` into `senate`; merge `lepidus` into `antony`. Keep Spring 44 BC as the starting point with Caesar already dead.
3. **Turn Suggestions Decoupling**: Move opening player recommendations (first 4 turns) from frontend hardcoding (`page.tsx`) to backend scenario configurations, indexed by `(scenario, faction, turn, locale)`.

---

## 2. Detailed Technical Design

### Task 2.1: Three Kingdoms (three-kingdoms) 208 Spring Start

#### Modified Files:
*   [scenarios/three-kingdoms/scenario.toml](file:///Users/julian/gitbubble/histrategy/scenarios/three-kingdoms/scenario.toml)
*   [scenarios/three-kingdoms/knowledge/initial_state.json](file:///Users/julian/gitbubble/histrategy/scenarios/three-kingdoms/knowledge/initial_state.json)
*   [scenarios/three-kingdoms/knowledge/timeline.json](file:///Users/julian/gitbubble/histrategy/scenarios/three-kingdoms/knowledge/timeline.json)

#### Changes to Apply:
1.  **scenario.toml**:
    *   Change `start_year` from `207` to `208`.
    *   Change `start_season` from `"冬"` (Winter) to `"春"` (Spring).
2.  **initial_state.json**:
    *   Set `year` to `208` and `season` to `"spring"`.
    *   Add `zhugeliang` as the starting advisor for the `shu` (Liu Bei) faction.
    *   Update initial text description to: *"公元208年春。诸葛亮已出山辅佐刘备，隆中对策初定。曹操彻底平定北方，正于邺城集结大军准备南征；孙权厉兵秣马准备西讨黄祖，大战阴云密布。"*
3.  **timeline.json**:
    *   Remove `three_visits_207` from pending event states (as it has already historically occurred).

---

### Task 2.2: Rome Triumvirate (rome-triumvirate) Faction Merger & Spring Start

#### Modified Files:
*   [scenarios/rome-triumvirate/knowledge/factions.json](file:///Users/julian/gitbubble/histrategy/scenarios/rome-triumvirate/knowledge/factions.json)
*   [scenarios/rome-triumvirate/knowledge/initial_state.json](file:///Users/julian/gitbubble/histrategy/scenarios/rome-triumvirate/knowledge/initial_state.json)
*   [scenarios/rome-triumvirate/npc_decisions_q0.json](file:///Users/julian/gitbubble/histrategy/scenarios/rome-triumvirate/npc_decisions_q0.json)

#### Changes to Apply:
1.  **Faction Consolidation**:
    *   Remove `lepidus`, `decimus_brutus`, and `cassius_brutus` as standalone active/minor factions in both `factions.json` and `initial_state.json`.
2.  **Territory & Resource Redistribution**:
    *   **antony**:
        *   Add starting territories: `"hispania_citerior"`, `"narbonensis"` (previously owned by Lepidus).
        *   Increase starting strength to `27,000` (12k Antony + 15k Lepidus).
        *   Increase starting treasury to `35,000` and food to `16,000`.
        *   Increase legions count to `7`.
    *   **senate**:
        *   Add starting territories: `"illyria"` (previously Decimus Brutus), `"mesopotamia"` (previously Cassius Brutus).
        *   Increase starting strength to `43,000` (8k Senate + 15k Decimus + 20k Cassius).
        *   Increase starting treasury to `38,000` and food to `21,000`.
        *   Increase legions count to `8`.
3.  **Relation Simplification**:
    *   Remove references to `lepidus`, `decimus_brutus`, and `cassius_brutus` from relations dictionaries.
    *   Keep/adjust relations between the 4 remaining major players (`octavian`, `antony`, `cleopatra`, `senate`) and `sextus_pompey` (retaining Pompey as a minor naval threat).
4.  **NPC Decisions**:
    *   In `npc_decisions_q0.json`, delete the command/decision sections for `lepidus`, `decimus_brutus`, and `cassius_brutus`. Ensure `antony` and `senate` have appropriate Turn 0 decisions to manage their newly acquired armies.

---

### Task 2.3: Dynamic Opening Suggestions (Backend Config & Frontend Integration)

#### Modified Files:
*   [histrategy/engine/helpers.py](file:///Users/julian/gitbubble/histrategy/histrategy/engine/helpers.py)
*   [histrategy/engine/intro_plan.py](file:///Users/julian/gitbubble/histrategy/histrategy/engine/intro_plan.py)
*   [apps/surprisal-portal/src/app/[lang]/play/histrategy/[sessionId]/page.tsx](file:///Users/julian/gitbubble/emergence/apps/surprisal-portal/src/app/[lang]/play/histrategy/[sessionId]/page.tsx)

#### Changes to Apply:
1.  **Backend Configuration (`helpers.py`)**:
    *   Expand `FIRST_TURN_SUGGESTIONS` to a generic `EARLY_TURNS_SUGGESTIONS` nested dictionary.
    *   Format structure: `EARLY_TURNS_SUGGESTIONS[scenario][faction][turn_number][locale] -> list[str]`.
    *   Define recommendations for Turns 1, 2, 3, and 4 for all playable factions in `three-kingdoms` and `rome-triumvirate`.
    *   *Example snippet:*
        ```python
        EARLY_TURNS_SUGGESTIONS = {
            "rome-triumvirate": {
                "octavian": {
                    1: {
                        "zh": ["【征召旧部】召回高卢时期的老兵，组建属于你的嫡系军团", "【发发表演说】前往元老院宣读遗嘱，争取温和派元老的支持", "【密会强敌】拜访执政官安东尼，要求其归还恺撒的遗产"],
                        "en": ["Rally Caesar's veterans to form your personal legions", "Address the Senate to gain support from moderate senators", "Meet with Mark Antony to demand Caesar's inheritance"]
                    },
                    # ... Turn 2, 3, 4 suggestions
                }
            }
        }
        ```
2.  **Backend Engine Implementation (`intro_plan.py` / `room_manager.py`)**:
    *   Update suggestions retrieval logic:
        *   If `turn_number <= 4` and matches the `EARLY_TURNS_SUGGESTIONS` config, return the hard-coded suggestions.
        *   If `turn_number > 4`, bypass dynamic LLM suggestions generation and directly fall back to the heuristic/rule-based suggestions (using `build_strategic_suggestions` or `_offline_v2_suggestions`) to ensure 0 extra latency and high performance.
3.  **Frontend Update (`page.tsx`)**:
    *   Delete hard-coded suggestions on lines 403-405, 418-420, 528-530.
    *   Simply map suggestions from API responses:
        ```typescript
        setSuggestions(response.new_suggestions || response.suggestions || []);
        ```


---

## 3. Verification Plan

### Automated Verification
*   Run scenario loader tests to verify that the start dates and consolidated factions load correctly:
    ```bash
    pytest tests/ -v
    ```
*   Verify that `get_plan_data()` returns the correct suggestions for the first 4 turns under different factions and locales.

### Manual Verification
*   Initialize a new single-player session for both `three-kingdoms` and `rome-triumvirate`.
*   Confirm that the UI displays clickable buttons containing the scenario-specific starting suggestions rather than the generic placeholder suggestions.
