"""Agent Seek FastAPI application."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.agent_ready import (
    PUBLIC_ORIGIN,
    agent_mode_document,
    homepage_headers,
    is_ai_bot_ua,
    origin_from,
    prefers_markdown,
    read_agent,
    register_agent_ready,
    render_homepage,
)
from apps.api.auth import require_api_key
from apps.api.config import get_settings
from apps.api.errors import (
    STATUS_CODES,
    error_payload,
    http_exception_handler,
    json_error,
    unhandled_exception_handler,
    validation_exception_handler,
)
from apps.api.mcp_server import register_mcp
from apps.api.oauth import SCOPES, register_oauth
from apps.api.rate_limit import (
    configure_limiter_from_settings,
    demo_quota_dep,
    limiter,
    rate_limit_dep,
)
from packages.core.cache import FileCache
from packages.core.discover.youcom import YouComDiscover, YouComError
from packages.core.models import (
    ApiDiscoveryResponse,
    HealthResponse,
    RankedResult,
    SearchMeta,
    SearchRequest,
    SearchResponse,
)
from packages.core.pipeline import AGENT_SEEK_VERSION, AgentSeekPipeline
from packages.core.rank.jev import JevClient

settings = get_settings()
logging.basicConfig(level=settings.agent_seek_log_level.upper())
logger = logging.getLogger("agent_seek.api")
configure_limiter_from_settings()

OPENAPI_DESCRIPTION = """
Less SEO. More signal. Agent Seek returns ranked sources; the caller writes the answer.
You.com discovers candidates, TypeSafe Jev cascade-ranks them, and `POST /v1/search`
returns a small scored list.

**Auth:** OAuth 2.0 (authorization code + PKCE S256, plus anonymous/service_auth
agent registration) **or** `Authorization: Bearer $AGENT_SEEK_API_KEY` /
`X-API-Key`. Scopes: `search:read`, `mcp:invoke`, `health:read`.
Walkthrough: `/auth.md`. Metadata: `/.well-known/oauth-authorization-server`
and `/.well-known/oauth-protected-resource`.

**Versioning:** URL versioning on `/v1`. `info.version` and `meta.agent_seek_version`
identify the prototype build. Additive JSON fields are non-breaking. Breaking
changes ship as a new path (`/v2`) and are announced with RFC 8594 `Deprecation`
and `Sunset` headers plus `/docs/versioning.md`. `/v1` has no sunset date.
Unsupported versions (for example `GET /v2` today) return
`application/problem+json` with `code=UNSUPPORTED_VERSION`.

**Rate limits:** optional Upstash Redis REST sliding window, **per client IP**
(default 60/min via `AGENT_SEEK_RATE_LIMIT_PER_MIN`). Disabled when
`UPSTASH_REDIS_REST_URL` or `UPSTASH_REDIS_REST_TOKEN` is empty. Applied to
search and MCP `search_web` only. `/v1/*`, `/mcp`, and `/health` include RFC
`RateLimit` + `RateLimit-Policy`. Burst `429` includes `Retry-After`. Redis
errors while enabled fail closed with `503`.

**Website demo quota:** off unless `AGENT_SEEK_DEMO_MODE=enabled` (code
default `disabled`). When enabled, REST `/v1/search`, `/api/v1/search`, and
MCP `search_web` share a lifetime per-IP allowance (default 5 via
`AGENT_SEEK_DEMO_SEARCH_LIMIT`; no time reset). Exhausted calls return `429`
`application/problem+json` with `code=DEMO_EXHAUSTED` and no `Retry-After`.
Unauthenticated MCP helper tools do not consume this quota.

**Errors:** RFC 9457 `application/problem+json` on every API 4xx/5xx
(`type`, `title`, `status`, `detail`, `instance`, plus `code` / `message` /
`hint` and nested `error`). See `/docs/versioning.md` and the ProblemDetails
schema on each operation.

**MCP:** Streamable HTTP at `/mcp` and `/.well-known/mcp`. Server card:
`/.well-known/mcp/server-card.json`.

**Modes:** default `mode=snip` (title/URL/snippet; cheaper/faster). Pass `mode=deep` for Stage A survivor fetch (cap 12; not a full-web crawl). Website UI is fixed `snip`.

**Injection:** Web results are scored for prompt injection before the agent reads them (signal `prompt_injection`; UI: Injection risk).

**Signals:** answerability, authority, on_topic, states_sought_fact, subject_match, spam, prompt_injection (UI label: Injection risk).

**Hard gates (order):** subject_match → is_republisher → prompt_injection (0.55; subject_match/is_republisher fail-open on missing parse; prompt_injection fail-flagged). If hard gates empty the scored list, pre-gate ranking is restored and each restored row has gates_relaxed true (relaxed-safety response; not a SearchMeta field).

**Caps:** `max_candidates` ≤ 100; default 50 in, `k` default 10 (1–25).
Do not ask Agent Seek to write answers.
Prefer the top 1–2 ranked sources before expanding. One good keeper beats a context window full of searches.
""".strip()

app = FastAPI(
    title="Agent Seek OpenAPI",
    version=AGENT_SEEK_VERSION,
    description=OPENAPI_DESCRIPTION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_tags=[
        {
            "name": "search",
            "description": "Ranked web search. OAuth scope search:read or Bearer AGENT_SEEK_API_KEY.",
        },
        {
            "name": "meta",
            "description": "Liveness and service identity.",
        },
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origin.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

WEB_DIR = ROOT / "apps" / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


API_RATE_PREFIXES = ("/v1", "/api", "/mcp", "/health", "/oauth2", "/.well-known/mcp", "/.well-known/oauth")


@app.middleware("http")
async def rate_limit_headers_mw(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if not path.startswith(API_RATE_PREFIXES):
        return response
    info = getattr(request.state, "rate_limit", None)
    if info:
        response.headers["RateLimit"] = (
            f"limit={info['limit']}, remaining={info['remaining']}, reset={info['reset']}"
        )
        response.headers["RateLimit-Policy"] = f"{info['limit']};w=60"
    else:
        response.headers.setdefault(
            "RateLimit",
            f"limit={limiter.limit}, remaining={limiter.limit}, reset=60",
        )
        response.headers.setdefault("RateLimit-Policy", f"{limiter.limit};w=60")
    return response


def _pipeline() -> AgentSeekPipeline:
    s = get_settings()
    if not s.ydc_api_key:
        raise HTTPException(status_code=503, detail="YDC_API_KEY not configured")
    discover = YouComDiscover(s.ydc_api_key)
    jev = JevClient(s.typesafe_api_key) if s.typesafe_api_key else None
    cache = FileCache(s.agent_seek_cache_dir, ttl_sec=s.agent_seek_cache_ttl_sec)
    return AgentSeekPipeline(discover, jev, cache=cache, hard_cap=s.agent_seek_max_candidates)


# Occurrence messages used by handlers / DETAIL_CODE. Example `code` is always
# STATUS_CODES[status] so OpenAPI does not reuse 401/UNAUTHORIZED for 4xx/5xx.
_ERROR_OCCURRENCE: dict[int, str] = {
    400: "mode must be 'snip' or 'deep'",
    401: "Unauthorized",
    403: "Insufficient scope",
    422: "Request validation failed",
    429: "Rate limit exceeded",
    502: "Upstream discover failed",
    503: "YDC_API_KEY not configured",
    504: "Upstream timeout",
}


def _problem_example(status: int) -> dict:
    return error_payload(
        status,
        _ERROR_OCCURRENCE[status],
        code=STATUS_CODES[status],
        instance="/v1/search",
        origin=PUBLIC_ORIGIN,
    )


ERROR_EXAMPLES = {
    400: {
        "description": "Bad request (RFC 9457 problem+json)",
        "example": _problem_example(400),
    },
    401: {
        "description": "Missing or invalid credential. WWW-Authenticate: Bearer resource_metadata=…",
        "example": _problem_example(401),
    },
    403: {
        "description": "Valid token missing required scope",
        "example": _problem_example(403),
    },
    422: {
        "description": "Validation error (RFC 9457 problem+json)",
        "example": _problem_example(422),
    },
    429: {
        "description": "Rate limited (per client IP when Upstash is enabled; default 60/min burst, Retry-After + RateLimit) or website demo quota exhausted (REST and MCP search_web share the per-IP allowance; code DEMO_EXHAUSTED; no Retry-After).",
        "example": _problem_example(429),
    },
    502: {
        "description": "Upstream discover failed",
        "example": _problem_example(502),
    },
    503: {
        "description": "Server missing YDC_API_KEY",
        "example": _problem_example(503),
    },
    504: {
        "description": "Upstream timeout",
        "example": _problem_example(504),
    },
}


# operationId → (200 response schema name, optional request schema name)
_TYPED_OP_SCHEMAS: dict[str, tuple[str, str | None]] = {
    "healthCheck": ("HealthResponse", None),
    "searchPost": ("SearchResponse", "SearchRequest"),
    "searchGet": ("SearchResponse", "SearchRequest"),
    "apiIndex": ("ApiDiscoveryResponse", None),
    "listPublicApi": ("ApiDiscoveryResponse", None),
    "sandboxSearchExample": ("SearchResponse", None),
}


def _model_openapi_schema(model: type) -> dict:
    """JSON Schema for a Pydantic model, with $defs flattened into components later."""
    return model.model_json_schema(ref_template="#/components/schemas/{model}")


def _ensure_component_model(schemas: dict, name: str, model: type) -> None:
    raw = _model_openapi_schema(model)
    defs = raw.pop("$defs", None) or raw.pop("definitions", None)
    if defs:
        for def_name, def_schema in defs.items():
            schemas.setdefault(def_name, def_schema)
    existing = schemas.get(name) or {}
    merged = {**raw, **{k: v for k, v in existing.items() if k not in raw}}
    # Prefer the generated typed object (properties + descriptions) for LLM tools.
    if raw.get("properties"):
        merged["type"] = raw.get("type") or "object"
        merged["properties"] = raw["properties"]
        if raw.get("required"):
            merged["required"] = raw["required"]
        if raw.get("description"):
            merged["description"] = raw["description"]
        if raw.get("title"):
            merged["title"] = raw["title"]
    schemas[name] = merged


def _ensure_typed_operation_schemas(schema: dict) -> None:
    """Lock request/response $ref + object properties on every public operation."""
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    _ensure_component_model(schemas, "SearchRequest", SearchRequest)
    _ensure_component_model(schemas, "SearchResponse", SearchResponse)
    _ensure_component_model(schemas, "RankedResult", RankedResult)
    _ensure_component_model(schemas, "SearchMeta", SearchMeta)
    _ensure_component_model(schemas, "HealthResponse", HealthResponse)
    _ensure_component_model(schemas, "ApiDiscoveryResponse", ApiDiscoveryResponse)

    for path_item in schema.get("paths", {}).values():
        for method, op in path_item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            oid = op.get("operationId")
            mapping = _TYPED_OP_SCHEMAS.get(oid)
            if not mapping:
                continue
            resp_name, req_name = mapping
            ok = op.setdefault("responses", {}).setdefault("200", {})
            content = ok.setdefault("content", {}).setdefault("application/json", {})
            content["schema"] = {"$ref": f"#/components/schemas/{resp_name}"}
            if req_name and method == "post":
                rb = op.setdefault("requestBody", {})
                rb.setdefault("required", True)
                rb.setdefault("description", op.get("description") or "Typed JSON request body")
                rb_content = rb.setdefault("content", {}).setdefault("application/json", {})
                rb_content["schema"] = {"$ref": f"#/components/schemas/{req_name}"}
            if req_name and method == "get":
                # Query-string twin of SearchRequest — each param keeps a typed schema.
                existing = {p.get("name"): p for p in op.get("parameters") or [] if isinstance(p, dict)}
                req_props = (schemas.get(req_name) or {}).get("properties") or {}
                req_required = set((schemas.get(req_name) or {}).get("required") or [])
                params = list(op.get("parameters") or [])
                for pname, prop in req_props.items():
                    if pname in existing:
                        existing[pname].setdefault("schema", prop)
                        existing[pname].setdefault("description", prop.get("description") or pname)
                        continue
                    params.append(
                        {
                            "name": pname,
                            "in": "query",
                            "required": pname in req_required,
                            "description": prop.get("description") or pname,
                            "schema": prop,
                        }
                    )
                op["parameters"] = params
            op.setdefault(
                "description",
                op.get("summary") or f"Agent Seek operation {oid}",
            )


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=OPENAPI_DESCRIPTION,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema["openapi"] = "3.1.0"
    schema.setdefault("components", {}).setdefault("schemas", {})
    schema["info"]["x-api-versioning"] = {
        "strategy": "url",
        "current": "v1",
        "policy": "/docs/versioning.md",
        "deprecation": "RFC 8594 Deprecation + Sunset headers at least 90 days before removal",
        "sunset": "Unsupported versions return application/problem+json with code=UNSUPPORTED_VERSION",
    }
    schema["components"]["schemas"]["ErrorBody"] = {
        "type": "object",
        "required": ["code", "message", "hint"],
        "properties": {
            "code": {"type": "string", "description": "Machine-readable error code"},
            "message": {"type": "string", "description": "Human-readable message"},
            "hint": {"type": "string", "description": "How an agent should recover"},
        },
    }
    schema["components"]["schemas"]["ProblemDetails"] = {
        "type": "object",
        "required": ["type", "title", "status", "detail", "code", "message", "hint", "error"],
        "properties": {
            "type": {"type": "string", "format": "uri", "description": "RFC 9457 problem type URI"},
            "title": {"type": "string", "description": "Short, stable problem title"},
            "status": {"type": "integer", "description": "HTTP status copy"},
            "detail": {"type": "string", "description": "Occurrence-specific explanation"},
            "instance": {"type": "string", "description": "Request path that failed"},
            "code": {"type": "string", "description": "Machine-readable error code"},
            "message": {"type": "string", "description": "Human-readable message"},
            "hint": {"type": "string", "description": "How an agent should recover"},
            "error": {"$ref": "#/components/schemas/ErrorBody"},
            "errors": {"description": "Optional validation issue list"},
        },
    }
    schema["components"]["schemas"]["ErrorResponse"] = {
        "$ref": "#/components/schemas/ProblemDetails",
    }
    schema["components"].setdefault("securitySchemes", {})["AgentSeekApiKey"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API key",
        "description": "Shared AGENT_SEEK_API_KEY. Alternate to OAuth 2.0. See /auth.md.",
    }
    schema["components"]["securitySchemes"]["OAuth2"] = {
        "type": "oauth2",
        "description": "OAuth 2.0 authorization code + PKCE (S256). See /auth.md.",
        "flows": {
            "authorizationCode": {
                "authorizationUrl": "/oauth2/authorize",
                "tokenUrl": "/oauth2/token",
                "refreshUrl": "/oauth2/token",
                "scopes": SCOPES,
            }
        },
    }
    schema["components"].setdefault("headers", {})["RateLimit"] = {
        "description": "RFC RateLimit header: limit, remaining, reset.",
        "schema": {"type": "string"},
    }
    schema["components"]["headers"]["RetryAfter"] = {
        "description": "Seconds to wait after 429.",
        "schema": {"type": "string"},
    }
    schema["components"]["headers"]["WWWAuthenticate"] = {
        "description": 'WorkOS/RFC 9728: Bearer resource_metadata="<PRM URL>" (no realm).',
        "schema": {"type": "string"},
    }
    schema["components"]["headers"]["Deprecation"] = {
        "description": "RFC 8594 Deprecation header when a version or field is retiring.",
        "schema": {"type": "string"},
    }
    schema["components"]["headers"]["Sunset"] = {
        "description": "HTTP Sunset date (IMF-fixdate) for a retiring version.",
        "schema": {"type": "string"},
    }
    err_ref = {"$ref": "#/components/schemas/ProblemDetails"}
    for path_item in schema.get("paths", {}).values():
        for method, op in path_item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            op.setdefault("description", op.get("summary") or "Agent Seek operation")
            if op.get("operationId") in {"searchPost", "searchGet"}:
                op.setdefault("security", [{"OAuth2": ["search:read"]}, {"AgentSeekApiKey": []}])
            for code, extra in ERROR_EXAMPLES.items():
                resp = op.setdefault("responses", {}).setdefault(str(code), {"description": extra["description"]})
                resp["description"] = extra["description"]
                example = extra["example"]
                resp["content"] = {
                    "application/problem+json": {"schema": err_ref, "example": example},
                    "application/json": {"schema": err_ref, "example": example},
                }
                if code == 401:
                    resp.setdefault("headers", {})["WWW-Authenticate"] = {
                        "$ref": "#/components/headers/WWWAuthenticate"
                    }
                if code == 429:
                    resp.setdefault("headers", {})["Retry-After"] = {
                        "$ref": "#/components/headers/RetryAfter"
                    }
                    resp.setdefault("headers", {})["RateLimit"] = {
                        "$ref": "#/components/headers/RateLimit"
                    }
            ok = op.setdefault("responses", {}).setdefault("200", {})
            ok.setdefault("headers", {})["RateLimit"] = {"$ref": "#/components/headers/RateLimit"}
            ok.setdefault("headers", {})["RateLimit-Policy"] = {
                "description": "Policy token, e.g. 60;w=60",
                "schema": {"type": "string"},
            }
            if "200" in op.get("responses", {}):
                ok_content = op["responses"]["200"].setdefault("content", {})
                if "application/json" not in ok_content and op.get("operationId"):
                    ok_content.setdefault("application/json", {})
    _ensure_typed_operation_schemas(schema)
    schema["servers"] = [
        {"url": PUBLIC_ORIGIN, "description": "Live Agent Seek prototype (agentseek.dev)"},
        {"url": "/", "description": "This Agent Seek host"},
    ]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[method-assign]


@app.get(
    "/health",
    tags=["meta"],
    operation_id="healthCheck",
    summary="Liveness + version",
    response_model=HealthResponse,
)
async def health() -> HealthResponse:
    """Return process liveness and `agent_seek_version` (same value as OpenAPI info.version). Zero-auth. Typed HealthResponse: ok + version."""
    return HealthResponse(ok=True, version=AGENT_SEEK_VERSION)


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def product_docs(request: Request):
    """Product documentation (humans + agents). OpenAPI Swagger lives at /api/docs."""
    if prefers_markdown(request):
        from apps.api.agent_ready import markdown_response

        return markdown_response(read_agent("docs.md"))
    docs_path = WEB_DIR / "docs.html"
    if not docs_path.exists():
        return HTMLResponse("<h1>Agent Seek</h1><p>Docs missing</p>", status_code=404)
    return HTMLResponse(docs_path.read_text(encoding="utf-8"))


@app.get("/", include_in_schema=False)
async def index(request: Request):
    origin = origin_from(request)
    headers = homepage_headers(origin)
    if request.query_params.get("mode") == "agent":
        return JSONResponse(agent_mode_document(origin), headers=headers)
    if is_ai_bot_ua(request) or prefers_markdown(request):
        from apps.api.agent_ready import markdown_response

        return markdown_response(read_agent("index.md"), extra_headers=headers)
    html = render_homepage(origin)
    return HTMLResponse(html, headers=headers)


@app.get("/config.js", include_in_schema=False)
async def config_js():
    """Same-origin UI config. Never exposes YDC/TYPESAFE keys."""
    ui_key = settings.agent_seek_ui_api_key or settings.agent_seek_api_key
    # Escape for JS string
    safe = ui_key.replace("\\", "\\\\").replace('"', '\\"')
    body = f'window.AGENT_SEEK_CONFIG = {{ apiKey: "{safe}", baseUrl: "" }};\n'
    return Response(
        content=body,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


async def website_search_limit_dep(
    _: None = Depends(require_api_key),
    __: None = Depends(rate_limit_dep),
) -> None:
    """Auth + burst limiter for website REST search. Demo quota is after validation."""


async def _run_search(req: SearchRequest) -> SearchResponse:
    if req.mode not in ("snip", "deep"):
        raise HTTPException(status_code=400, detail="mode must be 'snip' or 'deep'")
    pipe = _pipeline()
    try:
        return await pipe.search(
            req.q,
            k=req.k,
            max_candidates=req.clamped_max_candidates(settings.agent_seek_max_candidates),
            mode=req.mode,
            rank=req.rank,
            nocache=req.nocache,
        )
    except YouComError as e:
        if e.status == 504:
            raise HTTPException(status_code=504, detail="Upstream timeout") from e
        raise HTTPException(status_code=502, detail="Upstream discover failed") from e


async def _run_website_search(request: Request, req: SearchRequest) -> SearchResponse:
    """REST/UI search after SearchRequest validates. Never used by MCP."""
    await demo_quota_dep(request)
    return await _run_search(req)


@app.post(
    "/v1/search",
    response_model=SearchResponse,
    tags=["search"],
    operation_id="searchPost",
    summary="Ranked web search",
    description=(
        "Discover up to `max_candidates` (≤100) via You.com, cascade-rank with Jev, "
        "return top `k` scored results. Default `mode=snip` (title/URL/snippet; "
        "cheaper/faster). Pass `mode=deep` for Stage A survivor fetch (cap 12; "
        "not a full-web crawl). Website UI is fixed `snip`. "
        "Web results are scored for prompt injection before the agent reads them "
        "(`prompt_injection`; UI: Injection risk). "
        "If hard gates empty the scored list, pre-gate ranking is restored and "
        "each restored row has gates_relaxed true (relaxed-safety response; "
        "not a SearchMeta field). "
        "OAuth scope `search:read` or Bearer "
        "AGENT_SEEK_API_KEY. Burst rate limit: optional Upstash per client IP, "
        "default 60/min (RateLimit + Retry-After). When "
        "AGENT_SEEK_DEMO_MODE=enabled, REST /v1/search, /api/v1/search, and "
        "MCP search_web share a lifetime per-IP demo quota (default 5; 429 "
        "code DEMO_EXHAUSTED; no Retry-After). "
        "Errors use RFC 9457 application/problem+json "
        "(`type`, `title`, `status`, `detail`, `code`, `message`, `hint`)."
    ),
    responses={
        401: {"description": "Missing or invalid API key"},
        429: {"description": "Rate limited or website demo quota exhausted"},
    },
)
async def search_post(
    request: Request,
    body: SearchRequest,
    _: None = Depends(require_api_key),
    __: None = Depends(website_search_limit_dep),
):
    return await _run_website_search(request, body)


@app.get(
    "/v1/search",
    response_model=SearchResponse,
    tags=["search"],
    operation_id="searchGet",
    summary="Ranked web search (GET)",
    description=(
        "Same contract as POST /v1/search with query-string parameters. "
        "Default `mode=snip` (title/URL/snippet; cheaper/faster). "
        "Pass `mode=deep` for Stage A survivor fetch (cap 12). "
        "If hard gates empty the scored list, restored rows set gates_relaxed true. "
        "OAuth scope `search:read` or Bearer AGENT_SEEK_API_KEY."
    ),
)
async def search_get(
    request: Request,
    params: Annotated[SearchRequest, Query()],
    _: None = Depends(require_api_key),
    __: None = Depends(website_search_limit_dep),
):
    return await _run_website_search(request, params)


def _api_discovery(origin: str) -> ApiDiscoveryResponse:
    return ApiDiscoveryResponse(
        name="Agent Seek API",
        version=AGENT_SEEK_VERSION,
        description=(
            "Ranked web search: You.com discover + TypeSafe Jev cascade. "
            "Default mode=snip (title/URL/snippet; cheaper/faster). Pass mode=deep for Stage A survivor fetch (cap 12)."
        ),
        openapi=f"{origin}/openapi.json",
        docs=f"{origin}/docs",
        developers=f"{origin}/developers",
        auth=f"{origin}/auth.md",
        health=f"{origin}/health",
        search=f"{origin}/v1/search",
        search_get=f"{origin}/v1/search",
        mcp=f"{origin}/mcp",
        sandbox=f"{origin}/v1/sandbox",
        versioning=f"{origin}/docs/versioning.md",
        oauth_authorization_server=f"{origin}/.well-known/oauth-authorization-server",
        oauth_protected_resource=f"{origin}/.well-known/oauth-protected-resource",
        scopes=SCOPES,
        auth_methods=["oauth2", "api_key"],
        errors="RFC 9457 application/problem+json on every API 4xx/5xx",
        deprecation_policy="URL versioning on /v1. Breaking changes ship as /v2 with Deprecation + Sunset headers. See /docs/versioning.md.",
    )


@app.get(
    "/v1",
    tags=["meta"],
    operation_id="apiIndex",
    summary="Public API index",
    response_model=ApiDiscoveryResponse,
)
async def api_index(request: Request) -> ApiDiscoveryResponse:
    """Unauthenticated machine-readable index of the Agent Seek HTTP API (typed ApiDiscoveryResponse)."""
    return _api_discovery(origin_from(request))


@app.get(
    "/api",
    tags=["meta"],
    operation_id="listPublicApi",
    summary="Public API discovery (/api)",
    response_model=ApiDiscoveryResponse,
)
async def api_root(request: Request) -> ApiDiscoveryResponse:
    """Same typed public discovery document as GET /v1, at the conventional /api prefix."""
    return _api_discovery(origin_from(request))


@app.api_route("/api/v1", methods=["GET", "POST", "HEAD"], include_in_schema=False)
async def api_v1_entry(request: Request, _: object = Depends(require_api_key)) -> ApiDiscoveryResponse:
    """Protected versioned entry. Unauthenticated GET/POST returns 401 + WWW-Authenticate."""
    return _api_discovery(origin_from(request))


@app.get(
    "/v1/sandbox",
    tags=["search"],
    operation_id="sandboxSearchExample",
    summary="Zero-auth sandbox example",
    response_model=SearchResponse,
    description=(
        "Canned SearchResponse for onboarding. Does not call You.com or Jev and "
        "does not require a key. Use this to inspect the result shape before "
        "calling POST /v1/search."
    ),
)
async def sandbox_search_example() -> SearchResponse:
    """Zero-auth sandbox: a static ranked result so agents can parse the contract."""
    return SearchResponse(
        results=[
            RankedResult(
                rank=1,
                url=f"{PUBLIC_ORIGIN}/docs",
                title="Agent Seek docs — ranked web search",
                snippet=(
                    "Sandbox example. Real searches use POST /v1/search with OAuth "
                    "search:read or Bearer AGENT_SEEK_API_KEY."
                ),
                score=0.91,
                flags=["on_topic"],
                raw_rank=1,
                provider="sandbox",
                signals={
                    "on_topic": 0.9,
                    "answerability": 0.85,
                    "prompt_injection": 0.08,
                },
            )
        ],
        meta=SearchMeta(
            q="sandbox example",
            candidates_in=1,
            kept=1,
            latency_ms=0,
            mode="snip",
            provider="sandbox",
            agent_seek_version=AGENT_SEEK_VERSION,
            ranking="sandbox",
        ),
        raw_results=[],
    )


@app.api_route("/v2", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], include_in_schema=False)
@app.api_route("/v2/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], include_in_schema=False)
async def unsupported_v2(request: Request, rest: str = ""):
    return json_error(
        404,
        "API v2 is not published. Use /v1.",
        code="UNSUPPORTED_VERSION",
        request=request,
        headers={
            "Deprecation": "false",
            "Link": '</docs/versioning.md>; rel="deprecation"; type="text/markdown"',
        },
    )


@app.post("/api/v1/search", include_in_schema=False)
async def search_post_alias(
    request: Request,
    body: SearchRequest,
    _: None = Depends(require_api_key),
    __: None = Depends(website_search_limit_dep),
):
    return await _run_website_search(request, body)


@app.get("/api/v1/search", include_in_schema=False)
async def search_get_alias(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    k: int = Query(10, ge=1, le=25),
    max_candidates: int = Query(50, ge=1, le=100),
    mode: str = Query("snip"),
    rank: str = Query("on"),
    nocache: bool = Query(False),
    _: None = Depends(require_api_key),
    __: None = Depends(website_search_limit_dep),
):
    req = SearchRequest(
        q=q, k=k, max_candidates=max_candidates, mode=mode, rank=rank, nocache=nocache
    )
    return await _run_website_search(request, req)


register_oauth(app)
register_mcp(app, _run_search)
register_agent_ready(app)
