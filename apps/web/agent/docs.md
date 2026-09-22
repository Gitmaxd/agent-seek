---
title: Agent Seek docs
description: Agent Seek docs — API, OpenAPI, and search UI for humans and agents.
canonical: /docs.md
last-updated: 2026-09-20
---

# Agent Seek docs

Agent Seek is agent search: cheap You.com recall + TypeSafe Jev taste → ranked web results. Google-simple for people. Judgment-native for agents. Less SEO. More signal. Agent Seek returns ranked sources; the caller writes the answer. Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**).

## Install the skill

Efficient path: **skill → [llms.txt](/llms.txt) → [auth.md](/auth.md) → MCP or REST**.

Canonical skill URL and index:

- [/.well-known/agent-skills/agent-seek/SKILL.md](/.well-known/agent-skills/agent-seek/SKILL.md)
- Index: [/.well-known/agent-skills/index.json](/.well-known/agent-skills/index.json)

**Cursor:** save `SKILL.md` as `.cursor/skills/agent-seek/SKILL.md` (project) or `~/.cursor/skills/agent-seek/SKILL.md` (user).

**Other coding agents:** download `SKILL.md` from the well-known URL, or link it from the index.

Then read [llms.txt](/llms.txt), authenticate via [auth.md](/auth.md), and call `POST /v1/search` or MCP ([/mcp](/mcp), [server card](/.well-known/mcp/server-card.json)).

## Humans

- Open the [search UI](/) — type a query and press **Enter**.
- Each result shows a **relevance meter**; hover for a signal breakdown (UI label for `prompt_injection` is **Injection risk**).
- Website UI is fixed snip (k=10). No Mode/Order controls. API/MCP default is mode=snip (cheaper/faster). Pass mode=deep for Stage A survivor fetch (cap 12).

## Agent Seek API

Crawlable developer page: [Agent Seek API](/developers). Contract: `POST /v1/search`. Schema: [/openapi.json](/openapi.json). Swagger: [/api/docs](/api/docs). Auth: [Agent Seek authentication](/auth.md).

## Agents (primary)

Live prototype base URL: `https://agentseek.dev`

Auth header:

```
Authorization: Bearer $AGENT_SEEK_API_KEY
```

Contract: `POST /v1/search`

```json
{
  "q": "your query",
  "k": 10,
  "max_candidates": 50,
  "mode": "snip",
  "nocache": false
}
```

- `mode`: `snip` (default — title/URL/snippet, cheaper/faster) or `deep` (Stage A survivor fetch, cap 12; not a full-web crawl).
- `k` 1–25 (default 10) · `max_candidates` 1–100 (default 50).
- Results include `score`, `flags`, and optional `signals`: answerability, authority, on_topic, states_sought_fact, subject_match, spam, prompt_injection.
- Hard gates (order, 0.55): `subject_match` < 0.55, then `is_republisher` ≥ 0.55, then `prompt_injection` ≥ 0.55 or missing parse exclude from `results` (still in `raw_results`). `subject_match` and `is_republisher` fail-open if parse missing; `prompt_injection` is fail-flagged. UI label: **Injection risk**. If hard gates empty the scored list, pre-gate ranking is restored (scores unchanged) and each restored row has `gates_relaxed: true`. Treat that as a relaxed-safety response. `gates_relaxed` is a per-result boolean, not a SearchMeta field.

**Limits:** when `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled`), REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted is `429` `DEMO_EXHAUSTED` with no `Retry-After`. A separate 60 req/min burst, when Upstash is on, may return `Retry-After` (`RATE_LIMITED`). See [pricing.md](/pricing.md).

**When to use:** need a small set of high-relevance URLs/snippets for research or RAG.

**When not:** generative answers, unbounded crawl, or more than 100 candidates.

## How to use results

Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches. Use score order; only expand to the rest of `k` or re-query if those fail. Do not paste the full result list into context by default.

```bash
curl -sS -X POST "https://agentseek.dev/v1/search" \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10}'
```

See [Agent Seek API](/developers), [auth.md](/auth.md), [agents.md](/agents.md), [About Agent Seek](/about), and the [Agent Seek skill](/.well-known/agent-skills/agent-seek/SKILL.md).

## Also

- `GET /health` — liveness + version
- [Agent Seek sandbox](/v1/sandbox) — zero-auth canned SearchResponse
- [Agent Seek OpenAPI](/openapi.json) · [Swagger](/api/docs) · [ReDoc](/api/redoc) · [OpenAPI markdown](/api/docs.md)
- [llms.txt](/llms.txt) · [docs/llms.txt](/docs/llms.txt) · [api/llms.txt](/api/llms.txt)
- [Eval](/eval) · [eval.md](/eval.md)
- [pricing](/pricing) · [Agent Seek authentication](/auth.md) · [versioning](/docs/versioning.md)
- [Agent Seek MCP](/mcp) · [OAuth AS](/.well-known/oauth-authorization-server)
