"""Static /eval page — numbers come only from published public_v1 runs.

``/eval`` opens with what the questions tested, then snip preference and
top-3 hit rate. Wilson intervals, the judge model, and artifact paths sit in
a collapsed "How we measured" section. Former ``/eval/v0`` URLs redirect
here. Top-3 hit rate is read only from
``evals/public_v1/published/v1.0.0-snip-top3/``. First-hit rank counts come
from that directory's ``results.jsonl`` when the file is present. Scratch
``top3/results/`` is not a page source.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from apps.api.agent_ready import markdown_response, origin_from, page_html, prefers_markdown
from apps.api.proportion import (
    ProportionStat,
    format_p_value,
    format_rate_detail,
    format_wilson_ci,
    proportion_stat,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_ROOT_REL = "evals/public_v1/published"
PUBLISHED_ROOT = ROOT / PUBLISHED_ROOT_REL
DEEP_REL = f"{PUBLISHED_ROOT_REL}/v1.0.0-first-run"
DEEP_DIR = ROOT / DEEP_REL
# Preferred snip path; also accept siblings whose run_meta.mode is snip.
SNIP_CANDIDATE_RELS = (
    f"{PUBLISHED_ROOT_REL}/v1.0.0-snip",
    f"{PUBLISHED_ROOT_REL}/v1.0.0-snip-first-run",
    f"{PUBLISHED_ROOT_REL}/snip-first-run",
)
SUITE_README = ROOT / "evals" / "public_v1" / "README.md"
JUDGE_PROMPT = ROOT / "evals" / "public_v1" / "judge" / "PROMPT_v1.md"
HUMAN_SUMMARY_REL = "evals/public_v1/human_v1/summary.json"
HUMAN_SUMMARY = ROOT / HUMAN_SUMMARY_REL
# Snip is the product default and the first double-judge arm.
SNIP_DOUBLE_NAMES = ("v1.0.0-snip-double",)
DEEP_DOUBLE_NAMES = ("v1.0.0-deep-double", "v1.0.0-first-run-double")
# Reviewed top-3 run only. ``top3/results/run_*`` stays gitignored scratch.
TOP3_PUBLISHED_NAME = "v1.0.0-snip-top3"
TOP3_REL = f"{PUBLISHED_ROOT_REL}/{TOP3_PUBLISHED_NAME}"
TOP3_DIR = ROOT / TOP3_REL

# Backward-compatible aliases used by tests and older links.
PUBLISHED_REL = DEEP_REL
PUBLISHED_DIR = DEEP_DIR

WINNER_LABEL = {
    "agent_seek": "Agent Seek",
    "baseline": "You.com order",
    "tie": "Tie",
}

PUBLISHED_FILE_TYPES = {
    "summary.json": "application/json",
    "run_meta.json": "application/json",
    "per_query.jsonl": "application/x-ndjson",
    "results.jsonl": "application/x-ndjson",
    "pools.jsonl": "application/x-ndjson",
    "README.md": "text/markdown; charset=utf-8",
}


def pct1(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def pct_int(num: int, den: int) -> int:
    return int(round(100.0 * num / den)) if den else 0


# Of n: wins / judged queries, ties count as non-wins.
# Excl. ties: wins / decided pairs (ties dropped). Same Wilson + exact test
# on whichever denominator the rate uses. Published runs have 0 errors, so
# judged queries == n.
WIN_RATE_NOTE = (
    "Of n, a win rate is that side's wins divided by judged queries, and ties "
    "count as non-wins. Excl. ties drops ties and uses decided pairs only. "
    "When a run has no ties, those two rates match. Each win rate shows a "
    "Wilson 95% CI and a two-sided exact binomial p-value for H0: p=0.5."
)
# Coverage metadata, not a tier findings table. Cells at ~15–20 queries
# are too small to publish as preference rates.
SUITE_BALANCE_NOTE = (
    "The frozen query set is balanced across an L1–L3 difficulty mix for coverage. "
    "Tier-level win rates are not published because those cells are underpowered "
    "at the current n (~15–20 per tier)."
)
JUDGE_CERTAINTY_NOTE = (
    "Judge certainty is the judge's self-reported certainty on that "
    "comparison, not a statistical interval."
)
JUDGE_CERTAINTY_NOTE_DUAL = (
    "Judge certainty is listed as deep / snip. "
    + JUDGE_CERTAINTY_NOTE
)
# Separate from the single-pass leaderboard. Agreeing ties count as non-wins
# in the of-n rate. A tie against a side is a flip and is not in that rate.
DOUBLE_METHOD = (
    "Each query is judged twice on the same shortlists. The second pass swaps "
    "which list is labeled A and which is labeled B. The judge still sees only "
    "those labels. A pair counts in this preference score only when both passes "
    "pick the same side, or both call a tie. The flip rate is how often the swap "
    "changes that pick. A tie on one pass and a win on the other is a flip, and "
    "that pair is left out of the preference score. Matching ties stay ties: they "
    "count in the agreeing total and count as non-wins in the of-n rate. This "
    "block is separate from the leaderboard, which is one pass per query."
)
HUMAN_METHOD = (
    "People graded a blind sample of the snip shortlists, labeled only as list A "
    "and list B. Agreement is how often that pick matches the published judge on "
    "the same labeling. Kappa is Cohen's kappa for the three labels A, B, and tie."
)
SNIP_HERO_MEANS = (
    "Blinded pairwise preference vs same-pool You.com order, not top-2 sufficiency."
)
TOP3_HIT_MEANS = (
    "A query hits when any successfully judged Agent Seek snip top-3 page "
    "states the locked gold answer. Queries whose page calls all fail are "
    "errors, not misses."
)
SNIP_GLOSS = (
    "Agent Seek's short list was preferred to the same pages in You.com's order."
)
TOP3_GLOSS = "The known answer was in the top three results."
_UNSET = object()


def _of_n(run: dict[str, Any], wins: int) -> ProportionStat:
    return proportion_stat(wins, int(run["judged"]))


def _excl(run: dict[str, Any], wins: int) -> ProportionStat:
    return proportion_stat(wins, int(run["excl_ties"]))


def _md_rate(pct: float, stat: ProportionStat) -> str:
    if not stat.defined:
        return f"{pct:.1f}%"
    return f"{pct:.1f}% ({format_rate_detail(stat)})"


def _judge_certainty(row: dict[str, Any] | None) -> str:
    judge = (row or {}).get("judge") or {}
    conf = judge.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return "\u2014"
    return f"{float(conf):.2f}"


def preferred_margin(as_wins: int, base_wins: int) -> str:
    """Quiet shade trigger: 'as' | 'base' | '' when the margin is unclear."""
    if as_wins >= base_wins + 2:
        return "as"
    if base_wins >= as_wins + 2:
        return "base"
    return ""


def rate_cell_class(side: str, as_wins: int, base_wins: int) -> str:
    """Shade only the winning side's rate cell (soft green / muted red)."""
    winner = preferred_margin(int(as_wins), int(base_wins))
    if winner == "as" and side == "as":
        return "eval-win"
    if winner == "base" and side == "base":
        return "eval-loss"
    return ""


def _short_sha(sha: str, n: int = 12) -> str:
    sha = sha or ""
    return f"{sha[:n]}…" if len(sha) > n else sha


def _host_path(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    if len(path) > 48:
        path = path[:45] + "…"
    return f"{host}{path}" if host else url


def _is_complete_run(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "summary.json").is_file()
        and (path / "run_meta.json").is_file()
        and (path / "per_query.jsonl").is_file()
    )


def _run_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def load_run_from_dir(path: Path, *, rel: str | None = None) -> dict[str, Any]:
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    run_meta = json.loads((path / "run_meta.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for line in (path / "per_query.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    n = int(summary["n"])
    as_w = int(summary["agent_seek_wins"])
    base_w = int(summary["baseline_wins"])
    ties = int(summary["ties"])
    errors = int(summary["errors"])
    judged = n - errors
    excl = judged - ties
    judge = run_meta.get("judge") or {}
    return {
        "summary": summary,
        "run_meta": run_meta,
        "rows": rows,
        "n": n,
        "as_wins": as_w,
        "baseline_wins": base_w,
        "ties": ties,
        "errors": errors,
        "judged": judged,
        "excl_ties": excl,
        "as_rate": pct1(as_w, judged),
        "as_rate_int": pct_int(as_w, judged),
        "as_rate_excl": pct1(as_w, excl),
        "as_rate_excl_int": pct_int(as_w, excl),
        "base_rate": pct1(base_w, judged),
        "base_rate_excl": pct1(base_w, excl),
        "tie_rate": pct1(ties, judged),
        "judge_model": judge.get("model") or "",
        "reasoning_effort": judge.get("reasoning_effort") or "",
        "reasoning_mode": judge.get("reasoning_mode") or "",
        "prompt_version": run_meta.get("prompt_version") or "",
        "prompt_sha": run_meta.get("prompt_sha256") or "",
        "run_id": run_meta.get("run_id") or "",
        "suite_version": run_meta.get("suite_version") or "",
        "mode": run_meta.get("mode") or "deep",
        "k": run_meta.get("k") or 10,
        "rel": rel or _run_rel(path),
        "path": path,
    }


def is_double_judge_meta(name: str, meta: dict[str, Any] | None = None) -> bool:
    """Side-swap artifacts are not the single-pass snip leaderboard."""
    if name.endswith("-double"):
        return True
    meta = meta or {}
    if meta.get("double_judge") or meta.get("kind") == "double_judge":
        return True
    return False


def find_snip_published_dir() -> Path | None:
    for rel in SNIP_CANDIDATE_RELS:
        path = ROOT / rel
        if _is_complete_run(path):
            return path
    if not PUBLISHED_ROOT.is_dir():
        return None
    for child in sorted(PUBLISHED_ROOT.iterdir()):
        if not child.is_dir() or child.name == "v1.0.0-first-run":
            continue
        if not _is_complete_run(child):
            continue
        try:
            meta = json.loads((child / "run_meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if is_double_judge_meta(child.name, meta):
            continue
        if (meta.get("mode") or "") == "snip":
            return child
    return None


def _published_stamp() -> tuple[tuple[str, float], ...]:
    items: list[tuple[str, float]] = []
    if PUBLISHED_ROOT.is_dir():
        for name in ("summary.json", "results.jsonl"):
            for path in PUBLISHED_ROOT.rglob(name):
                try:
                    items.append((str(path), path.stat().st_mtime))
                except OSError:
                    continue
    if HUMAN_SUMMARY.is_file():
        try:
            items.append((str(HUMAN_SUMMARY), HUMAN_SUMMARY.stat().st_mtime))
        except OSError:
            pass
    return tuple(sorted(items))


def _is_double_complete(path: Path) -> bool:
    if not _is_complete_run(path):
        return False
    try:
        meta = json.loads((path / "run_meta.json").read_text(encoding="utf-8"))
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(meta, dict) or not isinstance(summary, dict):
        return False
    if not is_double_judge_meta(path.name, meta) and summary.get("kind") != "double_judge":
        return False
    for key in (
        "agreeing",
        "flips",
        "both_verdicts",
        "agent_seek_wins",
        "baseline_wins",
        "ties",
    ):
        if key not in summary:
            return False
    return True


def find_double_dirs() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for mode, names in (("snip", SNIP_DOUBLE_NAMES), ("deep", DEEP_DOUBLE_NAMES)):
        for name in names:
            path = PUBLISHED_ROOT / name
            if _is_double_complete(path):
                found[mode] = path
                break
    return found


def load_double_run(path: Path) -> dict[str, Any]:
    """Counts only. Rates are computed at render time from these integers."""
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    run_meta = json.loads((path / "run_meta.json").read_text(encoding="utf-8"))
    judge = run_meta.get("judge") or {}
    return {
        "summary": summary,
        "run_meta": run_meta,
        "mode": str(summary.get("mode") or run_meta.get("mode") or ""),
        "rel": _run_rel(path),
        "n": int(summary.get("n") or 0),
        "both_verdicts": int(summary["both_verdicts"]),
        "flips": int(summary["flips"]),
        "agreeing": int(summary["agreeing"]),
        "as_wins": int(summary["agent_seek_wins"]),
        "baseline_wins": int(summary["baseline_wins"]),
        "ties": int(summary["ties"]),
        "errors": int(summary.get("errors") or 0),
        "run_id": run_meta.get("run_id") or "",
        "judge_model": judge.get("model") or "",
        "shortlist_text": summary.get("shortlist_text") or run_meta.get("shortlist_text") or "",
    }


def load_double_bundle() -> dict[str, dict[str, Any] | None]:
    found = find_double_dirs()
    return {
        "snip": load_double_run(found["snip"]) if "snip" in found else None,
        "deep": load_double_run(found["deep"]) if "deep" in found else None,
    }


def load_human_summary() -> dict[str, Any] | None:
    """Present only when a scored human file exists. Blank packets do not count."""
    if not HUMAN_SUMMARY.is_file():
        return None
    try:
        data = json.loads(HUMAN_SUMMARY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "human_agreement":
        return None
    try:
        labeled = int(data.get("labeled") or 0)
    except (TypeError, ValueError):
        return None
    if labeled < 1 or not isinstance(data.get("agreement"), (int, float)):
        return None
    if isinstance(data.get("agreement"), bool):
        return None
    return data


def _json_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _is_top3_complete(path: Path) -> bool:
    """Published top-3 needs summary + run_meta. Counts come from the summary."""
    summary_path = path / "summary.json"
    meta_path = path / "run_meta.json"
    if not summary_path.is_file() or not meta_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(summary, dict) or not isinstance(meta, dict):
        return False
    if summary.get("kind") != "top3_gold":
        return False
    for key in ("hits", "misses", "errors", "scored", "n"):
        if _json_int(summary.get(key)) is None:
            return False
    hits = int(summary["hits"])
    misses = int(summary["misses"])
    scored = int(summary["scored"])
    n = int(summary["n"])
    errors = int(summary["errors"])
    if min(hits, misses, errors, scored, n) < 0:
        return False
    if hits + misses != scored or scored + errors != n:
        return False
    if hits > scored or scored > n:
        return False
    return True


def _count_first_hit_ranks(path: Path) -> dict[int, int] | None:
    """Count ``first_hit_rank`` on hit rows in ``results.jsonl``.

    Returns None when the file is missing or not valid JSONL, so the page
    omits the rank line instead of inventing one. Ranks other than 1–3 are
    ignored. A file of only misses still returns zeros.
    """
    results_path = path / "results.jsonl"
    if not results_path.is_file():
        return None
    try:
        text = results_path.read_text(encoding="utf-8")
    except OSError:
        return None
    counts: Counter[int] = Counter()
    hits = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(row, dict) or row.get("hit") is not True:
            continue
        hits += 1
        rank = row.get("first_hit_rank")
        if isinstance(rank, bool) or not isinstance(rank, int):
            continue
        if rank not in (1, 2, 3):
            continue
        counts[rank] += 1
    if hits and not counts:
        return None
    return {1: counts[1], 2: counts[2], 3: counts[3]}


def _first_hit_counts(ranks: dict[int, int] | None) -> tuple[int, int, int] | None:
    """``(#1, #2, #3)`` counts, or None when ranks were not loaded."""
    if not isinstance(ranks, dict):
        return None
    try:
        raw = (ranks[1], ranks[2], ranks[3])
        counts = tuple(int(value) for value in raw)
    except (KeyError, TypeError, ValueError):
        return None
    if any(isinstance(value, bool) for value in raw):
        return None
    return (counts[0], counts[1], counts[2])


def _first_hit_sentence(n1: int, total: int) -> str | None:
    """Plain reading of the #1 count. Omitted when there are no ranked hits."""
    if total <= 0:
        return None
    return f"{n1} of {total} hits already stated the answer in the first result."


def _first_hit_markdown(ranks: dict[int, int] | None) -> list[str]:
    """Stacked ``#1 → n`` lines. Empty when ranks were not loaded."""
    counts = _first_hit_counts(ranks)
    if counts is None:
        return []
    n1, n2, n3 = counts
    total = n1 + n2 + n3
    lines = ["First result that stated the answer:", ""]
    for rank, count in ((1, n1), (2, n2), (3, n3)):
        share = f" ({pct_int(count, total)}% of hits)" if total else ""
        lines.append(f"- **#{rank} → {count}**{share}")
    lines.append("")
    sentence = _first_hit_sentence(n1, total)
    if sentence:
        lines += [sentence, ""]
    return lines


def _first_hit_html(ranks: dict[int, int] | None) -> str:
    """Three ranked rows under the hit-rate headline. Empty when ranks were not loaded."""
    counts = _first_hit_counts(ranks)
    if counts is None:
        return ""
    n1, n2, n3 = counts
    total = n1 + n2 + n3
    rows: list[str] = []
    for rank, count in ((1, n1), (2, n2), (3, n3)):
        lead = " eval-rank-1" if rank == 1 else ""
        if total:
            pct = pct_int(count, total)
            share = f'<span class="eval-rank-share">{pct}% <span class="eval-rank-of">of hits</span></span>'
        else:
            pct = 0
            share = '<span class="eval-rank-share">—</span>'
        rows.append(
            f'<li class="eval-rank{lead}">'
            f'<span class="eval-rank-place">#{rank}</span>'
            f'<span class="eval-rank-arrow" aria-hidden="true">\u2192</span>'
            f'<span class="eval-rank-count">{count}</span>'
            f'<span class="eval-rank-track" aria-hidden="true">'
            f'<span class="eval-rank-fill" style="width:{pct}%"></span>'
            f"</span>"
            f"{share}"
            f"</li>"
        )
    sentence = _first_hit_sentence(n1, total)
    note = f'<p class="eval-first-hit-note">{html.escape(sentence)}</p>' if sentence else ""
    return (
        '<section class="eval-first-hits" aria-label="First result that stated the answer">'
        '<p class="eval-first-hit-kicker">First result that stated the answer</p>'
        f'<ol class="eval-rank-list">{"".join(rows)}</ol>'
        f"{note}"
        "</section>"
    )


def find_top3_published_dir() -> Path | None:
    """Only ``published/v1.0.0-snip-top3/``. Scratch ``top3/results/`` is ignored."""
    if _is_top3_complete(TOP3_DIR):
        return TOP3_DIR
    return None


def load_top3_from_dir(path: Path) -> dict[str, Any] | None:
    """Hit rate is hits/scored from the file. A stored ``hit_rate`` is not used."""
    if not _is_top3_complete(path):
        return None
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    run_meta = json.loads((path / "run_meta.json").read_text(encoding="utf-8"))
    judge = run_meta.get("judge") or {}
    hits = int(summary["hits"])
    scored = int(summary["scored"])
    return {
        "summary": summary,
        "run_meta": run_meta,
        "hits": hits,
        "misses": int(summary["misses"]),
        "errors": int(summary["errors"]),
        "scored": scored,
        "n": int(summary["n"]),
        "k": int(summary.get("k") or run_meta.get("k") or 3),
        "mode": str(summary.get("mode") or run_meta.get("mode") or "snip"),
        "rel": _run_rel(path),
        "judge_model": str(judge.get("model") or ""),
        "reasoning_effort": str(judge.get("reasoning_effort") or ""),
        "reasoning_mode": str(judge.get("reasoning_mode") or ""),
        "prompt_version": str(run_meta.get("prompt_version") or ""),
        "run_id": str(run_meta.get("run_id") or ""),
        "first_hit_ranks": _count_first_hit_ranks(path),
    }


def load_top3_published() -> dict[str, Any] | None:
    path = find_top3_published_dir()
    if path is None:
        return None
    return load_top3_from_dir(path)


@lru_cache(maxsize=8)
def _load_eval_bundle_cached(stamp: tuple[tuple[str, float], ...]) -> dict[str, Any]:
    del stamp
    deep = load_run_from_dir(DEEP_DIR, rel=DEEP_REL)
    snip_dir = find_snip_published_dir()
    snip = load_run_from_dir(snip_dir) if snip_dir is not None else None
    return {
        "deep": deep,
        "snip": snip,
        "doubles": load_double_bundle(),
        "human": load_human_summary(),
        "top3": load_top3_published(),
    }


def load_eval_bundle() -> dict[str, Any]:
    return _load_eval_bundle_cached(_published_stamp())


def load_published_run() -> dict[str, Any]:
    """Deep published run (v1.0.0-first-run)."""
    return load_eval_bundle()["deep"]


def published_honesty_line(
    run: dict[str, Any],
    snip: dict[str, Any] | None = None,
) -> str:
    if snip is not None:
        return (
            "Both published runs measure Agent Seek against same-pool You.com order: "
            "`mode=snip` (product default — UI and API/MCP) and `mode=deep` "
            "(optional richer mode; eval treatment)."
        )
    mode = str(run.get("mode") or "deep")
    return (
        f"This published run measures Agent Seek `mode={mode}` against same-pool "
        "You.com order. Product default is `mode=snip` (UI and API/MCP); snip "
        "preference is not validated by this table."
    )


def published_honesty_html(
    run: dict[str, Any],
    snip: dict[str, Any] | None = None,
) -> str:
    if snip is not None:
        return (
            "Both published runs measure Agent Seek against same-pool You.com order: "
            "<code>mode=snip</code> (product default — UI and API/MCP) and "
            "<code>mode=deep</code> (optional richer mode; eval treatment)."
        )
    mode = html.escape(str(run.get("mode") or "deep"))
    return (
        f"This published run measures Agent Seek <code>mode={mode}</code> against "
        "same-pool You.com order. Product default is <code>mode=snip</code> "
        "(UI and API/MCP); snip preference is not validated by this table."
    )


def _mode_label(run: dict[str, Any], *, snip_is_default: bool = False) -> str:
    mode = str(run.get("mode") or "deep")
    if mode == "snip" or snip_is_default:
        return "mode=snip (product default)"
    return f"mode={mode} (optional richer mode)"


def _judge_line(run: dict[str, Any]) -> str:
    return (
        f"Judge: `{run['judge_model']}` · `reasoning.effort={run['reasoning_effort']}` · "
        f"`reasoning.mode={run['reasoning_mode']}` · prompt `{run['prompt_version']}` · "
        f"sha `{_short_sha(run['prompt_sha'])}` · run `{run['run_id']}` · "
        f"suite `{run['suite_version']}`"
    )


def _insert_rate_note(lines: list[str]) -> None:
    """Place the denominator note immediately after the score block."""
    lines += ["", WIN_RATE_NOTE, ""]


def _with_eval_extras(
    run: dict[str, Any] | None,
    snip: dict[str, Any] | None,
    doubles: dict[str, Any] | None,
    human: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    if run is None:
        bundle = load_eval_bundle()
        run = bundle["deep"]
        snip = bundle["snip"]
        if doubles is None:
            doubles = bundle.get("doubles") or {}
        if human is None:
            human = bundle.get("human")
    if doubles is None:
        doubles = {}
    return run, snip, doubles, human


def _flip_phrase(run: dict[str, Any]) -> str:
    both = int(run["both_verdicts"])
    flips = int(run["flips"])
    if both <= 0:
        return "no complete pairs"
    return f"{pct1(flips, both):.1f}% ({flips}/{both})"


def _agreeing_rate_bits(run: dict[str, Any]) -> tuple[ProportionStat, ProportionStat, int]:
    agreeing = int(run["agreeing"])
    ties = int(run["ties"])
    wins = int(run["as_wins"])
    excl_n = agreeing - ties
    return proportion_stat(wins, agreeing), proportion_stat(wins, excl_n), excl_n


def _position_markdown(doubles: dict[str, Any]) -> list[str]:
    lines = ["## Position check", ""]
    any_run = False
    for mode, label in (
        ("snip", "Snip (product default)"),
        ("deep", "Deep (optional richer mode)"),
    ):
        side = doubles.get(mode)
        if not side:
            lines.append(f"{label}: side-swapped double judge not yet run.")
            lines.append("")
            continue
        any_run = True
        of_n, excl, excl_n = _agreeing_rate_bits(side)
        lines += [
            f"**{label} flip rate {_flip_phrase(side)}.**",
            "",
            (
                f"Agreeing pairs only: **{pct1(side['as_wins'], side['agreeing']):.1f}%** "
                f"preferred ({side['as_wins']}/{side['agreeing']}; {format_rate_detail(of_n)}). "
                f"Excl. ties {pct1(side['as_wins'], excl_n):.1f}% "
                f"({side['as_wins']}/{excl_n}; {format_rate_detail(excl)})."
            ),
            "",
            (
                "Agreeing W/T/L (Agent Seek / tie / You.com order): "
                f"{side['as_wins']} / {side['ties']} / {side['baseline_wins']}. "
                f"Incomplete pairs: {side['errors']}. n={side['n']}."
            ),
            "",
        ]
        if side.get("shortlist_text") == "url_only":
            lines += [
                "Shortlists in this pass were the published URLs (titles and snippets were not stored).",
                "",
            ]
    if any_run:
        lines += [DOUBLE_METHOD, ""]
    return lines


def _human_markdown(human: dict[str, Any] | None) -> list[str]:
    if not human:
        return []
    labeled = int(human["labeled"])
    agree = int(human.get("agree") or 0)
    pct = 100.0 * float(human["agreement"])
    kappa = human.get("kappa")
    kappa_s = "undefined" if not isinstance(kappa, (int, float)) or isinstance(kappa, bool) else f"{float(kappa):.3f}"
    lines = [
        "## Human baseline",
        "",
        f"Agreement {pct:.1f}% ({agree}/{labeled}). Cohen's kappa {kappa_s}.",
        "",
        HUMAN_METHOD,
        "",
    ]
    mapped = human.get("human_mapped") or {}
    if all(k in mapped for k in ("agent_seek", "baseline", "tie")):
        lines += [
            (
                "Human picks, mapped onto the same arms: "
                f"Agent Seek {mapped['agent_seek']} · tie {mapped['tie']} · "
                f"You.com order {mapped['baseline']}."
            ),
            "",
        ]
    return lines


def _position_html(doubles: dict[str, Any]) -> str:
    e = html.escape
    blocks: list[str] = ["<h2>Position check</h2>"]
    any_run = False
    for mode, label in (
        ("snip", "Snip (product default)"),
        ("deep", "Deep (optional richer mode)"),
    ):
        side = doubles.get(mode)
        if not side:
            blocks.append(
                f'<p class="eval-note">{e(label)}: side-swapped double judge not yet run.</p>'
            )
            continue
        any_run = True
        of_n, excl, excl_n = _agreeing_rate_bits(side)
        url_note = ""
        if side.get("shortlist_text") == "url_only":
            url_note = (
                '<p class="eval-note">Shortlists in this pass were the published URLs '
                "(titles and snippets were not stored).</p>"
            )
        blocks.append(
            f'<p class="eval-flip">{e(label)} flip rate {e(_flip_phrase(side))}.</p>'
            f'<p class="eval-score-sub">Agreeing pairs only: '
            f'{pct1(side["as_wins"], side["agreeing"]):.1f}% preferred '
            f'({side["as_wins"]}/{side["agreeing"]}; {e(format_rate_detail(of_n))}). '
            f'Excl. ties {pct1(side["as_wins"], excl_n):.1f}% '
            f'({side["as_wins"]}/{excl_n}; {e(format_rate_detail(excl))}).</p>'
            f'<p class="eval-note">Agreeing W/T/L (Agent Seek / tie / You.com order): '
            f'{side["as_wins"]} / {side["ties"]} / {side["baseline_wins"]}. '
            f'Incomplete pairs: {side["errors"]}. n={side["n"]}.</p>'
            f"{url_note}"
        )
    if any_run:
        blocks.append(f'<p class="eval-note">{e(DOUBLE_METHOD)}</p>')
    return "\n".join(blocks)


def _human_html(human: dict[str, Any] | None) -> str:
    if not human:
        return ""
    labeled = int(human["labeled"])
    agree = int(human.get("agree") or 0)
    pct = 100.0 * float(human["agreement"])
    kappa = human.get("kappa")
    if not isinstance(kappa, (int, float)) or isinstance(kappa, bool):
        kappa_s = "undefined"
    else:
        kappa_s = f"{float(kappa):.3f}"
    mapped = human.get("human_mapped") or {}
    mapped_html = ""
    if all(k in mapped for k in ("agent_seek", "baseline", "tie")):
        mapped_html = (
            '<p class="eval-note">Human picks, mapped onto the same arms: '
            f'Agent Seek {int(mapped["agent_seek"])} · tie {int(mapped["tie"])} · '
            f'You.com order {int(mapped["baseline"])}.</p>'
        )
    return (
        "<h2>Human baseline</h2>"
        f'<p class="eval-flip">Agreement {pct:.1f}% ({agree}/{labeled}). '
        f"Cohen's kappa {html.escape(kappa_s)}.</p>"
        f'<p class="eval-note">{html.escape(HUMAN_METHOD)}</p>'
        f"{mapped_html}"
    )


def render_eval_markdown(
    run: dict[str, Any] | None = None,
    snip: dict[str, Any] | None = None,
    doubles: dict[str, Any] | None = None,
    human: dict[str, Any] | None = None,
) -> str:
    run, snip, doubles, human = _with_eval_extras(run, snip, doubles, human)
    meta = run["run_meta"]
    lines = [
        "---",
        "title: Agent Seek Preference Eval",
        "canonical: /eval/v0.md",
        "---",
        "",
        "# Agent Seek Preference Eval",
        "",
        "Archived dense page. [Current eval](/eval).",
        "",
        "Same-pool pairwise preference vs You.com order · frozen suite `public_v1`.",
        "",
        published_honesty_line(run, snip),
        "",
    ]
    if snip is not None:
        snip_of = _of_n(snip, snip["as_wins"])
        snip_ex = _excl(snip, snip["as_wins"])
        deep_of = _of_n(run, run["as_wins"])
        deep_ex = _excl(run, run["as_wins"])
        lines += [
            f"**Snip (product default): {snip['as_rate_int']}% preferred** "
            f"({snip['as_wins']}/{snip['n']}; {format_rate_detail(snip_of)}); excl. ties "
            f"**{snip['as_rate_excl_int']}%** "
            f"({snip['as_wins']}/{snip['excl_ties']}; {format_rate_detail(snip_ex)}).",
            "",
            f"**Deep (optional richer mode): {run['as_rate_int']}% preferred** "
            f"({run['as_wins']}/{run['n']}; {format_rate_detail(deep_of)}); excl. ties "
            f"**{run['as_rate_excl_int']}%** "
            f"({run['as_wins']}/{run['excl_ties']}; {format_rate_detail(deep_ex)}).",
            "",
            f"Snip: ties {snip['ties']} · baseline wins {snip['baseline_wins']} · "
            f"n={snip['n']} · {snip['errors']} errors",
            "",
            f"Deep: ties {run['ties']} · baseline wins {run['baseline_wins']} · "
            f"n={run['n']} · {run['errors']} errors",
            "",
            f"Snip {_judge_line(snip)}",
            "",
            f"Deep {_judge_line(run)}",
            "",
        ]
        _insert_rate_note(lines)
    else:
        deep_of = _of_n(run, run["as_wins"])
        deep_ex = _excl(run, run["as_wins"])
        lines += [
            f"**{run['as_rate_int']}% preferred** "
            f"({run['as_wins']}/{run['n']}; {format_rate_detail(deep_of)}); "
            f"excl. ties **{run['as_rate_excl_int']}%** "
            f"({run['as_wins']}/{run['excl_ties']}; {format_rate_detail(deep_ex)}).",
            "",
            f"ties {run['ties']} · baseline wins {run['baseline_wins']} · n={run['n']} · "
            f"{run['errors']} errors",
            "",
            _judge_line(run),
            "",
        ]
        _insert_rate_note(lines)
    lines += [
        "Static published run. This page does not call OpenAI, You.com, or TypeSafe.",
        "",
        "## Method",
        "",
        "1. Discover once (You.com). Both sides use that candidate list.",
        "2. Baseline: You.com order top-k.",
    ]
    if snip is not None:
        lines += [
            (
                f"3. Treatment (deep): Agent Seek cascade top-k on the same objects "
                f"(`mode={run['mode']}`, optional richer mode) — "
                f"[`{run['rel']}/`](/{run['rel']}/summary.json)."
            ),
            (
                f"4. Treatment (snip): Agent Seek cascade top-k on the same objects "
                f"(`mode={snip['mode']}`, product default — UI and API/MCP) — "
                f"[`{snip['rel']}/`](/{snip['rel']}/summary.json)."
            ),
            "5. Blind A/B labels. Mapping is stored in run output only.",
            "6. Judge prefers the more useful shortlist (authority, on-topic, sought fact; not scrapers or hijack pages).",
            "",
            "Both published runs measure **preference vs same-pool You.com order**, not top-2 sufficiency.",
        ]
    else:
        lines += [
            (
                f"3. Treatment: Agent Seek cascade top-k on the same objects "
                f"(`mode={run['mode']}`). `mode=snip` is unvalidated by this table."
            ),
            "4. Blind A/B labels. Mapping is stored in run output only.",
            "5. Judge prefers the more useful shortlist (authority, on-topic, sought fact; not scrapers or hijack pages).",
            "",
            "This published eval measures **preference vs same-pool You.com order**, not top-2 sufficiency.",
        ]
    lines += [
        "",
        f"Suite: [evals/public_v1/README.md](/evals/public_v1/README.md) · "
        f"prompt: [PROMPT_v1.md](/evals/public_v1/judge/PROMPT_v1.md) · "
        f"deep: [`{run['rel']}/`](/{run['rel']}/summary.json)",
    ]
    if snip is not None:
        lines.append(f"snip: [`{snip['rel']}/`](/{snip['rel']}/summary.json)")
    lines += ["", "## Leaderboard", ""]
    if snip is not None:
        lines += [
            "Same-pool preference vs You.com order. Columns are cascade mode.",
            "",
            "| System | Deep wins | Deep rate (of n) | Deep excl. ties | Snip wins | Snip rate (of n) | Snip excl. ties |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| Agent Seek | {run['as_wins']} | {_md_rate(run['as_rate'], _of_n(run, run['as_wins']))} | "
                f"{_md_rate(run['as_rate_excl'], _excl(run, run['as_wins']))} | {snip['as_wins']} | "
                f"{_md_rate(snip['as_rate'], _of_n(snip, snip['as_wins']))} | "
                f"{_md_rate(snip['as_rate_excl'], _excl(snip, snip['as_wins']))} |"
            ),
            (
                f"| You.com order (same pool) | {run['baseline_wins']} | "
                f"{_md_rate(run['base_rate'], _of_n(run, run['baseline_wins']))} | "
                f"{_md_rate(run['base_rate_excl'], _excl(run, run['baseline_wins']))} | "
                f"{snip['baseline_wins']} | "
                f"{_md_rate(snip['base_rate'], _of_n(snip, snip['baseline_wins']))} | "
                f"{_md_rate(snip['base_rate_excl'], _excl(snip, snip['baseline_wins']))} |"
            ),
            (
                f"| Tie | {run['ties']} | {run['tie_rate']:.1f}% | — | "
                f"{snip['ties']} | {snip['tie_rate']:.1f}% | — |"
            ),
            "",
        ]
        for label, side in ((_mode_label(snip, snip_is_default=True), snip), (_mode_label(run), run)):
            lines += [
                f"### {label}",
                "",
                "| System | Pref. wins | Win rate (of n) | Win rate (excl. ties) |",
                "| --- | ---: | ---: | ---: |",
                (
                    f"| Agent Seek ({side['mode']}) | {side['as_wins']} | "
                    f"{_md_rate(side['as_rate'], _of_n(side, side['as_wins']))} | "
                    f"{_md_rate(side['as_rate_excl'], _excl(side, side['as_wins']))} |"
                ),
                (
                    f"| You.com order (same pool) | {side['baseline_wins']} | "
                    f"{_md_rate(side['base_rate'], _of_n(side, side['baseline_wins']))} | "
                    f"{_md_rate(side['base_rate_excl'], _excl(side, side['baseline_wins']))} |"
                ),
                f"| Tie | {side['ties']} | {side['tie_rate']:.1f}% | — |",
                "",
            ]
    else:
        lines += [
            "| System | Pref. wins | Win rate (of n) | Win rate (excl. ties) |",
            "| --- | ---: | ---: | ---: |",
            (
                f"| Agent Seek ({run['mode']}) | {run['as_wins']} | "
                f"{_md_rate(run['as_rate'], _of_n(run, run['as_wins']))} | "
                f"{_md_rate(run['as_rate_excl'], _excl(run, run['as_wins']))} |"
            ),
            (
                f"| You.com order (same pool) | {run['baseline_wins']} | "
                f"{_md_rate(run['base_rate'], _of_n(run, run['baseline_wins']))} | "
                f"{_md_rate(run['base_rate_excl'], _excl(run, run['baseline_wins']))} |"
            ),
            f"| Tie | {run['ties']} | {run['tie_rate']:.1f}% | — |",
            "",
        ]
    lines += [SUITE_BALANCE_NOTE, ""]
    lines += _position_markdown(doubles)
    lines += _human_markdown(human)
    certainty_note = JUDGE_CERTAINTY_NOTE_DUAL if snip is not None else JUDGE_CERTAINTY_NOTE
    lines += [
        "",
        "## Per-query",
        "",
        certainty_note,
        "",
    ]
    if snip is not None:
        lines += [
            "| id | tier | query | deep | snip | Judge certainty |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        snip_by_id = {row.get("id"): row for row in snip["rows"]}
        for row in run["rows"]:
            deep_w = WINNER_LABEL.get(row.get("mapped_winner") or "", row.get("mapped_winner") or "")
            srow = snip_by_id.get(row.get("id")) or {}
            snip_w = WINNER_LABEL.get(srow.get("mapped_winner") or "", srow.get("mapped_winner") or "")
            q = (row.get("q") or "").replace("|", "/")
            cert = f"{_judge_certainty(row)} / {_judge_certainty(srow)}"
            lines.append(
                f"| {row.get('id')} | {row.get('tier')} | {q} | {deep_w} | {snip_w} | {cert} |"
            )
    else:
        lines += [
            "| id | tier | query | winner | Judge certainty |",
            "| --- | --- | --- | --- | ---: |",
        ]
        for row in run["rows"]:
            winner = WINNER_LABEL.get(row.get("mapped_winner") or "", row.get("mapped_winner") or "")
            q = (row.get("q") or "").replace("|", "/")
            lines.append(
                f"| {row.get('id')} | {row.get('tier')} | {q} | {winner} | {_judge_certainty(row)} |"
            )
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "python scripts/eval_llm_judge.py --dry-run",
        "python scripts/eval_llm_judge.py",
        "python scripts/eval_llm_judge.py --mode snip",
        "python scripts/eval_llm_judge.py --double-judge --dry-run \\",
        "    --from-published evals/public_v1/published/v1.0.0-snip",
        "```",
        "",
        f"Deep artifacts: `{run['rel']}/` "
        f"(`summary.json`, `run_meta.json`, `per_query.jsonl`). ",
    ]
    if snip is not None:
        lines.append(
            f"Snip artifacts: `{snip['rel']}/`. "
            f"`evals/public_v1/results/run_*` stays gitignored."
        )
    else:
        lines.append("`evals/public_v1/results/run_*` stays gitignored.")
    lines += [
        "",
        f"Deep run started {meta.get('started_at')} · finished {meta.get('finished_at')} · "
        f"k={run['k']} · max_candidates={meta.get('max_candidates')} · path={meta.get('path')}.",
        "",
    ]
    if snip is not None:
        sm = snip["run_meta"]
        lines.append(
            f"Snip run started {sm.get('started_at')} · finished {sm.get('finished_at')} · "
            f"k={snip['k']} · max_candidates={sm.get('max_candidates')} · path={sm.get('path')}."
        )
        lines.append("")
    return "\n".join(lines)


def _url_list_html(urls: list[str], k: int = 5) -> str:
    items = []
    for u in urls[:k]:
        label = html.escape(_host_path(u))
        href = html.escape(u, quote=True)
        items.append(f'<li><a href="{href}" rel="noopener noreferrer">{label}</a></li>')
    if not items:
        items.append("<li>(empty)</li>")
    return "<ol class=\"eval-urls\">" + "".join(items) + "</ol>"


def _num_td(text: str, shade: str = "") -> str:
    cls = "eval-num" + (f" {html.escape(shade)}" if shade else "")
    return f'<td class="{cls}">{text}</td>'


def _rate_td(pct_text: str, stat: ProportionStat, shade: str = "") -> str:
    """Win-rate cell: point estimate, then Wilson CI and exact p."""
    cls = "eval-num" + (f" {html.escape(shade)}" if shade else "")
    if not stat.defined:
        return f'<td class="{cls}"><span class="eval-rate">{pct_text}</span></td>'
    assert stat.ci_low is not None and stat.ci_high is not None and stat.p_value is not None
    ci = html.escape(format_wilson_ci(stat.ci_low, stat.ci_high))
    p = html.escape(format_p_value(stat.p_value))
    return (
        f'<td class="{cls}">'
        f'<span class="eval-rate">{pct_text}</span>'
        f'<span class="eval-ci">Wilson {ci}</span>'
        f'<span class="eval-p">p={p}</span>'
        "</td>"
    )


def _leaderboard_rows_html(run: dict[str, Any]) -> str:
    e = html.escape
    as_shade = rate_cell_class("as", run["as_wins"], run["baseline_wins"])
    base_shade = rate_cell_class("base", run["as_wins"], run["baseline_wins"])
    rows = [
        (
            True,
            f"Agent Seek ({e(str(run['mode']))})",
            run["as_wins"],
            f"{run['as_rate']:.1f}%",
            _of_n(run, run["as_wins"]),
            f"{run['as_rate_excl']:.1f}%",
            _excl(run, run["as_wins"]),
            as_shade,
        ),
        (
            False,
            "You.com order (same pool)",
            run["baseline_wins"],
            f"{run['base_rate']:.1f}%",
            _of_n(run, run["baseline_wins"]),
            f"{run['base_rate_excl']:.1f}%",
            _excl(run, run["baseline_wins"]),
            base_shade,
        ),
    ]
    out = []
    for accent, name, wins, rate, rate_stat, excl, excl_stat, shade in rows:
        cls = ' class="eval-accent"' if accent else ""
        out.append(
            f"<tr{cls}><td>{name}</td>"
            f"{_num_td(str(wins))}"
            f"{_rate_td(rate, rate_stat, shade)}"
            f"{_rate_td(excl, excl_stat, shade)}"
            "</tr>"
        )
    out.append(
        "<tr><td>Tie</td>"
        f"{_num_td(str(run['ties']))}"
        f"{_num_td(f'{run["tie_rate"]:.1f}%')}"
        f"{_num_td('—')}"
        "</tr>"
    )
    return "".join(out)


def _leaderboard_table_html(run: dict[str, Any], heading: str | None = None) -> str:
    head = f"<h3>{html.escape(heading)}</h3>" if heading else ""
    return f"""
    {head}
    <table class="eval-table">
      <thead>
        <tr>
          <th>System</th>
          <th class="eval-num">Pref. wins</th>
          <th class="eval-num">Win rate (of n)</th>
          <th class="eval-num">Win rate (excl. ties)</th>
        </tr>
      </thead>
      <tbody>
        {_leaderboard_rows_html(run)}
      </tbody>
    </table>
"""


def _comparison_table_html(deep: dict[str, Any], snip: dict[str, Any]) -> str:
    deep_as = rate_cell_class("as", deep["as_wins"], deep["baseline_wins"])
    snip_as = rate_cell_class("as", snip["as_wins"], snip["baseline_wins"])
    deep_base = rate_cell_class("base", deep["as_wins"], deep["baseline_wins"])
    snip_base = rate_cell_class("base", snip["as_wins"], snip["baseline_wins"])
    return f"""
    <table class="eval-table eval-compare">
      <thead>
        <tr>
          <th>System</th>
          <th class="eval-num">Deep wins</th>
          <th class="eval-num">Deep rate (of n)</th>
          <th class="eval-num">Snip wins</th>
          <th class="eval-num">Snip rate (of n)</th>
        </tr>
      </thead>
      <tbody>
        <tr class="eval-accent">
          <td>Agent Seek</td>
          {_num_td(str(deep["as_wins"]))}
          {_rate_td(f'{deep["as_rate"]:.1f}%', _of_n(deep, deep["as_wins"]), deep_as)}
          {_num_td(str(snip["as_wins"]))}
          {_rate_td(f'{snip["as_rate"]:.1f}%', _of_n(snip, snip["as_wins"]), snip_as)}
        </tr>
        <tr>
          <td>You.com order (same pool)</td>
          {_num_td(str(deep["baseline_wins"]))}
          {_rate_td(f'{deep["base_rate"]:.1f}%', _of_n(deep, deep["baseline_wins"]), deep_base)}
          {_num_td(str(snip["baseline_wins"]))}
          {_rate_td(f'{snip["base_rate"]:.1f}%', _of_n(snip, snip["baseline_wins"]), snip_base)}
        </tr>
        <tr>
          <td>Tie</td>
          {_num_td(str(deep["ties"]))}
          {_num_td(f'{deep["tie_rate"]:.1f}%')}
          {_num_td(str(snip["ties"]))}
          {_num_td(f'{snip["tie_rate"]:.1f}%')}
        </tr>
      </tbody>
    </table>
"""


def _query_rows_html(run: dict[str, Any], snip: dict[str, Any] | None = None) -> str:
    e = html.escape
    snip_by_id = {row.get("id"): row for row in (snip["rows"] if snip else [])}
    q_html = []
    for row in run["rows"]:
        mapped = row.get("mapped_winner") or ""
        winner = WINNER_LABEL.get(mapped, mapped)
        judge = row.get("judge") or {}
        rationale = e(str(judge.get("rationale") or "").strip())
        qid = e(str(row.get("id") or ""))
        tier = e(str(row.get("tier") or ""))
        q = e(str(row.get("q") or ""))
        treat = _url_list_html(list(row.get("treatment_urls") or []))
        base = _url_list_html(list(row.get("baseline_urls") or []))
        extra = ""
        if snip is not None:
            srow = snip_by_id.get(row.get("id")) or {}
            smapped = srow.get("mapped_winner") or ""
            swinner = WINNER_LABEL.get(smapped, smapped)
            extra = f"<td>{e(swinner)}</td>"
            cert = f"{_judge_certainty(row)} / {_judge_certainty(srow)}"
        else:
            cert = _judge_certainty(row)
        q_html.append(
            "<tr>"
            f'<td class="eval-mono">{qid}</td>'
            f"<td>{tier}</td>"
            f"<td><details class=\"eval-q\">"
            f"<summary>{q}</summary>"
            f'<div class="eval-lists">'
            f"<div><h4>Agent Seek</h4>{treat}</div>"
            f"<div><h4>You.com order</h4>{base}</div>"
            f"</div>"
            f'<p class="eval-rationale">{rationale}</p>'
            f"</details></td>"
            f"<td>{e(winner)}</td>"
            f"{extra}"
            f'<td class="eval-num">{e(cert)}</td>'
            "</tr>"
        )
    return "".join(q_html)


def _method_links_html(run: dict[str, Any], snip: dict[str, Any] | None) -> str:
    e = html.escape
    links = [
        '<a href="/evals/public_v1/README.md">Suite README</a>',
        '<a href="/evals/public_v1/judge/PROMPT_v1.md">PROMPT_v1.md</a>',
        f'<a href="/{e(run["rel"])}/summary.json">deep summary.json</a>',
        f'<a href="/{e(run["rel"])}/run_meta.json">deep run_meta.json</a>',
        f'<a href="/{e(run["rel"])}/per_query.jsonl">deep per_query.jsonl</a>',
    ]
    if snip is not None:
        links += [
            f'<a href="/{e(snip["rel"])}/summary.json">snip summary.json</a>',
            f'<a href="/{e(snip["rel"])}/run_meta.json">snip run_meta.json</a>',
            f'<a href="/{e(snip["rel"])}/per_query.jsonl">snip per_query.jsonl</a>',
        ]
    return " · ".join(links)


def render_eval_body_html(
    run: dict[str, Any] | None = None,
    snip: dict[str, Any] | None = None,
    doubles: dict[str, Any] | None = None,
    human: dict[str, Any] | None = None,
) -> str:
    run, snip, doubles, human = _with_eval_extras(run, snip, doubles, human)
    e = html.escape
    sha = _short_sha(run["prompt_sha"])
    if snip is not None:
        snip_of = _of_n(snip, snip["as_wins"])
        snip_ex = _excl(snip, snip["as_wins"])
        deep_of = _of_n(run, run["as_wins"])
        deep_ex = _excl(run, run["as_wins"])
        score_html = f"""
    <p class="eval-score">{snip['as_rate_int']}% preferred <span class="eval-score-n">snip · product default · {snip['as_wins']}/{snip['n']}</span></p>
    <p class="eval-score-stat">of {snip_of.trials} (ties count as non-wins) · {format_rate_detail(snip_of)}</p>
    <p class="eval-score-sub">Deep (optional richer mode) {run['as_rate_int']}% preferred ({run['as_wins']}/{run['n']}; {format_rate_detail(deep_of)}) · excl. ties snip {snip['as_rate_excl_int']}% ({snip['as_wins']}/{snip['excl_ties']}; {format_rate_detail(snip_ex)}) · deep {run['as_rate_excl_int']}% ({run['as_wins']}/{run['excl_ties']}; {format_rate_detail(deep_ex)})</p>
    <p class="eval-chips">Snip ties {snip['ties']} · baseline {snip['baseline_wins']} · n={snip['n']} · {snip['errors']} errors</p>
    <p class="eval-chips">Deep ties {run['ties']} · baseline {run['baseline_wins']} · n={run['n']} · {run['errors']} errors</p>
    <p class="eval-meta">
      Snip judge <code>{e(snip['judge_model'])}</code>
      · run <code>{e(snip['run_id'])}</code>
      · Deep judge <code>{e(run['judge_model'])}</code>
      · run <code>{e(run['run_id'])}</code>
      · suite <code>{e(run['suite_version'])}</code>
    </p>
"""
        method_items = f"""
        <li>Discover once (You.com). Both sides use that candidate list.</li>
        <li>Baseline: You.com order top-k.</li>
        <li>Treatment (deep): Agent Seek cascade top-k on the same objects (<code>mode={e(str(run['mode']))}</code>, optional richer mode) — <code>{e(run['rel'])}</code>.</li>
        <li>Treatment (snip): Agent Seek cascade top-k on the same objects (<code>mode={e(str(snip['mode']))}</code>, product default — UI and API/MCP) — <code>{e(snip['rel'])}</code>.</li>
        <li>Blind A/B labels. Mapping is stored in run output only.</li>
        <li>Judge prefers the more useful shortlist (authority, on-topic, sought fact; not scrapers or hijack pages).</li>
"""
        method_pref = "Both published runs measure <strong>preference vs same-pool You.com order</strong>, not top-2 sufficiency."
        boards = (
            _comparison_table_html(run, snip)
            + _leaderboard_table_html(snip, _mode_label(snip, snip_is_default=True))
            + _leaderboard_table_html(run, _mode_label(run))
        )
        q_head = """
          <th>id</th>
          <th>tier</th>
          <th>query</th>
          <th>deep</th>
          <th>snip</th>
          <th class="eval-num">Judge certainty</th>
"""
        published_note = (
            f"Deep: <code>{e(run['rel'])}/</code>. "
            f"Snip: <code>{e(snip['rel'])}/</code>. "
            "Scratch output under <code>evals/public_v1/results/run_*</code> stays gitignored."
        )
    else:
        deep_of = _of_n(run, run["as_wins"])
        deep_ex = _excl(run, run["as_wins"])
        score_html = f"""
    <p class="eval-score">{run['as_rate_int']}% preferred <span class="eval-score-n">({run['as_wins']}/{run['n']})</span></p>
    <p class="eval-score-stat">of {deep_of.trials} (ties count as non-wins) · {format_rate_detail(deep_of)}</p>
    <p class="eval-score-sub">excl. ties {run['as_rate_excl_int']}% ({run['as_wins']}/{run['excl_ties']}; {format_rate_detail(deep_ex)})</p>
    <p class="eval-chips">ties {run['ties']} · baseline wins {run['baseline_wins']} · n={run['n']} · {run['errors']} errors</p>
    <p class="eval-meta">
      Judge <code>{e(run['judge_model'])}</code>
      · <code>reasoning.effort={e(run['reasoning_effort'])}</code>
      · <code>reasoning.mode={e(run['reasoning_mode'])}</code>
      · prompt <code>{e(run['prompt_version'])}</code>
      · sha <code>{e(sha)}</code>
      · run <code>{e(run['run_id'])}</code>
      · suite <code>{e(run['suite_version'])}</code>
    </p>
"""
        method_items = f"""
        <li>Discover once (You.com). Both sides use that candidate list.</li>
        <li>Baseline: You.com order top-k.</li>
        <li>Treatment: Agent Seek cascade top-k on the same objects (<code>mode={e(str(run['mode']))}</code>). <code>mode=snip</code> is unvalidated by this table.</li>
        <li>Blind A/B labels. Mapping is stored in run output only.</li>
        <li>Judge prefers the more useful shortlist (authority, on-topic, sought fact; not scrapers or hijack pages).</li>
"""
        method_pref = "This published eval measures <strong>preference vs same-pool You.com order</strong>, not top-2 sufficiency."
        boards = _leaderboard_table_html(run)
        q_head = """
          <th>id</th>
          <th>tier</th>
          <th>query</th>
          <th>winner</th>
          <th class="eval-num">Judge certainty</th>
"""
        published_note = (
            f"Published run: <code>{e(run['rel'])}/</code>. "
            "Scratch output under <code>evals/public_v1/results/run_*</code> stays gitignored."
        )
    certainty_note = JUDGE_CERTAINTY_NOTE_DUAL if snip is not None else JUDGE_CERTAINTY_NOTE
    return f"""
    <h1>Agent Seek Preference Eval</h1>
    <p class="eval-note">Archived dense page. <a href="/eval">Current eval</a>.</p>
    <p class="eval-sub">Same-pool pairwise preference vs You.com order · frozen suite <code>public_v1</code></p>
    <p class="eval-note eval-honesty">{published_honesty_html(run, snip)}</p>
    {score_html}
    <p class="eval-note">{html.escape(WIN_RATE_NOTE)}</p>

    <details class="eval-method" open>
      <summary>Method</summary>
      <ol>
        {method_items}
      </ol>
      <p>{method_pref}</p>
      <p>{_method_links_html(run, snip)}</p>
    </details>

    <h2>Leaderboard</h2>
    <div class="eval-scroll">
    {boards}
    </div>
    <p class="eval-note">{html.escape(SUITE_BALANCE_NOTE)}</p>

    {_position_html(doubles)}
    {_human_html(human)}

    <h2>Per-query</h2>
    <p class="eval-note">Expand a query for top-5 URLs and the judge rationale. Static only — no live judge. {html.escape(certainty_note)}</p>
    <div class="eval-scroll">
    <table class="eval-table eval-queries">
      <thead>
        <tr>
          {q_head}
        </tr>
      </thead>
      <tbody>
        {_query_rows_html(run, snip)}
      </tbody>
    </table>
    </div>

    <h2>Reproduce</h2>
    <pre><code>python scripts/eval_llm_judge.py --dry-run
python scripts/eval_llm_judge.py
python scripts/eval_llm_judge.py --mode snip
python scripts/eval_llm_judge.py --double-judge --dry-run \\
    --from-published evals/public_v1/published/v1.0.0-snip</code></pre>
    <p class="eval-note">{published_note}</p>
"""


def _v1_parts(
    run: Any = _UNSET,
    snip: Any = _UNSET,
    doubles: Any = _UNSET,
    human: Any = _UNSET,
    top3: Any = _UNSET,
) -> tuple[Any, Any, dict[str, Any], Any, Any]:
    bundle = load_eval_bundle()
    if run is _UNSET:
        run = bundle["deep"]
    if snip is _UNSET:
        snip = bundle["snip"]
    if doubles is _UNSET:
        doubles = bundle.get("doubles") or {}
    if human is _UNSET:
        human = bundle.get("human")
    if top3 is _UNSET:
        top3 = bundle.get("top3")
    if doubles is None:
        doubles = {}
    return run, snip, doubles, human, top3


def _judge_pin(model: str, effort: str, n: int) -> str:
    bits = [f"Judge {model}" if model else "Judge unpublished"]
    if effort:
        bits.append(f"reasoning.effort={effort}")
    bits.append(f"n={n}")
    return " · ".join(bits)


def _wtl(as_wins: int, ties: int, baseline: int) -> str:
    return f"{as_wins} / {ties} / {baseline}"


def _preferred_sentence(wins: int, n: int) -> str | None:
    """Plain reading of the snip win count. Omitted when the run has no questions."""
    if n <= 0:
        return None
    return f"Preferred on {wins} of {n} questions."


def _outcome_rows_markdown(wins: int, ties: int, losses: int, n: int) -> list[str]:
    """Stacked ``Wins → n`` lines. Shares are percent of the published n."""
    lines = [f"Of {n} questions:", ""]
    for label, count in (("Wins", wins), ("Ties", ties), ("Losses", losses)):
        share = f" ({pct_int(count, n)}% of {n})" if n else ""
        lines.append(f"- **{label} → {count}**{share}")
    lines.append("")
    sentence = _preferred_sentence(wins, n)
    if sentence:
        lines += [sentence, ""]
    return lines


def _outcome_rows_html(wins: int, ties: int, losses: int, n: int) -> str:
    """Three labeled rows under the preference headline. Same bars as first-hit ranks."""
    rows: list[str] = []
    for label, count, tone in (
        ("Wins", wins, " eval-rank-1"),
        ("Ties", ties, " eval-rank-tie"),
        ("Losses", losses, " eval-rank-loss"),
    ):
        if n > 0:
            pct = pct_int(count, n)
            share = (
                f'<span class="eval-rank-share">{pct}% '
                f'<span class="eval-rank-of">of {n}</span></span>'
            )
        else:
            pct = 0
            share = '<span class="eval-rank-share">—</span>'
        rows.append(
            f'<li class="eval-rank{tone}">'
            f'<span class="eval-rank-place">{html.escape(label)}</span>'
            f'<span class="eval-rank-arrow" aria-hidden="true">\u2192</span>'
            f'<span class="eval-rank-count">{count}</span>'
            f'<span class="eval-rank-track" aria-hidden="true">'
            f'<span class="eval-rank-fill" style="width:{pct}%"></span>'
            f"</span>"
            f"{share}"
            f"</li>"
        )
    sentence = _preferred_sentence(wins, n)
    note = f'<p class="eval-first-hit-note">{html.escape(sentence)}</p>' if sentence else ""
    kicker = f"Of {n} questions" if n > 0 else "Outcomes"
    return (
        '<section class="eval-outcomes" aria-label="Preference outcomes">'
        f'<p class="eval-first-hit-kicker">{html.escape(kicker)}</p>'
        f'<ol class="eval-rank-list">{"".join(rows)}</ol>'
        f"{note}"
        "</section>"
    )


def _top3_missing_line() -> str:
    return f"{TOP3_HIT_MEANS} No published run at `{TOP3_REL}/`."


def _top3_missing_html() -> str:
    e = html.escape
    return f"{e(TOP3_HIT_MEANS)} No published run at <code>{e(TOP3_REL)}/</code>."


def _diagnostics_markdown(doubles: dict[str, Any], human: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    side = doubles.get("snip")
    if side:
        lines += [
            "## Diagnostics",
            "",
            f"Snip (product default) flip rate {_flip_phrase(side)}.",
            "",
        ]
        if side.get("shortlist_text") == "url_only":
            lines += [
                "Shortlists in this pass were the published URLs (titles and snippets were not stored).",
                "",
            ]
    if human:
        if not lines:
            lines += ["## Diagnostics", ""]
        labeled = int(human["labeled"])
        agree = int(human.get("agree") or 0)
        pct = 100.0 * float(human["agreement"])
        kappa = human.get("kappa")
        if not isinstance(kappa, (int, float)) or isinstance(kappa, bool):
            kappa_s = "undefined"
        else:
            kappa_s = f"{float(kappa):.3f}"
        lines += [
            f"Agreement {pct:.1f}% ({agree}/{labeled}). Cohen's kappa {kappa_s}.",
            "",
        ]
    return lines


def _question_count(snip: dict[str, Any] | None, run: dict[str, Any] | None) -> int:
    if snip is not None:
        return int(snip["n"])
    if run is not None:
        return int(run["n"])
    return 50


def _intro_paragraphs(n: int) -> list[str]:
    """Plain account of the two checks. The cards below are the answers."""
    return [
        f"We asked {n} questions.",
        (
            "We checked whether Agent Seek's short list was preferred to the same pages in You.com's order. "
            "We also checked whether the known answer was in the top three results."
        ),
    ]


def _intro_html(n: int) -> str:
    paragraphs = "".join(f"<p>{html.escape(text)}</p>" for text in _intro_paragraphs(n))
    return f'<div class="eval-intro">{paragraphs}</div>'


def _deep_plain(run: dict[str, Any], *, markdown: bool = False) -> str:
    rate = f"{run['as_rate_int']}% preferred"
    if markdown:
        rate = f"**{rate}**"
    return (
        f"With more text from each page, Agent Seek was {rate} "
        f"({run['as_wins']}/{run['n']})."
    )


def _artifact_md(rel: str, name: str) -> str:
    return f"[`{rel}/{name}`](/{rel}/{name})"


def _artifact_html(rel: str, name: str, label: str | None = None) -> str:
    href = html.escape(f"/{rel}/{name}", quote=True)
    text = html.escape(label or name)
    return f'<a href="{href}">{text}</a>'


def _measured_markdown(
    run: dict[str, Any],
    snip: dict[str, Any] | None,
    top3: dict[str, Any] | None,
) -> list[str]:
    """Wilson intervals, the judge, and artifact paths. After the skim story."""
    lines = ["## How we measured", "", published_honesty_line(run, snip), "", WIN_RATE_NOTE, ""]
    if snip is None:
        lines += ["Snip preference is not validated by the deep table.", ""]
    else:
        stat = _of_n(snip, snip["as_wins"])
        lines += [
            (
                f"Snip preference is {snip['as_rate_int']}% preferred "
                f"({snip['as_wins']}/{snip['n']}; {format_rate_detail(stat)}). "
                f"{SNIP_HERO_MEANS}"
            ),
            "",
            f"{_judge_pin(snip['judge_model'], snip['reasoning_effort'], snip['n'])}.",
            "",
            f"Artifact: {_artifact_md(str(snip['rel']), 'summary.json')}.",
            "",
        ]
    if not top3:
        lines += [_top3_missing_line(), ""]
    else:
        hits = int(top3["hits"])
        scored = int(top3["scored"])
        errors = int(top3["errors"])
        n = int(top3["n"])
        rel = str(top3.get("rel") or TOP3_REL)
        if scored <= 0:
            lines += [
                f"Published run has no scored queries ({hits}/{scored}, {errors} errors, n={n}).",
                "",
            ]
        else:
            stat = proportion_stat(hits, scored)
            lines += [
                (
                    f"Top-3 hit rate is {pct_int(hits, scored)}% "
                    f"({hits}/{scored}; {format_rate_detail(stat)}). "
                    f"Misses {int(top3['misses'])}. Errors {errors}. n={n}."
                ),
                "",
            ]
        pin = _judge_pin(
            str(top3.get("judge_model") or ""),
            str(top3.get("reasoning_effort") or ""),
            n,
        )
        artifact = _artifact_md(rel, "summary.json")
        if top3.get("first_hit_ranks") is not None:
            artifact += " · " + _artifact_md(rel, "results.jsonl")
        lines += [
            f"{pin}. k={int(top3.get('k') or 3)}. {TOP3_HIT_MEANS}",
            "",
            f"Artifact: {artifact}.",
            "",
        ]
    stat = _of_n(run, run["as_wins"])
    excl = _excl(run, run["as_wins"])
    lines += [
        "## Deep preference",
        "",
        _deep_plain(run, markdown=True),
        "",
        (
            f"Deep preference is {run['as_rate_int']}% preferred "
            f"({run['as_wins']}/{run['n']}; {format_rate_detail(stat)}). "
            f"Excluding ties, that is {run['as_rate_excl_int']}% "
            f"({run['as_wins']}/{run['excl_ties']}; {format_rate_detail(excl)})."
        ),
        "",
        (
            f"{_judge_pin(run['judge_model'], run['reasoning_effort'], run['n'])}. "
            "`mode=deep` (optional richer mode)."
        ),
        "",
        f"Artifact: {_artifact_md(str(run['rel']), 'summary.json')}.",
        "",
        "These figures come from saved runs. Opening this page does not call OpenAI, You.com, or TypeSafe.",
        "",
    ]
    return lines


def _measured_html(
    run: dict[str, Any],
    snip: dict[str, Any] | None,
    top3: dict[str, Any] | None,
) -> str:
    """Collapsed lecture. Hero cards do not repeat these lines."""
    e = html.escape
    chunks = [
        '<details class="eval-measured">',
        "<summary>How we measured</summary>",
        f"<p>{published_honesty_html(run, snip)}</p>",
        f"<p>{e(WIN_RATE_NOTE)}</p>",
    ]
    if snip is None:
        chunks.append("<p>Snip preference is not validated by the deep table.</p>")
    else:
        stat = _of_n(snip, snip["as_wins"])
        chunks.append(
            "<p>"
            f"Snip preference is {snip['as_rate_int']}% preferred "
            f"({snip['as_wins']}/{snip['n']}; {e(format_rate_detail(stat))}). "
            f"{e(SNIP_HERO_MEANS)} "
            f"{e(_judge_pin(snip['judge_model'], snip['reasoning_effort'], snip['n']))}. "
            f"Artifact: {_artifact_html(str(snip['rel']), 'summary.json')}."
            "</p>"
        )
    if not top3:
        chunks.append(f"<p>{_top3_missing_html()}</p>")
    else:
        hits = int(top3["hits"])
        scored = int(top3["scored"])
        errors = int(top3["errors"])
        n = int(top3["n"])
        rel = str(top3.get("rel") or TOP3_REL)
        if scored <= 0:
            lead = (
                f"Published run has no scored queries ({hits}/{scored}, {errors} errors, n={n})."
            )
        else:
            stat = proportion_stat(hits, scored)
            lead = (
                f"Top-3 hit rate is {pct_int(hits, scored)}% "
                f"({hits}/{scored}; {e(format_rate_detail(stat))}). "
                f"Misses {int(top3['misses'])}. Errors {errors}. n={n}."
            )
        links = _artifact_html(rel, "summary.json")
        if top3.get("first_hit_ranks") is not None:
            links += " · " + _artifact_html(rel, "results.jsonl")
        pin = _judge_pin(
            str(top3.get("judge_model") or ""),
            str(top3.get("reasoning_effort") or ""),
            n,
        )
        chunks.append(
            f"<p>{lead} {e(pin)}. k={int(top3.get('k') or 3)}. {e(TOP3_HIT_MEANS)} "
            f"Artifact: {links}.</p>"
        )
    stat = _of_n(run, run["as_wins"])
    excl = _excl(run, run["as_wins"])
    chunks.append(f'<p class="eval-secondary eval-deep-line">{e(_deep_plain(run))}</p>')
    chunks.append(
        "<p>"
        f"Deep preference is {run['as_rate_int']}% preferred "
        f"({run['as_wins']}/{run['n']}; {e(format_rate_detail(stat))}). "
        f"Excluding ties, that is {run['as_rate_excl_int']}% "
        f"({run['as_wins']}/{run['excl_ties']}; {e(format_rate_detail(excl))}). "
        f"{e(_judge_pin(run['judge_model'], run['reasoning_effort'], run['n']))}. "
        "<code>mode=deep</code> (optional richer mode). "
        f"Artifact: {_artifact_html(str(run['rel']), 'summary.json', 'deep summary.json')}."
        "</p>"
    )
    chunks.append(
        "<p>These figures come from saved runs. "
        "Opening this page does not call OpenAI, You.com, or TypeSafe.</p>"
    )
    chunks.append("</details>")
    return "".join(chunks)


def _snip_hero_markdown(snip: dict[str, Any] | None, run: dict[str, Any]) -> list[str]:
    del run
    lines = ["## Snip preference", ""]
    if snip is None:
        lines += [
            "Snip preference is not validated by the deep table.",
            "",
        ]
        return lines
    lines += [
        f"**{snip['as_rate_int']}% preferred** ({snip['as_wins']}/{snip['n']}).",
        "",
        SNIP_GLOSS,
        "",
    ]
    lines += _outcome_rows_markdown(
        int(snip["as_wins"]),
        int(snip["ties"]),
        int(snip["baseline_wins"]),
        int(snip["n"]),
    )
    return lines


def _top3_hero_markdown(top3: dict[str, Any] | None) -> list[str]:
    lines = ["## Top-3 hit rate", ""]
    if not top3:
        lines += [
            "**not yet run**",
            "",
            "This check has not been published.",
            "",
        ]
        return lines
    hits = int(top3["hits"])
    scored = int(top3["scored"])
    rank_lines = _first_hit_markdown(top3.get("first_hit_ranks"))
    if scored <= 0:
        lines += ["This run has no scored questions.", ""]
    else:
        lines += [
            f"**{pct_int(hits, scored)}%** ({hits}/{scored}).",
            "",
            TOP3_GLOSS,
            "",
        ]
    if rank_lines:
        lines += rank_lines
    return lines


def _deep_secondary_markdown(run: dict[str, Any]) -> list[str]:
    return [
        "## Deep preference",
        "",
        _deep_plain(run, markdown=True),
        "",
    ]


def render_eval_v1_markdown(
    run: Any = _UNSET,
    snip: Any = _UNSET,
    doubles: Any = _UNSET,
    human: Any = _UNSET,
    top3: Any = _UNSET,
) -> str:
    run, snip, doubles, human, top3 = _v1_parts(run, snip, doubles, human, top3)
    n = _question_count(snip if isinstance(snip, dict) else None, run if isinstance(run, dict) else None)
    lines = [
        "---",
        "title: Agent Seek Eval",
        "canonical: /eval.md",
        "---",
        "",
        "# Agent Seek Eval",
        "",
    ]
    for paragraph in _intro_paragraphs(n):
        lines += [paragraph, ""]
    lines += _snip_hero_markdown(snip, run)
    lines += _top3_hero_markdown(top3)
    lines += _measured_markdown(run, snip, top3)
    lines += _diagnostics_markdown(doubles, human)
    certainty = JUDGE_CERTAINTY_NOTE_DUAL if snip is not None else JUDGE_CERTAINTY_NOTE
    lines += ["## Per-query", "", SUITE_BALANCE_NOTE, "", certainty, ""]
    if snip is not None:
        lines += [
            "| id | tier | query | deep | snip | Judge certainty |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        snip_by_id = {row.get("id"): row for row in snip["rows"]}
        for row in run["rows"]:
            deep_w = WINNER_LABEL.get(row.get("mapped_winner") or "", row.get("mapped_winner") or "")
            srow = snip_by_id.get(row.get("id")) or {}
            snip_w = WINNER_LABEL.get(srow.get("mapped_winner") or "", srow.get("mapped_winner") or "")
            q = (row.get("q") or "").replace("|", "/")
            cert = f"{_judge_certainty(row)} / {_judge_certainty(srow)}"
            lines.append(
                f"| {row.get('id')} | {row.get('tier')} | {q} | {deep_w} | {snip_w} | {cert} |"
            )
    else:
        lines += [
            "| id | tier | query | winner | Judge certainty |",
            "| --- | --- | --- | --- | ---: |",
        ]
        for row in run["rows"]:
            winner = WINNER_LABEL.get(row.get("mapped_winner") or "", row.get("mapped_winner") or "")
            q = (row.get("q") or "").replace("|", "/")
            lines.append(
                f"| {row.get('id')} | {row.get('tier')} | {q} | {winner} | {_judge_certainty(row)} |"
            )
    return "\n".join(lines)


def _top3_card_html(top3: dict[str, Any] | None) -> str:
    if not top3:
        return (
            '<article class="eval-hero" id="eval-hero-top3">'
            "<h2>Top-3 hit rate</h2>"
            '<p class="eval-score eval-pending">not yet run</p>'
            '<p class="eval-gloss">This check has not been published.</p>'
            "</article>"
        )
    hits = int(top3["hits"])
    scored = int(top3["scored"])
    rank_html = _first_hit_html(top3.get("first_hit_ranks"))
    if scored <= 0:
        score = (
            '<p class="eval-score eval-pending">no scored questions</p>'
            '<p class="eval-gloss">This run has no scored questions.</p>'
            f"{rank_html}"
        )
    else:
        score = (
            f'<p class="eval-score">{pct_int(hits, scored)}% '
            f'<span class="eval-score-n">{hits}/{scored}</span></p>'
            f'<p class="eval-gloss">{html.escape(TOP3_GLOSS)}</p>'
            f"{rank_html}"
        )
    return (
        '<article class="eval-hero" id="eval-hero-top3">'
        "<h2>Top-3 hit rate</h2>"
        f"{score}"
        "</article>"
    )


def _snip_card_html(snip: dict[str, Any] | None) -> str:
    if snip is None:
        return (
            '<article class="eval-hero" id="eval-hero-snip">'
            "<h2>Snip preference</h2>"
            '<p class="eval-score eval-pending">not validated</p>'
            '<p class="eval-gloss">Snip preference is not validated by the deep table.</p>'
            "</article>"
        )
    shade = rate_cell_class("as", snip["as_wins"], snip["baseline_wins"])
    shade_attr = f" {shade}" if shade else ""
    outcomes = _outcome_rows_html(
        int(snip["as_wins"]),
        int(snip["ties"]),
        int(snip["baseline_wins"]),
        int(snip["n"]),
    )
    return (
        f'<article class="eval-hero{shade_attr}" id="eval-hero-snip">'
        "<h2>Snip preference</h2>"
        f'<p class="eval-score">{snip["as_rate_int"]}% preferred '
        f'<span class="eval-score-n">{snip["as_wins"]}/{snip["n"]}</span></p>'
        f'<p class="eval-gloss">{html.escape(SNIP_GLOSS)}</p>'
        f"{outcomes}"
        "</article>"
    )


def _deep_line_html(run: dict[str, Any]) -> str:
    return f'<p class="eval-secondary eval-deep-line">{html.escape(_deep_plain(run))}</p>'


def _diagnostics_html(doubles: dict[str, Any], human: dict[str, Any] | None) -> str:
    e = html.escape
    chunks: list[str] = []
    side = doubles.get("snip")
    if side:
        url_note = ""
        if side.get("shortlist_text") == "url_only":
            url_note = (
                '<p class="eval-note">Shortlists in this pass were the published URLs '
                "(titles and snippets were not stored).</p>"
            )
        chunks.append(
            f'<p class="eval-flip">Snip (product default) flip rate {e(_flip_phrase(side))}.</p>{url_note}'
        )
    if human:
        labeled = int(human["labeled"])
        agree = int(human.get("agree") or 0)
        pct = 100.0 * float(human["agreement"])
        kappa = human.get("kappa")
        if not isinstance(kappa, (int, float)) or isinstance(kappa, bool):
            kappa_s = "undefined"
        else:
            kappa_s = f"{float(kappa):.3f}"
        chunks.append(
            f'<p class="eval-flip">Agreement {pct:.1f}% ({agree}/{labeled}). '
            f"Cohen's kappa {e(kappa_s)}.</p>"
            f'<p class="eval-note">{e(HUMAN_METHOD)}</p>'
        )
    if not chunks:
        return ""
    return (
        '<details class="eval-diagnostics">'
        "<summary>Diagnostics</summary>"
        + "".join(chunks)
        + "</details>"
    )


def _explore_html(run: dict[str, Any], snip: dict[str, Any] | None) -> str:
    certainty = JUDGE_CERTAINTY_NOTE_DUAL if snip is not None else JUDGE_CERTAINTY_NOTE
    if snip is not None:
        q_head = """
          <th>id</th>
          <th>tier</th>
          <th>query</th>
          <th>deep</th>
          <th>snip</th>
          <th class="eval-num">Judge certainty</th>
"""
    else:
        q_head = """
          <th>id</th>
          <th>tier</th>
          <th>query</th>
          <th>winner</th>
          <th class="eval-num">Judge certainty</th>
"""
    n = int(run["n"]) if run else 0
    summary = f"All {n} questions" if n else "Each question"
    return f"""
    <details class="eval-explore">
      <summary>{html.escape(summary)}</summary>
      <p class="eval-note">{html.escape(SUITE_BALANCE_NOTE)}</p>
      <p class="eval-note">Open a question to see the top five links and the reason for that pick. {html.escape(certainty)}</p>
      <div class="eval-scroll">
      <table class="eval-table eval-queries">
        <thead>
          <tr>
            {q_head}
          </tr>
        </thead>
        <tbody>
          {_query_rows_html(run, snip)}
        </tbody>
      </table>
      </div>
    </details>
"""


def render_eval_v1_body_html(
    run: Any = _UNSET,
    snip: Any = _UNSET,
    doubles: Any = _UNSET,
    human: Any = _UNSET,
    top3: Any = _UNSET,
) -> str:
    run, snip, doubles, human, top3 = _v1_parts(run, snip, doubles, human, top3)
    n = _question_count(snip if isinstance(snip, dict) else None, run if isinstance(run, dict) else None)
    return f"""
    <h1>Agent Seek Eval</h1>
    {_intro_html(n)}
    <div class="eval-heroes">
      {_snip_card_html(snip)}
      {_top3_card_html(top3)}
    </div>
    {_measured_html(run, snip, top3)}
    {_diagnostics_html(doubles, human)}
    {_explore_html(run, snip)}
"""


def _safe_published_dir(run_name: str) -> Path | None:
    if not run_name or "/" in run_name or run_name.startswith(".") or ".." in run_name:
        return None
    path = PUBLISHED_ROOT / run_name
    if path.is_dir() and (path / "summary.json").is_file():
        return path
    return None


def _eval_html_response(
    request: Request,
    *,
    title: str,
    body_html: str,
    canonical_path: str,
    description: str,
    body_class: str,
) -> HTMLResponse:
    return HTMLResponse(
        page_html(
            title,
            body_html,
            origin=origin_from(request),
            canonical_path=canonical_path,
            description=description,
            body_class=body_class,
            nav_current="eval",
        )
    )


def register_eval_page(app: FastAPI) -> None:
    v1_title = "Agent Seek Eval"
    v1_description = (
        "Fifty questions: whether Agent Seek's short list was preferred to "
        "You.com's order, and whether the known answer was in the top three."
    )

    @app.get("/eval", response_class=HTMLResponse, include_in_schema=False)
    async def eval_page(request: Request):
        if prefers_markdown(request):
            return markdown_response(render_eval_v1_markdown())
        return _eval_html_response(
            request,
            title=v1_title,
            body_html=render_eval_v1_body_html(),
            canonical_path="/eval",
            description=v1_description,
            body_class="eval-page eval-v1",
        )

    @app.get("/eval.md", include_in_schema=False)
    async def eval_md():
        return markdown_response(render_eval_v1_markdown())

    @app.get("/eval.html", include_in_schema=False)
    async def eval_html_alias():
        return RedirectResponse(url="/eval", status_code=308)

    @app.get("/eval/v0", include_in_schema=False)
    @app.get("/eval/v0.md", include_in_schema=False)
    @app.get("/eval-v0", include_in_schema=False)
    @app.get("/eval-v0.md", include_in_schema=False)
    async def eval_archive_redirect():
        return RedirectResponse(url="/eval", status_code=301)

    @app.get("/evals/public_v1/README.md", include_in_schema=False)
    async def suite_readme():
        return markdown_response(SUITE_README.read_text(encoding="utf-8"))

    @app.get("/evals/public_v1/judge/PROMPT_v1.md", include_in_schema=False)
    async def judge_prompt():
        return markdown_response(JUDGE_PROMPT.read_text(encoding="utf-8"))

    @app.get("/evals/public_v1/published/{run_name}/{name}", include_in_schema=False)
    async def published_file(run_name: str, name: str):
        if name not in PUBLISHED_FILE_TYPES:
            return HTMLResponse("Not found", status_code=404)
        path_dir = _safe_published_dir(run_name)
        if path_dir is None:
            return HTMLResponse("Not found", status_code=404)
        path = path_dir / name
        if not path.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(path, media_type=PUBLISHED_FILE_TYPES[name])
