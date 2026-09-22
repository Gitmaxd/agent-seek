"""URL normalize + dedupe helpers."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
}


def normalize_url(url: str) -> str:
    """Normalize URL for dedupe: lowercase host, strip fragment, drop trailing slash
    (except bare origin), strip common tracking query params.
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.rstrip("/")

    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path == "":
        path = ""

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))  # no fragment


def dedupe_by_url(candidates: list, *, key: str = "url") -> list:
    """Keep first occurrence by normalized URL."""
    seen: set[str] = set()
    out = []
    for c in candidates:
        url = c.url if hasattr(c, "url") else c.get(key, "")
        norm = normalize_url(url)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(c)
    return out


def clamp_max_candidates(n: int, hard_cap: int = 100) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 50
    return max(1, min(n, hard_cap))
