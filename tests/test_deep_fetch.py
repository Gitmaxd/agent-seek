"""Deep Stage B: page extract + Jev deep prompts + enrich caps."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from packages.core.fetch.page import html_to_text
from packages.core.models import Candidate
from packages.core.rank.cascade import DEEP_FETCH_CAP, enrich_survivors_with_bodies
from packages.core.rank.jev import build_stage_b_questions, candidates_state


def test_html_to_text_strips_scripts():
    html = """
    <html><head><script>evil()</script><style>.x{}</style></head>
    <body><h1>LangChain docs</h1><p>Deep Agents launched on March 1, 2026.</p></body></html>
    """
    text = html_to_text(html)
    assert "evil" not in text
    assert "Deep Agents" in text
    assert "March 1" in text


def test_html_to_text_truncates():
    html = "<p>" + ("word " * 5000) + "</p>"
    text = html_to_text(html, max_chars=200)
    assert len(text) <= 201  # ellipsis


def test_stage_b_deep_prompts_use_page_text():
    qs = build_stage_b_questions(["c0"], deep=True)
    assert "page text" in qs["c0__answerability"]["instructions"]
    assert "snippet" in qs["c0__answerability"]["instructions"]  # fallback mention
    qs_snip = build_stage_b_questions(["c0"], deep=False)
    assert "snippet" in qs_snip["c0__answerability"]["instructions"]
    assert "page text" not in qs_snip["c0__answerability"]["instructions"]


def test_candidates_state_includes_body_when_deep():
    c = Candidate(
        id="c0",
        url="https://docs.example.com/x",
        title="Docs",
        snippet="short",
        body="Full document body with the answer date 2026-03-01.",
        raw_rank=1,
    )
    deep = candidates_state("when launched?", [c], deep=True)
    assert deep["candidates"][0]["body"].startswith("Full document")
    snip = candidates_state("when launched?", [c], deep=False)
    assert "body" not in snip["candidates"][0]


@pytest.mark.asyncio
async def test_enrich_survivors_caps_and_sets_body():
    cands = [
        Candidate(id=f"c{i}", url=f"https://example.com/{i}", title=f"t{i}", snippet="s", raw_rank=i)
        for i in range(DEEP_FETCH_CAP + 3)
    ]

    async def fake_fetch(url, timeout=5.0):
        return f"BODY for {url}"

    with patch("packages.core.rank.cascade.fetch_main_text", side_effect=fake_fetch):
        survivors, ok, fetch_ms = await enrich_survivors_with_bodies(cands)

    assert ok == DEEP_FETCH_CAP
    assert fetch_ms >= 0
    assert all(c.body.startswith("BODY") for c in survivors[:DEEP_FETCH_CAP])
    assert all(c.body == "" for c in survivors[DEEP_FETCH_CAP:])


@pytest.mark.asyncio
async def test_enrich_fetch_failure_leaves_empty_body():
    c = Candidate(id="c0", url="https://example.com/x", title="t", snippet="s", raw_rank=1)

    async def fail_fetch(url, timeout=5.0):
        return None

    with patch("packages.core.rank.cascade.fetch_main_text", side_effect=fail_fetch):
        survivors, ok, _ = await enrich_survivors_with_bodies([c])
    assert ok == 0
    assert survivors[0].body == ""
