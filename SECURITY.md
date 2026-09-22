# Security policy

## Report a vulnerability

Email **[131803031+Gitmaxd@users.noreply.github.com](mailto:131803031+Gitmaxd@users.noreply.github.com)** with `Agent Seek security` in the subject.

Please do **not** file a public GitHub issue for key leaks, auth bypasses, or injection reports. Include the host (`https://agentseek.dev` or self-host), `GET /health` version, and enough detail to reproduce. There is no ticket portal and no SLA on this prototype; we will reply when we can.

Operator identity: Git Maxd — see [contact](https://agentseek.dev/contact).

## Demo security model (honest)

The live host is a **working prototype**, not a hardened multi-tenant SaaS.

**Public demo key via `/config.js`.** The same-origin search page loads `/config.js`, which injects the live `AS_…` demo Bearer key into the browser. That key is **public on purpose** (same value documented in the README) — not a secret to hide. Anyone can copy it and call search / MCP `search_web` on the live host. Abuse burns operator upstream quota and the per-IP demo limit only. `robots.txt` disallows `/config.js`; that is crawl hygiene, not access control. Training crawlers are also told `Disallow: /v1/` except the advertised zero-auth sandbox (`Allow: /v1/sandbox` and `Allow: /v1/sandbox/` appear above that disallow). Upstream `YDC_API_KEY` and `TYPESAFE_API_KEY` never leave the server.

**Opt-in Upstash rate limit.** Search and MCP `search_web` are unlimited unless **both** `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are set. When enabled, the limiter is a sliding 60s window **per client IP** (default 60/min). Redis/network errors fail closed (`503`). Health, sandbox, docs, and well-known discovery are not throttled.

**CORS defaults.** `CORS_ORIGIN` defaults to `*` (see `.env.example`). Fine for a public demo; too open for a locked-down self-host.

**OAuth DCR for demo.** Agents can register without an emailed key: `POST /oauth2/register` (dynamic client registration) and anonymous / claim flows documented in [`/auth.md`](https://agentseek.dev/auth.md). The live host does **not** mint self-serve `AGENT_SEEK_API_KEY` values. OAuth clients, codes, and registrations are **in-memory** (process-local). If `AGENT_SEEK_TOKEN_SIGNING_KEY` is empty, the HMAC signing key is derived from `AGENT_SEEK_API_KEY` so local pytest works.

**What this is not.** No billing, no self-serve private-key minting, no public bench. The public demo key is meant to be copied; using it spends the operator's You.com / TypeSafe quota and the per-IP demo limit. It does not reveal those upstream secrets.

## Self-host warnings

If you run this on the public internet:

1. **Dedicated UI / demo key.** Set `AGENT_SEEK_UI_API_KEY` to a key you are willing to publish in `/config.js` (and optionally in docs). Do not reuse a high-privilege operator key as the fallback for `/config.js`.
2. **Pin CORS.** Set `CORS_ORIGIN` to your UI origin(s), not `*`.
3. **Enable Upstash.** Set both official Upstash REST variables and tune `AGENT_SEEK_RATE_LIMIT_PER_MIN`.
4. **Signing key.** Set `AGENT_SEEK_TOKEN_SIGNING_KEY` to a long random secret. Do not rely on the API-key-derived fallback in production.
5. **Rotate** `AGENT_SEEK_API_KEY` and the UI key independently. Never commit `.env`.

Local/dev with default placeholders is fine behind localhost.
