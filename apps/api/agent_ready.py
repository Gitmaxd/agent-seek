"""Phase 1 agent-ready surfaces: discovery files, catalogs, markdown pages."""
from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.responses import Response as StarletteResponse

from packages.core.pipeline import AGENT_SEEK_VERSION

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "apps" / "web"
AGENT_DIR = WEB_DIR / "agent"
SKILL_PATH = ROOT / "skills" / "agent-seek" / "SKILL.md"

LASTMOD = date(2026, 9, 20).isoformat()
CONTACT_EMAIL = "131803031+Gitmaxd@users.noreply.github.com"
ORG_NAME = "Git Maxd"
PUBLIC_ORIGIN = os.environ.get("AGENT_SEEK_PUBLIC_ORIGIN", "https://agentseek.dev").rstrip("/")

SITEMAP_PATHS = (
    "/",
    "/about",
    "/about.md",
    "/agents.md",
    "/auth.md",
    "/contact",
    "/contact.md",
    "/developers",
    "/developers.md",
    "/docs",
    "/docs.md",
    "/eval",
    "/eval.md",
    "/index.md",
    "/llms.txt",
    "/docs/llms.txt",
    "/api/llms.txt",
    "/developers/llms.txt",
    "/openapi.json",
    "/v1",
    "/v1/sandbox",
    "/api",
    "/mcp",
    "/.well-known/mcp/server-card.json",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/agent-card.json",
    "/pricing",
    "/pricing.md",
    "/privacy",
    "/privacy.md",
    "/.well-known/agent-skills/agent-seek/SKILL.md",
    "/api/docs",
    "/api/docs.md",
    "/docs/versioning.md",
    "/docs/auth.md",
)

AI_CRAWLERS = (
    "GPTBot",
    "ClaudeBot",
    "OAI-SearchBot",
    "Claude-SearchBot",
    "PerplexityBot",
    "ChatGPT-User",
    "Claude-User",
    "Perplexity-User",
    "Google-Extended",
    "ora-agent",
    "DeepSeekBot",
)

# User-Agents that receive the markdown homepage even when they send Accept: text/html.
AI_BOT_USER_AGENTS = (
    "GPTBot",
    "ClaudeBot",
    "ChatGPT-User",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
    "ora-agent",
    "DeepSeekBot",
    "OAI-SearchBot",
    "Claude-SearchBot",
    "Perplexity-User",
    "Claude-User",
)

MARKDOWN_404 = """# Not found

This path does not exist on Agent Seek.

Try [the homepage](/), [product docs](/docs), [llms.txt](/llms.txt), or [the sitemap](/sitemap.xml).
"""

HTML_404 = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Not found — Agent Seek</title>
  <meta name="robots" content="noindex" />
</head>
<body>
  <h1>Not found</h1>
  <p>This path does not exist on Agent Seek.</p>
  <p>Try <a href="/">the homepage</a>, <a href="/docs">docs</a>, <a href="/llms.txt">llms.txt</a>, or <a href="/sitemap.xml">the sitemap</a>.</p>
</body>
</html>
"""


def origin_from(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def publisher_host(request: Request) -> str:
    host = request.url.hostname or urlparse(origin_from(request)).hostname or "localhost"
    return host


def read_agent(name: str) -> str:
    return (AGENT_DIR / name).read_text(encoding="utf-8")


def _strip_frontmatter(source: str) -> str:
    lines = source.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines[1:].index("---") + 1
            return "\n".join(lines[end + 1 :]).lstrip("\n") + ("\n" if source.endswith("\n") else "")
        except ValueError:
            return source
    return source


def prefers_markdown(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "text/markdown" not in accept:
        return False
    md = accept.find("text/markdown")
    html_i = accept.find("text/html")
    return html_i == -1 or md < html_i


def is_ai_bot_ua(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    if not ua:
        return False
    return any(bot.lower() in ua for bot in AI_BOT_USER_AGENTS)


def markdown_response(body: str, *, extra_headers: dict[str, str] | None = None) -> PlainTextResponse:
    headers = {"Vary": "Accept"}
    if extra_headers:
        headers.update(extra_headers)
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


def discovery_link_header(origin: str) -> str:
    return ", ".join(
        [
            f'<{origin}/sitemap.xml>; rel="sitemap"',
            f'<{origin}/llms.txt>; rel="describedby"; type="text/plain"',
            f'<{origin}/index.md>; rel="alternate"; type="text/markdown"',
            f'<{origin}/openapi.json>; rel="service-desc"; type="application/openapi+json"',
            f'<{origin}/.well-known/api-catalog>; rel="api-catalog"; type="application/linkset+json"',
            f'<{origin}/.well-known/ard.json>; rel="ard"; type="application/json"',
            f'<{origin}/.well-known/agent-skills/index.json>; rel="describedby"; type="application/json"',
            f'<{origin}/.well-known/mcp/server-card.json>; rel="describedby"; type="application/json"',
            f'<{origin}/.well-known/oauth-protected-resource>; rel="oauth-protected-resource"; type="application/json"',
            f'<{origin}/auth.md>; rel="alternate"; type="text/markdown"',
            f'<{origin}/v1>; rel="service"; type="application/json"',
            f'<{origin}/api>; rel="service"; type="application/json"',
            f'<{origin}/docs/llms.txt>; rel="describedby"; type="text/plain"',
            f'<{origin}/api/llms.txt>; rel="describedby"; type="text/plain"',
            f'<{origin}/.well-known/agent-card.json>; rel="describedby"; type="application/json"',
        ]
    )


def homepage_headers(origin: str) -> dict[str, str]:
    return {"Link": discovery_link_header(origin), "Vary": "Accept, User-Agent"}


def _robots_path_rules() -> list[str]:
    # Allow sandbox above Disallow: /v1/ so AI crawlers can fetch the advertised
    # zero-auth GET /v1/sandbox. Paid/search /v1/ paths stay disallowed.
    return [
        "Allow: /",
        "Disallow: /config.js",
        "Allow: /v1/sandbox",
        "Allow: /v1/sandbox/",
        "Disallow: /v1/",
    ]


def robots_txt(origin: str) -> str:
    path_rules = _robots_path_rules()
    lines = [
        "# Agent Seek robots — AI crawlers welcome on public docs and GET /v1/sandbox.",
        "User-agent: *",
        *path_rules,
        "Disallow: /admin",
        "Disallow: /internal",
        "Content-Signal: search=yes, ai-train=yes",
        "",
    ]
    for bot in AI_CRAWLERS:
        lines.extend([f"User-agent: {bot}", *path_rules, ""])
    lines.append(f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml")
    lines.append("")
    return "\n".join(lines)


def sitemap_xml(origin: str) -> str:
    urls = "\n".join(
        f"  <url>\n    <loc>{origin}{path}</loc>\n    <lastmod>{LASTMOD}</lastmod>\n  </url>"
        for path in SITEMAP_PATHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )


def skill_bytes() -> bytes:
    return SKILL_PATH.read_bytes()


def skill_digest() -> str:
    return "sha256:" + hashlib.sha256(skill_bytes()).hexdigest()


def skill_description() -> str:
    text = SKILL_PATH.read_text(encoding="utf-8")
    m = re.search(r"^description:\s*>?\s*\n?(.*?)(?:\n---|\n# )", text, re.S | re.M)
    if m:
        desc = " ".join(m.group(1).split())
        if desc:
            return desc[:400]
    return (
        "Web results are scored for prompt injection before the agent reads them "
        "(signal prompt_injection; UI: Injection risk). "
        "If hard gates empty the scored list, restored rows set gates_relaxed true. "
        "Use Agent Seek for ranked web URLs/snippets (You.com + Jev). "
        "Default mode=snip (title/URL/snippet; cheaper/faster). "
        "Pass mode=deep for Stage A survivor fetch (cap 12)."
    )


def ard_catalog(origin: str, host: str) -> dict[str, Any]:
    trust = {"identity": origin, "identityType": "https"}
    skill_url = f"{origin}/.well-known/agent-skills/agent-seek/SKILL.md"
    api_url = f"{origin}/openapi.json"
    return {
        "@context": "https://agenticresourcediscovery.org/context/v1",
        "specVersion": "1.0",
        "host": {
            "displayName": "Agent Seek",
            "identifier": origin,
        },
        "entries": [
            {
                "identifier": f"urn:air:{host}:api:search",
                "displayName": "Agent Seek Search API",
                "type": "application/openapi+json",
                "url": api_url,
                "description": (
                    "Less SEO. More signal. Ranked sources: You.com discover + "
                    "TypeSafe Jev cascade. The caller writes the answer. "
                    "Default mode=snip (title/URL/snippet; cheaper/faster). "
                    "Pass mode=deep for Stage A survivor fetch (cap 12). "
                    "POST /v1/search with OAuth search:read or Bearer AGENT_SEEK_API_KEY."
                ),
                "capabilities": ["web_search", "ranked_results"],
                "representativeQueries": [
                    "search the web for high-relevance sources about a topic",
                    "rank web results with less SEO spam",
                    "get scored URLs and snippets for a research query",
                ],
                "tags": ["search", "api", "agents"],
                "version": AGENT_SEEK_VERSION,
                "updatedAt": f"{LASTMOD}T00:00:00Z",
                "trustManifest": trust,
            },
            {
                "identifier": f"urn:air:{host}:skill:agent-seek",
                "displayName": "agent-seek",
                "type": "application/ai-skill+md",
                "url": skill_url,
                "description": skill_description(),
                "capabilities": ["agent_skill"],
                "representativeQueries": [
                    "how do I call Agent Seek from an agent",
                    "Agent Seek skill for web search with Jev ranking",
                ],
                "tags": ["skill", "search"],
                "version": AGENT_SEEK_VERSION,
                "updatedAt": f"{LASTMOD}T00:00:00Z",
                "trustManifest": trust,
            },
            {
                "identifier": f"urn:air:{host}:mcp:agent-seek",
                "displayName": "Agent Seek MCP",
                "type": "application/json",
                "url": f"{origin}/.well-known/mcp/server-card.json",
                "description": (
                    "Streamable HTTP MCP server exposing search_web, get_service_health, "
                    "get_api_docs, and list_search_capabilities."
                ),
                "capabilities": ["mcp", "web_search"],
                "representativeQueries": [
                    "Agent Seek MCP server for ranked web search",
                    "search the web via MCP Streamable HTTP",
                ],
                "tags": ["mcp", "search"],
                "version": AGENT_SEEK_VERSION,
                "updatedAt": f"{LASTMOD}T00:00:00Z",
                "trustManifest": trust,
            },
        ],
    }


def api_catalog_linkset(origin: str) -> dict[str, Any]:
    return {
        "linkset": [
            {
                "anchor": f"{origin}/.well-known/api-catalog",
                "item": [
                    {
                        "href": f"{origin}/v1/search",
                        "type": "application/json",
                    }
                ],
                "service-desc": [
                    {
                        "href": f"{origin}/openapi.json",
                        "type": "application/openapi+json",
                    }
                ],
                "service-doc": [
                    {
                        "href": f"{origin}/docs",
                        "type": "text/html",
                    },
                    {
                        "href": f"{origin}/docs.md",
                        "type": "text/markdown",
                    },
                    {
                        "href": f"{origin}/auth.md",
                        "type": "text/markdown",
                    },
                    {
                        "href": f"{origin}/v1",
                        "type": "application/json",
                    },
                    {
                        "href": f"{origin}/api",
                        "type": "application/json",
                    },
                    {
                        "href": f"{origin}/docs/versioning.md",
                        "type": "text/markdown",
                    },
                ],
                "status": [
                    {
                        "href": f"{origin}/health",
                        "type": "application/json",
                    }
                ],
            }
        ]
    }


def agent_skills_index(origin: str) -> dict[str, Any]:
    return {
        "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
        "skills": [
            {
                "name": "agent-seek",
                "description": skill_description(),
                "type": "skill-md",
                "url": f"{origin}/.well-known/agent-skills/agent-seek/SKILL.md",
                "digest": skill_digest(),
            }
        ],
    }


def json_ld(origin: str) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareApplication",
                "@id": f"{origin}/#app",
                "name": "Agent Seek",
                "applicationCategory": "SearchApplication",
                "operatingSystem": "Web",
                "url": f"{origin}/",
                "description": (
                    "Less SEO. More signal. Agent Seek returns ranked sources; "
                    "the caller writes the answer. You.com discover plus TypeSafe Jev "
                    "cascade ranking. Google-simple UI and POST /v1/search."
                ),
                "softwareVersion": AGENT_SEEK_VERSION,
                "offers": {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": "USD",
                    "category": "Free",
                    "description": "Free prototype. Operator-issued API key. See /pricing.",
                    "url": f"{origin}/pricing",
                },
                "author": {"@id": f"{origin}/#org"},
                "publisher": {"@id": f"{origin}/#org"},
                "sameAs": [
                    "https://github.com/Gitmaxd/agent-seek",
                    "https://github.com/Gitmaxd",
                ],
            },
            {
                "@type": "Service",
                "@id": f"{origin}/#service",
                "name": "Agent Seek ranked web search",
                "serviceType": "Web search API",
                "provider": {"@id": f"{origin}/#org"},
                "url": f"{origin}/v1/search",
                "description": (
                    "HTTP API and MCP tools that return ranked sources "
                    "(title, URL, snippet, score). The caller writes the answer."
                ),
                "areaServed": "Worldwide",
                "termsOfService": f"{origin}/privacy",
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{origin}/#breadcrumbs",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "Agent Seek",
                        "item": f"{origin}/",
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "Agent Seek docs",
                        "item": f"{origin}/docs",
                    },
                    {
                        "@type": "ListItem",
                        "position": 3,
                        "name": "Agent Seek API",
                        "item": f"{origin}/developers",
                    },
                ],
            },
            {
                "@type": "WebSite",
                "@id": f"{origin}/#website",
                "name": "Agent Seek",
                "url": f"{origin}/",
                "description": (
                    "Less SEO. More signal. Ranked sources (You.com + Jev); "
                    "the caller writes the answer."
                ),
                "publisher": {"@id": f"{origin}/#org"},
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": {
                        "@type": "EntryPoint",
                        "urlTemplate": f"{origin}/v1/search?q={{search_term_string}}",
                    },
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@type": "Organization",
                "@id": f"{origin}/#org",
                "name": ORG_NAME,
                "url": origin,
                "email": CONTACT_EMAIL,
                "sameAs": [
                    "https://github.com/Gitmaxd",
                    "https://github.com/Gitmaxd/agent-seek",
                ],
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Queen Creek",
                    "addressRegion": "AZ",
                    "addressCountry": "US",
                },
                "contactPoint": {
                    "@type": "ContactPoint",
                    "contactType": "developer support",
                    "email": CONTACT_EMAIL,
                    "url": f"{origin}/contact",
                },
            },
            {
                "@type": "FAQPage",
                "@id": f"{origin}/#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "When should an agent use Agent Seek?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": (
                                "When you need a small set of high-relevance URLs and snippets "
                                "for research or RAG, not a generated answer."
                            ),
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How do I authenticate?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "OAuth 2.0 (search:read) or Authorization: Bearer $AGENT_SEEK_API_KEY. See /auth.md.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "What does it cost?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "The prototype is free. Self-host operators pay You.com and TypeSafe directly.",
                        },
                    },
                ],
            },
        ],
    }


_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def markdown_to_html(source: str) -> str:
    """Minimal markdown subset for our controlled agent/*.md files."""
    lines = source.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines[1:].index("---") + 1
            lines = lines[end + 1 :]
        except ValueError:
            pass

    def inline(text: str) -> str:
        parts: list[str] = []
        last = 0
        for m in _MD_LINK.finditer(text):
            parts.append(html.escape(text[last : m.start()]))
            parts.append(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>')
            last = m.end()
        parts.append(html.escape(text[last:]))
        out = "".join(parts)
        out = _MD_BOLD.sub(r"<strong>\1</strong>", out)
        out = _MD_CODE.sub(r"<code>\1</code>", out)
        return out

    chunks: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("```"):
            fence = [""]
            i += 1
            while i < n and not lines[i].startswith("```"):
                fence.append(html.escape(lines[i]))
                i += 1
            i += 1
            chunks.append("<pre><code>" + "\n".join(fence).lstrip("\n") + "</code></pre>")
            continue
        if re.match(r"^#{1,3} ", line):
            level = len(line) - len(line.lstrip("#"))
            chunks.append(f"<h{level}>{inline(line[level + 1 :])}</h{level}>")
            i += 1
            continue
        if line.startswith("| ") and i + 1 < n and set(lines[i + 1].replace("|", "").replace("-", "").replace(" ", "")) == set():
            rows = []
            while i < n and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                rows.append(cells)
                i += 1
            head, body = rows[0], rows[2:]
            thead = "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
            tbody = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
            chunks.append(f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>")
            continue
        if line.startswith("- "):
            items = []
            while i < n and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            chunks.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r"^\d+\. ", line):
            items = []
            while i < n and re.match(r"^\d+\. ", lines[i]):
                items.append(f"<li>{inline(re.sub(r'^\d+\. ', '', lines[i]))}</li>")
                i += 1
            chunks.append("<ol>" + "".join(items) + "</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].startswith(("#", "-", "|", "```")) and not re.match(r"^\d+\. ", lines[i]):
            para.append(lines[i])
            i += 1
        chunks.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(chunks)


def _branded_title(title: str) -> str:
    return title if "Agent Seek" in title else f"{title} — Agent Seek"


def _header_nav_link(href: str, label: str, current: str) -> str:
    key = href.strip("/")
    is_cur = bool(current) and current == key
    cls = "site-header-docs is-current" if is_cur else "site-header-docs"
    extra = ' aria-current="page"' if is_cur else ""
    return f'<a class="{cls}" href="{href}"{extra}>{label}</a>'


def page_html(
    title: str,
    body_html: str,
    *,
    origin: str,
    canonical_path: str,
    description: str,
    body_class: str = "",
    nav_current: str = "",
) -> str:
    branded = _branded_title(title)
    canon = f"{PUBLIC_ORIGIN}{canonical_path}"
    md_href = canonical_path if canonical_path.endswith(".md") else f"{canonical_path}.md"
    body_attr = f' class="{html.escape(body_class)}"' if body_class else ""
    nav = "\n      ".join(
        [
            _header_nav_link("/eval", "Eval", nav_current),
            _header_nav_link("/docs", "Docs", nav_current),
            _header_nav_link("/developers", "API", nav_current),
        ]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(branded)}</title>
  <meta name="description" content="{html.escape(description)}" />
  <meta name="robots" content="index,follow" />
  <link rel="canonical" href="{html.escape(canon)}" />
  <link rel="alternate" type="text/markdown" href="{html.escape(md_href)}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Agent Seek" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:title" content="{html.escape(branded)}" />
  <meta property="og:description" content="{html.escape(description)}" />
  <meta property="og:url" content="{html.escape(canon)}" />
  <meta property="og:image" content="{html.escape(PUBLIC_ORIGIN)}/static/og.svg" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{html.escape(branded)}" />
  <meta name="twitter:description" content="{html.escape(description)}" />
  <meta name="twitter:image" content="{html.escape(PUBLIC_ORIGIN)}/static/og.svg" />
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
    .docs-wrap {{ max-width: 720px; margin: 0 auto; padding: 40px 24px 96px; }}
    .docs-wrap h1 {{ font-size: 1.75rem; font-weight: 400; letter-spacing: -0.02em; margin: 0 0 12px; }}
    .docs-wrap h2 {{ font-size: 1.05rem; font-weight: 500; margin: 32px 0 12px; }}
    .docs-wrap h3 {{ font-size: 0.95rem; font-weight: 500; margin: 24px 0 8px; }}
    .docs-wrap p, .docs-wrap li, .docs-wrap td, .docs-wrap th {{ color: var(--muted); font-size: 0.925rem; line-height: 1.6; }}
    .docs-wrap p {{ margin: 0 0 10px; }}
    .docs-wrap ul, .docs-wrap ol {{ margin: 0 0 12px; padding-left: 1.2em; }}
    .docs-wrap a {{ color: var(--title); text-decoration: none; }}
    .docs-wrap a:hover {{ text-decoration: underline; }}
    .docs-wrap code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.85em; background: var(--chip-bg); padding: 1px 5px; border-radius: 3px; }}
    .docs-wrap pre {{ background: #f8f9fa; padding: 14px 16px; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; line-height: 1.5; margin: 12px 0 16px; }}
    .docs-wrap pre code {{ background: transparent; padding: 0; }}
    .docs-wrap table {{ border-collapse: collapse; width: 100%; margin: 12px 0 16px; font-size: 0.85rem; }}
    .docs-wrap th, .docs-wrap td {{ text-align: left; padding: 6px 8px; vertical-align: top; }}
    .docs-wrap th {{ color: var(--text); font-weight: 500; }}
  </style>
</head>
<body{body_attr}>
  <header class="site-header">
    <a class="site-header-title" href="/" style="text-decoration:none;color:inherit">Agent Seek</a>
    <div class="site-header-actions">
      {nav}
      <a class="site-header-github" href="https://github.com/Gitmaxd/agent-seek" target="_blank" rel="noopener noreferrer" aria-label="GitHub repository">
      <svg class="octicon" viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
      </svg>
    </a>
    </div>
  </header>
  <main class="docs-wrap">
{body_html}
    <nav class="docs-links" aria-label="Agent Seek pages" style="margin-top:40px;padding-top:20px;box-shadow:0 -1px 0 rgba(32,33,36,0.06);font-size:0.9rem">
      <a href="/" style="margin-right:18px">Search</a>
      <a href="/eval" style="margin-right:18px">Eval</a>
      <a href="/docs" style="margin-right:18px">Docs</a>
      <a href="/developers" style="margin-right:18px">API</a>
      <a href="/auth.md" style="margin-right:18px">Auth</a>
      <a href="/about" style="margin-right:18px">About</a>
      <a href="/.well-known/agent-skills/agent-seek/SKILL.md" style="margin-right:18px">Skill</a>
      <a href="/llms.txt">llms.txt</a>
    </nav>
  </main>
</body>
</html>
"""


HOME_AGENT_CALLOUT_HTML = """
      <p class="agent-callout">
      Agents: install the
      <a href="/.well-known/agent-skills/agent-seek/SKILL.md">skill</a>,
      read <a href="/llms.txt">/llms.txt</a>, then
      <a href="/auth.md">/auth.md</a>
      · <a href="/.well-known/mcp/server-card.json">MCP</a> or <code>POST /v1/search</code>
      · <a href="/docs">/docs</a>
      · sandbox <a href="/v1/sandbox"><code>GET /v1/sandbox</code></a>.
    </p>
"""

HOME_PROSE_HTML = """
  <section class="home-prose" id="home-prose" aria-label="About Agent Seek">
    <h2>What it is</h2>
    <p>
      Less SEO. More signal. Agent Seek is a prototype web search service.
      You.com discovers candidate pages; TypeSafe Jev cascade-ranks them.
      Agent Seek returns ranked sources; the caller writes the answer. You get
      a short scored list (title, URL, snippet, score, flags, signals) instead
      of raw SERP noise. Web results are scored for prompt injection before the
      agent reads them (<code>prompt_injection</code>; UI: <strong>Injection risk</strong>).
      If hard gates empty the scored list, pre-gate ranking is restored and each
      restored row has <code>gates_relaxed: true</code> (relaxed-safety response;
      not a SearchMeta field).
      People use the Google-simple search box above. Agents
      call <code>POST /v1/search</code> or MCP. Hard cap: 100 discover
      candidates per query (default 50 in, top 10 out).
      Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches.
    </p>
    <h2>For agents</h2>
    <p>
      Start with the zero-auth sandbox at
      <a href="/v1/sandbox"><code>GET /v1/sandbox</code></a>
      to see the SearchResponse shape without a key and without calling
      You.com or Jev. Then install the
      <a href="/.well-known/agent-skills/agent-seek/SKILL.md">skill</a>,
      read <a href="/llms.txt">/llms.txt</a>, and authenticate via
      <a href="/auth.md">auth</a>
      (OAuth 2.0 <code>search:read</code> or
      <code>Bearer $AGENT_SEEK_API_KEY</code>). The live host does not mint
      self-serve API keys; use OAuth dynamic registration, an operator-issued
      key, or a local <code>AGENT_SEEK_API_KEY</code>. Agent Seek returns
      ranked sources; you write the answer.
    </p>
    <h2>API entry points</h2>
    <p>
      <a href="/docs">Docs</a>,
      <a href="/developers">API</a>,
      <a href="/openapi.json">OpenAPI</a>,
      <a href="/auth.md">auth</a>,
      <a href="/mcp">MCP</a>
      (<a href="/.well-known/mcp/server-card.json">server card</a>),
      <a href="/v1/sandbox">sandbox</a>,
      and the <a href="/.well-known/agent-skills/agent-seek/SKILL.md">skill</a>.
      Machine index: <a href="/llms.txt">/llms.txt</a>.
      Liveness: <a href="/health"><code>GET /health</code></a>.
    </p>
  </section>
"""

HOME_FOOTER_HTML = """
  <footer class="site-footer" id="site-footer">
    <nav aria-label="Site">
      <a href="/about">About</a>
      <a href="/eval">Eval</a>
      <a href="/docs">Docs</a>
      <a href="/developers">API</a>
      <a href="/pricing">Pricing</a>
      <a href="/privacy">Privacy</a>
      <a href="/contact">Contact</a>
      <a href="/openapi.json">Agent Seek OpenAPI</a>
      <a href="/llms.txt">llms.txt</a>
      <a href="/.well-known/agent-skills/agent-seek/SKILL.md">Skill</a>
    </nav>
  </footer>
"""


def render_homepage(origin: str) -> str:
    index_path = WEB_DIR / "index.html"
    raw = index_path.read_text(encoding="utf-8") if index_path.exists() else "<html><body><h1>Agent Seek</h1></body></html>"
    seo_origin = PUBLIC_ORIGIN
    payload = json_ld(seo_origin)
    import json

    script = (
        '<script type="application/ld+json">\n'
        + json.dumps(payload, indent=2)
        + "\n</script>"
    )
    replacements = {
        "{{BASE_URL}}": seo_origin,
        "{{VERSION}}": AGENT_SEEK_VERSION,
        "{{JSON_LD}}": script,
        "{{HOME_AGENT_CALLOUT}}": HOME_AGENT_CALLOUT_HTML,
        "{{HOME_PROSE}}": HOME_PROSE_HTML,
        "{{HOME_FOOTER}}": HOME_FOOTER_HTML,
    }
    for k, v in replacements.items():
        raw = raw.replace(k, v)
    return raw


def agent_mode_document(origin: str) -> dict[str, Any]:
    """Structured homepage for ?mode=agent (not marketing HTML)."""
    return {
        "name": "Agent Seek",
        "mode": "agent",
        "version": AGENT_SEEK_VERSION,
        "description": (
            "Ranked web search for agents: You.com discover + TypeSafe Jev cascade. "
            "Default mode=snip (title/URL/snippet; cheaper/faster). "
            "Pass mode=deep for Stage A survivor fetch (cap 12; not a full-web crawl). "
            "Returns scored URLs and snippets. Does not write answers."
        ),
        "when_to_use": (
            "Need a small set of high-relevance web sources for research or RAG. "
            "Hard cap 100 discover candidates (default 50 in, top 10 out)."
        ),
        "default_mode": "snip",
        "modes": ["deep", "snip"],
        "deep_fetch_cap": 12,
        "signals": [
            "answerability",
            "authority",
            "on_topic",
            "states_sought_fact",
            "subject_match",
            "spam",
            "prompt_injection",
        ],
        "hard_gates": ["subject_match", "is_republisher", "prompt_injection"],
        "hard_gate_threshold": 0.55,
        "hard_gate_missing_parse": {
            "subject_match": "fail-open",
            "is_republisher": "fail-open",
            "prompt_injection": "fail-flagged",
        },
        "gates_relaxed": (
            "Per-result boolean. True when hard gates emptied the scored list "
            "and this row was restored from pre-gate ranking. Not a SearchMeta field."
        ),
        "endpoints": {
            "search": f"{origin}/v1/search",
            "search_alias": f"{origin}/api/v1/search",
            "discovery": f"{origin}/v1",
            "api_root": f"{origin}/api",
            "health": f"{origin}/health",
            "sandbox": f"{origin}/v1/sandbox",
            "openapi": f"{origin}/openapi.json",
            "mcp": f"{origin}/mcp",
            "docs": f"{origin}/docs",
            "developers": f"{origin}/developers",
            "auth": f"{origin}/auth.md",
            "versioning": f"{origin}/docs/versioning.md",
            "llms_txt": f"{origin}/llms.txt",
            "skill": f"{origin}/.well-known/agent-skills/agent-seek/SKILL.md",
            "mcp_server_card": f"{origin}/.well-known/mcp/server-card.json",
        },
        "onboarding": "GET /v1/sandbox (zero-auth) → install skill → read /llms.txt → auth via /auth.md → MCP or POST /v1/search",
        "authentication": {
            "methods": ["oauth2", "api_key"],
            "scopes": ["search:read", "mcp:invoke", "health:read"],
            "walkthrough": f"{origin}/auth.md",
            "protected_resource": f"{origin}/.well-known/oauth-protected-resource",
            "authorization_server": f"{origin}/.well-known/oauth-authorization-server",
            "self_serve": (
                "POST /oauth2/register or POST /agent/identity {\"type\":\"anonymous\"}. "
                "No contact-sales form."
            ),
        },
        "capabilities": [
            "ranked_web_search",
            "mcp_streamable_http",
            "oauth2_pkce_s256",
            "rfc9457_problem_json",
        ],
        "errors": "application/problem+json on API 4xx/5xx",
        "homepage_markdown": f"{origin}/index.md",
    }


def agent_card(origin: str) -> dict[str, Any]:
    """A2A agent card at /.well-known/agent-card.json."""
    return {
        "protocolVersion": "1.0",
        "name": "Agent Seek",
        "description": (
            "Less SEO. More signal. Ranked web search: You.com discover plus "
            "TypeSafe Jev cascade. Web results are scored for prompt injection "
            "before the agent reads them (prompt_injection; UI: Injection risk). "
            "If hard gates empty the scored list, restored rows set gates_relaxed true. "
            "Default mode=snip (title/URL/snippet; cheaper/faster). "
            "Pass mode=deep for Stage A survivor fetch (cap 12). "
            "Returns ranked sources (scored URLs and snippets); the caller writes the answer."
        ),
        "url": f"{origin}/mcp",
        "version": AGENT_SEEK_VERSION,
        "documentationUrl": f"{origin}/docs",
        "iconUrl": f"{origin}/static/og.svg",
        "provider": {
            "organization": ORG_NAME,
            "url": origin,
        },
        "supportedInterfaces": [
            {
                "url": f"{origin}/mcp",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
        },
        "defaultInputModes": ["text", "application/json"],
        "defaultOutputModes": ["text", "application/json"],
        "skills": [
            {
                "id": "search_web",
                "name": "search_web",
                "description": (
                    "Ranked web search via You.com discover and Jev cascade. "
                    "Web results are scored for prompt injection before the agent reads them. "
                    "If hard gates empty the scored list, restored rows set gates_relaxed true. "
                    "Default mode=snip (title/URL/snippet). Pass mode=deep for survivor fetch (cap 12)."
                ),
                "tags": ["search", "web", "ranking"],
                "examples": ["Search for Introducing System One Models Jev"],
            }
        ],
        "securitySchemes": {
            "oauth2": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": f"{origin}/oauth2/authorize",
                        "tokenUrl": f"{origin}/oauth2/token",
                        "scopes": {
                            "search:read": "Call ranked web search",
                            "mcp:invoke": "Call MCP tools",
                            "health:read": "Read health and docs",
                        },
                    }
                },
            },
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "AGENT_SEEK_API_KEY or OAuth access_token",
            },
        },
    }


def register_agent_ready(app: FastAPI) -> None:
    @app.get("/llms.txt", include_in_schema=False)
    async def llms_txt():
        return PlainTextResponse(read_agent("llms.txt"), media_type="text/plain; charset=utf-8")

    @app.get("/docs/llms.txt", include_in_schema=False)
    async def docs_llms_txt():
        return PlainTextResponse(read_agent("llms-docs.txt"), media_type="text/plain; charset=utf-8")

    @app.get("/api/llms.txt", include_in_schema=False)
    async def api_llms_txt():
        return PlainTextResponse(read_agent("llms-api.txt"), media_type="text/plain; charset=utf-8")

    @app.get("/developers/llms.txt", include_in_schema=False)
    async def developers_llms_txt():
        return PlainTextResponse(read_agent("llms-developers.txt"), media_type="text/plain; charset=utf-8")

    @app.get("/.well-known/agent-card.json", include_in_schema=False)
    @app.get("/.well-known/agent.json", include_in_schema=False)
    async def a2a_agent_card(request: Request):
        return JSONResponse(
            agent_card(origin_from(request)),
            media_type="application/json",
        )

    @app.get("/robots.txt", include_in_schema=False)
    async def robots(request: Request):
        return PlainTextResponse(robots_txt(origin_from(request)), media_type="text/plain; charset=utf-8")

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request):
        return Response(
            content=sitemap_xml(PUBLIC_ORIGIN),
            media_type="application/xml; charset=utf-8",
        )

    @app.get("/.well-known/ard.json", include_in_schema=False)
    async def ard_json(request: Request):
        return JSONResponse(ard_catalog(origin_from(request), publisher_host(request)))

    @app.get("/.well-known/ai-catalog.json", include_in_schema=False)
    async def ai_catalog(request: Request):
        return JSONResponse(ard_catalog(origin_from(request), publisher_host(request)))

    @app.get("/.well-known/agent-skills/index.json", include_in_schema=False)
    async def skills_index(request: Request):
        return JSONResponse(agent_skills_index(origin_from(request)))

    @app.get("/.well-known/agent-skills/agent-seek/SKILL.md", include_in_schema=False)
    async def skill_md():
        return markdown_response(SKILL_PATH.read_text(encoding="utf-8"))

    @app.api_route("/skills/agent-seek/SKILL.md", methods=["GET", "HEAD"], include_in_schema=False)
    async def skill_md_alias():
        return RedirectResponse(
            url="/.well-known/agent-skills/agent-seek/SKILL.md",
            status_code=308,
        )

    @app.api_route("/.well-known/api-catalog", methods=["GET", "HEAD"], include_in_schema=False)
    async def rfc9727_catalog(request: Request):
        import json

        origin = origin_from(request)
        headers = {
            "Content-Type": 'application/linkset+json;profile="https://www.rfc-editor.org/info/rfc9727"',
            "Link": f'<{origin}/.well-known/api-catalog>; rel="api-catalog"',
        }
        if request.method == "HEAD":
            return StarletteResponse(status_code=200, headers=headers)
        return Response(
            content=json.dumps(api_catalog_linkset(origin)).encode("utf-8"),
            headers=headers,
        )

    @app.get("/agents.md", include_in_schema=False)
    async def agents_md():
        return markdown_response(read_agent("agents.md"))

    @app.get("/auth.md", include_in_schema=False)
    async def auth_md():
        # Ora auth-md-exists requires a leading markdown heading (not YAML frontmatter).
        return markdown_response(_strip_frontmatter(read_agent("auth.md")))

    @app.get("/index.md", include_in_schema=False)
    async def index_md():
        return markdown_response(read_agent("index.md"))

    @app.get("/docs.md", include_in_schema=False)
    async def docs_md():
        return markdown_response(read_agent("docs.md"))

    @app.get("/api/docs.md", include_in_schema=False)
    async def api_docs_md():
        return markdown_response(read_agent("api-docs.md"))

    @app.get("/api/redoc.md", include_in_schema=False)
    async def api_redoc_md():
        return markdown_response(read_agent("api-docs.md"))

    @app.get("/docs/versioning.md", include_in_schema=False)
    async def versioning_md():
        return markdown_response(read_agent("versioning.md"))

    @app.get("/docs/auth.md", include_in_schema=False)
    async def docs_auth_md():
        return markdown_response(_strip_frontmatter(read_agent("auth.md")))

    @app.get("/developers.md", include_in_schema=False)
    async def developers_md():
        return markdown_response(read_agent("developers.md"))

    @app.get("/pricing.md", include_in_schema=False)
    async def pricing_md():
        return markdown_response(read_agent("pricing.md"))

    @app.get("/about.md", include_in_schema=False)
    async def about_md():
        return markdown_response(read_agent("about.md"))

    @app.get("/contact.md", include_in_schema=False)
    async def contact_md():
        return markdown_response(read_agent("contact.md"))

    @app.get("/privacy.md", include_in_schema=False)
    async def privacy_md():
        return markdown_response(read_agent("privacy.md"))

    def _html_or_md(
        md_name: str,
        title: str,
        path: str,
        description: str,
        *,
        human_body: str | None = None,
    ):
        """Serve humanized HTML for browsers; keep agent markdown at *.md unchanged."""

        async def _view(request: Request):
            source = read_agent(md_name)
            if prefers_markdown(request):
                return markdown_response(source)
            origin = origin_from(request)
            body = source
            if human_body:
                body_path = WEB_DIR / "human" / human_body
                if body_path.exists():
                    body_html = body_path.read_text(encoding="utf-8")
                    return HTMLResponse(
                        page_html(
                            title,
                            body_html,
                            origin=origin,
                            canonical_path=path,
                            description=description,
                        )
                    )
            return HTMLResponse(
                page_html(
                    title,
                    markdown_to_html(source),
                    origin=origin,
                    canonical_path=path,
                    description=description,
                )
            )

        return _view

    app.add_api_route("/about", _html_or_md("about.md", "About Agent Seek", "/about", "Who builds Agent Seek and what the prototype is for.", human_body="about.body.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/contact", _html_or_md("contact.md", "Contact Agent Seek", "/contact", "How to reach Git Maxd about Agent Seek keys and bugs.", human_body="contact.body.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/privacy", _html_or_md("privacy.md", "Agent Seek privacy", "/privacy", "How Agent Seek handles search queries and API keys.", human_body="privacy.body.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/pricing", _html_or_md("pricing.md", "Agent Seek pricing", "/pricing", "Free Agent Seek prototype. Operator-issued API key.", human_body="pricing.body.html"), methods=["GET"], include_in_schema=False)
    app.add_api_route("/developers", _html_or_md("developers.md", "Agent Seek API", "/developers", "Agent Seek API: ranked web results via POST /v1/search, OpenAPI, and Bearer AGENT_SEEK_API_KEY.", human_body="developers.body.html"), methods=["GET"], include_in_schema=False)

    from apps.api.eval_page import register_eval_page

    register_eval_page(app)
