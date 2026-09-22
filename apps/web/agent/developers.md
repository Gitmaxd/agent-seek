---
title: Agent Seek API
description: Agent Seek API — public AS_ Bearer live demo, local key, optional OAuth. POST /v1/search, OpenAPI, sandbox. No sales form.
canonical: /developers
last-updated: 2026-09-22
---

# Agent Seek API

The **Agent Seek API** is how agents and scripts get ranked sources without using the HTML UI. Less SEO. More signal. You.com discovers candidates; TypeSafe Jev cascade-ranks them; you receive scored JSON (`url`, `title`, `snippet`, `score`, `flags`, `signals`). The caller writes the answer. Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**).

There is **no contact-sales form** and no waitlist. Self-serve paths are live on this host.

## Self-serve access (do this first)

### Zero-auth (sandbox)

These need no key. Use them to confirm the API is reachable:

```bash
curl -sS https://agentseek.dev/health
curl -sS https://agentseek.dev/v1
curl -sS https://agentseek.dev/api
curl -sS https://agentseek.dev/v1/sandbox
curl -sS https://agentseek.dev/openapi.json
```

`GET /v1/sandbox` returns a canned `SearchResponse` so you can parse `results[]` and `meta` without spending You.com or Jev.

### Live demo (public Bearer)

Copy the public demo key (not a secret — same value as [`/config.js`](/config.js)):

```http
Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
```

```bash
curl -sS -X POST https://agentseek.dev/v1/search \
  -H "Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10}'
```

This is the main live path for `POST /v1/search` and MCP `search_web` on `https://agentseek.dev`. It burns operator You.com / TypeSafe quota and the per-IP demo limit. It does not unlock upstream secrets. The live host does **not** mint self-serve API keys.

### Local / self-host API key

```bash
cp .env.example .env   # set AGENT_SEEK_API_KEY (and your own YDC / TypeSafe keys)
uvicorn apps.api.main:app --port 8787
curl -sS -X POST http://127.0.0.1:8787/v1/search \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10}'
```

Local `AGENT_SEEK_API_KEY` is separate from the live `AS_…` demo key.

### Optional / advanced: OAuth DCR

Prefer Dynamic Client Registration or PKCE instead of the public demo key? See [Agent Seek authentication](/auth.md). Brief entry points: `POST /agent/identity` with `{"type":"anonymous"}`, or `POST /oauth2/register`. Metadata: [/.well-known/oauth-authorization-server](/.well-known/oauth-authorization-server), [/.well-known/oauth-protected-resource](/.well-known/oauth-protected-resource). You do not need OAuth to try the live demo.

## Predictable paths

| Resource | Path |
| --- | --- |
| Search | `POST /v1/search` and `GET /v1/search` |
| Search alias | `POST /api/v1/search` |
| Public index | `GET /v1` · `GET /api` |
| Sandbox example | `GET /v1/sandbox` |
| OpenAPI 3.1 | `/openapi.json` |
| Swagger UI | `/api/docs` · [api/docs.md](/api/docs.md) |
| ReDoc | `/api/redoc` |
| Health | `/health` |
| Versioning / Sunset | `/docs/versioning.md` |
| Product docs | `/docs` |
| Auth walkthrough | `/auth.md` |
| Developers llms.txt | `/developers/llms.txt` |
| API llms.txt | `/api/llms.txt` |
| Agent skill | `/.well-known/agent-skills/agent-seek/SKILL.md` |

Live prototype: `https://agentseek.dev`

## When to call Agent Seek

Use the Agent Seek API for **agent search**: a small set of high-relevance ranked web results for research or RAG. Do not ask it to write the answer. Hard cap 100 discover candidates per query. Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches. Do not dump all `k` results into context by default.

## `POST /v1/search`

```json
{
  "q": "Introducing System One Models Jev",
  "k": 10,
  "max_candidates": 50,
  "mode": "snip",
  "nocache": false
}
```

- `q` required, 1–500 characters
- `k` 1–25 (default 10)
- `max_candidates` 1–100 (default 50)
- `mode` `snip` (default — title/URL/snippet, cheaper/faster) or `deep` (Stage A survivor fetch, cap 12; not a full-web crawl). Website UI is fixed `snip`.
- Optional `signals`: answerability, authority, on_topic, states_sought_fact, subject_match, spam, prompt_injection (UI: **Injection risk**)
- Hard gates (order, 0.55): `subject_match` < 0.55, then `is_republisher` ≥ 0.55, then `prompt_injection` ≥ 0.55 or missing parse exclude from `results`. `subject_match` and `is_republisher` fail-open if parse missing; `prompt_injection` is fail-flagged. If hard gates empty the scored list, pre-gate ranking is restored (scores unchanged) and each restored row has `gates_relaxed: true`. Treat that as a relaxed-safety response. `gates_relaxed` is a per-result boolean, not a SearchMeta field.

Unauthenticated calls return **401** `application/problem+json` with

```http
WWW-Authenticate: Bearer resource_metadata="https://agentseek.dev/.well-known/oauth-protected-resource"
```

**Burst rate limit:** optional Upstash sliding window, 60 requests / minute / client IP on search and MCP `search_web` when enabled. That `429` is `code=RATE_LIMITED` and may include `Retry-After`.

**Website demo quota:** when `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled`), REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted → `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. See [pricing.md](/pricing.md).

## Related Agent Seek pages

- [Agent Seek docs](/docs) — humans + agents
- [Agent Seek skill](/.well-known/agent-skills/agent-seek/SKILL.md)
- [agents.md](/agents.md) — public agent how-to
- [About Agent Seek](/about) · [Contact Agent Seek](/contact)
- [OpenAPI](/openapi.json) · [pricing](/pricing)
