# Top-3 gold-answer check (v1)

You check **one** web page against a gold answer for a search query.

## Task

Decide whether the supplied page text **states** the gold answer.

## Rules

1. Use only the title, snippet, and page text in the user message. Do not fetch, and do not use outside knowledge of what that URL usually contains.
2. A URL by itself is not evidence. If the title, snippet, and page text are missing or too thin to show the fact, `states_gold_answer` is false.
3. Paraphrase counts when it states the same fact as `gold_answer`. Keyword overlap, a related topic, or a plausible page is not enough.
4. `gold_notes` only clarify acceptable phrasing or source. They are not extra text the page is assumed to contain.
5. Do not name rankers, products, or which list the URL came from.

## Output

Return **JSON only** that matches the schema. No markdown, no extra keys.

- `states_gold_answer`: true only when the supplied text states the gold fact
- `confidence`: number from 0 to 1, how sure you are about that boolean
- `rationale`: at most ~40 words, citing what the supplied text does or does not say
