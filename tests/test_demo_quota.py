"""Lifetime website demo quota — mocked Upstash. REST and MCP search_web share it."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.config import get_settings, is_demo_mode_enabled
from apps.api.rate_limit import (
    DEMO_EXHAUSTED_DETAIL,
    DEMO_REDIS_KEY_PREFIX,
    RateLimitBackendError,
    demo_quota,
    limiter,
)
from packages.core.models import RankedResult, SearchMeta, SearchResponse
from packages.core.pipeline import AGENT_SEEK_VERSION

get_settings.cache_clear()

from apps.api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_quota():
    limiter.configure(url="", token="", limit_per_min=60)
    limiter._http = None
    demo_quota.configure(backend=limiter, limit=0, mode=False)
    yield
    limiter.configure(url="", token="", limit_per_min=60)
    limiter._http = None
    demo_quota.configure(backend=limiter, limit=0, mode=False)


def _ok_pipeline(count: int) -> list[dict]:
    return [{"result": 0}, {"result": 1}, {"result": count}, {"result": 1}]


def _fake_search(q: str = "demo") -> SearchResponse:
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


def _enable_demo(*, limit: int = 5, burst: int = 60, mode: str | bool = "enabled") -> None:
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=burst)
    demo_quota.configure(backend=limiter, limit=limit, mode=mode)


def test_is_demo_mode_enabled_case_insensitive():
    assert is_demo_mode_enabled("enabled") is True
    assert is_demo_mode_enabled("ENABLED") is True
    assert is_demo_mode_enabled(" Enabled ") is True
    assert is_demo_mode_enabled("disabled") is False
    assert is_demo_mode_enabled("") is False
    assert is_demo_mode_enabled("on") is False
    assert is_demo_mode_enabled(True) is True
    assert is_demo_mode_enabled(False) is False


def test_disabled_when_mode_off_limit_zero_or_upstash_missing():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="disabled")
    assert demo_quota.enabled is False

    demo_quota.configure(backend=limiter, limit=5, mode="ENABLED")
    assert demo_quota.enabled is True

    demo_quota.configure(backend=limiter, limit=0, mode="enabled")
    assert demo_quota.enabled is False

    limiter.configure(url="", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="enabled")
    assert demo_quota.enabled is False

    limiter.configure(url="https://example.upstash.io", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="enabled")
    assert demo_quota.enabled is False

    _enable_demo(limit=5)
    assert demo_quota.enabled is True


def test_demo_mode_default_disabled_skips_incr_on_rest():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="disabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(1)
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search()))
            r = client.post(
                "/v1/search",
                json={"q": "demo mode off"},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
    assert r.status_code == 200
    for call in pipe.await_args_list:
        assert call.args[0][0][0] != "INCR"


async def test_consume_disabled_skips_redis():
    demo_quota.configure(backend=limiter, limit=0, mode=False)
    limiter.configure(url="", token="", limit_per_min=60)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        remaining = await demo_quota.consume("8.8.8.8")
    pipe.assert_not_called()
    assert remaining == 0


async def test_consume_allows_under_limit():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = [{"result": 3}]
        remaining = await demo_quota.consume("8.8.4.4")
    assert remaining == 2
    pipe.assert_awaited_once()
    assert pipe.await_args.args[0] == [["INCR", f"{DEMO_REDIS_KEY_PREFIX}8.8.4.4"]]


async def test_consume_fifth_search_allowed_sixth_exhausted():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = [{"result": 5}]
        remaining = await demo_quota.consume("1.1.1.1")
    assert remaining == 0

    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = [{"result": 6}]
        with pytest.raises(HTTPException) as exc:
            await demo_quota.consume("1.1.1.1")
    assert exc.value.status_code == 429
    assert exc.value.detail == DEMO_EXHAUSTED_DETAIL
    assert not (exc.value.headers or {}).get("Retry-After")


async def test_consume_fail_closed_on_redis_error():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = RateLimitBackendError("timeout")
        with pytest.raises(HTTPException) as exc:
            await demo_quota.consume("1.0.0.1")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Rate limiter unavailable"


def _incr_calls(pipe) -> list:
    out = []
    for call in pipe.await_args_list:
        cmd = call.args[0][0]
        if str(cmd[0]) == "INCR":
            out.append(cmd)
    return out


def test_invalid_search_422_does_not_consume_demo_quota():
    _enable_demo(limit=5)
    with patch.object(demo_quota, "consume", new_callable=AsyncMock) as consume:
        with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
            pipe.return_value = _ok_pipeline(1)
            empty_q = client.post(
                "/v1/search",
                json={"q": ""},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
            bad_k = client.post(
                "/v1/search",
                json={"q": "valid query", "k": 0},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
            missing = client.post(
                "/v1/search",
                json={},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
    assert empty_q.status_code == 422
    assert bad_k.status_code == 422
    assert missing.status_code == 422
    consume.assert_not_called()
    assert _incr_calls(pipe) == []


def test_valid_search_consumes_demo_quota_after_validation():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = [_ok_pipeline(1), [{"result": 1}]]
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search()))
            r = client.post(
                "/v1/search",
                json={"q": "validated search"},
                headers={
                    "Authorization": "Bearer test-agent-seek-key",
                    "X-Forwarded-For": "5.5.5.5",
                },
            )
    assert r.status_code == 200
    incr = _incr_calls(pipe)
    assert len(incr) == 1
    assert incr[0][1] == f"{DEMO_REDIS_KEY_PREFIX}5.5.5.5"


def test_search_under_limit_allows():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = [_ok_pipeline(1), [{"result": 2}]]
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search()))
            r = client.post(
                "/v1/search",
                json={"q": "still allowed"},
                headers={
                    "Authorization": "Bearer test-agent-seek-key",
                    "X-Forwarded-For": "1.2.3.4",
                },
            )
    assert r.status_code == 200
    assert pipe.await_count == 2
    incr = pipe.await_args_list[1].args[0]
    assert incr[0][0] == "INCR"
    assert incr[0][1] == f"{DEMO_REDIS_KEY_PREFIX}1.2.3.4"


def test_search_over_limit_429_demo_exhausted_no_retry_after():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = [_ok_pipeline(1), [{"result": 6}]]
        r = client.post(
            "/v1/search",
            json={"q": "sixth try"},
            headers={
                "Authorization": "Bearer test-agent-seek-key",
                "X-Forwarded-For": "9.9.9.9",
            },
        )
    assert r.status_code == 429
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    body = r.json()
    assert body["code"] == "DEMO_EXHAUSTED"
    assert body["error"]["code"] == "DEMO_EXHAUSTED"
    assert "used up" in body["message"].lower()
    assert "retry-after" not in {k.lower() for k in r.headers}


def test_search_alias_over_limit_demo_exhausted():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.side_effect = [_ok_pipeline(1), [{"result": 7}]]
        r = client.post(
            "/api/v1/search",
            json={"q": "alias sixth"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 429
    assert r.json()["code"] == "DEMO_EXHAUSTED"


def test_search_disabled_limit_zero_does_not_incr():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=0, mode="enabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(1)
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search()))
            r = client.post(
                "/v1/search",
                json={"q": "quota off"},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
    assert r.status_code == 200
    for call in pipe.await_args_list:
        assert call.args[0][0][0] != "INCR"


def test_unauthenticated_search_does_not_consume_demo():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        r = client.post(
            "/v1/search",
            json={"q": "no key"},
            headers={"X-Forwarded-For": "2.2.2.2"},
        )
    assert r.status_code == 401
    for call in pipe.await_args_list:
        assert call.args[0][0][0] != "INCR"


def test_search_disabled_without_upstash_does_not_incr():
    limiter.configure(url="", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="enabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search()))
            r = client.post(
                "/v1/search",
                json={"q": "local unlimited"},
                headers={"Authorization": "Bearer test-agent-seek-key"},
            )
    assert r.status_code == 200
    pipe.assert_not_called()


def _mcp_tools_call(
    name: str,
    arguments: dict | None = None,
    *,
    ip: str = "8.8.8.8",
    auth: bool = True,
    rpc_id: int = 11,
):
    headers = {
        "Accept": "application/json, text/event-stream",
        "X-Forwarded-For": ip,
    }
    if auth:
        headers["Authorization"] = "Bearer test-agent-seek-key"
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )


def _shared_counter(ip: str):
    counts = {"n": 0}

    async def fake_pipeline(commands):
        op = str(commands[0][0])
        if op == "INCR":
            assert str(commands[0][1]) == f"{DEMO_REDIS_KEY_PREFIX}{ip}"
            counts["n"] += 1
            return [{"result": counts["n"]}]
        return _ok_pipeline(1)

    return counts, fake_pipeline


def test_mcp_and_rest_share_demo_counter():
    ip = "8.8.8.8"
    _enable_demo(limit=5)
    counts, fake_pipeline = _shared_counter(ip)
    search = AsyncMock(return_value=_fake_search("shared"))
    headers = {
        "Authorization": "Bearer test-agent-seek-key",
        "X-Forwarded-For": ip,
    }
    with patch.object(limiter, "_pipeline", side_effect=fake_pipeline):
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=search)
            for i in range(4):
                rest = client.post("/v1/search", json={"q": f"rest {i}"}, headers=headers)
                assert rest.status_code == 200
            fifth = _mcp_tools_call("search_web", {"q": "fifth via mcp"}, ip=ip)
            assert fifth.status_code == 200
            assert "error" not in fifth.json()
            assert search.await_count == 5
            exhausted = _mcp_tools_call("search_web", {"q": "sixth via mcp"}, ip=ip, rpc_id=12)
            still = client.post("/v1/search", json={"q": "seventh via rest"}, headers=headers)
    assert counts["n"] == 7
    assert search.await_count == 5
    assert exhausted.status_code == 429
    assert "application/problem+json" in (exhausted.headers.get("content-type") or "")
    body = exhausted.json()
    assert body["code"] == "DEMO_EXHAUSTED"
    assert body["error"]["code"] == "DEMO_EXHAUSTED"
    assert "retry-after" not in {k.lower() for k in exhausted.headers}
    assert still.status_code == 429
    assert still.json()["code"] == "DEMO_EXHAUSTED"
    assert "retry-after" not in {k.lower() for k in still.headers}


def test_mcp_search_web_skips_demo_quota_when_disabled():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="disabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(1)
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search("mcp")))
            r = _mcp_tools_call("search_web", {"q": "demo mode off"})
    assert r.status_code == 200
    assert "error" not in r.json()
    assert _incr_calls(pipe) == []


def test_mcp_search_web_skips_demo_quota_when_limit_zero_or_no_upstash():
    limiter.configure(url="https://example.upstash.io", token="tok", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=0, mode="enabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(1)
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search("mcp")))
            zero = _mcp_tools_call("search_web", {"q": "limit zero"})
    assert zero.status_code == 200
    assert _incr_calls(pipe) == []

    limiter.configure(url="", token="", limit_per_min=60)
    demo_quota.configure(backend=limiter, limit=5, mode="enabled")
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        with patch("apps.api.main._pipeline") as gp:
            gp.return_value = AsyncMock(search=AsyncMock(return_value=_fake_search("mcp")))
            local = _mcp_tools_call("search_web", {"q": "no upstash"})
    assert local.status_code == 200
    pipe.assert_not_called()


def test_mcp_helpers_unauth_and_invalid_do_not_consume_demo_quota():
    _enable_demo(limit=5)
    with patch.object(limiter, "_pipeline", new_callable=AsyncMock) as pipe:
        pipe.return_value = _ok_pipeline(1)
        with patch("apps.api.main._pipeline") as gp:
            search = AsyncMock(return_value=_fake_search("mcp"))
            gp.return_value = AsyncMock(search=search)
            health = _mcp_tools_call("get_service_health", {}, auth=False)
            docs = _mcp_tools_call("get_api_docs", {"topic": "mcp"}, auth=False, rpc_id=12)
            caps = _mcp_tools_call("list_search_capabilities", {}, auth=False, rpc_id=13)
            unauth = _mcp_tools_call("search_web", {"q": "no key"}, auth=False, rpc_id=14)
            empty = _mcp_tools_call("search_web", {"q": ""}, rpc_id=15)
    assert health.status_code == 200
    assert docs.status_code == 200
    assert caps.status_code == 200
    assert "error" not in health.json()
    assert unauth.status_code == 200
    assert unauth.json()["error"]["code"] == -32001
    assert empty.status_code == 200
    assert empty.json()["error"]["code"] == -32602
    search.assert_not_called()
    assert _incr_calls(pipe) == []


def test_mcp_server_reuses_demo_quota_dep():
    text = (ROOT / "apps" / "api" / "mcp_server.py").read_text(encoding="utf-8")
    assert "demo_quota_dep" in text
    assert "DEMO_EXHAUSTED_DETAIL" in text


def test_agent_surfaces_match_demo_quota_and_drop_20s_budget():
    """Agent docs must match REST lifetime quota and must not invent a 20s SLA."""
    root = ROOT
    files = {
        "pricing": root / "apps" / "web" / "agent" / "pricing.md",
        "privacy": root / "apps" / "web" / "agent" / "privacy.md",
        "auth": root / "apps" / "web" / "agent" / "auth.md",
        "agents": root / "apps" / "web" / "agent" / "agents.md",
        "llms": root / "apps" / "web" / "agent" / "llms.txt",
        "skill": root / "skills" / "agent-seek" / "SKILL.md",
    }
    for name, path in files.items():
        text = path.read_text(encoding="utf-8")
        assert "DEMO_EXHAUSTED" in text, name
        assert "/api/v1/search" in text, name
        assert "search_web" in text, name
        assert "share" in text.lower(), name
        assert "does not consume" not in text, name
        assert "not subject to" not in text, name
        assert "20s" not in text, name
        assert "total request" not in text.lower(), name
    auth = files["auth"].read_text(encoding="utf-8")
    assert "RATE_LIMITED" in auth
    assert "Retry-After" in auth
    assert "process-local" in auth
    pricing = files["pricing"].read_text(encoding="utf-8")
    assert "no `Retry-After`" in pricing or "no** `Retry-After`" in pricing or "**no** `Retry-After`" in pricing
    assert "≤ 5s" in pricing or "5s per call" in pricing
    human = (root / "apps" / "web" / "human" / "pricing.body.html").read_text(encoding="utf-8")
    assert "20s" not in human
    assert "total request" not in human.lower()
    assert "DEMO_EXHAUSTED" in human
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "rightmost" in readme
    assert "Exhausted UI searches" not in readme
    assert "DEMO_EXHAUSTED" in readme


def test_human_pricing_describes_website_demo_quota():
    html = (ROOT / "apps" / "web" / "human" / "pricing.body.html").read_text(encoding="utf-8")
    assert "AGENT_SEEK_DEMO_MODE" in html
    assert "5 website searches" in html or "5 searches" in html
    assert "DEMO_EXHAUSTED" in html
    assert "search_web" in html
    assert "shared by REST" in html
    assert "not subject to this quota" not in html
    assert "no time reset" in html or "no TTL" in html or "lifetime" in html
    assert "disabled" in html


def test_ui_dialog_wired_for_demo_exhausted():
    html = (ROOT / "apps" / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "apps" / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'id="demo-exhausted"' in html
    assert "Demo complete" in html
    assert "https://github.com/Gitmaxd/agent-seek" in html
    assert "DEMO_EXHAUSTED" in js
    assert "showDemoExhaustedDialog" in js
    assert ".demo-dialog" in css
