"""Test configuration — disable LLM during unit tests."""
import os
import pytest


@pytest.fixture(autouse=True)
def disable_llm_in_tests(monkeypatch):
    """Ensure all tests use offline keyword fallback, not real LLM calls."""
    # Unset any API keys that might activate LLM
    for key in list(os.environ):
        if key.endswith("_API_KEY") and key != "EMERGENCE_API_KEY_SYMBOLSCIENCE":
            monkeypatch.delenv(key, raising=False)
    # Reset the LLM singleton
    import histrategy_agent.llm_adapter as llm_mod
    llm_mod._llm_client = None
