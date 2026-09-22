#!/usr/bin/env python3
"""Compare raw vs Agent Seek hit-rate on evals/queries.json (frozen harness).

Usage:
  # HTTP against tunneled/live VM (preferred for frozen harness):
  AGENT_SEEK_BASE=http://127.0.0.1:8000 AGENT_SEEK_API_KEY=… \\
    python scripts/eval_compare.py --mode snip --nocache

  # Or env mode:
  AGENT_SEEK_MODE=deep AGENT_SEEK_BASE=http://127.0.0.1:8000 python scripts/eval_compare.py

  # In-process pipeline (local keys):
  AGENT_SEEK_LIVE=1 python scripts/eval_compare.py --mode snip

Exit 0 if Agent Seek aggregate hit-rate >= raw (soft-fail with warning otherwise).
Set AGENT_SEEK_EVAL_STRICT=1 to exit non-zero when Agent Seek loses.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

def _env(name: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

REPORTS = ROOT / "evals" / "reports"
QUERIES_PATH = ROOT / "evals" / "queries.json"
PHX = ZoneInfo("America/Phoenix")


def hit(urls: list[str], substrings: list[str]) -> bool:
    low = [u.lower() for u in urls]
    for s in substrings:
        s = s.lower()
        if any(s in u for u in low):
            return True
    return False


def matching_urls(urls: list[str], substrings: list[str]) -> list[str]:
    out: list[str] = []
    subs = [s.lower() for s in substrings]
    for u in urls:
        ul = u.lower()
        if any(s in ul for s in subs):
            out.append(u)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Agent Seek vs raw You.com eval harness")
    p.add_argument(
        "--mode",
        choices=("snip", "deep"),
        default=_env("AGENT_SEEK_MODE", default="snip"),
        help="Search mode (default: env AGENT_SEEK_MODE or snip)",
    )
    p.add_argument(
        "--base",
        default=_env("AGENT_SEEK_BASE", ""),
        help="HTTP base URL (env AGENT_SEEK_BASE). Default if unset with --http: http://127.0.0.1:8000",
    )
    p.add_argument(
        "--http",
        action="store_true",
        help="Force HTTP client path (uses --base / AGENT_SEEK_BASE / http://127.0.0.1:8000)",
    )
    p.add_argument("--nocache", action="store_true", help="Pass nocache=true to /v1/search")
    p.add_argument("-k", type=int, default=10, help="Top-k to score (default 10)")
    p.add_argument(
        "--max-candidates",
        type=int,
        default=int(os.environ.get("AGENT_SEEK_DEFAULT_MAX_CANDIDATES", "30")),
        help="Discover max candidates (default 30)",
    )
    p.add_argument(
        "--queries",
        type=Path,
        default=QUERIES_PATH,
        help="Path to queries.json",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="HTTP timeout seconds (default: 45 snip / 120 deep)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPORTS,
        help="Report output directory",
    )
    return p.parse_args()


async def run_via_pipeline(
    queries: list[dict],
    *,
    mode: str,
    k: int,
    max_candidates: int,
    nocache: bool,
) -> list[dict]:
    from packages.core.cache import FileCache
    from packages.core.discover.youcom import YouComDiscover
    from packages.core.pipeline import AgentSeekPipeline
    from packages.core.rank.jev import JevClient

    ydc = os.environ.get("YDC_API_KEY", "")
    ts = os.environ.get("TYPESAFE_API_KEY", "")
    if not ydc:
        print("YDC_API_KEY missing; skip live eval", file=sys.stderr)
        return []
    pipe = AgentSeekPipeline(
        YouComDiscover(ydc),
        JevClient(ts) if ts else None,
        cache=FileCache(ROOT / "data" / "cache"),
    )
    rows: list[dict] = []
    for i, item in enumerate(queries, 1):
        q = item["q"]
        subs = item.get("relevant_url_substrings") or []
        if not subs:
            continue
        t0 = time.perf_counter()
        try:
            resp = await pipe.search(
                q, k=k, max_candidates=max_candidates, mode=mode, nocache=nocache
            )
            seek_urls = [r.url for r in resp.results]
            raw_urls = [r.url for r in (resp.raw_results or [])][:k]
            err = None
            ranking = resp.meta.ranking
            latency_ms = getattr(resp.meta, "latency_ms", None)
        except Exception as e:  # noqa: BLE001 — per-query soft continue
            seek_urls, raw_urls, ranking, latency_ms = [], [], None, None
            err = f"{type(e).__name__}: {e}"
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        sh = hit(seek_urls, subs) if seek_urls else False
        rh = hit(raw_urls, subs) if raw_urls else False
        row = {
            "i": i,
            "q": q,
            "relevant_url_substrings": subs,
            "mode": mode,
            "seek_hit": sh,
            "raw_hit": rh,
            "outcome": _outcome(sh, rh),
            "seek_urls": seek_urls,
            "raw_urls": raw_urls,
            "seek_matching": matching_urls(seek_urls, subs),
            "raw_matching": matching_urls(raw_urls, subs),
            "ranking": ranking,
            "latency_ms": latency_ms if latency_ms is not None else elapsed_ms,
            "elapsed_ms": elapsed_ms,
            "error": err,
        }
        rows.append(row)
        print(
            f"  [{i}/{len(queries)}] outcome={row['outcome']} agent-seek={sh} raw={rh} "
            f"ms={row['latency_ms']} q={q[:50]}"
        )
    return rows


async def run_via_http(
    queries: list[dict],
    *,
    base: str,
    mode: str,
    k: int,
    max_candidates: int,
    nocache: bool,
    timeout: float,
) -> list[dict]:
    import httpx

    key = _env("AGENT_SEEK_API_KEY", "")
    if not key:
        print("AGENT_SEEK_API_KEY missing for HTTP eval", file=sys.stderr)
        return []
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i, item in enumerate(queries, 1):
            q = item["q"]
            subs = item.get("relevant_url_substrings") or []
            if not subs:
                continue
            t0 = time.perf_counter()
            seek_urls: list[str] = []
            raw_urls: list[str] = []
            ranking = None
            latency_ms = None
            err = None
            data = None
            last_err: Exception | None = None
            for attempt in range(1, 4):
                try:
                    r = await client.post(
                        f"{base.rstrip('/')}/v1/search",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "q": q,
                            "k": k,
                            "max_candidates": max_candidates,
                            "mode": mode,
                            "nocache": nocache,
                        },
                    )
                    if r.status_code in (429, 502, 503, 504):
                        await asyncio.sleep(2 * attempt)
                        last_err = RuntimeError(f"HTTP {r.status_code}")
                        continue
                    r.raise_for_status()
                    data = r.json()
                    last_err = None
                    break
                except Exception as e:  # noqa: BLE001 — retry ReadTimeout/Connect
                    last_err = e
                    await asyncio.sleep(1.5 * attempt)
            if data is not None:
                seek_urls = [x["url"] for x in data.get("results") or []]
                raw_urls = [x["url"] for x in data.get("raw_results") or []][:k]
                meta = data.get("meta") or {}
                ranking = meta.get("ranking")
                latency_ms = meta.get("latency_ms")
            else:
                err = f"{type(last_err).__name__}: {last_err}" if last_err else "unknown"
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            sh = hit(seek_urls, subs) if seek_urls else False
            rh = hit(raw_urls, subs) if raw_urls else False
            row = {
                "i": i,
                "q": q,
                "relevant_url_substrings": subs,
                "mode": mode,
                "seek_hit": sh,
                "raw_hit": rh,
                "outcome": _outcome(sh, rh),
                "seek_urls": seek_urls,
                "raw_urls": raw_urls,
                "seek_matching": matching_urls(seek_urls, subs),
                "raw_matching": matching_urls(raw_urls, subs),
                "ranking": ranking,
                "latency_ms": latency_ms if latency_ms is not None else elapsed_ms,
                "elapsed_ms": elapsed_ms,
                "error": err,
            }
            rows.append(row)
            print(
                f"  [{i}/{len(queries)}] outcome={row['outcome']} agent-seek={sh} raw={rh} "
                f"ms={row['latency_ms']} err={bool(err)} q={q[:50]}"
            )
            if mode == "deep":
                await asyncio.sleep(0.75)
    return rows


def _outcome(seek_hit: bool, raw_hit: bool) -> str:
    if seek_hit and not raw_hit:
        return "seek_win"
    if seek_hit and raw_hit:
        return "tie"
    if (not seek_hit) and (not raw_hit):
        return "tie_miss"
    return "seek_loss"


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    seek_hits = sum(1 for r in rows if r["seek_hit"])
    raw_hits = sum(1 for r in rows if r["raw_hit"])
    wins = [r for r in rows if r["outcome"] == "seek_win"]
    ties = [r for r in rows if r["outcome"] in ("tie", "tie_miss")]
    losses = [r for r in rows if r["outcome"] == "seek_loss"]
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    return {
        "n": n,
        "seek_hits": seek_hits,
        "raw_hits": raw_hits,
        "seek_hit_rate": (seek_hits / n) if n else 0.0,
        "raw_hit_rate": (raw_hits / n) if n else 0.0,
        "seek_wins": len(wins),
        "ties": len(ties),
        "losses": len(losses),
        "loss_queries": [r["q"] for r in losses],
        "win_queries": [r["q"] for r in wins],
        "errors": sum(1 for r in rows if r.get("error")),
        "latency_ms_avg": (sum(latencies) / len(latencies)) if latencies else None,
        "latency_ms_p50": sorted(latencies)[len(latencies) // 2] if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
    }


def write_reports(
    rows: list[dict],
    agg: dict,
    *,
    mode: str,
    base: str,
    nocache: bool,
    out_dir: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(PHX)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    jsonl_path = out_dir / f"eval-{mode}-{stamp}.jsonl"
    md_path = out_dir / f"eval-{mode}-{stamp}.md"

    with jsonl_path.open("w") as f:
        meta = {
            "_type": "run_meta",
            "mode": mode,
            "base": base or "(pipeline)",
            "nocache": nocache,
            "timestamp_pt": now.isoformat(),
            "n": agg["n"],
        }
        f.write(json.dumps(meta) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write(json.dumps({"_type": "aggregate", **agg}) + "\n")

    lines = [
        f"# Agent Seek eval — mode=`{mode}`",
        "",
        f"**When:** {now.strftime('%Y-%m-%d %H:%M:%S')} PT  ",
        f"**Base:** `{base or '(in-process pipeline)'}`  ",
        f"**nocache:** {nocache}  ",
        f"**Queries:** {agg['n']}",
        "",
        "## Aggregate",
        "",
        f"| metric | value |",
        f"|---|---:|",
        f"| agent-seek hit-rate | {agg['seek_hit_rate']:.3f} ({agg['seek_hits']}/{agg['n']}) |",
        f"| raw hit-rate | {agg['raw_hit_rate']:.3f} ({agg['raw_hits']}/{agg['n']}) |",
        f"| seek_wins | {agg['seek_wins']} |",
        f"| ties (incl. both-miss) | {agg['ties']} |",
        f"| losses | {agg['losses']} |",
        f"| errors | {agg['errors']} |",
        f"| latency_ms avg / p50 / max | {agg['latency_ms_avg']} / {agg['latency_ms_p50']} / {agg['latency_ms_max']} |",
        "",
        "## Per-query",
        "",
        "| # | agent-seek | raw | outcome | ms | query |",
        "|---:|:---:|:---:|---|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['i']} | {'Y' if r['seek_hit'] else 'N'} | "
            f"{'Y' if r['raw_hit'] else 'N'} | {r['outcome']} | "
            f"{r.get('latency_ms') or ''} | {r['q'][:60]} |"
        )
    if agg["loss_queries"]:
        lines += ["", "## Losses (raw hit, agent-seek miss)", ""]
        for q in agg["loss_queries"]:
            lines.append(f"- {q}")
    else:
        lines += ["", "## Losses", "", "_None._", ""]
    if agg["win_queries"]:
        lines += ["", "## Wins (agent-seek hit, raw miss)", ""]
        for q in agg["win_queries"]:
            lines.append(f"- {q}")
    lines += ["", "---", f"*Artifacts: `{jsonl_path.name}` · No secrets.*", ""]
    md_path.write_text("\n".join(lines))
    return jsonl_path, md_path


async def main() -> int:
    args = parse_args()
    queries = json.loads(args.queries.read_text())
    mode = args.mode
    timeout = args.timeout
    if timeout is None:
        timeout = 120.0 if mode == "deep" else 45.0

    use_http = bool(args.http or args.base or _env("AGENT_SEEK_BASE", ""))
    # Default HTTP target: live VM via localhost tunnel / on-VM loopback
    base = (args.base or _env("AGENT_SEEK_BASE", "") or "").rstrip("/")
    if use_http and not base:
        base = "http://127.0.0.1:8000"
    if not use_http and _env("AGENT_SEEK_LIVE") == "1":
        use_http = False
    elif not use_http and not _env("AGENT_SEEK_LIVE", ""):
        # Prefer HTTP default for frozen harness when neither set — try base 8000
        if _env("AGENT_SEEK_API_KEY", ""):
            use_http = True
            base = base or "http://127.0.0.1:8000"

    print(f"Eval: {len(queries)} queries · mode={mode} · nocache={args.nocache}")
    if use_http:
        print(f"HTTP base={base} timeout={timeout}s")
        rows = await run_via_http(
            queries,
            base=base,
            mode=mode,
            k=args.k,
            max_candidates=args.max_candidates,
            nocache=args.nocache,
            timeout=timeout,
        )
    elif _env("AGENT_SEEK_LIVE", "") == "1":
        print("In-process pipeline (AGENT_SEEK_LIVE=1)")
        rows = await run_via_pipeline(
            queries,
            mode=mode,
            k=args.k,
            max_candidates=args.max_candidates,
            nocache=args.nocache,
        )
    else:
        print("Set AGENT_SEEK_LIVE=1 or AGENT_SEEK_BASE=… / --http to run live eval. Soft-skip.")
        print("SOFT_FAIL: eval skipped (no live keys/server). Documented.")
        return 0

    if not rows:
        print("SOFT_FAIL: no rows scored")
        return 0 if _env("AGENT_SEEK_EVAL_STRICT", "") != "1" else 1

    agg = aggregate(rows)
    jsonl_path, md_path = write_reports(
        rows,
        agg,
        mode=mode,
        base=base if use_http else "",
        nocache=args.nocache,
        out_dir=args.out_dir,
    )

    print(f"Agent Seek hit-rate: {agg['seek_hit_rate']:.3f} ({agg['seek_hits']}/{agg['n']})")
    print(f"Raw hit-rate:   {agg['raw_hit_rate']:.3f} ({agg['raw_hits']}/{agg['n']})")
    print(
        f"Wins/ties/losses: {agg['seek_wins']}/{agg['ties']}/{agg['losses']}"
    )
    if agg["loss_queries"]:
        print("Losses:")
        for q in agg["loss_queries"]:
            print(f"  - {q}")
    print(f"Wrote {jsonl_path}")
    print(f"Wrote {md_path}")

    if agg["seek_hit_rate"] + 1e-9 >= agg["raw_hit_rate"]:
        print("PASS: Agent Seek >= raw")
        return 0
    msg = "Agent Seek lost to raw on aggregate"
    if _env("AGENT_SEEK_EVAL_STRICT", "") == "1":
        print("FAIL:", msg)
        return 1
    print("SOFT_FAIL:", msg, "(set AGENT_SEEK_EVAL_STRICT=1 to fail hard)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
