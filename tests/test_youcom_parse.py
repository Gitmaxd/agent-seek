import json
from pathlib import Path

from packages.core.discover.youcom import parse_youcom_response

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_fixture():
    payload = json.loads((FIXTURES / "youcom_search_sample.json").read_text())
    cands = parse_youcom_response(payload)
    assert len(cands) >= 5
    assert cands[0].provider == "you.com"
    assert cands[0].raw_rank == 1
    assert "typesafe" in cands[0].url
    assert cands[0].title
    assert cands[0].snippet
