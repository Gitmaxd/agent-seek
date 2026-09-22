import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from packages.core.discover.youcom import parse_youcom_response
from packages.core.rank.cascade import cascade_rank, derive_flags, raw_as_ranked
from packages.core.rank.jev import JevClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_derive_flags():
    flags = derive_flags(on_topic=0.9, spam=0.8, score=0.8)
    assert "on_topic" in flags
    assert "spam_low" in flags
    assert "high_relevance" in flags


def test_raw_as_ranked():
    payload = json.loads((FIXTURES / "youcom_search_sample.json").read_text())
    cands = parse_youcom_response(payload)
    ranked = raw_as_ranked(cands, 3)
    assert len(ranked) == 3
    assert ranked[0].raw_rank == 1
    assert ranked[0].score == 0.0


@pytest.mark.asyncio
async def test_cascade_with_fixtures():
    payload = json.loads((FIXTURES / "youcom_search_sample.json").read_text())
    cands = parse_youcom_response(payload)
    stage_a = json.loads((FIXTURES / "jev_stage_a_sample.json").read_text())["answers"]
    stage_b = json.loads((FIXTURES / "jev_stage_b_sample.json").read_text())["answers"]

    client = JevClient(api_key="test-key")
    call_n = {"n": 0}

    async def fake_eval(state, questions):
        call_n["n"] += 1
        # First call(s) stage A, then B
        if any("__possibly_relevant" in q for q in questions):
            return {k: v for k, v in stage_a.items() if k in questions}
        return {k: v for k, v in stage_b.items() if k in questions}

    client.evaluate = AsyncMock(side_effect=fake_eval)
    results, mode, extras = await cascade_rank(client, "Introducing System One Models Jev", cands, k=3)
    assert mode == "jev"
    assert len(results) <= 3
    assert "typesafe.ai" in results[0].url  # blog or docs (authority boost)
    assert results[0].score > results[-1].score or results[0].score >= 0.8
    assert "on_topic" in results[0].flags or results[0].score > 0.5
    # Additive signals from cascade maps (keys only when present)
    if results[0].signals:
        assert set(results[0].signals.keys()) <= {
            "answerability",
            "authority",
            "on_topic",
            "states_sought_fact",
            "subject_match",
            "spam",
            "prompt_injection",
        }
        for v in results[0].signals.values():
            assert 0.0 <= float(v) <= 1.0


def test_ranked_result_accepts_signals():
    from packages.core.models import RankedResult

    r = RankedResult(
        rank=1,
        url="https://example.com",
        title="T",
        snippet="s",
        score=0.85,
        flags=[],
        raw_rank=3,
        signals={
            "answerability": 0.9,
            "authority": 0.7,
            "on_topic": 0.8,
            "states_sought_fact": 0.6,
            "subject_match": 0.95,
            "spam": 0.1,
        },
    )
    assert r.signals["answerability"] == 0.9
    assert r.signals["states_sought_fact"] == 0.6
    assert set(r.signals) <= {
        "answerability",
        "authority",
        "on_topic",
        "states_sought_fact",
        "subject_match",
        "spam",
        "prompt_injection",
    }
    bare = RankedResult(
        rank=1,
        url="https://example.com",
        title="T",
        snippet="s",
        score=0.0,
        flags=[],
        raw_rank=1,
    )
    assert bare.signals is None


def test_signals_for_helper():
    from packages.core.rank.cascade import _signals_for

    out = _signals_for(
        "c1",
        answerability={"c1": 0.91234},
        authority={"c1": 0.7},
        on_topic={},
        states_fact={"c1": 0.55},
        subject_match={"c1": 0.88},
        a_spam={"c1": 0.12},
        prompt_injection={"c1": 0.21},
    )
    assert out == {
        "answerability": 0.9123,
        "authority": 0.7,
        "states_sought_fact": 0.55,
        "subject_match": 0.88,
        "spam": 0.12,
        "prompt_injection": 0.21,
    }
    assert "on_topic" not in out
    assert _signals_for(
        "missing",
        answerability={},
        authority={},
        on_topic={},
        states_fact={},
        subject_match={},
        a_spam={},
    ) is None


def test_raw_as_ranked_signals_none():
    payload = json.loads((FIXTURES / "youcom_search_sample.json").read_text())
    cands = parse_youcom_response(payload)
    ranked = raw_as_ranked(cands, 2)
    assert all(r.signals is None for r in ranked)
