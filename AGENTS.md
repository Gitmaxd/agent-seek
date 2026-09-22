# Repository guide

## What this project is

**Agent Seek** is a prototype search service: You.com discovers web candidates, TypeSafe Jev cascade-ranks them, and clients get a small scored JSON list (plus a Google-simple UI). Live origin: `https://agentseek.dev`. Stack: FastAPI (`apps/api`) + static web (`apps/web`) + core pipeline (`packages/core`) + MCP Streamable HTTP at `/mcp`.

This file is for coding agents editing the repo. Product usage (MCP/`search_web`) lives in `skills/agent-seek/SKILL.md`. Human onboarding lives in `README.md`. Public consumer how-to is served `/agents.md` (`apps/web/agent/agents.md`) — do not conflate those surfaces.

## Commands

- Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Configure: copy `.env.example` → `.env` and fill `YDC_API_KEY`, `TYPESAFE_API_KEY`, `AGENT_SEEK_API_KEY` (never commit `.env`)
- Run locally: `uvicorn apps.api.main:app --host 0.0.0.0 --port 8787` then open `http://127.0.0.1:8787`
- Tests: `pytest -q` (from repo root; `pytest.ini` sets `testpaths = tests`, `pythonpath = .`)
- Focused tests: `pytest -q tests/path/to/test_file.py`
- Optional live eval (soft-fail): `AGENT_SEEK_LIVE=1 python scripts/eval_compare.py`

There is no separate lint/typecheck gate in this repo; **`pytest -q` is the required verification.**

## Project layout

- `apps/api/` — FastAPI app: search, health, OAuth, MCP (`mcp_server.py`), agent-ready HTML/markdown/well-known (`agent_ready.py`)
- `apps/web/` — static UI (`index.html`, `app.js`, `styles.css`) and agent/human prose under `apps/web/agent/`
- `packages/core/` — discover, Jev cascade, deep fetch, models, cache
- `skills/agent-seek/` — installable Skill (`SKILL.md` + `reference.md`); well-known serves `SKILL.md` only
- `docs/agent_contract.json` — machine-readable contract locked by tests
- `tests/` — pytest suite (API contract, agent-ready, skill, surface nits)
- `scripts/` — eval/compare helpers
- `fixtures/` — recorded You.com / Jev payloads for offline tests
- `CHANGELOG.md` — release history (not duplicated in README)
- `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
- Local `docs/PRD*.md` — planning drafts, **gitignored**; optional

## Conventions

- Locked product behavior: `skills/agent-seek/SKILL.md`, `docs/agent_contract.json`, and the code. Prefer those over informal notes or gitignored PRDs.
- Do not reopen locked choices without an explicit ask: You.com discover, Jev cascade, max **100** candidates, no Deep Research / Deep Agents coupling, no Google scrape for v0 discover.
- API/MCP default search `mode=snip` (title/URL/snippet). Pass `mode=deep` for Stage A survivor fetch (cap **12**). Website UI is fixed `snip`. MCP tool `search_web` does **not** accept REST-only `nocache` / `rank`.
- Keep agent-facing and human-facing docs accurate when behavior changes (Skill, `llms.txt`, OpenAPI, contract tests).
- Match existing Python / FastAPI / pytest patterns. Prefer fixtures over live upstream calls in CI.
- Do not add a dependency unless the existing stack cannot solve the problem.
- Keep changes scoped to the requested task. Public `/agents.md` is a consumer guide; root `AGENTS.md` is implementer guidance — do not merge them into one file.

## Testing

- Add or update tests when changing API contracts, MCP schemas, ranking gates, or agent-facing prose that tests lock.
- Run focused tests while iterating; run full `pytest -q` before finishing.
- Gate live upstream work with `AGENT_SEEK_LIVE=1`; default CI stays offline via fixtures.

## Verification

Before calling work finished:

1. `pytest -q`
2. If you changed Skill/MCP/docs surfaces, confirm related contract/surface tests still cover the new wording
3. If you changed ranking or search behavior, note any live smoke you ran (optional; not required for docs-only)

If a check fails, fix it and rerun before claiming done.

## Safety

- Never commit secrets or credentials (`YDC_API_KEY`, `TYPESAFE_API_KEY`, `AGENT_SEEK_API_KEY`, OAuth signing keys, `.env`).
- Do not run destructive git or production commands without explicit approval.
- Do not invent self-serve API key minting, billing, or upstream providers that are not in the code.
- Do not hand-edit generated or recorded fixture payloads unless the task is explicitly about fixtures; prefer updating code + tests.
- Public origin defaults to `https://agentseek.dev`; do not re-advertise alternate hosts in live docs.

## PR expectations

- Green `pytest -q`
- Short summary of behavior change (or “docs only”)
- Update `CHANGELOG.md` when shipping user/agent-visible behavior (not required for pure internal chores unless asked)
