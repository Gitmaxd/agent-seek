# Eval v1 — locked design

Locked 2026-09-21. Implementation follows this note. Do not reopen these choices without an explicit ask.

## Frozen inputs

- Same 50 queries (`queries.json`, `p1-001` … `p1-050`).
- Gold answers: `gold_v1/gold_key.jsonl` (locked; published shortlists were not consulted).
- Snip preference stays the published `v1.0.0-snip` pairwise result.
- Deep preference stays `v1.0.0-first-run` until a later fresh deep re-pass.

## Headlines (equal weight)

1. **Snip preference** — blinded pairwise preference of the Agent Seek cascade versus same-pool You.com order. Product default. This is the hero number.
2. **Top-3 hit rate** — for each query, an LLM reads the Agent Seek snip top-3 pages and scores whether the page states `gold_answer`. A query hits when any of those pages states it.

Deep preference is a small secondary figure, not a co-headline. A fresh deep re-pass is a later job.

## Audience and page

`/eval` is the skim-first page for a broader audience and for buyers: two hero cards side by side. Former archive URLs redirect to `/eval`.

No competitor products (no Brave, Google, Exa, or similar). The snip card may still name the same-pool You.com-order baseline, because that is the published comparison.

### Information architecture

1. A short intro: 50 questions, preference against You.com order, and whether the answer is in the top three.
2. Twin hero cards: Snip preference and Top-3 hit rate. Equal visual weight. One plain sentence under each score. Wins / ties / losses and first-hit ranks stay on the cards.
3. Wilson intervals, the judge model, and artifact paths live in a collapsed "How we measured" section.
4. Deep preference is one line under the heroes.
5. Diagnostics and the per-query table stay collapsed, and only show when their artifacts exist.
6. No run button. No invented numbers. Former `/eval/v0` URLs redirect to `/eval`.

## This change

- Enrich frozen shortlist URLs with HTML `<title>` and meta description. No You.com rediscovery.
- Regenerate the existing 30-item human packet (seed `20260921`) with that text. Blinding unchanged. Human picks stay blank. No kappa.
- Scaffold the top-3 scorer. The reviewed live run is published at `published/v1.0.0-snip-top3/` (43/50).

## Published top-3 path

The reviewed snip top-3 gold check is published at `evals/public_v1/published/v1.0.0-snip-top3/` (`summary.json` kind `top3_gold`: **43/50** hits, errors 0). `/eval` reads `hits / scored` from that summary. First-hit rank counts come from `results.jsonl` in that directory when the file is present. Scratch `evals/public_v1/top3/results/` is not a page source. Page text is not shipped. A missing or incomplete directory renders **not yet run**.

## Later

- Fresh deep re-pass.
- Human kappa, only after filled labels.
