#!/usr/bin/env python3
"""HTML title and meta description for frozen published shortlists.

Reads ``baseline_urls`` and ``treatment_urls`` from a published
``per_query.jsonl`` and GETs each distinct URL. Does not call You.com
and does not rediscover. Failures stay on each candidate (``fetch``)
and in the sidecar ``*.meta.json`` counts.

  python scripts/eval_enrich_shortlists.py

  python scripts/eval_enrich_shortlists.py \\
      --from-published evals/public_v1/published/v1.0.0-snip \\
      --out evals/public_v1/enriched/v1.0.0-snip-shortlists.jsonl \\
      --label v1.0.0-snip
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "evals" / "public_v1" / "published"
ENRICHED = ROOT / "evals" / "public_v1" / "enriched"

USER_AGENT = (
    "AgentSeekEval/1.0 (+https://agentseek.dev; frozen-shortlist title enrichment)"
)
MAX_BYTES = 48_000
TIMEOUT_S = 6.0
CONNECT_TIMEOUT_S = 4.0
CONCURRENCY = 8
PER_HOST_INTERVAL_S = 0.35
TITLE_CAP = 300
SNIPPET_CAP = 600

FETCH_OK = "ok"
FETCH_EMPTY = "empty"
FETCH_NON_HTML = "non_html"
FETCH_HTTP = "http_error"
FETCH_FAILED = "failed"
FETCH_VALUES = (FETCH_OK, FETCH_EMPTY, FETCH_NON_HTML, FETCH_HTTP, FETCH_FAILED)

# Content types we do not treat as a page. octet-stream is sniffed.
_BINARY_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/octet-stream",
}
_BINARY_PREFIXES = ("image/", "audio/", "video/", "font/")

_WS = re.compile(r"\s+")
_CHARSET = re.compile(r"charset=[\"']?([\w.-]+)", re.I)

DEFAULT_JOBS: list[dict[str, Any]] = [
    {
        "label": "v1.0.0-snip",
        "published": PUBLISHED / "v1.0.0-snip",
        "out": ENRICHED / "v1.0.0-snip-shortlists.jsonl",
    },
    {
        "label": "v1.0.0-deep",
        "published": PUBLISHED / "v1.0.0-first-run",
        "out": ENRICHED / "v1.0.0-deep-shortlists.jsonl",
    },
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collapse(text: str, limit: int) -> str:
    cleaned = _WS.sub(" ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rsplit(" ", 1)[0]
    return (cut or cleaned[:limit]).rstrip() + "…"


class _HeadExtractor(HTMLParser):
    """Title and description from the head. Stops being useful after ``</head>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.og_title = ""
        self.twitter_title = ""
        self.description = ""
        self.og_description = ""
        self.twitter_description = ""
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        ad = {k.lower(): (v or "") for k, v in attrs}
        name = ad.get("name", "").lower()
        prop = ad.get("property", "").lower()
        content = ad.get("content", "")
        if not content:
            return
        if name == "description" and not self.description:
            self.description = content
        elif prop == "og:description" and not self.og_description:
            self.og_description = content
        elif name == "twitter:description" and not self.twitter_description:
            self.twitter_description = content
        elif prop == "og:title" and not self.og_title:
            self.og_title = content
        elif name == "twitter:title" and not self.twitter_title:
            self.twitter_title = content

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"} and self._skip:
            self._skip -= 1
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip or not self._in_title:
            return
        if data:
            self.title_parts.append(data)


def title_snippet_from_html(html: str) -> tuple[str, str]:
    """``<title>`` (then og/twitter title) and meta description (then og/twitter)."""
    if not html:
        return "", ""
    parser = _HeadExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return "", ""
    title = collapse(
        " ".join(parser.title_parts)
        or parser.og_title
        or parser.twitter_title,
        TITLE_CAP,
    )
    snippet = collapse(
        parser.description or parser.og_description or parser.twitter_description,
        SNIPPET_CAP,
    )
    return title, snippet


def is_binary_type(content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct:
        return False
    if ct in _BINARY_TYPES or ct.startswith(_BINARY_PREFIXES):
        return True
    return False


def looks_like_html(raw: bytes) -> bool:
    sniff = raw.lstrip()[:300].lower()
    if sniff.startswith(b"%pdf"):
        return False
    return sniff.startswith((b"<", b"\xef\xbb\xbf<"))


def decode_html(raw: bytes, content_type: str) -> str:
    charset = None
    match = _CHARSET.search(content_type or "")
    if match:
        charset = match.group(1)
    if not charset:
        head = raw[:2500].decode("ascii", errors="ignore")
        match = _CHARSET.search(head)
        if match:
            charset = match.group(1)
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_label(
    *,
    http_status: int | None,
    content_type: str,
    title: str,
    snippet: str,
    error: str | None,
    binary: bool,
) -> str:
    if error and http_status is None:
        return FETCH_FAILED
    if binary:
        return FETCH_NON_HTML
    if http_status is not None and http_status >= 400:
        return FETCH_HTTP
    if title or snippet:
        return FETCH_OK
    return FETCH_EMPTY


def empty_fetch(url: str, *, error: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": "",
        "snippet": "",
        "fetch": FETCH_FAILED,
        "http_status": None,
        "final_url": None,
        "content_type": "",
        "error": error[:300],
        "elapsed_ms": 0,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def shortlist_urls(row: dict[str, Any]) -> list[str]:
    """Baseline order, then treatment URLs not already listed. Exact strings."""
    ordered: list[str] = []
    seen: set[str] = set()
    for key in ("baseline_urls", "treatment_urls", "baseline", "treatment"):
        values = row.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            url = ""
            if isinstance(item, str):
                url = item.strip()
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            ordered.append(url)
    return ordered


def load_published(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_query = path / "per_query.jsonl"
    if not per_query.is_file():
        raise FileNotFoundError(f"{path} has no per_query.jsonl")
    rows = load_jsonl(per_query)
    meta: dict[str, Any] = {}
    meta_path = path / "run_meta.json"
    if meta_path.is_file():
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            meta = loaded
    return rows, meta


class _HostGate:
    """One in-flight request per host, then a gap before the next."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._locks: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            nxt = self._next.get(host, 0.0)
            if now < nxt:
                await asyncio.sleep(nxt - now)
            self._next[host] = time.monotonic() + self.interval_s


def _host(url: str) -> str:
    return (urlsplit(url).netloc or "").lower()


async def fetch_url(
    client: Any,
    url: str,
    *,
    sem: asyncio.Semaphore,
    gate: _HostGate,
) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        return empty_fetch(url, error="unsupported URL scheme")
    async with sem:
        await gate.wait(_host(url))
        started = time.perf_counter()
        try:
            async with client.stream("GET", url) as resp:
                status = int(resp.status_code)
                ctype_full = resp.headers.get("content-type") or ""
                ctype = ctype_full.split(";")[0].strip().lower()
                final = str(resp.url)
                binary = is_binary_type(ctype)
                buf = bytearray()
                if binary and ctype != "application/octet-stream":
                    elapsed = int((time.perf_counter() - started) * 1000)
                    return {
                        "url": url,
                        "title": "",
                        "snippet": "",
                        "fetch": FETCH_NON_HTML,
                        "http_status": status,
                        "final_url": final,
                        "content_type": ctype,
                        "error": None,
                        "elapsed_ms": elapsed,
                    }
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= MAX_BYTES or b"</head>" in buf.lower():
                        break
                elapsed = int((time.perf_counter() - started) * 1000)
        except Exception as exc:
            return empty_fetch(url, error=f"{type(exc).__name__}: {exc}")
    raw = bytes(buf)
    if ctype == "application/octet-stream" and not looks_like_html(raw):
        return {
            "url": url,
            "title": "",
            "snippet": "",
            "fetch": FETCH_NON_HTML,
            "http_status": status,
            "final_url": final,
            "content_type": ctype,
            "error": None,
            "elapsed_ms": elapsed,
        }
    if raw[:4] == b"%PDF" or raw.lstrip()[:4] == b"%PDF":
        return {
            "url": url,
            "title": "",
            "snippet": "",
            "fetch": FETCH_NON_HTML,
            "http_status": status,
            "final_url": final,
            "content_type": ctype or "application/pdf",
            "error": None,
            "elapsed_ms": elapsed,
        }
    title, snippet = title_snippet_from_html(decode_html(raw, ctype_full))
    label = fetch_label(
        http_status=status,
        content_type=ctype,
        title=title,
        snippet=snippet,
        error=None,
        binary=False,
    )
    return {
        "url": url,
        "title": title,
        "snippet": snippet,
        "fetch": label,
        "http_status": status,
        "final_url": final,
        "content_type": ctype,
        "error": None,
        "elapsed_ms": elapsed,
    }


def load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for url, rec in loaded.items():
        if isinstance(url, str) and isinstance(rec, dict) and rec.get("fetch") in FETCH_VALUES:
            out[url] = rec
    return out


def save_cache(path: Path | None, cache: dict[str, dict[str, Any]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def enrich_urls(
    urls: list[str],
    *,
    cache: dict[str, dict[str, Any]],
    cache_path: Path | None,
    concurrency: int,
    per_host_interval_s: float,
    timeout_s: float,
) -> dict[str, dict[str, Any]]:
    import httpx

    pending = [u for u in urls if u not in cache]
    print(
        f"URLs {len(urls)}  cached {len(urls) - len(pending)}  to fetch {len(pending)}",
        file=sys.stderr,
    )
    if not pending:
        return cache
    sem = asyncio.Semaphore(concurrency)
    gate = _HostGate(per_host_interval_s)
    timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "en",
        },
    ) as client:
        tasks = [
            asyncio.create_task(fetch_url(client, url, sem=sem, gate=gate))
            for url in pending
        ]
        done = 0
        for fut in asyncio.as_completed(tasks):
            rec = await fut
            cache[rec["url"]] = rec
            done += 1
            if done % 25 == 0 or done == len(pending):
                print(f"fetched {done}/{len(pending)}", file=sys.stderr)
                save_cache(cache_path, cache)
    save_cache(cache_path, cache)
    return cache


def build_rows(
    published_rows: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    *,
    label: str,
    source_dir: str,
    mode: str | None,
) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for row in published_rows:
        candidates = []
        for url in shortlist_urls(row):
            fetched = cache.get(url) or empty_fetch(url, error="not fetched")
            candidates.append(
                {
                    "url": url,
                    "title": str(fetched.get("title") or ""),
                    "snippet": str(fetched.get("snippet") or ""),
                    "fetch": fetched.get("fetch") or FETCH_FAILED,
                    "http_status": fetched.get("http_status"),
                    "final_url": fetched.get("final_url"),
                    "content_type": fetched.get("content_type") or "",
                    "error": fetched.get("error"),
                    "elapsed_ms": fetched.get("elapsed_ms") or 0,
                }
            )
        built.append(
            {
                "id": row.get("id"),
                "q": row.get("q") or "",
                "tier": row.get("tier"),
                "intent": row.get("intent"),
                "source_run": label,
                "source_dir": source_dir,
                "mode": mode,
                "candidates": candidates,
            }
        )
    return built


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in FETCH_VALUES}
    titles = 0
    snippets = 0
    urls = 0
    for row in rows:
        for cand in row["candidates"]:
            urls += 1
            label = cand.get("fetch")
            if label in counts:
                counts[label] += 1
            if cand.get("title"):
                titles += 1
            if cand.get("snippet"):
                snippets += 1
    return {
        "candidate_rows": urls,
        "with_title": titles,
        "with_snippet": snippets,
        **counts,
    }


def write_job(
    job: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    *,
    generated_at: str,
    concurrency: int,
    per_host_interval_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    published = Path(job["published"])
    rows, run_meta = load_published(published)
    mode = run_meta.get("mode")
    source_dir = rel(published)
    built = build_rows(
        rows,
        cache,
        label=job["label"],
        source_dir=source_dir,
        mode=mode if isinstance(mode, str) else None,
    )
    out = Path(job["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in built:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats = summarize_rows(built)
    meta = {
        "method": "http_html_title_meta",
        "rediscover": False,
        "youcom": False,
        "description": (
            "GET each frozen shortlist URL and read the HTML title and meta "
            "description. No You.com rediscovery. Blank title and snippet mean "
            "the fetch failed or the page had neither tag."
        ),
        "user_agent": USER_AGENT,
        "concurrency": concurrency,
        "per_host_interval_s": per_host_interval_s,
        "timeout_s": timeout_s,
        "max_bytes": MAX_BYTES,
        "generated_at": generated_at,
        "label": job["label"],
        "source_dir": source_dir,
        "mode": mode if isinstance(mode, str) else None,
        "queries": len(built),
        "distinct_urls_in_run": len({c["url"] for row in built for c in row["candidates"]}),
        "fetch_counts": {name: stats[name] for name in FETCH_VALUES},
        "with_title": stats["with_title"],
        "with_snippet": stats["with_snippet"],
        "candidate_rows": stats["candidate_rows"],
        "artifact": rel(out),
    }
    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {rel(out)}  queries={meta['queries']}  "
        f"urls={meta['distinct_urls_in_run']}  "
        f"title={meta['with_title']}  snippet={meta['with_snippet']}  "
        f"failed={meta['fetch_counts']['failed']}  "
        f"http_error={meta['fetch_counts']['http_error']}"
    )
    return meta


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-published",
        type=Path,
        default=None,
        help="One published run directory. Requires --out. Default: snip and deep.",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSONL path for --from-published")
    parser.add_argument(
        "--label",
        default=None,
        help="Run label stored on each row (default: the published directory name)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("/tmp/agent-seek-shortlist-enrich.json"),
        help="Resume file of per-URL fetch records. Not committed.",
    )
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--per-host-interval", type=float, default=PER_HOST_INTERVAL_S)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_S)
    return parser.parse_args(argv)


def jobs_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.from_published is None and args.out is None:
        return [dict(job) for job in DEFAULT_JOBS]
    if args.from_published is None or args.out is None:
        raise SystemExit("--from-published and --out must be passed together")
    label = args.label or args.from_published.name
    return [
        {
            "label": label,
            "published": args.from_published,
            "out": args.out,
        }
    ]


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    jobs = jobs_from_args(args)
    generated_at = iso_now()
    urls: list[str] = []
    seen: set[str] = set()
    for job in jobs:
        rows, _meta = load_published(Path(job["published"]))
        for row in rows:
            for url in shortlist_urls(row):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    cache = load_cache(args.cache)
    try:
        await enrich_urls(
            urls,
            cache=cache,
            cache_path=args.cache,
            concurrency=max(1, args.concurrency),
            per_host_interval_s=max(0.0, args.per_host_interval),
            timeout_s=args.timeout,
        )
    finally:
        save_cache(args.cache, cache)
    for job in jobs:
        write_job(
            job,
            cache,
            generated_at=generated_at,
            concurrency=args.concurrency,
            per_host_interval_s=args.per_host_interval,
            timeout_s=args.timeout,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
