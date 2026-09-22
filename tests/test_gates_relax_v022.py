"""v0.1.22 — restore pre-gate ranking when hard gates empty the result set."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from packages.core.models import Candidate, RankedResult
from packages.core.rank.cascade import (
    apply_prompt_injection_gate,
    apply_republisher_gate,
    apply_subject_match_gate,
    cascade_rank,
    restore_pre_gate_if_empty,
)
from packages.core.rank.jev import JevClient


def _cand(cid: str, url: str, rank: int) -> Candidate:
    return Candidate(
        id=cid,
        url=url,
        title=cid,
        snippet=f"snippet for {cid}",
        raw_rank=rank,
    )


def test_restore_pre_gate_when_subject_match_empties():
    """Gates drop everyone → restore yields pre-gate list + gates_relaxed."""
    a = _cand("a", "https://contextrepo.example/", 1)
    b = _cand("b", "https://example.com/other", 2)
    pre_gate = [(a, 0.91, ["on_topic"]), (b, 0.72, [])]
    scored = apply_subject_match_gate(list(pre_gate), {"a": 0.1, "b": 0.05})
    assert scored == []
    scored = apply_republisher_gate(scored, {})
    scored = apply_prompt_injection_gate(scored, {})
    assert scored == []
    extras: dict = {}
    scored = restore_pre_gate_if_empty(scored, pre_gate, extras)
    assert len(scored) >= 1
    assert [c.id for c, _, _ in scored] == ["a", "b"]
    assert scored[0][1] == 0.91  # pre-gate scores preserved
    assert extras["gates_relaxed"] == "empty_after_hard_gates"


def test_restore_pre_gate_when_republisher_empties():
    a = _cand("a", "https://mirror.example/x", 1)
    pre_gate = [(a, 0.88, [])]
    scored = apply_subject_match_gate(list(pre_gate), {"a": 0.95})  # passes subject
    scored = apply_republisher_gate(scored, {"a": 0.9})  # dropped as republisher
    scored = apply_prompt_injection_gate(scored, {})
    assert scored == []
    extras: dict = {}
    scored = restore_pre_gate_if_empty(scored, pre_gate, extras)
    assert len(scored) == 1
    assert scored[0][0].id == "a"
    assert scored[0][1] == 0.88
    assert extras["gates_relaxed"] == "empty_after_hard_gates"


def test_restore_noop_when_gates_keep_some():
    a = _cand("a", "https://ok.example/", 1)
    b = _cand("b", "https://bad.example/", 2)
    pre_gate = [(a, 0.9, []), (b, 0.8, [])]
    scored = apply_subject_match_gate(list(pre_gate), {"a": 0.9, "b": 0.1})
    assert [c.id for c, _, _ in scored] == ["a"]
    extras: dict = {}
    scored = restore_pre_gate_if_empty(scored, pre_gate, extras)
    assert [c.id for c, _, _ in scored] == ["a"]
    assert "gates_relaxed" not in extras


def test_restore_noop_when_pre_gate_empty():
    extras: dict = {}
    scored = restore_pre_gate_if_empty([], [], extras)
    assert scored == []
    assert "gates_relaxed" not in extras


@pytest.mark.asyncio
async def test_cascade_returns_pre_gate_when_hard_gates_empty_all():
    """Full cascade_rank: all subject_match below min → still ≥1 RankedResult."""
    cands = [
        _cand("c0", "https://contextrepo.example/", 1),
        _cand("c1", "https://example.com/noise", 2),
    ]

    def noul(v: float) -> dict:
        return {"type": "noul", "noul": v}

    def score(v: float) -> dict:
        # parse_score_01: score / 4 → [0,1]; use 4 for ~1.0
        return {"type": "score", "score": v}

    async def fake_eval(state, questions):
        out = {}
        for qid in questions:
            if qid.endswith("__possibly_relevant"):
                out[qid] = noul(0.95)
            elif qid.endswith("__likely_spam"):
                out[qid] = noul(0.05)
            elif qid.endswith("__answerability"):
                out[qid] = score(4)
            elif qid.endswith("__authority"):
                out[qid] = noul(0.8)
            elif qid.endswith("__on_topic"):
                out[qid] = noul(0.9)
            elif qid.endswith("__states_sought_fact"):
                out[qid] = noul(0.7)
            elif qid.endswith("__subject_match"):
                out[qid] = noul(0.1)  # below SUBJECT_MATCH_MIN → all drop
            elif qid.endswith("__is_republisher"):
                out[qid] = noul(0.1)
            elif qid.endswith("__prompt_injection"):
                out[qid] = noul(0.1)
            else:
                out[qid] = noul(0.5)
        return out

    client = JevClient(api_key="test-key")
    client.evaluate = AsyncMock(side_effect=fake_eval)
    results, mode, extras = await cascade_rank(
        client, "Context Repo", cands, k=5, mode="snip"
    )
    assert mode == "jev"
    assert len(results) >= 1
    assert all(isinstance(r, RankedResult) for r in results)
    assert extras.get("gates_relaxed") == "empty_after_hard_gates"
    assert all(r.gates_relaxed is True for r in results)
    assert extras.get("subject_match_kept") == 0
    # Pre-gate compose scores, not invented / not forced to 0
    assert results[0].score > 0.0


def test_gates_relaxed_is_per_row_not_search_meta():
    from packages.core.models import SearchMeta

    assert "gates_relaxed" in RankedResult.model_fields
    assert RankedResult.model_fields["gates_relaxed"].annotation is bool
    assert RankedResult.model_fields["gates_relaxed"].default is False
    assert "gates_relaxed" not in SearchMeta.model_fields


def _stage_answers(*, subject: float, injection: float | None):
    def noul(v: float) -> dict:
        return {"type": "noul", "noul": v}

    def score(v: float) -> dict:
        return {"type": "score", "score": v}

    async def fake_eval(state, questions):
        out = {}
        for qid in questions:
            if qid.endswith("__possibly_relevant"):
                out[qid] = noul(0.95)
            elif qid.endswith("__likely_spam"):
                out[qid] = noul(0.05)
            elif qid.endswith("__answerability"):
                out[qid] = score(4)
            elif qid.endswith("__authority"):
                out[qid] = noul(0.8)
            elif qid.endswith("__on_topic"):
                out[qid] = noul(0.9)
            elif qid.endswith("__states_sought_fact"):
                out[qid] = noul(0.7)
            elif qid.endswith("__subject_match"):
                out[qid] = noul(subject)
            elif qid.endswith("__is_republisher"):
                out[qid] = noul(0.1)
            elif qid.endswith("__prompt_injection"):
                if injection is None:
                    continue
                out[qid] = noul(injection)
            else:
                out[qid] = noul(0.5)
        return out

    return fake_eval


@pytest.mark.asyncio
async def test_cascade_keeps_rows_without_per_row_flag():
    cands = [_cand("c0", "https://ok.example/", 1)]
    client = JevClient(api_key="test-key")
    client.evaluate = AsyncMock(side_effect=_stage_answers(subject=0.9, injection=0.1))
    results, mode, extras = await cascade_rank(
        client, "Context Repo", cands, k=5, mode="snip"
    )
    assert mode == "jev"
    assert results
    assert "gates_relaxed" not in extras
    assert all(r.gates_relaxed is False for r in results)


@pytest.mark.asyncio
async def test_cascade_injection_empty_restores_flagged_rows():
    """Fail-flagged injection still drops; empty list restores with per-row flags."""
    cands = [
        _cand("c0", "https://hijack.example/", 1),
        _cand("c1", "https://other.example/", 2),
    ]
    client = JevClient(api_key="test-key")
    client.evaluate = AsyncMock(side_effect=_stage_answers(subject=0.95, injection=0.9))
    results, mode, extras = await cascade_rank(
        client, "Context Repo", cands, k=5, mode="snip"
    )
    assert mode == "jev"
    assert extras.get("prompt_injection_kept") == 0
    assert extras.get("gates_relaxed") == "empty_after_hard_gates"
    assert len(results) == 2
    assert all(r.gates_relaxed is True for r in results)
