"""v0.1.39 — public origin + agent onboarding path (callout under search, skill install, llms.txt)."""
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

SKILL_ALIAS = "/skills/agent-seek/SKILL.md"
WELL_KNOWN_SKILL = "/.well-known/agent-skills/agent-seek/SKILL.md"


def test_version_is_0129():
    assert AGENT_SEEK_VERSION == "0.1.39"
    assert client.get("/health").json() == {"ok": True, "version": "0.1.39"}


def test_homepage_html_has_agent_callout_and_links():
    r = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert "Less SEO. More signal." in html
    assert re.search(r'class="[^"]*agent-callout[^"]*"', html)
    assert "Agents:" in html
    assert "/llms.txt" in html
    assert WELL_KNOWN_SKILL in html
    assert "/auth.md" in html
    assert "/docs" in html
    # Server-rendered under search form in .hero (not in footer).
    assert 'id="search-form"' in html
    hero = html.split('class="hero"', 1)[-1].split("</header>", 1)[0]
    assert "agent-callout" in hero
    assert "Agents:" in hero
    form_at = hero.find('id="search-form"')
    callout_at = hero.find("agent-callout")
    assert 0 <= form_at < callout_at
    assert 'class="site-footer"' in html or 'id="site-footer"' in html
    footer = html.split('id="site-footer"', 1)[-1] if 'id="site-footer"' in html else html.split('class="site-footer"', 1)[-1]
    footer = footer.split("</footer>", 1)[0]
    assert "agent-callout" not in footer
    assert "Agents:" not in footer
    assert "About" in footer and "Docs" in footer
    # No mid-page expandable about on landing.
    assert "home-about-details" not in html
    assert 'id="about-seek"' not in html
    assert "<summary>What Agent Seek is</summary>" not in html
    assert "What Agent Seek is" not in html


def test_homepage_hero_unchanged():
    r = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert re.search(r"<h1[^>]*>\s*Less SEO\. More signal\.\s*</h1>", r.text)
    assert re.search(
        r'<p class="tagline">\s*Progressive Disclosure Search Ranking\s*</p>',
        r.text,
    )
    assert 'id="search-form"' in r.text
    assert 'id="q"' in r.text


def test_llms_txt_has_install_section():
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert re.search(r"(?im)^## Install the skill", body)
    assert WELL_KNOWN_SKILL in body
    assert "/auth.md" in body
    assert "POST /v1/search" in body
    assert "/mcp" in body
    assert ".cursor/skills/agent-seek/SKILL.md" in body
    assert "skill →" in body.lower() or "skill → this file" in body.lower() or "skill →" in body


def test_modular_llms_point_at_install():
    for path in ("/docs/llms.txt", "/api/llms.txt", "/developers/llms.txt"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "Install the skill" in r.text
        assert WELL_KNOWN_SKILL in r.text


def test_agents_and_docs_have_install_section():
    for path in ("/agents.md", "/docs.md"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert re.search(r"(?im)^## Install the skill", r.text)
        assert WELL_KNOWN_SKILL in r.text

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "Install the skill" in docs.text
    assert WELL_KNOWN_SKILL in docs.text
    assert "What it is" in docs.text
    assert "Who it is for" in docs.text


def test_skill_routes_200_and_lead_with_install():
    r = client.get(WELL_KNOWN_SKILL)
    assert r.status_code == 200
    assert "markdown" in r.headers["content-type"]
    body = r.text
    assert "private exe.dev" not in body
    assert "https://agentseek.dev" in body
    # Factory-style: numbered Instructions first; Install is a short footer.
    assert re.search(r"(?m)^## Instructions\s*$", body)
    assert "When to use" in body
    assert "search_web" in body
    assert "/.well-known/mcp/server-card.json" in body
    assert "Streamable HTTP" in body
    instructions_at = body.find("## Instructions")
    install_at = body.find("## Install")
    assert 0 <= instructions_at < install_at
    assert "/llms.txt" in body
    assert "/auth.md" in body
    assert "POST /v1/search" in body
    assert ".cursor/skills/agent-seek/SKILL.md" in body

    alias = client.get(SKILL_ALIAS, follow_redirects=False)
    assert alias.status_code in (301, 308)
    loc = alias.headers.get("location") or ""
    assert loc.endswith(WELL_KNOWN_SKILL)


def test_mode_agent_includes_onboarding():
    r = client.get("/?mode=agent")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "0.1.39"
    assert "skill" in body["endpoints"]
    assert body["endpoints"]["skill"].endswith(WELL_KNOWN_SKILL)
    assert "llms.txt" in body["onboarding"]
    assert "auth.md" in body["onboarding"]
