import pytest
from pydantic import ValidationError

from packages.core.models import SearchRequest


def test_request_defaults():
    r = SearchRequest(q="hello")
    assert r.k == 10
    assert r.max_candidates == 50
    assert r.mode == "snip"


def test_request_null_or_blank_mode_is_snip():
    assert SearchRequest(q="hello", mode=None).mode == "snip"
    assert SearchRequest(q="hello", mode="").mode == "snip"
    assert SearchRequest(q="hello", mode="deep").mode == "deep"


def test_request_clamp_helper():
    r = SearchRequest(q="hello", max_candidates=100)
    assert r.clamped_max_candidates(100) == 100


def test_q_required():
    with pytest.raises(ValidationError):
        SearchRequest(q="")
