# V3 Engine E2E Test Report — rome-triumvirate (English)

**Date:** 2026-06-18  
**Engine:** V3 (`HISTRATEGY_ENGINE=v3`)  
**Model:** deepseek-v4-flash  
**Scenario:** rome-triumvirate, lang=en  
**Factions:** 8 active (Octavian=human, 7 NPCs)  
**Turns played:** 3 (Q1-Q3)

---

## 1. Latency Analysis

| Turn | Elapsed (s) | Tokens |
|------|------------|--------|
| Q1 | 109.6 | 25,880 |
| Q2 | 92.7 | 26,685 |
| Q3 | 85.8 | 27,082 |
| **Avg** | **96.0** | **26,549** |

### Root Cause: Two Sequential LLM Calls

V3's `QuarterlyResolver.resolve()` makes TWO sequential LLM calls per turn:

```
Step 4: _run_macro_simulation()  →  MacroPolicyEngine.simulate()     (~40-50s)
Step 6: _generate_narratives()   →  NarrativeEngine.generate_global() (~40-50s)
                                                                      = 85-110s
```

Both use `deepseek-v4-flash` thinking mode on an 8-faction context (~26K tokens). **This is actually worse than V1** (which makes ONE call at 66-85s) because V3 adds the narrative call on top of the macro call.

### Comparison

| Engine | Calls/Turn | Avg Latency | Tokens/Turn |
|--------|-----------|-------------|-------------|
| V1 | 1 LLM | 66-85s | ~10-15K |
| **V3** | **2 LLM** | **85-110s** | **~26K** |
| V2 (deterministic) | 0 LLM | <1s | 0 |

---

## 2. Critical Bugs Found

### 🔴 BUG 1: Population = 0 for ALL factions

```
antony:         pop=0  troops=12000
cassius_brutus: pop=0  troops=20000
cleopatra:      pop=0  troops=15000
octavian:       pop=0  troops=1000
senate:         pop=0  troops=8000
```

Every faction has `population=0`. This is a V3 engine regression — population is not being computed or persisted. The population field exists in the DB (`game_state` table) but V3 never writes to it.

**Impact:** Population-based mechanics (tax revenue, conscription limits, food consumption) are all dead. The game economy is fundamentally broken.

### 🔴 BUG 2: Player faction (Octavian) state FROZEN

```
Octavian after 3 turns:
  troops=1000, food=500, treasury=1000, morale=55

Meanwhile NPCs fluctuate:
  Antony treasury: 25000 → 19237 → 3177 → 12565
  Cleopatra food:   40000 → 36145 → 39535 → 34916
```

Octavian's starting values never change. Only morale drifts (90→80→65→55). This means:
- Player's `troops`, `food`, `treasury` are **never updated by V3**
- The deterministic baseline (TurnController) is NOT applied to the human faction
- Only the LLM macro layer touches NPC factions

**Bug location:** `_run_macro_simulation()` in `quarterly_resolver.py` only passes the player as `player_decision`, not as a faction to apply deltas to. Line 280 has the `return` indented inside the `for` loop, exiting on first iteration.

### 🔴 BUG 3: `_run_macro_simulation` early return

```python
# quarterly_resolver.py line 270-290
for fid, decision in all_decisions.items():
    if fid != player_faction:
        npc_actions.append({...})
    
    return self.macro_policy_engine.simulate(...)  # ← RETURNS ON FIRST ITERATION!
```

The `return` is inside the `for` loop, not after it. It returns on the first faction, never building the full `npc_actions` list. This means the macro engine gets incomplete NPC context.

### 🟡 BUG 4: No policies generated

Across all 3 turns, **zero policy states** were recorded for any faction. The `policy_state` table is empty. V3's `save_policy_state()` is never called. This means:
- No policy evolution tracking
- Frontend can't show policy history
- NPC strategic shifts are invisible

### 🟡 BUG 5: 8 factions active for rome-triumvirate

The scenario loads all 8 Roman factions instead of the main triumvirate (Octavian, Antony, Lepidus + maybe Cleopatra/Senate). This inflates the LLM context unnecessarily:
- 8 factions × 5 state fields = 40 data points in prompt
- Each NPC needs decision generation
- Narrative must cover all 8

---

## 3. State Accuracy Analysis

### 3.1 Deterministic baseline not producing deltas

All `turn_deltas` show `source=llm` — the TurnController (deterministic V2 engine) is NOT producing any deltas. The LLM macro is the sole source of state changes.

Expected V3 behavior:
```
TurnController (deterministic) → baseline state changes
MacroEngine (LLM)              → nonlinear adjustments on top
```

Actual V3 behavior:
```
TurnController → produces nothing (or output is ignored)
MacroEngine    → produces ALL state changes
```

### 3.2 State change quality

The LLM macro is producing plausible-seeming deltas, but without deterministic grounding:
- Antony treasury goes 25000→19237→3177→12565 (wild swings)
- No logic for tax income vs expenditure
- No food consumption formula applied

---

## 4. Language Quality

✅ **All narratives are in English** — the `lang=en` metadata is correctly propagated. No Chinese characters detected in any Q1-Q3 narrative.

Narrative sample (Q1):
> "-44 Summer · Annals — In the summer following Caesar's murder, the Roman world fractured further: Antony marched on Rome..."

Quality is good, historically flavored.

---

## 5. LLM Performance

| Metric | Value |
|--------|-------|
| Avg tokens/turn | ~26,500 |
| Prompt/Completion ratio | ~60/40 (estimated) |
| Provider | DeepSeek |
| Model | deepseek-v4-flash (thinking mode) |
| Thinking mode overhead | Significant — likely 2-3× latency vs non-thinking |

The 26K token context per turn is expensive. For 10 turns: ~265K tokens. At DeepSeek pricing: ~$0.05-0.10 per game session.

---

## 6. Recommendations

### Immediate Fixes (P0)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 1 | **Population=0** | Ensure V3 `save_game_state` includes population field; fix TurnController to compute population | 1h |
| 2 | **Player state frozen** | Pass ALL faction states to macro engine, not just player_decision; fix early-return bug | 30min |
| 3 | **Early return in _run_macro_simulation** | De-indent the `return` statement to after the for loop | 5min |
| 4 | **No policies saved** | Add `save_policy_state()` call in `_save_v3_state_to_db` | 30min |

### Latency Reduction (P1)

| # | Approach | Expected Latency | Effort |
|---|----------|-----------------|--------|
| 1 | **Async narrative** — return baseline immediately, stream narrative later | 40-50s → 85-110s (non-blocking) | 4h |
| 2 | **Merge macro+narrative into one call** — single LLM generates both | 50-60s | 2h |
| 3 | **Drop thinking mode for macro** — use non-thinking model for state changes | 20-30s per call | 1h |
| 4 | **Reduce active factions** — limit rome-triumvirate to 4 main factions | ~30% token reduction | 1h |

### Architecture (P2)

See `docs/design/v1-latency-strategic-analysis.md` for the Two-Phase approach:
- **Phase 1 (instant):** Deterministic V2 TurnController → state updated
- **Phase 2 (async):** LLM macro + narrative → streamed to client

V3 already HAS the deterministic baseline in Step 2. The fix is to NOT block on Steps 4+6.

---

## 7. Summary

| Dimension | Status | Notes |
|-----------|--------|-------|
| **Latency** | 🔴 85-110s | 2 sequential LLM calls, worse than V1 |
| **Population** | 🔴 Always 0 | Critical economy bug |
| **Player state** | 🔴 Frozen | Player actions have no effect |
| **Narrative quality** | 🟢 Good | English, historically flavored |
| **Language support** | 🟢 Works | lang=en correctly propagated |
| **Policy tracking** | 🔴 Missing | No policies saved to DB |
| **Faction count** | 🟡 Too many | 8 factions inflate LLM context |
| **Deterministic baseline** | 🟡 Not producing deltas | TurnController output not visible |
| **Token efficiency** | 🟡 26K/turn | High for a strategy game turn |

**Bottom line:** V3 has solid architecture (deterministic baseline + LLM augmentation) but critical bugs make it currently worse than V1 in both correctness and speed. The two-phase async pattern described in the V1 analysis document is the right path forward for both engines.
