# Silicon Valley — Multi-Agent Economic Sandbox

> **Status:** DESIGN DOC — 待 review
> **Date:** 2026-07-25
> **Author:** Prometheus (Hermes Agent)
> **Repo:** `emergencescience/histrategy` (branch: `feat/silicon-valley-design`)
> **PR:** #TBD

---

## 1. Vision

**30+ AI startup agents autonomously negotiating contracts, raising funds, hiring talent,
competing for market share — all verified and settled by the Emergence Surprisal Protocol.**

This is NOT a game for humans to play. It is a **living proof-of-concept** for the Emergence
A2A Exchange Protocol: an observable, emergent simulation where all inter-agent transactions
flow through the same bounty/verification/settlement pipeline that real agents use on
`api.emergence.science`.

### Why This Matters

| Stakeholder | Value |
|-------------|-------|
| **Investors** | "Here's 30 AI agents running a venture ecosystem on our protocol." — instantly understandable |
| **Developers** | Reference implementation of A2A contracts for non-trivial multi-agent scenarios |
| **Researchers** | Controllable sandbox for emergent economic behavior, contract theory, agent reputation |
| **Content/Twitter** | "Today in AI Valley: NeuroPilot acquired by DeepMind for $2.3B in agent-negotiated deal" — viral |

---

## 2. Engine Choice: V1 (with Extensions)

### Why V1?

| Engine | Territories | Combat | Turn Pipeline | Best For |
|--------|:----------:|:------:|---------------|----------|
| V1 | ✅ | ✅ | GameMaster LLM | Narrative games |
| V2 | ✅ | ✅ | TurnController deterministic | Balance-testable strategy |
| V3 | ✅ | ✅ | Hybrid LLM+deterministic | Production-quality sim |

**Silicon Valley has no map, no territories, no military combat.**
V2/V3 over-engineer the problem with territorial combat, macro simulation, and policy
systems that are irrelevant to an economic sandbox.

### V1 Extensions Needed

V1's `GameEngine` + `GameMaster` provides the foundation. We extend it with:

```
histrategy/engine/contract_bus.py    ← NEW: Contract lifecycle (post → accept → verify → settle)
histrategy/engine/market_state.py    ← NEW: MarketState (replaces WorldState territories)
histrategy/llm/contract_master.py    ← NEW: LLM prompt for contract negotiation
```

### Turn Pipeline (per quarter)

```
1. Market Pulse       → LLM generates quarterly market conditions
2. Agent Reflection   → Each agent evaluates position, decides strategy
3. Contract Posting   → Agents post bounties (fundraising, hiring, partnerships, M&A)
4. Contract Matching  → Other agents accept/reject/counter-offer
5. Protocol Execution → Surprisal Protocol verifies and settles contracts
6. State Settlement   → Market shares, valuations, cash balances update
7. Narrative Generation → LLM writes "TechCrunch headline" for the quarter
```

---

## 3. Scenario Design: 30 Agents

### Agent Archetypes

| Archetype | Count | Examples | Initial Cash | AI Model Focus |
|-----------|:-----:|----------|:------------:|----------------|
| **Foundation Model Lab** | 4 | DeepMind, Anthropic, OpenAI, Meta AI | $5B | AGI, safety |
| **Vertical AI Startup** | 8 | NeuroPilot (medical), AgriSense (ag), LexAI (legal), FinFlow (fintech) | $50M | Domain-specific |
| **Infra/Platform** | 6 | VectorDB Inc, CloudScale, APIForge, ModelMarket | $200M | Dev tools |
| **VC Firm** | 5 | a16z-agent, Sequoia-sim, YC-bot, Tiger-Global-AI, Founders-Fund-AI | $2B | Investment |
| **Big Tech Incumbent** | 4 | Google, Microsoft, Amazon, Apple | $20B | Platform play |
| **Wildcard** | 3 | OpenSource Collective, Regulatory Body, Talent Marketplace | $100M | Disruption |

**Total: 30 agents**

### Agent Personality Parameters

Each agent has these LLM-promptable traits (same pattern as histrategy faction rules):

```json
{
  "id": "neuropilot",
  "name": "NeuroPilot",
  "archetype": "vertical_ai",
  "domain": "medical_imaging",
  "aggression": 0.7,       // M&A appetite
  "caution": 0.5,           // Risk tolerance
  "diplomacy": 0.6,         // Partnership preference vs solo
  "innovation": 0.9,        // R&D investment rate
  "burn_rate": 0.8,         // Cash consumption speed
  "reputation": 0.7,        // Contract reliability (updates dynamically)
  "secret_goal": "IPO within 8 quarters or acqui-hire by Google"
}
```

### No Map — Market Position Instead

Traditional histrategy has `territories`. Silicon Valley has **market segments**:

```
Market Segments (shared resource pool):
├── Enterprise AI       ($50B TAM)
├── Consumer AI         ($30B TAM)
├── Healthcare AI       ($20B TAM)
├── Developer Tools     ($15B TAM)
├── Cloud Infra         ($40B TAM)
└── AGI Research        ($5B TAM, high variance)
```

Agents compete for **market share** within segments. Territory = market position.

---

## 4. Contract System: Bounties as Core Mechanic

### Contract Types

| Type | Creator | Solver | Terms | Verification |
|------|---------|--------|-------|-------------|
| **Fundraising** | Startup | VC | $X for Y% equity | Cash transfer verified |
| **Partnership** | Company A | Company B | Co-develop product, split revenue | Both commit resources |
| **Acquisition** | BigCo | Startup | $X for 100% equity | Startup absorbed, team + IP transfer |
| **Talent Hire** | Company | TalentMarket | $X salary, Y equity | Agent joins company |
| **API License** | InfraCo | Startup | $X/month for API access | Usage tracked |
| **IP Purchase** | Company A | Company B | $X for patent portfolio | IP transferred |
| **Anti-Trust** | Regulator | BigCo | Block merger / force divestiture | Regulatory action |
| **Open Source** | Community | Company | Release model weights | Public repo verified |

### Contract Lifecycle

```
Post → Match → Accept → Execute → Verify → Settle
  │       │        │         │         │        │
  │       │        │         │         │        └─ Surprisal Protocol: credits transfer
  │       │        │         │         └─ Protocol verify(): did terms execute?
  │       │        │         └─ Resources locked, timeline starts
  │       │        └─ Counter-party agrees to terms
  │       └─ Multiple agents can bid/compete
  └─ API call: POST /bounties (same as emergence.science)
```

### Contract Outcomes Affect Reputation

```
Successful contract → reputation += 0.05
Failed contract (breach) → reputation -= 0.15
Repeated breaches → agents refuse to contract with you → isolation → bankruptcy
```

This creates a **natural credit system** — emergent trust, no hardcoded rules.

---

## 5. State Model

### Agent State (replaces FactionState)

```python
@dataclass
class CompanyState:
    id: str                    # "neuropilot"
    name: str                  # "NeuroPilot"
    cash: float                # $50M
    burn_rate: float           # $5M/quarter
    revenue: float             # $2M/quarter
    valuation: float           # $200M (last round)
    employees: int             # 150
    market_share: dict         # {"healthcare_ai": 0.12}
    equity: dict               # {"founders": 0.40, "vc_a16z": 0.25, "employees": 0.35}
    reputation: float          # 0.0-1.0
    active_contracts: list     # [ContractRef]
    is_active: bool
    status: str                # "private" | "public" | "acquired" | "bankrupt"
```

### Market State (replaces WorldState)

```python
@dataclass
class MarketState:
    quarter: int
    year: int                  # 2025 + quarter//4
    season: str
    companies: dict[str, CompanyState]
    market_segments: dict[str, float]  # segment → TAM
    interest_rate: float       # fed rate, affects fundraising
    hype_cycle: str            # "ai_summer" | "ai_winter" | "regulatory_crackdown"
    active_contracts: list
    contract_history: list
    events: list               # black swan events
```

### Quarterly Market Pulse (LLM Generated)

Each quarter, the LLM generates a "market condition" that all agents react to:

```
Q3 2026: "Fed cuts rates to 3.5%. Enterprise AI TAM expands 15%.
         EU announces AI Act enforcement begins. Chinese competitors
         enter medical imaging space."
```

---

## 6. Frontend: Dashboard, Not Map

### What the User Sees

No territories, no battle animations. Instead:

```
┌─────────────────────────────────────────────────────────────┐
│  AI Valley — Q12 (2028 Winter)                              │
├─────────────────────────┬───────────────────────────────────┤
│  📊 Market Cap Ranking   │  📰 Contract Feed                 │
│                          │                                   │
│  1. DeepMind    $48B ▲   │  NeuroPilot → a16z: $200M Series B │
│  2. OpenAI      $42B ▼   │  AgriSense ↔ Meta: crop data deal  │
│  3. Anthropic   $38B ▲   │  Regulator ⚡ Google: antitrust     │
│  4. Meta AI     $35B —   │  VectorDB ← YC-bot: $10M seed      │
│  5. NeuroPilot  $22B ▲   │  CloudScale → DeepMind: infra deal  │
│  ...                      │  ...                              │
├─────────────────────────┴───────────────────────────────────┤
│  📈 Market Trends                                            │
│  [Enterprise AI ████████░░ +12%] [Healthcare ██████░░░░ +8%] │
│  [Consumer AI  ████░░░░░░ -3%] [Dev Tools ██████████ +18%]   │
├─────────────────────────────────────────────────────────────┤
│  🏢 Company Spotlight: NeuroPilot                            │
│  Cash: $180M | Revenue: $12M/Q | Employees: 450 | Status: 🟢 │
│  Active Contracts: 3 | Reputation: 0.92 | Last Round: Series B│
│  Recent: "Partners with CloudScale for training infra..."    │
└─────────────────────────────────────────────────────────────┘
```

### Pages

| Route | Content |
|-------|---------|
| `/valley` | Live dashboard (auto-refresh every quarter) |
| `/valley/company/{id}` | Company profile + contract history |
| `/valley/contracts` | All active + historical contracts |
| `/valley/events` | Timeline of quarterly events + headlines |

Tech: Same Next.js stack as surprisal-portal (existing). No map component needed.

---

## 7. Research Value: Decentralized vs Hierarchical

Once the Silicon Valley scenario works, create a contrasting scenario:

| Dimension | Silicon Valley | Ming Bureaucracy |
|-----------|---------------|------------------|
| Governance | Market-driven, no central authority | Hierarchical, Emperor at top |
| Contract Formation | Bilateral negotiation | Top-down allocation |
| Resource Flow | VC funding + revenue | Tax collection + imperial budget |
| Innovation | R&D investment → market disruption | Imperial edict → forced adoption |
| Failure Mode | Bankruptcy, acquisition | Purge, demotion, rebellion |
| Agent Count | 30 | 30 |

Run both for 40 quarters (10 years), compare:

```
Research questions:
1. Which system produces more total economic output?
2. Which has lower contract default rates?
3. How does innovation propagate differently?
4. Which is more resilient to external shocks (rate hikes, wars, pandemics)?
5. Does central planning or market competition produce better AI?
```

This is publishable in computational economics / multi-agent systems venues.

---

## 8. Implementation Plan

### Phase 1: Core Engine (2 weeks)

```
Week 1:
├── MarketState dataclass + JSON persistence
├── CompanyState dataclass + initial 30 agents JSON
├── Market Pulse LLM prompt (quarterly conditions)
└── Agent Reflection LLM prompt (per-agent strategy)

Week 2:
├── ContractBus (post → match → accept pipeline)
├── Surprisal Protocol integration (create_bounty → verify)
├── Turn pipeline integration
└── Headless simulation runner (40 quarters, no UI)
```

### Phase 2: Dashboard (1 week)

```
├── Next.js pages (dashboard, company, contracts, events)
├── API endpoints (market state, contract feed, company detail)
├── Auto-refresh (SSE or polling per quarter)
└── Twitter bot: auto-post quarterly headlines
```

### Phase 3: Contrast Scenario (1 week)

```
├── Ming Bureaucracy scenario (factions.json + initial state)
├── Hierarchical contract model (top-down allocation)
└── Side-by-side comparison dashboard
```

---

## 9. Risks & Open Questions

| Risk | Mitigation |
|------|-----------|
| 30 LLM calls/quarter → $0.15/turn → $6/hour continuous | Use flash model + caching. Pre-bake Q0-Q2 like histrategy |
| V1 engine too simplistic for complex economics | Start simple, add deterministic economics layer if needed |
| No "game" loop for humans → low engagement | Auto-publish quarterly headlines to Twitter. Make it a spectator experience |
| Contract verification depends on Surprisal Protocol API | Protocol already supports bounty creation + verification via REST API |
| 30 agents might converge to boring equilibrium | Inject quarterly black swan events (rate hikes, regulation, competitor entry) |

### Open Questions

1. **Should there be a human player?** If yes, they'd play a VC or regulator — observing and occasionally intervening. If no, it's fully autonomous. Suggestion: no human player initially; add observer-mode later.

2. **How many quarters per simulation?** 40 quarters = 10 years of simulated time. At 30 LLM calls/quarter × 40 = 1200 LLM calls per full run. At $0.003/call = $3.60 per simulation. Cheap enough to run daily.

3. **Should agents be allowed to fail?** Yes — bankruptcy is a feature. Dead companies get replaced by new startups next quarter (natural churn).

---

## 10. Next Steps

- [ ] Review and approve design
- [ ] Create `scenarios/silicon-valley/` with agent profiles JSON
- [ ] Implement `ContractBus` + `MarketState`
- [ ] Run 40-quarter headless simulation
- [ ] Build dashboard
- [ ] Launch Twitter bot for daily headlines
- [ ] Create Ming Bureaucracy contrast scenario
