# Contributing to Agent Seek

Thanks for helping. Agent Seek is a small ranked-search service: You.com discovers candidates, TypeSafe Jev cascade-ranks them, and clients get a scored JSON list.

## Before you start

1. Read `AGENTS.md`, `skills/agent-seek/SKILL.md`, and `docs/agent_contract.json`. Local `docs/PRD*.md` drafts are gitignored and optional.
2. Do **not** reopen locked product choices:
   - You.com for discover (no Google scrape, no Firecrawl)
   - Jev cascade ranking
   - Hard cap of **100** discover candidates
   - API/MCP default `mode=snip`; pass `mode=deep` for Stage A survivor fetch (cap 12). Website UI is fixed `snip`
   - No Deep Research / Deep Agents coupling
   - No public `/bench` and no self-serve API key minting
3. Never commit secrets — `.env` is gitignored; use `.env.example` placeholders.

## Tests

Python **3.12+**, from the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

No live API keys required. Prefer fixtures over live upstream calls. CI runs the same `pytest -q` command. Gate live work with `AGENT_SEEK_LIVE=1` (optional eval: `python scripts/eval_compare.py`).

## Pull requests

- Keep changes scoped. Match existing FastAPI / pytest patterns.
- Run `pytest -q` before opening a PR.
- When behavior changes, update the Skill / `llms.txt` / OpenAPI / contract tests that lock it.
- User-visible changes: add a `CHANGELOG.md` note.

See also [SECURITY.md](./SECURITY.md) and [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).
