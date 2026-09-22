---
title: Agent Seek privacy
description: How Agent Seek handles search queries, API keys, and upstream providers.
canonical: /privacy
last-updated: 2026-09-22
---

# Agent Seek privacy

This privacy page describes how the **Agent Seek** prototype handles information as of version 0.1.39. Agent Seek is operated by Git Maxd (Queen Creek, Arizona). It is a search proxy with a ranking layer — not an advertising network and not a consumer account product.

## What we process

**Search queries.** When you submit a query on the website or `POST /v1/search`, the text of `q` (and options such as `k`, `max_candidates`, `mode`) is sent to this service so it can discover and rank results. The same query is forwarded to **You.com** (discover) and, when ranking is on, to **TypeSafe** (Jev / System One). We do not append a user profile or advertising identifier. Do not put secrets, passwords, or personal health data in `q`.

**API keys.** `AGENT_SEEK_API_KEY` authenticates agents. Send it only in `Authorization` or `X-API-Key`. The server compares it to the configured secret and does not write keys to application logs by design. `/config.js` may inject a same-origin UI key for the demo page; that file is disallowed in `robots.txt` and must not be treated as a public credential dump. `robots.txt` also `Disallow: /v1/` for training crawlers, with an explicit `Allow: /v1/sandbox` (and `/v1/sandbox/`) above that rule so the zero-auth sandbox stays crawlable. Upstream keys (`YDC_API_KEY`, `TYPESAFE_API_KEY`) never leave the server and are never returned in API or HTML responses.

**Results.** Titles, URLs, and snippets come from You.com (and, in `mode=deep`, from fetched page text). We cache **discover** payloads on the server filesystem for a short TTL to control cost. Ranking is recomputed. You can force a discover cache miss with `nocache=true`. Cache entries are query-derived, not a cross-user identity graph.

**Technical metadata.** When `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled` at deploy), the live host may see your IP address for a lifetime per-IP demo quota shared by REST `/v1/search`, `/api/v1/search`, and MCP `search_web` (default 5 searches, Upstash `INCR`, no TTL). Exhausted calls return `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. Unauthenticated MCP helper tools are not counted against that quota. There is also an optional Upstash burst limit (default 60 requests per minute per client IP when Redis is configured); that `429` may include `Retry-After`. Local/dev applies neither unless demo mode is enabled and the Upstash env vars are set. We do not sell logs. There are no third-party marketing pixels on the search UI.

## What we do not do

- We do not create end-user accounts or store passwords.
- We do not sell query streams or build advertising profiles.
- We do not use search contents to train Agent Seek’s own ranking model (Jev is a third-party judge).
- We do not claim that You.com or TypeSafe will delete your query on a custom schedule — their policies apply once the request leaves this host.

## Upstream processors

- [You.com privacy](https://you.com/legal/privacy) — web search / discover.
- TypeSafe / Jev — ranking judgments on titles, URLs, snippets, and (deep mode) extracted page text.

If you need a query forgotten on this host, email [131803031+Gitmaxd@users.noreply.github.com](mailto:131803031+Gitmaxd@users.noreply.github.com) with the approximate time and the query text. Local self-host operators control their own cache directory and `.env`.

## Cookies and tracking

The search UI does not set an analytics cookie. It is a static page plus `POST /v1/search`.

## Children

Agent Seek is a developer / agent prototype, not directed at children under 13 (or under 16 where that is the digital-consent age).

## Changes

Material changes will be reflected on this page and in the changelog. Questions: [/contact](/contact).
