"""Offline tests for side-swap counting and the blind human packet."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evals" / "public_v1"
SCRIPT = ROOT / "scripts" / "eval_llm_judge.py"
POSITION = ROOT / "scripts" / "eval_position.py"
HUMAN = ROOT / "scripts" / "eval_human_packet.py"
SNIP = SUITE / "published" / "v1.0.0-snip"
PACKET_DIR = SUITE / "human_v1"


def _load(path: Path, name: str):
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _position():
    return _load(POSITION, "eval_position")


def _harness():
    return _load(SCRIPT, "eval_llm_judge")


def _rows(pos):
    rows, _meta = pos.load_published_dir(SNIP)
    return rows


def test_swap_keeps_arms_and_flips_labels():
    pos = _position()
    assignment = {"A": "baseline", "B": "agent_seek"}
    baseline = [{"rank": 1, "url": "https://b.example/1", "title": "", "snippet": ""}]
    treatment = [{"rank": 1, "url": "https://t.example/1", "title": "T", "snippet": "s"}]
    shows = pos.presentations(assignment, baseline, treatment)
    assert shows["original"]["A"][0]["url"] == "https://b.example/1"
    assert shows["original"]["B"][0]["url"] == "https://t.example/1"
    assert shows["swapped"]["A"][0]["url"] == "https://t.example/1"
    assert shows["swapped"]["B"][0]["url"] == "https://b.example/1"
    assert shows["swapped"]["assignment"] == {"A": "agent_seek", "B": "baseline"}
    # Content-consistent judge: the treatment list wins under both labels.
    original_arm = pos.map_winner("B", shows["original"]["assignment"])
    swapped_arm = pos.map_winner("A", shows["swapped"]["assignment"])
    assert original_arm == swapped_arm == "agent_seek"
    assert pos.classify_pair(original_arm, swapped_arm)["agree"] is True
    assert pos.classify_pair(original_arm, swapped_arm)["flip"] is False
    # Always picking the label A is a flip (position, not content).
    always_a = pos.classify_pair(
        pos.map_winner("A", shows["original"]["assignment"]),
        pos.map_winner("A", shows["swapped"]["assignment"]),
    )
    assert always_a["flip"] is True
    assert always_a["agree"] is False
    assert always_a["hardened"] is None


def test_tie_agrees_only_with_tie_and_errors_are_incomplete():
    pos = _position()
    both_ties = pos.classify_pair("tie", "tie")
    assert both_ties["agree"] is True
    assert both_ties["flip"] is False
    assert both_ties["hardened"] == "tie"
    mixed = pos.classify_pair("tie", "agent_seek")
    assert mixed["flip"] is True
    assert mixed["hardened"] is None
    missing = pos.classify_pair(None, "agent_seek")
    assert missing["status"] == "incomplete"
    assert missing["agree"] is False
    assert missing["flip"] is False


def test_summarize_double_agreeing_only_and_flip_rate():
    pos = _position()
    rows = [
        {"mapped_original": "agent_seek", "mapped_swapped": "agent_seek"},
        {"mapped_original": "baseline", "mapped_swapped": "baseline"},
        {"mapped_original": "tie", "mapped_swapped": "tie"},
        {"mapped_original": "agent_seek", "mapped_swapped": "baseline"},
        {"mapped_original": "tie", "mapped_swapped": "agent_seek"},
        {"mapped_original": None, "mapped_swapped": "agent_seek"},
    ]
    summary = pos.summarize_double(rows, suite_id="agent-seek-public-v1", mode="snip")
    assert summary["kind"] == "double_judge"
    assert summary["n"] == 6
    assert summary["both_verdicts"] == 5
    assert summary["flips"] == 2
    assert summary["flip_rate"] == 2 / 5
    assert summary["agreeing"] == 3
    assert summary["agent_seek_wins"] == 1
    assert summary["baseline_wins"] == 1
    assert summary["ties"] == 1
    assert summary["errors"] == 1
    assert summary["judged"] == 3
    assert summary["agreeing"] + summary["flips"] + summary["errors"] == summary["n"]


def test_pools_attach_title_without_reordering():
    pos = _position()
    row = {
        "id": "p1-001",
        "q": "q",
        "assignment": {"A": "baseline", "B": "agent_seek"},
        "baseline_urls": ["https://ex.test/a", "https://ex.test/c"],
        "treatment_urls": ["https://ex.test/b"],
        "mapped_winner": "agent_seek",
        "judge": {"winner": "B"},
    }
    index = {
        "p1-001": {
            "https://ex.test/a": {"title": "Alpha", "snippet": "docs"},
        }
    }
    prepared = pos.prepare_query(row, pool_index=index)
    assert [it["url"] for it in prepared["baseline"]] == [
        "https://ex.test/a",
        "https://ex.test/c",
    ]
    assert prepared["baseline"][0]["title"] == "Alpha"
    assert prepared["baseline"][0]["snippet"] == "docs"
    assert prepared["baseline"][1]["title"] == ""
    assert prepared["treatment"][0]["title"] == ""
    assert prepared["shortlist_text"] == "title_snippet"


def test_pool_index_drops_titles_from_failed_fetches(tmp_path: Path):
    pos = _position()
    path = tmp_path / "pools.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "p1-001",
                "candidates": [
                    {
                        "url": "https://ex.test/ok",
                        "title": "Real title",
                        "snippet": "Real snippet",
                        "fetch": "ok",
                    },
                    {
                        "url": "https://ex.test/blocked",
                        "title": "Attention Required! | Cloudflare",
                        "snippet": "blocked",
                        "fetch": "http_error",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    index = pos.load_pool_index(path)
    assert index["p1-001"]["https://ex.test/ok"]["title"] == "Real title"
    assert index["p1-001"]["https://ex.test/blocked"]["title"] == ""
    assert index["p1-001"]["https://ex.test/blocked"]["snippet"] == ""


def test_judge_messages_swap_urls_and_stay_blind():
    pos = _position()
    harness = _harness()
    assignment = {"A": "baseline", "B": "agent_seek"}
    baseline = [{"rank": 1, "url": "https://b.example/1", "title": "Base page", "snippet": "b"}]
    treatment = [{"rank": 1, "url": "https://t.example/1", "title": "Treat page", "snippet": "t"}]
    shows = pos.presentations(assignment, baseline, treatment)

    def message(side: dict) -> str:
        return harness.build_judge_user_message(
            "example query",
            harness._items_as_lists(side["A"]),
            harness._items_as_lists(side["B"]),
        )

    original = message(shows["original"])
    swapped = message(shows["swapped"])
    assert "agent_seek" not in original.lower()
    assert "baseline" not in original.lower()
    assert original.index("https://b.example/1") < original.index("https://t.example/1")
    assert swapped.index("https://t.example/1") < swapped.index("https://b.example/1")
    request = harness.build_judge_request(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        reasoning_mode="standard",
        prompt="prompt",
        user_message=original,
        schema={"type": "object", "properties": {}, "required": []},
    )
    assert "temperature" not in request
    assert "seed" not in request


def test_allocate_snip_mix_and_human_sample_is_stable():
    pos = _position()
    quotas = pos.allocate_quotas(
        {"agent_seek": 37, "baseline": 13, "tie": 0},
        30,
    )
    assert quotas == {"agent_seek": 22, "baseline": 8, "tie": 0}
    rows = _rows(pos)
    first, q1 = pos.stratified_sample(rows, n=30, seed=pos.HUMAN_SAMPLE_SEED)
    second, q2 = pos.stratified_sample(rows, n=30, seed=pos.HUMAN_SAMPLE_SEED)
    assert q1 == q2 == quotas
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert len(first) == 30
    assert first == sorted(first, key=lambda r: r["id"])
    counts = {"agent_seek": 0, "baseline": 0, "tie": 0}
    for row in first:
        counts[row["mapped_winner"]] += 1
    assert counts == {"agent_seek": 22, "baseline": 8, "tie": 0}


def test_committed_packet_is_blind_and_matches_sample():
    pos = _position()
    packet = pos.load_jsonl(PACKET_DIR / "packet.jsonl")
    key = pos.load_jsonl(PACKET_DIR / "key.jsonl")
    meta = json.loads((PACKET_DIR / "sample_meta.json").read_text(encoding="utf-8"))
    markdown = (PACKET_DIR / "packet.md").read_text(encoding="utf-8")
    csv_text = (PACKET_DIR / "packet.csv").read_text(encoding="utf-8")
    rows = _rows(pos)
    selected, _quotas = pos.stratified_sample(rows, n=30, seed=pos.HUMAN_SAMPLE_SEED)
    assert meta["n"] == 30
    assert meta["seed"] == pos.HUMAN_SAMPLE_SEED
    assert meta["quotas"]["agent_seek"] == 22
    assert meta["quotas"]["baseline"] == 8
    assert [item["id"] for item in packet] == [row["id"] for row in selected]
    assert [item["id"] for item in key] == [item["id"] for item in packet]
    by_id = {row["id"]: row for row in rows}
    for item, key_row in zip(packet, key):
        assert item["human"] == ""
        assert item["note"] == ""
        assert "assignment" not in item
        assert "mapped_winner" not in item
        assert "judge" not in item
        assert key_row["judge_winner"] == by_id[item["id"]]["judge"]["winner"]
        assert key_row["assignment"] == by_id[item["id"]]["assignment"]
        assert item["list_a"] and item["list_b"]
    for blob in (json.dumps(packet), markdown, csv_text):
        lowered = blob.lower()
        assert "agent_seek" not in lowered
        assert "baseline" not in lowered
        assert "you.com order" not in lowered
    assert csv_text.startswith("item,id,tier,q,human,note\n")
    assert "Human pick (A / B / tie):" in markdown


def test_kappa_known_table_and_score_refuses_blanks(tmp_path: Path):
    pos = _position()
    stats = pos.cohens_kappa(["A", "A", "B", "tie"], ["A", "B", "B", "tie"])
    assert stats["n"] == 4
    assert stats["agree"] == 3
    assert stats["agreement"] == 0.75
    assert abs(stats["p_e"] - 0.3125) < 1e-12
    assert abs(stats["kappa"] - (0.4375 / 0.6875)) < 1e-12
    assert pos.cohens_kappa(["A", "B", "tie"], ["A", "B", "tie"])["kappa"] == 1.0
    assert pos.cohens_kappa(["tie", "tie"], ["tie", "tie"])["kappa"] == 1.0

    published = [
        {
            "id": "q1",
            "assignment": {"A": "baseline", "B": "agent_seek"},
            "judge": {"winner": "A"},
            "mapped_winner": "baseline",
        },
        {
            "id": "q2",
            "assignment": {"A": "agent_seek", "B": "baseline"},
            "judge": {"winner": "A"},
            "mapped_winner": "agent_seek",
        },
        {
            "id": "q3",
            "assignment": {"A": "baseline", "B": "agent_seek"},
            "judge": {"winner": "tie"},
            "mapped_winner": "tie",
        },
        {
            "id": "q4",
            "assignment": {"A": "baseline", "B": "agent_seek"},
            "judge": {"winner": "B"},
            "mapped_winner": "agent_seek",
        },
    ]
    packet = [
        {"id": "q1", "human": "A"},
        {"id": "q2", "human": "B"},
        {"id": "q3", "human": "tie"},
        {"id": "q4", "human": "B"},
    ]
    # Human vs judge: A/A, B/A, tie/tie, B/B → agree on 3 of 4.
    scored = pos.score_human_labels(packet, pos.published_index(published))
    expected = pos.cohens_kappa(["A", "B", "tie", "B"], ["A", "A", "tie", "B"])
    assert scored["kind"] == "human_agreement"
    assert scored["labeled"] == 4
    assert scored["agree"] == 3
    assert scored["agreement"] == 0.75
    assert scored["human_mapped"] == {"agent_seek": 1, "baseline": 2, "tie": 1}
    assert abs(scored["kappa"] - expected["kappa"]) < 1e-12

    blank = tmp_path / "blank.jsonl"
    blank.write_text(json.dumps({"id": "q1", "human": ""}) + "\n", encoding="utf-8")
    out = tmp_path / "summary.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(HUMAN),
            "score",
            "--labels",
            str(blank),
            "--from-published",
            str(SNIP),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert not out.exists()
    assert "no human labels" in proc.stderr


def test_double_artifact_shape_loads_for_the_page(tmp_path: Path):
    """Writer output is the directory /eval treats as a double-judge run."""
    os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
    os.environ.setdefault("YDC_API_KEY", "test-ydc")
    os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
    from apps.api.eval_page import _is_double_complete, load_double_run

    pos = _position()
    harness = _harness()
    rows = [
        {"mapped_original": "agent_seek", "mapped_swapped": "agent_seek"},
        {"mapped_original": "agent_seek", "mapped_swapped": "baseline"},
    ]
    summary = pos.summarize_double(rows, suite_id="agent-seek-public-v1", mode="snip")
    summary["shortlist_text"] = "url_only"
    meta = {
        "run_id": "test-double",
        "double_judge": True,
        "kind": "double_judge",
        "mode": "snip",
        "judge": {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "reasoning_mode": "standard",
            "api": "responses",
            "temperature": None,
            "request_seed": None,
        },
        "harness_commit": "abc",
        "temperature": None,
    }
    harness.write_double_run(out_dir=tmp_path, run_meta=meta, rows=rows, summary=summary)
    assert _is_double_complete(tmp_path)
    loaded = load_double_run(tmp_path)
    assert loaded["mode"] == "snip"
    assert loaded["flips"] == 1
    assert loaded["both_verdicts"] == 2
    assert loaded["agreeing"] == 1
    assert loaded["as_wins"] == 1
    assert loaded["errors"] == 0
    assert json.loads((tmp_path / "run_meta.json").read_text())["judge"]["temperature"] is None
    assert "not a flip" in (tmp_path / "README.md").read_text()


def test_double_judge_dry_run_calls_no_api(tmp_path: Path):
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "OPENAI_API_KEY",
            "YDC_API_KEY",
            "TYPESAFE_API_KEY",
            "AGENT_SEEK_API_KEY",
            "AGENT_SEEK_BASE",
            "AGENT_SEEK_LIVE",
            "AGENT_SEEK_EVAL_STRICT",
        }
    }
    env["PYTHONPATH"] = str(ROOT)
    dest = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--double-judge",
            "--dry-run",
            "--from-published",
            str(SNIP),
            "--out-dir",
            str(dest),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "DRY-RUN" in out
    assert "no APIs called" in out
    assert "url_only" in out
    assert "Judge calls: 100" in out
    assert "gpt-5.6-sol" in out
    assert "reasoning.effort=medium" in out
    assert "Rediscover: no" in out
    assert not dest.exists()

    missing = subprocess.run(
        [sys.executable, str(SCRIPT), "--double-judge", "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "--from-published" in missing.stderr

    help_proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--double-judge" in help_proc.stdout
    assert "--from-published" in help_proc.stdout
    assert "--pools" in help_proc.stdout
