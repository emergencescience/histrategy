# AI-Native Historical Strategy Game Design

> 三國志略 — Redesign Philosophy
> 
> Based on: AI Dungeon architecture analysis, Nottingham "LLMs and Games" (2024),
> Gallotta et al. survey (2024), and player experience testing.
>
> Date: 2026-05-23

---

## 1. Core Problem

### Current State

The v1 game has a fundamental design flaw: **it's a template-driven simulation with LLM narration on top.** Player input is classified into 5 buckets (economy/military/diplomacy/spy/domestic), each with a fixed template response. The LLM only writes pretty text over pre-computed outcomes.

### Root Cause

The architecture conflates two concerns that should be separate:
- **Strategic planning** (WHAT to do) — needs structure, guidance, options
- **Tactical execution** (HOW it happens) — needs freedom, emergence, narrative

Trying to do both in a single input box ("你的战略决策：") fails because:
1. New players don't know what to type → choice paralysis (Nottingham's anti-pattern)
2. The engine can't distinguish strategic intent from tactical flavor
3. Consequences feel generic because they're computed from the bucket, not the text

### Research Validation

| Source | Key Insight |
|--------|-------------|
| Nottingham (2024) | "Too many choices feels like work. Guide with generated suggestions + free text override." |
| AI Dungeon (Walton) | Early version had zero state = incoherent after 50 turns. Now uses structured Lorebook + Story Cards. |
| Gallotta et al. | Hybrid architecture (rules + LLM) outperforms pure LLM on coherence. |
| Player feedback | "I couldn't feel my decisions mattered" — template responses to everything. |

---

## 2. Redesign: Plan & Command

### 2.1 The Two Modes

```
┌─────────────────────────────────────────────┐
│              ONE TURN CYCLE                  │
│                                             │
│  1. SITUATION BRIEFING                      │
│     LLM summarizes what happened last       │
│     quarter across the realm                │
│           ↓                                 │
│  2. PLAN MODE (内政会议)                     │
│     Hold court with advisors                │
│     Each advisor gives their perspective     │
│     Player: choose a suggestion OR type      │
│     a strategic directive                   │
│           ↓                                 │
│  3. COMMAND MODE (政令执行)                  │
│     Bureaucracy executes the plan            │
│     World engine simulates consequences      │
│     Short-term aftermath (immediate)         │
│     Long-term seeds planted (future)         │
│           ↓                                 │
│  4. NEXT QUARTER SNAPSHOT                    │
│     New world state revealed                 │
│     NPC factions react                       │
│     Historical events check                  │
└─────────────────────────────────────────────┘
```

### 2.2 Plan Mode (内政会议)

**Design principle:** "Guided Freedom" — AI generates structured options, player can choose or override.

**Flow:**

```
Player enters PLAN MODE
  ↓
Court assembles (advisor introductions vary by faction)
  ↓
Each advisor speaks:
  ┌─────────────────────────────────────────────┐
  │ 荀彧（军师）: "主公，袁绍在河北集结重兵，     │
  │ 似有南下之意。建议派使者稳住袁绍，同时加强    │
  │ 许昌城防。"                                 │
  │                                             │
  │ 夏侯惇（将军）: "末将愿率三万精兵北上，      │
  │ 趁袁绍未稳先发制人！"                       │
  │                                             │
  │ 郭嘉（谋士）: "袁绍好谋无断，不足为虑。      │
  │ 但吕布在徐州虎视眈眈，主公不可不防。"        │
  └─────────────────────────────────────────────┘
  ↓
4 AI-generated strategic suggestions:
  1. 派使者结交袁绍，同时加固许昌城防
  2. 先发制人，率军北上攻打袁绍
  3. 东进徐州，先灭吕布再图河北
  4. 按兵不动，继续发展经济积蓄力量
  ↓
Player can:
  - Choose 1-4 (select a suggestion)
  - Type free text (override the suggestions)
  ↓
Plan is recorded for execution
```

**Benefits:**
- New players always have guidance (not staring at blank prompt)
- Expert players can type anything (freedom)
- The suggestions are contextual (based on current state)
- Advisors reveal faction dynamics (荀彧 vs 夏侯惇 disagreement)

### 2.3 Command Mode (政令执行)

**Design principle:** "LLM as Bureaucracy Simulator" — the plan is executed through a hierarchical system.

```
Player's plan recorded:
  "派使者稳住袁绍，同时加强许昌城防"
  ↓
Bureaucracy processes the plan:
  ┌─────────────────────────────────────────────┐
  │ ⚡ 政令执行                                 │
  │                                             │
  │ 外交：简雍奉命出使河北。袁绍设宴款待，但    │
  │ 席间神色不定。袁绍提出：若曹操愿尊他为盟主，│
  │ 则暂不南侵。                               │
  │                                             │
  │ 军事：曹仁督率五千民夫加固许昌城墙，预计    │
  │ 三个月内完工。夏侯惇对此不满——他更想打仗。  │
  │                                             │
  │ 内政：荀彧开仓放粮，安抚流民。民心+3。      │
  │ 但粮草-800。                               │
  └─────────────────────────────────────────────┘
  ↓
Short-term aftermath (immediate visible effects):
  - 袁绍暂时不会南下（但条件是尊他为盟主）
  - 许昌城防+2
  - 夏侯惇忠诚度-3（不满）
  - 民心+3, 粮草-800
  ↓
Long-term seeds (future consequences planted):
  - 袁绍要求被尊为盟主 → 未来可能的冲突
  - 夏侯惇不满 → 将来自动触发事件
  - 许昌城防增强 → 未来防御加成
```

### 2.4 State Management

```
~/.histrategy/
├── world_state.json        # Current game state (all factions, territories)
├── player_memory.json      # Player decisions + consequences
├── relationships.json      # Inter-faction relationship graph
├── event_history.json      # Full chronological event log
├── pending_seeds.json      # Long-term consequence seeds (not yet triggered)
└── court_dynamics.json     # Court faction relationships, advisor loyalty
```

**Layered context for LLM:**

| Layer | Size | Contents | Refresh |
|-------|------|----------|---------|
| **ALWAYS** | ~2000 tokens | System prompt, current state digest (5 lines), last 3 actions | Every turn |
| **RETRIEVED** | ~2000 tokens | Character bios mentioned, relevant relationships, active seeds | On demand |
| **LONG_TERM** | DB | Full history, relationship graph, all decisions, triggered events | Never in context |

---

## 3. Bureaucracy & Advisor System

### 3.1 Advisor Roles

Each faction has unique advisors with distinct perspectives:

| Role | Focus | Example (曹操) |
|------|-------|---------------|
| **军师 (Strategist)** | Overall strategy, all advice | 荀彧 |
| **将军 (General)** | Military, offensive | 夏侯惇 |
| **谋士 (Tactician)** | Schemes, intelligence | 郭嘉 |
| **内政官 (Minister)** | Economy, civil affairs | 荀攸 |

Advisors have:
- **Expertise** (what they're good at advising on)
- **Temperament** (aggressive/cautious/scheming)
- **Loyalty** (may defect or rebel if mistreated)
- **Relationship** (with each other — court factions!)

### 3.2 Court Faction Dynamics

```
Courtyard factions emerge naturally:
- 主战派 (War faction): 夏侯惇, 曹仁 — want to attack
- 稳健派 (Stability faction): 荀彧, 荀攸 — want to build
- 谋略派 (Scheme faction): 郭嘉, 程昱 — want to scheme

Player favors one faction → others lose loyalty
If loyalty drops below threshold:
  - Advisor may leak information to rivals
  - Advisor may form a coup/faction within court
  - Advisor may defect to another faction
```

### 3.3 Seed System (Long-term Consequences)

Not all consequences are immediate. Some are "seeds" planted now that bear fruit later:

```
Seed types:
├── DIPLOMATIC: "袁绍要求被尊为盟主" 
│   → If ignored, triggers "袁绍翻脸" event in 2-4 turns
├── MILITARY: "夏侯惇不满"
│   → If not addressed, triggers "夏侯惇擅自出兵" event
├── CIVIL: "许昌城防加固"
│   → Will activate as "+defense" if 许昌 is attacked
├── SCHEME: "细作已潜入洛阳"
│   → Reveals intelligence after 1-2 turns
└── ECONOMIC: "鼓励农耕令"
    → Gradual +food per turn for 4 turns
```

---

## 4. Historical Accuracy & Player Agency

### 4.1 The 50/20 Balance

| Constraint | Target | Mechanism |
|------------|--------|-----------|
| **Major historical events** | ~50% happen | LLM prompt includes timeline reference |
| **Player-driven divergence** | 20%+ possible | Seeds + state changes propagate |
| **NPC autonomy** | 30% emerge | NPC factions act based on their state |
| **Total** | 100% | All tracked via deviation_score in world_state |

### 4.2 Deviation Tracking

```python
world_state.player_deviation  # 0.00 = pure historical, 0.20+ = significantly alternate
```

When deviation > 0.30, the LLM prompt shifts from "here's what happened historically" to "history has diverged — here's what the world looks like now."

---

## 5. Technical Architecture

### 5.1 Component Diagram

```
┌──────────────────────────────────────────────────────┐
│                    CLI Layer                          │
│  ┌─────────────────┐  ┌──────────────────────────┐   │
│  │  Rich TUI        │  │  Dev CLI (--dev)         │   │
│  │  - Panels        │  │  - Plain text I/O        │   │
│  │  - Colors        │  │  - Machine-parseable     │   │
│  │  - Interactive   │  │  - Scripting friendly    │   │
│  └────────┬────────┘  └───────────┬──────────────┘   │
└───────────┼───────────────────────┼──────────────────┘
            │                       │
┌───────────┼───────────────────────┼──────────────────┐
│           ▼                       ▼                   │
│  ┌──────────────────────────────────────────────┐    │
│  │          Game Engine (Orchestrator)          │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │    │
│  │  │Plan Mode │ │Command   │ │ World State  │  │    │
│  │  │(Advisors)│ │Mode      │ │ Manager      │  │    │
│  │  │          │ │(Simulate)│ │              │  │    │
│  │  └─────┬────┘ └────┬─────┘ └──────┬───────┘  │    │
│  │        │           │              │           │    │
│  │        ▼           ▼              ▼           │    │
│  │  ┌──────────────────────────────────────┐    │    │
│  │  │       LLM World Model                │    │    │
│  │  │  - Advisor generation                │    │    │
│  │  │  - Consequence simulation            │    │    │
│  │  │  - Narrative generation              │    │    │
│  │  └──────────────────────────────────────┘    │    │
│  │                                              │    │
│  │  ┌──────────────────────────────────────┐    │    │
│  │  │       Knowledge Base                 │    │    │
│  │  │  - Characters.json (personalities)   │    │    │
│  │  │  - Factions.json (tendencies)        │    │    │
│  │  │  - Regions.json (geography)          │    │    │
│  │  │  - Events.json (historical)          │    │    │
│  │  └──────────────────────────────────────┘    │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 5.2 LLM Call Patterns

| Phase | LLM Call | Input | Output | Temperature |
|-------|----------|-------|--------|-------------|
| Advisor | Generate advisors + suggestions | State + player history | JSON: {advisors, suggestions} | 0.7 |
| Simulation | Simulate consequences | State + player's plan | JSON: {state_changes, aftermath, narrative} | 0.8 |
| NPC | Generate NPC actions | State (minus player) | JSON: {npc_actions, world_changes} | 0.6 |
| Narrative | Final narrative | All of the above | JSON: {narrative, choices} | 0.85 |

---

## 6. Kanban Task Breakdown

### Phase 1: Foundation (今天)

| # | Task | Est. |
|---|------|------|
| H23g | Design doc: Create complete design philosophy document | 30min |
| H23h | Rewrite PRD.md with Plan/Command philosophy | 20min |
| H23i | Rewrite tech-design.md with new architecture | 30min |
| H23j | Implement Plan Mode: advisor generation + 4 suggestions | 1h |
| H23k | Implement Command Mode: bureaucracy simulation + seeds | 1.5h |
| H23l | Implement court dynamics: faction relationships, loyalty | 1h |
| H23m | --dev mode E2E test script: automate playthrough all factions | 30min |
| H23n | Iterate based on E2E results until high quality | 2h |
| H23o | Marketing: update README, 知乎, Show HN, B站 | 1h |

### Phase 2: Polish (今天~明天)

| # | Task | Est. |
|---|------|------|
| H24a | Seed system: long-term consequences that trigger later | 1h |
| H24b | Historical deviation tracking + dynamic prompt | 30min |
| H24c | Save/load improvements: resume with full context | 30min |
| H24d | SVG demo re-record with new UI | 20min |
| H24e | GitHub star campaign: reach 100 | ongoing |

---

## 7. Success Criteria

### Quality Gate (must pass before marketing)

1. **E2E test**: All 4 factions playable for 5+ turns without crash
2. **Plan Mode**: Advisors speak, suggestions are contextual, free text accepted
3. **Command Mode**: Consequences are visible, specific, and connected to player's words
4. **Aftermath**: Short-term AND long-term consequences tracked
5. **Deviation**: Historical events occur ~50%, player changes 20%+
6. **Offline mode**: Still functional (template fallback)
7. **All 41 existing tests pass**: No regressions

### Marketing Targets

- **GitHub stars**: 100 by end of day
- **知乎**: Already published, aim for 1000+ views
- **Show HN**: Draft ready for Monday 10AM ET
- **B站**: Video or screen recording of Plan→Command cycle
