import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure settings pick up test key before import
import os

os.environ["AGENT_SEEK_API_KEY"] = "test-agent-seek-key"
os.environ["YDC_API_KEY"] = "test-ydc"
os.environ["TYPESAFE_API_KEY"] = "test-typesafe"
os.environ["AGENT_SEEK_UI_API_KEY"] = "test-agent-seek-key"

from apps.api.config import get_settings

get_settings.cache_clear()

from apps.api.errors import STATUS_CODES
from apps.api.main import app
from packages.core.models import Candidate, RankedResult, SearchMeta, SearchResponse

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "0.3.0"}


def test_search_unauthorized():
    r = client.post("/v1/search", json={"q": "test"})
    assert r.status_code == 401


def test_deep_mode_accepted():
    fake = SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url="https://example.com",
                title="Example",
                snippet="hi",
                score=0.9,
                flags=["on_topic"],
                raw_rank=2,
                provider="you.com",
            )
        ],
        meta=SearchMeta(
            q="test",
            candidates_in=5,
            kept=1,
            latency_ms=12,
            mode="deep",
            ranking="jev",
            agent_seek_version="0.3.0",
            fetch_ms=5,
        ),
        raw_results=[],
    )

    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/v1/search",
            json={"q": "test", "mode": "deep"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["mode"] == "deep"
    assert body["meta"]["agent_seek_version"] == "0.3.0"
    assert pipe.search.await_args.kwargs.get("mode") == "deep"


def test_omitted_mode_is_snip():
    fake = SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url="https://example.com",
                title="Example",
                snippet="hi",
                score=0.9,
                flags=["on_topic"],
                raw_rank=2,
                provider="you.com",
            )
        ],
        meta=SearchMeta(
            q="test",
            candidates_in=5,
            kept=1,
            latency_ms=10,
            mode="snip",
            ranking="jev",
            agent_seek_version="0.3.0",
        ),
        raw_results=[],
    )

    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        post = client.post(
            "/v1/search",
            json={"q": "test"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
        get = client.get(
            "/v1/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
        null_mode = client.post(
            "/v1/search",
            json={"q": "test", "mode": None},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
        alias = client.get(
            "/api/v1/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert post.status_code == 200
    assert get.status_code == 200
    assert null_mode.status_code == 200
    assert alias.status_code == 200
    assert pipe.search.await_args_list[0].kwargs.get("mode") == "snip"
    assert pipe.search.await_args_list[1].kwargs.get("mode") == "snip"
    assert pipe.search.await_args_list[2].kwargs.get("mode") == "snip"
    assert pipe.search.await_args_list[3].kwargs.get("mode") == "snip"


def test_openapi_and_mcp_default_mode_snip():
    spec = client.get("/openapi.json").json()
    mode_schema = spec["components"]["schemas"]["SearchRequest"]["properties"]["mode"]
    assert mode_schema.get("default") == "snip"

    from apps.api.mcp_server import TOOLS

    search = next(t for t in TOOLS if t["name"] == "search_web")
    assert search["inputSchema"]["properties"]["mode"]["default"] == "snip"


def test_search_mocked():
    fake = SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url="https://example.com",
                title="Example",
                snippet="hi",
                score=0.9,
                flags=["on_topic"],
                raw_rank=2,
                provider="you.com",
            )
        ],
        meta=SearchMeta(
            q="test",
            candidates_in=5,
            kept=1,
            latency_ms=10,
            ranking="jev",
        ),
        raw_results=[],
    )

    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/v1/search",
            json={"q": "test", "k": 5},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["score"] == 0.9
    assert body["meta"]["agent_seek_version"] == "0.3.0"


def _openapi_problem_example(media: dict) -> dict:
    if "example" in media and isinstance(media["example"], dict):
        return media["example"]
    examples = media.get("examples") or {}
    for item in examples.values():
        if isinstance(item, dict) and isinstance(item.get("value"), dict):
            return item["value"]
        if isinstance(item, dict) and "status" in item and "code" in item:
            return item
    raise AssertionError(f"no problem+json example in media keys={sorted(media)}")


def test_openapi_error_examples_are_status_specific():
    spec = client.get("/openapi.json").json()
    search_ops = (
        spec["paths"]["/v1/search"]["post"],
        spec["paths"]["/v1/search"]["get"],
    )
    expected = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        502: "UPSTREAM_ERROR",
    }
    for status, code in expected.items():
        assert STATUS_CODES[status] == code
    for op in search_ops:
        for status, code in expected.items():
            resp = op["responses"][str(status)]
            content = resp["content"]
            media = content.get("application/problem+json") or content.get("application/json")
            assert media, status
            example = _openapi_problem_example(media)
            assert example["status"] == status
            assert example["code"] == code
            assert example["error"]["code"] == code
            assert example["title"] == code.replace("_", " ").title()
            if status == 401:
                assert "WWW-Authenticate" in (resp.get("headers") or {})
            if status == 429:
                headers = resp.get("headers") or {}
                assert "Retry-After" in headers
                assert "RateLimit" in headers
