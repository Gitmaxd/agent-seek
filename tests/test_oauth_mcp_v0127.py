"""v0.1.27 — MCP Streamable HTTP + OAuth 2.0 discovery / token path."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.config import get_settings

get_settings.cache_clear()

from fastapi.testclient import TestClient

from apps.api.main import app
from packages.core.models import RankedResult, SearchMeta, SearchResponse
from packages.core.pipeline import AGENT_SEEK_VERSION

client = TestClient(app)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _fake_search(q: str = "jev") -> SearchResponse:
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
            candidates_in=5,
            kept=1,
            latency_ms=8,
            ranking="jev",
            agent_seek_version=AGENT_SEEK_VERSION,
        ),
        raw_results=[],
    )


def test_version_is_0127():
    assert AGENT_SEEK_VERSION == "0.3.0"
    assert client.get("/health").json() == {"ok": True, "version": "0.3.0"}


def test_oauth_as_metadata_shape():
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"].startswith("http")
    assert data["authorization_endpoint"].endswith("/oauth2/authorize")
    assert data["token_endpoint"].endswith("/oauth2/token")
    assert "S256" in data["code_challenge_methods_supported"]
    assert data.get("client_id_metadata_document_supported") is True
    for scope in ("search:read", "mcp:invoke", "health:read"):
        assert scope in data["scopes_supported"]
    agent = data["agent_auth"]
    assert agent["skill"].endswith("/auth.md")
    assert agent["identity_endpoint"].endswith("/agent/identity")
    assert agent["claim_endpoint"].endswith("/agent/identity/claim")
    assert agent["events_endpoint"].endswith("/agent/event/notify")
    assert set(agent["identity_types_supported"]) >= {"anonymous", "identity_assertion", "service_auth"}
    assert "urn:ietf:params:oauth:token-type:id-jag" in agent["identity_assertion"]["assertion_types_supported"]


def test_oauth_protected_resource():
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    data = r.json()
    assert data["resource"].startswith("http")
    assert data["authorization_servers"]
    assert "search:read" in data["scopes_supported"]
    assert "header" in data["bearer_methods_supported"]


def test_401_www_authenticate_resource_metadata():
    r = client.post("/v1/search", json={"q": "test"})
    assert r.status_code == 401
    wa = r.headers.get("www-authenticate") or ""
    assert "resource_metadata=" in wa
    assert "/.well-known/oauth-protected-resource" in wa
    assert "realm=" not in wa
    assert wa.startswith("Bearer resource_metadata=")
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    body = r.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["code"] == "UNAUTHORIZED"
    assert body["hint"]


def test_auth_md_content_type_and_heading():
    r = client.get("/auth.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text.lstrip().startswith("# Agent Seek authentication")
    assert "WWW-Authenticate" in r.text
    assert "identity_endpoint" in r.text
    assert "service_auth" in r.text
    assert "id-jag" in r.text


def test_agent_auth_endpoints_reachable():
    for path in (
        "/agent/identity",
        "/agent/identity/claim",
        "/agent/event/notify",
        "/oauth2/token",
        "/oauth2/revoke",
        "/oauth2/register",
        "/oauth2/authorize",
    ):
        opt = client.options(path)
        assert opt.status_code != 404, path
        get_or_post = client.get(path) if path in {"/agent/identity", "/agent/identity/claim", "/agent/event/notify"} else None
        if get_or_post is not None:
            assert get_or_post.status_code != 404, path


def test_mcp_server_card():
    r = client.get("/.well-known/mcp/server-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"]
    assert len(card["description"]) >= 20
    assert card["version"] == "0.3.0"
    assert card["serverUrl"].endswith("/mcp")
    names = {t["name"] if isinstance(t, dict) else t for t in card["tools"]}
    assert "search_web" in names
    assert len(card["tools"]) >= 3


def test_mcp_initialize_and_tools_list():
    init = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        },
    )
    assert init.status_code == 200
    body = init.json()
    assert body["jsonrpc"] == "2.0"
    result = body["result"]
    assert result["protocolVersion"].startswith("2025-")
    assert result["serverInfo"]["name"] == "agent-seek"
    assert result["serverInfo"]["version"] == "0.3.0"
    assert "instructions" in result and len(result["instructions"]) >= 20
    assert "tools" in result["capabilities"]
    assert "resources" not in result["capabilities"]

    listed = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    assert len(tools) >= 3
    for tool in tools:
        assert "_" in tool["name"] or tool["name"].islower()
        assert len(tool["name"]) >= 4
        assert len(tool["description"]) >= 20
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "annotations" in tool
        assert tool["annotations"].get("readOnlyHint") is True
    names = {t["name"] for t in tools}
    assert names >= {"search_web", "get_service_health", "get_api_docs"}
    search = next(t for t in tools if t["name"] == "search_web")
    assert search["inputSchema"]["properties"]["mode"]["default"] == "snip"


def test_mcp_jsonrpc_errors():
    bad = client.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "not/a/method"})
    assert bad.status_code == 200
    err = bad.json()["error"]
    assert err["code"] == -32601
    assert err["message"]

    parse = client.post("/mcp", content="not-json", headers={"Content-Type": "application/json"})
    assert parse.status_code == 400
    assert parse.json()["error"]["code"] == -32700

    missing = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_web", "arguments": {}}},
    )
    assert missing.status_code == 200
    assert missing.json()["error"]["code"] in (-32602, -32001)


def test_mcp_well_known_alias():
    r = client.post(
        "/.well-known/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "x", "version": "1"}}},
    )
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "agent-seek"


def test_public_api_index_and_rate_limit_headers():
    r = client.get("/v1")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Agent Seek API"
    assert "/v1/search" in data["search"]
    assert "openapi" in data
    assert "RateLimit" in r.headers
    assert "RateLimit-Policy" in r.headers


def test_oauth_pkce_s256_search(monkeypatch):
    verifier, challenge = _pkce()
    auth = client.get(
        "/oauth2/authorize",
        params={
            "response_type": "code",
            "client_id": "agent-seek-test",
            "redirect_uri": "http://127.0.0.1/callback",
            "scope": "search:read health:read mcp:invoke",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
        },
        follow_redirects=False,
    )
    assert auth.status_code in (302, 307)
    loc = auth.headers["location"]
    assert "code=" in loc
    code = loc.split("code=")[1].split("&")[0]

    tok = client.post(
        "/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1/callback",
            "client_id": "agent-seek-test",
            "code_verifier": verifier,
        },
    )
    assert tok.status_code == 200
    access = tok.json()["access_token"]
    assert tok.json()["token_type"] == "Bearer"
    assert "search:read" in tok.json()["scope"]

    fake = _fake_search("oauth pkce")
    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/v1/search",
            json={"q": "oauth pkce", "k": 5},
            headers={"Authorization": f"Bearer {access}"},
        )
    assert r.status_code == 200
    assert r.json()["results"][0]["score"] == 0.9


def test_oauth_service_auth_then_search():
    ident = client.post(
        "/agent/identity",
        json={"type": "service_auth", "client_secret": "test-agent-seek-key"},
    )
    assert ident.status_code == 200
    assertion = ident.json()["identity_assertion"]
    tok = client.post(
        "/oauth2/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    assert tok.status_code == 200
    access = tok.json()["access_token"]

    fake = _fake_search("oauth service")
    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/v1/search",
            json={"q": "oauth service"},
            headers={"Authorization": f"Bearer {access}"},
        )
    assert r.status_code == 200
    assert r.json()["meta"]["agent_seek_version"] == "0.3.0"


def test_anonymous_identity_lacks_search_scope():
    ident = client.post("/agent/identity", json={"type": "anonymous"})
    assert ident.status_code == 200
    assertion = ident.json()["identity_assertion"]
    tok = client.post(
        "/oauth2/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
    )
    assert tok.status_code == 200
    access = tok.json()["access_token"]
    r = client.post("/v1/search", json={"q": "nope"}, headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 403
    assert r.json()["code"] in {"INSUFFICIENT_SCOPE", "FORBIDDEN"}


def test_mcp_search_web_with_api_key():
    fake = _fake_search("mcp")
    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/mcp",
            headers={"Authorization": "Bearer test-agent-seek-key"},
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "search_web", "arguments": {"q": "mcp", "k": 5}},
            },
        )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["content"][0]["type"] == "text"
    assert "example.com" in result["content"][0]["text"]
    assert pipe.search.await_args.kwargs.get("mode") == "snip"


def test_api_key_still_works():
    fake = _fake_search("key")
    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.post(
            "/v1/search",
            json={"q": "key"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 200
    assert pipe.search.await_args.kwargs.get("mode") == "snip"
