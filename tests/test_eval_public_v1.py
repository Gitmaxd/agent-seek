"""Offline structure tests for evals/public_v1 (no live APIs)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evals" / "public_v1"
SCRIPT = ROOT / "scripts" / "eval_llm_judge.py"
BANNED = re.compile(r"(?i)\b(agent[-\s]?seek|typesafe|gitmaxd|sieve|jev)\b")


def _load_harness():
    spec = importlib.util.spec_from_file_location("eval_llm_judge", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_suite_layout_exists():
    for rel in (
        "README.md",
        "meta.json",
        "queries.json",
        "judge/PROMPT_v1.md",
        "judge/schema.json",
        "judge/example.json",
        "results/.gitkeep",
        "results/.gitignore",
        "results/README.md",
    ):
        assert (SUITE / rel).is_file(), rel
    assert SCRIPT.is_file()
    assert not (ROOT / "apps" / "web" / "eval.html").exists()


def test_queries_frozen_50_unique_tier_counts():
    queries = _load_json(SUITE / "queries.json")
    assert isinstance(queries, list)
    assert len(queries) == 50
    ids = [q["id"] for q in queries]
    assert ids == [f"p1-{i:03d}" for i in range(1, 51)]
    assert len(set(ids)) == 50
    assert len({q["q"] for q in queries}) == 50
    for q in queries:
        assert set(q) == {"id", "q", "tier", "intent"}
        assert q["tier"] in {"L1", "L2", "L3"}
        assert q["q"].strip()
        assert q["intent"].strip()
        assert not BANNED.search(q["q"])
        assert not BANNED.search(q["intent"])
    counts = Counter(q["tier"] for q in queries)
    assert counts == {"L1": 15, "L2": 20, "L3": 15}


def test_l3_046_defensive_wording_and_041_source_quality():
    by_id = {q["id"]: q for q in _load_json(SUITE / "queries.json")}
    assert (
        by_id["p1-046"]["q"]
        == "What is prompt injection? defensive overview for LLM applications"
    )
    assert "Wikipedia" in by_id["p1-041"]["q"]
    assert "Transformer" in by_id["p1-041"]["q"]
    assert by_id["p1-041"]["q"] != by_id["p1-046"]["q"]


def test_meta_judge_pin():
    meta = _load_json(SUITE / "meta.json")
    assert meta["suite_id"] == "agent-seek-public-v1"
    assert meta["version"] == "1.0.0"
    assert meta["k"] == 10
    assert meta["max_candidates"] == 50
    assert meta["mode_default"] == "deep"
    assert meta["baseline"] == "you_com_order"
    assert meta["treatment"] == "agent_seek_cascade"
    judge = meta["judge"]
    assert judge["model"] == "gpt-5.6-sol"
    assert judge["reasoning_effort"] == "medium"
    assert judge["reasoning_mode"] == "standard"
    assert judge["api"] == "responses"
    assert judge["prompt_version"] == "v1"
    assert "mapping stored in run output" in meta["blinding"]


def test_judge_schema_validates_example():
    harness = _load_harness()
    schema = _load_json(SUITE / "judge" / "schema.json")
    example = _load_json(SUITE / "judge" / "example.json")
    verdict = harness.validate_verdict(example, schema)
    assert verdict.winner == "A"
    assert 0 <= verdict.confidence <= 1
    assert schema["properties"]["winner"]["enum"] == ["A", "B", "tie"]
    for key in (
        "winner",
        "confidence",
        "rationale",
        "a_first_relevant_rank",
        "b_first_relevant_rank",
    ):
        assert key in schema["required"]
        assert key in schema["properties"]
    assert schema.get("additionalProperties") is False

    bad = {**example, "winner": "C"}
    try:
        harness.validate_verdict(bad, schema)
        raise AssertionError("expected invalid winner to fail")
    except Exception:
        pass


def test_judge_prompt_contract():
    prompt = (SUITE / "judge" / "PROMPT_v1.md").read_text(encoding="utf-8")
    assert "JSON only" in prompt
    assert "never invent" in prompt.lower() or "Do not invent" in prompt
    assert "instruction-hijack" in prompt or "prompt-injection" in prompt
    assert '"A"' in prompt and '"B"' in prompt and "tie" in prompt


def test_results_gitignore_keeps_gitkeep():
    gi = (SUITE / "results" / ".gitignore").read_text(encoding="utf-8")
    assert "run_*" in gi
    assert (SUITE / "results" / ".gitkeep").is_file()
    run_dirs = [p for p in (SUITE / "results").iterdir() if p.name.startswith("run_")]
    assert run_dirs == []


def test_no_invented_results_json():
    assert not (SUITE / "results.json").exists()
    assert not (SUITE / "results" / "results.json").exists()


def test_assign_and_map_winner():
    harness = _load_harness()
    a = harness.assign_labels("p1-001", seed=0)
    assert set(a) == {"A", "B"}
    assert set(a.values()) == {"baseline", "agent_seek"}
    assert a["A"] != a["B"]
    assert harness.map_winner("tie", a) == "tie"
    assert harness.map_winner("A", a) == a["A"]
    assert harness.map_winner("B", a) == a["B"]
    b = harness.assign_labels("p1-001", seed=0)
    assert a == b
    other = harness.assign_labels("p1-002", seed=0)
    # Different query ids must be allowed to flip; just lock reproducibility.
    assert harness.assign_labels("p1-002", seed=0) == other


def test_build_judge_request_pins_sol_medium_standard():
    harness = _load_harness()
    schema = _load_json(SUITE / "judge" / "schema.json")
    req = harness.build_judge_request(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        reasoning_mode="standard",
        prompt="Judge the lists.",
        user_message="Query: example\n\nList A:\n(empty)\n\nList B:\n(empty)\n",
        schema=schema,
    )
    assert req["model"] == "gpt-5.6-sol"
    assert req["reasoning"] == {"effort": "medium", "mode": "standard"}
    assert "temperature" not in req
    fmt = req["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == "judge_verdict"
    assert fmt["strict"] is True
    assert "$schema" not in fmt["schema"]
    assert fmt["schema"]["required"] == schema["required"]


def test_parse_judge_json_strips_fences():
    harness = _load_harness()
    schema = _load_json(SUITE / "judge" / "schema.json")
    raw = (
        "```json\n"
        + json.dumps(
            {
                "winner": "tie",
                "confidence": 0.5,
                "rationale": "Both lists lead with the same official document.",
                "a_first_relevant_rank": 1,
                "b_first_relevant_rank": 1,
            }
        )
        + "\n```"
    )
    v = harness.parse_judge_json(raw, schema)
    assert v.winner == "tie"


def test_summarize_by_tier():
    harness = _load_harness()
    rows = [
        {"tier": "L1", "mapped_winner": "agent_seek", "error": None},
        {"tier": "L1", "mapped_winner": "baseline", "error": None},
        {"tier": "L2", "mapped_winner": "tie", "error": None},
        {"tier": "L3", "mapped_winner": None, "error": "judge:boom"},
    ]
    s = harness.summarize(rows, suite_id="agent-seek-public-v1")
    assert s["n"] == 4
    assert s["agent_seek_wins"] == 1
    assert s["baseline_wins"] == 1
    assert s["ties"] == 1
    assert s["errors"] == 1
    assert s["by_tier"]["L1"]["n"] == 2
    assert s["by_tier"]["L3"]["errors"] == 1


def test_dry_run_needs_no_keys():
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
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--limit", "2"],
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
    assert "gpt-5.6-sol" in out
    assert "reasoning.effort=medium" in out
    assert "p1-001" in out
    assert "p1-002" in out
    assert "p1-003" not in out


def test_help_lists_entrypoints():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--limit" in proc.stdout
    assert "--from-pools" in proc.stdout
    assert "--replay-run" in proc.stdout
    assert "--mode" in proc.stdout


def test_pool_serialize_roundtrip_snip_fields():
    harness = _load_harness()
    raw = [
        {
            "id": "c0",
            "title": "FastAPI docs",
            "url": "https://example.com/a",
            "snippet": "Depends()",
            "raw_rank": 1,
            "provider": "you.com",
        },
        {
            "id": "c1",
            "title": "Guide",
            "url": "https://example.com/b",
            "snippet": "tutorial",
            "raw_rank": 2,
            "provider": "you.com",
        },
    ]
    dumped = harness.pool_from_candidates(raw)
    assert list(dumped[0])[:6] == list(harness.POOL_FIELDS)
    for key in harness.POOL_FIELDS:
        assert key in dumped[0]
    assert "body" not in dumped[0]
    cands = harness.candidates_from_pool(dumped)
    assert [c.id for c in cands] == ["c0", "c1"]
    assert cands[0].url == "https://example.com/a"
    assert cands[0].snippet == "Depends()"
    assert cands[0].raw_rank == 1


def test_write_run_persists_pools_jsonl(tmp_path):
    harness = _load_harness()
    pool = [
        {
            "id": "c0",
            "title": "T",
            "url": "https://ex.test/",
            "snippet": "s",
            "raw_rank": 1,
            "provider": "you.com",
        }
    ]
    rows = [
        harness.row_payload(
            {"id": "p1-001", "q": "example query", "tier": "L1", "intent": "x"},
            pool=pool,
        )
    ]
    dest = harness.write_run(
        out_dir=tmp_path,
        run_meta={"run_id": "TESTPOOL1"},
        rows=rows,
        summary=harness.summarize(rows, suite_id="agent-seek-public-v1"),
    )
    sidecar = dest / "pools.jsonl"
    assert sidecar.is_file()
    rec = json.loads(sidecar.read_text(encoding="utf-8").splitlines()[0])
    assert rec["id"] == "p1-001"
    assert rec["q"] == "example query"
    assert rec["candidates"][0]["id"] == "c0"
    assert rec["candidates"][0]["url"] == "https://ex.test/"
    for key in harness.POOL_FIELDS:
        assert key in rec["candidates"][0]
    per_query = json.loads((dest / "per_query.jsonl").read_text(encoding="utf-8"))
    assert per_query["pool"][0]["url"] == "https://ex.test/"
    loaded = harness.pools_from_run_dir(dest)
    assert loaded["p1-001"][0]["id"] == "c0"
    from_flag = harness.resolve_replay_pools(
        harness.parse_args(["--from-pools", str(sidecar)])
    )
    assert from_flag["p1-001"][0]["snippet"] == "s"


def test_published_first_run_has_no_frozen_pools():
    published = SUITE / "published" / "v1.0.0-first-run"
    assert not (published / "pools.jsonl").exists()
    harness = _load_harness()
    try:
        harness.pools_from_run_dir(published)
        raise AssertionError("published first-run must not invent frozen pools")
    except FileNotFoundError as e:
        assert "v1.0.0-first-run" in str(e) or "no frozen" in str(e)


def test_dry_run_replay_mentions_frozen_pools(tmp_path):
    pools = tmp_path / "pools.jsonl"
    pools.write_text(
        json.dumps(
            {
                "id": "p1-001",
                "q": "FastAPI dependency injection tutorial",
                "tier": "L1",
                "candidates": [
                    {
                        "id": "c0",
                        "title": "T",
                        "url": "https://ex.test/",
                        "snippet": "s",
                        "raw_rank": 1,
                        "provider": "you.com",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
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
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--limit",
            "1",
            "--mode",
            "snip",
            "--from-pools",
            str(pools),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DRY-RUN" in proc.stdout
    assert "no APIs called" in proc.stdout
    assert "Replay: frozen pools" in proc.stdout
    assert "mode=snip" in proc.stdout
    assert "YDC_API_KEY" not in proc.stdout
