---
title: Agent Seek OpenAPI docs
description: Markdown twin of /api/docs — OpenAPI 3.1, Swagger, and ReDoc for the Agent Seek API.
canonical: /api/docs.md
last-updated: 2026-09-20
---

# Agent Seek OpenAPI docs

This is the markdown twin of the Swagger UI at [`/api/docs`](/api/docs) (ReDoc: [`/api/redoc`](/api/redoc)).

Machine-readable contract: [`/openapi.json`](/openapi.json) (OpenAPI 3.1). Public discovery: [`GET /api`](/api) and [`GET /v1`](/v1).

Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**). Default `mode=snip` (title/URL/snippet; cheaper/faster). Pass `mode=deep` for Stage A survivor fetch (cap 12; not a full-web crawl). Website UI is fixed `snip`. `k` default 10 (1–25); `max_candidates` default 50 (hard max 100). Hard gates (order): subject_match → is_republisher → prompt_injection (0.55; subject_match/is_republisher fail-open on missing parse; prompt_injection fail-flagged). If hard gates empty the scored list, pre-gate ranking is restored and each restored row has `gates_relaxed: true` (relaxed-safety response; not a SearchMeta field).

## Operations

| operationId | Method | Path | Auth |
| --- | --- | --- | --- |
| `searchPost` | POST | `/v1/search` | OAuth `search:read` or API key |
| `searchGet` | GET | `/v1/search` | same |
| `healthCheck` | GET | `/health` | none |
| `apiIndex` | GET | `/v1` | none |
| `listPublicApi` | GET | `/api` | none |
| `sandboxSearchExample` | GET | `/v1/sandbox` | none |

Aliases (not in the spec, same handlers): `POST /api/v1/search`, `GET /api/v1/search`. `GET /api/v1` without a Bearer token returns **401** with `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"`.

## Errors

Every API 4xx/5xx is `Content-Type: application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail`, `instance`, `code`, `message`, `hint`, and nested `error`.

## Versioning

URL versioning on `/v1`. Deprecation and Sunset policy: [`/docs/versioning.md`](/docs/versioning.md).

## Try it

```bash
curl -sS https://agentseek.dev/health
curl -sS https://agentseek.dev/v1
curl -sS https://agentseek.dev/v1/sandbox
curl -sS -X POST https://agentseek.dev/v1/search \
  -H "Content-Type: application/json" \
  -d '{"q":"test"}'
```

The last call is a 401 problem+json with the WorkOS `resource_metadata` challenge. Continue at [`/auth.md`](/auth.md).
