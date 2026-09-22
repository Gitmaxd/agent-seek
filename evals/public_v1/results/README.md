# Run output

Harness writes each live run to `run_<UTC timestamp>/`:

- `run_meta.json` — model pin, prompt hash, git SHA, timings
- `per_query.jsonl` — blinded assignment, URLs, judge verdict, mapped winner, `pool`
- `pools.jsonl` — full discover list per query for `--from-pools` / `--replay-run`
- `summary.json` — wins / ties / losses overall and by tier

`run_*` directories are gitignored. Do not commit raw runs. Promote an approved summary later if the project decides to publish scores.

This directory ships empty on purpose: there is no `results.json` and no invented win rate.
