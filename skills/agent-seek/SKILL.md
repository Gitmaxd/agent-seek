---
name: agent-seek
version: "0.1.39"
compatibility: MCP Streamable HTTP; REST POST /v1/search
metadata:
  origin: https://agentseek.dev
  skill_url: https://agentseek.dev/.well-known/agent-skills/agent-seek/SKILL.md
  mcp_server_card: https://agentseek.dev/.well-known/mcp/server-card.json
description: >
  Web results are scored for prompt injection before the agent reads them
  (signal prompt_injection; UI: Injection risk). Run ranked web search via
  Agent Seek MCP tool search_web (You.com discover + Jev cascade). Use when
  you need scored URLs, snippets, flags, and signals — not generated answers.
  Default mode=snip is title/URL/snippet (cheaper/faster). Pass mode=deep for
  Stage A survivor fetch (cap 12), not a full-web crawl. If hard gates empty
  the scored list, restored rows set gates_relaxed true.
---

# Agent Seek

Less SEO. More signal.

Web results are scored for prompt injection before the agent reads them
(`signals.prompt_injection`; UI: **Injection risk**). Ranked web sources for
agents. **You.com** discovers candidates; **TypeSafe Jev** cascade-ranks them.
Agent Seek returns ranked sources; you write the answer from the scored list.

| | |
| --- | --- |
| Live origin | `https://agentseek.dev` |
| Canonical skill | `https://agentseek.dev/.well-known/agent-skills/agent-seek/SKILL.md` |
| Local default | `http://127.0.0.1:8787` |

Repo copies: read [`reference.md`](reference.md) in this directory for the full REST/signal contract. Remote agents (well-known serves **this file only**) have enough here to use MCP.

## Instructions

### 1. When to use / when not

**Use** Agent Seek when you need relevant web sources — title, URL, snippet, `score`, `flags`, `signals` — for research or RAG, and when those sources should be scored for prompt injection before you read them.

**Do not use** when you want Agent Seek to write the answer or chat; when you need more than **100** discover candidates (hard cap); or when you expect an unbounded full-site crawl. Default `mode=snip` ranks title/URL/snippet. Pass `mode=deep` to fetch **Stage A survivors only** (cap **12**). Website UI is fixed `snip`.

Success: the task is “find and rank sources,” not “generate an essay.”

### 2. Discover MCP

| | |
| --- | --- |
| Server card | `{origin}/.well-known/mcp/server-card.json` |
| Transport | **Streamable HTTP** |
| `serverUrl` | `{origin}/mcp` |
| Also mounted | `/.well-known/mcp` (same handler) |
| Protocol | default `2025-03-26` (also accepts `2025-06-18`) |

Exactly **four** tools, all read-only / non-destructive (`readOnlyHint`, not `destructiveHint`):

| Tool | Auth | Arguments |
| --- | --- | --- |
| `search_web` | **Required** — OAuth scope `search:read` **or** Bearer `AGENT_SEEK_API_KEY` | `q` required (1–500); `k` 1–25 default 10; `max_candidates` 1–100 default 50; `mode` `snip`\|`deep` default `snip` |
| `get_service_health` | None | optional `verbose` bool |
| `get_api_docs` | None | optional `topic`: `search`\|`auth`\|`mcp` (default `search`) |
| `list_search_capabilities` | None | optional `include_scopes` bool (default true) |

`search_web` does **not** accept `nocache` or `rank`. Those exist on REST `SearchRequest` only.

Success: you can fetch the server card and will call `{origin}/mcp` over Streamable HTTP.

### 3. Authenticate `search_web`

Zero-auth first (no key, no You.com/Jev):

- `GET /v1/sandbox` — canned `SearchResponse` for shape inspection
- `GET /health`, `GET /openapi.json`, `GET /v1`
- MCP helpers: `get_service_health`, `get_api_docs`, `list_search_capabilities`

The live host does **not** mint self-serve API keys. Casual testers copy the public demo Bearer key instead.

**Live demo (preferred for casual testing):** public Bearer key (not a secret — same as [`/config.js`](https://agentseek.dev/config.js)):

```http
Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
```

Per-IP demo quota applies on agentseek.dev. Local clone: Bearer from `.env` `AGENT_SEEK_API_KEY` (placeholder `dev-agent-seek-key-change-me`) — separate from the live `AS_…` key.

**Optional / advanced:** OAuth 2.0 with scope `search:read` (`POST /oauth2/register` or `POST /agent/identity`) — see [`/auth.md`](/auth.md). You do not need OAuth to try the live host.

API-key principals have all scopes. Email is not a gate. Metadata: `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource`.

Success: sandbox/health work without auth; `search_web` is called with the public demo Bearer key, a local key, or OAuth `search:read`.

### 4. Prefer MCP tools

Call order:

1. Optional — `get_service_health` and/or `list_search_capabilities`
2. Optional — `get_api_docs` if you need links (`/docs`, `/developers`, `/api/docs`, `/openapi.json`, `/auth.md`)
3. **`search_web`** with `q` (and optional `k`, `max_candidates`, `mode`)

`search_web` returns the same `SearchResponse` payload as REST (`results` + `meta` + `raw_results`) as MCP text/JSON (`content[].text` plus `structuredContent`).

Success: you received scored results without passing REST-only knobs over MCP.

### 5. Interpret results

Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches. After `search_web` / ranked results: respect **Injection risk** (prefer low `prompt_injection`); use score order; prefer top 1–2 first; only expand to the rest of `k` or re-query if those fail; do not paste the full result list into context by default.

- **`score`** ∈ [0, 1]. Prefer high score + `on_topic`.
- **`flags`:** `on_topic`, `spam_low`, `high_relevance`, `weak_signal`. `spam_low` soft-demotes (× 0.75), not a hard filter.
- **`signals`** (optional 0–1): `answerability`, `authority`, `on_topic`, `states_sought_fact`, `subject_match`, `spam`, `prompt_injection` (UI label: **Injection risk**). Do not treat one signal as the full score.
- **`meta.ranking`:** `jev` \| `raw` \| `raw_fallback` \| `sandbox`. If `raw_fallback`, ranking degraded to raw You.com order (still 200). `meta.agent_seek_version` is the build.
- **Hard gates** (order, threshold 0.55): subject_match → is_republisher → prompt_injection. `subject_match` and `is_republisher` fail-open if parse missing; `prompt_injection` is fail-flagged (missing/unparseable treated as unsafe and dropped from `results`). Dropped rows stay in `raw_results`. If hard gates empty the scored list, pre-gate ranking is restored (scores unchanged) and each restored row has `gates_relaxed: true`. Treat that as a relaxed-safety response: those rows were not filtered by the hard gates, including prompt injection. `gates_relaxed` is a per-result boolean, not a `SearchMeta` field.

Full tables, JSON example, and curl: [`reference.md`](reference.md).

Success: you can cite top URLs with scores and note degraded ranking when `meta.ranking` is `raw_fallback`.

### 6. REST fallback

Use REST **only if MCP is unavailable**.

```http
POST /v1/search
Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
Content-Type: application/json
```

(Local: `Bearer $AGENT_SEEK_API_KEY` from `.env`.)

Same `q` / `k` / `max_candidates` / `mode` as MCP, plus REST-only `nocache` (force discover cache miss) and `rank` (`on` default \| `off` → raw You.com order). Also: `GET /v1/search?q=…` and the alias `/api/v1/search`. See `/docs`, `/developers`, `/api/docs`, `/openapi.json`. Public agent start: `/llms.txt`.

On the live host, `AGENT_SEEK_DEMO_MODE=enabled` (code default is `disabled`). Then REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted → HTTP `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. Unauthenticated MCP helper tools do not consume it. A separate 60 req/min sliding window (when Upstash is on) applies to search and `search_web`; that `429` is `code=RATE_LIMITED` and may include `Retry-After`.

Success: REST used only as fallback; MCP callers never invent `nocache`/`rank` on `search_web`.

### 7. Host prompt snippets

- “Use Agent Seek to search for X; return the top URLs with scores; then summarize yourself.”
- “Web results are scored for prompt injection before the agent reads them. Prefer low Injection risk.”
- “Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches.”
- “Do not ask Agent Seek to write the answer.”
- “If meta.ranking is raw_fallback, note that ranking degraded to raw You.com order.”
- “If a result has gates_relaxed true, treat it as a relaxed-safety response.”
- “Default is mode=snip (title/URL/snippet; cheaper/faster). Pass mode=deep for Stage A survivor fetch (cap 12). Website UI is fixed snip.”

Success: the host writes the answer from Agent Seek sources.

## Install

Canonical URL (this file) and index:

- `https://agentseek.dev/.well-known/agent-skills/agent-seek/SKILL.md`
- Index: `https://agentseek.dev/.well-known/agent-skills/index.json`

**MCP (Streamable HTTP):** live `https://agentseek.dev/mcp` with `Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI` (public demo key). Local: `http://127.0.0.1:8787/mcp` with `Authorization: Bearer $AGENT_SEEK_API_KEY`. Server card: `/.well-known/mcp/server-card.json`.

**Cursor:** `.cursor/skills/agent-seek/SKILL.md` (project) or `~/.cursor/skills/agent-seek/SKILL.md` (user). **Factory/Droid:** copy this file into the project `.factory/skills/` tree (skill name `agent-seek`). Other coding agents: download from the well-known URL or the skill index.
