# Published top-3 gold check — snip v1.0.0

Reviewed live run against locked `gold_key.jsonl` on published snip treatment top-3 URLs.

| | |
| --- | --- |
| Hits | **43 / 50** (86%) |
| Errors | 0 |
| Evidence | page_text 147, title_snippet 1, url_only 0 |
| Judge | gpt-5.6-sol, Responses, reasoning.effort=medium |
| Finished | 2026-09-21T23:13:36Z |

`/eval` reads `hits / scored` from `summary.json` (`kind: top3_gold`). First-hit rank counts on that card come from `results.jsonl` when the file is present.
