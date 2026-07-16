"""
Pre-compute Intent Cache — asynchronous intent_parse for strategic suggestions.

After the "军师献策" (Strategic Advisor) finishes streaming, the frontend fires
async precompute requests for all 3 strategies (上中下策). When the user clicks
a suggestion, the /command endpoint uses the cached result for instant execution
instead of waiting 2-3s for synchronous intent_parse.

Cache key: suggestion_id (unique per suggestion).
Cache value: {parsed_commands, world_state_hash, expires_at}.

Feature flag: HISTRATEGY_PRECOMPUTE_INTENT=true (disabled by default).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time

logger = logging.getLogger("histrategy.intent_cache")

# ── Module-level in-memory cache ──────────────────────────────────

_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()

# TTL in seconds (5 minutes)
_CACHE_TTL = int(os.environ.get("HISTRATEGY_PRECOMPUTE_CACHE_TTL", "300"))


def _feature_enabled() -> bool:
    """Check if precompute intent feature is enabled."""
    return os.environ.get("HISTRATEGY_PRECOMPUTE_INTENT", "").strip() in (
        "1", "true", "True", "yes",
    )


def _compute_world_state_hash(room_id: str, quarter_number: int, faction_id: str) -> str:
    """Compute a deterministic world-state hash for cache invalidation.

    Uses room_id + quarter_number + faction_id as a proxy for world state.
    The cache is invalidated when the quarter advances.
    """
    payload = f"{room_id}:{quarter_number}:{faction_id}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def store(suggestion_id: str, commands: list, room_id: str, quarter_number: int, faction_id: str) -> None:
    """Store pre-computed intent_parse result in cache.

    Args:
        suggestion_id: Unique ID for this suggestion.
        commands: Parsed Command objects (list of dicts serializable).
        room_id: Room identifier.
        quarter_number: Current quarter number at time of precompute.
        faction_id: Player faction ID.
    """
    world_state_hash = _compute_world_state_hash(room_id, quarter_number, faction_id)
    entry = {
        "commands": commands,
        "world_state_hash": world_state_hash,
        "expires_at": time.time() + _CACHE_TTL,
    }
    with _CACHE_LOCK:
        _CACHE[suggestion_id] = entry
        logger.debug("Intent cache stored: sid=%s hash=%s", suggestion_id, world_state_hash)


def get(suggestion_id: str, room_id: str, quarter_number: int, faction_id: str) -> list | None:
    """Retrieve cached intent_parse result if valid.

    Returns parsed commands list, or None if cache miss / expired / state mismatch.

    Args:
        suggestion_id: Unique ID for this suggestion.
        room_id: Room identifier.
        quarter_number: Current quarter number.
        faction_id: Player faction ID.

    Returns:
        List of parsed Command dicts, or None.
    """
    with _CACHE_LOCK:
        entry = _CACHE.get(suggestion_id)
        if entry is None:
            return None

        # Check TTL
        if time.time() > entry["expires_at"]:
            del _CACHE[suggestion_id]
            return None

        # Check world state hash match
        current_hash = _compute_world_state_hash(room_id, quarter_number, faction_id)
        if entry["world_state_hash"] != current_hash:
            del _CACHE[suggestion_id]
            return None

        return entry["commands"]


def clear(suggestion_id: str | None = None) -> None:
    """Clear cache entries.

    Args:
        suggestion_id: Clear specific entry. If None, clear all.
    """
    with _CACHE_LOCK:
        if suggestion_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(suggestion_id, None)


def _serialize_commands(commands: list) -> list[dict]:
    """Convert Command objects to serializable dicts."""
    result = []
    for cmd in commands:
        if hasattr(cmd, "to_dict"):
            result.append(cmd.to_dict())
        elif isinstance(cmd, dict):
            result.append(cmd)
        else:
            # Fallback: extract attributes
            result.append({
                "type": getattr(cmd, "type", ""),
                "params": getattr(cmd, "params", {}),
                "faction_id": getattr(cmd, "faction_id", ""),
                "notes": getattr(cmd, "notes", ""),
            })
    return result


def _deserialize_commands(data: list[dict]) -> list:
    """Convert dicts back to Command objects."""
    from histrategy_engine.world import Command

    result = []
    for item in data:
        result.append(Command(
            type=item.get("type", ""),
            params=item.get("params", {}),
            faction_id=item.get("faction_id", ""),
            notes=item.get("notes", ""),
        ))
    return result


def precompute_and_cache(
    suggestion_id: str,
    command_text: str,
    faction_id: str,
    room_id: str,
    quarter_number: int,
    llm_adapter=None,
) -> None:
    """Run intent_parse in background and cache the result.

    This is the fire-and-forget entry point called from the precompute endpoint.
    It spawns a daemon thread to avoid blocking the response.

    Args:
        suggestion_id: Unique suggestion identifier.
        command_text: The natural-language command text to parse.
        faction_id: Player faction ID.
        room_id: Room identifier.
        quarter_number: Current quarter number.
        llm_adapter: LLM adapter for intent parsing. If None, uses keyword fallback.
    """
    if not _feature_enabled():
        return

    def _worker():
        _t0 = time.time()
        try:
            from histrategy.parser.intent import IntentParser

            parser = IntentParser(llm_adapter)
            commands = parser.parse(command_text, faction_id)
            serialized = _serialize_commands(commands)
            store(suggestion_id, serialized, room_id, quarter_number, faction_id)
            elapsed = time.time() - _t0
            logger.info(
                "Intent precompute cached: sid=%s cmds=%d t=%.1fs",
                suggestion_id, len(serialized), elapsed,
            )
        except Exception as e:
            logger.warning("Intent precompute failed: sid=%s err=%s", suggestion_id, e)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
