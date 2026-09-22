---
title: Agent Seek — Less SEO. More signal.
description: Less SEO. More signal. Ranked sources (You.com + TypeSafe Jev); the caller writes the answer. Google-simple UI and POST /v1/search.
canonical: /
last-updated: 2026-09-20
---

# Agent Seek

Less SEO. More signal.

Agent Seek returns ranked sources; the caller writes the answer. **You.com** discovers web candidates; **TypeSafe Jev** cascade-ranks them; you get ranked web results (title, URL, snippet, score) instead of SERP mush. Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**).

## Install the skill

For AI agents: install the [Agent Seek skill](/.well-known/agent-skills/agent-seek/SKILL.md), then read [llms.txt](/llms.txt).

Efficient path: **skill → llms.txt → [auth.md](/auth.md) → MCP or REST**.

- Canonical skill: [/.well-known/agent-skills/agent-seek/SKILL.md](/.well-known/agent-skills/agent-seek/SKILL.md)
- Index: [/.well-known/agent-skills/index.json](/.well-known/agent-skills/index.json)
- Cursor: save `SKILL.md` as `.cursor/skills/agent-seek/SKILL.md` or `~/.cursor/skills/agent-seek/SKILL.md`

Then authenticate via [Agent Seek authentication](/auth.md) and call `POST /v1/search` or [Agent Seek MCP](/mcp) ([server card](/.well-known/mcp/server-card.json)).

Zero-auth first: [GET /v1/sandbox](/v1/sandbox) returns a canned SearchResponse with no key.

## When to use this

- You need high-relevance URLs and snippets for research or RAG.
- Raw search top-10 is SEO-spammy and you want judgment-ranked keepers.
- You will synthesize the answer yourself. Do not ask Agent Seek to write it.
- Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches.

## How agents should call

```http
POST /v1/search
Authorization: Bearer $AGENT_SEEK_API_KEY
Content-Type: application/json
```

```json
{"q":"your query","k":10,"max_candidates":50}
```

- `k` 1–25 (default 10). `max_candidates` 1–100 (default 50).
- API/MCP default `mode=snip` ranks title/URL/snippet (cheaper/faster). Pass `mode=deep` to fetch Stage A survivor pages (cap 12), then rank. Not a full-web crawl. Website UI is fixed `snip`.
- Signals include `prompt_injection` (UI: **Injection risk**). Hard gates (order): subject_match → is_republisher → prompt_injection (0.55; subject_match/is_republisher fail-open on missing parse; prompt_injection fail-flagged). If hard gates empty the scored list, pre-gate ranking is restored and each restored row has `gates_relaxed: true` (relaxed-safety response; not a SearchMeta field).
- Auth is OAuth 2.0 (`search:read`) or an API key. See [auth.md](/auth.md). MCP: [/mcp](/mcp).
- Prototype pricing is free. When `AGENT_SEEK_DEMO_MODE=enabled`, REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5). Exhausted is `429` `DEMO_EXHAUSTED` with no `Retry-After`. See [pricing.md](/pricing.md).

## Humans

Open `/`, type a query, press Enter. No Mode/Order controls (UI is fixed `snip`). Each result has a 10-box relevance meter; hover for signal breakdown (including **Injection risk** for `prompt_injection`).

## More

- [Agent Seek docs](/docs) · [Agent Seek API](/developers) · [Agent Seek OpenAPI](/openapi.json)
- [Eval](/eval) · [eval.md](/eval.md)
- [Agent Seek skill](/.well-known/agent-skills/agent-seek/SKILL.md) · [agents.md](/agents.md)
- [About Agent Seek](/about) · [Contact](/contact) · [Privacy](/privacy)
- [llms.txt](/llms.txt) · [docs/llms.txt](/docs/llms.txt) · [api/llms.txt](/api/llms.txt)
- [Agent Seek sandbox](/v1/sandbox) · [Agent Seek MCP](/mcp) · [versioning](/docs/versioning.md) · [?mode=agent](/?mode=agent)
