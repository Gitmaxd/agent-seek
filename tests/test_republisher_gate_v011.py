"""v0.1.13 is_republisher hard gate — role-based, no domain blocklists."""
from __future__ import annotations

import json
from pathlib import Path

from packages.core.models import Candidate
from packages.core.rank.cascade import (
    REPUBLISHER_MIN,
    SUBJECT_MATCH_MIN,
    apply_republisher_gate,
    apply_subject_match_gate,
)
from packages.core.rank.jev import build_stage_b_questions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_is_republisher_question_role_based_no_domain_deny():
    for deep in (False, True):
        qs = build_stage_b_questions(["c0"], deep=deep)
        assert "c0__is_republisher" in qs
        q = qs["c0__is_republisher"]
        assert q["type"] == "noul"
        blob = (q["instructions"] + str(q["criteria"])).lower()
        assert "sotwe" not in blob
        assert "scraper" in blob or "mirror" in blob or "republisher" in blob
        assert "canonical" in blob or "original" in blob


def test_republisher_min_constant():
    assert REPUBLISHER_MIN == 0.55


def test_gate_drops_high_republisher_fail_open_missing():
    canon = Candidate(
        id="gh",
        url="https://github.com/gitmaxd",
        title="gitmaxd",
        snippet="profile",
        raw_rank=1,
    )
    mirror = Candidate(
        id="vw",
        url="https://example-x-viewer.test/GitMaxd",
        title="View tweets",
        snippet="unofficial profile viewer",
        raw_rank=2,
    )
    miss = Candidate(
        id="miss",
        url="https://example.com/x",
        title="x",
        snippet="x",
        raw_rank=3,
    )
    scored = [(canon, 0.7, []), (mirror, 0.95, []), (miss, 0.5, [])]
    out = apply_republisher_gate(scored, {"gh": 0.1, "vw": 0.9})
    assert [c.id for c, _, _ in out] == ["gh", "miss"]


def test_gate_keeps_just_below_threshold():
    c = Candidate(id="c", url="https://example.com", title="t", snippet="s", raw_rank=1)
    scored = [(c, 0.8, [])]
    assert len(apply_republisher_gate(scored, {"c": REPUBLISHER_MIN - 0.01})) == 1
    assert len(apply_republisher_gate(scored, {"c": REPUBLISHER_MIN})) == 0


def test_fixture_viewer_mirrors_filtered_canonicals_kept():
    data = json.loads((FIXTURES / "republisher_gate_gitmaxd.json").read_text())
    assert data["query"] == "Who is gitmaxd"
    scored = []
    subject_match: dict[str, float] = {}
    is_republisher: dict[str, float] = {}
    for row in data["candidates"]:
        c = Candidate(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            snippet=row["snippet"],
            raw_rank=row["raw_rank"],
        )
        # Mirrors can score high on answerability — gate must still drop them
        scored.append((c, 0.9 if "viewer" in row["id"] or "seo" in row["id"] else 0.7, ["on_topic"]))
        if row["subject_match"] is not None:
            subject_match[row["id"]] = float(row["subject_match"])
        if row["is_republisher"] is not None:
            is_republisher[row["id"]] = float(row["is_republisher"])

    # Product path: subject_match then republisher
    gated = apply_subject_match_gate(scored, subject_match)
    gated = apply_republisher_gate(gated, is_republisher)
    kept = {c.id for c, _, _ in gated}

    for row in data["candidates"]:
        if row["expect_in_results"]:
            assert row["id"] in kept, row["id"]
        else:
            assert row["id"] not in kept, row["id"]

    assert "viewer_mirror" not in kept
    assert "seo_copy" not in kept
    assert "gh_user" in kept
    assert "x_canon" in kept
    assert "parse_miss" in kept  # fail-open

    # No product blocklist of real scraper hosts in cascade module
    cascade_src = (Path(__file__).resolve().parents[1] / "packages/core/rank/cascade.py").read_text()
    jev_src = (Path(__file__).resolve().parents[1] / "packages/core/rank/jev.py").read_text()
    assert "sotwe.com" not in cascade_src.lower()
    assert "sotwe.com" not in jev_src.lower()


def test_gate_order_subject_then_republisher():
    """Wrong entity drops first; right-entity mirror drops second."""
    wrong = Candidate(
        id="gitmax_co",
        url="https://www.gitmax.com/",
        title="GitMax",
        snippet="company",
        raw_rank=1,
    )
    mirror = Candidate(
        id="viewer",
        url="https://example-x-viewer.test/u/GitMaxd",
        title="Tweets viewer",
        snippet="unofficial X profile viewer",
        raw_rank=2,
    )
    good = Candidate(
        id="gh",
        url="https://github.com/gitmaxd",
        title="gitmaxd",
        snippet="GitHub",
        raw_rank=3,
    )
    scored = [(wrong, 0.4, []), (mirror, 0.9, []), (good, 0.8, [])]
    after_sm = apply_subject_match_gate(
        scored, {"gitmax_co": 0.1, "viewer": 0.9, "gh": 0.95}
    )
    assert [c.id for c, _, _ in after_sm] == ["viewer", "gh"]
    after_rp = apply_republisher_gate(after_sm, {"viewer": 0.88, "gh": 0.05})
    assert [c.id for c, _, _ in after_rp] == ["gh"]
