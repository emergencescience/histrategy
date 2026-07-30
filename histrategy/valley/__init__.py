"""Silicon Valley — Agent Economy Sandbox.

A pure-NPC economic simulation where 30+ AI company agents autonomously
negotiate deals, raise funds, hire talent, and compete for market share.
"""

from .market_state import CompanyState, MarketState, load_scenario

__all__ = ["CompanyState", "MarketState", "load_scenario"]
