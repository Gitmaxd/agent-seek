# Agent Seek Eval v1 — Gold answer key

**Status:** locked `2026-09-21T21:56:50Z`

Authored at Git’s request for Eval v1. Answers were written from query intent and public facts; **published preference shortlists were not consulted**.

The top-3 LLM scorer should treat `gold_answer` as the fact to find; `gold_notes` guide acceptable sources/phrasing.

---

## p1-001 · L1 · official tutorial

**Query:** FastAPI dependency injection tutorial

**Gold answer:** FastAPI dependency injection is documented in the official FastAPI tutorial under Dependencies: you declare dependencies with Depends() (and related patterns) so FastAPI resolves and injects them into path-operation parameters.

**Notes:** Prefer fastapi.tiangolo.com tutorial/dependencies; not third-party blog rewrites.

---

## p1-002 · L1 · official index docs

**Query:** Postgres JSONB GIN index documentation

**Gold answer:** PostgreSQL documents GIN indexes for JSONB (and related jsonb operators) in the official Postgres docs: GIN is commonly used to index JSONB for containment and key existence queries.

**Notes:** Canonical host: postgresql.org documentation on jsonb indexing / GIN.

---

## p1-003 · L1 · canonical RFC

**Query:** RFC 9110 HTTP semantics

**Gold answer:** RFC 9110 defines HTTP semantics (methods, status codes, headers, caching-related semantics) and is the current authoritative HTTP semantics specification on the RFC Editor / IETF stream.

**Notes:** Look for RFC 9110 on rfc-editor.org (not random HTML mirrors alone).

---

## p1-004 · L1 · official React docs

**Query:** React useEffect cleanup function

**Gold answer:** In React, the cleanup function for an effect is the optional function returned from the useEffect callback; React runs it before re-running the effect and on unmount to cancel subscriptions/timers.

**Notes:** Prefer react.dev docs on useEffect / synchronizing with effects.

---

## p1-005 · L1 · official k8s docs

**Query:** Kubernetes liveness vs readiness probe

**Gold answer:** In Kubernetes, a liveness probe decides whether to restart a container that is stuck; a readiness probe decides whether the Pod should receive Service traffic. They answer different questions and are configured separately.

**Notes:** Official kubernetes.io probe documentation.

---

## p1-006 · L1 · official SQLite docs

**Query:** SQLite WAL mode concurrency

**Gold answer:** SQLite WAL (write-ahead logging) mode allows concurrent readers while a writer proceeds, with documented locking/checkpoint behavior in the official SQLite WAL documentation.

**Notes:** sqlite.org WAL docs.

---

## p1-007 · L1 · official KV limits

**Query:** Cloudflare Workers KV limits

**Gold answer:** Cloudflare Workers KV documents product limits (key/value size, request rates, eventual consistency characteristics) in the official Cloudflare Workers KV limits documentation.

**Notes:** Prefer developers.cloudflare.com Workers KV limits.

---

## p1-008 · L1 · canonical spec

**Query:** OpenAPI 3.1 specification

**Gold answer:** OpenAPI 3.1 is the OpenAPI Specification revision that aligns schemas with JSON Schema 2020-12; the authoritative text is published by the OpenAPI Initiative.

**Notes:** Canonical OpenAPI 3.1 Specification, not random tutorial summaries.

---

## p1-009 · L1 · official Python docs

**Query:** Python asyncio TaskGroup

**Gold answer:** Python’s asyncio.TaskGroup (3.11+) runs multiple tasks as a group and cancels remaining tasks if one fails, providing structured concurrency in the official asyncio docs.

**Notes:** docs.python.org asyncio TaskGroup.

---

## p1-010 · L1 · official Redis docs

**Query:** Redis Streams consumer groups

**Gold answer:** Redis Streams consumer groups let multiple consumers cooperatively read a stream with per-consumer acknowledgment and pending-entry tracking, as documented in official Redis Streams docs.

**Notes:** redis.io Streams / consumer groups.

---

## p1-011 · L1 · official Actions docs

**Query:** GitHub Actions cache key documentation

**Gold answer:** GitHub Actions cache keys identify cache entries; the official Actions cache documentation explains key construction, restore keys, and when a cache hit/miss occurs.

**Notes:** docs.github.com Actions cache.

---

## p1-012 · L1 · MDN CSP docs

**Query:** MDN Content-Security-Policy

**Gold answer:** Content-Security-Policy (CSP) is an HTTP response header that restricts resource loading to mitigate XSS and related attacks; MDN documents directives and usage.

**Notes:** Prefer MDN Web Docs CSP reference.

---

## p1-013 · L1 · official Docker docs

**Query:** Docker multi-stage build best practices

**Gold answer:** Docker multi-stage builds use multiple FROM stages so build tools stay in earlier stages while the final image copies only needed artifacts, reducing image size; official Docker docs describe the pattern.

**Notes:** docs.docker.com multi-stage builds.

---

## p1-014 · L1 · official Prometheus docs

**Query:** Prometheus histogram vs summary

**Gold answer:** In Prometheus, histograms sample observations into configurable buckets and can compute quantiles from those buckets; summaries calculate client-side quantiles over a sliding window and are not aggregatable the same way across instances.

**Notes:** prometheus.io histogram vs summary docs.

---

## p1-015 · L1 · authoritative TLS overview

**Query:** TLS 1.3 handshake overview

**Gold answer:** TLS 1.3 shortens the handshake (typically 1-RTT, with 0-RTT options) and removes legacy cryptographic algorithms compared with TLS 1.2; authoritative overviews appear in RFC 8446 and related TLS documentation.

**Notes:** RFC 8446 / IETF TLS 1.3 materials.

---

## p1-016 · L2 · product milestone date

**Query:** When was Next.js App Router stable

**Gold answer:** The Next.js App Router was marked stable in Next.js 13.4, released May 4, 2023, when Vercel announced it as ready for production adoption.

**Notes:** Prefer nextjs.org blog for 13.4 / App Router stable.

---

## p1-017 · L2 · first-party launch post

**Query:** LangChain Deep Agents release announcement

**Gold answer:** LangChain Deep Agents refers to LangChain’s open-source deepagents / Deep Agents work (planning/tool-using agents); first-party announcement and docs live on LangChain’s official channels (blog, docs, or GitHub), not third-party roundups.

**Notes:** Prefer langchain.com / official LangChain GitHub announcement posts over SEO blogs.

---

## p1-018 · L2 · official product docs

**Query:** Factory.ai Droid skills documentation

**Gold answer:** Factory.ai Droid skills are documented in Factory’s official docs as reusable instructions/workflows agents can load (Skills), distinct from ad-hoc chat prompts.

**Notes:** Prefer docs.factory.ai skills documentation.

---

## p1-019 · L2 · pricing and limits

**Query:** Vercel Fluid compute pricing limits

**Gold answer:** Vercel Fluid compute (and related Active CPU / fluid pricing) is defined on Vercel’s official pricing and docs pages with plan limits and billing units; treat vercel.com pricing/docs as authoritative over secondary blogs.

**Notes:** vercel.com pricing / fluid compute docs.

---

## p1-020 · L2 · official rate limits

**Query:** Upstash Redis REST rate limits

**Gold answer:** Upstash Redis documents REST/API rate limits and plan quotas in official Upstash documentation (requests per second / day depending on plan).

**Notes:** Prefer upstash.com docs rate limits.

---

## p1-021 · L2 · official branching docs

**Query:** Neon serverless Postgres branching docs

**Gold answer:** Neon documents database branching as copy-on-write Postgres branches for development and preview workflows in the official Neon docs.

**Notes:** neon.tech docs on branching.

---

## p1-022 · L2 · official tool-use docs

**Query:** Anthropic tool use JSON schema

**Gold answer:** Anthropic’s tool use / function calling uses JSON Schema-shaped tool definitions in the Messages API; official Anthropic docs specify the schema and tool-result flow.

**Notes:** docs.anthropic.com tool use.

---

## p1-023 · L2 · official structured-output docs

**Query:** OpenAI structured outputs JSON schema

**Gold answer:** OpenAI Structured Outputs constrain model output to a supplied JSON Schema (strict structured outputs); official OpenAI docs describe enabling JSON Schema adherence.

**Notes:** platform.openai.com structured outputs docs.

---

## p1-024 · L2 · official MCP spec

**Query:** MCP streamable HTTP transport

**Gold answer:** MCP (Model Context Protocol) defines Streamable HTTP as a transport for client–server communication in the official MCP specification (alongside other transports).

**Notes:** Prefer modelcontextprotocol.io / official MCP spec for streamable HTTP.

---

## p1-025 · L2 · canonical OAuth spec

**Query:** OAuth 2.1 authorization code PKCE

**Gold answer:** OAuth 2.1 keeps authorization code + PKCE as the recommended public-client pattern: the client uses a code_verifier/challenge so intercepted codes cannot be redeemed without the verifier.

**Notes:** OAuth 2.1 draft/spec and related IETF materials; also OAuth 2.0 PKCE RFC 7636 background.

---

## p1-026 · L2 · official R2 pricing

**Query:** Cloudflare R2 egress pricing

**Gold answer:** Cloudflare R2 is designed with no egress fees to the public Internet in Cloudflare’s standard R2 pricing positioning; authoritative numbers and caveats are on Cloudflare’s R2 pricing page.

**Notes:** developers.cloudflare.com / cloudflare.com R2 pricing (note any operation/class A/B fees separately from 'egress').

---

## p1-027 · L2 · official product docs

**Query:** Exe.dev persistent Linux VMs

**Gold answer:** exe.dev provides persistent Linux VMs for development/deployment; official product behavior and docs live on exe.dev (and related first-party docs), not random mirrors.

**Notes:** Prefer exe.dev / official docs.md materials.

---

## p1-028 · L2 · official product docs

**Query:** Cursor Background Agents documentation

**Gold answer:** Cursor Background Agents (cloud agents) are Cursor’s remote coding agents that work on a repo/branch asynchronously; official behavior is documented in Cursor’s product docs.

**Notes:** Prefer cursor.com docs on background/cloud agents.

---

## p1-029 · L2 · official Temporal docs

**Query:** Temporal workflow vs activity

**Gold answer:** In Temporal, a workflow is the durable orchestration logic; an activity is a non-deterministic unit of work (API call, DB write) invoked from a workflow. Official Temporal docs define the split.

**Notes:** docs.temporal.io workflow vs activity.

---

## p1-030 · L2 · official engine caveats

**Query:** ClickHouse ReplacingMergeTree caveats

**Gold answer:** ClickHouse ReplacingMergeTree can collapse duplicate rows by sorting key during merges, but replacements are not instantaneous and queries can still see duplicates until merges finish unless using FINAL or other patterns—official docs warn about these caveats.

**Notes:** clickhouse.com ReplacingMergeTree documentation.

---

## p1-031 · L2 · official Pydantic v2 docs

**Query:** Pydantic v2 model_validate vs parse_obj

**Gold answer:** In Pydantic v2, model_validate() is the supported way to parse/validate data into a model; parse_obj() is the v1-era API (removed/renamed in the v2 migration).

**Notes:** docs.pydantic.dev v2 migration / model_validate.

---

## p1-032 · L2 · support vs spec

**Query:** HTTP 103 Early Hints browser support

**Gold answer:** HTTP 103 Early Hints (RFC 8297) lets servers send preliminary headers (often Link preload) before the final response; browser support is partial and evolving—prefer MDN/Can I Use plus the RFC over random blogs.

**Notes:** MDN Early Hints / RFC 8297.

---

## p1-033 · L2 · spec or MDN

**Query:** WebAuthn discoverable credentials passkeys

**Gold answer:** WebAuthn discoverable credentials (often called passkeys) store credential material on the authenticator so the user can authenticate without the RP first supplying a credential ID; W3C WebAuthn and MDN document the model.

**Notes:** W3C WebAuthn / MDN passkeys.

---

## p1-034 · L2 · official S3 docs

**Query:** S3 conditional writes If-None-Match

**Gold answer:** Amazon S3 supports conditional writes using headers such as If-None-Match (e.g. '*' to create only if the object does not exist) as documented in official AWS S3 API docs.

**Notes:** docs.aws.amazon.com S3 conditional requests / PutObject.

---

## p1-035 · L2 · pooling caveats

**Query:** Postgres LISTEN NOTIFY connection pooling pitfalls

**Gold answer:** PostgreSQL LISTEN/NOTIFY is session-based: notifications are delivered on the connection that issued LISTEN. Transaction poolers that multiplex connections can break or confuse LISTEN/NOTIFY unless you use a dedicated session connection—official Postgres docs plus pooler docs warn about this.

**Notes:** postgresql.org NOTIFY + popular pooler caveats (PgBouncer session vs transaction).

---

## p1-036 · L3 · authoritative bio vs SEO

**Query:** Who created Redis

**Gold answer:** Redis was created by Salvatore Sanfilippo (antirez).

**Notes:** Prefer antirez / Redis history sources over SEO name-collision pages.

---

## p1-037 · L3 · primary paper vs rewrite

**Query:** Original paper introducing the Transformer attention architecture

**Gold answer:** The Transformer architecture was introduced in the 2017 paper “Attention Is All You Need” by Vaswani et al. (NeurIPS 2017).

**Notes:** Prefer the original paper (arXiv:1706.03762) over blog paraphrases.

---

## p1-038 · L3 · canonical host vs scrapers

**Query:** Official X/Twitter profile for OpenAI

**Gold answer:** OpenAI’s official presence on X/Twitter is the verified @OpenAI account on x.com (canonical host), not scraper/mirror profile pages.

**Notes:** Canonical: https://x.com/OpenAI

---

## p1-039 · L3 · canonical Instagram vs viewers

**Query:** NASA Instagram on the official Instagram host

**Gold answer:** NASA’s official Instagram profile is on Instagram’s own host (instagram.com), not third-party Instagram viewer/mirror sites.

**Notes:** Canonical Instagram host for @nasa.

---

## p1-040 · L3 · canonical github.com profile

**Query:** GitHub user torvalds

**Gold answer:** Linus Torvalds’ GitHub profile is github.com/torvalds on the official github.com host.

**Notes:** Canonical: https://github.com/torvalds

---

## p1-041 · L3 · encyclopedia vs SEO rewrite

**Query:** Wikipedia English: Transformer (machine learning model) vs SEO blog summaries of Attention Is All You Need

**Gold answer:** For an encyclopedia-grade overview of the Transformer ML model, prefer the English Wikipedia article (and/or the original paper) over SEO blog summaries of Attention Is All You Need.

**Notes:** Wikipedia Transformer (machine learning model) vs random SEO posts.

---

## p1-042 · L3 · official date vs rumor

**Query:** Apple Vision Pro US release date

**Gold answer:** Apple Vision Pro became available in the United States on February 2, 2024 (Apple Newsroom).

**Notes:** Prefer apple.com newsroom over rumor aggregators.

---

## p1-043 · L3 · first-party distinction

**Query:** Difference between LangGraph and LangChain agents

**Gold answer:** LangGraph is LangChain’s library/framework for durable, graph-structured agent workflows; “LangChain agents” more broadly includes earlier agent abstractions and tooling. Official LangChain docs distinguish LangGraph as the recommended durable agent orchestration layer.

**Notes:** Prefer official LangChain/LangGraph docs for the product distinction.

---

## p1-044 · L3 · official vs tutorial-farm

**Query:** Official Solidity language documentation

**Gold answer:** The official Solidity language documentation is published by the Solidity team (docs.soliditylang.org), not tutorial-farm mirrors.

**Notes:** Canonical: docs.soliditylang.org

---

## p1-045 · L3 · official product distinction

**Query:** Cloudflare Workers vs Cloudflare Pages Functions

**Gold answer:** Cloudflare Workers is the general serverless runtime on Cloudflare’s edge; Cloudflare Pages Functions are Functions integrated with Pages projects (Workers under the hood for Pages). Official Cloudflare docs describe the product split and when to use each.

**Notes:** developers.cloudflare.com Workers vs Pages Functions.

---

## p1-046 · L3 · educational defensive overview

**Query:** What is prompt injection? defensive overview for LLM applications

**Gold answer:** Prompt injection is an attack where untrusted text (user input or retrieved content) tries to override an LLM’s instructions; defensive overviews stress isolation, privilege reduction, and treating model output as untrusted—prefer security vendors/OWASP-style guidance over hype posts.

**Notes:** Educational defensive definition; not exploit steps.

---

## p1-047 · L3 · official release notes

**Query:** PyTorch 2.0 release date

**Gold answer:** PyTorch 2.0 was released on March 15, 2023 (official PyTorch release/GitHub tag v2.0.0).

**Notes:** Prefer pytorch.org / GitHub pytorch v2.0.0 release.

---

## p1-048 · L3 · canonical maintainer

**Query:** Who maintains the ripgrep project

**Gold answer:** ripgrep is primarily maintained by Andrew Gallant (BurntSushi) on GitHub.

**Notes:** Prefer github.com/BurntSushi/ripgrep.

---

## p1-049 · L3 · official security channel

**Query:** Official Kubernetes security announcements / CVE channel vs random aggregators

**Gold answer:** Official Kubernetes security announcements and CVE disclosures are published through Kubernetes’ official security channels (e.g. kubernetes.io security / official mailing lists and disclosure process), not random third-party aggregators as the primary source.

**Notes:** kubernetes.io security disclosure / official announce channels.

---

## p1-050 · L3 · official API distinction

**Query:** Stripe Tax vs Stripe Tax Calculations API distinction

**Gold answer:** Stripe Tax is Stripe’s product for calculating/collecting tax in payments flows; Stripe’s Tax Calculations API is the API surface for performing tax calculations (often used with Tax). Official Stripe docs distinguish the Tax product vs the Calculations API endpoints.

**Notes:** Prefer stripe.com docs Tax vs Tax Calculations API.

---
