"""Optional Upstash IP rate limiting — mocked Redis, no live account."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.config import get_settings
from apps.api.rate_limit import (
    RateLimitBackendError,
    RateLimiter,
    client_ip,
    configure_limiter_from_settings,
    demo_quota,
    limiter,
    rate_limit_dep,
)
from packages.core.models import RankedResult, SearchMeta, SearchResponse
from packages.core.pipeline import AGENT_SEEK_VERSION

get_settings.cache_clear()

from apps.api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.configure(url="", token="", limit_per_min=60)
    limiter._http = None
    demo_quota.configure(backend=limiter, limit=0, mode=False)
    yield
    limiter.configure(url="", token="", limit_per_min=60)
    limiter._http = None
    demo_quota.configure(backend=limiter, limit=0, mode=False)


def _scope(headers: dict[str, str] | None = None, client_host: str = "127.0.0.1") -> dict:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/search",
        "raw_path": b"/v1/search",
        "query_string": b"",
        "headers": raw,
        "client": (client_host, 12345),
        "server": ("testserver", 80),
    }


def _request(headers: dict[str, str] | None = None, client_host: str = "127.0.0.1") -> Request:
    return Request(_scope(headers, client_host))


def _ok_pipeline(count: int) -> list[dict]:
    return [{"result": 0}, {"result": 1}, {"result": count}, {"result": 1}]


def _fake_search(q: str = "rate") -> SearchResponse:
    return SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url="https://example.com",
                title="Example",
                snippet="hi",
                score=0.9,
                flags=["on_topic"],
                raw_rank=1,
                provider="you.com",
            )
        ],
        meta=SearchMeta(
            q=q,
            candidates_in=1,
            kept=1,
            latency_ms=4,
            ranking="jev",
            agent_seek_version=AGENT_SEEK_VERSION,
        ),
        raw_results=[],
    )


def test_disabled_when_url_or_token_missing():
    empty = RateLimiter()
    empty.configure(url="", token="", limit_per_min=60)
    assert empty.enabled is False
    empty.configure(url="https://example.upstash.io", token="", limit_per_min=60)
    assert empty.enabled is False
    empty.configure(url="", token="tok", limit_per_min=60)
    assert empty.enabled is False
    empty.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    assert empty.enabled is True


def test_settings_reads_upstash_env(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "upstash-test-token")
    monkeypatch.setenv("AGENT_SEEK_RATE_LIMIT_PER_MIN", "120")
    monkeypatch.setenv("AGENT_SEEK_DEMO_SEARCH_LIMIT", "5")
    monkeypatch.delenv("AGENT_SEEK_DEMO_MODE", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.upstash_redis_rest_url == "https://example.upstash.io"
    assert s.upstash_redis_rest_token == "upstash-test-token"
    assert s.agent_seek_rate_limit_per_min == 120
    assert s.agent_seek_demo_search_limit == 5
    assert s.agent_seek_demo_mode.lower() == "disabled"
    configure_limiter_from_settings()
    assert limiter.enabled is True
    assert limiter.limit == 120
    assert demo_quota.enabled is False
    assert demo_quota.limit == 5
    monkeypatch.setenv("AGENT_SEEK_DEMO_MODE", "ENABLED")
    get_settings.cache_clear()
    configure_limiter_from_settings()
    assert demo_quota.enabled is True
    get_settings.cache_clear()


def test_env_example_documents_opt_in_vars():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "UPSTASH_REDIS_REST_URL" in text
    assert "UPSTASH_REDIS_REST_TOKEN" in text
    assert "AGENT_SEEK_RATE_LIMIT_PER_MIN" in text
    assert "AGENT_SEEK_DEMO_SEARCH_LIMIT" in text
    assert "AGENT_SEEK_DEMO_MODE" in text
    assert "DEMO_EXHAUSTED" in text
    assert "search_web" in text
    assert "shared" in text
    assert "never MCP" not in text
    assert "disabled" in text
    assert "rightmost public hop" in text


def test_client_ip_rightmost_public_xff_hop_not_spoofed_leftmost():
    req = _request(
        {
            "X-Forwarded-For": "9.9.9.9, 8.8.8.8",
            "X-Real-IP": "1.1.1.1",
        },
        client_host="192.168.1.9",
    )
    assert client_ip(req) == "8.8.8.8"


def test_client_ip_single_public_xff_hop():
    req = _request(
        {
            "X-Forwarded-For": "8.8.8.8",
            "X-Real-IP": "1.1.1.1",
        },
        client_host="192.168.1.9",
    )
    assert client_ip(req) == "8.8.8.8"


def test_client_ip_private_xff_then_rightmost_public():
    req = _request(
        {
            "X-Forwarded-For": "10.0.0.2, 8.8.8.8, 10.1.1.1",
            "X-Real-IP": "1.1.1.1",
        },
        client_host="192.168.1.9",
    )
    assert client_ip(req) == "8.8.8.8"


def test_client_ip_falls_back_to_real_ip_then_socket():
    real = _request({"X-Real-IP": "1.1.1.1"}, client_host="10.0.0.8")
    assert client_ip(real) == "1.1.1.1"
    local = _request(client_host="127.0.0.1")
    assert client_ip(local) == "127.0.0.1"


async def test_check_disabled_skips_redis():
    limiter.configure(url="", token="", limit_per_min=60)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        remaining, reset = await limiter.check("8.8.8.8")
    pipe.assert_not_called()
    assert remaining == 60
    assert reset > 0


async def test_check_allows_under_limit():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=3)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(2)
        remaining, _reset = await limiter.check("8.8.4.4")
    assert remaining == 1
    pipe.assert_awaited_once()


async def test_check_429_over_limit():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=2)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(3)
        with pytest.raises(HTTPException) as exc:
            await limiter.check("1.1.1.1")
    assert exc.value.status_code == 429
    assert exc.value.detail == "Rate limit exceeded"
    assert exc.value.headers["Retry-After"] == "60"
    assert "RateLimit" in exc.value.headers
    assert "RateLimit-Policy" in exc.value.headers


async def test_check_fail_closed_on_redis_error():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = RateLimitBackendError("timeout")
        with pytest.raises(HTTPException) as exc:
            await limiter.check("1.0.0.1")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Rate limiter unavailable"


async def test_upstash_rest_pipeline_shape():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_pipeline(1))

    limiter.configure(url="https://example.upstash.io/", token="secret-token", limit_per_min=10)
    limiter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)
    try:
        remaining, _reset = await limiter.check("93.184.216.34")
    finally:
        await limiter._http.aclose()
        limiter._http = None
    assert remaining == 9
    assert seen["url"] == "https://example.upstash.io/pipeline"
    assert seen["auth"] == "Bearer secret-token"
    body = seen["body"]
    assert isinstance(body, list)
    assert body[0][0] == "ZREMRANGEBYSCORE"
    assert body[1][0] == "ZADD"
    assert body[2][0] == "ZCARD"
    assert body[3][0] == "PEXPIRE"
    assert str(body[0][1]).startswith("agent-seek:rl:ip:93.184.216.34")


async def test_upstash_http_error_fail_closed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "backend down"})

    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=10)
    limiter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)
    try:
        with pytest.raises(HTTPException) as exc:
            await limiter.check("4.4.4.4")
    finally:
        await limiter._http.aclose()
        limiter._http = None
    assert exc.value.status_code == 503


async def test_identity_is_client_ip_not_api_key():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=10)
    keys: list[str] = []

    async def capture(commands):
        keys.append(str(commands[0][1]))
        return _ok_pipeline(1)

    with patch.object(limiter, "_pipeline", side_effect=capture):
        await rate_limit_dep(
            _request(
                {"Authorization": "Bearer key-aaaa", "X-Forwarded-For": "8.8.8.8"},
            )
        )
        await rate_limit_dep(
            _request(
                {"Authorization": "Bearer key-bbbb", "X-Forwarded-For": "8.8.8.8"},
            )
        )
    assert keys[0] == keys[1]
    assert keys[0].endswith("8.8.8.8")


async def test_rate_limit_dep_sets_state_when_disabled():
    limiter.configure(url="", token="", limit_per_min=60)
    req = _request(client_host="testclient")
    await rate_limit_dep(req)
    info = req.state.rate_limit
    assert info["limit"] == 60
    assert info["remaining"] == 60


def test_search_disabled_does_not_call_redis():
    limiter.configure(url="", token="", limit_per_min=1)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        with patch("apps.api.main._pipeline") as gp:
            fake = _fake_search()
            gp.return_value = AsyncMock(search=AsyncMock(return_value=fake))
            r = client.post(
                "/v1/search",
                json={"q": "unlimited local"},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
    assert r.status_code == 200
    pipe.assert_not_called()


def test_search_429_over_limit_problem_json():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=1)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(2)
        r = client.post(
            "/v1/search",
            json={"q": "too many"},
            headers={
                "Authorization": "Bearer test-agent-seek-key",
                "X-Forwarded-For": "1.2.3.4",
            },
        )
    assert r.status_code == 429
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    body = r.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in r.headers
    assert "RateLimit" in r.headers
    assert "RateLimit-Policy" in r.headers


def test_search_fail_closed_503_problem_json():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = RateLimitBackendError("connect")
        r = client.post(
            "/v1/search",
            json={"q": "redis down"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 503
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    body = r.json()
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["message"] == "Rate limiter unavailable"


def test_health_and_sandbox_not_throttled_when_enabled():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=1)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        health = client.get("/health")
        sandbox = client.get("/v1/sandbox")
        well_known = client.get("/.well-known/mcp/server-card.json")
    assert health.status_code == 200
    assert sandbox.status_code == 200
    assert well_known.status_code == 200
    pipe.assert_not_called()


def test_mcp_search_web_over_limit():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=1)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(4)
        r = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test-agent-seek-key",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "search_web", "arguments": {"q": "mcp limit"}},
            },
        )
    assert r.status_code == 200
    err = r.json()["error"]
    assert err["code"] == -32000
    assert err["data"]["status_code"] == 429
    assert "Rate limit exceeded" in err["message"]
