#!/usr/bin/env python3
"""Headless Silicon Valley simulation runner.

Usage:
    cd histrategy/
    python scripts/run_valley.py                    # 4 quarters (default)
    python scripts/run_valley.py --quarters 10      # 10 quarters
    python scripts/run_valley.py --quarters 40 --output valley_10yr.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add repo root to path so we can import histrategy
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from histrategy.valley.market_state import MarketState, CompanyState, load_scenario
from histrategy.llm.adapter import LLMAdapter

# ── Prompt ───────────────────────────────────────────────────

SIMULATOR_PROMPT_PATH = REPO_ROOT / "scenarios/silicon-valley/prompts/v1_simulator_en.md"
SIMULATOR_PROMPT = SIMULATOR_PROMPT_PATH.read_text(encoding="utf-8")


# ── Context Builder ──────────────────────────────────────────

def build_market_context(ms: MarketState) -> str:
    """Build the LLM prompt context from current market state."""
    parts = []

    # Quarter header
    parts.append(f"## Current State: {ms.year} {ms.season} (Quarter {ms.quarter})\n")

    # Macro
    parts.append(f"Fed Rate: {ms.fed_rate}% | VC Sentiment: {ms.vc_sentiment} | Hype Cycle: {ms.hype_cycle}\n")

    # Market segments
    parts.append("## Market Segments\n")
    for seg_id, seg in ms.market_segments.items():
        parts.append(f"- {seg_id}: TAM ${seg['tam_b']}B, growth {seg['growth_rate']*100:.0f}%")

    # Company states (compact)
    parts.append(f"\n## Companies ({len(ms.active_companies())} active)\n")
    for c in ms.active_companies():
        runway = c.cash_runway_quarters()
        runway_str = f"{runway:.1f}q" if runway < 100 else "∞"
        portfolio_str = f" | Portfolio: {c.portfolio}" if c.portfolio else ""
        domain_str = f" [{c.domain}]" if c.domain else ""
        parts.append(
            f"### {c.name} ({c.id}) — {c.archetype}{domain_str}\n"
            f"Status: {c.status} | Cash: ${c.cash_m}M ({runway_str} runway) | "
            f"Burn: ${c.burn_rate_m_per_q}M/q | Revenue: ${c.revenue_m_per_q}M/q | "
            f"Employees: {c.employees} | Valuation: ${c.valuation_m}M\n"
            f"Rep: {c.reputation:.2f} | "
            f"Aggression:{c.aggression:.2f} Caution:{c.caution:.2f} "
            f"Diplomacy:{c.diplomacy:.2f} Innovation:{c.innovation:.2f}\n"
            f"Goal: {c.secret_goal}{portfolio_str}\n"
            f"Market Share: {json.dumps(c.market_share) if c.market_share else 'none (investor/regulator)'}"
        )

    # Active contracts
    if ms.active_contracts:
        parts.append(f"\n## Active Contracts ({len(ms.active_contracts)})\n")
        for ct in ms.active_contracts:
            parts.append(f"- {ct.get('type')}: {ct.get('from')} → {ct.get('to')} "
                         f"${ct.get('amount_m', 0)}M (status: {ct.get('status')})")

    # Recent history
    if ms.turn_memory:
        parts.append(f"\n## Recent Quarter Summaries\n")
        for mem in ms.turn_memory[-3:]:
            parts.append(f"- Q{mem.get('quarter')}: {mem.get('headline', '')}")

    return "\n".join(parts)


# ── State Applier ────────────────────────────────────────────

def apply_llm_result(ms: MarketState, result: dict) -> MarketState:
    """Apply LLM simulation output to market state."""
    # Macro
    ms.market_pulse = result.get("market_pulse", "")
    ms.fed_rate = result.get("fed_rate", ms.fed_rate)
    ms.vc_sentiment = result.get("vc_sentiment", ms.vc_sentiment)
    ms.hype_cycle = result.get("hype_cycle", ms.hype_cycle)

    # Events
    ms.events = result.get("events", [])
    ms.headlines.append(result.get("headline", ""))

    # Contracts
    ms.active_contracts = result.get("active_contracts", [])
    ms.contract_history.extend(result.get("contract_history", []))

    # Market segments
    for seg_id, seg_data in result.get("market_segments", {}).items():
        if seg_id in ms.market_segments:
            ms.market_segments[seg_id].update(seg_data)

    # Companies
    for cid, cdata in result.get("companies", {}).items():
        if cid not in ms.companies:
            continue
        c = ms.companies[cid]
        for field in ("cash_m", "burn_rate_m_per_q", "revenue_m_per_q",
                       "employees", "valuation_m", "reputation", "status"):
            if field in cdata:
                setattr(c, field, cdata[field])
        if "market_share" in cdata:
            c.market_share = cdata["market_share"]
        if "portfolio" in cdata:
            c.portfolio = cdata["portfolio"]
        c.last_quarter_delta = cdata.get("last_quarter_delta", {})

    # Turn memory
    ms.turn_memory.append({
        "quarter": ms.quarter,
        "headline": result.get("headline", ""),
        "market_pulse": ms.market_pulse,
        "event_count": len(ms.events),
    })

    # Advance quarter
    ms.advance_quarter()

    return ms


# ── Print Helpers ────────────────────────────────────────────

def print_leaderboard(ms: MarketState, n: int = 15):
    """Print the market cap leaderboard."""
    active = ms.active_companies()
    ranked = sorted(active, key=lambda c: c.valuation_m, reverse=True)[:n]

    print(f"\n{'='*80}")
    print(f"  🏆 {ms.year} {ms.season} — Market Cap Leaderboard")
    print(f"{'='*80}")
    print(f"{'#':>3} {'Company':<25} {'Valuation':>12} {'Cash':>10} {'Revenue/q':>12} {'Employees':>10} {'Status':>12}")
    print(f"{'-'*3} {'-'*25} {'-'*12} {'-'*10} {'-'*12} {'-'*10} {'-'*12}")

    for i, c in enumerate(ranked, 1):
        val = f"${c.valuation_m:,.0f}M" if c.valuation_m > 0 else "N/A"
        delta = c.last_quarter_delta.get("valuation_change", 0)
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
        print(f"{i:>3} {c.name:<25} {val:>12} ${c.cash_m:,.0f}M   "
              f"${c.revenue_m_per_q:,.1f}M/q   {c.employees:>6}    {c.status:<12} {arrow}")

    print()

    # Segments
    print(f"  Market: Fed {ms.fed_rate}% | Sentiment: {ms.vc_sentiment} | Cycle: {ms.hype_cycle}")
    print(f"{'='*80}\n")


def print_events(ms: MarketState):
    """Print this quarter's events."""
    if not ms.events:
        return
    print(f"📰 {ms.headlines[-1] if ms.headlines else 'No headline'}")
    for ev in ms.events:
        agents = ", ".join(ev.get("agents_involved", []))
        print(f"  [{ev.get('type', 'event')}] {ev.get('description', '')} ({agents})")
    print()


# ── Main Runner ──────────────────────────────────────────────

def run_simulation(quarters: int = 4, output_file: str | None = None):
    """Run the Silicon Valley simulation for N quarters."""

    # Load scenario
    ms = load_scenario(str(REPO_ROOT / "scenarios" / "silicon-valley"))
    print(f"Loaded {len(ms.companies)} agents in {len(ms.market_segments)} market segments.\n")

    # Init LLM
    llm = LLMAdapter()

    if not llm.is_available:
        print("ERROR: No LLM API key configured. Set DEEPSEEK_API_KEY.")
        sys.exit(1)

    llm.set_room_context("valley_headless", 0, "silicon-valley", "en")
    print(f"LLM: {llm.provider_name}/{llm.model}\n")

    total_start = time.perf_counter()

    for q in range(1, quarters + 1):
        q_start = time.perf_counter()

        # Build context
        context = build_market_context(ms)
        messages = [
            {"role": "system", "content": SIMULATOR_PROMPT},
            {"role": "user", "content": context},
        ]

        # Call LLM
        print(f"🔄 Simulating Q{q}...", end=" ", flush=True)
        try:
            response = llm.chat(
                messages,
                temperature=0.7,
                max_tokens=65536,
                metadata={"category": "valley_sim", "quarter": q},
            )

            # Parse JSON
            result = _extract_json(response)

            # Apply
            ms = apply_llm_result(ms, result)

            elapsed = time.perf_counter() - q_start
            event_count = len(result.get("events", []))
            print(f"✅ {elapsed:.1f}s | {event_count} events | "
                  f"Headline: {result.get('headline', 'N/A')[:80]}")

            # Print events
            print_events(ms)

            # Every quarter, show leaderboard snapshot
            if q % 2 == 0 or q == quarters:
                print_leaderboard(ms, n=10)

        except Exception as e:
            elapsed = time.perf_counter() - q_start
            print(f"❌ FAILED ({elapsed:.1f}s): {e}")
            break

    total_elapsed = time.perf_counter() - total_start
    qcount = max(ms.quarter, 1)
    print(f"\n⏱️  Total: {total_elapsed:.1f}s for {qcount} quarters "
          f"({total_elapsed/qcount:.1f}s/quarter)")

    # Save final state
    if output_file:
        out_path = Path(output_file)
    else:
        out_path = REPO_ROOT / f"valley_state_q{ms.quarter}.json"

    out_path.write_text(json.dumps(ms.to_dict(), indent=2, ensure_ascii=False))
    print(f"💾 State saved to {out_path}")

    # Print final stats
    _print_final_stats(ms)

    return ms


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling truncation and malformed output."""
    import re

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try ```json ... ``` block
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try outermost { ... }
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try json_repair library (handles unescaped quotes, trailing commas, etc.)
    try:
        from json_repair import repair_json
        fixed = repair_json(text, return_objects=False)
        return json.loads(fixed)
    except Exception:
        pass

    # Handle truncated JSON: add closing brackets
    fixed = text.rstrip()
    open_braces = fixed.count('{') - fixed.count('}')
    open_brackets = fixed.count('[') - fixed.count(']')
    if open_braces > 0 or open_brackets > 0:
        print(f"  ⚠️  Closing {open_braces} braces, {open_brackets} brackets...")
        fixed += '}' * open_braces + ']' * open_brackets
        try:
            from json_repair import repair_json
            return json.loads(repair_json(fixed, return_objects=False))
        except Exception:
            pass

    raise ValueError(f"Could not parse JSON from LLM response. "
                     f"Length: {len(text)} chars. First 200: {text[:200]}... "
                     f"Last 200: ...{text[-200:]}")


def _print_final_stats(ms: MarketState):
    """Print end-of-simulation statistics."""
    active = ms.active_companies()
    bankrupt = [c for c in ms.companies.values() if c.status == "bankrupt"]
    acquired = [c for c in ms.companies.values() if c.status == "acquired"]
    public = [c for c in ms.companies.values() if c.status == "public"]

    print(f"\n{'='*60}")
    print(f"  📊 Simulation Summary ({ms.quarter} quarters)")
    print(f"{'='*60}")
    print(f"  Active companies:     {len(active)}")
    print(f"  Bankrupt:             {len(bankrupt)}")
    print(f"  Acquired:             {len(acquired)}")
    print(f"  Public (IPO):         {len(public)}")
    print(f"  Total deals:          {len(ms.contract_history)}")
    print(f"  Market pulse:         {ms.vc_sentiment} / {ms.hype_cycle}")
    print(f"  Fed rate:             {ms.fed_rate}%")
    print(f"{'='*60}")

    # Top 5 by growth
    print(f"\n  🚀 Top 5 by Valuation Growth:")
    growth = []
    for c in active:
        delta = c.last_quarter_delta.get("valuation_change", 0)
        growth.append((c, delta))
    growth.sort(key=lambda x: x[1], reverse=True)
    for c, d in growth[:5]:
        sign = "+" if d >= 0 else ""
        print(f"    {c.name:<25} {sign}${d:,.0f}M")

    print(f"\n  📉 Bottom 5 (Cash Runway):")
    runway_list = [(c, c.cash_runway_quarters()) for c in active]
    runway_list.sort(key=lambda x: x[1])
    for c, r in runway_list[:5]:
        print(f"    {c.name:<25} {r:.1f} quarters (${c.cash_m:,.0f}M)")

    # Segment winners
    print(f"\n  🏅 Segment Leaders:")
    for seg_id in ms.market_segments:
        best = max(active, key=lambda c: c.market_share.get(seg_id, 0), default=None)
        if best and best.market_share.get(seg_id, 0) > 0.05:
            print(f"    {seg_id:<25} {best.name} ({best.market_share.get(seg_id, 0)*100:.1f}%)")


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Silicon Valley Simulation Runner")
    parser.add_argument("--quarters", type=int, default=4, help="Number of quarters to simulate")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    run_simulation(quarters=args.quarters, output_file=args.output)
