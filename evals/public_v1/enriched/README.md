# Frozen shortlist enrichment

HTML `<title>` and meta description for every URL already stored on a published shortlist. No You.com call and no rediscovery.

| Artifact | Source run |
| --- | --- |
| `v1.0.0-snip-shortlists.jsonl` | `published/v1.0.0-snip` (`mode=snip`) |
| `v1.0.0-deep-shortlists.jsonl` | `published/v1.0.0-first-run` (`mode=deep`) |

Each file is one JSON object per query. `candidates[]` is the union of `baseline_urls` and `treatment_urls` (baseline order, then new treatment URLs). Fields: `url`, `title`, `snippet`, `fetch`, `http_status`, `final_url`, `content_type`, `error`, `elapsed_ms`.

`fetch` is `ok`, `empty`, `non_html`, `http_error`, or `failed`. Counts and the user-agent / rate limit are in the sidecar `*.meta.json`. A title can still be present on `http_error` (a block page). Graders and the pairwise `--pools` loader copy title and snippet only when `fetch` is `ok`.

Title is `<title>`, then `og:title`, then `twitter:title`. Snippet is `meta name=description`, then `og:description`, then `twitter:description`. Body text is not used.

The fetch is polite: one request at a time per host, a gap between them, a short timeout, and a cap on bytes read. Resume state is a local cache (`--cache`, default `/tmp/agent-seek-shortlist-enrich.json`), not committed.

## Orchestrator

Re-run both frozen runs in one pass (shared fetches):

```bash
python scripts/eval_enrich_shortlists.py
```

One run:

```bash
python scripts/eval_enrich_shortlists.py \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl \
    --label v1.0.0-snip
```

Then rebuild the human packet only if grading has not started. Same seed and n:

```bash
python scripts/eval_human_packet.py sample \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out-dir evals/public_v1/human_v1 \
    --pools evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl
```

The top-3 scorer reads this snip file for title and snippet. It does not need a second enrich pass. See [`../top3/README.md`](../top3/README.md).
