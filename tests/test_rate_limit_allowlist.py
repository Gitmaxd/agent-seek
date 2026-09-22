"""IP allowlist skips burst + demo quota."""
from __future__ import annotations

import apps.api.config as config_mod
from apps.api.config import get_settings, is_rate_limit_allowlisted, rate_limit_allowlist
from apps.api.rate_limit import demo_quota, limiter


def test_allowlist_parse(monkeypatch):
    monkeypatch.setenv("AGENT_SEEK_RATE_LIMIT_ALLOWLIST", "136.63.82.70, 203.0.113.1")
    get_settings.cache_clear()
    assert rate_limit_allowlist() == {"136.63.82.70", "203.0.113.1"}
    assert is_rate_limit_allowlisted("136.63.82.70") is True
    assert is_rate_limit_allowlisted("1.2.3.4") is False
    get_settings.cache_clear()


async def test_allowlisted_ip_skips_demo_consume(monkeypatch):
    monkeypatch.setenv("AGENT_SEEK_RATE_LIMIT_ALLOWLIST", "136.63.82.70")
    get_settings.cache_clear()
    demo_quota.configure(backend=limiter, limit=5, mode="enabled")
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("Upstash should not be called for allowlisted IP")

    monkeypatch.setattr(limiter, "_pipeline", boom)
    limiter.configure(url="https://example.upstash.io", token="t", limit_per_min=60)
    remaining = await demo_quota.consume("136.63.82.70")
    assert remaining == 5
    assert calls["n"] == 0
    demo_quota.configure(backend=limiter, limit=0, mode=False)
    get_settings.cache_clear()
