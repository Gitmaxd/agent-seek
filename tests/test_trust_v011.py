"""Agent Seek v0.1.1 trust (kept in v0.1.27): spam soft-demote, near-dupe, nocache; host boost updated."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

from apps.api.config import get_settings

get_settings.cache_clear()

from apps.api.main import app
from packages.core.models import Candidate, RankedResult, SearchMeta, SearchResponse
from packages.core.rank.cascade import (
    AUTHORITY_HOST_BOOST,
    SPAM_SOFT_DEMOTE,
    apply_authority_boost,
    derive_flags,
    is_authority_host,
)
from packages.core.rank.jev import build_stage_b_questions
from packages.core.rank.near_dupe import (
    collapse_near_dupes,
    host_path_alias_key,
    soft_content_key,
)

client = TestClient(app)


def test_authority_boost_docs_and_cap():
    assert AUTHORITY_HOST_BOOST == pytest.approx(0.02)
    assert is_authority_host("https://docs.langchain.com/oss/python/deepagents/overview")
    # Host boost only when auth missing (default)
    assert apply_authority_boost(0.5, "https://docs.langchain.com/x") == pytest.approx(
        0.5 + AUTHORITY_HOST_BOOST
    )
    assert apply_authority_boost(0.99, "https://docs.langchain.com/x") == 1.0
    assert apply_authority_boost(1.0, "https://changelog.example.com/notes") == 1.0
    assert is_authority_host("https://github.com/langchain-ai/langchain/releases/tag/v1")
    boosted = apply_authority_boost(0.4, "https://github.com/foo/bar/releases")
    assert boosted == pytest.approx(0.4 + AUTHORITY_HOST_BOOST)
    # When auth present, host boost must NOT apply
    assert apply_authority_boost(
        0.5, "https://docs.langchain.com/x", auth_missing=False
    ) == 0.5


def test_authority_boost_not_on_third_party():
    assert not is_authority_host("https://www.marktechpost.com/2026/03/deep-agents")
    assert apply_authority_boost(0.8, "https://www.marktechpost.com/x") == 0.8
    assert not is_authority_host("https://blog.langchain.com/deep-agents")
    assert not is_authority_host("https://www.langchain.com/blog/deep-agents")


def test_spam_soft_demote_changes_order():
    twin_clean = Candidate(
        id="clean",
        url="https://example.com/a",
        title="A",
        snippet="same",
        raw_rank=2,
    )
    twin_spam = Candidate(
        id="spam",
        url="https://example.com/b",
        title="B",
        snippet="same",
        raw_rank=1,
    )
    # Simulate post-Stage-B scores equal before demote
    score = 0.8
    flags_clean = derive_flags(spam=0.1, score=score)
    flags_spam = derive_flags(spam=0.9, score=score)
    assert "spam_low" not in flags_clean
    assert "spam_low" in flags_spam

    sc_clean = score
    sc_spam = score * SPAM_SOFT_DEMOTE if "spam_low" in flags_spam else score
    assert sc_spam == pytest.approx(0.8 * 0.75)
    scored = [(twin_spam, sc_spam, flags_spam), (twin_clean, sc_clean, flags_clean)]
    scored.sort(key=lambda t: (-t[1], t[0].raw_rank))
    assert scored[0][0].id == "clean"
    assert scored[1][0].id == "spam"


def test_near_dupe_blog_vs_www_blog():
    title = "Introducing Deep Agents"
    snip = "Build agents that can plan and use tools."
    high = Candidate(
        id="blog",
        url="https://blog.example.com/deep-agents",
        title=title,
        snippet=snip,
        raw_rank=5,
    )
    low = Candidate(
        id="www",
        url="https://www.example.com/blog/deep-agents",
        title=title,
        snippet=snip,
        raw_rank=3,
    )
    assert soft_content_key(title, snip) == soft_content_key(high.title, high.snippet)
    assert host_path_alias_key(high.url) == host_path_alias_key(low.url)

    scored = [
        (low, 0.70, []),
        (high, 0.85, ["on_topic"]),
    ]
    out = collapse_near_dupes(scored)
    assert len(out) == 1
    assert out[0][0].id == "blog"
    assert out[0][1] == 0.85


def test_stage_b_prompt_has_answerability_not_authority_in_levels():
    qs = build_stage_b_questions(["c1"])
    assert "c1__answerability" in qs
    assert "c1__authority" in qs
    assert "c1__on_topic" in qs
    assert "c1__states_sought_fact" in qs
    assert "c1__relevance" not in qs
    instr = qs["c1__answerability"]["instructions"]
    assert "clearly states the asked fact" in instr
    assert "must not outrank a page that clearly answers" in instr
    criteria_blob = " ".join(qs["c1__answerability"]["criteria"]).lower()
    assert "authoritative" not in criteria_blob
    assert "Answers outright" in qs["c1__answerability"]["criteria"][-1]


def test_api_nocache_and_cache_scope():
    fake = SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url="https://example.com",
                title="Example",
                snippet="hi",
                score=0.9,
                flags=["on_topic"],
                raw_rank=2,
                provider="you.com",
            )
        ],
        meta=SearchMeta(
            q="test",
            candidates_in=5,
            kept=1,
            latency_ms=10,
            ranking="jev",
            agent_seek_version="0.3.0",
            cache_hit=False,
            cache_scope="discover",
        ),
        raw_results=[],
    )

    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r = client.get(
            "/v1/search",
            params={"q": "test", "k": 5, "nocache": "true"},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["cache_scope"] == "discover"
    assert body["meta"]["agent_seek_version"] == "0.3.0"
    pipe.search.assert_awaited()
    kwargs = pipe.search.await_args.kwargs
    assert kwargs.get("nocache") is True

    with patch("apps.api.main._pipeline") as gp:
        pipe = AsyncMock()
        pipe.search = AsyncMock(return_value=fake)
        gp.return_value = pipe
        r2 = client.post(
            "/v1/search",
            json={"q": "test", "k": 5, "nocache": True},
            headers={"Authorization": "Bearer test-agent-seek-key"},
        )
    assert r2.status_code == 200
    assert r2.json()["meta"]["cache_scope"] == "discover"
    assert pipe.search.await_args.kwargs.get("nocache") is True


def test_health_version_012():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "0.3.0"}
