"""RFC 9457 problem+json errors (code + message + hint) for every API 4xx/5xx."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.agent_ready import HTML_404, MARKDOWN_404, origin_from, prefers_markdown
from apps.api.rate_limit import limiter

STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    410: "GONE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}

HINTS: dict[str, str] = {
    "BAD_REQUEST": "Check request fields against /openapi.json. mode must be 'snip' or 'deep'.",
    "UNAUTHORIZED": "Use OAuth (see /auth.md) or Authorization: Bearer $AGENT_SEEK_API_KEY.",
    "FORBIDDEN": "Token is valid but missing the required OAuth scope. See /auth.md.",
    "NOT_FOUND": "Unknown path. See /llms.txt, /sitemap.xml, /docs, or GET /v1.",
    "METHOD_NOT_ALLOWED": "Use the method documented in /openapi.json.",
    "GONE": "This API version is not published. Use /v1. See /docs/versioning.md.",
    "VALIDATION_ERROR": "q is required (1–500 chars); k 1–25; max_candidates 1–100. See /openapi.json.",
    "RATE_LIMITED": "Wait Retry-After seconds, then retry. When Upstash is enabled, the live burst limit is per client IP (default 60 requests/minute).",
    "DEMO_EXHAUSTED": "The free website demo allowance is used up for this client. Clone the repo and run locally — there is no time-based reset. REST search and MCP search_web share this per-IP quota.",
    "INTERNAL_ERROR": "Retry once with backoff. If it persists, see /contact.",
    "UPSTREAM_ERROR": "Discover provider failed. Retry with backoff.",
    "SERVICE_UNAVAILABLE": "Server is missing upstream configuration (YDC_API_KEY), or the rate limiter is unavailable. Retry with backoff.",
    "UPSTREAM_TIMEOUT": "Upstream timed out. Retry with backoff or a smaller max_candidates.",
    "INSUFFICIENT_SCOPE": "Request search:read (or use the operator API key). See /auth.md.",
    "UNSUPPORTED_VERSION": "Agent Seek HTTP API is /v1. /v2 is not published. See /docs/versioning.md.",
}

DETAIL_CODE: dict[str, str] = {
    "Unauthorized": "UNAUTHORIZED",
    "Missing or invalid API key": "UNAUTHORIZED",
    "YDC_API_KEY not configured": "SERVICE_UNAVAILABLE",
    "mode must be 'snip' or 'deep'": "BAD_REQUEST",
    "Upstream timeout": "UPSTREAM_TIMEOUT",
    "Upstream discover failed": "UPSTREAM_ERROR",
    "Rate limit exceeded": "RATE_LIMITED",
    "Free demo allowance used up": "DEMO_EXHAUSTED",
    "Rate limiter unavailable": "SERVICE_UNAVAILABLE",
    "Server misconfigured": "INTERNAL_ERROR",
    "Insufficient scope": "INSUFFICIENT_SCOPE",
}

# Paths that must never return HTML/markdown errors (Ora probes these for JSON).
API_ERROR_PREFIXES = (
    "/api",
    "/v1",
    "/v2",
    "/oauth2",
    "/mcp",
    "/health",
    "/agent/",
    "/.well-known/mcp",
    "/.well-known/oauth",
)

PROBLEM_JSON = "application/problem+json"


def is_api_error_path(path: str) -> bool:
    if path in {"/api", "/v1", "/v2", "/mcp", "/health"}:
        return True
    return path.startswith(API_ERROR_PREFIXES)


def problem_type(origin: str, code: str) -> str:
    slug = code.lower().replace("_", "-")
    base = origin.rstrip("/") if origin else ""
    return f"{base}/errors/{slug}" if base else f"/errors/{slug}"


def error_payload(
    status: int,
    message: str,
    *,
    code: str | None = None,
    detail: Any = None,
    instance: str | None = None,
    origin: str = "",
) -> dict[str, Any]:
    resolved = code or DETAIL_CODE.get(message) or STATUS_CODES.get(status, "ERROR")
    hint = HINTS.get(resolved, "See /docs and /openapi.json.")
    title = resolved.replace("_", " ").title()
    detail_text = message if isinstance(message, str) and message else title
    body: dict[str, Any] = {
        "type": problem_type(origin, resolved),
        "title": title,
        "status": status,
        "detail": detail_text,
        "instance": instance or "/",
        "code": resolved,
        "message": message,
        "hint": hint,
        "error": {
            "code": resolved,
            "message": message,
            "hint": hint,
        },
    }
    if detail is not None and detail != message:
        body["errors"] = detail
    return body


def _rate_headers() -> dict[str, str]:
    return {
        "RateLimit": f"limit={limiter.limit}, remaining={limiter.limit}, reset=60",
        "RateLimit-Policy": f"{limiter.limit};w=60",
    }


def _www_authenticate(request: Request | None) -> str:
    from apps.api.oauth import www_authenticate

    if request is not None:
        return www_authenticate(request)
    return 'Bearer resource_metadata="/.well-known/oauth-protected-resource"'


def json_error(
    status: int,
    message: str,
    *,
    code: str | None = None,
    detail: Any = None,
    headers: dict[str, str] | None = None,
    request: Request | None = None,
) -> JSONResponse:
    resolved = code or DETAIL_CODE.get(message) or STATUS_CODES.get(status, "ERROR")
    extra = dict(headers or {})
    extra.update({k: v for k, v in _rate_headers().items() if k not in extra})
    if status == 401 and "www-authenticate" not in {k.lower() for k in extra}:
        extra["WWW-Authenticate"] = _www_authenticate(request)
    if resolved == "DEMO_EXHAUSTED":
        extra = {k: v for k, v in extra.items() if k.lower() != "retry-after"}
    elif status == 429 and "retry-after" not in {k.lower() for k in extra}:
        extra["Retry-After"] = "60"
    origin = origin_from(request) if request is not None else ""
    instance = request.url.path if request is not None else "/"
    return JSONResponse(
        status_code=status,
        content=error_payload(
            status,
            message,
            code=code,
            detail=detail,
            instance=instance,
            origin=origin,
        ),
        headers=extra,
        media_type=PROBLEM_JSON,
    )


def _http_message(exc: StarletteHTTPException) -> str:
    d = exc.detail
    if isinstance(d, str) and d:
        return d
    if exc.status_code == 404:
        return "Not found"
    return STATUS_CODES.get(exc.status_code, "Error").replace("_", " ").title()


def _wants_problem_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept or "application/problem+json" in accept


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse | PlainTextResponse | HTMLResponse:
    path = request.url.path
    if exc.status_code == 404 and not is_api_error_path(path) and not _wants_problem_json(request):
        if prefers_markdown(request):
            return PlainTextResponse(
                MARKDOWN_404,
                status_code=404,
                media_type="text/markdown; charset=utf-8",
            )
        return HTMLResponse(HTML_404, status_code=404)
    headers = dict(exc.headers or {})
    return json_error(exc.status_code, _http_message(exc), detail=exc.detail, headers=headers, request=request)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return json_error(
        422,
        "Request validation failed",
        code="VALIDATION_ERROR",
        detail=exc.errors(),
        request=request,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return json_error(500, "Internal server error", code="INTERNAL_ERROR", request=request)
