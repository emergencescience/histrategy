"""
Tests for REST API server endpoints.

Uses FastAPI TestClient to call endpoints without starting a real server.
ImportError is caught at module level so tests skip gracefully when
fastapi is not installed (it's an optional dependency).

Note: /api/games/* endpoints removed in H27 (superseded by /api/single-player/*
and /api/rooms/* which are SQL-backed). See git log 57dd6ae for migration.
"""

from __future__ import annotations

import pytest

# Check optional dependency
try:
    from fastapi.testclient import TestClient
except ImportError:
    pytest.skip("fastapi not installed — pip install histrategy[web]", allow_module_level=True)  # noqa: DTZ003


@pytest.fixture
def client():
    """Create a fresh TestClient."""
    from histrategy.server.api import create_app

    app = create_app()
    return TestClient(app)


class TestHealth:
    """Health and root endpoints."""

    def test_root_returns_web_client(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # Root now serves the web client HTML page
        assert "text/html" in resp.headers.get("content-type", "")
        assert "三國志略" in resp.text

    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "llm" in resp.json()
        assert "engine" in resp.json()
        assert "db" in resp.json()


class TestStaticFiles:
    """Static file serving endpoints."""

    def test_manual_returns_html(self, client):
        resp = client.get("/manual")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_mp_returns_html(self, client):
        resp = client.get("/mp")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_css_file(self, client):
        resp = client.get("/css/main.css")
        assert resp.status_code in (200, 404)  # 404 if file missing is OK
