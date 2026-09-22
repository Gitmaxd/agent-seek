# Top-3 gold-answer scorer

Checks whether the Agent Seek **snip** top-3 (published `treatment_urls`, k=3) states the locked `gold_answer`. One model call per page. A query hits when any successfully judged page returns `states_gold_answer: true`. Queries whose page calls all fail are errors, not misses.

The reviewed run is published at `evals/public_v1/published/v1.0.0-snip-top3/` (**43/50** hits, errors 0). This scorer directory does not hold that score. `--dry-run` writes nothing. A missing `OPENAI_API_KEY` soft-skips and does not invent a score.

## Published path

`/eval` reads the hit rate from `evals/public_v1/published/v1.0.0-snip-top3/` (`summary.json` with `"kind": "top3_gold"` and `run_meta.json`). The page uses `hits / scored` from that summary (**43/50**). When `results.jsonl` is in that directory, the card also shows first-hit rank counts from hit rows. Scratch under `results/run_*/` is gitignored and is not shown. Page text from the live run is not shipped. If that published directory is missing or incomplete, `/eval` says **not yet run**.

| Input | Role |
| --- | --- |
| `gold_v1/gold_key.jsonl` | `gold_answer` / `gold_notes` |
| `published/v1.0.0-snip/per_query.jsonl` | treatment top-3 URLs |
| `enriched/v1.0.0-snip-shortlists.jsonl` | optional title and snippet |
| `--page-text` JSONL `{id, url, text}` | optional fetched page text; this repo does not ship one |

Prompt: `PROMPT_v1.md`. Schema: `schema.json`. Model pin matches the pairwise judge: `gpt-5.6-sol`, Responses API, `reasoning.effort=medium`, `reasoning.mode=standard`, temperature unset.

Title and snippet alone are thin evidence. The prompt must return false when the supplied text does not state the fact, including when only the URL is present. Pass `--page-text` when a stronger live run is wanted. That file is produced outside this scorer (no You.com rediscovery).

## Orchestrator — live run

After enrichment (already at `evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl`):

```bash
# Plan only. No key required. Writes nothing.
python scripts/eval_top3.py --dry-run

# Live. Needs OPENAI_API_KEY. Writes a gitignored run directory.
python scripts/eval_top3.py \
    --gold evals/public_v1/gold_v1/gold_key.jsonl \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --enrich evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl \
    --out-dir evals/public_v1/top3/results/run_<UTC>
```

Optional page text:

```bash
python scripts/eval_top3.py \
    --page-text path/to/page_text.jsonl \
    --out-dir evals/public_v1/top3/results/run_<UTC>
```

`--limit 2` is a smoke. Do not publish `summary.json` until the full run is reviewed. `results/run_*/` is gitignored.

Offline aggregation of an existing judgments file (no API), used by tests:

```bash
python scripts/eval_top3.py \
    --judgments path/to/judgments.jsonl \
    --out-dir /tmp/top3-fixture
```

Each judgments row is `{id, url, states_gold_answer, confidence, rationale}`.
