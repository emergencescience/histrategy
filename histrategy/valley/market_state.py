"""MarketState and CompanyState dataclasses for Silicon Valley simulation.

Replaces WorldState/FactionState from histrategy's war-game engine.
No maps, no territories — only market segments, cash, and contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ── Company State ────────────────────────────────────────────


@dataclass
class CompanyState:
    """State of a single AI company / investor / regulator."""

    id: str
    name: str
    archetype: str  # foundation_lab, vertical_startup, infra_platform, vc_firm, big_tech, wildcard
    primary_segment: str  # primary market segment
    secondary_segments: list[str] = field(default_factory=list)

    # Financials (all in millions USD)
    cash_m: float = 0
    burn_rate_m_per_q: float = 0
    revenue_m_per_q: float = 0
    employees: int = 0
    valuation_m: float = 0
    equity: dict[str, float] = field(default_factory=dict)  # stakeholder → share

    # Personality (0.0–1.0)
    aggression: float = 0.5
    caution: float = 0.5
    diplomacy: float = 0.5
    innovation: float = 0.5

    # Dynamic
    reputation: float = 0.5
    market_share: dict[str, float] = field(default_factory=dict)  # segment → share
    secret_goal: str = ""
    status: str = "private"  # private, public, acquired, bankrupt, nonprofit, government

    # VC-specific
    portfolio: list[str] = field(default_factory=list)
    dry_powder_m: float = 0

    # Domain (vertical startups)
    domain: str = ""

    # Turn-by-turn delta tracking
    last_quarter_delta: dict = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status not in ("bankrupt", "acquired")

    def cash_runway_quarters(self) -> float:
        """Months of runway remaining at current burn rate."""
        net = self.burn_rate_m_per_q - self.revenue_m_per_q
        if net <= 0:
            return float("inf")
        return self.cash_m / net

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "archetype": self.archetype,
            "primary_segment": self.primary_segment,
            "secondary_segments": self.secondary_segments,
            "cash_m": self.cash_m,
            "burn_rate_m_per_q": self.burn_rate_m_per_q,
            "revenue_m_per_q": self.revenue_m_per_q,
            "employees": self.employees,
            "valuation_m": self.valuation_m,
            "equity": self.equity,
            "aggression": self.aggression,
            "caution": self.caution,
            "diplomacy": self.diplomacy,
            "innovation": self.innovation,
            "reputation": self.reputation,
            "market_share": self.market_share,
            "secret_goal": self.secret_goal,
            "status": self.status,
            "portfolio": self.portfolio,
            "dry_powder_m": self.dry_powder_m,
            "domain": self.domain,
            "last_quarter_delta": self.last_quarter_delta,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CompanyState":
        return cls(**{k: d.get(k, v.default if v.default is not v.default else None)
                       for k, v in cls.__dataclass_fields__.items()})


# ── Market State ─────────────────────────────────────────────


@dataclass
class MarketState:
    """Complete market state for the Silicon Valley simulation."""

    quarter: int = 0
    year: int = 2025
    season: str = "Q1"

    # All agents
    companies: dict[str, CompanyState] = field(default_factory=dict)

    # Market segments (segment_id → TAM in billions)
    market_segments: dict[str, dict] = field(default_factory=dict)

    # Macro
    fed_rate: float = 4.5
    vc_sentiment: str = "cautious_optimistic"  # bearish, cautious_optimistic, bullish, euphoric
    hype_cycle: str = "ai_summer"  # ai_summer, ai_winter, regulatory_crackdown

    # Contract history
    active_contracts: list[dict] = field(default_factory=list)
    contract_history: list[dict] = field(default_factory=list)

    # Quarterly pulse
    market_pulse: str = ""
    events: list[dict] = field(default_factory=list)

    # Narrative
    headlines: list[str] = field(default_factory=list)
    turn_memory: list[dict] = field(default_factory=list)  # recent quarter summaries

    SEASONS = ["Q1", "Q2", "Q3", "Q4"]

    def advance_quarter(self):
        self.quarter += 1
        qi = self.quarter % 4
        self.season = self.SEASONS[qi] if qi > 0 else "Q4"
        if self.quarter % 4 == 0:
            self.year += 1

    def active_companies(self) -> list[CompanyState]:
        return [c for c in self.companies.values() if c.is_active()]

    def get_leaderboard(self, by: str = "valuation_m", n: int = 10) -> list[CompanyState]:
        return sorted(self.active_companies(), key=lambda c: getattr(c, by, 0), reverse=True)[:n]

    def to_dict(self) -> dict:
        return {
            "quarter": self.quarter,
            "year": self.year,
            "season": self.season,
            "companies": {cid: c.to_dict() for cid, c in self.companies.items()},
            "market_segments": self.market_segments,
            "fed_rate": self.fed_rate,
            "vc_sentiment": self.vc_sentiment,
            "hype_cycle": self.hype_cycle,
            "active_contracts": self.active_contracts,
            "contract_history": self.contract_history,
            "market_pulse": self.market_pulse,
            "events": self.events,
            "headlines": self.headlines,
            "turn_memory": self.turn_memory,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MarketState":
        ms = cls()
        ms.quarter = data.get("quarter", 0)
        ms.year = data.get("year", 2025)
        ms.season = data.get("season", "Q1")
        ms.companies = {cid: CompanyState.from_dict(cd) for cid, cd in data.get("companies", {}).items()}
        ms.market_segments = data.get("market_segments", {})
        ms.fed_rate = data.get("fed_rate", 4.5)
        ms.vc_sentiment = data.get("vc_sentiment", "cautious_optimistic")
        ms.hype_cycle = data.get("hype_cycle", "ai_summer")
        ms.active_contracts = data.get("active_contracts", [])
        ms.contract_history = data.get("contract_history", [])
        ms.market_pulse = data.get("market_pulse", "")
        ms.events = data.get("events", [])
        ms.headlines = data.get("headlines", [])
        ms.turn_memory = data.get("turn_memory", [])
        return ms


# ── Scenario Loader ──────────────────────────────────────────

def load_scenario(scenario_dir: str = "scenarios/silicon-valley") -> MarketState:
    """Load the Silicon Valley scenario from agents.json."""
    agents_path = Path(scenario_dir) / "agents.json"
    if not agents_path.exists():
        raise FileNotFoundError(f"Scenario not found: {agents_path}")

    data = json.loads(agents_path.read_text(encoding="utf-8"))

    ms = MarketState()
    ms.market_segments = data.get("market_segments", {})

    for agent_data in data.get("agents", []):
        c = CompanyState(
            id=agent_data["id"],
            name=agent_data["name"],
            archetype=agent_data["archetype"],
            primary_segment=agent_data["primary_segment"],
            secondary_segments=agent_data.get("secondary_segments", []),
            cash_m=agent_data.get("cash_m", 0),
            burn_rate_m_per_q=agent_data.get("burn_rate_m_per_q", 0),
            revenue_m_per_q=agent_data.get("revenue_m_per_q", 0),
            employees=agent_data.get("employees", 0),
            valuation_m=agent_data.get("valuation_m", 0),
            equity=agent_data.get("equity", {}),
            aggression=agent_data.get("aggression", 0.5),
            caution=agent_data.get("caution", 0.5),
            diplomacy=agent_data.get("diplomacy", 0.5),
            innovation=agent_data.get("innovation", 0.5),
            reputation=agent_data.get("reputation", 0.5),
            market_share=agent_data.get("market_share", {}),
            secret_goal=agent_data.get("secret_goal", ""),
            status=agent_data.get("status", "private"),
            portfolio=agent_data.get("portfolio", []),
            dry_powder_m=agent_data.get("dry_powder_m", 0),
            domain=agent_data.get("domain", ""),
        )
        ms.companies[c.id] = c

    return ms
