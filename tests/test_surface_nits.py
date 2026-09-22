"""Surface nits: one canonical skill URL, no advertised exe.xyz alternate."""
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

client = TestClient(app)

SKILL_ALIAS = "/skills/agent-seek/SKILL.md"
WELL_KNOWN_SKILL = "/.well-known/agent-skills/agent-seek/SKILL.md"

PUBLIC_PROSE_PATHS = (
    "/llms.txt",
    "/docs/llms.txt",
    "/api/llms.txt",
    "/developers/llms.txt",
    "/docs.md",
    "/docs",
    "/eval",
    "/eval.md",
    "/about.md",
    "/contact.md",
    "/agents.md",
    "/developers.md",
    "/developers",
    "/index.md",
    WELL_KNOWN_SKILL,
)

PUBLIC_SOURCE_FILES = (
    ROOT / "README.md",
    ROOT / "skills" / "agent-seek" / "SKILL.md",
    ROOT / "apps" / "web" / "docs.html",
    *(sorted((ROOT / "apps" / "web" / "agent").glob("*"))),
)

OPTIONAL_MCP_KEYS = {
    "get_service_health": "verbose",
    "get_api_docs": "topic",
    "list_search_capabilities": "include_scopes",
}

_CURSOR_SKILL = re.compile(r"~?/?\.cursor/skills/agent-seek/SKILL\.md")
_PUBLIC_ALIAS = re.compile(r"(?:https://agentseek\.dev)?/skills/agent-seek/SKILL\.md")


def _without_cursor_skill_paths(body: str) -> str:
    return _CURSOR_SKILL.sub("", body)


def test_well_known_skill_still_200():
    r = client.get(WELL_KNOWN_SKILL)
    assert r.status_code == 200
    assert "markdown" in r.headers["content-type"]
    assert r.text.lstrip().startswith("---") or r.text.lstrip().startswith("#")
    assert "## Instructions" in r.text
    assert "## Install" in r.text
    assert "search_web" in r.text
    assert "https://agentseek.dev" in r.text


def test_skill_alias_redirects_to_well_known():
    r = client.get(SKILL_ALIAS, follow_redirects=False)
    assert r.status_code in (301, 308)
    loc = r.headers.get("location") or ""
    assert loc.endswith(WELL_KNOWN_SKILL)

    followed = client.get(SKILL_ALIAS, follow_redirects=True)
    canonical = client.get(WELL_KNOWN_SKILL)
    assert followed.status_code == 200
    assert followed.text == canonical.text


def test_public_docs_do_not_advertise_exe_xyz_alternate():
    for path in PUBLIC_PROSE_PATHS:
        body = client.get(path, follow_redirects=True).text
        assert "gitmaxd-agent-seek.exe.xyz" not in body, path
        assert "alternate host" not in body.lower(), path

    home = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}).text
    assert "gitmaxd-agent-seek.exe.xyz" not in home
    assert "alternate host" not in home.lower()

    for src in PUBLIC_SOURCE_FILES:
        if not src.is_file():
            continue
        text = src.read_text(encoding="utf-8")
        assert "gitmaxd-agent-seek.exe.xyz" not in text, src.name
        assert "alternate host" not in text.lower(), src.name


def test_public_docs_advertise_canonical_skill_only():
    for path in PUBLIC_PROSE_PATHS:
        raw = client.get(path, follow_redirects=True).text
        stripped = _without_cursor_skill_paths(raw)
        assert not _PUBLIC_ALIAS.search(stripped), path

    home = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}).text
    assert WELL_KNOWN_SKILL in home
    assert not _PUBLIC_ALIAS.search(_without_cursor_skill_paths(home))


def test_readme_does_not_advertise_exe_xyz_alternate():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://agentseek.dev" in readme
    assert "exe.xyz" not in readme
    assert "alternate host" not in readme.lower()


def test_readme_is_oss_front_door():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in readme
    assert "/workspace" not in readme
    assert "Prototype / internal" not in readme
    assert "YDC_API_KEY" in readme
    assert "TYPESAFE_API_KEY" in readme
    assert "AGENT_SEEK_API_KEY" in readme
    assert "https://agentseek.dev/mcp" in readme
    assert "http://127.0.0.1:8787/mcp" in readme
    assert "SECURITY.md" in readme
    assert "CONTRIBUTING" in readme
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Git Maxd" in license_text


def test_sitemap_lists_canonical_skill_only():
    from apps.api.agent_ready import SITEMAP_PATHS

    assert WELL_KNOWN_SKILL in SITEMAP_PATHS
    assert SKILL_ALIAS not in SITEMAP_PATHS

    body = client.get("/sitemap.xml").text
    origin = "https://agentseek.dev"
    assert f"<loc>{origin}{WELL_KNOWN_SKILL}</loc>" in body
    assert f"<loc>{origin}{SKILL_ALIAS}</loc>" not in body


def test_mcp_optional_params_not_required():
    from apps.api.mcp_server import TOOLS

    by_name = {tool["name"]: tool for tool in TOOLS}
    for name, optional in OPTIONAL_MCP_KEYS.items():
        schema = by_name[name]["inputSchema"]
        assert optional in schema["properties"], name
        assert optional not in schema.get("required", []), name


def test_tagline_is_less_seo_more_signal():
    old_tagline = "more " + "answer"
    home = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}).text
    assert "Less SEO. More signal." in home
    assert "<title>Agent Seek — Less SEO. More signal.</title>" in home
    assert old_tagline not in home.lower()
    assert "ranked sources" in home.lower()
    assert "caller writes the answer" in home.lower()

    index_md = client.get("/index.md").text
    assert "Less SEO. More signal." in index_md
    assert "ranked sources" in index_md.lower()
    assert "caller writes the answer" in index_md.lower()

    og = (ROOT / "apps" / "web" / "og.svg").read_text(encoding="utf-8")
    assert "Less SEO. More signal." in og

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Less SEO. More signal." in readme

    llms = client.get("/llms.txt").text
    assert llms.lstrip().startswith("# Agent Seek")
    assert "Less SEO. More signal." in llms
    assert "ranked sources" in llms.lower()
    assert "caller writes the answer" in llms.lower()

    skill = client.get(WELL_KNOWN_SKILL).text
    assert "Less SEO. More signal." in skill
    assert "you write the answer" in skill.lower() or "caller writes the answer" in skill.lower()

    about_md = client.get("/about.md").text
    about_html = client.get("/about").text
    for body in (about_md, about_html, home, index_md, og, readme, llms, skill):
        assert old_tagline not in body.lower()


CONTEXT_ECONOMY = (
    "Prefer the top 1–2 ranked sources before expanding. "
    "One good keeper beats a context window full of searches."
)


def _has_top_1_2_and_context_window(body: str) -> bool:
    has_top = "top 1–2" in body or "top 1-2" in body
    return has_top and "context window" in body.lower()


def test_context_economy_one_liner_locked():
    old_tagline = "more " + "answer"
    never_abs = "never need more than 2"
    home = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"}).text
    index_md = client.get("/index.md").text
    llms = client.get("/llms.txt").text
    skill = client.get(WELL_KNOWN_SKILL).text
    docs = client.get("/docs").text
    about = client.get("/about.md").text
    agents = client.get("/agents.md").text

    assert CONTEXT_ECONOMY in home
    assert _has_top_1_2_and_context_window(home)
    assert CONTEXT_ECONOMY in llms or CONTEXT_ECONOMY in index_md
    assert CONTEXT_ECONOMY in skill
    assert any(CONTEXT_ECONOMY in body for body in (docs, about, agents))

    for body in (home, index_md, llms, skill, docs, about, agents):
        assert old_tagline not in body.lower()
        assert never_abs not in body.lower()


def test_about_keeps_public_repo_wording():
    about_md = client.get("/about.md").text
    about_html = client.get("/about").text
    assert "public repository" in about_md.lower()
    assert "public repo" in about_html.lower()
    assert "https://github.com/Gitmaxd/agent-seek" in about_md
    assert "https://github.com/Gitmaxd/agent-seek" in about_html


def test_llms_mentions_robots_sandbox_allow():
    llms = client.get("/llms.txt").text
    assert "robots.txt" in llms
    assert "/v1/sandbox" in llms
    assert "Disallow: /v1/" in llms


INJECTION_BEFORE_READ = "scored for prompt injection before the agent reads them"


def test_injection_first_positioning_on_live_surfaces():
    skill = client.get(WELL_KNOWN_SKILL).text
    about_md = client.get("/about.md").text
    about_html = client.get("/about").text
    docs_html = client.get("/docs").text
    docs_md = client.get("/docs.md").text
    llms = client.get("/llms.txt").text
    agents = client.get("/agents.md").text
    for body, label in (
        (skill, "skill"),
        (about_md, "about.md"),
        (about_html, "about"),
        (docs_html, "docs"),
        (docs_md, "docs.md"),
        (llms, "llms.txt"),
        (agents, "agents.md"),
    ):
        assert INJECTION_BEFORE_READ in body, label
        assert "Injection risk" in body, label
        assert "fail-open" in body.lower(), label
        assert "fail-flagged" in body.lower(), label
        assert "gates_relaxed" in body, label


def test_openapi_exposes_per_row_gates_relaxed_not_search_meta():
    spec = client.get("/openapi.json").json()
    ranked = spec["components"]["schemas"]["RankedResult"]["properties"]["gates_relaxed"]
    assert ranked["type"] == "boolean"
    assert "gates_relaxed" in ranked["description"]
    assert "SearchMeta" in ranked["description"]
    assert "gates_relaxed" not in spec["components"]["schemas"]["SearchMeta"]["properties"]
    assert "gates_relaxed" in spec["info"]["description"]
    assert "gates_relaxed" in spec["paths"]["/v1/search"]["post"]["description"]
    for path in ("/docs", "/developers", "/developers.md", "/"):
        assert "gates_relaxed" in client.get(path).text, path


def test_ui_fixed_snip():
    app_js = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const UI_MODE = "snip"' in app_js
    assert "mode: UI_MODE" in app_js
    assert 'const UI_MODE = "deep"' not in app_js


def test_live_surfaces_do_not_claim_api_default_deep():
    stale = (
        "both default to deep",
        "api also defaults to",
        "default `mode=deep`",
        "default mode=deep",
        "mode=deep` (default",
        "mode=deep (default",
    )
    for path in PUBLIC_PROSE_PATHS:
        body = client.get(path, follow_redirects=True).text.lower()
        for phrase in stale:
            assert phrase not in body, f"{path} still claims API default deep: {phrase}"

    for extra in (
        ROOT / "README.md",
        ROOT / "apps" / "web" / "docs.html",
        ROOT / "skills" / "agent-seek" / "SKILL.md",
        ROOT / "skills" / "agent-seek" / "reference.md",
    ):
        text = extra.read_text(encoding="utf-8").lower()
        for phrase in stale:
            assert phrase not in text, f"{extra.name} still claims API default deep: {phrase}"


def test_llms_txt_has_discovery_map():
    body = client.get("/llms.txt").text
    assert re.search(r"(?im)^## Discovery map", body)
    assert "one public agent entry" in body.lower() or "start here" in body.lower()
    for catalog in (
        "/.well-known/api-catalog",
        "/.well-known/ard.json",
        "/.well-known/agent-card.json",
        "/.well-known/mcp/server-card.json",
        "/.well-known/agent-skills/index.json",
    ):
        assert catalog in body
    assert WELL_KNOWN_SKILL in body
