"""Fetch URL main text for deep Stage B. Caps bytes/time/chars. No host special-cases."""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

logger = logging.getLogger("agent_seek.fetch.page")

DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_BYTES = 200_000
DEFAULT_MAX_CHARS = 8_000
USER_AGENT = "AgentSeekBot/0.1 (+https://github.com/gitmaxd/agent-seek; deep-stage-b)"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return " ".join(self._chunks)


def html_to_text(html: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Strip tags/scripts; collapse whitespace; truncate."""
    if not html:
        return ""
    # Drop obvious non-content blocks early
    cleaned = re.sub(
        r"(?is)<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>",
        " ",
        html,
    )
    parser = _TextExtractor()
    try:
        parser.feed(cleaned)
        parser.close()
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", cleaned)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


async def fetch_main_text(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_chars: int = DEFAULT_MAX_CHARS,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """
    GET url and return extracted main text, or None on failure.
    Never raises for network/parse errors — deep Stage B falls back to snippet.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    owns = client is None
    http = client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        resp = await http.get(url)
        if resp.status_code >= 400:
            logger.debug("fetch %s status %s", url, resp.status_code)
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text/" not in ctype and ctype:
            # allow empty content-type; skip obvious binaries
            if any(x in ctype for x in ("pdf", "image/", "octet-stream", "zip", "json")):
                return None
        raw = resp.content[:max_bytes]
        try:
            html = raw.decode(resp.encoding or "utf-8", errors="replace")
        except Exception:
            html = raw.decode("utf-8", errors="replace")
        text = html_to_text(html, max_chars=max_chars)
        return text or None
    except Exception as e:
        logger.debug("fetch failed %s: %s", url, e)
        return None
    finally:
        if owns:
            await http.aclose()
