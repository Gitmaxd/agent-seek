"""Discover → rank pipeline."""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from packages.core.cache import FileCache
from packages.core.discover.youcom import YouComDiscover, YouComError
from packages.core.models import Candidate, RankedResult, SearchMeta, SearchResponse
from packages.core.rank.cascade import cascade_rank, raw_as_ranked
from packages.core.rank.jev import JevClient, JevError
from packages.core.url_normalize import clamp_max_candidates

logger = logging.getLogger("agent_seek.pipeline")
AGENT_SEEK_VERSION = "0.1.39"


class AgentSeekPipeline:
    def __init__(
        self,
        discover: YouComDiscover,
        jev: JevClient | None,
        *,
        cache: FileCache | None = None,
        hard_cap: int = 100,
    ):
        self.discover = discover
        self.jev = jev
        self.cache = cache
        self.hard_cap = hard_cap

    async def search(
        self,
        q: str,
        *,
        k: int = 10,
        max_candidates: int = 50,
        mode: str = "snip",
        rank: str = "on",
        nocache: bool = False,
    ) -> SearchResponse:
        t0 = time.perf_counter()
        max_candidates = clamp_max_candidates(max_candidates, self.hard_cap)
        cache_hit = False
        discover_ms = 0
        rank_ms = 0
        fetch_ms = None
        cache_scope = "discover" if self.cache is not None else None

        cache_key = None
        cached = None
        if self.cache:
            q_hash = hashlib.sha256(q.encode()).hexdigest()[:16]
            cache_key = f"discover:{q_hash}:{max_candidates}:you.com"
            if not nocache:
                cached = self.cache.get(cache_key)

        if cached is not None:
            candidates = [Candidate.model_validate(c) for c in cached]
            cache_hit = True
        else:
            td0 = time.perf_counter()
            try:
                candidates = await self.discover.search(q, max_candidates)
            except YouComError:
                raise
            discover_ms = int((time.perf_counter() - td0) * 1000)
            if self.cache and cache_key:
                self.cache.set(cache_key, [c.model_dump() for c in candidates])

        ranking = "raw"
        results: list[RankedResult]
        raw_results = raw_as_ranked(candidates, len(candidates))

        if rank == "off" or self.jev is None:
            results = raw_as_ranked(candidates, k)
            ranking = "raw"
        else:
            tr0 = time.perf_counter()
            try:
                results, ranking, rank_extras = await cascade_rank(
                    self.jev, q, candidates, k=k, mode=mode
                )
            except JevError as e:
                logger.warning("Jev failed, raw_fallback: %s", e)
                results = raw_as_ranked(candidates, k)
                ranking = "raw_fallback"
                rank_extras = {}
            rank_ms = int((time.perf_counter() - tr0) * 1000)
            fetch_ms = rank_extras.get("fetch_ms")

        total_ms = int((time.perf_counter() - t0) * 1000)
        meta = SearchMeta(
            q=q,
            candidates_in=len(candidates),
            kept=len(results),
            latency_ms=total_ms,
            mode=mode,
            provider="you.com",
            agent_seek_version=AGENT_SEEK_VERSION,
            ranking=ranking,
            discover_ms=discover_ms or None,
            rank_ms=rank_ms or None,
            fetch_ms=fetch_ms if ranking != "raw" else None,
            cache_hit=cache_hit,
            cache_scope=cache_scope,
        )
        return SearchResponse(
            results=results,
            meta=meta,
            raw_results=raw_results[: max(k, 25)],
        )
