"""Offline checks for HTML title/meta extraction and the committed shortlist artifact."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "eval_enrich_shortlists.py"
SUITE = ROOT / "evals" / "public_v1"
SNIP = SUITE / "published" / "v1.0.0-snip"
DEEP = SUITE / "published" / "v1.0.0-first-run"
SNIP_OUT = SUITE / "enriched" / "v1.0.0-snip-shortlists.jsonl"
DEEP_OUT = SUITE / "enriched" / "v1.0.0-deep-shortlists.jsonl"

HTML = """<!doctype html>
<html><head>
<title>Dependencies &amp; FastAPI</title>
<meta name="description" content="Declare dependencies with Depends().">
<meta property="og:description" content="ignored when name=description is set">
</head><body><p>body text that must not become the snippet</p></body></html>
"""


def _load():
    name = "eval_enrich_shortlists"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(SCRIPT):
        return existing
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_title_and_meta_description_not_body():
    mod = _load()
    title, snippet = mod.title_snippet_from_html(HTML)
    assert title == "Dependencies & FastAPI"
    assert snippet == "Declare dependencies with Depends()."
    assert "body text" not in snippet


def test_og_fallbacks_when_title_and_description_missing():
    mod = _load()
    html = """<html><head>
    <meta property="og:title" content="OG title">
    <meta property="og:description" content="OG description text">
    </head></html>"""
    title, snippet = mod.title_snippet_from_html(html)
    assert title == "OG title"
    assert snippet == "OG description text"


def test_fetch_label_keeps_http_errors_distinct_from_hits():
    mod = _load()
    assert (
        mod.fetch_label(
            http_status=404,
            content_type="text/html",
            title="Not found",
            snippet="",
            error=None,
            binary=False,
        )
        == "http_error"
    )
    assert (
        mod.fetch_label(
            http_status=200,
            content_type="text/html",
            title="",
            snippet="",
            error=None,
            binary=False,
        )
        == "empty"
    )
    assert mod.is_binary_type("application/pdf") is True
    assert mod.is_binary_type("text/html; charset=utf-8") is False


def _urls(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        urls: set[str] = set()
        for key in ("baseline_urls", "treatment_urls"):
            urls.update(row.get(key) or [])
        out[row["id"]] = urls
    return out


def _assert_artifact(published: Path, artifact: Path, label: str) -> None:
    assert artifact.is_file(), artifact
    meta_path = artifact.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["rediscover"] is False
    assert meta["youcom"] is False
    assert meta["label"] == label
    assert meta["method"] == "http_html_title_meta"
    rows = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = _urls(published / "per_query.jsonl")
    assert [row["id"] for row in rows] == list(expected)
    assert meta["queries"] == len(rows)
    for row in rows:
        got = [cand["url"] for cand in row["candidates"]]
        assert set(got) == expected[row["id"]]
        assert len(got) == len(set(got))
        for cand in row["candidates"]:
            assert cand["fetch"] in {
                "ok",
                "empty",
                "non_html",
                "http_error",
                "failed",
            }
            assert isinstance(cand["title"], str)
            assert isinstance(cand["snippet"], str)
    assert meta["with_title"] > 0


def test_human_packet_keeps_ids_and_copies_ok_titles_only():
    pos_path = ROOT / "scripts" / "eval_position.py"
    existing = sys.modules.get("eval_position")
    if existing is not None and getattr(existing, "__file__", None) == str(pos_path):
        pos = existing
    else:
        spec = importlib.util.spec_from_file_location("eval_position", pos_path)
        assert spec and spec.loader
        pos = importlib.util.module_from_spec(spec)
        sys.modules["eval_position"] = pos
        spec.loader.exec_module(pos)
    packet = pos.load_jsonl(SUITE / "human_v1" / "packet.jsonl")
    meta = json.loads((SUITE / "human_v1" / "sample_meta.json").read_text(encoding="utf-8"))
    rows, _ = pos.load_published_dir(SNIP)
    selected, _quotas = pos.stratified_sample(rows, n=30, seed=pos.HUMAN_SAMPLE_SEED)
    assert meta["seed"] == 20260921
    assert meta["shortlist_text"] == "title_snippet"
    assert meta["pools"].endswith("v1.0.0-snip-shortlists.jsonl")
    assert [item["id"] for item in packet] == [row["id"] for row in selected]
    index = pos.load_pool_index(SNIP_OUT)
    titled = 0
    for item in packet:
        assert item["human"] == ""
        for side in ("list_a", "list_b"):
            for entry in item[side]:
                src = index[item["id"]][entry["url"]]
                assert entry["title"] == src["title"]
                assert entry["snippet"] == src["snippet"]
                if entry["title"]:
                    titled += 1
    assert titled > 0
    raw = next(
        json.loads(line)
        for line in SNIP_OUT.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("id") == "p1-001"
    )
    blocked = next(
        (cand for cand in raw["candidates"] if cand["fetch"] != "ok" and cand["title"]),
        None,
    )
    if blocked is not None:
        found = False
        for item in packet:
            if item["id"] != "p1-001":
                continue
            for side in ("list_a", "list_b"):
                for entry in item[side]:
                    if entry["url"] == blocked["url"]:
                        assert entry["title"] == ""
                        assert entry["snippet"] == ""
                        found = True
        assert found


def test_committed_snip_and_deep_shortlists_match_frozen_urls():
    _assert_artifact(SNIP, SNIP_OUT, "v1.0.0-snip")
    _assert_artifact(DEEP, DEEP_OUT, "v1.0.0-deep")
    snip_meta = json.loads(SNIP_OUT.with_suffix(".meta.json").read_text(encoding="utf-8"))
    deep_meta = json.loads(DEEP_OUT.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert snip_meta["mode"] == "snip"
    assert deep_meta["mode"] == "deep"
    assert snip_meta["source_dir"].endswith("published/v1.0.0-snip")
    assert deep_meta["source_dir"].endswith("published/v1.0.0-first-run")
