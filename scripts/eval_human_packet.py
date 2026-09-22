#!/usr/bin/env python3
"""Blind human grading packet and Cohen's kappa for public_v1 snip.

Does not call You.com, TypeSafe, or OpenAI. Does not invent agreement.

  python scripts/eval_human_packet.py sample
  python scripts/eval_human_packet.py score --labels path/to/filled.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_position as pos

DEFAULT_PUBLISHED = ROOT / "evals" / "public_v1" / "published" / "v1.0.0-snip"
DEFAULT_OUT = ROOT / "evals" / "public_v1" / "human_v1"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def cmd_sample(args: argparse.Namespace) -> int:
    rows, _meta = pos.load_published_dir(args.from_published)
    pool_index = pos.load_pool_index(args.pools) if args.pools else None
    built = pos.build_human_packet(
        rows,
        n=args.n,
        seed=args.seed,
        pool_index=pool_index,
    )
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "packet.jsonl", built["packet"])
    _write_jsonl(out / "key.jsonl", built["key"])
    (out / "packet.md").write_text(
        pos.render_packet_markdown(built["packet"]), encoding="utf-8"
    )
    (out / "packet.csv").write_text(
        pos.render_packet_csv(built["packet"]), encoding="utf-8"
    )
    meta = {
        "n": built["n"],
        "seed": built["seed"],
        "source": _rel(args.from_published),
        "quotas": built["quotas"],
        "shortlist_text": built["shortlist_text"],
        "order": "stratified by published mapped_winner, listed by query id",
        "note": (
            "Quotas are sample sizes per published outcome. They are not "
            "per-item labels. packet.md / packet.jsonl / packet.csv omit arm names."
        ),
    }
    if args.pools:
        meta["pools"] = _rel(args.pools)
        meta["enrichment"] = (
            "Titles and snippets are copied from pools by exact URL. "
            "This sampler does not rediscover."
        )
    (out / "sample_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {built['n']} blind items to {out} "
        f"(seed={built['seed']}, shortlists={built['shortlist_text']})."
    )
    print("Human picks are blank. No agreement was computed.")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    packet = pos.load_jsonl(args.labels)
    rows, _meta = pos.load_published_dir(args.from_published)
    try:
        summary = pos.score_human_labels(packet, pos.published_index(rows))
    except ValueError as e:
        print(f"score refused: {e}", file=sys.stderr)
        return 2
    summary["source_published"] = str(args.from_published)
    summary["source_labels"] = str(args.labels)
    text = json.dumps(summary, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text, end="")
    kappa = summary["kappa"]
    kappa_s = "undefined" if kappa is None else f"{kappa:.3f}"
    print(
        f"Agreement {summary['agree']}/{summary['labeled']} "
        f"({100.0 * summary['agreement']:.1f}%)  kappa={kappa_s}",
        file=sys.stderr if args.out else sys.stdout,
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sample = sub.add_parser("sample", help="Write a blind 25–30 item packet")
    sample.add_argument("--from-published", type=Path, default=DEFAULT_PUBLISHED)
    sample.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    sample.add_argument("--n", type=int, default=pos.HUMAN_SAMPLE_N)
    sample.add_argument("--seed", type=int, default=pos.HUMAN_SAMPLE_SEED)
    sample.add_argument(
        "--pools",
        type=Path,
        default=None,
        help="Optional pools.jsonl to attach title/snippet. Does not rediscover.",
    )
    sample.set_defaults(func=cmd_sample)

    score = sub.add_parser("score", help="Agreement and Cohen's kappa from filled labels")
    score.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="Filled packet JSONL with human set to A, B, or tie",
    )
    score.add_argument("--from-published", type=Path, default=DEFAULT_PUBLISHED)
    score.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write summary JSON (omit to print only). /eval reads human_v1/summary.json",
    )
    score.set_defaults(func=cmd_score)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cmd == "sample" and not (25 <= args.n <= 30):
        print(
            f"warning: n={args.n} is outside the 25–30 band the review asked for",
            file=sys.stderr,
        )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
