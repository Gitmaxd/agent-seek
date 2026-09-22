"""Agent Seek official preference: Jev semantic authority + gated composite (no host overfitting)."""
from __future__ import annotations

import pytest

from packages.core.rank.cascade import (
    ANSWER_WEIGHT,
    AUTH_GATE,
    AUTH_SOFT_FLOOR,
    AUTH_WEIGHT,
    AUTHORITY_HOST_BOOST,
    COMPARABLE_EPS,
    FACT_WEIGHT,
    ON_TOPIC_MIN,
    apply_authority_host_boost,
    compose_score,
    is_authority_host,
)
from packages.core.rank.jev import ANSWERABILITY_LEVELS, build_stage_b_questions, parse_score_01


def test_constants_semantic_policy():
    assert ANSWER_WEIGHT == 0.75
    assert FACT_WEIGHT == 0.25
    assert COMPARABLE_EPS == 0.08
    assert ON_TOPIC_MIN == 0.55
    assert AUTH_GATE == 0.65
    assert AUTH_WEIGHT == 0.12
    assert AUTH_SOFT_FLOOR == 0.25
    # host boost is cold fallback only
    assert AUTHORITY_HOST_BOOST == 0.02


def test_stage_b_asks_semantic_authority_not_host_rules():
    qs = build_stage_b_questions(["c0"])
    assert set(qs.keys()) == {
        "c0__answerability",
        "c0__authority",
        "c0__on_topic",
        "c0__states_sought_fact",
        "c0__subject_match",
        "c0__is_republisher",
        "c0__prompt_injection",
    }
    assert "c0__relevance" not in qs
    levels = qs["c0__answerability"]["criteria"]
    assert levels == ANSWERABILITY_LEVELS
    assert "authoritative" not in " ".join(levels).lower()
    # authority question is semantic (query subject), not docs.* allowlist
    auth_instr = qs["c0__authority"]["instructions"].lower()
    assert "docs." not in auth_instr
    assert "official" in auth_instr or "primary" in auth_instr


def test_authority_gate_only_when_comparable():
    best_a = 0.90
    s_low_ot = compose_score(
        answerability=0.88, fact=0.5, authority=0.95, on_topic=0.40, best_a=best_a
    )
    s_far = compose_score(
        answerability=0.70, fact=0.5, authority=0.95, on_topic=0.90, best_a=best_a
    )
    s_low_auth = compose_score(
        answerability=0.88, fact=0.5, authority=0.50, on_topic=0.90, best_a=best_a
    )
    s_ok = compose_score(
        answerability=0.88, fact=0.5, authority=0.95, on_topic=0.90, best_a=best_a
    )
    base = 0.75 * 0.88 + 0.25 * 0.5
    far_base = 0.75 * 0.70 + 0.25 * 0.5
    assert s_low_ot == pytest.approx(base)
    assert s_far == pytest.approx(min(1.0, far_base + AUTH_SOFT_FLOOR * 0.95))
    assert s_low_auth == pytest.approx(base)
    assert s_ok == pytest.approx(min(1.0, base + AUTH_WEIGHT * 0.95))
    assert s_ok > s_far > far_base


def test_high_auth_low_answerability_does_not_outrank_fact_answer():
    # First-party (could be docs OR blog) with high semantic authority but weak answerability
    official = compose_score(
        answerability=0.50,
        fact=0.20,
        authority=0.95,
        on_topic=0.90,
        best_a=0.95,
        url="https://blog.example-vendor.com/announcing-feature",
    )
    third = compose_score(
        answerability=0.95,
        fact=0.95,
        authority=0.15,
        on_topic=0.90,
        best_a=0.95,
        url="https://news.example.com/feature-launched-on-march-15",
    )
    official_base = 0.75 * 0.50 + 0.25 * 0.20
    assert official == pytest.approx(min(1.0, official_base + AUTH_SOFT_FLOOR * 0.95))
    assert official < third


def test_comparable_answerability_high_auth_beats_twin_any_host():
    """Semantic authority wins the tie — including first-party blog (not docs.*)."""
    best_a = 0.85
    twin_no = compose_score(
        answerability=0.85,
        fact=0.5,
        authority=0.20,
        on_topic=0.90,
        best_a=best_a,
        url="https://random-seo.example/post",
    )
    twin_auth = compose_score(
        answerability=0.85,
        fact=0.5,
        authority=0.90,
        on_topic=0.90,
        best_a=best_a,
        url="https://blog.vendor.example/official-announce",
    )
    base = 0.75 * 0.85 + 0.25 * 0.5
    assert twin_no == pytest.approx(base)
    assert twin_auth == pytest.approx(min(1.0, base + AUTH_WEIGHT * 0.90))
    assert twin_auth > twin_no


def test_host_boost_only_when_authority_noul_missing():
    url = "https://docs.example.com/guide"
    assert is_authority_host(url)
    assert AUTHORITY_HOST_BOOST == pytest.approx(0.02)

    missing = compose_score(
        answerability=0.80, fact=0.5, authority=None, on_topic=0.90, best_a=0.80, url=url
    )
    base = 0.75 * 0.80 + 0.25 * 0.5
    assert missing == pytest.approx(min(1.0, base + AUTHORITY_HOST_BOOST))

    # authority present → no host boost (even outside ε)
    present = compose_score(
        answerability=0.50, fact=0.5, authority=0.90, on_topic=0.90, best_a=0.95, url=url
    )
    soft_base = 0.75 * 0.50 + 0.25 * 0.5
    assert present == pytest.approx(min(1.0, soft_base + AUTH_SOFT_FLOOR * 0.90))

    assert apply_authority_host_boost(0.5, url, auth_missing=False) == 0.5
    assert apply_authority_host_boost(0.5, url, auth_missing=True) == pytest.approx(
        0.5 + AUTHORITY_HOST_BOOST
    )


def test_no_host_allowlist_in_compose_for_non_heuristic_hosts():
    """A first-party apex blog with high authority Noul must not need docs.* to get the gate."""
    blog = compose_score(
        answerability=0.84,
        fact=0.6,
        authority=0.92,
        on_topic=0.9,
        best_a=0.85,
        url="https://openai.com/blog/something",
    )
    base = 0.75 * 0.84 + 0.25 * 0.6
    assert blog == pytest.approx(min(1.0, base + AUTH_WEIGHT * 0.92))
