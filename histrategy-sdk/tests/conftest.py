"""Test fixtures for histrategy-sdk integration tests.

Starts a local histrategy server in a background thread for multiplayer tests.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from pathlib import Path

import pytest


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server_thread(host: str, port: int, data_dir: str, api_key: str):
    """Start the histrategy server in a daemon thread (same process)."""
    os.environ["DEEPSEEK_API_KEY"] = api_key
    os.environ["HISTRATEGY_DATA_DIR"] = data_dir
    os.environ["HISTRATEGY_ENGINE"] = "v1"

    import logging
    logging.basicConfig(level=logging.ERROR)

    from histrategy.server.api import create_app
    import uvicorn

    app = create_app(llm_provider="deepseek")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@pytest.fixture(scope="session")
def histrategy_server():
    """Start a histrategy server for the test session.

    Sets HISTRATEGY_ENGINE=v1 and uses DEEPSEEK_API_KEY from environment.
    Uses a daemon thread (same process) for reliable env + threading.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # Try loading from .env file
        env_path = os.path.join(os.path.dirname(__file__), "../../../histrategy/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    val = val.strip().strip("'\"").strip()
                    os.environ[key] = val
            api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not set — skipping integration test")

    port = _find_free_port()
    host = "127.0.0.1"
    data_dir = os.path.join(
        os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy")),
        f"test-{uuid.uuid4().hex[:8]}",
    )

    # Start server in daemon thread (shares process, reliable env + threading)
    t = threading.Thread(
        target=_start_server_thread,
        args=(host, port, data_dir, api_key),
        daemon=True,
    )
    t.start()

    # Health-check the server
    import httpx
    base_url = f"http://{host}:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=5)
            if r.is_success:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        pytest.fail("Server did not become healthy within 30s")

    yield {"base_url": base_url, "host": host, "port": port, "data_dir": data_dir}

    # Cleanup test data dir
    import shutil
    data_path = Path(data_dir)
    if data_path.exists():
        shutil.rmtree(data_path, ignore_errors=True)


@pytest.fixture
def server_client(histrategy_server):
    """Create a ServerClient connected to the test server."""
    from histrategy_sdk import ServerClient

    return ServerClient(base_url=histrategy_server["base_url"], timeout=60)
