"""v0.1.39 — crawlable homepage prose + typed OpenAPI schemas + sandbox discoverability."""
from __future__ import annotations

import os
import re
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

MAJOR_OPS = {
    "searchPost",
    "searchGet",
    "healthCheck",
    "apiIndex",
    "listPublicApi",
    "sandboxSearchExample",
}


def _visible_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _resolve_ref(schema: dict, components: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = ref.rsplit("/", 1)[-1]
    return (components.get("schemas") or {}).get(name) or {}


def _is_typed_object(schema: dict, components: dict) -> bool:
    resolved = _resolve_ref(schema, components) if "$ref" in schema else schema
    if resolved.get("allOf"):
        return any(
            _is_typed_object(part, components)
            for part in resolved["allOf"]
            if isinstance(part, dict)
        )
    props = resolved.get("properties")
    if resolved.get("type") != "object" or not isinstance(props, dict) or not props:
        return False
    return all(
        isinstance(p, dict)
        and (
            p.get("type")
            or p.get("$ref")
            or p.get("anyOf")
            or p.get("items")
            or p.get("additionalProperties")
        )
        and (p.get("description") or p.get("$ref") or p.get("items") or p.get("additionalProperties"))
        for p in props.values()
    )


def test_version_is_0139():
    assert AGENT_SEEK_VERSION == "0.1.39"
    assert client.get("/health").json() == {"ok": True, "version": "0.1.39"}


def test_homepage_raw_html_has_500_chars_h1_and_h2s():
    r = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    text = _visible_text(html)
    assert len(text) >= 500
    assert re.search(r"<h1[^>]*>\s*Less SEO\. More signal\.\s*</h1>", html)
    assert "<title>Agent Seek" in html
    assert "Agent Seek" in text
    headings = re.findall(r"<h([1-3])[^>]*>(.*?)</h\1>", html, flags=re.I | re.S)
    levels = [int(lvl) for lvl, _ in headings]
    assert levels[0] == 1
    assert levels == sorted(levels)
    labels = [re.sub(r"<[^>]+>", "", body).strip() for _, body in headings]
    assert labels[0] == "Less SEO. More signal."
    assert "What it is" in labels
    assert "For agents" in labels
    assert "API entry points" in labels
    prose = html.split('id="home-prose"', 1)[-1]
    assert "You.com" in prose and "Jev" in prose
    assert "/docs" in prose
    assert "/llms.txt" in prose
    assert "/auth.md" in prose
    assert "/openapi.json" in prose
    assert "/mcp" in prose or "server-card.json" in prose
    assert "/v1/sandbox" in prose
    assert "SKILL.md" in prose
    assert "display:none" not in html.split('id="home-prose"', 1)[0][-80:]
    css = client.get("/static/styles.css").text
    assert ".home-prose" in css
    assert "body:has(.hero.has-results) .home-prose" in css
    default_block = re.search(r"\.home-prose\s*\{([^}]+)\}", css)
    assert default_block and "display: none" not in default_block.group(1)


def test_homepage_prose_outside_hero():
    html = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}).text
    hero = html.split('class="hero"', 1)[-1].split("</header>", 1)[0]
    assert "home-prose" not in hero
    assert 'id="search-form"' in hero
    assert "What it is" not in hero
    after_main = html.split("</main>", 1)[-1]
    assert 'id="home-prose"' in after_main
    assert 'id="site-footer"' in after_main


def test_llms_and_skill_feature_sandbox():
    llms = client.get("/llms.txt").text
    assert llms.lstrip().startswith("# Agent Seek")
    assert re.search(r"(?im)^## Zero-auth sandbox", llms)
    assert "/v1/sandbox" in llms
    assert "Agent Seek OpenAPI" in llms
    assert "Agent Seek MCP" in llms
    assert "self-serve API keys" in llms.lower() or "mint self-serve" in llms.lower()

    skill = client.get("/.well-known/agent-skills/agent-seek/SKILL.md").text
    assert "GET /v1/sandbox" in skill
    assert "self-serve API keys" in skill.lower() or "mint self-serve" in skill
    assert "search_web" in skill

    auth = client.get("/auth.md").text
    assert "GET /v1/sandbox" in auth
    assert re.search(r"^# Agent Seek authentication", auth, re.M)

    dev = client.get("/developers.md").text
    assert "/v1/sandbox" in dev
    assert "does **not** mint self-serve API keys" in dev or "does not mint self-serve API keys" in dev


def test_sandbox_zero_auth_still_works():
    r = client.get("/v1/sandbox")
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["provider"] == "sandbox"
    assert body["meta"]["ranking"] == "sandbox"
    assert body["meta"]["agent_seek_version"] == "0.1.39"


def test_openapi_all_major_ops_have_typed_schemas():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Agent Seek OpenAPI"
    assert spec["info"]["version"] == "0.1.39"
    components = spec["components"]
    schemas = components["schemas"]
    for name in (
        "SearchRequest",
        "SearchResponse",
        "HealthResponse",
        "ApiDiscoveryResponse",
        "RankedResult",
        "SearchMeta",
        "ProblemDetails",
    ):
        assert name in schemas, name
        if name != "ProblemDetails":
            assert _is_typed_object({"$ref": f"#/components/schemas/{name}"}, components), name

    found: set[str] = set()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict) or method.startswith("x-"):
                continue
            oid = op.get("operationId")
            assert oid, f"{method} {path} missing operationId"
            found.add(oid)
            assert op.get("description") or op.get("summary")
            ok = (op.get("responses") or {}).get("200") or {}
            schema = ((ok.get("content") or {}).get("application/json") or {}).get("schema")
            assert schema and ("$ref" in schema or _is_typed_object(schema, components)), oid
            if oid in MAJOR_OPS:
                assert _is_typed_object(schema, components), oid
            if oid == "searchPost":
                rb = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
                assert rb and _is_typed_object(rb, components)
            if oid == "searchGet":
                params = {p.get("name"): p for p in op.get("parameters") or [] if isinstance(p, dict)}
                for field in ("q", "k", "max_candidates", "mode"):
                    assert field in params, field
                    pschema = params[field].get("schema") or {}
                    assert pschema.get("type") or pschema.get("$ref")
                    assert params[field].get("description") or pschema.get("description")
    assert MAJOR_OPS <= found
    assert len(found) == len(set(found))


def test_mcp_card_branded():
    card = client.get("/.well-known/mcp/server-card.json").json()
    assert card["name"] == "Agent Seek MCP"
    assert card["version"] == "0.1.39"
