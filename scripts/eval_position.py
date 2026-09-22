"""Position-bias double judge and blind human-packet math.

No network. The live OpenAI calls stay in ``scripts/eval_llm_judge.py``.

Definitions (locked):

* **Original order.** Shortlists are labeled A and B with the published
  run's ``assignment``. The judge sees titles, URLs, and snippets when we
  have them, otherwise the published URLs. It never sees arm names.
* **Swapped order.** The same two shortlists with the labels exchanged:
  the list that was A is shown as B, and the list that was B is shown as A.
  ``assignment`` is inverted so a raw A/B/tie still maps back to
  ``agent_seek`` | ``baseline`` | ``tie``.
* **Agree.** Both passes returned a verdict and the mapped arms are equal.
  Two ties agree. A tie and a side do not.
* **Flip.** Both passes returned a verdict and the mapped arms differ.
  That includes tie versus a side. Flip rate = flips / pairs with both
  verdicts. A raw label change that still maps to the same arm is not a
  flip (that is what a consistent judge does when the sides swap).
* **Incomplete.** Either pass is missing or errored. Not an agree and not
  a flip. Left out of the flip rate and out of the agreeing W/T/L.
* **Agreeing-only W/T/L.** The hardened preference counts. Only agreeing
  pairs contribute. The shared mapped arm is the win, the loss, or the tie.
  Of-n rate = agent_seek wins / agreeing pairs, and agreeing ties count as
  non-wins. Excl.-ties drops those ties. Disagreeing pairs are flips and
  are not in this W/T/L.
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
from pathlib import Path
from typing import Any

ARMS = ("agent_seek", "baseline")
LABELS = ("A", "B", "tie")
MAPPED = ("agent_seek", "baseline", "tie")

# Blind human sample of the snip published run. 30 is the top of the
# requested 25–30 band. Seed is fixed so the packet does not drift.
HUMAN_SAMPLE_N = 30
HUMAN_SAMPLE_SEED = 20260921

DEFINITIONS = {
    "flip_rate": (
        "flips / both_verdicts. A flip is a pair where both passes returned "
        "a verdict and the mapped arms differ, including a tie against a side. "
        "A raw A/B label change that maps to the same arm is not a flip."
    ),
    "agreeing_wtl": (
        "agent_seek_wins, baseline_wins, and ties count only pairs whose two "
        "mapped arms are equal. Of-n preference is agent_seek_wins / agreeing, "
        "and agreeing ties count as non-wins. Excl.-ties uses agreeing - ties."
    ),
    "incomplete": (
        "A pair with a missing or errored pass is neither an agree nor a flip. "
        "It is excluded from flip_rate and from the agreeing W/T/L."
    ),
    "blinding": (
        "The judge and the human packet see list A and list B only. "
        "assignment maps those labels to baseline | agent_seek and is stored "
        "in run output, not sent to the judge."
    ),
    "tie_handling": (
        "Both passes map to tie: agree, count as a tie. One pass maps to tie "
        "and the other to a side: flip, omit from agreeing W/T/L."
    ),
}


def invert_assignment(assignment: dict[str, str]) -> dict[str, str]:
    """Exchange which arm is shown as A vs B. Labels stay A and B."""
    if set(assignment) != {"A", "B"}:
        raise ValueError(f"assignment must map A and B, got {assignment!r}")
    return {"A": assignment["B"], "B": assignment["A"]}


def map_winner(winner: str, assignment: dict[str, str]) -> str:
    """Map a blind A/B/tie onto agent_seek | baseline | tie."""
    if winner == "tie":
        return "tie"
    if winner not in assignment:
        raise ValueError(f"unknown winner {winner!r}")
    return assignment[winner]


def _arm_items(
    assignment: dict[str, str],
    label: str,
    baseline: list[dict[str, Any]],
    treatment: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    arm = assignment[label]
    if arm == "baseline":
        return baseline
    if arm == "agent_seek":
        return treatment
    raise ValueError(f"assignment[{label}] is {arm!r}, expected an arm name")


def presentations(
    assignment: dict[str, str],
    baseline: list[dict[str, Any]],
    treatment: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Original published labeling, and the same shortlists with sides flipped.

    Swapped list A is original list B. Swapped assignment is the inverse,
    so mapping the swapped verdict recovers the same arm when the judge
    follows the content instead of the label.
    """
    swapped = invert_assignment(assignment)
    return {
        "original": {
            "order": "original",
            "assignment": dict(assignment),
            "A": _arm_items(assignment, "A", baseline, treatment),
            "B": _arm_items(assignment, "B", baseline, treatment),
        },
        "swapped": {
            "order": "swapped",
            "assignment": swapped,
            "A": _arm_items(swapped, "A", baseline, treatment),
            "B": _arm_items(swapped, "B", baseline, treatment),
        },
    }


def classify_pair(
    mapped_original: str | None,
    mapped_swapped: str | None,
) -> dict[str, Any]:
    """Agree, flip, or incomplete. See module docstring for tie handling."""
    if mapped_original not in MAPPED or mapped_swapped not in MAPPED:
        return {
            "status": "incomplete",
            "agree": False,
            "flip": False,
            "hardened": None,
        }
    if mapped_original == mapped_swapped:
        return {
            "status": "agree",
            "agree": True,
            "flip": False,
            "hardened": mapped_original,
        }
    return {"status": "flip", "agree": False, "flip": True, "hardened": None}


def summarize_double(
    rows: list[dict[str, Any]],
    *,
    suite_id: str,
    mode: str,
) -> dict[str, Any]:
    """Agreeing-only W/T/L plus flip rate. Counts, not a live API result."""
    as_wins = base_wins = ties = flips = errors = 0
    for row in rows:
        outcome = classify_pair(row.get("mapped_original"), row.get("mapped_swapped"))
        if outcome["status"] == "incomplete":
            errors += 1
            continue
        if outcome["flip"]:
            flips += 1
            continue
        hardened = outcome["hardened"]
        if hardened == "agent_seek":
            as_wins += 1
        elif hardened == "baseline":
            base_wins += 1
        elif hardened == "tie":
            ties += 1
    agreeing = as_wins + base_wins + ties
    both = agreeing + flips
    n = len(rows)
    if agreeing + flips + errors != n:
        raise RuntimeError("double-judge summary did not partition the rows")
    return {
        "suite_id": suite_id,
        "kind": "double_judge",
        "mode": mode,
        "n": n,
        "both_verdicts": both,
        "errors": errors,
        "agreeing": agreeing,
        "flips": flips,
        "flip_rate": (flips / both) if both else None,
        "agent_seek_wins": as_wins,
        "baseline_wins": base_wins,
        "ties": ties,
        "judged": agreeing,
        "definitions": DEFINITIONS,
    }


def coerce_items(value: Any) -> list[dict[str, Any]] | None:
    """Normalize a URL list or a list of {url, title, snippet} dicts."""
    if not isinstance(value, list) or not value:
        return None
    items: list[dict[str, Any]] = []
    for i, raw in enumerate(value, 1):
        if isinstance(raw, str):
            url = raw.strip()
            if not url:
                continue
            items.append({"rank": i, "url": url, "title": "", "snippet": ""})
            continue
        if isinstance(raw, dict):
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            try:
                rank = int(raw.get("rank") or i)
            except (TypeError, ValueError):
                rank = i
            items.append(
                {
                    "rank": rank,
                    "url": url,
                    "title": str(raw.get("title") or ""),
                    "snippet": str(raw.get("snippet") or ""),
                }
            )
    return items or None


def shortlists_from_row(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Baseline and treatment shortlists from a published per_query row.

    Rich item lists win over bare URL lists. Published v1 rows store URLs
    only; title and snippet stay empty unless a pools file fills them.
    """
    baseline = (
        coerce_items(row.get("baseline"))
        or coerce_items(row.get("baseline_items"))
        or coerce_items(row.get("baseline_urls"))
    )
    treatment = (
        coerce_items(row.get("treatment"))
        or coerce_items(row.get("treatment_items"))
        or coerce_items(row.get("treatment_urls"))
    )
    if not baseline or not treatment:
        raise ValueError(f"{row.get('id')}: missing baseline or treatment shortlist")
    return baseline, treatment


def shortlist_text_kind(items: list[dict[str, Any]]) -> str:
    if any((it.get("title") or it.get("snippet")) for it in items):
        return "title_snippet"
    return "url_only"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def load_pool_index(path: Path) -> dict[str, dict[str, dict[str, str]]]:
    """pools.jsonl → {query_id: {url: {title, snippet}}}.

    Does not discover or re-rank. Unknown URLs are left blank.
    A candidate whose ``fetch`` is set and is not ``ok`` contributes an
    empty title and snippet so a block page or HTTP error is not graded
    as the document. The enrichment JSONL still records that failure.
    """
    index: dict[str, dict[str, dict[str, str]]] = {}
    for rec in load_jsonl(path):
        qid = str(rec.get("id") or "")
        candidates = rec.get("candidates") or rec.get("pool") or []
        if not qid or not isinstance(candidates, list):
            continue
        by_url = index.setdefault(qid, {})
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            url = str(cand.get("url") or "").strip()
            if not url:
                continue
            # Enrichment rows set ``fetch``. An error-page title (a block
            # page, a PDF with no HTML title) is not the document. Older
            # pools omit ``fetch`` and are copied as stored.
            fetch = cand.get("fetch")
            if fetch not in (None, "", "ok"):
                by_url[url] = {"title": "", "snippet": ""}
                continue
            by_url[url] = {
                "title": str(cand.get("title") or ""),
                "snippet": str(cand.get("snippet") or ""),
            }
    return index


def enrich_items(
    items: list[dict[str, Any]],
    by_url: dict[str, dict[str, str]],
) -> None:
    for it in items:
        src = by_url.get(it["url"])
        if not src:
            continue
        if not it.get("title") and src.get("title"):
            it["title"] = src["title"]
        if not it.get("snippet") and src.get("snippet"):
            it["snippet"] = src["snippet"]


def load_published_dir(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_query = path / "per_query.jsonl"
    meta_path = path / "run_meta.json"
    if not per_query.is_file():
        raise FileNotFoundError(f"{path} has no per_query.jsonl")
    rows = load_jsonl(per_query)
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            meta = loaded
    return rows, meta


def prepare_query(
    row: dict[str, Any],
    *,
    pool_index: dict[str, dict[str, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """One published query → original and swapped shortlists.

    Requires the published assignment. Does not call You.com or TypeSafe.
    """
    assignment = row.get("assignment")
    if not isinstance(assignment, dict):
        raise ValueError(f"{row.get('id')}: missing assignment")
    baseline, treatment = shortlists_from_row(row)
    qid = str(row.get("id") or "")
    if pool_index and qid in pool_index:
        enrich_items(baseline, pool_index[qid])
        enrich_items(treatment, pool_index[qid])
    shows = presentations(assignment, baseline, treatment)
    kind = shortlist_text_kind(baseline + treatment)
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    return {
        "id": qid,
        "q": row.get("q") or "",
        "tier": row.get("tier"),
        "intent": row.get("intent"),
        "baseline": baseline,
        "treatment": treatment,
        "shortlist_text": kind,
        "original": shows["original"],
        "swapped": shows["swapped"],
        "published_winner": judge.get("winner"),
        "published_mapped_winner": row.get("mapped_winner"),
    }


def allocate_quotas(counts: dict[str, int], n: int) -> dict[str, int]:
    """Largest-remainder allocation. Quotas sum to min(n, total) and never
    exceed the stratum size.

    Remainder ties break toward the larger stratum, then the name.
    """
    usable = {k: int(v) for k, v in counts.items() if int(v) > 0}
    total = sum(usable.values())
    if n < 0:
        raise ValueError("n must be >= 0")
    if total == 0 or n == 0:
        return {k: 0 for k in counts}
    target = min(n, total)
    raw = {k: target * usable[k] / total for k in usable}
    floors = {k: min(int(math.floor(raw[k])), usable[k]) for k in usable}
    left = target - sum(floors.values())
    order = sorted(
        usable,
        key=lambda k: (-(raw[k] - math.floor(raw[k])), -usable[k], k),
    )
    idx = 0
    guard = 0
    limit = target * max(len(order), 1) + 5
    while left > 0 and guard < limit:
        key = order[idx % len(order)]
        if floors[key] < usable[key]:
            floors[key] += 1
            left -= 1
        idx += 1
        guard += 1
    if left:
        raise RuntimeError("could not allocate human-sample quotas")
    return {k: floors.get(k, 0) for k in counts}


def stratified_sample(
    rows: list[dict[str, Any]],
    *,
    n: int = HUMAN_SAMPLE_N,
    seed: int = HUMAN_SAMPLE_SEED,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Sample ``n`` rows stratified by ``mapped_winner``.

    Within a stratum, ``random.Random(seed)`` draws from ids sorted
    lexicographically. The returned rows are sorted by id so the packet
    order does not depend on draw order. One shared RNG, strata visited
    in sorted arm-name order (``agent_seek``, ``baseline``, ``tie``).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        arm = row.get("mapped_winner")
        if arm not in MAPPED:
            continue
        groups.setdefault(str(arm), []).append(row)
    counts = {arm: len(groups.get(arm, [])) for arm in MAPPED}
    quotas = allocate_quotas(counts, n)
    rng = random.Random(seed)
    chosen: set[str] = set()
    for arm in MAPPED:
        pool = sorted(groups.get(arm, []), key=lambda r: str(r.get("id") or ""))
        quota = quotas.get(arm, 0)
        if quota <= 0 or not pool:
            continue
        if quota >= len(pool):
            picked = pool
        else:
            picked = rng.sample(pool, quota)
        for row in picked:
            chosen.add(str(row.get("id") or ""))
    selected = [r for r in rows if str(r.get("id") or "") in chosen]
    selected.sort(key=lambda r: str(r.get("id") or ""))
    return selected, quotas


def build_human_packet(
    rows: list[dict[str, Any]],
    *,
    n: int = HUMAN_SAMPLE_N,
    seed: int = HUMAN_SAMPLE_SEED,
    pool_index: dict[str, dict[str, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Blind packet plus a scoring key. The packet has no arm names."""
    selected, quotas = stratified_sample(rows, n=n, seed=seed)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    kinds: set[str] = set()
    for i, row in enumerate(selected, 1):
        prepared = prepare_query(row, pool_index=pool_index)
        kinds.add(prepared["shortlist_text"])
        original = prepared["original"]
        packet.append(
            {
                "item": i,
                "id": prepared["id"],
                "tier": prepared["tier"],
                "q": prepared["q"],
                "list_a": original["A"],
                "list_b": original["B"],
                "human": "",
                "note": "",
            }
        )
        key.append(
            {
                "id": prepared["id"],
                "judge_winner": prepared["published_winner"],
                "assignment": original["assignment"],
                "mapped_winner": prepared["published_mapped_winner"],
            }
        )
    if len(kinds) == 1:
        text_kind = next(iter(kinds))
    elif not kinds:
        text_kind = "url_only"
    else:
        text_kind = "mixed"
    return {
        "packet": packet,
        "key": key,
        "n": len(packet),
        "seed": seed,
        "quotas": quotas,
        "shortlist_text": text_kind,
    }


def render_packet_markdown(packet: list[dict[str, Any]]) -> str:
    """Checklist a person can fill. No arm names, no judge verdicts."""
    lines = [
        "# Human grading packet",
        "",
        "Pick which shortlist is more useful for the query. Write **A**, **B**, or **tie**.",
        "An optional note can sit under the pick. These lists are unlabeled on purpose.",
        "Leave the scoring key closed until every item has a pick.",
        "",
        f"Items: {len(packet)}.",
        "",
    ]
    for item in packet:
        lines.append(f"## {item['item']}. {item['id']}")
        lines.append("")
        lines.append(f"Query: {item.get('q') or ''}")
        lines.append("")
        lines.append(_format_blind_list("A", item.get("list_a") or []))
        lines.append("")
        lines.append(_format_blind_list("B", item.get("list_b") or []))
        lines.append("")
        lines.append("Human pick (A / B / tie):")
        lines.append("")
        lines.append("Note:")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_blind_list(label: str, items: list[dict[str, Any]]) -> str:
    lines = [f"### List {label}"]
    if not items:
        lines.append("(empty)")
        return "\n".join(lines)
    for it in items:
        title = (it.get("title") or "").strip()
        url = it.get("url") or ""
        snippet = " ".join(str(it.get("snippet") or "").split())
        head = title or url
        lines.append(f"{it.get('rank')}. {head}")
        if title and url:
            lines.append(f"   {url}")
        elif not title:
            pass
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def render_packet_csv(packet: list[dict[str, Any]]) -> str:
    """Spreadsheet checklist. Shortlists live in the markdown and JSONL."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=("item", "id", "tier", "q", "human", "note"),
        lineterminator="\n",
    )
    writer.writeheader()
    for item in packet:
        writer.writerow(
            {
                "item": item.get("item"),
                "id": item.get("id"),
                "tier": item.get("tier") or "",
                "q": item.get("q") or "",
                "human": item.get("human") or "",
                "note": item.get("note") or "",
            }
        )
    return buf.getvalue()


def cohens_kappa(
    left: list[str],
    right: list[str],
    *,
    categories: tuple[str, ...] = LABELS,
) -> dict[str, Any]:
    """Cohen's kappa for paired labels.

    ``p_e == 1`` and perfect agreement returns kappa 1. ``p_e == 1`` with
    any disagreement returns kappa ``None`` (undefined), not zero.
    """
    if len(left) != len(right):
        raise ValueError("label lists differ in length")
    n = len(left)
    if n == 0:
        raise ValueError("no labeled pairs")
    allowed = set(categories)
    for label in left + right:
        if label not in allowed:
            raise ValueError(f"label {label!r} is outside {categories}")
    agree = sum(a == b for a, b in zip(left, right))
    p_o = agree / n
    p_e = 0.0
    marginals: dict[str, dict[str, int]] = {}
    for cat in categories:
        n_left = sum(x == cat for x in left)
        n_right = sum(x == cat for x in right)
        marginals[cat] = {"left": n_left, "right": n_right}
        p_e += (n_left / n) * (n_right / n)
    if p_e == 1.0:
        kappa: float | None = 1.0 if p_o == 1.0 else None
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)
    return {
        "n": n,
        "agree": agree,
        "agreement": p_o,
        "p_e": p_e,
        "kappa": kappa,
        "categories": list(categories),
        "marginals": marginals,
    }


def _normalize_human_label(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in {"", "null", "none"}:
        return None
    if text in {"a", "b"}:
        return text.upper()
    if text == "tie":
        return "tie"
    raise ValueError(f"human pick must be A, B, or tie, got {raw!r}")


def score_human_labels(
    packet: list[dict[str, Any]],
    published_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Raw agreement and Cohen's kappa: human A/B/tie vs the published judge.

    Blank picks are unlabeled and excluded. The comparison uses the blind
    labels on the same lists, then maps both through the published
    assignment for a human W/T/L. Refuses to invent a rate when nothing
    is labeled.
    """
    human_labels: list[str] = []
    judge_labels: list[str] = []
    human_mapped = {"agent_seek": 0, "baseline": 0, "tie": 0}
    judge_mapped = {"agent_seek": 0, "baseline": 0, "tie": 0}
    unlabeled = 0
    for item in packet:
        human = _normalize_human_label(item.get("human"))
        if human is None:
            unlabeled += 1
            continue
        qid = str(item.get("id") or "")
        row = published_by_id.get(qid)
        if row is None:
            raise ValueError(f"no published row for {qid}")
        judge = (row.get("judge") or {}).get("winner")
        if judge not in LABELS:
            raise ValueError(f"{qid}: published judge winner missing")
        assignment = row.get("assignment")
        if not isinstance(assignment, dict):
            raise ValueError(f"{qid}: published assignment missing")
        human_labels.append(human)
        judge_labels.append(str(judge))
        human_mapped[map_winner(human, assignment)] += 1
        judge_mapped[map_winner(str(judge), assignment)] += 1
    if not human_labels:
        raise ValueError("no human labels — refusing to write an agreement")
    stats = cohens_kappa(human_labels, judge_labels)
    return {
        "kind": "human_agreement",
        "packet_n": len(packet),
        "labeled": stats["n"],
        "unlabeled": unlabeled,
        "agree": stats["agree"],
        "agreement": stats["agreement"],
        "p_e": stats["p_e"],
        "kappa": stats["kappa"],
        "categories": stats["categories"],
        "human_mapped": human_mapped,
        "judge_mapped": judge_mapped,
        "comparison": (
            "human A/B/tie vs the published judge winner on the same blind lists"
        ),
    }


def published_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in rows if row.get("id")}
