# Agent Seek authentication

You are an agent. Start with the easy path. OAuth is optional.

## Easy path (live demo)

1. **Zero-auth inspect:** `GET /v1/sandbox` returns a canned Agent Seek `SearchResponse` with no key and no upstream calls. `GET /health` and `GET /openapi.json` are also public.
2. **Public live demo Bearer key** (not a secret — same value as [`/config.js`](/config.js)):

```http
Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
```

Use that header on `POST /v1/search` or MCP `search_web` against `https://agentseek.dev`. It is subject to the per-IP demo quota on the live host. It does not unlock You.com / TypeSafe secrets.

3. **Local clone only:** `cp .env.example .env` and use `AGENT_SEEK_API_KEY=dev-agent-seek-key-change-me` (or any local secret). That key is separate from the live `AS_…` demo key.

## Optional / advanced: OAuth (`agent_auth`)

If you prefer Dynamic Client Registration or PKCE instead of the public demo key: Discover → pick a method → register → claim if needed → exchange for an `access_token` → call `POST /v1/search` or MCP → handle revocation. Follow the steps below.

Resource server and authorization server are the same host (this origin). Machine-readable discovery is authoritative; this file is the prose companion (`agent_auth.skill`).

## Discover

A `401` from `/v1/search` or `/mcp` carries `WWW-Authenticate` with `resource_metadata`:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="https://agentseek.dev/.well-known/oauth-protected-resource"
```

Pull that URL (or fall back to [/.well-known/oauth-protected-resource](/.well-known/oauth-protected-resource) on this host).

### 1a. Fetch the Protected Resource Metadata

```http
GET /.well-known/oauth-protected-resource
```

You will receive `resource`, `resource_name`, `authorization_servers`, `scopes_supported` (`search:read`, `mcp:invoke`, `health:read`), and `bearer_methods_supported` (`header`).

Public API index (no auth): [GET /v1](/v1). OpenAPI: [/openapi.json](/openapi.json). Docs: [/docs](/docs). Developers: [/developers](/developers).

### 1b. Fetch the Authorization Server metadata

```http
GET /.well-known/oauth-authorization-server
```

Read RFC 8414 fields (`issuer`, `authorization_endpoint`, `token_endpoint`, `revocation_endpoint`, `registration_endpoint`, `code_challenge_methods_supported` including **S256**, `client_id_metadata_document_supported`) and the full `agent_auth` block:

- `skill` — this document (`/auth.md`)
- `identity_endpoint` — [POST /agent/identity](/agent/identity)
- `claim_endpoint` — [POST /agent/identity/claim](/agent/identity/claim)
- `events_endpoint` — [POST /agent/event/notify](/agent/event/notify)
- `identity_types_supported` — `anonymous`, `identity_assertion`, `service_auth`
- `identity_assertion.assertion_types_supported` — `urn:ietf:params:oauth:token-type:id-jag`

Alternate credential: public live demo Bearer `AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI` (or local `AGENT_SEEK_API_KEY`) as `Authorization: Bearer` or `X-API-Key`. Both paths work on `/v1/search` and MCP `search_web`.

**Self-serve (no sales form).** Prefer the public demo key above for live search. Anonymous identity and `POST /oauth2/register` also work without email if you want OAuth. Zero-auth inspect: [`GET /v1`](/v1), [`GET /api`](/api), [`GET /v1/sandbox`](/v1/sandbox), [`GET /health`](/health). Local key: set `AGENT_SEEK_API_KEY` in `.env`.

## Pick a method

1. **You have an ID-JAG** audience-bound to this `resource` → `identity_assertion` + `id-jag`.
2. **You have the public live demo key or a local API key** → skip OAuth and send `Authorization: Bearer` (live: `AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI`; local: your `.env` `AGENT_SEEK_API_KEY`). Or use `service_auth` with `client_secret` = that key.
3. **You have neither and still want OAuth** → `anonymous` for `health:read` + `mcp:invoke`. Claim later if you need `search:read` without copying the demo key.
4. **Interactive OAuth client** → authorization code + PKCE S256 at `/oauth2/authorize` using seeded client `agent-seek-test` or [POST /oauth2/register](/oauth2/register) / CIMD.

## Register

Surface `resource_name` (Agent Seek) before asserting a user identity. Skip that consent gate for `anonymous`.

### identity_assertion + id-jag

```http
POST /agent/identity
Content-Type: application/json

{
  "type": "identity_assertion",
  "assertion_type": "urn:ietf:params:oauth:token-type:id-jag",
  "assertion": "<your ID-JAG JWT>"
}
```

Success returns a service-signed `identity_assertion`. Go to **Exchange**.

### service_auth

With the operator key (prototype shortcut — no claim ceremony):

```http
POST /agent/identity
Content-Type: application/json

{"type":"service_auth","client_secret":"<AGENT_SEEK_API_KEY>"}
```

Without the key, send `{"type":"service_auth","login_hint":"user@example.com"}` and complete **Claim**.

### anonymous

```http
POST /agent/identity
Content-Type: application/json

{"type":"anonymous"}
```

Response includes `identity_assertion`, `pre_claim_scopes`, `claim_token`, and `claim_url`.

### OAuth client (authorization code + PKCE)

Seeded test client (local pytest / self-host): `client_id=agent-seek-test`. Public PKCE client (`token_endpoint_auth_method=none`). Redirects: `http://127.0.0.1/callback`, `http://127.0.0.1:8787/oauth/callback`, `urn:ietf:wg:oauth:2.0:oob`. CIMD document: [/.well-known/oauth-client/agent-seek-test.json](/.well-known/oauth-client/agent-seek-test.json). Dynamic registration: `POST /oauth2/register`. Never commit client secrets; this prototype client is public.

OAuth clients, authorization codes, and registrations are **process-local** (in-memory). They die with the process. See the repo `SECURITY.md`.

```http
GET /oauth2/authorize?response_type=code&client_id=agent-seek-test&redirect_uri=http://127.0.0.1/callback&scope=search:read%20health:read%20mcp:invoke&code_challenge=<S256>&code_challenge_method=S256&state=<csrf>
```

## Claim

For anonymous / email `service_auth`, start a ceremony:

```http
POST /agent/identity/claim
Content-Type: application/json

{"claim_token":"clm_...","email":"user@example.com"}
```

Hand the user `claim_attempt.verification_uri` and `user_code`. They confirm at `/oauth2/claim`. Poll:

```http
POST /oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:workos:agent-auth:grant-type:claim&claim_token=clm_...
```

Pending → `authorization_pending`. Success → `access_token` plus a fresh `identity_assertion`.

## Exchange

POST the service-signed `identity_assertion` to the token endpoint ([RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) JWT-bearer):

```http
POST /oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=<identity_assertion>&resource=https://agentseek.dev/
```

Authorization-code clients exchange `code` + `code_verifier` with `grant_type=authorization_code`.

Response:

```json
{
  "access_token": "<token>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "search:read health:read mcp:invoke"
}
```

## Use the access_token

```http
POST /v1/search HTTP/1.1
Authorization: Bearer <access_token>
Content-Type: application/json

{"q":"Introducing System One Models Jev","k":10,"max_candidates":50}
```

MCP Streamable HTTP (same token, scope `mcp:invoke` / `search:read` for `search_web`):

```http
POST /mcp
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"agent","version":"1.0"}}}
```

Server card: [/.well-known/mcp/server-card.json](/.well-known/mcp/server-card.json). Alternate MCP URL: [/.well-known/mcp](/.well-known/mcp).

**Bearer alternate** (no OAuth — preferred for casual testing): live public demo key `AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI`, or local `Authorization: Bearer $AGENT_SEEK_API_KEY` / `X-API-Key`. Same-origin UI injects the public demo key via `/config.js` and never exposes You.com / TypeSafe secrets.

**Burst rate limit:** optional Upstash sliding window, **per client IP** (default **60 requests / minute**), on search and MCP `search_web` when both Upstash REST env vars are set. Responses include RFC `RateLimit` and `RateLimit-Policy`. That `429` is `application/problem+json` with `code=RATE_LIMITED` and may include `Retry-After`.

**Website demo quota:** off unless `AGENT_SEEK_DEMO_MODE=enabled` (code default `disabled`; the live host sets `enabled` at deploy). Then REST `/v1/search`, `/api/v1/search`, and MCP `search_web` share a lifetime per-IP allowance (default 5, Upstash `INCR`, no TTL). Exhausted calls return `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and **no** `Retry-After`. Unauthenticated MCP helper tools do not consume this quota. Also off when `AGENT_SEEK_DEMO_SEARCH_LIMIT=0` or Upstash is unset.

## Errors

API 4xx/5xx use RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`, `instance`) plus `code`, `message`, `hint`, and nested `error`. A 401 also carries the `WWW-Authenticate` header shown in **Discover**.

```json
{
  "type": "https://agentseek.dev/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Unauthorized",
  "instance": "/v1/search",
  "code": "UNAUTHORIZED",
  "message": "Unauthorized",
  "hint": "Use Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI (public live demo key) or OAuth (see /auth.md). Local: Bearer $AGENT_SEEK_API_KEY.",
  "error": {"code": "UNAUTHORIZED", "message": "Unauthorized", "hint": "Use Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI (public live demo key) or OAuth (see /auth.md). Local: Bearer $AGENT_SEEK_API_KEY."}
}
```

| Code | Where | What to do |
| --- | --- | --- |
| `UNAUTHORIZED` | `/v1/search`, `/mcp` | Send Bearer `AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI` (live demo), a local `AGENT_SEEK_API_KEY`, or an OAuth access_token |
| `INSUFFICIENT_SCOPE` | `/v1/search` | Request `search:read` or present the operator API key |
| `invalid_grant` | `/oauth2/token` | Re-register at `identity_endpoint` and exchange a fresh `identity_assertion` |
| `authorization_pending` | `/oauth2/token` (claim) | Honor `interval`; user has not typed `user_code` |
| `RATE_LIMITED` | search, MCP `search_web` | Burst window (default 60/min). Wait `Retry-After` |
| `DEMO_EXHAUSTED` | REST `/v1/search`, `/api/v1/search`, MCP `search_web` | Lifetime demo allowance is used for this IP. No `Retry-After`. REST and MCP `search_web` share the same per-IP counter |

## Revocation

POST `token=<access_token>&token_type_hint=access_token` to [`/oauth2/revoke`](/oauth2/revoke) (RFC 7009). `200` is success and is idempotent. Re-run **Exchange** with the same `identity_assertion` for a new access_token.

Registration-layer revocation uses `agent_auth.events_endpoint` (`/agent/event/notify`) via SET (RFC 8417 / RFC 8935). You do not call it; the next `/oauth2/token` returns `invalid_grant` — restart at **Register**.

The live public demo key is rotated by the operator when needed ([contact](/contact)). Local clones rotate their own `AGENT_SEEK_API_KEY` in `.env`.
