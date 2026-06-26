# Histrategy — Refactoring Design Document
### For Hermes Agent Handoff · v1.0 · 2026-06-26

---

> [!IMPORTANT]
> This document is the single source of truth for the refactoring sprint.
> Hermes should treat every section as binding unless explicitly marked 🔶 DECISION NEEDED.

---

## 0. Guiding Principle: Conservative Refactoring

**Before deleting ANY file or code path, verify:**
1. Is there a test that exercises it? If yes, run it first.
2. Is it referenced in `ROADMAP.md` or any `docs/design-*.md` as future work? If yes, preserve it.
3. Is it a runtime fallback (e.g. offline mode, no-LLM mode)? If yes, MUST preserve.
4. Is it only used in local CLI tooling (not the live web product)? Mark it `# [LOCAL_ONLY]`, don't delete.

**The online product at `emergence.science/play/histrategy` must never break.**
Every phase must have a regression gate before merge.

---

## 1. Frontend Strategy

### 1.1 Decision: Dual-Client Architecture

**Keep both frontends with clear ownership:**

| Client | Location | Purpose | Status |
|--------|----------|---------|--------|
| **Portal (canonical)** | `emergence/apps/surprisal-portal/src/app/[lang]/play/histrategy/` | Production web UI, authenticated, bilingual | ✅ Primary |
| **Local debug** | `histrategy/histrategy/web/` | `histrategy serve` local demo, quick debugging, no-auth | ✅ Keep, but simplify |

**Do NOT copy portal code into `histrategy/web/`.** The portal is Next.js + React; the local web is vanilla HTML/JS. They share an API contract, not code.

### 1.2 What to DO with `mp.html`

- ✅ **Keep** `mp.html` but relabel it clearly in the header: `<!-- LOCAL DEBUG / DEMO ONLY — Not the production multiplayer UI -->`
- ✅ **Add** a banner at the top of the rendered page linking to `emergence.science/play/histrategy` for the full experience
- ✅ **Add** the missing auto-poll loop (8-second interval when `phase === 'waiting'`) — this is a 10-line fix
- 🚫 **Do NOT** rebuild `mp.html` into a full multiplayer UI — that's the portal's job

### 1.3 Portal: Extend for Multiplayer Rooms (Future, Not This Sprint)

The portal's `[sessionId]/page.tsx` already handles single-player via `single-player` API and multiplayer via room API calls. Extending it for a full multiplayer lobby would require:
- A new `[roomId]/page.tsx` route for room-specific views (already scaffolded in `[sessionId]/[roomId]/` directory!)
- Shared `useRoomStatus` hook with SSE or polling
- This is Phase 2 work — **not in this sprint**

### 1.4 Portal: Make Faction Select Dynamic (Quick Win — This Sprint)

`HiStrategyLobby.tsx` has `SCENARIOS` and `TK_FACTIONS`/`ROMAN_FACTIONS` hardcoded. As new scenarios are added (Ming dynasty, etc.), this file must be manually updated.

**Proposed change**: Add `GET /api/scenarios` call on mount, merge with static defaults as fallback.

```typescript
// In HiStrategyLobby.tsx
useEffect(() => {
  fetch(`${API_BASE}/games/histrategy/api/scenarios`)
    .then(r => r.json())
    .then(data => {
      if (data.ok && data.scenarios?.length) {
        setDynamicScenarios(data.scenarios);
      }
    })
    .catch(() => { /* use static SCENARIOS as fallback */ });
}, []);
```

---

## 2. Engine Consolidation

### 2.1 Current Engine Inventory

| Mode | File(s) | Status | Keep? |
|------|---------|--------|-------|
| **no-llm / offline** | `engine/offline_sim.py`, `engine/offline_sim_engine.py` | Active fallback | ✅ Keep |
| **v1 (pure LLM)** | `engine/v1_simulator.py`, `llm/prompts/v1_simulator.md` | Still used by `HISTRATEGY_ENGINE=v1` | ✅ Keep |
| **v2 (rule-centric)** | `engine/game.py` (v2 branch), `histrategy-engine/` package | Production default | ✅ Keep |
| **v3 (hybrid)** | `engine/quarterly_engine.py`, `engine/macro_policy_engine.py` | In development | ✅ Keep |
| **macro-llm** | Was separate; already merged into v3 via `engine_switch.py` | ✅ Already done! | N/A |

### 2.2 Macro-LLM Merge — Already Completed

Good news: `engine_switch.py` already maps `HISTRATEGY_MACRO=1` and `HISTRATEGY_V3=1` both to `EngineMode.V3`. The merge is **already done at the routing level**. What remains is:

- [ ] Verify that `macro_policy_engine.py` is called from within the v3 code path and NOT from a separate entry point
- [ ] Remove any direct references to `HISTRATEGY_MACRO` in documentation (update `OPERATIONS.md`)
- [ ] Remove the old `macro-llm` entry from `engine_switch.py` docstring comments (already done)

### 2.3 v1/v2 Branch Cleanup in `api.py`

The `if engine._use_v2: ... else: ...` pattern appears in ~20 places in `api.py`. This is **low priority** for now because:
- v1 is still a valid mode (`HISTRATEGY_ENGINE=v1`)
- Deleting the v1 branch now would break BYOK users using v1

**Proposed action**: Mark v1 branches with `# [V1_COMPAT]` comments but do NOT delete. Create a GitHub issue to track v1 deprecation post-v3 stabilization.

---

## 3. Documentation Gap Analysis

### 3.1 What the Docs Tell Us (That We Should Not Delete)

Reading `ROADMAP.md` reveals planned features that may appear "dead code" but are intentional placeholders:

| Code that looks unused | Why to keep it |
|------------------------|----------------|
| `engine/guardrail.py` | v3 Guardrail Validator (Phase A.2 in `design-v3-llm-simulation.md`) |
| `engine/world_sim_interface.py` | v3 World Simulator LLM interface |
| `engine/knowledge_layer.py` | Knowledge-as-gravity system (Phase 2: Historical anchor events) |
| `engine/policy_evaluator.py` | Policy/tech tree (Phase 1: legitimacy system) |
| `engine/narrative_director.py` | Chronicle entry system (Phase 2) |
| `cli/record.py`, `cli/simulator.py` | Video recording pipeline (Phase 3 roadmap) |
| `histrategy-sdk/` | SDK for external integrations (OpenClaw, Discord bot) |

> [!WARNING]
> Hermes must NOT delete any of the above files. They are pre-built infrastructure for roadmap items.

### 3.2 Documentation Gaps That Need Filling

| Gap | Action |
|-----|--------|
| `OPERATIONS.md` says "needs update" | Update after sprint to reflect v3 engine naming, no `HISTRATEGY_MACRO` env var |
| No API contract document | Add `docs/api-contract.md` listing all endpoints, request/response shapes |
| `engine_switch.py` is undocumented in ROADMAP | Add a note in ROADMAP that engine mode is controlled by `HISTRATEGY_ENGINE` env var |

---

## 4. Prompt Migration to Scenarios

### 4.1 Current Structure

All LLM prompts live at `histrategy/llm/prompts/` and are loaded by `prompt_loader.py` at import time as module-level constants. There are **22 prompt files**, several of which are scenario-specific (e.g., `narrative.md` mentions 三國志略 explicitly, `gamemaster_command.md` references Three Kingdoms concepts).

### 4.2 The Problem

```
narrative.md:  "你是《三國志略》的史官..."   ← Three Kingdoms hardcoded
npc_decision.md: "建安十二年..."            ← Three Kingdoms year hardcoded
```

When Rome scenario uses these prompts, it gets Three Kingdoms flavor text. This is a hallucination risk AND breaks the "generic framework" vision.

### 4.3 Proposed Two-Tier Prompt Architecture

```
histrategy/llm/prompts/          ← Generic/base prompts (scenario-agnostic)
  narrative_base.md              ← "你是一位史官，负责撰写史书纪事"
  npc_decision_base.md           ← Generic NPC decision prompt
  intent_parse.md                ← No changes needed (already generic)
  advisor.md                     ← Already generic
  alignment.md                   ← Already generic

scenarios/three-kingdoms/prompts/  ← Scenario-specific overrides
  narrative.md                   ← Inherits base + adds TK flavor
  npc_decision.md                ← Inherits base + TK personalities
  gamemaster_command.md          ← TK-specific intro/command prompts

scenarios/rome-triumvirate/prompts/ ← Roman scenario prompts
  narrative.md                   ← Roman historian voice
  npc_decision.md                ← Roman political reasoning
```

### 4.4 `prompt_loader.py` Evolution

```python
def load_prompt(filename: str, scenario: str | None = None, default: str | None = None) -> str | None:
    """Load prompt: scenario-specific override first, then global, then default."""
    if scenario:
        scenario_path = Path(__file__).parent.parent.parent / "scenarios" / scenario / "prompts" / filename
        if scenario_path.exists():
            return scenario_path.read_text(encoding="utf-8").strip()
    # Fall back to global prompts
    path = Path(__file__).parent / "prompts" / filename
    if not path.exists() and default is not None:
        return default
    return path.read_text(encoding="utf-8").strip()
```

### 4.5 Migration Plan

**This sprint**: 
- [ ] Add the `prompt_loader.py` scenario parameter support
- [ ] Create `scenarios/three-kingdoms/prompts/` with symlinks or copies of current scenario-specific prompts
- [ ] Create `scenarios/rome-triumvirate/prompts/` with Rome-specific narrative prompt

**NOT this sprint** (future):
- Rewriting all prompts to be base + override — that requires LLM quality testing

> [!NOTE]
> The current prompts still work. This is additive, not breaking. Existing prompts remain as fallback.

---

## 5. Methodology: Document-Driven + Regression Baseline

### 5.1 Recommendation: Document-Driven, with a Regression Baseline

**Why NOT pure TDD for this sprint:**
- The core engine already has 459 tests
- The refactoring is mostly structural (moving code, not changing behavior)
- Writing tests for LLM narrative output is expensive and fragile

**Why Document-Driven works here:**
- This doc IS the spec — Hermes reads it, implements it, checks against it
- Success criteria are defined per section (§5.3)
- The ROADMAP.md provides intent context

**What we DO need — a regression baseline:**

Before any changes, capture a "golden snapshot":

```bash
# Run this BEFORE any refactoring changes
pytest tests/ -x --tb=short -q > /tmp/baseline_test_report.txt
curl https://emergence.science/play/histrategy/api/health > /tmp/baseline_health.json
```

After each phase, run the same checks. If test count drops or health endpoint changes, STOP and investigate.

### 5.2 Regression Test for Online Product

The online product at `emergence.science/play/histrategy` must be verified at the API level (not UI level, to avoid flakiness):

```python
# tests/regression/test_online_product.py
import httpx

PROD_BASE = "https://emergence.science/play/histrategy"

def test_health():
    r = httpx.get(f"{PROD_BASE}/api/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "llm" in data
    assert "engine" in data

def test_scenarios_endpoint():
    r = httpx.get(f"{PROD_BASE}/api/scenarios", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"]
    assert len(data["scenarios"]) >= 2  # three-kingdoms + rome

def test_create_game_no_auth():
    # Unauthenticated game creation should fail gracefully (not 500)
    r = httpx.post(f"{PROD_BASE}/api/games", json={"faction": "shu"}, timeout=30)
    assert r.status_code in (200, 401, 403)  # Not 500
```

These tests run in CI before any deploy.

---

## 6. Phased Execution Plan for Hermes

### Phase 0: Baseline Capture (Pre-work, 1h)
- [ ] Run all existing tests, save report to `scratch/baseline_tests.txt`
- [ ] Capture `GET /api/health` response, save to `scratch/baseline_health.json`
- [ ] List all Python files with line counts: `find histrategy/ -name "*.py" | xargs wc -l | sort -rn > scratch/file_inventory.txt`
- [ ] Create `tests/regression/test_online_product.py` (tests from §5.2)

### Phase 1: Analytics Instrumentation (P0, 2–3h)
**Goal**: Gain visibility into player behavior without breaking anything.

Tasks:
- [ ] Add `game_event` table to `histrategy/db/schema.sql`
- [ ] Add `log_game_event(event_type, ...)` function to `histrategy/db/models.py`
- [ ] Fire `game_created` in `POST /api/games` (single-player) and `POST /api/rooms` (multiplayer)
- [ ] Fire `turn_completed` in `POST /api/games/{id}/command` and `POST /api/rooms/{id}/decide`
- [ ] Fire `game_over` when `result.game_over` is truthy
- [ ] Add `GET /api/admin/stats` endpoint: count by event_type grouped by day

**Success criteria:**
- All existing tests still pass
- `game_event` table exists in local SQLite after `init_db()`
- Manual play test fires at least 2 events visible in `GET /api/admin/stats`

### Phase 2: In-Memory State Persistence (P0, 2–3h)
**Goal**: Single-player games survive server restarts.

Tasks:
- [ ] In `POST /api/games`, after engine creation, call `_persist_single_player_game(game_id, engine)` which writes to `game_room` table using `room_manager` pattern (or a minimal equivalent)
- [ ] In `_get_engine(game_id)`, add DB recovery fallback: if `game_id` not in `_games`, try `GameEngine.from_dict(load_world_state_dict(game_id))`
- [ ] Add test: `test_game_survives_memory_loss` — create game, clear `_games` dict, assert `GET /api/games/{id}` still returns valid data

**Success criteria:**
- Test passes
- Existing tests unchanged

### Phase 3: `api.py` Router Split (P1, 3–4h)
**Goal**: Decompose god file into testable routers.

**IMPORTANT**: This is a pure structural refactor. Zero behavior change.

Tasks:
- [ ] Create `histrategy/server/routes/__init__.py`
- [ ] Create `histrategy/server/routes/games.py` — move all `@app.get/post("/api/games*")` routes
- [ ] Create `histrategy/server/routes/rooms.py` — move all `@app.*/("/api/rooms*")` routes
- [ ] Create `histrategy/server/routes/scenarios.py` — move `/api/scenarios` routes
- [ ] Create `histrategy/server/routes/health.py` — move `/api/health`, `/api/credit/status`
- [ ] Create `histrategy/server/engine_pool.py` — extract `_games`, `_game_meta`, `_game_turns`, `_get_engine`, `_get_or_create_engine`
- [ ] Create `histrategy/server/server_models.py` — extract all Pydantic models from `api.py`, fix the duplicate `RestoreGameRequest`
- [ ] Update `api.py` to `create_app()` that includes all routers
- [ ] Run all tests — must have 0 new failures

**Success criteria:**
- `api.py` is <200 lines (just app factory + route inclusion)
- All existing API tests pass
- Online product regression tests pass

### Phase 4: Prompt Loader Scenario Support (P1, 2h)
**Goal**: Scenario-specific prompt overrides.

Tasks:
- [ ] Update `prompt_loader.py` `load_prompt()` to accept optional `scenario` parameter (§4.4)
- [ ] Create `scenarios/three-kingdoms/prompts/narrative.md` (copy of current `narrative.md`)
- [ ] Create `scenarios/rome-triumvirate/prompts/narrative.md` (Rome-flavored version)
- [ ] Add `narrative_en.md` equivalents
- [ ] Update `NarrativeEngine` to pass `scenario=` to `load_prompt()`
- [ ] Verify that existing tests still pass (prompts are test-mocked anyway)

**Success criteria:**
- Rome scenario games generate Roman-flavored narrative, not Three Kingdoms flavor
- Three Kingdoms games unchanged
- All tests pass

### Phase 5: `mp.html` Quick Fixes (P2, 1h)
**Goal**: Make the debug UI slightly less misleading and add auto-refresh.

Tasks:
- [ ] Add HTML comment header: `<!-- LOCAL DEBUG / DEMO ONLY -->`
- [ ] Add visible banner: "📱 完整多人体验请访问 emergence.science/play/histrategy"
- [ ] Add 8-second auto-poll when `phase === 'waiting'`
- [ ] DO NOT change any API calls or styling beyond these

**Success criteria:**
- Manual test: open two browser tabs, submit decision in one, other updates within 10s without button click

---

## 7. Success Matrix

| Metric | Baseline (Before) | Target (After) | How to Verify |
|--------|-------------------|----------------|---------------|
| Test count | 459+ | ≥ 459 (no regression) | `pytest tests/ -q` |
| `api.py` line count | 1,495 | < 200 | `wc -l histrategy/server/api.py` |
| Server-restart game loss | 100% (all games lost) | 0% (games restored from DB) | `test_game_survives_memory_loss` |
| Player funnel visibility | 0 events tracked | ≥ 3 event types tracked | `GET /api/admin/stats` returns data |
| Scenario-specific prompts | 0 (all TK hardcoded) | ≥ 2 scenarios with own prompts | Manual Rome game check |
| Online product uptime | Not tested | Regression suite passes | `pytest tests/regression/` |
| `mp.html` auto-refresh | Manual only | ≤ 10s auto-update | Manual test |

---

## 8. What Hermes MUST NOT Change

> [!CAUTION]
> The following are protected — do not modify without explicit approval:

1. **`histrategy-engine/` package** — standalone pure-Python engine, has its own tests. Touch only for prompt migration.
2. **`histrategy-sdk/`** — SDK for third-party clients. No changes this sprint.
3. **`scenarios/*/knowledge/` and `scenarios/*/scenario.toml`** — data files, not code.
4. **`histrategy-knowledge/` directory** — community data layer.
5. **`histrategy/engine/guardrail.py`, `world_sim_interface.py`, `narrative_director.py`** — v3 pre-built infrastructure, even if currently unused.
6. **`cli/record.py`** — video recording pipeline, roadmap Phase 3.
7. **`histrategy-agent/skills/`** — agent skill definitions, separate concern.
8. **All `docs/` files** — design history, must be preserved.
9. **Database schema column additions** — always additive, never drop columns.

---

## 9. Open Questions for Julian (🔶 DECISION NEEDED)

1. **`mp.html` multiplayer**: Should `mp.html` eventually be deprecated once the portal supports multiplayer rooms natively? Or keep it permanently as a lightweight local-play option that doesn't require a portal account?

2. **Prompt migration timing**: The prompt scenario migration (Phase 4) touches NarrativeEngine which affects the live product quality. Should this be gated behind a feature flag (`HISTRATEGY_SCENARIO_PROMPTS=1`) so it can be rolled back without a deploy?

3. **Analytics data retention**: The `game_event` table will grow indefinitely. Should we add a `created_at` index and a cron job to archive/delete events older than 90 days? Or is the volume low enough to not worry about this yet?

4. **v1 engine deprecation timeline**: The docs say "v1/v2 architecture unification" is P1 in Phase 1 roadmap. Should v1 be formally deprecated (add deprecation warning to `engine_switch.py` logs) but kept, or is v1 actively used by any production users?

5. **`single_player.py` vs `api.py` game routes**: There are two different single-player APIs — `POST /api/games` (original) and `POST /api/single-player/start` (newer). Are they functionally equivalent? Can we consolidate, or do they serve different clients?
