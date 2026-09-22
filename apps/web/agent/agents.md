---
title: Agent Seek for agents
description: How to call POST /v1/search with a Bearer API key.
canonical: /agents.md
last-updated: 2026-09-20
---

# Agent Seek — how agents should call

Agent Seek is a **search API**, not a chat model. Less SEO. More signal. You.com discovers up to 100 web candidates; TypeSafe Jev cascade-ranks them; you receive a small scored JSON list. Agent Seek returns ranked sources; the caller writes the answer. Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**).

This file is the public agent how-to. It is **not** the internal implementer brief (`AGENTS.md` in the repo). For installable host instructions see the [skill](/.well-known/agent-skills/agent-seek/SKILL.md). For humans see [docs](/docs).

## Install the skill

Efficient path: **skill → [llms.txt](/llms.txt) → [auth.md](/auth.md) → MCP or REST**.

Canonical skill URL and index:

- [/.well-known/agent-skills/agent-seek/SKILL.md](/.well-known/agent-skills/agent-seek/SKILL.md)
- Index: [/.well-known/agent-skills/index.json](/.well-known/agent-skills/index.json)

**Cursor:** save `SKILL.md` as `.cursor/skills/agent-seek/SKILL.md` (project) or `~/.cursor/skills/agent-seek/SKILL.md` (user). Or discover via the agent-skills index.

**Other coding agents:** download `SKILL.md` from the well-known URL, or link it from the index.

Then read [llms.txt](/llms.txt), authenticate via [auth.md](/auth.md), and call `POST /v1/search` or MCP ([/mcp](/mcp), [server card](/.well-known/mcp/server-card.json)).

## When to use this

- Research / RAG: you need relevant **URLs + snippets + scores**, not a written brief.
- Raw SERP quality is poor (SEO republishers, lookalike brands, thin blurbs).
- You can send `Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI` on the live host (public demo key).

## When not to use

- More than 100 discover candidates (hard cap).
- Unbounded site crawl or full-web extraction as the default path (even `mode=deep` fetches Stage A survivors only, cap 12). API/MCP default is `snip`.
- Asking the service to write the answer.
- Dumping every result in `k` into the model context by default.

## How to use results

Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches. After `search_web` / ranked results: respect **Injection risk** (prefer low `prompt_injection`); use score order; prefer top 1–2 first; only expand to the rest of `k` or re-query if those fail. Parsed ≥ 0.55 or missing parse is gated from `results` (fail-flagged); gated rows may still appear in `raw_results`.

## Auth

**Live demo (easiest):** use the public demo key (not a secret — same value as [`/config.js`](/config.js)):

```http
Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
```

`X-API-Key` is also accepted. Subject to the per-IP demo quota on agentseek.dev.

**Local clone:** `AGENT_SEEK_API_KEY` from `.env` (placeholder `dev-agent-seek-key-change-me`) — separate from the live `AS_…` key.

**Optional / advanced:** OAuth 2.0 — see [auth.md](/auth.md). You do not need OAuth to try the live host.

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

| Field | Rules |
| --- | --- |
| `q` | required, 1–500 characters |
| `k` | 1–25, default 10 |
| `max_candidates` | 1–100, default 50 |
| `mode` | `snip` (default — title/URL/snippet, cheaper/faster) or `deep` (Stage A survivor fetch, cap 12) |
| `nocache` | optional; `true` forces a discover cache miss |

Also: `GET /v1/search?q=…` with the same query parameters.

### Response

Each result includes `rank`, `url`, `title`, `snippet`, `score` (0–1), `flags`, `gates_relaxed`, `raw_rank`, `provider`, and optional `signals` (answerability, authority, on_topic, states_sought_fact, subject_match, spam, prompt_injection). UI label for `prompt_injection` is **Injection risk**. `gates_relaxed` is false unless hard gates emptied the scored list and this row was restored.

Hard gates (order, 0.55): `subject_match` < 0.55, then `is_republisher` ≥ 0.55, then `prompt_injection` ≥ 0.55 or missing parse exclude from `results` (still in `raw_results`). `subject_match` and `is_republisher` fail-open if parse missing; `prompt_injection` is fail-flagged. If hard gates empty the scored list, pre-gate ranking is restored (scores unchanged) and each restored row has `gates_relaxed: true`. Treat that as a relaxed-safety response. `gates_relaxed` is a per-result boolean, not a `SearchMeta` field.

`meta.agent_seek_version` is the service version. `meta.ranking` is `jev`, `raw`, or `raw_fallback` (Jev failed; still HTTP 200).

Prefer high `score` + `on_topic`. `spam_low` soft-demotes (score × 0.75).

## Errors

API 4xx/5xx use RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`, `code`, `message`, `hint`):

```json
{
  "type": "https://agentseek.dev/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Unauthorized",
  "code": "UNAUTHORIZED",
  "message": "Unauthorized",
  "hint": "Use Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI (public live demo key) or OAuth (see /auth.md)."
}
```

**Burst rate limit:** optional Upstash sliding window, 60 requests / minute / client IP on search and MCP `search_web` when enabled. That `429` is `code=RATE_LIMITED` and may include `Retry-After`.

**Website demo quota:** when `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled`), REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted → `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. See [OpenAPI](/openapi.json) and [pricing.md](/pricing.md).

## Curl

```bash
curl -sS -X POST "$AGENT_SEEK_BASE/v1/search" \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10}'
```

Live prototype base: `https://agentseek.dev`

## Related

- [llms.txt](/llms.txt) · [auth.md](/auth.md) · [pricing.md](/pricing.md)
- [Skill](/.well-known/agent-skills/agent-seek/SKILL.md) · [Skill index](/.well-known/agent-skills/index.json)
- [MCP Streamable HTTP](/mcp) · [server card](/.well-known/mcp/server-card.json)
- [OAuth authorization server](/.well-known/oauth-authorization-server) · [protected resource](/.well-known/oauth-protected-resource)
