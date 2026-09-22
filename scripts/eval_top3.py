#!/usr/bin/env python3
"""Score whether Agent Seek snip top-3 pages state the locked gold answer.

Does not rediscover and does not call You.com or TypeSafe. A live run calls
OpenAI once per page. CI uses ``--dry-run`` or ``--judgments`` (no API).

  python scripts/eval_top3.py --dry-run
  python scripts/eval_top3.py --limit 2
  python scripts/eval_top3.py --judgments path/to/page_judgments.jsonl --out-dir DIR

A query is a hit when any successfully judged top-3 page has
``states_gold_answer`` true. This script does not invent a suite hit rate:
``--dry-run`` writes nothing, and a missing ``OPENAI_API_KEY`` soft-skips.

``/eval`` reads only ``evals/public_v1/published/v1.0.0-snip-top3/``.
Copy a reviewed run there. ``top3/results/`` is scratch and is not the page.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import eval_enrich_shortlists as enrich
import eval_position as pos

SUITE = ROOT / "evals" / "public_v1"
DEFAULT_GOLD = SUITE / "gold_v1" / "gold_key.jsonl"
DEFAULT_PUBLISHED = SUITE / "published" / "v1.0.0-snip"
DEFAULT_ENRICH = SUITE / "enriched" / "v1.0.0-snip-shortlists.jsonl"
DEFAULT_PROMPT = SUITE / "top3" / "PROMPT_v1.md"
DEFAULT_SCHEMA = SUITE / "top3" / "schema.json"
DEFAULT_OUT = SUITE / "top3" / "results"

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "medium"
DEFAULT_MODE = "standard"
TOP_K = 3
ARM = "agent_seek"
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)
TEXT_CAP = 6_000


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


class PageVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    states_gold_answer: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=280)


PageVerdict.model_rebuild()


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def schema_for_api(schema: dict[str, Any]) -> dict[str, Any]:
    skip = {"$schema", "$id", "title", "description"}
    return {k: v for k, v in schema.items() if k not in skip}


def load_prompt(path: Path = DEFAULT_PROMPT) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def load_schema(path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a JSON object")
    return loaded


def treatment_top(row: dict[str, Any], k: int = TOP_K) -> list[str]:
    values = row.get("treatment_urls")
    if not isinstance(values, list):
        values = row.get("treatment") or []
    urls: list[str] = []
    for item in values:
        url = ""
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        if url:
            urls.append(url)
        if len(urls) >= k:
            break
    return urls


def evidence_kind(title: str, snippet: str, text: str) -> str:
    if text.strip():
        return "page_text"
    if title.strip() or snippet.strip():
        return "title_snippet"
    return "url_only"


def index_enrich(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    """``(query id, url) -> {title, snippet}`` from an enrichment JSONL."""
    index: dict[tuple[str, str], dict[str, str]] = {}
    if path is None or not path.is_file():
        return index
    for rec in pos.load_jsonl(path):
        qid = str(rec.get("id") or "")
        candidates = rec.get("candidates") or []
        if not qid or not isinstance(candidates, list):
            continue
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            url = str(cand.get("url") or "").strip()
            if not url:
                continue
            index[(qid, url)] = {
                "title": str(cand.get("title") or ""),
                "snippet": str(cand.get("snippet") or ""),
            }
    return index


def index_page_text(path: Path | None) -> dict[tuple[str, str], str]:
    """Optional ``{id, url, text}`` JSONL. Does not fetch."""
    index: dict[tuple[str, str], str] = {}
    if path is None:
        return index
    for rec in pos.load_jsonl(path):
        qid = str(rec.get("id") or "")
        url = str(rec.get("url") or "").strip()
        text = str(rec.get("text") or "")
        if qid and url and text.strip():
            index[(qid, url)] = text
    return index


def index_gold(path: Path) -> dict[str, dict[str, Any]]:
    rows = pos.load_jsonl(path)
    return {str(row.get("id") or ""): row for row in rows if row.get("id")}


def build_cases(
    gold: dict[str, dict[str, Any]],
    published_rows: list[dict[str, Any]],
    enrich_index: dict[tuple[str, str], dict[str, str]],
    page_text: dict[tuple[str, str], str],
    *,
    k: int = TOP_K,
) -> list[dict[str, Any]]:
    """One case per published query that has a gold row. Order follows published."""
    cases: list[dict[str, Any]] = []
    for row in published_rows:
        qid = str(row.get("id") or "")
        gold_row = gold.get(qid)
        pages: list[dict[str, Any]] = []
        if gold_row is not None and gold_row.get("locked") is not False:
            for rank, url in enumerate(treatment_top(row, k), 1):
                extra = enrich_index.get((qid, url)) or {}
                title = str(extra.get("title") or "")
                snippet = str(extra.get("snippet") or "")
                text = page_text.get((qid, url)) or ""
                if len(text) > TEXT_CAP:
                    text = text[:TEXT_CAP].rsplit(" ", 1)[0] + "…"
                pages.append(
                    {
                        "rank": rank,
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "text": text,
                        "evidence": evidence_kind(title, snippet, text),
                    }
                )
        cases.append(
            {
                "id": qid,
                "q": (gold_row or row).get("q") or row.get("q") or "",
                "tier": row.get("tier") or (gold_row or {}).get("tier"),
                "gold_answer": (gold_row or {}).get("gold_answer") or "",
                "gold_notes": (gold_row or {}).get("gold_notes") or "",
                "locked": None if gold_row is None else gold_row.get("locked"),
                "missing_gold": gold_row is None,
                "unlocked": bool(gold_row) and gold_row.get("locked") is False,
                "pages": pages,
            }
        )
    return cases


def build_user_message(case: dict[str, Any], page: dict[str, Any]) -> str:
    text = page.get("text") or ""
    body = text if text else "(not provided)"
    notes = case.get("gold_notes") or "(none)"
    return (
        f"Query: {case.get('q') or ''}\n"
        f"Gold answer: {case.get('gold_answer') or ''}\n"
        f"Gold notes: {notes}\n"
        f"Rank: {page.get('rank')}\n"
        f"URL: {page.get('url') or ''}\n"
        f"Title: {page.get('title') or ''}\n"
        f"Snippet: {page.get('snippet') or ''}\n"
        f"Page text:\n{body}\n"
    )


def build_request(
    *,
    model: str,
    reasoning_effort: str,
    reasoning_mode: str,
    prompt: str,
    user_message: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """OpenAI Responses body. No temperature (reasoning-model default)."""
    return {
        "model": model,
        "reasoning": {"effort": reasoning_effort, "mode": reasoning_mode},
        "input": [
            {"role": "developer", "content": prompt.strip()},
            {"role": "user", "content": user_message},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "top3_page_verdict",
                "strict": True,
                "schema": schema_for_api(schema),
            }
        },
    }


def extract_output_text(payload: dict[str, Any]) -> str:
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and part.get("text"):
                chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()


def parse_verdict(text: str) -> PageVerdict:
    cleaned = FENCE_RE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"top-3 output is not JSON: {exc}") from exc
    try:
        return PageVerdict.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"top-3 output does not match schema: {exc}") from exc


def load_judgments(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in pos.load_jsonl(path):
        qid = str(rec.get("id") or "")
        url = str(rec.get("url") or "").strip()
        if not qid or not url:
            continue
        index[(qid, url)] = rec
    return index


def apply_judgment(page: dict[str, Any], judgment: dict[str, Any] | None) -> dict[str, Any]:
    base = {
        "rank": page["rank"],
        "url": page["url"],
        "evidence": page["evidence"],
        "title": page.get("title") or "",
        "snippet": page.get("snippet") or "",
        "text_chars": len(page.get("text") or ""),
        "states_gold_answer": None,
        "confidence": None,
        "rationale": None,
        "error": None,
    }
    if judgment is None:
        base["error"] = "no judgment"
        return base
    if judgment.get("error"):
        base["error"] = str(judgment["error"])[:300]
        return base
    try:
        verdict = PageVerdict.model_validate(
            {
                "states_gold_answer": judgment.get("states_gold_answer"),
                "confidence": judgment.get("confidence"),
                "rationale": judgment.get("rationale"),
            }
        )
    except ValidationError as exc:
        base["error"] = f"invalid judgment: {exc}"[:300]
        return base
    base["states_gold_answer"] = verdict.states_gold_answer
    base["confidence"] = verdict.confidence
    base["rationale"] = verdict.rationale
    return base


def outcome_for_case(case: dict[str, Any], judged_pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit if any judged page states the gold answer. All-error is not a miss."""
    if case.get("missing_gold"):
        return _row(case, judged_pages, hit=None, error="missing gold key")
    if case.get("unlocked"):
        return _row(case, judged_pages, hit=None, error="gold row is not locked")
    if not judged_pages:
        return _row(case, judged_pages, hit=None, error="no top-3 URLs")
    successes = [p for p in judged_pages if p.get("error") is None and p.get("states_gold_answer") is not None]
    if not successes:
        return _row(case, judged_pages, hit=None, error="all page judgments failed")
    hits = [p for p in successes if p.get("states_gold_answer") is True]
    if hits:
        first = min(int(p["rank"]) for p in hits)
        return _row(case, judged_pages, hit=True, first_hit_rank=first, error=None)
    return _row(case, judged_pages, hit=False, first_hit_rank=None, error=None)


def _row(
    case: dict[str, Any],
    pages: list[dict[str, Any]],
    *,
    hit: bool | None,
    error: str | None,
    first_hit_rank: int | None = None,
) -> dict[str, Any]:
    return {
        "id": case.get("id"),
        "tier": case.get("tier"),
        "q": case.get("q") or "",
        "gold_answer": case.get("gold_answer") or "",
        "arm": ARM,
        "k": TOP_K,
        "hit": hit,
        "first_hit_rank": first_hit_rank,
        "error": error,
        "pages": pages,
    }


def score_cases(
    cases: list[dict[str, Any]],
    judgments: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        judged = [
            apply_judgment(page, judgments.get((str(case["id"]), page["url"])))
            for page in case["pages"]
        ]
        rows.append(outcome_for_case(case, judged))
    return rows


def _tier_bucket() -> dict[str, int]:
    return {"n": 0, "scored": 0, "hits": 0, "misses": 0, "errors": 0}


def summarize(rows: list[dict[str, Any]], *, suite_id: str, mode: str) -> dict[str, Any]:
    by_tier = {"L1": _tier_bucket(), "L2": _tier_bucket(), "L3": _tier_bucket()}
    hits = misses = errors = 0
    page_judged = page_states = page_errors = 0
    evidence = {"page_text": 0, "title_snippet": 0, "url_only": 0}
    for row in rows:
        tier = row.get("tier") if row.get("tier") in by_tier else None
        buckets = [by_tier[tier]] if tier else []
        for bucket in buckets:
            bucket["n"] += 1
        if row.get("error") or row.get("hit") is None:
            errors += 1
            for bucket in buckets:
                bucket["errors"] += 1
        elif row.get("hit") is True:
            hits += 1
            for bucket in buckets:
                bucket["scored"] += 1
                bucket["hits"] += 1
        else:
            misses += 1
            for bucket in buckets:
                bucket["scored"] += 1
                bucket["misses"] += 1
        for page in row.get("pages") or []:
            kind = page.get("evidence")
            if kind in evidence:
                evidence[kind] += 1
            if page.get("error"):
                page_errors += 1
            else:
                page_judged += 1
                if page.get("states_gold_answer") is True:
                    page_states += 1
    scored = hits + misses
    return {
        "kind": "top3_gold",
        "suite_id": suite_id,
        "arm": ARM,
        "mode": mode,
        "k": TOP_K,
        "n": len(rows),
        "scored": scored,
        "hits": hits,
        "misses": misses,
        "errors": errors,
        "hit_rate": (hits / scored) if scored else None,
        "hit_rate_basis": "hits / scored; scored excludes queries whose page judgments all failed",
        "pages_judged": page_judged,
        "pages_states_gold": page_states,
        "pages_errors": page_errors,
        "evidence_pages": evidence,
        "by_tier": by_tier,
        "live": False,
    }


def evidence_totals(cases: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"page_text": 0, "title_snippet": 0, "url_only": 0, "pages": 0, "queries": len(cases)}
    for case in cases:
        for page in case["pages"]:
            totals["pages"] += 1
            kind = page["evidence"]
            if kind in totals:
                totals[kind] += 1
    return totals


def plan_text(
    *,
    cases: list[dict[str, Any]],
    model: str,
    reasoning_effort: str,
    reasoning_mode: str,
    prompt_sha: str,
    published: Path,
    gold: Path,
    enrich_path: Path | None,
    page_text: Path | None,
    dry_run: bool,
) -> str:
    totals = evidence_totals(cases)
    lines = [
        "Top-3 gold check",
        f"Queries: {len(cases)}",
        f"Pages: {totals['pages']}  (Agent Seek snip treatment, k={TOP_K})",
        f"Evidence pages: title_snippet={totals['title_snippet']}  "
        f"page_text={totals['page_text']}  url_only={totals['url_only']}",
        f"Gold: {enrich.rel(gold)}",
        f"Published: {enrich.rel(published)}",
        f"Enrich: {enrich.rel(enrich_path) if enrich_path else 'none'}",
        f"Page text: {enrich.rel(page_text) if page_text else 'none'}",
        (
            f"Judge: model={model}  api=responses  "
            f"reasoning.effort={reasoning_effort}  reasoning.mode={reasoning_mode}"
        ),
        f"Prompt sha256={prompt_sha[:12]}…",
        "Rediscover: no. You.com: no.",
        "Hit: any successfully judged top-3 page states gold_answer.",
    ]
    if dry_run:
        lines += ["", "DRY-RUN: no APIs called. No hit rate written."]
    return "\n".join(lines)


def write_run(
    dest: Path,
    *,
    run_meta: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2) + "\n", encoding="utf-8"
    )
    with (dest / "results.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (dest / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


async def call_model(request: dict[str, Any], *, api_key: str, timeout: float) -> dict[str, Any]:
    import httpx

    url = _env("OPENAI_BASE_URL", default=OPENAI_RESPONSES_URL)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI HTTP {response.status_code}: {response.text[:400]}")
        return response.json()


async def judge_pages_live(
    cases: list[dict[str, Any]],
    *,
    prompt: str,
    schema: dict[str, Any],
    model: str,
    reasoning_effort: str,
    reasoning_mode: str,
    api_key: str,
    timeout: float,
    sleep_s: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        judged: list[dict[str, Any]] = []
        for page in case["pages"]:
            request = build_request(
                model=model,
                reasoning_effort=reasoning_effort,
                reasoning_mode=reasoning_mode,
                prompt=prompt,
                user_message=build_user_message(case, page),
                schema=schema,
            )
            try:
                payload = await call_model(request, api_key=api_key, timeout=timeout)
                verdict = parse_verdict(extract_output_text(payload))
                judged.append(
                    apply_judgment(
                        page,
                        {
                            "states_gold_answer": verdict.states_gold_answer,
                            "confidence": verdict.confidence,
                            "rationale": verdict.rationale,
                        },
                    )
                )
            except Exception as exc:
                judged.append(apply_judgment(page, {"error": f"{type(exc).__name__}: {exc}"}))
            if sleep_s:
                await asyncio.sleep(sleep_s)
        rows.append(outcome_for_case(case, judged))
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--from-published", type=Path, default=DEFAULT_PUBLISHED)
    parser.add_argument(
        "--enrich",
        type=Path,
        default=None,
        help="Enrichment JSONL (title/snippet). Default: snip shortlists if that file exists.",
    )
    parser.add_argument(
        "--page-text",
        type=Path,
        default=None,
        help="Optional JSONL of {id, url, text}. Does not fetch.",
    )
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_EFFORT)
    parser.add_argument("--reasoning-mode", default=DEFAULT_MODE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds between live page calls")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan. Call no APIs. Write nothing.")
    parser.add_argument(
        "--judgments",
        type=Path,
        default=None,
        help="Offline page judgments JSONL. Writes a summary without calling the model.",
    )
    return parser.parse_args(argv)


def resolve_enrich(args: argparse.Namespace) -> Path | None:
    if args.enrich is not None:
        return args.enrich
    if DEFAULT_ENRICH.is_file() and args.from_published == DEFAULT_PUBLISHED:
        return DEFAULT_ENRICH
    return None


def prepare(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    prompt, prompt_sha = load_prompt(args.prompt)
    schema = load_schema(args.schema)
    gold = index_gold(args.gold)
    published_rows, run_meta = pos.load_published_dir(args.from_published)
    if args.limit is not None:
        published_rows = published_rows[: args.limit]
    enrich_path = resolve_enrich(args)
    cases = build_cases(
        gold,
        published_rows,
        index_enrich(enrich_path),
        index_page_text(args.page_text),
    )
    mode = run_meta.get("mode") if isinstance(run_meta.get("mode"), str) else "snip"
    return cases, prompt_sha, {
        "prompt": prompt,
        "prompt_sha": prompt_sha,
        "schema": schema,
        "mode": mode,
        "enrich_path": enrich_path,
        "suite_id": "agent-seek-public-v1",
    }


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases, _sha, ctx = prepare(args)
    text = plan_text(
        cases=cases,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        reasoning_mode=args.reasoning_mode,
        prompt_sha=ctx["prompt_sha"],
        published=args.from_published,
        gold=args.gold,
        enrich_path=ctx["enrich_path"],
        page_text=args.page_text,
        dry_run=args.dry_run,
    )
    print(text)
    if args.dry_run:
        return 0
    if args.judgments is not None:
        rows = score_cases(cases, load_judgments(args.judgments))
        summary = summarize(rows, suite_id=ctx["suite_id"], mode=ctx["mode"])
        summary["source"] = "judgments_file"
        dest = args.out_dir or (DEFAULT_OUT / f"run_{utc_stamp()}")
        write_run(
            dest,
            run_meta=_run_meta(args, ctx, live=False, source="judgments_file"),
            rows=rows,
            summary=summary,
        )
        _print_summary(summary, dest)
        return 0
    if not _env("OPENAI_API_KEY"):
        print(
            "SOFT_FAIL: missing OPENAI_API_KEY — top-3 scorer skipped (no invented scores).",
            file=sys.stderr,
        )
        return 0 if _env("AGENT_SEEK_EVAL_STRICT") != "1" else 1
    started = time.perf_counter()
    rows = await judge_pages_live(
        cases,
        prompt=ctx["prompt"],
        schema=ctx["schema"],
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        reasoning_mode=args.reasoning_mode,
        api_key=_env("OPENAI_API_KEY"),
        timeout=args.timeout,
        sleep_s=max(0.0, args.sleep),
    )
    summary = summarize(rows, suite_id=ctx["suite_id"], mode=ctx["mode"])
    summary["live"] = True
    summary["elapsed_s"] = round(time.perf_counter() - started, 3)
    dest = args.out_dir or (DEFAULT_OUT / f"run_{utc_stamp()}")
    write_run(
        dest,
        run_meta=_run_meta(args, ctx, live=True, source="openai"),
        rows=rows,
        summary=summary,
    )
    _print_summary(summary, dest)
    return 0


def _run_meta(
    args: argparse.Namespace,
    ctx: dict[str, Any],
    *,
    live: bool,
    source: str,
) -> dict[str, Any]:
    return {
        "kind": "top3_gold",
        "suite_id": ctx["suite_id"],
        "arm": ARM,
        "mode": ctx["mode"],
        "k": TOP_K,
        "source": source,
        "live": live,
        "gold": enrich.rel(args.gold),
        "published": enrich.rel(args.from_published),
        "enrich": enrich.rel(ctx["enrich_path"]) if ctx["enrich_path"] else None,
        "page_text": enrich.rel(args.page_text) if args.page_text else None,
        "rediscover": False,
        "youcom": False,
        "temperature": None,
        "finished_at": iso_now(),
        "judge": {
            "model": args.model,
            "api": "responses",
            "reasoning_effort": args.reasoning_effort,
            "reasoning_mode": args.reasoning_mode,
            "temperature": None,
            "prompt": enrich.rel(args.prompt),
            "prompt_sha256": ctx["prompt_sha"],
            "schema": enrich.rel(args.schema),
        },
    }


def _print_summary(summary: dict[str, Any], dest: Path) -> None:
    rate = summary.get("hit_rate")
    rate_s = "undefined" if rate is None else f"{rate:.3f}"
    print(
        f"Wrote {dest}  hits={summary['hits']}/{summary['scored']}  "
        f"hit_rate={rate_s}  errors={summary['errors']}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
