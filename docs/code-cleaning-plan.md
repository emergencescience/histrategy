# Histrategy — Code Cleaning Plan
> **Assignee**: Hermes Agent
> **Reviewer**: Julian
> **Status**: Ready for execution
> **Created**: 2026-06-26
> **Priority**: See per-phase labels

---

## Guiding Principle: Conservative Refactoring

> **When in doubt, keep it. When keeping, annotate it.**

Before deleting ANY file or code path, Hermes must verify all of the following:
1. No existing test references it (`pytest --collect-only | grep <filename>`)
2. No `docs/design-*.md` or `ROADMAP.md` lists it as future planned work
3. It is not a runtime fallback (offline mode, no-LLM mode, v1 engine)
4. It is not used by any SDK or agent skill (`histrategy-agent/`, `histrategy-sdk/`)

**The production site at `emergence.science/play/histrategy` must never break.**
Run regression tests before every merge.

---

## Protected Files — DO NOT MODIFY

| File/Directory | Reason to Preserve |
|---|---|
| `histrategy/engine/guardrail.py` | v3 Guardrail Validator (design-v3, Phase A.2) |
| `histrategy/engine/world_sim_interface.py` | v3 World Simulator LLM interface |
| `histrategy/engine/knowledge_layer.py` | Historical gravity system (Roadmap Phase 2) |
| `histrategy/engine/policy_evaluator.py` | Policy/tech tree (Roadmap Phase 1) |
| `histrategy/engine/narrative_director.py` | Chronicle entry system (Roadmap Phase 2) |
| `histrategy/engine/v1_simulator.py` | v1 engine — kept forever, most stable mode |
| `histrategy/engine/offline_sim.py` | No-LLM offline fallback — always needed |
| `histrategy/engine/offline_sim_engine.py` | No-LLM offline fallback — always needed |
| `histrategy-engine/` | Standalone pure-Python engine package |
| `histrategy-sdk/` | SDK for third-party clients |
| `histrategy-agent/skills/` | Agent skill definitions |
| `histrategy-knowledge/` | Community data layer |
| `scenarios/*/knowledge/` | Scenario knowledge data |
| `scenarios/*/scenario.toml` | Scenario configuration data |
| `docs/` | All design history — preserve entirely |
| `cli/record.py` | Video recording pipeline (Roadmap Phase 3) |

---

## Phase 0: Baseline Capture
**Estimate**: 1h | **Risk**: None | **Priority**: Pre-work

### Tasks

- [ ] Run full test suite and save output:
  ```bash
  pytest tests/ -x --tb=short -q 2>&1 | tee docs/scratch/baseline_tests.txt
  ```
- [ ] Capture online health baseline:
  ```bash
  curl https://emergence.science/play/histrategy/api/health | python3 -m json.tool > docs/scratch/baseline_health.json
  ```
- [ ] Create file inventory:
  ```bash
  find histrategy/ -name "*.py" | xargs wc -l | sort -rn > docs/scratch/file_inventory.txt
  ```
- [ ] Create `tests/regression/test_online_product.py`:

```python
"""Regression tests against the live production product.
Run before every deploy. Failure = deploy blocked.
"""
import httpx

PROD_BASE = "https://emergence.science/play/histrategy"
TIMEOUT = 15

def test_health():
    r = httpx.get(f"{PROD_BASE}/api/health", timeout=TIMEOUT)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "llm" in data
    assert "engine" in data

def test_scenarios_endpoint():
    r = httpx.get(f"{PROD_BASE}/api/scenarios", timeout=TIMEOUT)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"]
    assert len(data["scenarios"]) >= 2  # three-kingdoms + rome-triumvirate

def test_room_status_nonexistent_graceful():
    """Non-existent room must return 404, not 500."""
    r = httpx.get(f"{PROD_BASE}/api/rooms/nonexistent-room-id/status", timeout=TIMEOUT)
    assert r.status_code in (404, 200)

def test_create_sp_game_no_auth():
    """Single-player game start without auth returns structured error, not 500."""
    r = httpx.post(
        f"{PROD_BASE}/api/single-player/start",
        json={"faction": "shu", "scenario": "207", "lang": "zh"},
        timeout=30,
    )
    assert r.status_code in (200, 401, 403, 429)  # Never 500
```

### Success Criteria
- `docs/scratch/baseline_tests.txt` exists with test count
- `docs/scratch/baseline_health.json` shows `"status": "ok"`
- `tests/regression/test_online_product.py` created

---

## Phase 1: Analytics Instrumentation
**Estimate**: 2–3h | **Risk**: Low (additive only) | **Priority**: 🔴 P0

### Background
No product funnel tracking exists. Cannot measure what % of players reach turn 5, which factions are chosen, or where players drop off.

### Tasks

**1a. Add `game_event` table to `histrategy/db/schema.sql`:**

```sql
-- game_event: Product analytics. Append-only. Never delete rows unless count > 10000.
CREATE TABLE IF NOT EXISTS game_event (
    id           TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,   -- 'game_created' | 'turn_completed' | 'game_over' | 'room_created' | 'room_started'
    room_id      TEXT,
    faction      TEXT,
    scenario     TEXT,
    turn_number  INTEGER,
    engine_mode  TEXT,
    metadata     TEXT DEFAULT '{}',
    created_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_game_event_type ON game_event(event_type, created_at);
```

**1b. Add `log_game_event()` to `histrategy/db/models.py`:**

```python
def log_game_event(
    event_type: str,
    room_id: str | None = None,
    faction: str | None = None,
    scenario: str | None = None,
    turn_number: int | None = None,
    engine_mode: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Fire a product analytics event. Never raises — analytics must not crash the game."""
    import uuid, json
    from histrategy.db.connection import execute_write
    try:
        execute_write(
            """INSERT OR IGNORE INTO game_event
               (id, event_type, room_id, faction, scenario, turn_number, engine_mode, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (str(uuid.uuid4()), event_type, room_id, faction, scenario,
             turn_number, engine_mode, json.dumps(metadata or {})),
        )
    except Exception:
        pass
```

**1c. Fire events in `histrategy/server/api.py`:**

| Endpoint | Event | When |
|---|---|---|
| `POST /api/single-player/start` | `game_created` | After `start()` returns success |
| `POST /api/single-player/{id}/command` | `turn_completed` | After `command()` returns |
| `POST /api/rooms` | `room_created` | After `create_room()` returns |
| `POST /api/rooms/{id}/start` | `room_started` | After `start_game()` returns |
| `POST /api/rooms/{id}/decide` | `turn_completed` | After all factions resolved |
| game_over check | `game_over` | When response contains truthy `game_over` |

**1d. Add `GET /api/admin/stats` endpoint:**

```python
@app.get("/api/admin/stats")
def api_admin_stats():
    """Basic product funnel stats. Internal use only."""
    from histrategy.db.connection import execute
    rows = execute(
        """SELECT event_type, DATE(created_at) as day, COUNT(*) as count
           FROM game_event GROUP BY event_type, day
           ORDER BY day DESC, count DESC LIMIT 200"""
    )
    total = execute("SELECT COUNT(*) as n FROM game_event")[0]["n"]
    return {"ok": True, "total_events": total, "by_day": [dict(r) for r in rows]}
```

### Success Criteria
- [ ] `game_event` table in local SQLite after `init_db()`
- [ ] Manual: start game → `GET /api/admin/stats` shows `game_created` event
- [ ] Manual: complete turn → `GET /api/admin/stats` shows `turn_completed` event
- [ ] All existing tests pass (unchanged count)

---

## Phase 2: In-Memory State Persistence
**Estimate**: 2–3h | **Risk**: Medium | **Priority**: 🔴 P0

### Background
All single-player engines live in `_games: dict` in `api.py`. Server restart wipes all active games. Players return to a dead `game_id` with no explanation.

### Tasks

**2a. Persist game state on creation**

Investigate `histrategy/server/single_player.py`. After the engine is created and intro generated, verify that `save_room()` (or equivalent) is called immediately — not only after turn 1 completes. If not, add the call.

**2b. Add DB recovery in `_get_engine()`**

In `histrategy/server/api.py`, find `_get_engine()` or `_get_or_create_engine()`. Add:

```python
def _get_engine(game_id: str):
    if game_id in _games:
        return _games[game_id]
    # Recovery: restore from DB if in-memory dict was cleared (e.g. after restart)
    from histrategy.server.room_manager import _get_room
    room = _get_room(game_id)
    if room and room.world_state:
        import json
        from histrategy.engine.game import GameEngine
        engine = GameEngine.from_dict(json.loads(room.world_state), llm=_make_llm())
        _games[game_id] = engine
        return engine
    return None
```

**2c. Add regression test `tests/test_game_persistence.py`:**

```python
def test_game_survives_memory_loss(client):
    """Game must be recoverable from DB after in-memory dict is cleared."""
    r = client.post("/api/single-player/start", json={"faction": "shu", "scenario": "207", "lang": "zh"})
    assert r.status_code == 200
    game_id = r.json()["game_id"]

    # Simulate restart by clearing in-memory state
    from histrategy.server import api
    api._games.clear()
    api._game_meta.clear()

    # Game must still respond
    r2 = client.get(f"/api/single-player/{game_id}/status")
    assert r2.status_code == 200
    assert r2.json().get("game_id") == game_id
```

### Success Criteria
- [ ] `test_game_survives_memory_loss` passes
- [ ] All existing tests pass unchanged

---

## Phase 3: `api.py` Router Split
**Estimate**: 3–4h | **Risk**: Medium (structural only — no behavior change) | **Priority**: 🟡 P1

### Background
`api.py` is 1,495 lines with routes as closures inside `create_app()`. `RestoreGameRequest` defined twice. Untestable in isolation.

### Target Structure

```
histrategy/server/
  api.py                  # <200 lines: app factory + router includes
  engine_pool.py          # _games, _game_meta, _get_engine, _get_or_create_engine
  server_models.py        # All Pydantic models (deduplicated RestoreGameRequest)
  routes/
    __init__.py
    single_player.py      # /api/single-player/*
    rooms.py              # /api/rooms/*
    scenarios.py          # /api/scenarios/*
    health.py             # /api/health, /api/credit/status, /api/admin/stats
    games_legacy.py       # /api/games/* (deprecated — see Phase 4)
```

### Tasks
- [ ] Create `histrategy/server/engine_pool.py` — extract pool state and helpers
- [ ] Create `histrategy/server/server_models.py` — extract and deduplicate Pydantic models
- [ ] Create `histrategy/server/routes/` with modules above
- [ ] Replace inline route definitions in `create_app()` with `app.include_router(...)`
- [ ] Verify: `wc -l histrategy/server/api.py` < 200
- [ ] `pytest tests/ -q` passes with same count as baseline

### Success Criteria
- [ ] `api.py` ≤ 200 lines
- [ ] Baseline test count unchanged
- [ ] `pytest tests/regression/` passes against live production

---

## Phase 4: Deprecate Legacy `/api/games` Route
**Estimate**: 2h | **Risk**: Low | **Priority**: 🟡 P1

### Background — API Audit

The production portal (`surprisal-portal/src/lib/histrategy-api.ts`) **exclusively** uses:
- `POST /api/single-player/start`
- `GET /api/single-player/{id}/status`
- `POST /api/single-player/{id}/command`

The old `/api/games/*` routes are **not used by the production portal**. They predate the single-player API and are legacy code.

### Decision
Deprecate (mark + warn) but do NOT delete. Plan removal post-v1.0.

### Tasks
- [ ] Add `X-Deprecated: true` response header to all `/api/games/*` responses
- [ ] Add `"deprecated": true` field to all `/api/games/*` JSON responses
- [ ] Add `logging.warning("DEPRECATED: /api/games/... called. Use /api/single-player/...")` in each handler
- [ ] Add `# [DEPRECATED]` comment block at top of each `/api/games/*` handler explaining the migration path
- [ ] Create `docs/api-contract.md` documenting canonical vs. deprecated endpoints

### Success Criteria
- [ ] `curl /api/games/...` response body includes `"deprecated": true`
- [ ] Server logs show deprecation warning
- [ ] All existing tests pass unchanged

---

## Phase 5: Prompt Loader Scenario Support
**Estimate**: 2h | **Risk**: Medium | **Priority**: 🟡 P1
**Feature flag**: `HISTRATEGY_SCENARIO_PROMPTS=1` (default: off)

### Background
All LLM prompts are hardcoded to Three Kingdoms. Rome scenario games get Three Kingdoms flavor text — a significant immersion break.

### Tasks

**5a. Update `histrategy/llm/prompt_loader.py`:**

```python
import os
from pathlib import Path

def load_prompt(
    filename: str,
    scenario: str | None = None,
    default: str | None = None,
) -> str | None:
    """Load prompt with scenario override support.

    When HISTRATEGY_SCENARIO_PROMPTS=1:
      1. scenarios/{scenario}/prompts/{filename}  (scenario-specific)
      2. histrategy/llm/prompts/{filename}        (global fallback)
    When flag is off: always uses global prompts (backward compat).
    """
    use_scenario_prompts = os.environ.get("HISTRATEGY_SCENARIO_PROMPTS") == "1"

    if use_scenario_prompts and scenario:
        scenario_path = (
            Path(__file__).parent.parent.parent.parent
            / "scenarios" / scenario / "prompts" / filename
        )
        if scenario_path.exists():
            return scenario_path.read_text(encoding="utf-8").strip()

    path = Path(__file__).parent / "prompts" / filename
    if not path.exists() and default is not None:
        return default
    return path.read_text(encoding="utf-8").strip()
```

**5b. Create scenario prompt directories:**

- [ ] `scenarios/three-kingdoms/prompts/narrative.md` — copy of current `narrative.md` (unchanged)
- [ ] `scenarios/three-kingdoms/prompts/narrative_en.md` — copy of current `narrative_en.md`
- [ ] `scenarios/rome-triumvirate/prompts/narrative.md` — Roman historian voice:

```markdown
你是罗马帝国时代的历史学家，以塔西佗（Tacitus）和李维（Livy）的风格记录历史。

⚠️ **反幻觉规则**：TurnResult中的faction_snapshots和battles是当前**真实游戏状态**。
你必须尊重数据，不得凭空补充不存在于数据中的事件或人物。

## 核心规则

1. **绝不修改任何数据** — 只读取并描述 TurnResult 中的事实
2. **罗马史学风格** — 仿塔西佗风格：庄重、简洁、因果分明，政治嗅觉敏锐
3. **数值自然嵌入** — 如"（募兵三千，耗金千五百）"
4. **长度 200-400 字**
5. **忠实于物理引擎输出** — 不虚构未发生的事件

## 输出格式

### [年份] [季节] · 罗马纪事
（总览当前天下动态，1-2句）

### 战争与军事
（若有 battles，逐一简要描述战果）

### 政治与外交
（若有 diplomatic_events 或 political_events）

### 人物变易
（若有 character_events）

### 天下势力
（从 faction_snapshots 中选取关键势力变化）
```

- [ ] `scenarios/rome-triumvirate/prompts/narrative_en.md` — English Roman historian voice

**5c. Update `NarrativeEngine` to pass `scenario_id` to `load_prompt()`:**

In `histrategy/llm/narrative.py`, find the `NARRATIVE_SYSTEM` usage and update:
```python
scenario = getattr(self, "scenario_id", None)
narrative_prompt = load_prompt("narrative.md", scenario=scenario)
```

### Success Criteria
- [ ] `HISTRATEGY_SCENARIO_PROMPTS=0` (default): behavior unchanged, all tests pass
- [ ] `HISTRATEGY_SCENARIO_PROMPTS=1`: Rome games produce Roman-flavored narrative
- [ ] Scenario prompt files created at correct paths

---

## Phase 6: `mp.html` Local Demo Fixes
**Estimate**: 1h | **Risk**: None | **Priority**: 🟢 P2

### Tasks
- [ ] Add HTML comment at top of `histrategy/web/mp.html` marking it as local debug only
- [ ] Add visible banner: `🔧 本地调试模式 · <a href="https://emergence.science/play/histrategy">访问 emergence.science 体验完整多人版</a>`
- [ ] Add 8-second auto-poll in `startGameLoop()` or equivalent:
  ```javascript
  pollTimer = setInterval(async () => {
    if (!roomId) return;
    const s = await api('GET', `/api/rooms/${roomId}/status?faction_id=${myFaction}`).catch(() => null);
    if (s) updateGameUI(s);
  }, 8000);
  ```
- [ ] Stop poll when `phase === 'finished'`

### Success Criteria
- [ ] Banner visible when serving locally
- [ ] Two-tab test: submit in one tab → other updates within 10 seconds without manual refresh

---

## Phase 7: Documentation Updates
**Estimate**: 1h | **Risk**: None | **Priority**: 🟢 P2

### Tasks
- [ ] Update `docs/OPERATIONS.md`:
  - Remove `HISTRATEGY_MACRO=1` and `HISTRATEGY_V3=1` references
  - Document `HISTRATEGY_ENGINE=v1|v2|v3|offline`
  - Document `HISTRATEGY_SCENARIO_PROMPTS=1`
- [ ] Create `docs/api-contract.md` with canonical endpoints, deprecated endpoints, request/response shapes

---

## Execution Order

| Phase | Priority | Estimate | Depends On |
|-------|---------|---------|------------|
| 0: Baseline | Pre-work | 1h | — |
| 1: Analytics | 🔴 P0 | 2–3h | Phase 0 |
| 2: State Persistence | 🔴 P0 | 2–3h | Phase 0 |
| 3: Router Split | 🟡 P1 | 3–4h | 0, 1, 2 |
| 4: Deprecate /api/games | 🟡 P1 | 2h | Phase 3 |
| 5: Prompt Scenarios | 🟡 P1 | 2h | Phase 0 |
| 6: mp.html Fixes | 🟢 P2 | 1h | — |
| 7: Docs | 🟢 P2 | 1h | 1–5 |

**Total estimate**: 14–17 hours

---

## Success Matrix

| Metric | Baseline | Target | Verification |
|--------|----------|--------|-------------|
| Test count | Run Phase 0 | ≥ baseline | `pytest tests/ -q` |
| `api.py` line count | 1,495 | < 200 | `wc -l histrategy/server/api.py` |
| Server-restart game loss | 100% | 0% | `test_game_survives_memory_loss` |
| Funnel visibility | 0 events | ≥ 3 event types | `GET /api/admin/stats` |
| Scenario prompt support | 0 scenarios | ≥ 2 scenarios | Manual Rome game check |
| Online regression | Not tested | Suite passes | `pytest tests/regression/` |
| `mp.html` auto-refresh | Manual only | ≤ 10s | Two-tab manual test |
| Legacy route | Not marked | `deprecated: true` in response | `curl /api/games` |

---

## Notes for Hermes

1. **Commit per phase** — each phase is a standalone commit with passing tests
2. **Never reformat files wholesale** — only change lines required for the task
3. **If you find additional dead code** — add `# [CANDIDATE_FOR_REMOVAL]` comment, create a GitHub issue, do NOT delete
4. **If a test breaks** — stop the phase and report; do not suppress or skip tests
5. **v1 engine is kept forever** — it is the most stable mode; never remove it
6. **`log_game_event()` must never raise** — always wrap in try/except that passes silently
