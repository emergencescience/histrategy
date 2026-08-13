"""Shared CLI utilities to eliminate duplication across app.py, dev_cli.py, headless_cli.py.

Extracted from the three CLI entry points during the 2025-06-18 cleanup scan.
"""

from __future__ import annotations

from ..llm.adapter import LLMAdapter, detect_provider
from ..llm.game_master import GameMaster


def is_v2_engine_available() -> bool:
    """Check if the histrategy-engine v2 (histrategy_engine) is installed."""
    try:
        from histrategy_engine import TurnController  # noqa: F401

        return True
    except ImportError:
        return False


def bootstrap_llm() -> tuple[LLMAdapter | None, dict]:
    """Detect the best available LLM provider and initialize the adapter.

    Returns:
        (llm_adapter, provider_info_dict)
        llm_adapter is None if no API key is configured (offline mode).
    """
    provider_info = detect_provider()
    llm = LLMAdapter() if provider_info.get("name") else None
    if llm:
        # Side-effect: GameMaster init validates LLM availability
        GameMaster(llm)
    return llm, provider_info


def parse_suggestions(suggestions: list[str]) -> list[dict]:
    """Parse LLM suggestion strings like '\u3010title\u3011description' or '[title] description'.

    Used by all three CLI files (was duplicated 6 times).
    """
    parsed: list[dict] = []
    for s in suggestions:
        for prefix, suffix in [("\u3010", "\u3011"), ("[", "]")]:
            if s.startswith(prefix) and suffix in s:
                parts = s.split(suffix, 1)
                parsed.append({"title": parts[0][len(prefix):], "description": parts[1].strip()})
                break
        else:
            parsed.append({"title": "", "description": s})
    return parsed


def format_llm_stats(llm: LLMAdapter) -> str:
    """Format LLM call statistics as a human-readable string.

    Returns empty string if no stats are available.
    """
    if not llm or not llm.last_call_stats:
        return ""
    stats = llm.last_call_stats
    parts = [
        f"Provider: {stats.get('provider', '?')}",
        f"Model: {stats.get('model', '?')}",
        f"Latency: {stats['latency']:.1f}s",
        f"Tokens: prompt={stats.get('prompt_tokens', 0):,} "
        f"completion={stats.get('completion_tokens', 0):,} "
        f"total={stats.get('total_tokens', 0):,}",
    ]
    if stats.get("reasoning_tokens", 0) > 0:
        parts.append(f"Reasoning: {stats['reasoning_tokens']:,}")
    return " | ".join(parts)
