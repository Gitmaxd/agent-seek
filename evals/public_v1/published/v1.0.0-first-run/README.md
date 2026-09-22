# Published run — v1.0.0 first run (`mode=deep`)

Frozen live **deep** preference eval for suite `agent-seek-public-v1`. Path stays `v1.0.0-first-run/` so `/eval` links keep working. The snip published run (product default — UI and API/MCP) lives beside this directory at [`../v1.0.0-snip/`](../v1.0.0-snip/).

| | |
| --- | --- |
| Run id | `20260921T044121Z` |
| Judge | `gpt-5.6-sol` · Responses API · `reasoning.effort=medium` · `mode=standard` |
| Mode | `deep` · k=10 · max_candidates=50 |
| Score | **32** Agent Seek · **2** tie · **16** baseline (You.com order) |
| Errors | 0 / 50 |

Same discover pool for both sides; blinded A/B labels. Method: [`../README.md`](../README.md). Public page: [`/eval`](/eval).

This published run measures Agent Seek `mode=deep` (optional richer mode; eval treatment) against same-pool You.com order. Product default is `mode=snip` (UI and API/MCP); snip preference is published separately and is not validated by this deep table. No `pools.jsonl` was written (harness predates pool persistence), so this run cannot be replayed with `--replay-run`.

## Files

- `summary.json` — aggregates + by-tier
- `run_meta.json` — judge pin, prompt sha, timings
- `per_query.jsonl` — one JSON object per query (URLs + mapped winner)

Raw scratch runs under `../results/run_*` stay gitignored.
