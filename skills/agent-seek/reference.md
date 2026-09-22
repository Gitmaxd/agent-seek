# Agent Seek reference

In-repo companion to [`SKILL.md`](SKILL.md). Read this when you need the full REST/signal contract. The public well-known path serves `SKILL.md` only; remote MCP usage does not require this file.

Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**). Parsed ≥ 0.55 or missing/unparseable parse is gated from `results` (fail-flagged); gated rows may still appear in `raw_results`.

**Live origin:** `https://agentseek.dev` · **Local:** `http://127.0.0.1:8787` · **Version:** `0.1.39` (`meta.agent_seek_version`, `GET /health`)

## REST `POST /v1/search`

Auth: OAuth `search:read` or Bearer `AGENT_SEEK_API_KEY` (also `X-API-Key`). Same payload as MCP `search_web`, plus REST-only knobs below.

**Request**

```json
{
  "q": "Introducing System One Models Jev",
  "k": 10,
  "max_candidates": 50,
  "mode": "snip",
  "rank": "on",
  "nocache": false
}
```

| Field | Rules | MCP `search_web` |
| --- | --- | --- |
| `q` | required, 1–500 chars | yes |
| `k` | 1–25, default 10 | yes |
| `max_candidates` | 1–100, default 50 (clamped to 100) | yes |
| `mode` | `snip` (default) or `deep` | yes |
| `rank` | `on` (default) or `off` (raw You.com order, `meta.ranking=raw`) | **no** — MCP always ranks (`rank` defaults to `on`) |
| `nocache` | optional bool; `true` forces discover cache miss (ranking still runs) | **no** — MCP always uses default `false` |

Also: `GET /v1/search?q=…&mode=snip` with the same query fields.

### Modes

- **`snip`** (API/MCP default): Stage A + Stage B on title / URL / snippet (cheaper / lower latency). Omit `mode` or pass `mode=snip`.
- **`deep`**: Stage A on snippets → prune survivors → fetch main page text for top survivors (**cap 12**; concurrency 6, timeout 5s, 200 KB / 8k chars) → Stage B Jev on fuller text. Not a full-web crawl. Per-URL fetch failure falls back to snippet. Slower / more expensive; response may include `meta.fetch_ms`. Website UI is fixed `snip`.

### Response (200)

```json
{
  "results": [
    {
      "rank": 1,
      "url": "https://…",
      "title": "…",
      "snippet": "…",
      "score": 0.91,
      "flags": ["on_topic"],
      "raw_rank": 4,
      "provider": "you.com",
      "signals": {
        "answerability": 0.9,
        "authority": 0.8,
        "on_topic": 0.95,
        "states_sought_fact": 0.7,
        "subject_match": 0.9,
        "spam": 0.1,
        "prompt_injection": 0.12
      },
      "gates_relaxed": false
    }
  ],
  "meta": {
    "q": "…",
    "candidates_in": 50,
    "kept": 10,
    "latency_ms": 842,
    "mode": "snip",
    "provider": "you.com",
    "agent_seek_version": "0.1.39",
    "ranking": "jev",
    "fetch_ms": null,
    "cache_hit": false,
    "cache_scope": "discover"
  },
  "raw_results": []
}
```

`raw_results` holds the same candidate set in discover order (capped at `max(k, 25)`) for A/B.

`GET /v1/sandbox` (zero-auth) returns this shape with `provider` / `meta.ranking` = `sandbox` and does not call You.com or Jev.

## Signals (on each result)

Optional 0–1 floats from the cascade (omitted on fallback / missing parses):

| Key | Meaning | UI hover label |
| --- | --- | --- |
| `answerability` | How well the page answers the query | Answers the query |
| `authority` | Source authority / first-party quality | Source authority |
| `on_topic` | Topical relevance | On topic |
| `states_sought_fact` | Whether the sought fact is stated | States the fact |
| `subject_match` | Entity / subject identity match | Right subject |
| `spam` | Spamminess (higher = worse) | Spam risk |
| `prompt_injection` | Injection / instruction-hijack risk (higher = worse) | **Injection risk** |

`meta.ranking`: `jev` \| `raw` \| `raw_fallback` \| `sandbox`.

- `jev` — cascade succeeded
- `raw` — `rank=off` or no Jev client (You.com order, scores 0)
- `raw_fallback` — Jev failed; You.com order, still HTTP 200
- `sandbox` — `GET /v1/sandbox` only

`meta.fetch_ms`: wall time for deep page fetches when `mode=deep` (null/omitted for snip or `ranking=raw`).

`meta.cache_scope`: `"discover"` when a discover cache is used or attempted (even on miss). Ranking always recomputes; discover may cache unless REST `nocache=true`.

`meta.discover_ms` / `meta.rank_ms`: stage latencies when non-zero.

## Scores and flags

- **score** ∈ [0, 1] from Stage B answerability+fact composite (`0.75*a + 0.25*fact`) with gated authority preference (host boost **only** if authority Noul is missing), then spam soft-demote.
- **flags:** `on_topic` (on_topic ≥ 0.55), `spam_low` (spam ≥ 0.65), `high_relevance` (score ≥ 0.75), `weak_signal` (Stage A possibly-relevant < 0.3).
- Prefer high score + `on_topic`.
- **`spam_low` soft-demotes** (score × 0.75) — not a hard filter; UI chip stays warn-style.
- Prefer `raw_rank` only when comparing against unranked SERP.
- Use **signals** for hover/debug and agent routing — do not treat a single signal as the full score.

## Hard gates

Order (0.55 thresholds): **subject_match → is_republisher → prompt_injection**. `subject_match` and `is_republisher` fail-open if a parse is missing; `prompt_injection` is fail-flagged.

- **subject_match**: Stage B `{cid}__subject_match` — parsed < 0.55 excluded from `results` (still in `raw_results`); missing parse fails open.
- **republisher**: Stage B `{cid}__is_republisher` — parsed ≥ 0.55 excluded; judges role (mirror/viewer vs canonical), not a domain deny list. Missing parse fails open.
- **prompt_injection**: Stage B `{cid}__prompt_injection` — parsed ≥ 0.55 or missing/unparseable parse excluded (fail-flagged); judges injection/hijack intent aimed at agents/LLMs (not educational pages about the attack); not a keyword deny list. UI label: **Injection risk**.
- If hard gates empty the scored list, the post-compose Jev-ranked pre-gate list is restored (scores unchanged). Each restored row sets `gates_relaxed` to `true`. Treat that as a relaxed-safety response: those rows were not filtered by the hard gates, including prompt injection. `gates_relaxed` is a per-result boolean, not a `SearchMeta` field. The cascade may still record an internal extra `gates_relaxed=empty_after_hard_gates`; that string is not returned on `meta`.

## UI defaults vs API knobs

| | UI | REST | MCP `search_web` |
| --- | --- | --- | --- |
| Mode | fixed `snip` | `mode=snip` (default) \| `deep` | same as REST |
| k / max | fixed 10 / 50 | `k` 1–25, `max_candidates` 1–100 | same as REST |
| Cache | normal | `nocache=true` forces discover miss | not exposed |
| Rank | always on | `rank=on` (default) \| `off` | not exposed (always on) |
| Auth | injected same-origin key | Bearer / `X-API-Key` / OAuth | same |

Humans: open `/`, Enter to search; relevance meter + hover signal breakdown.

## Limits

When `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled` at deploy), REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted → `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. Also off when `AGENT_SEEK_DEMO_SEARCH_LIMIT=0` or Upstash is unset. Unauthenticated MCP helper tools do not consume this quota.

A separate optional Upstash sliding window (default 60 requests / minute / client IP) applies to search and MCP `search_web`. That `429` is `code=RATE_LIMITED` and may include `Retry-After`. Health, sandbox, docs, and well-known discovery are not throttled.

Call timeouts: You.com ≤ 8s, Jev ≤ 8s, deep page fetch ≤ 5s per call. There is no whole-request timeout.

Client IP for both limiters is the **rightmost** public `X-Forwarded-For` hop, then `X-Real-IP`, then the socket address.

## Curl examples

Default snip (local):

```bash
export AGENT_SEEK_API_KEY=…   # from .env
curl -sS -X POST "http://127.0.0.1:8787/v1/search" \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10,"max_candidates":50}'
```

Opt-in deep (Stage A survivor fetch, cap 12):

```bash
curl -sS -X POST "http://127.0.0.1:8787/v1/search" \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"when were langchain deep agents released","k":10,"max_candidates":50,"mode":"deep"}'
```

Live MCP server card (no auth):

```bash
curl -sS "https://agentseek.dev/.well-known/mcp/server-card.json"
```

Zero-auth sandbox:

```bash
curl -sS "https://agentseek.dev/v1/sandbox"
```

`GET /health` → `{"ok":true,"version":"0.1.39"}`.

Human product page: `/docs`. OpenAPI Swagger: `/api/docs`. Schema: `/openapi.json`. Auth walkthrough: `/auth.md`. Public agent start: `/llms.txt`.
