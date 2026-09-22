"""Soft near-dupe collapse: title+snippet key and blog↔apex/blog host aliases."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from packages.core.models import Candidate

_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    return _WS.sub(" ", (title or "").strip().lower())


def normalize_snippet(snippet: str) -> str:
    return _WS.sub(" ", (snippet or "").strip().lower())


def soft_content_key(title: str, snippet: str) -> str:
    snip = normalize_snippet((snippet or "")[:160])
    return f"{normalize_title(title)}||{snip}"


def host_path_alias_key(url: str) -> str:
    """Canonical key: blog.<apex>/P ≡ <apex>/blog/P (www stripped)."""
    if not url or not isinstance(url, str):
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = ""

    if host.startswith("blog.") and host.count(".") >= 2:
        apex = host[len("blog.") :]
        if path == "/blog" or path.startswith("/blog/"):
            return f"{apex}{path}"
        if not path.startswith("/"):
            path = "/" + path
        return f"{apex}/blog{path}" if path != "/" else f"{apex}/blog"
    return f"{host}{path}"


def _better(
    a: tuple[Candidate, float, list[str]],
    b: tuple[Candidate, float, list[str]],
) -> bool:
    """True if a should replace b (higher score; tie → lower raw_rank)."""
    ca, sa, _ = a
    cb, sb, _ = b
    if sa > sb:
        return True
    if sa < sb:
        return False
    return ca.raw_rank < cb.raw_rank


def _collapse_by_key(
    scored: list[tuple[Candidate, float, list[str]]],
    key_fn,
) -> list[tuple[Candidate, float, list[str]]]:
    best: dict[str, tuple[Candidate, float, list[str]]] = {}
    order: list[str] = []
    for item in scored:
        c, _sc, _fl = item
        k = key_fn(item)
        if not k:
            # empty key: keep as unique by id
            k = f"__id__:{c.id}"
        if k not in best:
            best[k] = item
            order.append(k)
        elif _better(item, best[k]):
            best[k] = item
    return [best[k] for k in order]


def collapse_near_dupes(
    scored: list[tuple[Candidate, float, list[str]]],
) -> list[tuple[Candidate, float, list[str]]]:
    """Drop near-dupes: same soft content key, then blog↔apex/blog path aliases."""
    if not scored:
        return scored
    after_soft = _collapse_by_key(
        scored,
        lambda item: soft_content_key(item[0].title, item[0].snippet),
    )
    return _collapse_by_key(
        after_soft,
        lambda item: host_path_alias_key(item[0].url),
    )
