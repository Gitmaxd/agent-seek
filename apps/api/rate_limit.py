"""Optional Upstash Redis REST rate limiter (per client IP).

Disabled when ``UPSTASH_REDIS_REST_URL`` or ``UPSTASH_REDIS_REST_TOKEN`` is
missing/empty — no Redis calls, no throttling (local/dev default).

When both are set, each search/MCP search request consumes one slot in a
60-second **sliding window** stored in Upstash (sorted set). Over the limit
returns HTTP 429. Redis/network errors fail **closed** (HTTP 503) — traffic
is not silently allowed while limiting is enabled.

A separate **lifetime website demo quota** (``INCR`` on
``agent-seek:demo:ip:{ip}``, no TTL) can also run when
``AGENT_SEEK_DEMO_MODE=enabled``, Upstash is configured, and
``AGENT_SEEK_DEMO_SEARCH_LIMIT`` is > 0 (default 5). The code default for
demo mode is ``disabled`` (local/dev unchanged). That clamp is applied to
REST website search (``/v1/search`` and ``/api/v1/search``) and to MCP
``search_web`` via ``demo_quota_dep``. Both share the same per-IP counter.
Unauthenticated MCP helper tools do not consume it.

Identity is the client IP, not the shared ``AGENT_SEEK_API_KEY`` (the public
UI uses one key, so per-key limits would punish every visitor).

IP assumption (exe / reverse-proxy): parse ``X-Forwarded-For`` hops and take
the **rightmost** public address (skip private, loopback, link-local,
reserved). Ingress is expected to **append** the connecting IP, so the
edge-appended hop is trusted — not a client-controlled leftmost address.
If no XFF hop is public, fall back to ``X-Real-IP`` then
``request.client.host``.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets
import time
from typing import Any

import httpx
from fastapi import HTTPException, Request

logger = logging.getLogger("agent_seek.rate_limit")

WINDOW_SEC = 60
REDIS_KEY_PREFIX = "agent-seek:rl:ip:"
UPSTASH_TIMEOUT_SEC = 2.0


class RateLimitBackendError(Exception):
    """Upstash Redis was configured but the REST call failed."""


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    # is_global excludes private, loopback, link-local, multicast, reserved,
    # and documentation ranges (TEST-NET) — Python 3.12 treats those as private.
    return ip.is_global


def client_ip(request: Request) -> str:
    """Best-effort client IP for rate-limit identity. See module docstring."""
    xff = request.headers.get("x-forwarded-for") or ""
    xff_hops = [part.strip() for part in xff.split(",") if part.strip()]
    for ip in reversed(xff_hops):
        if _is_public_ip(ip):
            return ip

    fallbacks: list[str] = []
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        fallbacks.append(real_ip)
    if request.client and request.client.host:
        fallbacks.append(request.client.host)

    for ip in fallbacks:
        if _is_public_ip(ip):
            return ip
    candidates = xff_hops + fallbacks
    return candidates[0] if candidates else "unknown"


def _pipeline_value(results: list[Any], index: int) -> Any:
    if index >= len(results):
        raise RateLimitBackendError("Upstash pipeline returned too few results")
    item = results[index]
    if isinstance(item, dict):
        if item.get("error"):
            raise RateLimitBackendError(str(item["error"]))
        if "result" in item:
            return item["result"]
    return item


class RateLimiter:
    """Sliding-window limiter. No-op unless Upstash URL + token are both set."""

    def __init__(self, limit_per_min: int = 60):
        self.limit = limit_per_min
        self.window_sec = WINDOW_SEC
        self._url = ""
        self._token = ""
        self._http: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url and self._token)

    def configure(
        self,
        *,
        url: str = "",
        token: str = "",
        limit_per_min: int | None = None,
    ) -> None:
        self._url = (url or "").strip().rstrip("/")
        self._token = (token or "").strip()
        if limit_per_min is not None:
            self.limit = int(limit_per_min)

    def _headers(self) -> dict[str, str]:
        remaining = 0
        reset = int(time.time()) + self.window_sec
        return {
            "Retry-After": str(self.window_sec),
            "RateLimit": f"limit={self.limit}, remaining={remaining}, reset={reset}",
            "RateLimit-Policy": f"{self.limit};w={self.window_sec}",
        }

    async def _pipeline(self, commands: list[list[Any]]) -> list[Any]:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=UPSTASH_TIMEOUT_SEC)
        try:
            response = await self._http.post(
                f"{self._url}/pipeline",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json=commands,
            )
        except httpx.HTTPError as exc:
            raise RateLimitBackendError(f"Upstash request failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise RateLimitBackendError(f"Upstash HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RateLimitBackendError("Upstash returned non-JSON") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise RateLimitBackendError(str(payload["error"]))
        if not isinstance(payload, list):
            raise RateLimitBackendError("Upstash pipeline response was not a list")
        return payload

    async def check(self, identity: str) -> tuple[int, int]:
        now = time.time()
        reset = int(now) + self.window_sec
        from apps.api.config import is_rate_limit_allowlisted

        if is_rate_limit_allowlisted(identity):
            return self.limit, reset
        if not self.enabled:
            return self.limit, reset

        key = f"{REDIS_KEY_PREFIX}{identity}"
        now_ms = int(now * 1000)
        window_ms = self.window_sec * 1000
        cutoff = now_ms - window_ms
        member = f"{now_ms}:{secrets.token_hex(8)}"

        try:
            results = await self._pipeline(
                [
                    ["ZREMRANGEBYSCORE", key, 0, cutoff],
                    ["ZADD", key, now_ms, member],
                    ["ZCARD", key],
                    ["PEXPIRE", key, window_ms],
                ]
            )
            count = int(_pipeline_value(results, 2))
        except RateLimitBackendError:
            logger.warning("rate limiter backend unavailable (fail-closed)")
            raise HTTPException(
                status_code=503,
                detail="Rate limiter unavailable",
                headers=self._headers(),
            ) from None

        remaining = max(0, self.limit - count)
        if count > self.limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "Retry-After": str(self.window_sec),
                    "RateLimit": f"limit={self.limit}, remaining=0, reset={reset}",
                    "RateLimit-Policy": f"{self.limit};w={self.window_sec}",
                },
            )
        return remaining, reset


limiter = RateLimiter()

DEMO_REDIS_KEY_PREFIX = "agent-seek:demo:ip:"
DEMO_EXHAUSTED_DETAIL = "Free demo allowance used up"


class DemoQuota:
    """Lifetime per-IP website demo allowance. No TTL / no time reset.

    Off unless ``AGENT_SEEK_DEMO_MODE=enabled``, the limit is > 0, and
    Upstash is configured. REST search and MCP ``search_web`` both call
    ``consume`` / ``demo_quota_dep`` and share this counter.
    """

    def __init__(self, limit: int = 5):
        self.limit = limit
        self.mode_enabled = False
        self._backend: RateLimiter | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            self.mode_enabled
            and self.limit > 0
            and self._backend is not None
            and self._backend.enabled
        )

    def configure(
        self,
        *,
        backend: RateLimiter | None = None,
        limit: int | None = None,
        mode: str | bool | None = None,
    ) -> None:
        if backend is not None:
            self._backend = backend
        if limit is not None:
            self.limit = int(limit)
        if mode is not None:
            from apps.api.config import is_demo_mode_enabled

            self.mode_enabled = is_demo_mode_enabled(mode)

    async def consume(self, identity: str) -> int:
        from apps.api.config import is_rate_limit_allowlisted

        if is_rate_limit_allowlisted(identity):
            return max(self.limit, 0)
        if not self.enabled:
            return max(self.limit, 0)
        if self._backend is None:
            return max(self.limit, 0)

        key = f"{DEMO_REDIS_KEY_PREFIX}{identity}"
        try:
            results = await self._backend._pipeline([["INCR", key]])
            count = int(_pipeline_value(results, 0))
        except RateLimitBackendError:
            logger.warning("demo quota backend unavailable (fail-closed)")
            raise HTTPException(
                status_code=503,
                detail="Rate limiter unavailable",
                headers=self._backend._headers(),
            ) from None

        remaining = max(0, self.limit - count)
        if count > self.limit:
            raise HTTPException(
                status_code=429,
                detail=DEMO_EXHAUSTED_DETAIL,
            )
        return remaining


demo_quota = DemoQuota()


def configure_limiter_from_settings() -> RateLimiter:
    """Apply env-backed settings. Safe to call repeatedly (tests)."""
    from apps.api.config import get_settings

    settings = get_settings()
    limiter.configure(
        url=settings.upstash_redis_rest_url,
        token=settings.upstash_redis_rest_token,
        limit_per_min=settings.agent_seek_rate_limit_per_min,
    )
    demo_quota.configure(
        backend=limiter,
        limit=settings.agent_seek_demo_search_limit,
        mode=settings.agent_seek_demo_mode,
    )
    return limiter


async def rate_limit_dep(request: Request) -> None:
    remaining, reset = await limiter.check(client_ip(request))
    request.state.rate_limit = {
        "limit": limiter.limit,
        "remaining": remaining,
        "reset": reset,
    }


async def demo_quota_dep(request: Request) -> None:
    """Lifetime per-IP demo quota after the search request validates.

    Shared by REST ``/v1/search`` (and ``/api/v1/search``) and MCP ``search_web``.
    """
    remaining = await demo_quota.consume(client_ip(request))
    request.state.demo_quota = {
        "limit": demo_quota.limit,
        "remaining": remaining,
    }
