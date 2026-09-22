import json
from pathlib import Path

from packages.core.rank.jev import parse_noul, parse_score_01

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_stage_a():
    data = json.loads((FIXTURES / "jev_stage_a_sample.json").read_text())
    answers = data["answers"]
    assert parse_noul(answers, "c0__possibly_relevant") == 0.96
    assert parse_noul(answers, "c2__likely_spam") == 0.91


def test_parse_stage_b_score_01():
    data = json.loads((FIXTURES / "jev_stage_b_sample.json").read_text())
    answers = data["answers"]
    sc = parse_score_01(answers, "c0__answerability")
    assert sc is not None
    assert 0.9 <= sc <= 1.0  # 3.7/4
    assert parse_noul(answers, "c0__on_topic") == 0.97
    assert parse_noul(answers, "c0__authority") == 0.92
    assert parse_noul(answers, "c0__states_sought_fact") == 0.85
