#!/usr/bin/env python3
"""Blind pairwise LLM-judge: You.com order vs Agent Seek cascade.

Same discover pool per query. Judge never sees system names or A/B mapping.

Usage:
  python scripts/eval_llm_judge.py --help
  python scripts/eval_llm_judge.py --dry-run
  python scripts/eval_llm_judge.py --limit 2
  python scripts/eval_llm_judge.py
  python scripts/eval_llm_judge.py --replay-run DIR --mode snip
  python scripts/eval_llm_judge.py --from-pools PATH --mode snip
  python scripts/eval_llm_judge.py --double-judge \\
      --from-published evals/public_v1/published/v1.0.0-snip --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

SUITE_DIR = ROOT / "evals" / "public_v1"
DEFAULT_QUERIES = SUITE_DIR / "queries.json"
DEFAULT_META = SUITE_DIR / "meta.json"
DEFAULT_PROMPT = SUITE_DIR / "judge" / "PROMPT_v1.md"
DEFAULT_SCHEMA = SUITE_DIR / "judge" / "schema.json"
DEFAULT_OUT = SUITE_DIR / "results"

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_JUDGE_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_REASONING_MODE = "standard"
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


class JudgeVerdict(BaseModel):
    """Published judge response (evals/public_v1/judge/schema.json)."""

    model_config = ConfigDict(extra="forbid")

    winner: Literal["A", "B", "tie"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=280)
    a_first_relevant_rank: int | None = Field(default=None, ge=1)
    b_first_relevant_rank: int | None = Field(default=None, ge=1)


class ListItem(BaseModel):
    rank: int
    url: str
    title: str = ""
    snippet: str = ""


# importlib-loaded scripts leave postponed annotations unresolved for Pydantic.
JudgeVerdict.model_rebuild()
ListItem.model_rebuild()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_suite(
    *,
    queries_path: Path = DEFAULT_QUERIES,
    meta_path: Path = DEFAULT_META,
    prompt_path: Path = DEFAULT_PROMPT,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    queries = load_json(queries_path)
    meta = load_json(meta_path)
    schema = load_json(schema_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    if not isinstance(queries, list):
        raise ValueError(f"{queries_path} must be a JSON array")
    return {
        "queries": queries,
        "meta": meta,
        "schema": schema,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "queries_path": queries_path,
        "meta_path": meta_path,
        "prompt_path": prompt_path,
        "schema_path": schema_path,
    }


def schema_for_api(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop JSON Schema metadata OpenAI structured outputs does not want."""
    skip = {"$schema", "$id", "title", "description"}
    return {k: v for k, v in schema.items() if k not in skip}


def validate_verdict(data: Any, schema: dict[str, Any] | None = None) -> JudgeVerdict:
    """Validate judge JSON via pydantic (and required-key check against schema)."""
    if not isinstance(data, dict):
        raise ValueError("judge output must be a JSON object")
    if schema:
        required = schema.get("required") or []
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"judge output missing {missing}")
    return JudgeVerdict.model_validate(data)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Blind pairwise LLM-judge: You.com order vs Agent Seek cascade "
            "on the same discover pool (evals/public_v1)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/eval_llm_judge.py --dry-run\n"
            "  python scripts/eval_llm_judge.py --limit 2\n"
            "  python scripts/eval_llm_judge.py\n"
            "  python scripts/eval_llm_judge.py --replay-run "
            "evals/public_v1/results/run_<UTC> --mode snip\n"
            "  python scripts/eval_llm_judge.py --from-pools path/to/pools.jsonl "
            "--mode snip\n"
            "  python scripts/eval_llm_judge.py --double-judge --dry-run \\\n"
            "      --from-published evals/public_v1/published/v1.0.0-snip\n"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Load suite and print the plan; call no APIs",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Score only the first N queries (smoke)",
    )
    p.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    p.add_argument("--meta", type=Path, default=DEFAULT_META)
    p.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--k",
        type=int,
        default=None,
        help="Top-k (default: meta.k)",
    )
    p.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Discover cap (default: meta.max_candidates)",
    )
    p.add_argument(
        "--mode",
        choices=("deep", "snip"),
        default=None,
        help="Cascade mode (default: meta.mode_default)",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"Judge model (default: {DEFAULT_JUDGE_MODEL})",
    )
    p.add_argument(
        "--reasoning-effort",
        default=None,
        help=f"Responses reasoning.effort (default: {DEFAULT_REASONING_EFFORT})",
    )
    p.add_argument(
        "--reasoning-mode",
        choices=("standard", "pro"),
        default=None,
        help=(
            "Responses reasoning.mode (default: standard). "
            "pro is opt-in only — do not use unless you intend the override."
        ),
    )
    p.add_argument("--seed", type=int, default=0, help="A/B assignment seed")
    p.add_argument("--nocache", action="store_true", help="Bypass discover cache")
    p.add_argument(
        "--http",
        action="store_true",
        help="Use one POST /v1/search per query (same-pool raw_results + results)",
    )
    p.add_argument(
        "--base",
        default=_env("AGENT_SEEK_BASE", ""),
        help="HTTP base URL (env AGENT_SEEK_BASE)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="HTTP timeout seconds (default: 120 deep / 60 snip)",
    )
    p.add_argument(
        "--judge-timeout",
        type=float,
        default=120.0,
        help="OpenAI Responses timeout seconds (default: 120)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Pause between queries in seconds (default: 0.25)",
    )
    p.add_argument(
        "--from-pools",
        type=Path,
        default=None,
        help=(
            "Replay a frozen pools.jsonl (full discover list per query). "
            "Skips You.com rediscover. Pass --mode snip to re-rank the same pool."
        ),
    )
    p.add_argument(
        "--replay-run",
        type=Path,
        default=None,
        help=(
            "Replay DIR/pools.jsonl (or pool fields on DIR/per_query.jsonl). "
            "Same as --from-pools DIR/pools.jsonl."
        ),
    )
    p.add_argument(
        "--double-judge",
        action="store_true",
        help=(
            "Judge each published shortlist twice (original A/B, then swapped). "
            "Does not rediscover or re-rank. Requires --from-published."
        ),
    )
    p.add_argument(
        "--from-published",
        type=Path,
        default=None,
        help=(
            "Published run directory (per_query.jsonl + run_meta.json). "
            "With --double-judge, those frozen A/B shortlists are the only inputs."
        ),
    )
    p.add_argument(
        "--pools",
        type=Path,
        default=None,
        help=(
            "Optional pools.jsonl used only to attach title/snippet onto "
            "published URLs. Does not rediscover or change order."
        ),
    )
    return p.parse_args(argv)


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def assign_labels(
    query_id: str,
    *,
    seed: int,
) -> dict[str, str]:
    """Return {A,B} → baseline|agent_seek. Mapping is run-output only."""
    rng = random.Random(f"{seed}:{query_id}")
    if rng.random() < 0.5:
        return {"A": "baseline", "B": "agent_seek"}
    return {"A": "agent_seek", "B": "baseline"}


def map_winner(winner: str, assignment: dict[str, str]) -> str:
    if winner == "tie":
        return "tie"
    if winner not in assignment:
        raise ValueError(f"unknown winner {winner!r}")
    return assignment[winner]


POOL_FIELDS = ("id", "title", "url", "snippet", "raw_rank", "provider")


def serialize_pool_item(c: Any) -> dict[str, Any]:
    """Persist one discover candidate (snip-complete fields for cascade replay)."""
    if hasattr(c, "model_dump") and not isinstance(c, dict):
        data = c.model_dump()
    elif isinstance(c, dict):
        data = c
    else:
        data = {
            "id": getattr(c, "id", ""),
            "title": getattr(c, "title", ""),
            "url": getattr(c, "url", ""),
            "snippet": getattr(c, "snippet", ""),
            "raw_rank": getattr(c, "raw_rank", 0),
            "provider": getattr(c, "provider", "you.com"),
            "body": getattr(c, "body", ""),
        }
    item: dict[str, Any] = {
        "id": str(data.get("id") or ""),
        "title": str(data.get("title") or ""),
        "url": str(data.get("url") or ""),
        "snippet": str(data.get("snippet") or ""),
        "raw_rank": int(data.get("raw_rank") or 0),
        "provider": str(data.get("provider") or "you.com"),
    }
    body = data.get("body") or ""
    if body:
        item["body"] = str(body)
    return item


def pool_from_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    return [serialize_pool_item(c) for c in candidates]


def pool_from_ranked(rows: list[Any]) -> list[dict[str, Any]]:
    """Best-effort pool from HTTP raw_results (may be truncated vs full discover)."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if isinstance(row, dict):
            raw = dict(row)
            raw.setdefault("id", f"c{i}")
            raw.setdefault("raw_rank", i + 1)
            out.append(serialize_pool_item(raw))
            continue
        raw_rank = int(getattr(row, "raw_rank", i + 1) or i + 1)
        out.append(
            serialize_pool_item(
                {
                    "id": str(getattr(row, "id", "") or f"c{i}"),
                    "title": str(getattr(row, "title", "") or ""),
                    "url": str(getattr(row, "url", "") or ""),
                    "snippet": str(getattr(row, "snippet", "") or ""),
                    "raw_rank": raw_rank,
                    "provider": str(getattr(row, "provider", "") or "you.com"),
                    "body": str(getattr(row, "body", "") or ""),
                }
            )
        )
    return out


def candidates_from_pool(items: list[Any]) -> list[Any]:
    """Rebuild Candidate objects from a frozen pool record."""
    from packages.core.models import Candidate

    out: list[Any] = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        try:
            raw_rank = int(item.get("raw_rank") or 0)
        except (TypeError, ValueError):
            raw_rank = 0
        if raw_rank < 1:
            raw_rank = i + 1
        out.append(
            Candidate(
                id=str(item.get("id") or f"c{i}"),
                url=url,
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
                body=str(item.get("body") or ""),
                raw_rank=raw_rank,
                provider=str(item.get("provider") or "you.com"),
            )
        )
    return out


def load_pools_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """Load pools.jsonl → {query_id: record}."""
    recs: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if not isinstance(rec, dict):
            continue
        qid = str(rec.get("id") or "")
        if not qid:
            continue
        recs[qid] = rec
    return recs


def pools_from_run_dir(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load frozen candidates from a prior run (sidecar first, then per_query)."""
    sidecar = run_dir / "pools.jsonl"
    if sidecar.is_file():
        recs = load_pools_jsonl(sidecar)
        out = {
            qid: list(rec.get("candidates") or [])
            for qid, rec in recs.items()
            if rec.get("candidates")
        }
        if out:
            return out
    per_query = run_dir / "per_query.jsonl"
    if per_query.is_file():
        out: dict[str, list[dict[str, Any]]] = {}
        for line in per_query.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            qid = str(rec.get("id") or "")
            pool = rec.get("pool") or rec.get("candidates")
            if qid and isinstance(pool, list) and pool:
                out[qid] = pool
        if out:
            return out
    raise FileNotFoundError(
        f"{run_dir} has no frozen discover pools "
        "(expected pools.jsonl or per_query pool/candidates). "
        "The published v1.0.0-first-run predates pool persistence."
    )


def resolve_replay_pools(args: argparse.Namespace) -> dict[str, list[dict[str, Any]]] | None:
    if args.from_pools and args.replay_run:
        raise ValueError("use --from-pools or --replay-run, not both")
    if args.from_pools:
        recs = load_pools_jsonl(args.from_pools)
        return {
            qid: list(rec.get("candidates") or [])
            for qid, rec in recs.items()
            if rec.get("candidates")
        }
    if args.replay_run:
        return pools_from_run_dir(args.replay_run)
    return None


def items_from_ranked(rows: list[Any], k: int) -> list[ListItem]:
    out: list[ListItem] = []
    for i, row in enumerate(rows[:k], 1):
        if isinstance(row, dict):
            out.append(
                ListItem(
                    rank=int(row.get("rank") or i),
                    url=str(row.get("url") or ""),
                    title=str(row.get("title") or ""),
                    snippet=str(row.get("snippet") or ""),
                )
            )
            continue
        out.append(
            ListItem(
                rank=int(getattr(row, "rank", i)),
                url=str(getattr(row, "url", "")),
                title=str(getattr(row, "title", "")),
                snippet=str(getattr(row, "snippet", "")),
            )
        )
    return [it for it in out if it.url]


def format_list(label: str, items: list[ListItem]) -> str:
    if not items:
        return f"List {label}:\n(empty)"
    lines = [f"List {label}:"]
    for it in items:
        snippet = " ".join((it.snippet or "").split())[:240]
        lines.append(f"{it.rank}. {it.title or it.url}")
        lines.append(f"   {it.url}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def build_judge_user_message(query: str, a: list[ListItem], b: list[ListItem]) -> str:
    return (
        f"Query: {query}\n\n"
        f"{format_list('A', a)}\n\n"
        f"{format_list('B', b)}\n"
    )


def build_judge_request(
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
        "reasoning": {
            "effort": reasoning_effort,
            "mode": reasoning_mode,
        },
        "input": [
            {"role": "developer", "content": prompt.strip()},
            {"role": "user", "content": user_message},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "judge_verdict",
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
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("output_text", "text") and part.get("text"):
                chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()


def parse_judge_json(text: str, schema: dict[str, Any]) -> JudgeVerdict:
    cleaned = FENCE_RE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"judge output is not JSON: {e}") from e
    return validate_verdict(data, schema)


def empty_tier_counts() -> dict[str, int]:
    return {
        "n": 0,
        "agent_seek_wins": 0,
        "baseline_wins": 0,
        "ties": 0,
        "errors": 0,
    }


def summarize(rows: list[dict[str, Any]], *, suite_id: str) -> dict[str, Any]:
    by_tier = {"L1": empty_tier_counts(), "L2": empty_tier_counts(), "L3": empty_tier_counts()}
    totals = empty_tier_counts()
    for row in rows:
        tier = row.get("tier") if row.get("tier") in by_tier else None
        buckets = [totals] + ([by_tier[tier]] if tier else [])
        for b in buckets:
            b["n"] += 1
        if row.get("error"):
            for b in buckets:
                b["errors"] += 1
            continue
        mapped = row.get("mapped_winner")
        key = {
            "agent_seek": "agent_seek_wins",
            "baseline": "baseline_wins",
            "tie": "ties",
        }.get(mapped)
        if key:
            for b in buckets:
                b[key] += 1
    judged = totals["n"] - totals["errors"]
    return {
        "suite_id": suite_id,
        "n": totals["n"],
        "agent_seek_wins": totals["agent_seek_wins"],
        "baseline_wins": totals["baseline_wins"],
        "ties": totals["ties"],
        "errors": totals["errors"],
        "judged": judged,
        "by_tier": by_tier,
    }


def plan_text(
    *,
    suite: dict[str, Any],
    queries: list[dict[str, Any]],
    k: int,
    max_candidates: int,
    mode: str,
    model: str,
    reasoning_effort: str,
    reasoning_mode: str,
    dry_run: bool,
    path: str,
    replay: str | None = None,
) -> str:
    meta = suite["meta"]
    lines = [
        f"Suite: {meta.get('suite_id')} v{meta.get('version')}",
        f"Queries: {len(queries)} / {len(suite['queries'])} loaded",
        f"k={k}  max_candidates={max_candidates}  mode={mode}",
        f"Baseline: {meta.get('baseline')}   Treatment: {meta.get('treatment')}",
        (
            f"Judge: model={model}  api=responses  "
            f"reasoning.effort={reasoning_effort}  reasoning.mode={reasoning_mode}"
        ),
        f"Prompt: {suite['prompt_path'].name}  sha256={suite['prompt_sha256'][:12]}…",
        f"Path: {path}",
        "Fairness: discover once per query; both sides share that pool.",
        "Blinding: random A/B per query; mapping stored in run output only.",
    ]
    if replay:
        lines.append(f"Replay: frozen pools from {replay} (no You.com rediscover).")
    else:
        lines.append("Pools: full discover list written to pools.jsonl for later --from-pools replay.")
    lines += [
        "",
        "Queries:",
    ]
    for item in queries:
        lines.append(f"  {item.get('id')}  [{item.get('tier')}]  {item.get('q')}")
    if dry_run:
        lines += ["", "DRY-RUN: suite loaded; no APIs called."]
    return "\n".join(lines)


def pools_sidecar_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sidecar: list[dict[str, Any]] = []
    for row in rows:
        pool = row.get("pool")
        if not pool:
            continue
        sidecar.append(
            {
                "id": row.get("id"),
                "q": row.get("q"),
                "tier": row.get("tier"),
                "candidates": pool,
            }
        )
    return sidecar


def write_run(
    *,
    out_dir: Path,
    run_meta: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    pools: list[dict[str, Any]] | None = None,
) -> Path:
    stamp = run_meta.get("run_id") or utc_stamp()
    dest = out_dir / f"run_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2) + "\n", encoding="utf-8"
    )
    with (dest / "per_query.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (dest / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    sidecar = pools if pools is not None else pools_sidecar_from_rows(rows)
    if sidecar:
        with (dest / "pools.jsonl").open("w", encoding="utf-8") as f:
            for rec in sidecar:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return dest


async def discover_pair_inprocess(
    query: str,
    *,
    k: int,
    max_candidates: int,
    mode: str,
    nocache: bool,
) -> dict[str, Any]:
    """Discover once, then You.com-order top-k vs cascade on the same list."""
    from packages.core.cache import FileCache
    from packages.core.discover.youcom import YouComDiscover
    from packages.core.rank.cascade import cascade_rank, raw_as_ranked
    from packages.core.rank.jev import JevClient

    ydc = _env("YDC_API_KEY")
    ts = _env("TYPESAFE_API_KEY")
    if not ydc:
        raise RuntimeError("YDC_API_KEY missing")
    if not ts:
        raise RuntimeError("TYPESAFE_API_KEY missing")

    discover = YouComDiscover(ydc)
    jev = JevClient(ts)
    cache = FileCache(ROOT / "data" / "cache")
    cache_key = None
    candidates = None
    cache_hit = False
    discover_ms = 0

    if not nocache:
        q_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        cache_key = f"discover:{q_hash}:{max_candidates}:you.com"
        cached = cache.get(cache_key)
        if cached is not None:
            from packages.core.models import Candidate

            candidates = [Candidate.model_validate(c) for c in cached]
            cache_hit = True

    if candidates is None:
        t0 = time.perf_counter()
        candidates = await discover.search(query, max_candidates)
        discover_ms = int((time.perf_counter() - t0) * 1000)
        if cache_key:
            cache.set(cache_key, [c.model_dump() for c in candidates])

    baseline = items_from_ranked(raw_as_ranked(candidates, k), k)
    t1 = time.perf_counter()
    ranked, ranking, extras = await cascade_rank(
        jev, query, candidates, k=k, mode=mode
    )
    rank_ms = int((time.perf_counter() - t1) * 1000)
    treatment = items_from_ranked(ranked, k)
    return {
        "candidates_in": len(candidates),
        "baseline": baseline,
        "treatment": treatment,
        "pool": pool_from_candidates(candidates),
        "ranking": ranking,
        "discover_ms": discover_ms,
        "rank_ms": rank_ms,
        "fetch_ms": (extras or {}).get("fetch_ms"),
        "cache_hit": cache_hit,
    }


async def rank_pair_from_pool(
    query: str,
    pool: list[dict[str, Any]],
    *,
    k: int,
    mode: str,
) -> dict[str, Any]:
    """Same-pool replay: You.com order top-k vs cascade on frozen candidates."""
    from packages.core.rank.cascade import cascade_rank, raw_as_ranked
    from packages.core.rank.jev import JevClient

    ts = _env("TYPESAFE_API_KEY")
    if not ts:
        raise RuntimeError("TYPESAFE_API_KEY missing")
    candidates = candidates_from_pool(pool)
    if not candidates:
        raise RuntimeError("frozen pool is empty or missing urls")
    jev = JevClient(ts)
    baseline = items_from_ranked(raw_as_ranked(candidates, k), k)
    t1 = time.perf_counter()
    ranked, ranking, extras = await cascade_rank(
        jev, query, candidates, k=k, mode=mode
    )
    rank_ms = int((time.perf_counter() - t1) * 1000)
    treatment = items_from_ranked(ranked, k)
    return {
        "candidates_in": len(candidates),
        "baseline": baseline,
        "treatment": treatment,
        "pool": pool_from_candidates(candidates),
        "ranking": ranking,
        "discover_ms": 0,
        "rank_ms": rank_ms,
        "fetch_ms": (extras or {}).get("fetch_ms"),
        "cache_hit": True,
        "replay": True,
    }


async def discover_pair_http(
    query: str,
    *,
    base: str,
    k: int,
    max_candidates: int,
    mode: str,
    nocache: bool,
    timeout: float,
) -> dict[str, Any]:
    """One /v1/search — raw_results is the same discover pool as results."""
    import httpx

    key = _env("AGENT_SEEK_API_KEY")
    if not key:
        raise RuntimeError("AGENT_SEEK_API_KEY missing for HTTP path")
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{base.rstrip('/')}/v1/search",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "q": query,
                "k": k,
                "max_candidates": max_candidates,
                "mode": mode,
                "nocache": nocache,
            },
        )
        r.raise_for_status()
        data = r.json()
    meta = data.get("meta") or {}
    raw_rows = data.get("raw_results") or []
    return {
        "candidates_in": meta.get("candidates_in"),
        "baseline": items_from_ranked(raw_rows, k),
        "treatment": items_from_ranked(data.get("results") or [], k),
        "pool": pool_from_ranked(raw_rows),
        "ranking": meta.get("ranking"),
        "discover_ms": meta.get("discover_ms"),
        "rank_ms": meta.get("rank_ms"),
        "fetch_ms": meta.get("fetch_ms"),
        "cache_hit": meta.get("cache_hit"),
    }


async def call_judge(
    request: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    import httpx

    url = _env("OPENAI_BASE_URL", default=OPENAI_RESPONSES_URL)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:400]}")
        return r.json()


def resolve_settings(
    args: argparse.Namespace, meta: dict[str, Any]
) -> dict[str, Any]:
    judge = meta.get("judge") or {}
    use_http = bool(args.http or args.base)
    base = (args.base or "").rstrip("/")
    if use_http and not base:
        base = "http://127.0.0.1:8787"
    mode = args.mode or meta.get("mode_default") or "deep"
    timeout = args.timeout
    if timeout is None:
        timeout = 120.0 if mode == "deep" else 60.0
    return {
        "k": args.k if args.k is not None else int(meta.get("k") or 10),
        "max_candidates": (
            args.max_candidates
            if args.max_candidates is not None
            else int(meta.get("max_candidates") or 50)
        ),
        "mode": mode,
        "model": args.model or judge.get("model") or DEFAULT_JUDGE_MODEL,
        "reasoning_effort": (
            args.reasoning_effort
            or judge.get("reasoning_effort")
            or DEFAULT_REASONING_EFFORT
        ),
        "reasoning_mode": (
            args.reasoning_mode
            or judge.get("reasoning_mode")
            or DEFAULT_REASONING_MODE
        ),
        "use_http": use_http,
        "base": base,
        "timeout": timeout,
        "path": f"http:{base}" if use_http else "in_process",
        "replaying": bool(args.from_pools or args.replay_run),
    }


def missing_keys(settings: dict[str, Any]) -> list[str]:
    need: list[str] = []
    if not _env("OPENAI_API_KEY"):
        need.append("OPENAI_API_KEY")
    if settings.get("replaying"):
        if not _env("TYPESAFE_API_KEY"):
            need.append("TYPESAFE_API_KEY")
        return need
    if settings["use_http"]:
        if not _env("AGENT_SEEK_API_KEY"):
            need.append("AGENT_SEEK_API_KEY")
    else:
        if not _env("YDC_API_KEY"):
            need.append("YDC_API_KEY")
        if not _env("TYPESAFE_API_KEY"):
            need.append("TYPESAFE_API_KEY")
    return need


def row_payload(item: dict[str, Any], **extra: Any) -> dict[str, Any]:
    row = {
        "id": item.get("id"),
        "q": item.get("q"),
        "tier": item.get("tier"),
        "intent": item.get("intent"),
        "candidates_in": None,
        "baseline_urls": [],
        "treatment_urls": [],
        "pool": None,
        "assignment": None,
        "judge": None,
        "mapped_winner": None,
        "ranking": None,
        "discover_ms": None,
        "rank_ms": None,
        "judge_ms": None,
        "error": None,
    }
    row.update(extra)
    return row


async def run_query(
    item: dict[str, Any],
    *,
    settings: dict[str, Any],
    suite: dict[str, Any],
    args: argparse.Namespace,
    replay_pools: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    q = item["q"]
    k = settings["k"]
    t0 = time.perf_counter()
    try:
        if replay_pools is not None:
            qid = str(item.get("id") or "")
            frozen = replay_pools.get(qid)
            if not frozen:
                return row_payload(
                    item,
                    error="replay:no_pool",
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                )
            pair = await rank_pair_from_pool(
                q, frozen, k=k, mode=settings["mode"]
            )
        elif settings["use_http"]:
            pair = await discover_pair_http(
                q,
                base=settings["base"],
                k=k,
                max_candidates=settings["max_candidates"],
                mode=settings["mode"],
                nocache=args.nocache,
                timeout=settings["timeout"],
            )
        else:
            pair = await discover_pair_inprocess(
                q,
                k=k,
                max_candidates=settings["max_candidates"],
                mode=settings["mode"],
                nocache=args.nocache,
            )
    except Exception as e:  # noqa: BLE001 — per-query soft continue
        return row_payload(
            item,
            error=f"discover:{type(e).__name__}: {e}",
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )

    assignment = assign_labels(str(item.get("id") or q), seed=args.seed)
    sides = {
        "baseline": pair["baseline"],
        "agent_seek": pair["treatment"],
    }
    list_a = sides[assignment["A"]]
    list_b = sides[assignment["B"]]
    request = build_judge_request(
        model=settings["model"],
        reasoning_effort=settings["reasoning_effort"],
        reasoning_mode=settings["reasoning_mode"],
        prompt=suite["prompt"],
        user_message=build_judge_user_message(q, list_a, list_b),
        schema=suite["schema"],
    )
    tj = time.perf_counter()
    try:
        raw = await call_judge(
            request,
            api_key=_env("OPENAI_API_KEY"),
            timeout=args.judge_timeout,
        )
        verdict = parse_judge_json(extract_output_text(raw), suite["schema"])
        mapped = map_winner(verdict.winner, assignment)
        judge_ms = int((time.perf_counter() - tj) * 1000)
        return row_payload(
            item,
            candidates_in=pair.get("candidates_in"),
            baseline_urls=[it.url for it in pair["baseline"]],
            treatment_urls=[it.url for it in pair["treatment"]],
            pool=pair.get("pool"),
            assignment=assignment,
            judge=verdict.model_dump(),
            mapped_winner=mapped,
            ranking=pair.get("ranking"),
            discover_ms=pair.get("discover_ms"),
            rank_ms=pair.get("rank_ms"),
            fetch_ms=pair.get("fetch_ms"),
            cache_hit=pair.get("cache_hit"),
            judge_ms=judge_ms,
            judge_id=raw.get("id"),
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )
    except (ValidationError, Exception) as e:  # noqa: BLE001
        return row_payload(
            item,
            candidates_in=pair.get("candidates_in"),
            baseline_urls=[it.url for it in pair["baseline"]],
            treatment_urls=[it.url for it in pair["treatment"]],
            pool=pair.get("pool"),
            assignment=assignment,
            ranking=pair.get("ranking"),
            discover_ms=pair.get("discover_ms"),
            rank_ms=pair.get("rank_ms"),
            fetch_ms=pair.get("fetch_ms"),
            cache_hit=pair.get("cache_hit"),
            judge_ms=int((time.perf_counter() - tj) * 1000),
            error=f"judge:{type(e).__name__}: {e}",
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )


def _eval_position():
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import eval_position

    return eval_position


def default_double_out(mode: str) -> Path:
    """Flat published dir. Snip is the product default; deep is separate."""
    if mode == "snip":
        name = "v1.0.0-snip-double"
    elif mode == "deep":
        name = "v1.0.0-deep-double"
    else:
        name = f"v1.0.0-{mode}-double"
    return SUITE_DIR / "published" / name


def double_plan_text(
    *,
    n_source: int,
    n: int,
    mode: str,
    model: str,
    reasoning_effort: str,
    reasoning_mode: str,
    prompt_sha: str,
    text_kind: str,
    out_dir: Path,
    source: Path,
    dry_run: bool,
) -> str:
    lines = [
        "Double judge: original A/B order, then the same shortlists with sides swapped.",
        f"Source: {source}  ({n_source} published rows, scoring {n})",
        f"Mode: {mode}  (from the published run; shortlists are not re-ranked)",
        (
            f"Judge: model={model}  api=responses  "
            f"reasoning.effort={reasoning_effort}  reasoning.mode={reasoning_mode}"
        ),
        "Temperature: not sent (reasoning-model default). Request seed: not sent.",
        f"Prompt sha256={prompt_sha[:12]}…",
        f"Judge calls: {n * 2} (2 per query).",
        "Blinding: lists stay labeled A and B. Arm names are not in the prompt.",
        "Flip: mapped arm changed after the swap (tie vs a side counts).",
        "Preference W/T/L: agreeing pairs only. Incomplete pairs are excluded.",
        f"Shortlists: {text_kind}.",
        "Rediscover: no. You.com and TypeSafe are not called.",
        f"Output: {out_dir}",
    ]
    if text_kind == "url_only":
        lines.append(
            "NOTE: published rows have URLs and no titles or snippets. "
            "The original judge saw titles and snippets. Pass --pools to attach "
            "them without rediscovering."
        )
    if dry_run:
        lines += ["", "DRY-RUN: suite loaded; no APIs called."]
    return "\n".join(lines)


def double_readme(summary: dict[str, Any], run_meta: dict[str, Any]) -> str:
    flips = summary.get("flips")
    both = summary.get("both_verdicts")
    rate = summary.get("flip_rate")
    rate_s = "n/a" if rate is None else f"{100.0 * rate:.1f}% ({flips}/{both})"
    return "\n".join(
        [
            "# Side-swapped double judge",
            "",
            "Same shortlists as the source published run. Second pass flips A and B.",
            "The judge still sees only those labels.",
            "",
            f"Mode: `{run_meta.get('mode')}`",
            f"Flip rate: {rate_s}",
            (
                "Agreeing W/T/L (Agent Seek / tie / You.com order): "
                f"{summary.get('agent_seek_wins')} / {summary.get('ties')} / "
                f"{summary.get('baseline_wins')} "
                f"(agreeing n={summary.get('agreeing')})"
            ),
            "",
            "Flip rate = pairs whose mapped arm changed, divided by pairs with both verdicts.",
            "Agreeing ties count as ties. A tie against a win is a flip and is left out of the W/T/L.",
            "A pass that errors is incomplete: not a flip, and not in the W/T/L.",
            "",
            "Temperature was not sent. Assignment seed is the source run's A/B seed; it is not an API seed.",
            f"Harness commit: `{run_meta.get('harness_commit')}`",
            "",
        ]
    )


def _items_as_lists(items: list[dict[str, Any]]) -> list[ListItem]:
    out: list[ListItem] = []
    for i, it in enumerate(items, 1):
        out.append(
            ListItem(
                rank=int(it.get("rank") or i),
                url=str(it.get("url") or ""),
                title=str(it.get("title") or ""),
                snippet=str(it.get("snippet") or ""),
            )
        )
    return [it for it in out if it.url]


async def _judge_presentation(
    *,
    query: str,
    items_a: list[dict[str, Any]],
    items_b: list[dict[str, Any]],
    assignment: dict[str, str],
    settings: dict[str, Any],
    suite: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """One blind pass. Returns verdict, mapped arm, and error. No arm names in the prompt."""
    request = build_judge_request(
        model=settings["model"],
        reasoning_effort=settings["reasoning_effort"],
        reasoning_mode=settings["reasoning_mode"],
        prompt=suite["prompt"],
        user_message=build_judge_user_message(
            query, _items_as_lists(items_a), _items_as_lists(items_b)
        ),
        schema=suite["schema"],
    )
    # Temperature and seed are intentionally absent. This suite pins the
    # reasoning model default and records that fact on run_meta.
    if "temperature" in request or "seed" in request:
        raise RuntimeError("double judge must not send temperature or seed")
    try:
        raw = await call_judge(
            request,
            api_key=_env("OPENAI_API_KEY"),
            timeout=timeout,
        )
        verdict = parse_judge_json(extract_output_text(raw), suite["schema"])
        mapped = map_winner(verdict.winner, assignment)
        return {
            "judge": verdict.model_dump(),
            "mapped": mapped,
            "error": None,
            "judge_id": raw.get("id"),
        }
    except (ValidationError, Exception) as e:  # noqa: BLE001 — per-pass soft continue
        return {
            "judge": None,
            "mapped": None,
            "error": f"judge:{type(e).__name__}: {e}",
            "judge_id": None,
        }


def write_double_run(
    *,
    out_dir: Path,
    run_meta: dict[str, Any],
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Path:
    """Flat artifact dir (summary, run_meta, per_query, README). No run_<UTC> nest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_meta.json").write_text(
        json.dumps(run_meta, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "per_query.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "README.md").write_text(
        double_readme(summary, run_meta), encoding="utf-8"
    )
    return out_dir


async def run_double_judge(args: argparse.Namespace, suite: dict[str, Any]) -> int:
    """Side-swapped re-judge of a frozen published run. No You.com rediscovery."""
    pos = _eval_position()
    if not args.from_published:
        print("--double-judge requires --from-published PATH", file=sys.stderr)
        return 2
    if args.replay_run or args.from_pools:
        print(
            "--double-judge does not rediscover or re-rank. "
            "Omit --replay-run and --from-pools. Use --pools only to attach titles.",
            file=sys.stderr,
        )
        return 2
    if args.http:
        print("--double-judge does not call /v1/search; omit --http", file=sys.stderr)
        return 2
    try:
        source_rows, source_meta = pos.load_published_dir(args.from_published)
    except (OSError, json.JSONDecodeError, FileNotFoundError, ValueError) as e:
        print(f"published run: {e}", file=sys.stderr)
        return 2
    pool_index = None
    if args.pools:
        try:
            pool_index = pos.load_pool_index(args.pools)
        except (OSError, json.JSONDecodeError) as e:
            print(f"pools: {e}", file=sys.stderr)
            return 2
    mode = str(source_meta.get("mode") or "snip")
    if args.mode and args.mode != mode:
        print(
            f"note: --mode {args.mode} ignored; published run mode is {mode}",
            file=sys.stderr,
        )
    settings = resolve_settings(args, suite["meta"])
    settings["mode"] = mode
    prepared: list[dict[str, Any]] = []
    for row in source_rows:
        try:
            prepared.append(pos.prepare_query(row, pool_index=pool_index))
        except ValueError as e:
            print(f"shortlist: {e}", file=sys.stderr)
            return 2
    n_source = len(prepared)
    if args.limit is not None:
        if args.limit < 1:
            print("--limit must be >= 1", file=sys.stderr)
            return 2
        prepared = prepared[: args.limit]
    out_dir = Path(args.out_dir)
    if out_dir.resolve() == DEFAULT_OUT.resolve():
        out_dir = default_double_out(mode)
    kinds = {item["shortlist_text"] for item in prepared}
    text_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    print(
        double_plan_text(
            n_source=n_source,
            n=len(prepared),
            mode=mode,
            model=settings["model"],
            reasoning_effort=settings["reasoning_effort"],
            reasoning_mode=settings["reasoning_mode"],
            prompt_sha=suite["prompt_sha256"],
            text_kind=text_kind or "url_only",
            out_dir=out_dir,
            source=args.from_published,
            dry_run=args.dry_run,
        )
    )
    if args.dry_run:
        return 0
    if not _env("OPENAI_API_KEY"):
        print(
            "SOFT_FAIL: missing OPENAI_API_KEY — double judge skipped "
            "(no invented scores).",
            file=sys.stderr,
        )
        return 0 if _env("AGENT_SEEK_EVAL_STRICT") != "1" else 1

    started = iso_now()
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    n = len(prepared)
    for i, item in enumerate(prepared, 1):
        original = await _judge_presentation(
            query=item["q"],
            items_a=item["original"]["A"],
            items_b=item["original"]["B"],
            assignment=item["original"]["assignment"],
            settings=settings,
            suite=suite,
            timeout=args.judge_timeout,
        )
        if args.sleep:
            await asyncio.sleep(args.sleep)
        swapped = await _judge_presentation(
            query=item["q"],
            items_a=item["swapped"]["A"],
            items_b=item["swapped"]["B"],
            assignment=item["swapped"]["assignment"],
            settings=settings,
            suite=suite,
            timeout=args.judge_timeout,
        )
        outcome = pos.classify_pair(original["mapped"], swapped["mapped"])
        published_mapped = item.get("published_mapped_winner")
        match = None
        if original["mapped"] in pos.MAPPED and published_mapped in pos.MAPPED:
            match = original["mapped"] == published_mapped
        rows.append(
            {
                "id": item["id"],
                "q": item["q"],
                "tier": item["tier"],
                "intent": item["intent"],
                "shortlist_text": item["shortlist_text"],
                "assignment_original": item["original"]["assignment"],
                "assignment_swapped": item["swapped"]["assignment"],
                "baseline_urls": [it["url"] for it in item["baseline"]],
                "treatment_urls": [it["url"] for it in item["treatment"]],
                "judge_original": original["judge"],
                "judge_swapped": swapped["judge"],
                "mapped_original": original["mapped"],
                "mapped_swapped": swapped["mapped"],
                "agree": outcome["agree"],
                "flip": outcome["flip"],
                "published_winner": item.get("published_winner"),
                "published_mapped_winner": published_mapped,
                "original_matches_published": match,
                "error_original": original["error"],
                "error_swapped": swapped["error"],
                "judge_id_original": original["judge_id"],
                "judge_id_swapped": swapped["judge_id"],
            }
        )
        print(
            f"  [{i}/{n}] {item['id']}  agree={outcome['agree']}  "
            f"flip={outcome['flip']}  "
            f"orig={original['mapped']}  swap={swapped['mapped']}"
        )
        if args.sleep and i < n:
            await asyncio.sleep(args.sleep)

    summary = pos.summarize_double(
        rows,
        suite_id=str(suite["meta"].get("suite_id")),
        mode=mode,
    )
    summary["source_published"] = str(args.from_published)
    summary["shortlist_text"] = text_kind
    comparable = [
        r
        for r in rows
        if r.get("original_matches_published") is not None
    ]
    summary["original_matches_published"] = sum(
        1 for r in comparable if r["original_matches_published"]
    )
    summary["original_comparable"] = len(comparable)
    sha = git_sha()
    source_prompt = source_meta.get("prompt_sha256")
    run_meta = {
        "run_id": utc_stamp(),
        "suite_id": suite["meta"].get("suite_id"),
        "suite_version": suite["meta"].get("suite_version")
        or suite["meta"].get("version"),
        "started_at": started,
        "finished_at": iso_now(),
        "git_sha": sha,
        "harness_commit": sha,
        "double_judge": True,
        "kind": "double_judge",
        "prompt_version": (suite["meta"].get("judge") or {}).get("prompt_version"),
        "prompt_sha256": suite["prompt_sha256"],
        "source_prompt_sha256": source_prompt,
        "prompt_sha_matches_source": bool(
            source_prompt and source_prompt == suite["prompt_sha256"]
        ),
        "judge": {
            "model": settings["model"],
            "reasoning_effort": settings["reasoning_effort"],
            "reasoning_mode": settings["reasoning_mode"],
            "api": "responses",
            "temperature": None,
            "request_seed": None,
        },
        "assignment_seed": source_meta.get("seed"),
        "seed": source_meta.get("seed"),
        "k": source_meta.get("k"),
        "max_candidates": source_meta.get("max_candidates"),
        "mode": mode,
        "limit": args.limit,
        "source_published": str(args.from_published),
        "source_run_id": source_meta.get("run_id"),
        "pools": str(args.pools) if args.pools else None,
        "shortlist_text": text_kind,
        "rediscover": False,
        "path": "double_judge",
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "n": len(rows),
        "definitions": pos.DEFINITIONS,
    }
    dest = write_double_run(
        out_dir=out_dir,
        run_meta=run_meta,
        rows=rows,
        summary=summary,
    )
    rate = summary["flip_rate"]
    rate_s = "n/a" if rate is None else f"{100.0 * rate:.1f}%"
    print(
        "Agreeing W/T/L (agent_seek / tie / baseline): "
        f"{summary['agent_seek_wins']}/{summary['ties']}/{summary['baseline_wins']}  "
        f"agreeing={summary['agreeing']}  flips={summary['flips']}  "
        f"flip_rate={rate_s}  errors={summary['errors']}"
    )
    print(f"Wrote {dest}")
    return 0


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.double_judge:
        suite = load_suite(
            queries_path=args.queries,
            meta_path=args.meta,
            prompt_path=args.prompt,
            schema_path=args.schema,
        )
        return await run_double_judge(args, suite)
    suite = load_suite(
        queries_path=args.queries,
        meta_path=args.meta,
        prompt_path=args.prompt,
        schema_path=args.schema,
    )
    settings = resolve_settings(args, suite["meta"])
    queries = list(suite["queries"])
    if args.limit is not None:
        if args.limit < 1:
            print("--limit must be >= 1", file=sys.stderr)
            return 2
        queries = queries[: args.limit]
    if args.from_pools and args.replay_run:
        print("use --from-pools or --replay-run, not both", file=sys.stderr)
        return 2
    if settings["replaying"] and settings["use_http"]:
        print("replay is in-process only; omit --http / --base", file=sys.stderr)
        return 2

    replay_pools: dict[str, list[dict[str, Any]]] | None = None
    replay_label: str | None = None
    if settings["replaying"]:
        try:
            replay_pools = resolve_replay_pools(args)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            if args.dry_run:
                print(f"Replay pools not loaded ({e}).", file=sys.stderr)
            else:
                print(f"replay failed: {e}", file=sys.stderr)
                return 2
        replay_label = str(args.from_pools or args.replay_run)
        if replay_pools is not None:
            settings["path"] = f"replay:{replay_label}"

    print(
        plan_text(
            suite=suite,
            queries=queries,
            k=settings["k"],
            max_candidates=settings["max_candidates"],
            mode=settings["mode"],
            model=settings["model"],
            reasoning_effort=settings["reasoning_effort"],
            reasoning_mode=settings["reasoning_mode"],
            dry_run=args.dry_run,
            path=settings["path"],
            replay=replay_label,
        )
    )
    if args.dry_run:
        return 0

    missing = missing_keys(settings)
    if missing:
        print(
            "SOFT_FAIL: missing "
            + ", ".join(missing)
            + " — judge eval skipped (documented; no invented scores).",
            file=sys.stderr,
        )
        return 0 if _env("AGENT_SEEK_EVAL_STRICT") != "1" else 1

    started = iso_now()
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    n = len(queries)
    for i, item in enumerate(queries, 1):
        row = await run_query(
            item,
            settings=settings,
            suite=suite,
            args=args,
            replay_pools=replay_pools,
        )
        rows.append(row)
        mapped = row.get("mapped_winner") or "error"
        print(
            f"  [{i}/{n}] {item.get('id')}  mapped={mapped}  "
            f"err={bool(row.get('error'))}  ms={row.get('elapsed_ms')}"
        )
        if args.sleep and i < n:
            await asyncio.sleep(args.sleep)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    run_id = utc_stamp()
    run_meta = {
        "run_id": run_id,
        "suite_id": suite["meta"].get("suite_id"),
        "suite_version": suite["meta"].get("suite_version")
        or suite["meta"].get("version"),
        "started_at": started,
        "finished_at": iso_now(),
        "git_sha": git_sha(),
        "prompt_version": (suite["meta"].get("judge") or {}).get("prompt_version"),
        "prompt_sha256": suite["prompt_sha256"],
        "judge": {
            "model": settings["model"],
            "reasoning_effort": settings["reasoning_effort"],
            "reasoning_mode": settings["reasoning_mode"],
            "api": "responses",
        },
        "k": settings["k"],
        "max_candidates": settings["max_candidates"],
        "mode": settings["mode"],
        "limit": args.limit,
        "seed": args.seed,
        "path": settings["path"],
        "nocache": args.nocache,
        "elapsed_ms": elapsed_ms,
        "n": len(rows),
        "replay": (
            {
                "from_pools": str(args.from_pools) if args.from_pools else None,
                "replay_run": str(args.replay_run) if args.replay_run else None,
                "rediscover": False,
            }
            if settings["replaying"]
            else None
        ),
    }
    summary = summarize(rows, suite_id=str(suite["meta"].get("suite_id")))
    dest = write_run(
        out_dir=args.out_dir,
        run_meta=run_meta,
        rows=rows,
        summary=summary,
    )
    print(
        "Wins/ties/losses (agent_seek / tie / baseline): "
        f"{summary['agent_seek_wins']}/{summary['ties']}/{summary['baseline_wins']}  "
        f"errors={summary['errors']}"
    )
    print(f"Wrote {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
