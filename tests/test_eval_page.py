"""Offline tests for the static /eval page (published public_v1 run)."""
from __future__ import annotations

import html as html_mod
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.config import get_settings

get_settings.cache_clear()

from fastapi.testclient import TestClient

from apps.api.eval_page import (
    SUITE_BALANCE_NOTE,
    TOP3_REL,
    find_double_dirs,
    find_snip_published_dir,
    find_top3_published_dir,
    is_double_judge_meta,
    load_eval_bundle,
    load_human_summary,
    load_published_run,
    load_top3_from_dir,
    pct1,
    pct_int,
    preferred_margin,
    published_honesty_line,
    rate_cell_class,
    render_eval_body_html,
    render_eval_markdown,
    render_eval_v1_body_html,
    render_eval_v1_markdown,
)
from apps.api.proportion import format_rate_detail, proportion_stat
from apps.api.main import app

client = TestClient(app)
PUBLISHED = ROOT / "evals" / "public_v1" / "published" / "v1.0.0-first-run"


def test_eval_html_200_from_published_json():
    summary = json.loads((PUBLISHED / "summary.json").read_text(encoding="utf-8"))
    meta = json.loads((PUBLISHED / "run_meta.json").read_text(encoding="utf-8"))
    r = client.get("/eval")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Agent Seek Eval" in body
    assert 'class="eval-heroes"' in body
    assert 'id="eval-hero-snip"' in body
    assert 'id="eval-hero-top3"' in body
    assert "Snip preference" in body
    assert "Top-3 hit rate" in body
    top3 = _article(body, "eval-hero-top3")
    assert "not yet run" not in top3
    assert "43/50" in top3
    assert f"{pct_int(43, 50)}%" in top3
    assert "Wilson" not in top3
    assert html_mod.escape(format_rate_detail(proportion_stat(43, 50))) not in top3
    assert html_mod.escape(format_rate_detail(proportion_stat(43, 50))) in body
    _assert_first_hit_rows(top3, 29, 11, 3)
    snip = _article(body, "eval-hero-snip")
    assert "Wilson" not in snip
    assert "summary.json" not in snip
    assert "gpt-5.6" not in snip
    assert "gpt-5.6" not in top3
    assert "eval-first-hits" not in snip
    _assert_snip_outcome_rows(snip, 37, 0, 13, 50)
    assert "37 / 0 / 13" not in snip
    assert "gpt-5.6-sol" in body
    assert str(summary["agent_seek_wins"]) in body
    assert str(summary["baseline_wins"]) in body
    assert str(summary["ties"]) in body
    assert str(summary["n"]) in body
    assert meta["judge"]["model"] == "gpt-5.6-sol"
    assert meta["judge"]["reasoning_effort"] == "medium"
    assert "SOTA" not in body
    assert "trophy" not in body.lower()
    assert "we win" not in body.lower()
    assert "Run eval" not in body
    assert 'href="/eval.md"' in body or 'href="/eval.md"' in body.lower()
    assert "preference vs same-pool You.com order" in body
    assert "not top-2 sufficiency" in body
    assert "mode=deep" in body
    assert "mode=snip" in body
    assert "Both published runs" in body
    assert "not validated" not in body.lower()
    assert "unvalidated" not in body.lower()
    assert "eval-win" in body
    assert "More Answer" not in body
    assert "product default" in body
    assert "optional richer mode" in body
    assert "UI and API/MCP" in body
    assert "website demo" not in body.lower()
    assert "API/MCP default" not in body
    assert "37/50" in body  # snip headline
    assert "32/50" in body  # deep


def test_eval_numbers_match_published_summary():
    run = load_published_run()
    summary = json.loads((PUBLISHED / "summary.json").read_text(encoding="utf-8"))
    assert run["as_wins"] == summary["agent_seek_wins"] == 32
    assert run["ties"] == summary["ties"] == 2
    assert run["baseline_wins"] == summary["baseline_wins"] == 16
    assert run["n"] == summary["n"] == 50
    assert run["errors"] == summary["errors"] == 0
    assert run["as_rate"] == pct1(32, 50) == 64.0
    assert run["as_rate_int"] == pct_int(32, 50) == 64
    assert run["as_rate_excl"] == pct1(32, 48) == 66.7
    assert run["as_rate_excl_int"] == pct_int(32, 48) == 67
    html = client.get("/eval").text
    assert "64% preferred" in html
    assert "67%" in html
    assert "32/50" in html
    assert "74% preferred" in html
    assert "37/50" in html
    md = client.get("/eval.md").text
    assert "64% preferred" in md
    assert "74% preferred" in md
    assert "gpt-5.6-sol" in md
    assert "32" in md
    assert "37" in md
    assert "mode=deep" in md
    assert "mode=snip" in md
    assert "Both published runs" in md
    assert "not validated" not in md.lower()


def test_eval_html_discloses_dual_published_runs():
    html = client.get("/eval").text
    md = client.get("/eval.md").text
    for body in (html, md):
        assert "mode=deep" in body
        assert "mode=snip" in body
        assert "Both published runs" in body
        assert "not validated" not in body.lower()
        assert "unvalidated" not in body.lower()
        assert "product default" in body
        assert "optional richer mode" in body
        assert "UI and API/MCP" in body
        assert "website demo" not in body.lower()
        assert "API/MCP default" not in body


def test_eval_md_and_html_alias():
    md = client.get("/eval.md")
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert "Agent Seek Eval" in md.text
    assert "Top-3 hit rate" in md.text
    assert "not yet run" not in md.text
    assert "43/50" in md.text
    assert f"{pct_int(43, 50)}%" in md.text
    assert format_rate_detail(proportion_stat(43, 50)) in md.text
    _assert_snip_outcome_rows(md.text, 37, 0, 13, 50)
    assert "37 / 0 / 13" not in md.text.split("## Deep preference", 1)[0]
    alias = client.get("/eval.html", follow_redirects=False)
    assert alias.status_code == 308
    assert alias.headers.get("location", "").endswith("/eval")


def test_published_json_served():
    r = client.get("/evals/public_v1/published/v1.0.0-first-run/summary.json")
    assert r.status_code == 200
    assert r.json()["agent_seek_wins"] == 32
    meta = client.get("/evals/public_v1/published/v1.0.0-first-run/run_meta.json")
    assert meta.json()["judge"]["model"] == "gpt-5.6-sol"


def test_eval_in_nav_and_sitemap():
    home = client.get("/", headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    assert 'href="/eval"' in home.text
    docs = client.get("/docs")
    assert 'href="/eval"' in docs.text
    sm = client.get("/sitemap.xml").text
    assert "<loc>https://agentseek.dev/eval</loc>" in sm
    assert "<loc>https://agentseek.dev/eval.md</loc>" in sm
    assert "/eval/v0" not in sm
    assert "/eval-v0" not in sm


def test_eval_page_is_not_hand_copied_html():
    assert not (ROOT / "apps" / "web" / "eval.html").exists()
    assert (PUBLISHED / "summary.json").is_file()


def test_snip_published_dir_present_validates_both():
    snip_dir = find_snip_published_dir()
    assert snip_dir is not None
    assert snip_dir.name == "v1.0.0-snip"
    bundle = load_eval_bundle()
    assert bundle["snip"] is not None
    assert bundle["deep"]["mode"] == "deep"
    assert bundle["snip"]["mode"] == "snip"
    assert bundle["snip"]["as_wins"] == 37
    assert bundle["snip"]["baseline_wins"] == 13
    assert bundle["snip"]["ties"] == 0
    assert bundle["snip"]["errors"] == 0
    line = published_honesty_line(bundle["deep"], bundle["snip"])
    assert "mode=deep" in line
    assert "mode=snip" in line
    assert "Both published runs" in line
    assert "not validated" not in line


def test_rate_shading_only_when_margin_clear():
    assert preferred_margin(32, 16) == "as"
    assert preferred_margin(16, 32) == "base"
    assert preferred_margin(10, 10) == ""
    assert preferred_margin(11, 10) == ""
    assert rate_cell_class("as", 32, 16) == "eval-win"
    assert rate_cell_class("base", 32, 16) == ""
    assert rate_cell_class("base", 16, 32) == "eval-loss"
    assert rate_cell_class("as", 16, 32) == ""


def test_dual_mode_render_uses_real_snip_shape_without_publishing_scores():
    deep = load_published_run()
    snip = dict(deep)
    snip["mode"] = "snip"
    snip["rel"] = "evals/public_v1/published/v1.0.0-snip"
    snip["as_wins"] = 20
    snip["baseline_wins"] = 28
    snip["ties"] = 2
    snip["as_rate"] = pct1(20, 50)
    snip["as_rate_int"] = pct_int(20, 50)
    snip["as_rate_excl"] = pct1(20, 48)
    snip["as_rate_excl_int"] = pct_int(20, 48)
    snip["base_rate"] = pct1(28, 50)
    snip["base_rate_excl"] = pct1(28, 48)
    snip["tie_rate"] = pct1(2, 50)
    snip["run_id"] = "synthetic-snip-for-render"
    html = render_eval_body_html(deep, snip)
    md = render_eval_markdown(deep, snip)
    for body in (html, md):
        assert "mode=deep" in body
        assert "mode=snip" in body
        assert "product default" in body
        assert "optional richer mode" in body
        assert "UI and API/MCP" in body
        assert "website demo" not in body.lower()
        assert "API/MCP default" not in body
        assert "unvalidated" not in body.lower()
        assert "not validated" not in body.lower()
        assert "More Answer" not in body
        assert "preference vs same-pool You.com order" in body
    assert "eval-win" in html
    assert "eval-loss" in html
    assert "synthetic-snip-for-render" in html
    assert "v1.0.0-snip" in html
    live = client.get("/eval").text
    assert "synthetic-snip-for-render" not in live
    # Live page now loads the published snip run (validated dual honesty).
    assert "Both published runs" in live
    assert "not validated" not in live.lower()
    assert "unvalidated" not in live.lower()
    assert "37/50" in live


def _detail_pieces(successes: int, trials: int) -> tuple[str, str]:
    wilson, p_bit = format_rate_detail(proportion_stat(successes, trials)).split("; ")
    return wilson, p_bit


def test_eval_shows_wilson_and_exact_p_for_both_denominators():
    """Snip 37-13-0 and deep 32-16-2, of n and of decided pairs.

    The skim page carries the headline rates.
    """
    html = client.get("/eval").text
    md = client.get("/eval.md").text
    headline = (
        (37, 50),  # snip of n, and excl. ties (0 ties)
        (32, 50),  # deep of n
        (32, 48),  # deep decided pairs
    )
    for body in (html, md):
        assert "74% preferred" in body
        assert "64% preferred" in body
        assert "37/50" in body
        assert "32/50" in body
        assert "32/48" in body
        assert "ties count as non-wins" in body
        assert "decided pairs" in body
        assert "Wilson 95% CI" in body
        assert "H0: p=0.5" in body
        assert "Judge certainty" in body
        assert "not a statistical interval" in body
        assert "deep / snip" in body
        assert "0.93 / 0.82" in body
        assert "confidence" not in body.lower()
        assert ">conf.<" not in body
        assert "| confidence |" not in body
        for successes, trials in headline:
            wilson, p_bit = _detail_pieces(successes, trials)
            assert wilson in body
            assert p_bit in body
        assert format_rate_detail(proportion_stat(37, 50)) in body
        assert format_rate_detail(proportion_stat(32, 50)) in body
        assert format_rate_detail(proportion_stat(32, 48)) in body


def test_eval_omits_tier_win_rate_tables():
    """L1/L2/L3 stay on each query. Their win rates are not a findings table."""
    html = client.get("/eval").text
    md = client.get("/eval.md").text
    # Published by_tier cells (deep and snip), excl. ties where ties exist.
    buried = (
        (16, 20),  # snip L2
        (9, 15),  # snip L1
        (12, 15),  # snip L3
        (14, 20),  # deep L2
        (10, 14),  # deep L1 excl. one tie
        (8, 14),  # deep L3 excl. one tie
    )
    for body in (html, md):
        assert SUITE_BALANCE_NOTE in body
        assert "Tier breakdown" not in body
        assert "AS win% excl. ties" not in body
        assert "Deep AS" not in body
        assert "Snip AS" not in body
        assert "for coverage" in body
        assert "not published" in body
        assert "underpowered" in body
        for successes, trials in buried:
            assert format_rate_detail(proportion_stat(successes, trials)) not in body
    assert "<th>tier</th>" in html
    assert "<td>L1</td>" in html
    assert "<td>L2</td>" in html
    assert "<td>L3</td>" in html
    assert "| id | tier | query |" in md
    assert "| L1 |" in md
    assert "| L2 |" in md
    assert "| L3 |" in md
    deep = load_published_run()
    for body in (render_eval_body_html(deep, None), render_eval_markdown(deep, None)):
        assert SUITE_BALANCE_NOTE in body
        assert "Tier breakdown" not in body
        assert "AS win% excl. ties" not in body


def test_position_check_renders_published_snip_double():
    """Published snip double is on /eval. Human kappa stays off until summary.json exists."""
    doubles = find_double_dirs()
    assert set(doubles) == {"snip"}
    assert doubles["snip"].name == "v1.0.0-snip-double"
    assert load_human_summary() is None
    assert is_double_judge_meta("v1.0.0-snip-double", {"mode": "snip"})
    assert is_double_judge_meta("custom", {"double_judge": True})
    assert not is_double_judge_meta("v1.0.0-snip", {"mode": "snip"})
    html = client.get("/eval").text
    md = client.get("/eval.md").text
    for body in (html, md):
        assert "Snip (product default) flip rate 14.0% (7/50)" in body
        assert "published URLs" in body
        assert "Cohen" not in body
        assert "kappa" not in body.lower()
        assert 'href="/eval/v0"' not in body
        assert "/eval/v0" not in body
    assert find_snip_published_dir().name == "v1.0.0-snip"


def test_position_check_uses_agreeing_pairs_and_wilson():
    deep = load_published_run()
    bundle = load_eval_bundle()
    snip = bundle["snip"]
    double = {
        "mode": "snip",
        "n": 10,
        "both_verdicts": 10,
        "flips": 2,
        "agreeing": 8,
        "as_wins": 6,
        "baseline_wins": 1,
        "ties": 1,
        "errors": 0,
        "shortlist_text": "url_only",
    }
    doubles = {"snip": double, "deep": None}
    human = {
        "kind": "human_agreement",
        "labeled": 4,
        "agree": 3,
        "agreement": 0.75,
        "kappa": 0.6363636363636364,
        "human_mapped": {"agent_seek": 1, "baseline": 2, "tie": 1},
    }
    for body in (
        render_eval_body_html(deep, snip, doubles, human),
        render_eval_markdown(deep, snip, doubles, human),
    ):
        assert "20.0% (2/10)" in body
        assert "6/8" in body
        assert "6/7" in body
        assert format_rate_detail(proportion_stat(6, 8)) in body
        assert format_rate_detail(proportion_stat(6, 7)) in body
        assert "Agreeing pairs only" in body
        assert "same shortlists" in body
        assert "Deep (optional richer mode): side-swapped double judge not yet run." in body
        assert "Agreement 75.0% (3/4)" in body
        assert "0.636" in body
        assert "Cohen's kappa" in body
        assert "urls" in body.lower()


def _article(html: str, element_id: str) -> str:
    start = html.index(f'id="{element_id}"')
    end = html.index("</article>", start)
    return html[start:end]


def _assert_first_hit_rows(body: str, n1: int, n2: int, n3: int) -> None:
    """HTML rows or markdown bullets. Shares are pct of the counted hits."""
    total = n1 + n2 + n3
    assert "First hit at #1 / #2 / #3" not in body
    assert "First result that stated the answer" in body
    sentence = f"{n1} of {total} hits already stated the answer in the first result."
    if 'class="eval-rank-place"' in body:
        for rank, count in ((1, n1), (2, n2), (3, n3)):
            assert f'<span class="eval-rank-place">#{rank}</span>' in body
            assert f'<span class="eval-rank-count">{count}</span>' in body
            if total:
                pct = pct_int(count, total)
                assert f'{pct}% <span class="eval-rank-of">of hits</span>' in body
        places = [body.index(f'<span class="eval-rank-place">#{rank}</span>') for rank in (1, 2, 3)]
        assert places == sorted(places)
        if total:
            assert sentence in body
            assert pct_int(n1, total) == round(100.0 * n1 / total)
        else:
            assert "already stated the answer" not in body
            assert 'class="eval-rank-share">—</span>' in body
        return
    for rank, count in ((1, n1), (2, n2), (3, n3)):
        share = f" ({pct_int(count, total)}% of hits)" if total else ""
        assert f"- **#{rank} → {count}**{share}" in body
    bullets = [body.index(f"- **#{rank} →") for rank in (1, 2, 3)]
    assert bullets == sorted(bullets)
    if total:
        assert sentence in body
    else:
        assert "already stated the answer" not in body


def _assert_snip_outcome_rows(body: str, wins: int, ties: int, losses: int, n: int) -> None:
    """HTML rows or markdown bullets for the snip preference hero."""
    assert f"Preferred on {wins} of {n} questions." in body
    if 'class="eval-rank-place">Wins' in body:
        for label, count in (("Wins", wins), ("Ties", ties), ("Losses", losses)):
            assert f'<span class="eval-rank-place">{label}</span>' in body
            assert f'<span class="eval-rank-count">{count}</span>' in body
            if n:
                assert f'{pct_int(count, n)}% <span class="eval-rank-of">of {n}</span>' in body
        places = [
            body.index(f'<span class="eval-rank-place">{label}</span>')
            for label in ("Wins", "Ties", "Losses")
        ]
        assert places == sorted(places)
        return
    for label, count in (("Wins", wins), ("Ties", ties), ("Losses", losses)):
        share = f" ({pct_int(count, n)}% of {n})" if n else ""
        assert f"- **{label} → {count}**{share}" in body
    bullets = [body.index(f"- **{label} →") for label in ("Wins", "Ties", "Losses")]
    assert bullets == sorted(bullets)


def test_eval_v0_redirects_to_eval():
    for path in ("/eval/v0", "/eval/v0.md", "/eval-v0", "/eval-v0.md"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 301, path
        assert response.headers.get("location", "").endswith("/eval"), path
        followed = client.get(path, follow_redirects=True)
        assert followed.status_code == 200, path
        assert "Agent Seek Eval" in followed.text
        assert "Archived dense page" not in followed.text
        assert "Leaderboard" not in followed.text


def test_eval_v1_heroes_show_published_top3():
    """Live /eval loads published/v1.0.0-snip-top3 (43/50), not scratch results."""
    html = client.get("/eval").text
    md = client.get("/eval.md").text
    assert html.index("eval-heroes") < html.index("eval-hero-snip")
    assert html.index("eval-hero-snip") < html.index("eval-hero-top3")
    assert html.index("eval-hero-top3") < html.index("eval-secondary")
    detail = format_rate_detail(proportion_stat(43, 50))
    top3 = _article(html, "eval-hero-top3")
    assert "not yet run" not in top3
    assert "43/50" in top3
    assert f"{pct_int(43, 50)}%" in top3
    assert "Wilson" not in top3
    assert html_mod.escape(detail) not in top3
    assert html_mod.escape(detail) in html
    _assert_first_hit_rows(top3, 29, 11, 3)
    assert top3.index(f"{pct_int(43, 50)}%") < top3.index("eval-first-hits")
    assert "results.jsonl" not in top3
    assert "summary.json" not in top3
    snip = _article(html, "eval-hero-snip")
    assert "eval-first-hits" not in snip
    assert "Wilson" not in snip
    assert "summary.json" not in snip
    _assert_snip_outcome_rows(snip, 37, 0, 13, 50)
    assert "37 / 0 / 13" not in snip
    assert "37 / 0 / 13" not in top3
    skim = html.split("<details", 1)[0]
    assert "Wilson" not in skim
    assert "summary.json" not in skim
    assert "results.jsonl" not in skim
    assert "gpt-5.6" not in skim
    assert "H0:" not in skim
    assert "We asked 50 questions." in skim
    assert "74% preferred" in skim
    assert "86%" in skim
    assert "43/50" in skim
    assert "#1" in skim
    assert '<details class="eval-measured">' in html
    assert 'class="eval-measured" open' not in html
    assert "How we measured" in html
    for body in (html, md):
        assert "continued run after upstream 503s" not in body
        assert "upstream 503" not in body
        assert "continued run" not in body
        assert "stitched" not in body.lower()
        assert "truncate_gate" not in body
        assert "gitignored" not in body
        assert "A fresh deep pass" not in body
    assert '<details class="eval-diagnostics">' in html
    assert 'class="eval-diagnostics" open' not in html
    assert '<details class="eval-explore">' in html
    assert 'class="eval-explore" open' not in html
    md_skim = md.split("## How we measured", 1)[0]
    assert "Wilson" not in md_skim
    assert "summary.json" not in md_skim
    assert "results.jsonl" not in md_skim
    assert "We asked 50 questions." in md_skim
    assert "Tier breakdown" not in html
    assert "Brave" not in html
    assert "Exa" not in html
    assert "Run eval" not in html
    assert 'href="/eval/v0"' not in html
    assert "/eval/v0" not in html
    assert "/eval/v0" not in md
    for body in (html, md):
        assert "74% preferred" in body
        _assert_snip_outcome_rows(body, 37, 0, 13, 50)
        assert format_rate_detail(proportion_stat(37, 50)) in body
        assert "43/50" in body
        _assert_first_hit_rows(body, 29, 11, 3)
        assert "not yet run" not in body
    assert detail in md
    assert html_mod.escape(detail) in html
    published = find_top3_published_dir()
    assert published is not None
    assert published.name == "v1.0.0-snip-top3"
    summary = json.loads((published / "summary.json").read_text(encoding="utf-8"))
    meta = json.loads((published / "run_meta.json").read_text(encoding="utf-8"))
    assert summary["kind"] == "top3_gold"
    assert summary["hits"] == 43
    assert summary["scored"] == 50
    assert summary["errors"] == 0
    assert summary["hit_rate"] == 0.86
    assert meta["kind"] == "top3_gold"
    loaded = load_eval_bundle()["top3"]
    assert loaded is not None
    assert loaded["hits"] == 43
    assert loaded["scored"] == 50
    assert loaded["errors"] == 0
    assert loaded["first_hit_ranks"] == {1: 29, 2: 11, 3: 3}
    assert sum(loaded["first_hit_ranks"].values()) == 43
    assert "hit_rate" not in loaded
    assert TOP3_REL == "evals/public_v1/published/v1.0.0-snip-top3"
    assert "top3/results" not in TOP3_REL
    served = client.get("/evals/public_v1/published/v1.0.0-snip-top3/summary.json")
    assert served.status_code == 200
    assert served.json()["hits"] == 43
    assert served.json()["scored"] == 50


def test_top3_published_dir_renders_counts_and_ignores_stored_rate(tmp_path: Path):
    """A reviewed copy under the published path is the only hit rate source."""
    summary = {
        "kind": "top3_gold",
        "hits": 41,
        "misses": 8,
        "errors": 1,
        "scored": 49,
        "n": 50,
        "hit_rate": 0.99,
        "k": 3,
        "mode": "snip",
    }
    meta = {
        "kind": "top3_gold",
        "mode": "snip",
        "k": 3,
        "run_id": "top3-fixture",
        "judge": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    loaded = load_top3_from_dir(tmp_path)
    assert loaded is not None
    assert loaded["hits"] == 41
    assert loaded["scored"] == 49
    assert loaded["first_hit_ranks"] is None
    assert "hit_rate" not in loaded
    deep = load_published_run()
    snip = load_eval_bundle()["snip"]
    html = render_eval_v1_body_html(deep, snip, {"snip": None, "deep": None}, None, loaded)
    md = render_eval_v1_markdown(deep, snip, {"snip": None, "deep": None}, None, loaded)
    detail = format_rate_detail(proportion_stat(41, 49))
    top3 = _article(html, "eval-hero-top3")
    assert "not yet run" not in top3
    assert "41/49" in top3
    assert f"{pct_int(41, 49)}%" in top3
    assert "Wilson" not in top3
    assert html_mod.escape(detail) not in top3
    assert html_mod.escape(detail) in html
    assert "0.99" not in top3
    assert "99%" not in top3
    assert "eval-first-hits" not in top3
    assert "First result that stated the answer" not in top3
    assert detail in md
    assert "First result that stated the answer" not in md.split("## Deep preference", 1)[0]
    assert "99%" not in md.split("## Deep preference", 1)[0]
    for body in (html, md):
        assert "41/49" in body
        _assert_snip_outcome_rows(body, 37, 0, 13, 50)
    # Incomplete or wrong-kind directories do not become a hit rate.
    (tmp_path / "summary.json").write_text(json.dumps({"kind": "other", "hits": 1}), encoding="utf-8")
    assert load_top3_from_dir(tmp_path) is None


def _write_top3_dir(path: Path, *, hits: int, misses: int, errors: int = 0) -> None:
    scored = hits + misses
    summary = {
        "kind": "top3_gold",
        "hits": hits,
        "misses": misses,
        "errors": errors,
        "scored": scored,
        "n": scored + errors,
        "k": 3,
        "mode": "snip",
    }
    meta = {
        "kind": "top3_gold",
        "mode": "snip",
        "k": 3,
        "judge": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (path / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_top3_first_hit_ranks_come_from_results_jsonl(tmp_path: Path):
    """Rank counts are a Counter of first_hit_rank on hits, not a stored summary field."""
    _write_top3_dir(tmp_path, hits=4, misses=1)
    rows = [
        {"id": "a", "hit": True, "first_hit_rank": 1},
        {"id": "b", "hit": True, "first_hit_rank": 1},
        {"id": "c", "hit": True, "first_hit_rank": 2},
        {"id": "d", "hit": True, "first_hit_rank": 3},
        {"id": "e", "hit": False, "first_hit_rank": None},
        {"id": "f", "hit": True, "first_hit_rank": 9},
        {"id": "g", "hit": True, "first_hit_rank": "1"},
    ]
    # Summary hits stay 4. Rank 9 and the string rank are not #1/#2/#3 counts.
    (tmp_path / "results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    loaded = load_top3_from_dir(tmp_path)
    assert loaded is not None
    assert loaded["hits"] == 4
    assert loaded["first_hit_ranks"] == {1: 2, 2: 1, 3: 1}
    deep = load_published_run()
    snip = load_eval_bundle()["snip"]
    html = render_eval_v1_body_html(deep, snip, {"snip": None, "deep": None}, None, loaded)
    md = render_eval_v1_markdown(deep, snip, {"snip": None, "deep": None}, None, loaded)
    top3 = _article(html, "eval-hero-top3")
    _assert_first_hit_rows(top3, 2, 1, 1)
    _assert_first_hit_rows(md, 2, 1, 1)
    assert "43/50" not in top3
    assert "4/5" in top3
    assert "results.jsonl" not in top3
    assert "results.jsonl" in html
    assert "eval-first-hits" not in _article(html, "eval-hero-snip")
    # Unreadable JSONL omits the block rather than guessing from a prefix.
    (tmp_path / "results.jsonl").write_text('{"hit": true, "first_hit_rank": 1}\n{', encoding="utf-8")
    broken = load_top3_from_dir(tmp_path)
    assert broken is not None
    assert broken["first_hit_ranks"] is None
    broken_html = render_eval_v1_body_html(deep, snip, {"snip": None, "deep": None}, None, broken)
    broken_top3 = _article(broken_html, "eval-hero-top3")
    assert "eval-first-hits" not in broken_top3
    assert "First result that stated the answer" not in broken_top3
    # Misses only still render the counted zeros.
    (tmp_path / "results.jsonl").write_text(
        json.dumps({"hit": False, "first_hit_rank": None}) + "\n",
        encoding="utf-8",
    )
    zeros = load_top3_from_dir(tmp_path)
    assert zeros is not None
    assert zeros["first_hit_ranks"] == {1: 0, 2: 0, 3: 0}
    zeros_html = render_eval_v1_body_html(deep, snip, {"snip": None, "deep": None}, None, zeros)
    zeros_md = render_eval_v1_markdown(deep, snip, {"snip": None, "deep": None}, None, zeros)
    _assert_first_hit_rows(_article(zeros_html, "eval-hero-top3"), 0, 0, 0)
    _assert_first_hit_rows(zeros_md, 0, 0, 0)
    # Hits with no integer rank in 1–3 omit the line instead of printing 0 / 0 / 0.
    (tmp_path / "results.jsonl").write_text(
        json.dumps({"hit": True, "first_hit_rank": None}) + "\n",
        encoding="utf-8",
    )
    unranked = load_top3_from_dir(tmp_path)
    assert unranked is not None
    assert unranked["first_hit_ranks"] is None


def test_v1_shows_human_kappa_only_when_summary_passed():
    deep = load_published_run()
    snip = load_eval_bundle()["snip"]
    human = {
        "kind": "human_agreement",
        "labeled": 4,
        "agree": 3,
        "agreement": 0.75,
        "kappa": 0.6363636363636364,
    }
    html = render_eval_v1_body_html(deep, snip, {"snip": None, "deep": None}, human, None)
    md = render_eval_v1_markdown(deep, snip, {"snip": None, "deep": None}, human, None)
    for body in (html, md):
        assert "Agreement 75.0% (3/4)" in body
        assert "0.636" in body
        assert "Cohen's kappa" in body
        assert "not yet run" in body
