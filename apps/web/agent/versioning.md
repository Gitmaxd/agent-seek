---
title: Agent Seek API versioning
description: URL versioning, deprecation, and Sunset policy for the Agent Seek HTTP API.
canonical: /docs/versioning.md
last-updated: 2026-09-20
---

# Agent Seek API versioning

Agent Seek versions the HTTP API in the **URL path**. The current public surface is **`/v1`**. `GET /health` and OpenAPI `info.version` carry the prototype build (`0.1.39`). `meta.agent_seek_version` on search responses is the same value.

## What is stable

- Path prefix `/v1`
- `POST /v1/search` and `GET /v1/search` field names documented in `/openapi.json`
- OAuth scopes `search:read`, `mcp:invoke`, `health:read`
- RFC 9457 `application/problem+json` error members `type`, `title`, `status`, `detail`, `code`, `message`, `hint`

Additive JSON fields on 200 responses are **non-breaking**. Clients must ignore unknown fields.

## How we sunset

Breaking changes ship as a new path (`/v2`, …), not as silent incompatible edits to `/v1`.

When a version or field is retiring we:

1. Publish the change on this page and in `CHANGELOG.md`.
2. Mark the operation `deprecated: true` in `/openapi.json`.
3. Send RFC 8594 **`Deprecation`** and **`Sunset`** response headers on the retiring route (Sunset is an IMF-fixdate at least **90 days** after the announcement).
4. Keep the old path serving until the Sunset date, then return `application/problem+json` with `code=UNSUPPORTED_VERSION` and a `hint` pointing here.

`/v1` has **no sunset date**. `GET /v2` today is not published and returns that problem+json document so agents can detect the policy without guessing.

## Discovery

- Public index: [`GET /v1`](/v1) and [`GET /api`](/api)
- OpenAPI: [`/openapi.json`](/openapi.json) (`info.x-api-versioning`)
- Auth: [`/auth.md`](/auth.md)
