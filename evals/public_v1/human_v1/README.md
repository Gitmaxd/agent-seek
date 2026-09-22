# Human grading packet

Blind sample of the published snip run (`v1.0.0-snip`). Picks are blank. No agreement has been computed.

| | |
| --- | --- |
| Items | 30 (inside the 25–30 band) |
| Seed | `20260921` |
| Mix | 22 queries the published judge mapped to Agent Seek, 8 to You.com order, 0 ties |
| Order | Stratified draw, then listed by query id |
| Labels on the form | List A and list B only |

`packet.md`, `packet.jsonl`, and `packet.csv` are the form. Titles and snippets come from [`../enriched/v1.0.0-snip-shortlists.jsonl`](../enriched/v1.0.0-snip-shortlists.jsonl): an HTML `<title>` and meta description fetched from each frozen URL. That fetch does not call You.com. A blank title or snippet means `fetch` was not `ok` (or the page had no tag). Block-page titles are not copied onto the form. `key.jsonl` holds the published judge's A/B/tie and the arm mapping for scoring. `sample_meta.json` holds the stratum sizes and the pools path. Leave both closed while grading.

## What Git does by hand

1. Open `packet.md` (or the CSV / JSONL). Do not open `key.jsonl`.
2. For each item, write `A`, `B`, or `tie`. A note is optional.
3. If you filled the markdown or CSV, copy those picks into `human` on `packet.jsonl` (one JSON object per line). The score script reads that file.
4. Run the scorer. It joins each pick to the published judge on the same blind labels. It will not write a summary if every `human` field is blank.

```bash
python scripts/eval_human_packet.py score \
    --labels evals/public_v1/human_v1/packet.jsonl \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out evals/public_v1/human_v1/summary.json
```

Commit `summary.json` when you want `/eval` to show the agreement and Cohen's kappa. Do not type those numbers in by hand.

Regenerate the packet only before anyone has started, and only with the same `--n 30 --seed 20260921` unless you intend a new sample. `--pools` attaches titles and snippets by exact URL. It does not rediscover and it does not change which ids are drawn.

```bash
python scripts/eval_human_packet.py sample \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out-dir evals/public_v1/human_v1 \
    --pools evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl
```
