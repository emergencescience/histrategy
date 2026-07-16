"""
Tests for pre-compute intent cache system.

Covers:
- Cache store/get/clear operations
- TTL expiration
- World state hash invalidation
- Feature flag gating
- Command serialization/deserialization
- Precompute endpoint
"""

from __future__ import annotations

import os
import time
from unittest import mock

import pytest

# ═══════════════════════════════════════════════════════════════
# Cache operations
# ═══════════════════════════════════════════════════════════════


class TestIntentCache:
    """Tests for intent_cache module core operations."""

    def test_store_and_get(self):
        """Store a cached entry and retrieve it."""
        from histrategy.server.intent_cache import clear, get, store

        clear()  # Ensure clean state
        sid = "test_faction_t5_attack"
        commands = [{"type": "attack", "params": {"target_territory": "xinye"}, "faction_id": "cao", "notes": ""}]

        store(sid, commands, "room-1", 5, "cao")
        result = get(sid, "room-1", 5, "cao")
        assert result == commands

        clear()

    def test_cache_miss_nonexistent(self):
        """Retrieving a non-existent key returns None."""
        from histrategy.server.intent_cache import clear, get

        clear()
        result = get("nonexistent_sid", "room-1", 5, "cao")
        assert result is None

    def test_cache_miss_wrong_quarter(self):
        """Cache miss when quarter number differs (world state changed)."""
        from histrategy.server.intent_cache import clear, get, store

        clear()
        sid = "test_t5_defend"
        commands = [{"type": "defend", "params": {"territory": "xiapi"}, "faction_id": "cao", "notes": ""}]

        store(sid, commands, "room-1", 5, "cao")

        # Same room, same faction, different quarter → miss
        result = get(sid, "room-1", 6, "cao")
        assert result is None

        clear()

    def test_cache_miss_wrong_faction(self):
        """Cache miss when faction differs."""
        from histrategy.server.intent_cache import clear, get, store

        clear()
        sid = "test_t5_defend"
        commands = [{"type": "defend", "params": {"territory": "xiapi"}, "faction_id": "cao", "notes": ""}]

        store(sid, commands, "room-1", 5, "cao")

        # Different faction → miss
        result = get(sid, "room-1", 5, "shu")
        assert result is None

        clear()

    def test_clear_specific(self):
        """Clear a specific cache entry."""
        from histrategy.server.intent_cache import clear, get, store

        clear()
        sid = "test_t5_attack"
        commands = [{"type": "attack", "params": {"target_territory": "xinye"}, "faction_id": "cao", "notes": ""}]

        store(sid, commands, "room-1", 5, "cao")
        clear(sid)
        result = get(sid, "room-1", 5, "cao")
        assert result is None

    def test_clear_all(self):
        """Clear all cache entries."""
        from histrategy.server.intent_cache import clear, get, store

        clear()
        store("sid_1", [{"type": "attack"}], "room-1", 5, "cao")
        store("sid_2", [{"type": "defend"}], "room-1", 5, "cao")

        clear()  # clear all
        assert get("sid_1", "room-1", 5, "cao") is None
        assert get("sid_2", "room-1", 5, "cao") is None

    def test_cache_ttl_expiration(self, monkeypatch):
        """Cache entry should expire after TTL."""
        from histrategy.server.intent_cache import _CACHE_TTL, clear, get, store

        clear()
        # Set very short TTL for testing
        monkeypatch.setattr("histrategy.server.intent_cache._CACHE_TTL", 0)

        sid = "test_t5_attack"
        commands = [{"type": "attack", "params": {"target_territory": "xinye"}, "faction_id": "cao", "notes": ""}]

        store(sid, commands, "room-1", 5, "cao")
        # With TTL=0, it should expire immediately
        time.sleep(0.01)
        result = get(sid, "room-1", 5, "cao")
        assert result is None

        # Restore TTL
        monkeypatch.setattr("histrategy.server.intent_cache._CACHE_TTL", _CACHE_TTL)
        clear()


# ═══════════════════════════════════════════════════════════════
# Feature flag
# ═══════════════════════════════════════════════════════════════


class TestFeatureFlag:
    """Tests for HISTRATEGY_PRECOMPUTE_INTENT feature flag."""

    def test_feature_disabled_by_default(self):
        """Feature should be disabled when env var is not set."""
        from histrategy.server.intent_cache import _feature_enabled

        # Ensure env var is not set
        with mock.patch.dict(os.environ, {}, clear=True):
            assert not _feature_enabled()

    def test_feature_enabled_with_true(self):
        """Feature should be enabled when env var is 'true'."""
        with mock.patch.dict(os.environ, {"HISTRATEGY_PRECOMPUTE_INTENT": "true"}):
            from histrategy.server.intent_cache import _feature_enabled

            assert _feature_enabled()

    def test_feature_enabled_with_1(self):
        """Feature should be enabled when env var is '1'."""
        with mock.patch.dict(os.environ, {"HISTRATEGY_PRECOMPUTE_INTENT": "1"}):
            from histrategy.server.intent_cache import _feature_enabled

            assert _feature_enabled()

    def test_feature_disabled_with_false(self):
        """Feature should be disabled when env var is 'false'."""
        with mock.patch.dict(os.environ, {"HISTRATEGY_PRECOMPUTE_INTENT": "false"}):
            from histrategy.server.intent_cache import _feature_enabled

            assert not _feature_enabled()


# ═══════════════════════════════════════════════════════════════
# Serialization
# ═══════════════════════════════════════════════════════════════


class TestSerialization:
    """Tests for command serialization/deserialization."""

    def test_serialize_dict_commands(self):
        """Serialize command dicts."""
        from histrategy.server.intent_cache import _serialize_commands

        commands = [
            {"type": "attack", "params": {"target_territory": "xinye"}, "faction_id": "cao", "notes": "进攻"},
        ]
        result = _serialize_commands(commands)
        assert result == commands

    def test_serialize_command_objects(self):
        """Serialize Command dataclass objects."""
        from histrategy_engine.world import Command

        from histrategy.server.intent_cache import _serialize_commands

        commands = [
            Command(
                type="attack",
                params={"target_territory": "xinye"},
                faction_id="cao",
                notes="进攻新野",
            ),
        ]
        result = _serialize_commands(commands)
        assert len(result) == 1
        assert result[0]["type"] == "attack"
        assert result[0]["params"]["target_territory"] == "xinye"
        assert result[0]["notes"] == "进攻新野"

    def test_get_returns_raw_dicts(self):
        """get() returns raw dicts (no Command deserialization)."""
        from histrategy.server.intent_cache import get, store, clear

        try:
            data = [
                {"type": "defend", "params": {"territory": "xiapi"}, "faction_id": "cao", "notes": "防守"},
            ]
            store("sid-dict-test", data, "room-1", 1, "cao")
            cached = get("sid-dict-test", "room-1", 1, "cao")
            assert cached is not None
            assert isinstance(cached, list)
            assert cached[0]["type"] == "defend"
            assert cached[0]["params"]["territory"] == "xiapi"
            assert cached[0]["notes"] == "防守"
        finally:
            clear("sid-dict-test")

    def test_roundtrip_serialize_only(self):
        """Serialize preserves data — get() returns raw dicts."""
        from histrategy_engine.world import Command

        from histrategy.server.intent_cache import _serialize_commands

        original = [
            Command(
                type="recruit",
                params={"territory": "xuchang", "unit_type": "cavalry", "amount": 10000},
                faction_id="cao",
                notes="招募骑兵",
            ),
        ]
        serialized = _serialize_commands(original)
        assert len(serialized) == 1
        assert serialized[0]["type"] == original[0].type
        assert serialized[0]["params"] == original[0].params


# ═══════════════════════════════════════════════════════════════
# Precompute endpoint
# ═══════════════════════════════════════════════════════════════


class TestPrecomputeEndpoint:
    """Tests for /api/intent/precompute endpoint."""

    @pytest.fixture
    def client(self):
        """Create a fresh TestClient."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not installed")

        from histrategy.server.api import create_app

        app = create_app()
        return TestClient(app)

    def test_precompute_missing_params(self, client):
        """Precompute returns error when required params are missing."""
        resp = client.post("/api/intent/precompute", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert not data["ok"]
        assert "suggestion_id" in data["error"]

    def test_precompute_disabled_by_default(self, client):
        """Precompute returns feature_disabled when flag is off."""
        resp = client.post("/api/intent/precompute", json={
            "suggestion_id": "cao_t5_attack",
            "command_text": "进攻新野",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert data["reason"] == "feature_disabled"
        assert not data["cached"]

    def test_precompute_enabled(self, client, monkeypatch):
        """Precompute returns precomputing status when flag is on."""
        monkeypatch.setenv("HISTRATEGY_PRECOMPUTE_INTENT", "true")

        resp = client.post("/api/intent/precompute", json={
            "suggestion_id": "cao_t5_attack",
            "command_text": "进攻新野",
            "game_id": "test-room",
            "faction_id": "cao",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert data["reason"] == "precomputing"
        assert not data["cached"]
