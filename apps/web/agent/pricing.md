---
title: Agent Seek pricing
description: Free prototype plans, feature breakdown, rate limits, and self-serve access. No paid checkout.
canonical: /pricing.md
last-updated: 2026-09-22
---

# Agent Seek pricing

Agent Seek is a **free prototype**. There is no paid plan, no usage invoice from this host, no credit-card checkout, and **no contact-sales form**. You still incur whatever You.com and TypeSafe bill for the upstream calls this service makes on your behalf when you self-host.

## Plan tiers

| Plan | Price | Who it is for | How to start | Rate limit | Discover cap |
| --- | --- | --- | --- | --- | --- |
| **Sandbox** | **$0** | Agents inspecting the contract | `GET /health`, `GET /v1`, `GET /v1/sandbox` — zero auth | not throttled | n/a (canned body) |
| **Prototype** | **$0** | Live demo on this host | Public `AS_…` Bearer (same as `/config.js`) or optional OAuth DCR | When `AGENT_SEEK_DEMO_MODE=enabled`: 5 searches / IP lifetime shared by REST and MCP `search_web` (no reset); optional 60 req / min burst | 100 candidates / query |
| **Self-host** | **$0** from us | You run the repo | Set `AGENT_SEEK_API_KEY` in `.env` | Off unless you set Upstash | 100 (code hard cap) |

There is no Team, Business, or Enterprise SKU. If a future paid tier appears it will be listed here with a USD price, a feature matrix, and a Sunset note — not a “contact us” cell.

## Feature breakdown

| Feature | Sandbox | Prototype | Self-host |
| --- | --- | --- | --- |
| Google-simple search UI | yes (this host) | yes | yes |
| `POST /v1/search` / `GET /v1/search` | example only | yes | yes |
| `mode=snip` (API/MCP default) | example | yes | yes |
| `mode=deep` (opt-in) | example | yes | yes |
| MCP Streamable HTTP (`/mcp`) | tools/list yes | yes | yes |
| OAuth 2.0 + PKCE S256 | yes (anonymous / DCR) | yes | yes |
| Shared API key | local `.env` only | public demo `AS_…` Bearer (not a secret) | you set it |
| OpenAPI 3.1 / Swagger / ReDoc | yes | yes | yes |
| SLA / uptime contract | no | no | no |
| Markup on You.com / Jev | none | none | none (you pay providers) |

## Usage limits

- **k:** 1–25 (default 10)
- **max_candidates:** 1–100 (default 50). The service never requests more than 100 discover hits.
- **Website demo quota:** off unless `AGENT_SEEK_DEMO_MODE=enabled` (code default is `disabled`; the live host sets `enabled` at deploy). Then REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a **lifetime per-IP** allowance (default 5, Upstash `INCR`, **no TTL**). The HTML UI uses that same allowance. After it is used, `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and **no** `Retry-After`. Also off when `AGENT_SEEK_DEMO_SEARCH_LIMIT=0` or Upstash is unset. Unauthenticated MCP helper tools do not consume this quota.
- **Burst rate limit:** optional Upstash Redis REST sliding window, **per client IP** (default 60/min), on search and MCP `search_web`. Off when `UPSTASH_REDIS_REST_URL` or `UPSTASH_REDIS_REST_TOKEN` is empty. Health, sandbox, docs, and well-known discovery are not throttled. Responses include RFC `RateLimit` and `RateLimit-Policy`. Burst `429` is `application/problem+json` with `code=RATE_LIMITED` and may include `Retry-After`. Redis errors while enabled fail closed (`503`).
- **Call timeouts:** You.com ≤ 8s, Jev ≤ 8s, deep page fetch ≤ 5s per call. There is no whole-request timeout.

Default discover cost is on the order of **You.com ~$0.005 per query** plus Jev cascade spend on the admitted set (Stage A on candidates, Stage B on survivors). Agent Seek does not add a markup or invoice that spend.

## How to get access (self-serve)

No sales form. Copy the public demo Bearer for live search; do not wait on email.

1. **Zero-auth:** call [`GET /v1/sandbox`](/v1/sandbox) and [`GET /openapi.json`](/openapi.json).
2. **Live demo Bearer:** `Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI` (public; same as `/config.js`). Burns operator quota + per-IP demo limit. Walkthrough: [auth.md](/auth.md).
3. **Local key:** `cp .env.example .env`, set `AGENT_SEEK_API_KEY` (and your own YDC / TypeSafe keys), run `uvicorn apps.api.main:app --port 8787`.
4. **Optional / advanced — OAuth:** `POST /oauth2/register` or `POST /agent/identity` with `{"type":"anonymous"}`. You do not need OAuth to try the live demo.

## What is not included

- Generated answers / chat
- Unbounded crawl
- SLA, refunds, or uptime credits (there is nothing to refund)
- Metered billing or overage fees (there is no bill)

See [Agent Seek API](/developers), [auth.md](/auth.md), and [versioning](/docs/versioning.md).
