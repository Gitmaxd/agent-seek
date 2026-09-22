"""Offline top-3 gold scorer. No OpenAI calls."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "eval_top3.py"
FIXTURE = ROOT / "tests" / "fixtures" / "eval_top3"
SUITE = ROOT / "evals" / "public_v1"


def _load():
    name = "eval_top3"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(SCRIPT):
        return existing
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fixture_rows(mod):
    gold = mod.index_gold(FIXTURE / "gold.jsonl")
    published = mod.pos.load_jsonl(FIXTURE / "per_query.jsonl")
    cases = mod.build_cases(
        gold,
        published,
        mod.index_enrich(FIXTURE / "enrich.jsonl"),
        mod.index_page_text(FIXTURE / "page_text.jsonl"),
    )
    rows = mod.score_cases(cases, mod.load_judgments(FIXTURE / "judgments.jsonl"))
    return cases, rows


def test_fixture_hit_is_any_top3_page_and_errors_stay_out_of_the_rate():
    mod = _load()
    cases, rows = _fixture_rows(mod)
    by_id = {row["id"]: row for row in rows}
    assert by_id["q1"]["hit"] is True
    assert by_id["q1"]["first_hit_rank"] == 2
    assert by_id["q1"]["error"] is None
    assert by_id["q2"]["hit"] is False
    assert by_id["q2"]["first_hit_rank"] is None
    # q3 has two URLs and no judgments, so it is an error, not a miss.
    assert by_id["q3"]["hit"] is None
    assert by_id["q3"]["error"] == "all page judgments failed"
    assert len(by_id["q3"]["pages"]) == 2
    q1_pages = {page["url"]: page for page in by_id["q1"]["pages"]}
    assert q1_pages["https://ex.test/q1/b"]["evidence"] == "page_text"
    assert q1_pages["https://ex.test/q1/a"]["evidence"] == "title_snippet"
    assert cases[1]["pages"][0]["evidence"] == "url_only"

    summary = mod.summarize(rows, suite_id="agent-seek-public-v1", mode="snip")
    assert summary["kind"] == "top3_gold"
    assert summary["n"] == 3
    assert summary["hits"] == 1
    assert summary["misses"] == 1
    assert summary["errors"] == 1
    assert summary["scored"] == 2
    assert summary["hit_rate"] == 0.5
    assert summary["live"] is False
    assert summary["by_tier"]["L1"]["hits"] == 1
    assert summary["by_tier"]["L3"]["errors"] == 1
    assert summary["arm"] == "agent_seek"
    assert "baseline" not in summary["hit_rate_basis"]


def test_request_has_no_temperature_and_message_quotes_gold():
    mod = _load()
    cases, _rows = _fixture_rows(mod)
    page = cases[0]["pages"][1]
    message = mod.build_user_message(cases[0], page)
    assert "Depends() to inject a database handle" in message
    assert "https://ex.test/q1/b" in message
    assert "agent_seek" not in message
    schema = json.loads((SUITE / "top3" / "schema.json").read_text(encoding="utf-8"))
    prompt = (SUITE / "top3" / "PROMPT_v1.md").read_text(encoding="utf-8")
    request = mod.build_request(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        reasoning_mode="standard",
        prompt=prompt,
        user_message=message,
        schema=schema,
    )
    assert "temperature" not in request
    assert "seed" not in request
    assert request["model"] == "gpt-5.6-sol"
    assert request["reasoning"]["mode"] == "standard"
    verdict = mod.parse_verdict(
        '{"states_gold_answer": false, "confidence": 0.2, "rationale": "URL only."}'
    )
    assert verdict.states_gold_answer is False


def test_judgments_cli_writes_summary_and_dry_run_calls_no_api(tmp_path: Path):
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "YDC_API_KEY",
            "TYPESAFE_API_KEY",
            "AGENT_SEEK_API_KEY",
            "AGENT_SEEK_EVAL_STRICT",
        }
    }
    env["PYTHONPATH"] = str(ROOT)
    dest = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--gold",
            str(FIXTURE / "gold.jsonl"),
            "--from-published",
            str(FIXTURE),
            "--enrich",
            str(FIXTURE / "enrich.jsonl"),
            "--page-text",
            str(FIXTURE / "page_text.jsonl"),
            "--judgments",
            str(FIXTURE / "judgments.jsonl"),
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
    summary = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
    assert summary["hit_rate"] == 0.5
    assert summary["source"] == "judgments_file"
    assert summary["live"] is False
    meta = json.loads((dest / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["rediscover"] is False
    assert meta["youcom"] is False
    assert meta["judge"]["temperature"] is None
    assert meta["judge"]["model"] == "gpt-5.6-sol"
    results = [
        json.loads(line)
        for line in (dest / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["id"] for row in results] == ["q1", "q2", "q3"]

    dry = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stderr
    assert "DRY-RUN" in dry.stdout
    assert "no APIs called" in dry.stdout
    assert "No hit rate written" in dry.stdout
    assert "Queries: 50" in dry.stdout
    assert "Pages: 148" in dry.stdout
    assert "Rediscover: no" in dry.stdout
    assert "gpt-5.6-sol" in dry.stdout
    assert list((SUITE / "top3").glob("results/run_*")) == []
