# Agent Seek — Less SEO. More signal.

**Cheap web recall (You.com) + Jev taste → Google-simple UI, HTTP API, and an agent Skill.**

> Google-simple for people. Judgment-native for agents.

You.com discovers web candidates. TypeSafe Jev cascade-ranks them. Clients get a small scored JSON list (plus a simple search UI). Agent Seek does **not** write the answer. Web results are scored for prompt injection before the agent reads them (`signals.prompt_injection`; UI: **Injection risk**). If hard gates empty the scored list, restored rows set `gates_relaxed: true`.

- Live demo: https://agentseek.dev
- Not Deep Research / Deep Agents. Max **100** discover candidates per query.
- API/MCP default `mode=snip` (title/URL/snippet; cheaper/faster). Pass `mode=deep` for Stage A survivor fetch (cap **12**). Website UI is fixed `snip`.

## Two ways to try it

1. **Live demo (no clone):** paste the public `AS_…` Bearer into MCP or curl — see [Try the live demo](#try-the-live-demo-easiest-path). This burns **operator** You.com / TypeSafe quota and the per-IP demo limit on agentseek.dev.
2. **Self-host / local:** clone + `.env` — you must supply **your own** `YDC_API_KEY` and `TYPESAFE_API_KEY`. Local `AGENT_SEEK_API_KEY` is only your machine Bearer (not the live `AS_…` key).

## Try the live demo (easiest path)

The live host publishes a **public demo key** (not a secret). It is the same `AS_…` value the website injects via [`/config.js`](https://agentseek.dev/config.js). Anyone can copy it. It only spends operator upstream quota / the per-IP demo limit on agentseek.dev — it does not unlock You.com or TypeSafe secrets.

```text
AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI
```

### Cursor MCP (live)

Paste into your Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "agent-seek": {
      "url": "https://agentseek.dev/mcp",
      "headers": {
        "Authorization": "Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI"
      }
    }
  }
}
```

### Curl (live)

```bash
curl -sS -X POST https://agentseek.dev/v1/search \
  -H "Authorization: Bearer AS_LXxYWY1wQcEwliYnkfAXRA-c0sPlsRtVz4j_ZvJRlnI" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10,"max_candidates":50}'
```

Zero-auth inspect (no key): `GET https://agentseek.dev/v1/sandbox`, `GET /health`, `GET /openapi.json`.

| | Live demo | Local clone |
| --- | --- | --- |
| MCP | `https://agentseek.dev/mcp` | `http://127.0.0.1:8787/mcp` |
| Also mounted | `https://agentseek.dev/.well-known/mcp` | `http://127.0.0.1:8787/.well-known/mcp` |
| Server card | `https://agentseek.dev/.well-known/mcp/server-card.json` | `http://127.0.0.1:8787/.well-known/mcp/server-card.json` |
| Skill | `https://agentseek.dev/.well-known/agent-skills/agent-seek/SKILL.md` | same path on `:8787` |

`search_web` accepts Bearer (public demo key on live, or your local `AGENT_SEEK_API_KEY`) **or** OAuth scope `search:read`. Health/docs helper tools are unauthenticated.

## Quickstart — local clone

Python **3.12+**. Clone this repo:

```bash
git clone https://github.com/Gitmaxd/agent-seek.git
cd agent-seek

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Fill `.env` (never commit it):

| Variable | Needed for | Notes |
| --- | --- | --- |
| `YDC_API_KEY` | Live / local **search** | You.com Platform (paid upstream) |
| `TYPESAFE_API_KEY` | Live / local **search** | TypeSafe / Jev (paid upstream) |
| `AGENT_SEEK_API_KEY` | Local API + MCP Bearer only | Local placeholder `dev-agent-seek-key-change-me` — **not** the live public `AS_…` demo key |
| `OPENAI_API_KEY` | Optional **LLM-judge eval** | `evals/public_v1` harness only; not used by search |

**Self-hosters:** real search needs **paid** You.com + TypeSafe keys; without them only tests, fixtures, and the sandbox work. **Tests run without live keys** (`pytest -q` uses fixtures). Local `POST /v1/search` / MCP `search_web` needs those two paid upstream keys plus a local `AGENT_SEEK_API_KEY`.

```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8787
```

Open http://127.0.0.1:8787 — the UI calls same-origin `/v1/search` with the injected Agent Seek key (never exposes You.com / TypeSafe keys). The website UI is fixed **snip** (no Mode control). API/MCP default is `snip`; pass `mode=deep` for Stage A survivor fetch.

### Curl (local)

```bash
source .venv/bin/activate
export AGENT_SEEK_API_KEY="$(grep ^AGENT_SEEK_API_KEY= .env | cut -d= -f2-)"

curl -sS http://127.0.0.1:8787/health

curl -sS -X POST http://127.0.0.1:8787/v1/search \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Introducing System One Models Jev","k":10,"max_candidates":50}'

# Opt-in deep: Stage A survivor fetch (cap 12; slower / more expensive)
curl -sS -X POST http://127.0.0.1:8787/v1/search \
  -H "Authorization: Bearer $AGENT_SEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"when were langchain deep agents released","k":10,"max_candidates":50,"mode":"deep"}'
```

### Local MCP

After `cp .env.example .env`, set `AGENT_SEEK_API_KEY=dev-agent-seek-key-change-me` (or any local secret). That key is **only** for your machine — it is not the live `AS_…` demo key.

```json
{
  "mcpServers": {
    "agent-seek": {
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_LOCAL_AGENT_SEEK_API_KEY"
      }
    }
  }
}
```

### Optional / advanced: OAuth DCR

Agents that prefer Dynamic Client Registration can use `POST /oauth2/register` and the flows in [`/auth.md`](https://agentseek.dev/auth.md). You do **not** need OAuth to try the live demo — copy the public Bearer key above. Full tool contract: [`skills/agent-seek/SKILL.md`](./skills/agent-seek/SKILL.md).

## Tests

```bash
pytest -q
```

No live API keys required. Optional live evals (soft-fail):

```bash
# Legacy substring hit-rate (evals/queries.json)
AGENT_SEEK_LIVE=1 python scripts/eval_compare.py

# Pairwise LLM-judge suite — dry-run needs no keys
python scripts/eval_llm_judge.py --dry-run
```

Frozen first run: [`evals/public_v1/published/v1.0.0-first-run/`](./evals/public_v1/published/v1.0.0-first-run/). Public page: [`/eval`](https://agentseek.dev/eval) (markdown: [`/eval.md`](https://agentseek.dev/eval.md)). Suite contract: [`evals/public_v1/README.md`](./evals/public_v1/README.md).

## What it is

A small FastAPI service:

1. **Discover** — You.com web candidates (hard cap 100)
2. **Rank** — TypeSafe Jev cascade (subject / republisher / prompt-injection gates)
3. **Snip (API/MCP default)** — Stage B on title/URL/snippet. **Deep** (pass `mode=deep`) fetches main text for Stage A survivors (cap 12), then Stage B
4. **Return** — top-k scored URLs, snippets, flags, and signals

On total Jev failure: HTTP **200** with `meta.ranking: "raw_fallback"`.

```
apps/api/          FastAPI (health, /v1/search, OAuth, MCP, serves UI)
apps/web/          Google-simple static UI + public agent/human prose
packages/core/     discover (You.com) + Jev cascade + cache + deep fetch
skills/agent-seek/ Agent Skill (well-known serves SKILL.md)
fixtures/          Recorded You.com + Jev payloads (keys redacted)
tests/             Offline pytest (no live upstream)
evals/queries.json Frozen legacy eval queries (optional live compare script)
evals/public_v1/   Pairwise LLM-judge suite + published first run (`/eval`)
```

| Route | Notes |
| --- | --- |
| `GET /health` | `{ok:true, version}` |
| `POST /mcp` | MCP Streamable HTTP |
| `GET /agents.md` | Public agent how-to |
| `POST /v1/search` | Bearer `AGENT_SEEK_API_KEY` or OAuth `search:read` |
| `GET /v1/search` | Same params as query string |
| `GET /v1/sandbox` | Zero-auth canned `SearchResponse` |
| `mode=snip` | API/MCP default — Stage B on title/URL/snippet (cheaper/faster) |
| `mode=deep` | Opt-in — Stage A survivor fetch, then Stage B |

MCP `search_web` does **not** accept REST-only `nocache` / `rank`. See `/docs`, `/developers`, `/api/docs`.

## Progressive Disclosure Search Ranking

You.com discovers candidates. TypeSafe Jev (a System One model) re-scores them in stages. Agent Seek returns a small scored URL list; it does not write the answer. The funnel exists so you can start at the head of the list: prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches.

Ranking is progressive: cheap judgment first, then fetch and deeper judgment only on survivors.

1. **Discover** — up to **100** You.com candidates (default 50 in)
2. **Stage A** — Jev scores coarse relevance across the batch; weak hits drop
3. **Disclose** — API/MCP default `mode=snip` skips fetch and ranks title / URL / snippet only (fast/cheap). Pass `mode=deep` to fetch main text for up to **12** Stage A survivors (not a full-web crawl; slower/more expensive). Website UI is fixed `snip`.
4. **Stage B** — Jev scores the richer evidence, then Agent Seek composes a 0–1 score, collapses near-dupes, applies hard gates, and returns top-`k`

Stage B is where page text (not just SERP blurbs) drives answerability, fact-stated, authority, and injection-risk judgments.

On total Jev failure: HTTP **200** with `meta.ranking: "raw_fallback"`.

### Jev metrics

Returned under `signals` when parsed:

| Signal | Role |
| --- | --- |
| `answerability` | How well the page helps answer the query |
| `states_sought_fact` | Whether the asked fact is stated explicitly |
| `authority` | Official / first-party vs third-party rewrite |
| `on_topic` | Tightly on-topic (soft) |
| `subject_match` | Same entity the query asks about |
| `spam` | Soft demotion when high |
| `prompt_injection` | Prompt-injection / instruction-hijack risk (UI: **Injection risk**) |

**Hard gates** (order, 0.55): `subject_match` → `is_republisher` → `prompt_injection`. `subject_match` and `is_republisher` fail-open if parse missing; `prompt_injection` is fail-flagged (missing/unparseable dropped from `results`). Gated rows stay in `raw_results`. If hard gates empty the scored list, pre-gate ranking is restored and each restored row has `gates_relaxed: true` (relaxed-safety response; not a SearchMeta field).

Score composition favors answerability, with a smaller weight for stating the sought fact and a gated authority boost when scores are close — primary sources preferred without crushing a page that clearly answers.

A pairwise LLM-judge harness compares You.com order vs Agent Seek cascade on the **same discover pool** (`evals/public_v1/`). [`/eval`](https://agentseek.dev/eval) shows snip preference beside the top-3 gold hit rate. The frozen deep run is in [`evals/public_v1/published/v1.0.0-first-run/`](./evals/public_v1/published/v1.0.0-first-run/).

## Rate limiting (optional)

Local/dev is **unlimited** unless you set both `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`. Missing either disables limiting — no Redis calls.

When enabled: sliding 60s window **per client IP** (not the shared UI API key), default `AGENT_SEEK_RATE_LIMIT_PER_MIN=60`, on search and MCP `search_web` only. Client IP is the **rightmost** public `X-Forwarded-For` hop, then `X-Real-IP`, then the socket address. Redis/network errors fail closed (`503`). Burst `429` is `code=RATE_LIMITED` and may include `Retry-After`.

The public host can also apply a lifetime per-IP demo quota, gated by `AGENT_SEEK_DEMO_MODE` (default `disabled`; live agentseek.dev sets `enabled` at deploy). When enabled: `AGENT_SEEK_DEMO_SEARCH_LIMIT` (default 5, Upstash `INCR`, no TTL). REST `/v1/search`, `/api/v1/search` (the HTML UI and any other REST client), and MCP `search_web` share that allowance. Exhausted searches from that IP return `429` `application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`. Unauthenticated MCP helper tools do not consume it. See `.env.example`.

## Secrets

Never commit `YDC_API_KEY`, `TYPESAFE_API_KEY`, local `AGENT_SEEK_API_KEY`, `OPENAI_API_KEY`, or Upstash tokens. `.env.example` has placeholders only. The live `AS_…` value in `/config.js` is a **public demo key** (documented on purpose). How we handle that vs self-host hardening: [`SECURITY.md`](./SECURITY.md).

## Community

- [Contributing](./CONTRIBUTING.md) — tests, product locks (You.com / Jev / 100-cap)
- [Security policy](./SECURITY.md) — report vulns to 131803031+Gitmaxd@users.noreply.github.com
- [Code of conduct](./CODE_OF_CONDUCT.md)
- Release notes: [`CHANGELOG.md`](./CHANGELOG.md)

## License

[MIT](./LICENSE). SPDX-License-Identifier: MIT

## Author

Built by [Git Maxd](https://x.com/gitmaxd) ([@gitmaxd](https://x.com/gitmaxd)). Follow on X for more.
