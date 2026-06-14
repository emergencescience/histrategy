# Package Naming & PyPI Publishing Strategy

> **Task**: H14q — 理清目录命名 + PyPI 发布决策
> **Date**: 2026-06-14
> **Status**: ✅ Decided

---

## 1. Current Situation

The histrategy monorepo contains **four Python packages** under separate directories:

| Directory | PyPI Name | Version | Purpose | Consumers |
|-----------|-----------|---------|---------|-----------|
| `histrategy-engine/` | `histrategy-engine` | 0.1.1 | Deterministic physics engine (map, military, domestic, governance, characters, rules-as-YAML, fog-of-war AI) | Both SDK and Agent |
| `histrategy-sdk/` | `histrategy-sdk` | 0.2.0 | User-facing SDK: ServerClient (HTTP), Room (file-based), DirectEngine (in-process) | Game developers, AI agent builders |
| `histrategy-agent/` | `histrategy-agent` | 0.1.0 | IM agent shared core: GameSession, TurnProcessor, StateBridge, FormatEngine, IM adapters (Feishu/Telegram) | OpenClaw/Hermes skills |
| `histrategy/` | `histrategy` | 0.2.0 | Main game: CLI (`histrategy` command), FastAPI server, LLM integration, DB models, all game engines (v1/v2/v3) | End users, server deployments |

### Dependency Graph

```
histrategy-engine (pure Python, only pyyaml)
    ▲           ▲
    │           │
histrategy-sdk  histrategy-agent
    │ (hidden dep)
    ▼
histrategy (main) — CLI, server, LLM, engines
```

### Critical Issue: Hidden Dependency

`histrategy-sdk`'s `DirectEngine` and `Room` classes SHIP CODE that imports `histrategy.engine.game.GameEngine` at runtime:

```python
# histrategy-sdk/src/histrategy_sdk/_engine.py:52
from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter
```

This means `pip install histrategy-sdk[engine]` actually requires the full `histrategy` main package to be installed — the `[engine]` extra doesn't declare this dependency. It's a **hidden/implicit** dependency.

---

## 2. Decisions

### D1: Package Names — KEEP AS-IS

**Decision**: Keep all four names. Each serves a distinct audience with minimal overlap.

| Package | Who installs it | Why |
|---------|----------------|-----|
| `histrategy-engine` | Engine hackers, SDK/Agent as transitive dep | Pure physics, no LLM, no network |
| `histrategy-sdk` | Python developers building games or agents | `from histrategy_sdk import Room; room.play("打襄阳")` |
| `histrategy-agent` | IM platform integrators (OpenClaw, Hermes) | `from histrategy_agent import GameSessionManager` |
| `histrategy` | CLI users, server operators | `pip install histrategy && histrategy` |

**Rationale**: Renaming now breaks imports for existing consumers (the SDK is already documented in skills and guides). The only naming confusion is `histrategy-sdk` vs `histrategy-agent` — they sound similar but target different integration patterns (SDK = library-first, Agent = IM-first).

### D2: PyPI Publishing — ALL FOUR, STAGED

**Decision**: Publish all four packages to PyPI, in dependency order.

| # | Package | PyPI Status | Action |
|---|---------|------------|--------|
| 1 | `histrategy-engine` | ✅ Published v0.1.1 | No action needed |
| 2 | `histrategy` (main) | ❌ Not published | **Publish first** (blocker for SDK) |
| 3 | `histrategy-sdk` | ❌ Not published | Publish after main, declare `histrategy` as optional dep |
| 4 | `histrategy-agent` | ❌ Not published | Publish after main |

**Rationale**: The SDK's hidden dependency on `histrategy` must be resolved. The cleanest fix: make `histrategy` a proper PyPI package with an explicit `[engine]` extra in the SDK:

```toml
# histrategy-sdk/pyproject.toml
[project.optional-dependencies]
engine = ["histrategy>=0.2.0"]  # Was implicit, now explicit
```

### D3: SDK vs Agent — NO MERGE, BRIDGE INSTEAD

**Decision**: Keep `histrategy-sdk` and `histrategy-agent` separate. Create a thin bridge where Agent can optionally use SDK primitives.

**Boundary**:
- **SDK** is the *game interface*: `Room`, `ServerClient`, `MultiplayerRoom`, `TurnResult`
- **Agent** is the *platform adapter*: `GameSessionManager`, `TurnProcessor`, `FormatEngine`, `FeishuAdapter`

**Why not merge**: The SDK targets "I want to build a game client", the Agent targets "I want to let users play via Feishu chat". These are different use cases with different APIs. Merging would create a bloated package.

**Bridge path** (future H15): `histrategy-agent` optionally imports `histrategy_sdk.Room` as its game backend, replacing the current direct `histrategy_engine.WorldState` manipulation.

### D4: Main Package Structure

**Decision**: The main `histrategy/` directory is a proper PyPI package providing:

1. **CLI**: `histrategy` command (dev mode, Rich TUI, headless)
2. **Server**: FastAPI app (`histrategy server`)
3. **Library**: `from histrategy.engine.game import GameEngine` — consumable by SDK

The `pyproject.toml` at the repo root IS the package config. The SDK and Agent are subdirectories with their own `pyproject.toml`.

### D5: Version Alignment

**Decision**: All four packages share a synchronized MAJOR.MINOR version. Patch versions may diverge.

```
histrategy-engine   0.2.0  (bump from 0.1.1 for next release)
histrategy          0.2.0
histrategy-sdk      0.2.0
histrategy-agent    0.2.0  (bump from 0.1.0)
```

This makes it easy for users to know which versions are compatible.

---

## 3. Action Plan

### Immediate (this sprint)

1. **[x] H14p**: Bug fixes (V1 parse, year/season update, turn summaries) — committed in `d77201c`
2. **[x] H14q (this doc)**: Naming & PyPI decision documented
3. **[ ] H14n**: Agent architecture refactor (TurnProcessor → Room.play(), session → loader.build_world_state())
4. **[ ] Publish `histrategy` to PyPI** with proper `[project.optional-dependencies]`
5. **[ ] Update `histrategy-sdk` deps**: `engine = ["histrategy>=0.2.0"]`

### Near-term (H15)

- Bridge `histrategy-agent` → `histrategy-sdk` (optional import)
- Add integration tests across package boundaries
- CI pipeline for PyPI publishing on tag

---

## 4. FAQ

**Q: Why four packages instead of one monolith?**
A: Different users, different deps. A game developer wants `pip install histrategy-sdk`. A server operator wants `pip install histrategy`. Neither should pull in Feishu adapter code.

**Q: Why not merge SDK + Agent?**
A: The SDK is game logic (rooms, turns, decisions). The Agent is platform glue (IM messages, format rendering, session persistence across IM contexts). Merging creates unwanted dependencies (e.g., SDK users don't need IM adapter deps).

**Q: Why publish the main `histrategy` package to PyPI?**
A: Two reasons. (1) The SDK's DirectEngine already depends on it — we need to make that dependency explicit. (2) Users who want the CLI (`pip install histrategy && histrategy`) currently clone the repo — PyPI makes distribution trivial.
