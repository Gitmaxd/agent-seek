"""v0.1.14: AGENT_SEEK_* only — no SIEVE_* fallback."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_settings():
    from apps.api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_ignores_sieve_api_key(monkeypatch):
    monkeypatch.delenv("AGENT_SEEK_API_KEY", raising=False)
    monkeypatch.setenv("SIEVE_API_KEY", "legacy-must-not-apply")
    from apps.api.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.agent_seek_api_key != "legacy-must-not-apply"


def test_settings_reads_agent_seek_api_key(monkeypatch):
    monkeypatch.setenv("AGENT_SEEK_API_KEY", "fresh-agent-seek-key")
    monkeypatch.setenv("SIEVE_API_KEY", "legacy-must-not-apply")
    from apps.api.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.agent_seek_api_key == "fresh-agent-seek-key"
