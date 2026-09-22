"""You.com Web Search discover adapter."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from packages.core.models import Candidate
from packages.core.url_normalize import clamp_max_candidates, dedupe_by_url, normalize_url

logger = logging.getLogger("agent_seek.discover.youcom")

YOUCOM_URL = "https://api.you.com/v1/search"
USER_AGENT = "Agent Seek/0.1.0 (+https://github.com/Gitmaxd/agent-seek; research-prototype)"
DEFAULT_TIMEOUT = 8.0


class YouComError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _snippet_from_hit(hit: dict[str, Any]) -> str:
    desc = hit.get("description") or hit.get("snippet") or ""
    if isinstance(desc, list):
        desc = " ".join(str(x) for x in desc if x)
    snippets = hit.get("snippets")
    if not desc and isinstance(snippets, list) and snippets:
        parts = []
        for s in snippets[:3]:
            if isinstance(s, str):
                parts.append(s)
            elif isinstance(s, dict):
                parts.append(str(s.get("text") or s.get("snippet") or ""))
        desc = " ".join(p for p in parts if p)
    return str(desc)[:600]


def parse_youcom_response(payload: dict[str, Any], *, provider: str = "you.com") -> list[Candidate]:
    """Normalize live/fixture You.com payload → Candidate list (web section preferred)."""
    results_block = payload.get("results") or payload
    web = []
    if isinstance(results_block, dict):
        web = results_block.get("web") or results_block.get("hits") or []
        if not web and isinstance(results_block.get("organic"), list):
            web = results_block["organic"]
    elif isinstance(results_block, list):
        web = results_block

    if not isinstance(web, list):
        web = []

    candidates: list[Candidate] = []
    for i, hit in enumerate(web):
        if not isinstance(hit, dict):
            continue
        url = (hit.get("url") or hit.get("link") or "").strip()
        if not url:
            continue
        title = str(hit.get("title") or hit.get("name") or url)
        snippet = _snippet_from_hit(hit)
        # Prefer already-normalized for stability but keep original url for display
        display_url = url
        candidates.append(
            Candidate(
                id=f"c{i}",
                url=display_url,
                title=title,
                snippet=snippet,
                raw_rank=i + 1,
                provider=provider,
            )
        )

    return dedupe_by_url(candidates)


class YouComDiscover:
    name = "you.com"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = YOUCOM_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("YDC_API_KEY required")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self._client = client

    async def search(self, query: str, count: int) -> list[Candidate]:
        count = clamp_max_candidates(count, 100)
        body = {"query": query, "count": count}
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            resp = await client.post(self.base_url, json=body, headers=headers)
            if resp.status_code == 401:
                raise YouComError("You.com unauthorized", status=401)
            if resp.status_code >= 400:
                raise YouComError(
                    f"You.com error {resp.status_code}",
                    status=resp.status_code,
                )
            data = resp.json()
            return parse_youcom_response(data)
        except httpx.TimeoutException as e:
            raise YouComError("You.com timeout", status=504) from e
        except YouComError:
            raise
        except Exception as e:
            raise YouComError(f"You.com request failed: {e}") from e
        finally:
            if owns_client:
                await client.aclose()
