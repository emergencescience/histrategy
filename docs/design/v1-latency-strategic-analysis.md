# V1 Engine Latency & Reliability — Strategic Analysis

**Date:** 2026-06-18
**Author:** Prometheus (Hermes Agent)
**Status:** Analysis complete, implementation pending approval

---

## 1. Problem Statement

V1 engine uses a single monolithic LLM call (`deepseek-v4-flash` with thinking mode) that:
- Generates narrative
- Computes all faction state changes (troops, food, treasury, morale, territories)
- Resolves battles
- Determines diplomatic shifts
- Generates events and knowledge cards

**User-facing latency: 60-100s** for a 3-faction scenario. With timeout+retry, worst case is 260s before fallback.

---

## 2. Current Architecture (the bottleneck)

```
User submits → API → _resolve_and_advance()
                       ├── collect_all_decisions (instant, pre-generated)
                       └── _resolve_v1()
                             └── ONE LLM call (deepseek-v4-flash thinking)
                                   Input:  full world state + all decisions + history + diplomacy
                                   Output: narrative + state + battles + events + diplomacy
                                   60-100s → if timeout(130s) → retry(×2) → fallback
```

NPC decisions are already pre-generated via `_trigger_npc_decisions()` (parallel, 90s timeout, Q0 cached). The bottleneck is exclusively in `_resolve_v1()`.

---

## 3. Diagnosis: Two Unrelated Jobs in One Call

| Job | Nature | Needs thinking? | Can be parallel? |
|-----|--------|----------------|-------------------|
| **State computation** | Arithmetic/logic | No | Yes (per faction) |
| **Narrative generation** | Creative writing | Yes | No (needs full picture) |

State computation should be **deterministic or fast-LLM** (5-10s). Narrative can be **slow and rich** (30-60s) because it doesn't block gameplay state.

The fundamental insight: **you can play the game knowing only the state numbers. The narrative is flavor that can arrive later.**

---

## 4. Real Failures (beyond latency)

| Problem | Impact |
|---------|--------|
| **Zero visibility** | User stares at spinner for 100s, no idea if it's working |
| **Single point of failure** | One bad JSON parse → entire turn wasted, fallback to heuristic |
| **Retry = double pain** | Timeout at 130s → retry → 260s total |
| **Overloaded prompt** | Too many responsibilities → LLM quality degrades on each |

---

## 5. Recommended Architecture: Two-Phase V1

```
Phase 1: State Resolution (<10s)              Phase 2: Narrative (async, 30-60s)
┌─────────────────────────────────┐           ┌──────────────────────────┐
│ Parallel per-faction LLM calls   │           │ One rich LLM call         │
│ (fast model, no thinking)       │──states──→│ (deepseek thinking mode)  │
│ OR deterministic V3 engine      │           │ Generates narrative only   │
│                                 │           │ + knowledge cards          │
│ Updates: troops, food, treasury │           │ + events                   │
│          territories, morale    │           │                            │
│          battles (resolved)     │           │ Streamed via SSE to client │
│                                 │           │                            │
│ ← Returns immediately to user → │           │ ← Arrives 30-60s later ──→ │
└─────────────────────────────────┘           └──────────────────────────┘
```

### Phase 1 Options

| Option | Latency | Quality | Cost |
|--------|---------|---------|------|
| **A) V3 deterministic engine** (already built) | <1s | Predictable, consistent | **Low** — already exists |
| **B) Parallel fast-LLM per faction** | ~5s (parallel) | Better nonlinear events | Medium — new prompts needed |
| **C) Single fast-LLM (no thinking)** | ~10-15s | Decent | Low — switch model only |

**Recommendation: Option A (V3 engine) for Phase 1.** Already built, instant, deterministic, battle-tested.

### Phase 2 Improvements

- Leaner prompt: only needs final state + summary of what changed (not full decision text)
- Stream tokens to client → narrative appears line-by-line
- If Phase 2 fails → template narrative from Phase 1 state (no gameplay impact)
- Phase 2 failure doesn't block the next turn

---

## 6. Additional Optimizations (stackable)

### 6.1 Streaming token-by-token
Instead of waiting for full LLM completion, stream tokens. Narrative appears progressively like ChatGPT. No more "100s of nothing."

### 6.2 Cancel thinking for NPC decisions
NPC decisions currently use deepseek-v4-flash thinking (~20-30s each). For "attack X, defend Y," thinking mode is overkill. Use fast non-thinking model or the heuristic engine (already surprisingly good).

### 6.3 Pre-compute Phase 1 speculatively
When NPC decisions are generated at turn start, also pre-compute Phase 1 state changes. When human submits, state is already resolved. Only need to incorporate human's decision (diff-based update).

### 6.4 Reduce V1 prompt bloat
Current V1 prompt: full world state + all decisions + 4-turn history + diplomatic status. For Phase 2 (narrative only): just final state + "what happened" summary. Cuts prompt size by 60%+.

---

## 7. Expected Outcomes

| Metric | Before | After |
|--------|--------|-------|
| Time-to-playable | 60-100s | **<2s** |
| Time-to-narrative | 60-100s (blocking) | 30-60s (non-blocking, streamed) |
| Success rate | ~80% (timeout/parse failures) | **>95%** (Phase 1 deterministic) |
| Worst-case latency | 260s (timeout×2 + fallback) | **2s** (heuristic narrative fallback) |
| User experience | Spinner of death | Instant feedback, narrative arrives progressively |

---

## 8. Implementation Plan

```
Sprint 1: Split _resolve_v1() into Phase 1 + Phase 2
          Phase 1 → V3 engine (already exists)
          Phase 2 → existing V1 simulator (narrative only, leaner prompt)
          Response: return Phase 1 immediately, Phase 2 via polling endpoint

Sprint 2: Add SSE streaming for Phase 2 narrative
          Switch NPC decisions to fast model
          Measure: before/after metrics, A/B test quality
```

---

## 9. Key Decision Points

1. **Phase 1 engine**: V3 deterministic (fastest, most reliable) vs fast-LLM (more interesting nonlinear events)?
2. **Phase 2 async**: Polling (existing infra) vs SSE (better UX, more work)?
3. **NPC model**: Switch to fast non-thinking model now, or measure quality impact first?
4. **Backward compatibility**: Keep current V1 as "V1-classic" for comparison, or replace entirely?
