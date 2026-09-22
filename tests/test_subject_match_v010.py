"""v0.1.13 subject_match hard gate — gitmaxd vs GitMax lookalikes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.models import Candidate
from packages.core.rank.cascade import SUBJECT_MATCH_MIN, apply_subject_match_gate
from packages.core.rank.jev import build_stage_b_questions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_subject_match_question_present_snip_and_deep():
    for deep in (False, True):
        qs = build_stage_b_questions(["c0"], deep=deep)
        assert "c0__subject_match" in qs
        assert qs["c0__subject_match"]["type"] == "noul"
        assert "c0__on_topic" in qs  # soft flag still present
        instr = qs["c0__subject_match"]["instructions"]
        assert "same" in instr.lower() or "**same**" in instr
        assert "near-homonym" in qs["c0__subject_match"]["criteria"]["false"]
        if deep:
            assert "page text" in instr
        else:
            assert "snippet" in instr


def test_subject_match_min_constant():
    assert SUBJECT_MATCH_MIN == 0.55


def test_gate_drops_below_min_fail_open_missing():
    keep = Candidate(
        id="ok",
        url="https://github.com/gitmaxd",
        title="gitmaxd",
        snippet="profile",
        raw_rank=1,
    )
    drop = Candidate(
        id="bad",
        url="https://www.gitmax.com/",
        title="GitMax",
        snippet="company",
        raw_rank=2,
    )
    miss = Candidate(
        id="miss",
        url="https://example.com/x",
        title="x",
        snippet="x",
        raw_rank=3,
    )
    scored = [(keep, 0.9, ["on_topic"]), (drop, 0.42, ["on_topic"]), (miss, 0.5, [])]
    out = apply_subject_match_gate(scored, {"ok": 0.9, "bad": 0.2})
    assert [c.id for c, _, _ in out] == ["ok", "miss"]


def test_gate_keeps_at_threshold():
    c = Candidate(id="c", url="https://example.com", title="t", snippet="s", raw_rank=1)
    scored = [(c, 0.7, [])]
    assert len(apply_subject_match_gate(scored, {"c": SUBJECT_MATCH_MIN})) == 1
    assert len(apply_subject_match_gate(scored, {"c": SUBJECT_MATCH_MIN - 0.01})) == 0


def test_gitmaxd_fixture_lookalikes_filtered():
    data = json.loads((FIXTURES / "subject_match_gitmaxd.json").read_text())
    assert data["query"] == "Who is gitmaxd"
    scored = []
    subject_match: dict[str, float] = {}
    for row in data["candidates"]:
        c = Candidate(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            snippet=row["snippet"],
            raw_rank=row["raw_rank"],
        )
        scored.append((c, 0.45, ["on_topic"]))  # lookalikes can look "on_topic"
        if row["subject_match"] is not None:
            subject_match[row["id"]] = float(row["subject_match"])

    gated = apply_subject_match_gate(scored, subject_match)
    kept_ids = {c.id for c, _, _ in gated}
    for row in data["candidates"]:
        if row["expect_in_results"]:
            assert row["id"] in kept_ids, row["id"]
        else:
            assert row["id"] not in kept_ids, row["id"]

    # Wrong-entity company pages must not ship
    assert "cbi" not in kept_ids
    assert "corp" not in kept_ids
    assert "clutch" not in kept_ids
    # Real gitmaxd surfaces
    assert "gh_user" in kept_ids
    assert "gh_repo" in kept_ids
    # Fail-open on missing parse
    assert "parse_miss" in kept_ids

    # raw discover set length unchanged (gate only affects exposure list)
    assert len(scored) == len(data["candidates"])
