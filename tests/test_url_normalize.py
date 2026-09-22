from packages.core.url_normalize import clamp_max_candidates, dedupe_by_url, normalize_url
from packages.core.models import Candidate


def test_normalize_strips_fragment_and_tracking():
    u = normalize_url("https://WWW.Example.com/path/?utm_source=x&id=1#frag")
    assert u == "https://example.com/path?id=1"


def test_normalize_trailing_slash():
    assert normalize_url("https://example.com/foo/") == "https://example.com/foo"
    assert normalize_url("https://example.com/") in (
        "https://example.com",
        "https://example.com/",
    )


def test_dedupe():
    cands = [
        Candidate(id="a", url="https://example.com/a", raw_rank=1),
        Candidate(id="b", url="https://example.com/a/", raw_rank=2),
        Candidate(id="c", url="https://example.com/b", raw_rank=3),
    ]
    out = dedupe_by_url(cands)
    assert len(out) == 2
    assert out[0].id == "a"


def test_clamp():
    assert clamp_max_candidates(500) == 100
    assert clamp_max_candidates(0) == 1
    assert clamp_max_candidates(50) == 50
