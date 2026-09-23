"""v0.1.28 — Phase 3A ora scoring mismatches (errors, WWW-Authenticate, OpenAPI, llms)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

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
from packages.core.pipeline import AGENT_SEEK_VERSION

client = TestClient(app)


def test_version_is_0128():
    assert AGENT_SEEK_VERSION == "0.3.0"
    assert client.get("/health").json() == {"ok": True, "version": "0.3.0"}


def _assert_problem(r, status: int, code: str):
    assert r.status_code == status
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    body = r.json()
    assert body["type"].endswith("/errors/" + code.lower().replace("_", "-"))
    assert body["title"]
    assert body["status"] == status
    assert body["detail"]
    assert body["instance"]
    assert body["code"] == code
    assert body["message"]
    assert body["hint"]
    assert body["error"]["code"] == code
    assert body["error"]["hint"]
    return body


def test_problem_json_401_search():
    r = client.post("/v1/search", json={"q": "test"})
    body = _assert_problem(r, 401, "UNAUTHORIZED")
    wa = r.headers.get("www-authenticate") or ""
    assert wa.startswith("Bearer resource_metadata=")
    assert "realm=" not in wa
    assert "/.well-known/oauth-protected-resource" in wa
    assert body["instance"] == "/v1/search"


def test_problem_json_422_validation():
    r = client.post(
        "/v1/search",
        json={"q": ""},
        headers={"Authorization": "Bearer test-agent-seek-key"},
    )
    body = _assert_problem(r, 422, "VALIDATION_ERROR")
    assert "errors" in body


def test_api_v1_entry_401_www_authenticate():
    for method in ("get", "post"):
        r = getattr(client, method)("/api/v1")
        _assert_problem(r, 401, "UNAUTHORIZED")
        wa = r.headers.get("www-authenticate") or ""
        assert wa.startswith("Bearer resource_metadata=")
        assert "realm=" not in wa
        assert wa.count("resource_metadata=") == 1


def test_public_api_discovery_routes():
    for path in ("/v1", "/api"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "application/json" in r.headers["content-type"]
        data = r.json()
        assert data["name"] == "Agent Seek API"
        assert data["version"] == "0.3.0"
        assert data["search"].endswith("/v1/search")
        assert data["sandbox"].endswith("/v1/sandbox")
        assert data["versioning"].endswith("/docs/versioning.md")
        assert "oauth2" in data["auth_methods"]
        assert "search:read" in data["scopes"]


def test_sandbox_zero_auth():
    r = client.get("/v1/sandbox")
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["provider"] == "sandbox"
    assert body["meta"]["ranking"] == "sandbox"
    assert body["meta"]["agent_seek_version"] == "0.3.0"


def test_v2_and_api_unknown_are_problem_json():
    r = client.get("/v2")
    _assert_problem(r, 404, "UNSUPPORTED_VERSION")
    assert "versioning.md" in (r.headers.get("link") or "") or "versioning" in r.json()["hint"]

    unknown = client.get("/api/this-is-not-a-real-operation")
    _assert_problem(unknown, 404, "NOT_FOUND")


def test_content_404_still_markdown():
    md = client.get("/this-path-does-not-exist-0128", headers={"Accept": "text/markdown"})
    assert md.status_code == 404
    assert "text/markdown" in md.headers["content-type"]
    assert md.text.lstrip().startswith("#")


def test_modular_llms_txt():
    root = client.get("/llms.txt")
    assert root.status_code == 200
    for path in ("/docs/llms.txt", "/api/llms.txt", "/developers/llms.txt"):
        assert path in root.text
        r = client.get(path)
        assert r.status_code == 200, path
        assert "text/plain" in r.headers["content-type"]
        assert r.text.lstrip().startswith("# Agent Seek")
        assert len(r.text) >= 100
        assert not r.text.lstrip().startswith("<")


def test_markdown_twins_api_docs_and_versioning():
    for path in ("/api/docs.md", "/api/redoc.md", "/docs/versioning.md", "/docs/auth.md"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "markdown" in r.headers["content-type"]
        assert r.text.lstrip().startswith("#") or r.text.lstrip().startswith("---")
        assert "<!doctype" not in r.text.lower()


def test_openapi_operation_ids_typed_and_problem():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "0.3.0"
    assert spec["info"]["x-api-versioning"]["current"] == "v1"
    assert "Sunset" in spec["info"]["description"] or "sunset" in spec["info"]["description"].lower()
    ids = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict) or method.startswith("x-"):
                continue
            oid = op.get("operationId")
            assert oid, f"{method} {path} missing operationId"
            ids.append(oid)
            assert op.get("description") or op.get("summary")
            assert "401" in op["responses"]
            err = op["responses"]["401"]
            assert "application/problem+json" in err["content"]
            assert err["content"]["application/problem+json"]["schema"]["$ref"].endswith("ProblemDetails")
    assert len(ids) == len(set(ids))
    assert {"searchPost", "searchGet", "healthCheck", "apiIndex", "listPublicApi", "sandboxSearchExample"} <= set(ids)
    schemas = spec["components"]["schemas"]
    assert "ProblemDetails" in schemas
    assert "HealthResponse" in schemas
    assert "ApiDiscoveryResponse" in schemas
    assert "SearchRequest" in schemas or "SearchResponse" in schemas
    oauth = spec["components"]["securitySchemes"]["OAuth2"]
    assert set(oauth["flows"]["authorizationCode"]["scopes"]) >= {"search:read", "mcp:invoke", "health:read"}
    assert spec["components"]["headers"]["WWWAuthenticate"]


def test_mcp_param_schemas_complete():
    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed.json()["result"]["tools"]
    assert len(tools) == 4
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)
        assert len(schema["properties"]) >= 1
        assert isinstance(schema.get("required"), list)
        for name, prop in schema["properties"].items():
            assert "type" in prop, name
            assert prop.get("description")


def test_agent_card_and_mode_agent():
    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    data = card.json()
    assert data["name"] == "Agent Seek"
    assert data["version"] == "0.3.0"
    assert data["skills"]
    assert data["skills"][0]["tags"]
    assert data["supportedInterfaces"][0]["url"].endswith("/mcp")
    alias = client.get("/.well-known/agent.json")
    assert alias.status_code == 200
    assert alias.json()["name"] == "Agent Seek"

    mode = client.get("/?mode=agent")
    assert mode.status_code == 200
    body = mode.json()
    assert body["mode"] == "agent"
    assert body["default_mode"] == "snip"
    assert body["endpoints"]["search"].endswith("/v1/search")
    assert "oauth2" in body["authentication"]["methods"]
    assert "ranked_web_search" in body["capabilities"]


def test_bot_ua_markdown_homepage():
    html = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert "text/html" in html.headers["content-type"]
    assert "Less SEO. More signal." in html.text

    bot = client.get(
        "/",
        headers={"Accept": "text/html", "User-Agent": "ClaudeBot/1.0"},
    )
    assert bot.status_code == 200
    assert "markdown" in bot.headers["content-type"]
    assert bot.text.lstrip().startswith("---") or bot.text.lstrip().startswith("#")
    assert "<!doctype" not in bot.text.lower()
    assert "Agent Seek" in bot.text


def test_pricing_md_expanded():
    r = client.get("/pricing.md")
    assert r.status_code == 200
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) >= 40
    assert "Sandbox" in r.text
    assert "Prototype" in r.text
    assert "Self-host" in r.text
    assert "no contact-sales" in r.text.lower() or "No sales form" in r.text or "no contact-sales form" in r.text.lower()


def test_developers_self_serve():
    r = client.get("/developers.md")
    assert "Self-serve" in r.text
    assert "/oauth2/register" in r.text
    assert "/v1/sandbox" in r.text
    assert "no contact-sales" in r.text.lower() or "no contact-sales form" in r.text
