"""v0.1.13 snip official-docs soft floor — compose + snip prompt."""
from __future__ import annotations

import pytest

from packages.core.rank.cascade import (
    AUTH_SOFT_FLOOR,
    AUTH_WEIGHT,
    compose_score,
)
from packages.core.rank.jev import build_stage_b_questions


def test_constants_v012():
    assert AUTH_SOFT_FLOOR == 0.25
    assert AUTH_WEIGHT == 0.12


def test_outside_eps_high_auth_docs_reach_070():
    """K8s-shaped: a=0.58 fact=0.21 auth=0.98 ot=0.98 best_a=0.91 → ≥ 0.70."""
    score = compose_score(
        answerability=0.58,
        fact=0.21,
        authority=0.98,
        on_topic=0.98,
        best_a=0.91,
        url="https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/",
    )
    assert score >= 0.70
    # Explicit soft-floor arithmetic
    plain = 0.75 * 0.58 + 0.25 * 0.21
    assert score == pytest.approx(min(1.0, plain + AUTH_SOFT_FLOOR * 0.98))


def test_low_auth_blog_can_still_outrank_on_numbers():
    docs = compose_score(
        answerability=0.58,
        fact=0.21,
        authority=0.98,
        on_topic=0.98,
        best_a=0.91,
        url="https://kubernetes.io/docs/x",
    )
    blog = compose_score(
        answerability=0.90,
        fact=0.40,
        authority=0.02,
        on_topic=0.95,
        best_a=0.91,
        url="https://blog.example/liveness-vs-readiness",
    )
    assert blog > docs


def test_comparable_uses_auth_weight_not_soft_floor():
    # a within ε of best → AUTH_WEIGHT path
    score = compose_score(
        answerability=0.88,
        fact=0.30,
        authority=0.95,
        on_topic=0.97,
        best_a=0.91,
        url="https://docs.example.com/guide",
    )
    plain = 0.75 * 0.88 + 0.25 * 0.30
    assert score == pytest.approx(min(1.0, plain + AUTH_WEIGHT * 0.95))


def test_snip_answerability_prompt_has_useful_floor_deep_does_not():
    snip = build_stage_b_questions(["c0"], deep=False)["c0__answerability"]["instructions"]
    deep = build_stage_b_questions(["c0"], deep=True)["c0__answerability"]["instructions"]
    assert "Useful band" in snip
    assert "thin SERP" in snip or "thin" in snip.lower()
    assert "Do not invent facts from the URL path" in snip
    assert "Useful band" not in deep
