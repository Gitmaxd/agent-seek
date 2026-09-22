# Agent Seek public_v1 — pairwise LLM-judge suite

Private / public-ready **evidence harness** for Progressive Disclosure Search Ranking.

**Hypothesis:** on the **same You.com discover pool**, Agent Seek’s cascade top-10 is preferred over raw You.com order top-10 by a blinded LLM judge.

This directory is the frozen suite + contract. The runner is [`scripts/eval_llm_judge.py`](../../scripts/eval_llm_judge.py). The first published run is rendered at [`/eval`](/eval) ([`/eval.md`](/eval.md)).

The legacy substring harness (`evals/queries.json` + `scripts/eval_compare.py`) is unchanged.

## Methodology

| Side | Definition |
| --- | --- |
| **Baseline** `you_com_order` | Top-`k` of the discover list in You.com order |
| **Treatment** `agent_seek_cascade` | Cascade rank with suite `mode_default` (this suite: `deep`, the optional richer mode) on **that same** candidate list, then top-`k`. Product default is `snip` (UI and API/MCP). Published snip preference is the same-pool run at `v1.0.0-snip`. |

Fairness rules:

1. **One discover per query.** Do not call search twice with different modes if that rediscovers.
2. In-process path: `YouComDiscover.search` once → `raw_as_ranked(..., k)` → `cascade_rank(...)` on the same objects.
3. HTTP path (optional): a **single** `POST /v1/search` and read `raw_results` + `results` from that response.
4. **Blind labels.** Each query shuffles A/B. The mapping is stored only in run output (`per_query.jsonl`), never sent to the judge.
5. The judge sees titles, URLs, and snippets only — no scores, flags, or system names.

Suite harness default is `k=10`, `max_candidates=50`, `mode=deep` (optional richer mode; eval treatment). Product default is `mode=snip` (UI and API/MCP). `v1.0.0-first-run` measures **deep**; `v1.0.0-snip` measures **snip**. Both are on [`/eval`](/eval).

## Judge (locked)

| Field | Value |
| --- | --- |
| API | OpenAI **Responses** (`POST /v1/responses`) |
| Model | `gpt-5.6-sol` (alias `gpt-5.6` also routes to Sol; this suite pins the explicit id) |
| Reasoning | `{ "effort": "medium", "mode": "standard" }` |
| Temperature | not set (reasoning-model default) |

Pro mode (`reasoning.mode=pro`) is **off** unless the runner is given an explicit override. Do not change the default pin.

Published prompt: [`judge/PROMPT_v1.md`](./judge/PROMPT_v1.md).  
JSON Schema: [`judge/schema.json`](./judge/schema.json).  
Shape example (not a live verdict): [`judge/example.json`](./judge/example.json).

The judge must output JSON only:

```json
{
  "winner": "A",
  "confidence": 0.72,
  "rationale": "List A leads with the canonical specification; list B opens on a mirror.",
  "a_first_relevant_rank": 1,
  "b_first_relevant_rank": 4
}
```

`winner` is remapped after the call to `baseline` | `agent_seek` | `tie`.

## Queries

[`queries.json`](./queries.json) — **50** items, ids `p1-001` … `p1-050`.

| Tier | Count | Role |
| --- | ---: | --- |
| `L1` | 15 | Easy — clear official docs |
| `L2` | 20 | Medium — fact-in-body / SEO fog / product clarity |
| `L3` | 15 | Hard — entity, republisher, lookalike, source quality |

Each row: `{ "id", "q", "tier", "intent" }`. No Agent Seek / TypeSafe / Jev / personal-brand queries.

## Same-pool replay (`--mode snip`)

Live in-process runs persist the **full** You.com discover list so a later run can re-rank without rediscover:

```bash
# Replay a prior scratch run in snip (product default). Needs TYPESAFE + OPENAI; no YDC.
python scripts/eval_llm_judge.py --replay-run evals/public_v1/results/run_<UTC> --mode snip

# Or a pools.jsonl path
python scripts/eval_llm_judge.py --from-pools path/to/pools.jsonl --mode snip
```

`--replay-run DIR` loads `DIR/pools.jsonl` (fallback: `pool` / `candidates` on `DIR/per_query.jsonl`). Baseline is You.com order top-`k`; treatment is `cascade_rank(..., mode=...)` on those same objects; the judge protocol is unchanged. Replay is in-process only (omit `--http`).

The published `v1.0.0-first-run` predates pool persistence and **cannot** be replayed. Do not invent snip win rates from that table.

## How to run

Keys stay in `.env` (never commit them):

| Variable | Used for |
| --- | --- |
| `YDC_API_KEY` | You.com discover (in-process) |
| `TYPESAFE_API_KEY` | Jev cascade (in-process) |
| `OPENAI_API_KEY` | Judge only — not used by product search |
| `AGENT_SEEK_API_KEY` + `AGENT_SEEK_BASE` | Optional HTTP path (one `/v1/search` per query) |

```bash
# Load suite, print plan, call no APIs
python scripts/eval_llm_judge.py --dry-run

# Two-query smoke (needs the keys above)
python scripts/eval_llm_judge.py --limit 2

# Full 50
python scripts/eval_llm_judge.py

# Same-pool replay — see section above
python scripts/eval_llm_judge.py --replay-run evals/public_v1/results/run_<UTC> --mode snip
```

Missing keys soft-skip (exit 0) unless `AGENT_SEEK_EVAL_STRICT=1`.

## Side-swapped double judge

A single A/B pass does not show whether the judge is following the shortlists or the label. This pass re-judges a **frozen published run**. It does not call You.com or TypeSafe, and it does not re-rank.

For each query the judge sees the same two shortlists twice:

1. **Original order** — list A and list B as in that run's `assignment`.
2. **Swapped order** — those same shortlists with the labels exchanged.

The prompt, model, and schema stay `gpt-5.6-sol`, `reasoning.effort=medium`, `reasoning.mode=standard`, prompt v1. Temperature is not sent (reasoning-model default). No request seed is sent. `run_meta.json` records `temperature: null`, `request_seed: null`, the source run's assignment seed, and `harness_commit`.

Definitions:

| Term | Meaning |
| --- | --- |
| **Agree** | Both passes returned a verdict and the mapped arms are equal. Two ties agree. |
| **Flip** | Both passes returned a verdict and the mapped arms differ. A tie against a side is a flip. A raw A/B change that still maps to the same arm is not a flip. |
| **Flip rate** | Flips / pairs with both verdicts. |
| **Agreeing-only W/T/L** | Only agreeing pairs count. That shared arm is the win, the loss, or the tie. Of-n preference is Agent Seek wins / agreeing pairs, and agreeing ties count as non-wins. Excl.-ties drops those ties. |
| **Incomplete** | Either pass errored. Not a flip, and not in the W/T/L. |

Blind labels stay A and B. The mapping is stored on the new `per_query.jsonl` only.

Published snip and deep rows store **URLs only** (no titles or snippets). The original judge saw titles and snippets. Pass `--pools` with a `pools.jsonl` only to attach that text. Do not rediscover.

```bash
# Plan only. No API key required.
python scripts/eval_llm_judge.py --double-judge --dry-run \
    --from-published evals/public_v1/published/v1.0.0-snip

# Live snip pass (product default). Needs OPENAI_API_KEY. Writes a flat dir.
python scripts/eval_llm_judge.py --double-judge \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out-dir evals/public_v1/published/v1.0.0-snip-double

# Optional deep pass, same harness, separate dir.
python scripts/eval_llm_judge.py --double-judge \
    --from-published evals/public_v1/published/v1.0.0-first-run \
    --out-dir evals/public_v1/published/v1.0.0-deep-double
```

Omitting `--out-dir` uses those same default directories (`results/run_*` is not the double-judge destination). `--limit N` scores the first N published rows. `/eval` shows the snip flip rate when `v1.0.0-snip-double/` exists. This commit does not invent a flip rate.

## Human grading

There is no human agreement number in this commit. The packet is a 30-item stratified sample of the snip published run (22 Agent Seek wins and 8 You.com-order wins in the source table; 0 ties), seed `20260921`, listed by query id. List A and list B follow the published blinding. The form does not name the arms. Titles and snippets are filled from the HTML enrichment artifact when that fetch succeeded. Human picks stay blank until someone grades.

```bash
# Regenerate the packet (does not score anything).
python scripts/eval_human_packet.py sample \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out-dir evals/public_v1/human_v1 \
    --pools evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl
```

Git fills `human` with `A`, `B`, or `tie` (optional `note`) in `packet.md`, `packet.csv`, or `packet.jsonl`. Leave `key.jsonl` and `sample_meta.json` closed while grading. Then:

```bash
python scripts/eval_human_packet.py score \
    --labels evals/public_v1/human_v1/packet.jsonl \
    --from-published evals/public_v1/published/v1.0.0-snip \
    --out evals/public_v1/human_v1/summary.json
```

The score script refuses to write a summary when every pick is blank. `/eval` shows agreement and Cohen's kappa only after `human_v1/summary.json` exists and has at least one label. Details: [`human_v1/README.md`](./human_v1/README.md).

## Eval v1 (locked)

The page brief is [`EVAL_V1_DESIGN.md`](./EVAL_V1_DESIGN.md). Same 50 queries. [`/eval`](/eval) shows snip preference and the published top-3 gold hit rate at equal weight. Snip is the product-default hero; deep stays a small secondary. No competitor products. Top-3 hit rate is the reviewed run at [`published/v1.0.0-snip-top3/`](./published/v1.0.0-snip-top3/) (**43/50**).

| Piece | Path |
| --- | --- |
| Gold key | [`gold_v1/gold_key.jsonl`](./gold_v1/gold_key.jsonl) |
| Snip title/snippet enrichment | [`enriched/v1.0.0-snip-shortlists.jsonl`](./enriched/v1.0.0-snip-shortlists.jsonl) |
| Deep title/snippet enrichment | [`enriched/v1.0.0-deep-shortlists.jsonl`](./enriched/v1.0.0-deep-shortlists.jsonl) |
| Top-3 scorer and published run (43/50) | [`top3/README.md`](./top3/README.md) · [`published/v1.0.0-snip-top3/`](./published/v1.0.0-snip-top3/) |

Enrichment GETs the frozen shortlist URLs. It does not call You.com. The top-3 script's `--dry-run` calls no model. Do not invent a hit rate.

## Output

Each live run writes `evals/public_v1/results/run_<UTC>/`. Those directories are gitignored. This repo does **not** ship a filled `results.json`.

| File | Contents |
| --- | --- |
| `run_meta.json` | Judge pin, prompt sha, `mode`, timings |
| `per_query.jsonl` | Assignment, URLs, verdict, mapped winner, plus `pool` (full discover list) |
| `pools.jsonl` | Sidecar: `{id, q, tier, candidates[]}` for `--from-pools` / `--replay-run` |
| `summary.json` | Wins / ties / losses overall and by tier |

Each `candidates[]` item is snip-complete for cascade replay: `id`, `title`, `url`, `snippet`, `raw_rank`, `provider` (and `body` only if present). HTTP-path runs persist `raw_results` only (API truncates that list); use in-process runs for a full discover pool.

`summary.json` shape after a real run (zeros shown only as a schema — not a measured result):

```json
{
  "suite_id": "agent-seek-public-v1",
  "n": 50,
  "agent_seek_wins": null,
  "baseline_wins": null,
  "ties": null,
  "errors": null,
  "by_tier": {
    "L1": {"n": 15, "agent_seek_wins": null, "baseline_wins": null, "ties": null, "errors": null},
    "L2": {"n": 20, "agent_seek_wins": null, "baseline_wins": null, "ties": null, "errors": null},
    "L3": {"n": 15, "agent_seek_wins": null, "baseline_wins": null, "ties": null, "errors": null}
  }
}
```

Live summaries fill the counts from that run. Do not invent win rates in docs or commits.

## Offline tests

```bash
pytest -q tests/test_eval_public_v1.py
```

No OpenAI / You.com / TypeSafe calls.

## Published runs

Public page: [`/eval`](/eval) · [`/eval.md`](/eval.md). Scratch `results/run_*` stays gitignored.

| Run | Score (AS / tie / baseline) | Judge | Mode |
| --- | --- | --- | --- |
| [v1.0.0-first-run](./published/v1.0.0-first-run/) | 32 / 2 / 16 | gpt-5.6-sol · medium | `deep` (optional richer mode; eval treatment; no frozen pools) |
| [v1.0.0-snip](./published/v1.0.0-snip/) | 37 / 0 / 13 | gpt-5.6-sol · medium | `snip` (product default — UI and API/MCP) |

Top-3 gold check: [v1.0.0-snip-top3](./published/v1.0.0-snip-top3/) — **43/50** hits (errors 0), `kind: top3_gold`, gpt-5.6-sol · medium, `mode=snip`, k=3.

`/eval` loads `published/v1.0.0-first-run/` as deep and snip from `published/v1.0.0-snip/` (or `v1.0.0-snip-first-run` / `snip-first-run`, or any sibling whose `run_meta.mode` is `snip`). A directory whose name ends in `-double`, or whose `run_meta.double_judge` is true, is the side-swap artifact and is not the single-pass leaderboard. Both published single-pass runs are validated preference tables. If the snip directory is absent, the page says snip preference is not validated by the deep table. Top-3 hit rate is loaded only from `published/v1.0.0-snip-top3/` (`summary.json` kind `top3_gold`, **43/50**). First-hit rank counts on the top-3 card come from that directory's `results.jsonl` when the file is present. `top3/results/` is not shown. Do not invent snip win rates or a different top-3 hit rate. Do not invent a flip rate or a kappa; those sections stay empty until their artifacts exist. The page says **not yet run** only when the top-3 directory is missing.
