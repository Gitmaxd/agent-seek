"""v0.1.27 — Phase 1 agent-ready discovery / access surfaces."""
from __future__ import annotations

import json
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

from apps.api.agent_ready import AI_CRAWLERS
from apps.api.main import app
from packages.core.pipeline import AGENT_SEEK_VERSION

client = TestClient(app)

URN = re.compile(r"^urn:air:[a-zA-Z0-9.-]+(:[a-zA-Z0-9._-]+)+$")


def _visible_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def test_version_is_0126():
    assert AGENT_SEEK_VERSION == "0.3.0"
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "0.3.0"}


def test_llms_txt():
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert len(body) >= 100
    assert re.search(r"when to use", body, re.I)
    assert body.lstrip().startswith("# Agent Seek")
    assert "/docs" in body
    assert "/developers" in body
    assert "/openapi.json" in body
    assert "/api/docs" in body
    assert "/auth.md" in body
    assert "SKILL.md" in body
    assert not body.lstrip().startswith("<")


def _robots_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line:
                current = None
            continue
        lowered = line.lower()
        if lowered.startswith("user-agent:"):
            current = line.split(":", 1)[1].strip()
            blocks.setdefault(current, [])
            continue
        if lowered.startswith("sitemap:"):
            current = None
            continue
        if current is not None:
            blocks[current].append(line)
    return blocks


def test_robots_txt():
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    text = r.text
    for bot in (
        "GPTBot",
        "ClaudeBot",
        "OAI-SearchBot",
        "Claude-SearchBot",
        "PerplexityBot",
        "ChatGPT-User",
        "Claude-User",
        "Google-Extended",
        "ora-agent",
        "DeepSeekBot",
    ):
        assert bot in text
    assert "Sitemap:" in text
    assert "/sitemap.xml" in text
    assert "Disallow: /config.js" in text
    assert "Allow: /v1/sandbox" in text
    assert "Allow: /v1/sandbox/" in text
    assert "Disallow: /v1/" in text

    blocks = _robots_blocks(text)
    for agent in ("*", *AI_CRAWLERS):
        rules = blocks[agent]
        allow_i = rules.index("Allow: /v1/sandbox")
        allow_slash_i = rules.index("Allow: /v1/sandbox/")
        disallow_i = rules.index("Disallow: /v1/")
        assert allow_i < disallow_i, agent
        assert allow_slash_i < disallow_i, agent
        assert "Disallow: /config.js" in rules


def test_sitemap_xml():
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    body = r.text
    assert "<lastmod>" in body
    for path in ("/", "/docs", "/developers", "/openapi.json", "/llms.txt", "/auth.md", "/about", "/contact", "/privacy", "/mcp", "/v1", "/v1/sandbox", "/eval", "/eval.md"):
        assert path in body
    assert "https://agentseek.dev/" in body


def test_ard_and_ai_catalog():
    for path in ("/.well-known/ard.json", "/.well-known/ai-catalog.json"):
        r = client.get(path)
        assert r.status_code == 200, path
        data = r.json()
        assert "entries" in data and len(data["entries"]) >= 2
        for entry in data["entries"]:
            assert URN.match(entry["identifier"])
            assert entry["displayName"]
            assert entry["type"]
            assert "url" in entry
            assert "data" not in entry
            assert entry["url"].startswith("http")
            assert "trustManifest" in entry
            assert "identity" in entry["trustManifest"]


def test_agent_skills_index_and_skill_md():
    r = client.get("/.well-known/agent-skills/index.json")
    assert r.status_code == 200
    data = r.json()
    skills = data["skills"]
    assert skills
    seek = next(s for s in skills if s["name"] == "agent-seek")
    assert len(seek["description"]) > 20
    assert seek["type"] == "skill-md"
    assert seek["url"].endswith("/SKILL.md")
    assert seek["digest"].startswith("sha256:")
    assert len(seek["digest"]) == 7 + 64

    s = client.get("/.well-known/agent-skills/agent-seek/SKILL.md")
    assert s.status_code == 200
    assert "markdown" in s.headers["content-type"]
    assert s.text.lstrip().startswith("---") or s.text.lstrip().startswith("#")
    assert "private exe.dev" not in s.text
    assert "POST /v1/search" in s.text

    alias = client.get("/skills/agent-seek/SKILL.md", follow_redirects=False)
    assert alias.status_code in (301, 308)
    loc = alias.headers.get("location") or ""
    assert loc.endswith("/.well-known/agent-skills/agent-seek/SKILL.md")


def test_agents_and_auth_md():
    agents = client.get("/agents.md")
    assert agents.status_code == 200
    assert "markdown" in agents.headers["content-type"]
    assert agents.text.lstrip().startswith("---") or agents.text.lstrip().startswith("#")
    assert "POST /v1/search" in agents.text
    assert len(agents.text) >= 200

    auth = client.get("/auth.md")
    assert auth.status_code == 200
    assert auth.headers["content-type"].startswith("text/markdown")
    assert auth.text.lstrip().startswith("# ")
    assert re.search(r"^# Agent Seek authentication", auth.text, re.M)
    assert len(auth.text) >= 200
    assert "AGENT_SEEK_API_KEY" in auth.text
    assert "OAuth" in auth.text
    assert "identity_endpoint" in auth.text
    assert "/.well-known/oauth-protected-resource" in auth.text


def test_trust_and_pricing_pages():
    for path in ("/about", "/contact", "/privacy", "/pricing"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "text/html" in r.headers["content-type"]
        text = _visible_text(r.text)
        assert len(text) >= 500, f"{path} visible text {len(text)}"
        assert "<h1" in r.text.lower()
        assert "Agent Seek" in r.text
        assert "/developers" in r.text or "Agent Seek API" in r.text

        md = client.get(path + ".md")
        assert md.status_code == 200
        assert "markdown" in md.headers["content-type"]
        assert len(md.text) >= 200


def test_homepage_html_metadata_and_jsonld():
    r = client.get("/", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    text = _visible_text(html)
    # Landing search stays primary; crawlable below-fold prose must still be in raw HTML.
    assert len(text) >= 500
    assert re.search(r"<h1[^>]*>\s*Less SEO\. More signal\.\s*</h1>", html)
    assert "<title>Agent Seek — Less SEO. More signal.</title>" in html
    assert 'property="og:title" content="Agent Seek — Less SEO. More signal."' in html
    assert 'name="twitter:title" content="Agent Seek — Less SEO. More signal."' in html
    desc = re.search(r'name="description" content="([^"]+)"', html)
    assert desc
    assert "people and agents" in desc.group(1)
    assert len(desc.group(1)) >= 80
    assert "You.com" in desc.group(1) and "Jev" in desc.group(1)
    assert "ranked sources" in desc.group(1).lower()
    assert "caller writes the answer" in desc.group(1).lower()
    og_desc = re.search(r'property="og:description" content="([^"]+)"', html)
    tw_desc = re.search(r'name="twitter:description" content="([^"]+)"', html)
    assert og_desc and "ranked sources" in og_desc.group(1).lower()
    assert tw_desc and "caller writes the answer" in tw_desc.group(1).lower()
    assert "For agents" in text
    assert "What Agent Seek is" not in text
    assert "home-about-details" not in html
    assert 'content="index,follow"' in html
    assert 'rel="canonical" href="https://agentseek.dev/"' in html
    assert 'property="og:image"' in html
    assert 'property="og:type"' in html
    assert 'name="twitter:card"' in html
    assert 'name="twitter:title"' in html
    assert 'lang="en"' in html
    assert 'id="search-form"' in html
    assert "/developers" in html
    assert "application/ld+json" in html
    ld = re.search(r'<script type="application/ld\+json">\s*([\s\S]*?)\s*</script>', html)
    assert ld, "JSON-LD missing"
    data = json.loads(ld.group(1))
    types = {n.get("@type") for n in data.get("@graph", [])}
    assert "SoftwareApplication" in types
    assert "WebSite" in types
    assert "Organization" in types
    assert "Service" in types
    assert "BreadcrumbList" in types
    assert "FAQPage" in types
    website = next(n for n in data["@graph"] if n.get("@type") == "WebSite")
    action = website["potentialAction"]
    assert action["@type"] == "SearchAction"
    assert "{search_term_string}" in action["target"]["urlTemplate"]
    assert action["target"]["urlTemplate"].startswith("https://agentseek.dev/")
    app_node = next(n for n in data["@graph"] if n.get("@type") == "SoftwareApplication")
    assert "Less SEO. More signal." in app_node["description"]
    assert "ranked sources" in app_node["description"].lower()
    assert "caller writes the answer" in app_node["description"].lower()
    offers = app_node["offers"]
    assert offers["@type"] == "Offer"
    assert offers["price"] == "0"
    assert "ranked sources" in website["description"].lower()
    same_as = []
    for n in data["@graph"]:
        same_as.extend(n.get("sameAs") or [])
    assert "https://github.com/Gitmaxd/agent-seek" in same_as
    assert not any("wikipedia" in s.lower() or "wikidata" in s.lower() for s in same_as)


def test_homepage_link_headers():
    r = client.get("/", headers={"Accept": "text/html"})
    link = r.headers.get("link", "")
    assert "rel=\"sitemap\"" in link or "rel=sitemap" in link
    assert "/llms.txt" in link
    assert "/openapi.json" in link
    assert "agent-skills" in link
    assert "text/markdown" in link
    assert "api-catalog" in link
    assert "mcp/server-card.json" in link
    assert "oauth-protected-resource" in link


def test_rfc9727_api_catalog():
    r = client.get("/.well-known/api-catalog")
    assert r.status_code == 200
    ct = r.headers["content-type"]
    assert "application/linkset+json" in ct
    assert "rfc9727" in ct
    data = r.json()
    assert "linkset" in data and data["linkset"]
    blob = json.dumps(data)
    assert "/openapi.json" in blob
    head = client.head("/.well-known/api-catalog")
    assert head.status_code == 200


def test_markdown_negotiation_and_index_md():
    md = client.get("/", headers={"Accept": "text/markdown"})
    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    assert "Vary" in md.headers and "Accept" in md.headers["Vary"]
    assert md.text.lstrip().startswith("---") or md.text.lstrip().startswith("#")
    assert "<!doctype" not in md.text.lower()

    html = client.get("/", headers={"Accept": "text/html"})
    assert "text/html" in html.headers["content-type"]
    assert "<h1" in html.text

    twin = client.get("/index.md")
    assert twin.status_code == 200
    assert "markdown" in twin.headers["content-type"]
    assert twin.text.lstrip().startswith("---") or twin.text.lstrip().startswith("#")


def test_agent_friendly_404():
    html = client.get("/this-path-does-not-exist-0126")
    assert html.status_code == 404

    md = client.get(
        "/this-path-does-not-exist-0126",
        headers={"Accept": "text/markdown"},
    )
    assert md.status_code == 404
    assert "text/markdown" in md.headers["content-type"]
    assert len(md.text) >= 20
    assert md.text.lstrip().startswith("#")
    assert "/llms.txt" in md.text or "/docs" in md.text


def test_json_error_model_401():
    r = client.post("/v1/search", json={"q": "test"})
    assert r.status_code == 401
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["error"]["message"]
    assert body["error"]["hint"]
    assert "detail" in body
    assert "www-authenticate" in {k.lower() for k in r.headers}
    wa = r.headers.get("www-authenticate") or r.headers.get("WWW-Authenticate")
    assert "resource_metadata=" in wa
    assert "oauth-protected-resource" in wa
    assert "realm=" not in wa
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    assert body["type"].endswith("/errors/unauthorized")
    assert body["title"]
    assert body["status"] == 401
    assert r.json().get("code") == "UNAUTHORIZED"
    assert r.json().get("hint")
    assert "RateLimit" in r.headers or "ratelimit" in {k.lower() for k in r.headers}


def test_json_error_model_422():
    r = client.post(
        "/v1/search",
        json={"q": ""},
        headers={"Authorization": "Bearer test-agent-seek-key"},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["hint"]


def test_openapi_operation_ids_and_errors():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["version"] == "0.3.0"
    post = spec["paths"]["/v1/search"]["post"]
    assert post["operationId"] == "searchPost"
    assert post.get("description") or post.get("summary")
    assert "401" in post["responses"]
    schemas = spec["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "ErrorBody" in schemas
    assert "AgentSeekApiKey" in spec["components"]["securitySchemes"]
    assert "OAuth2" in spec["components"]["securitySchemes"]
    oauth = spec["components"]["securitySchemes"]["OAuth2"]
    assert "search:read" in oauth["flows"]["authorizationCode"]["scopes"]
    assert "RateLimit" in spec["components"]["headers"]


def test_developers_agent_seek_api():
    r = client.get("/developers")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Agent Seek API</title>" in r.text
    assert re.search(r"<h1[^>]*>\s*Agent Seek API", r.text)
    assert "POST /v1/search" in r.text
    assert "/openapi.json" in r.text
    assert "/auth.md" in r.text
    assert 'rel="canonical" href="https://agentseek.dev/developers"' in r.text
    assert len(_visible_text(r.text)) >= 500
    md = client.get("/developers.md")
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert md.text.lstrip().startswith("---") or "# Agent Seek API" in md.text


def test_docs_has_what_agent_seek_is():
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "What it is" in docs.text
    assert "Who it is for" in docs.text
    assert "TypeSafe Jev" in docs.text
    assert "chat model" in docs.text.lower() or "write the answer" in docs.text.lower()
    assert len(_visible_text(docs.text)) >= 500


def test_search_form_css_google_width():
    css = client.get("/static/styles.css")
    assert css.status_code == 200
    body = css.text
    assert re.search(r"\.search-form\s*\{[^}]*width:\s*100%", body, re.S)
    assert re.search(r"\.search-form\s*\{[^}]*max-width:\s*584px", body, re.S)
    assert re.search(r"\.site-footer nav\s*\{[^}]*justify-content:\s*center", body, re.S)
    assert re.search(r"\.site-footer nav\s*\{[^}]*max-width:\s*584px", body, re.S)
    assert re.search(r"\.site-footer nav\s*\{[^}]*margin:\s*0 auto", body, re.S)
    assert "home-about-details" not in body


def test_unique_branded_titles_and_h1s():
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "<title>Agent Seek docs" in docs.text
    assert re.search(r"<h1[^>]*>\s*Agent Seek docs", docs.text)
    assert "/developers" in docs.text
    assert "POST /v1/search" in docs.text
    assert "Agent Seek" in docs.text

    about = client.get("/about")
    assert "<title>About Agent Seek</title>" in about.text
    assert re.search(r"<h1[^>]*>\s*About Agent Seek", about.text)

    contact = client.get("/contact")
    assert "<title>Contact Agent Seek</title>" in contact.text
    assert re.search(r"<h1[^>]*>\s*Contact Agent Seek", contact.text)

    privacy = client.get("/privacy")
    assert "<title>Agent Seek privacy</title>" in privacy.text
    auth = client.get("/auth.md")
    assert re.search(r"^# Agent Seek authentication", auth.text, re.M)


def test_ui_search_form_still_present():
    r = client.get("/")
    assert 'id="search-form"' in r.text
    assert 'id="q"' in r.text
    assert "webmcp.js" in r.text
    assert 'toolname="search_web"' in r.text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "search-form" in js.text
    assert "score-meter" in js.text
    webmcp = client.get("/static/webmcp.js")
    assert webmcp.status_code == 200
    assert "document.modelContext" in webmcp.text
    assert "navigator.modelContext" in webmcp.text
    assert "registerTool" in webmcp.text
