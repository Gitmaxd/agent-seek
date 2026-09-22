"""MCP Streamable HTTP server for Agent Seek (JSON-RPC over POST)."""
from __future__ import annotations

import json
import secrets
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from apps.api.agent_ready import origin_from
from apps.api.oauth import SCOPES, principal_from_request, www_authenticate
from apps.api.rate_limit import DEMO_EXHAUSTED_DETAIL, demo_quota_dep, rate_limit_dep
from packages.core.models import SearchRequest
from packages.core.pipeline import AGENT_SEEK_VERSION

PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL = "2025-03-26"

SearchRunner = Callable[[SearchRequest], Awaitable[Any]]

MCP_INSTRUCTIONS = (
    "Less SEO. More signal. Agent Seek returns ranked sources; the caller writes "
    "the answer. Web results are scored for prompt injection before the agent "
    "reads them (signal prompt_injection; UI: Injection risk). You.com discovers "
    "candidates and TypeSafe Jev cascade-ranks them. "
    "Default mode=snip (title/URL/snippet; cheaper/faster). Pass mode=deep for "
    "Stage A survivor fetch (cap 12; not a full-web crawl). Website UI is fixed snip. "
    "Signals include prompt_injection (UI: Injection risk). Hard gates (order): "
    "subject_match → is_republisher → prompt_injection (0.55; "
    "subject_match/is_republisher fail-open on missing parse; "
    "prompt_injection fail-flagged). If hard gates empty the scored list, "
    "pre-gate ranking is restored and each restored row has gates_relaxed true "
    "(relaxed-safety response; not a SearchMeta field). Use "
    "search_web for a small scored URL list. Authenticate search_web with OAuth "
    "2.0 (scope search:read) or Bearer AGENT_SEEK_API_KEY. Hard cap 100 discover "
    "candidates per query (default 50 in, top 10 out). Prefer the top 1–2 ranked "
    "sources before expanding. One good keeper beats a context window full of "
    "searches. After search_web: use score order; expand the rest of k or re-query "
    "only if those fail; do not paste the full result list into context by default."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_web",
        "description": (
            "Run Agent Seek ranked web search (You.com discover + Jev cascade; "
            "results are scored for prompt injection before the agent reads them; "
            "default mode=snip, title/URL/snippet) and return scored "
            "URLs, snippets, flags, and signals (including prompt_injection). "
            "If hard gates empty the scored list, restored rows set gates_relaxed true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query, 1 to 500 characters.",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "k": {
                    "type": "integer",
                    "description": "Number of ranked results to return (1-25).",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10,
                },
                "max_candidates": {
                    "type": "integer",
                    "description": "Discover candidate cap (1-100, default 50).",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                },
                "mode": {
                    "type": "string",
                    "description": "snip (default) ranks title/URL/snippet (cheaper/faster); deep fetches Stage A survivor pages (cap 12).",
                    "enum": ["deep", "snip"],
                    "default": "snip",
                },
            },
            "required": ["q"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "Ranked web search",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "get_service_health",
        "description": (
            "Return Agent Seek process liveness and the current prototype version "
            "so agents can confirm the service is up before searching."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "verbose": {
                    "type": "boolean",
                    "description": "If true, include endpoint and auth reminder fields.",
                    "default": False,
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "Service health",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "get_api_docs",
        "description": (
            "Return Agent Seek API, OAuth, and MCP documentation links plus a "
            "short contract summary for POST /v1/search."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Focus area: search, auth, or mcp.",
                    "enum": ["search", "auth", "mcp"],
                    "default": "search",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "API documentation",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "list_search_capabilities",
        "description": (
            "List Agent Seek search modes (default snip), hard caps, signals, "
            "hard gates, OAuth scopes, and which auth methods the HTTP API and "
            "MCP transport accept."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_scopes": {
                    "type": "boolean",
                    "description": "If true, include the OAuth scope map in the result.",
                    "default": True,
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "annotations": {
            "title": "Search capabilities",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]


def server_card(origin: str) -> dict[str, Any]:
    return {
        "name": "Agent Seek MCP",
        "description": (
            "Less SEO. More signal. Ranked web search for agents (You.com discover "
            "plus TypeSafe Jev cascade). Default mode=snip (title/URL/snippet; cheaper/faster). "
            "Pass mode=deep for Stage A survivor fetch (cap 12). Returns ranked sources; the caller writes the answer."
        ),
        "version": AGENT_SEEK_VERSION,
        "serverUrl": f"{origin}/mcp",
        "transport": "streamable-http",
        "icon": f"{origin}/static/og.svg",
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
            }
            for t in TOOLS
        ],
    }


def _rpc_error(id_value: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_value, "error": err}


def _rpc_result(id_value: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_value, "result": result}


def _text_result(payload: Any) -> dict[str, Any]:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, indent=2)
        structured = payload
    else:
        text = str(payload)
        structured = {"text": text}
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


class McpHandler:
    def __init__(self, search_runner: SearchRunner):
        self.search_runner = search_runner

    def initialize(self, params: dict[str, Any], origin: str) -> dict[str, Any]:
        requested = str((params or {}).get("protocolVersion") or DEFAULT_PROTOCOL)
        version = requested if requested in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL
        return {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "agent-seek",
                "title": "Agent Seek",
                "version": AGENT_SEEK_VERSION,
            },
            "instructions": MCP_INSTRUCTIONS,
        }

    def tools_list(self) -> dict[str, Any]:
        return {"tools": TOOLS}

    async def tools_call(self, params: dict[str, Any], request: Request, origin: str) -> dict[str, Any]:
        name = str((params or {}).get("name") or "")
        args = (params or {}).get("arguments") or {}
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        if name == "get_service_health":
            verbose = bool(args.get("verbose", False))
            payload: dict[str, Any] = {"ok": True, "version": AGENT_SEEK_VERSION}
            if verbose:
                payload["health"] = f"{origin}/health"
                payload["auth"] = f"{origin}/auth.md"
            return _text_result(payload)
        if name == "get_api_docs":
            topic = str(args.get("topic") or "search")
            return _text_result(
                {
                    "topic": topic,
                    "openapi": f"{origin}/openapi.json",
                    "docs": f"{origin}/docs",
                    "developers": f"{origin}/developers",
                    "auth": f"{origin}/auth.md",
                    "mcp": f"{origin}/mcp",
                    "server_card": f"{origin}/.well-known/mcp/server-card.json",
                    "oauth_as": f"{origin}/.well-known/oauth-authorization-server",
                    "oauth_prm": f"{origin}/.well-known/oauth-protected-resource",
                    "search": "POST /v1/search with Bearer OAuth access_token (search:read) or AGENT_SEEK_API_KEY",
                    "contract": {
                        "q": "required 1-500",
                        "k": "1-25 default 10",
                        "max_candidates": "1-100 default 50",
                        "mode": "snip (default) | deep",
                        "deep_fetch_cap": 12,
                        "signals": (
                            "answerability, authority, on_topic, states_sought_fact, "
                            "subject_match, spam, prompt_injection"
                        ),
                        "hard_gates": (
                            "subject_match → is_republisher → prompt_injection "
                            "(0.55; subject_match/is_republisher fail-open; "
                            "prompt_injection fail-flagged). "
                            "Empty scored list restores pre-gate rows with "
                            "gates_relaxed true (not a SearchMeta field)"
                        ),
                    },
                }
            )
        if name == "list_search_capabilities":
            include_scopes = bool(args.get("include_scopes", True))
            payload = {
                "modes": ["deep", "snip"],
                "default_mode": "snip",
                "default_k": 10,
                "default_max_candidates": 50,
                "hard_cap": 100,
                "deep_fetch_cap": 12,
                "signals": [
                    "answerability",
                    "authority",
                    "on_topic",
                    "states_sought_fact",
                    "subject_match",
                    "spam",
                    "prompt_injection",
                ],
                "hard_gates": [
                    "subject_match",
                    "is_republisher",
                    "prompt_injection",
                ],
                "hard_gate_threshold": 0.55,
                "hard_gate_missing_parse": {
                    "subject_match": "fail-open",
                    "is_republisher": "fail-open",
                    "prompt_injection": "fail-flagged",
                },
                "ui_signal_labels": {"prompt_injection": "Injection risk"},
                "gates_relaxed": (
                    "Per-result boolean. True when hard gates emptied the scored "
                    "list and this row was restored from pre-gate ranking. "
                    "Not a SearchMeta field."
                ),
                "auth": ["oauth2", "api_key"],
                "mcp_transport": "streamable-http",
                "version": AGENT_SEEK_VERSION,
            }
            if include_scopes:
                payload["scopes"] = SCOPES
            return _text_result(payload)
        if name == "search_web":
            principal = principal_from_request(request)
            if principal is None or not principal.has({"search:read"}):
                raise PermissionError("search_web requires OAuth scope search:read or AGENT_SEEK_API_KEY")
            await rate_limit_dep(request)
            q = str(args.get("q") or "").strip()
            if not q:
                raise ValueError("q is required")
            req = SearchRequest(
                q=q,
                k=int(args.get("k") or 10),
                max_candidates=int(args.get("max_candidates") or 50),
                mode=str(args.get("mode") or "snip"),
            )
            # Same lifetime per-IP bucket as REST, after auth and a valid request.
            await demo_quota_dep(request)
            result = await self.search_runner(req)
            if hasattr(result, "model_dump"):
                payload = result.model_dump()
            else:
                payload = result
            return _text_result(payload)
        raise KeyError(name)

    async def handle_message(self, message: Any, request: Request, origin: str) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        is_notification = "id" not in message
        try:
            if method == "initialize":
                return _rpc_result(msg_id, self.initialize(params, origin))
            if method == "notifications/initialized":
                return None if is_notification else _rpc_result(msg_id, {})
            if method == "ping":
                return _rpc_result(msg_id, {})
            if method == "tools/list":
                return _rpc_result(msg_id, self.tools_list())
            if method == "tools/call":
                result = await self.tools_call(params, request, origin)
                return _rpc_result(msg_id, result)
            if is_notification:
                return None
            return _rpc_error(msg_id, -32601, f"Method not found: {method}")
        except PermissionError as exc:
            return _rpc_error(msg_id, -32001, str(exc), {"hint": "See /auth.md and WWW-Authenticate resource_metadata."})
        except KeyError:
            return _rpc_error(msg_id, -32601, f"Unknown tool: {params.get('name')}")
        except ValueError as exc:
            return _rpc_error(msg_id, -32602, f"Invalid params: {exc}")
        except HTTPException as exc:
            if exc.status_code == 429 and exc.detail == DEMO_EXHAUSTED_DETAIL:
                raise
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return _rpc_error(
                msg_id,
                -32000,
                detail,
                {"status_code": exc.status_code, "detail": detail},
            )
        except Exception as exc:
            return _rpc_error(msg_id, -32603, "Internal error", {"hint": str(exc.__class__.__name__)})


def register_mcp(app: FastAPI, search_runner: SearchRunner) -> None:
    handler = McpHandler(search_runner)

    @app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
    async def mcp_server_card(request: Request):
        return JSONResponse(server_card(origin_from(request)))

    async def mcp_get(request: Request):
        # Streamable HTTP GET opens an SSE stream (no legacy /sse endpoint).
        return Response(
            content=": agent-seek streamable-http\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-MCP-Transport": "streamable-http"},
        )

    async def mcp_post(request: Request):
        origin = origin_from(request)
        authorization = request.headers.get("Authorization") or ""
        if authorization and principal_from_request(request) is None:
            from apps.api.errors import json_error

            return json_error(
                401,
                "Invalid bearer token",
                request=request,
                headers={"WWW-Authenticate": www_authenticate(request)},
            )
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

        session = request.headers.get("Mcp-Session-Id") or secrets.token_urlsafe(16)
        headers = {
            "Mcp-Session-Id": session,
            "MCP-Protocol-Version": DEFAULT_PROTOCOL,
            "X-MCP-Transport": "streamable-http",
        }

        if isinstance(payload, list):
            results = []
            for item in payload:
                out = await handler.handle_message(item, request, origin)
                if out is not None:
                    results.append(out)
            if not results:
                return Response(status_code=202, headers=headers)
            return JSONResponse(results, headers=headers)

        out = await handler.handle_message(payload, request, origin)
        if out is None:
            return Response(status_code=202, headers=headers)
        if "error" in out and out["error"].get("code") == -32001:
            headers["WWW-Authenticate"] = www_authenticate(request)
        return JSONResponse(out, headers=headers)

    async def mcp_options():
        return Response(status_code=204, headers={"Allow": "GET, POST, DELETE, OPTIONS"})

    async def mcp_delete(request: Request):
        return Response(status_code=204, headers={"Mcp-Session-Id": request.headers.get("Mcp-Session-Id", "")})

    for path in ("/mcp", "/.well-known/mcp"):
        app.add_api_route(path, mcp_get, methods=["GET"], include_in_schema=False)
        app.add_api_route(path, mcp_post, methods=["POST"], include_in_schema=False)
        app.add_api_route(path, mcp_options, methods=["OPTIONS"], include_in_schema=False)
        app.add_api_route(path, mcp_delete, methods=["DELETE"], include_in_schema=False)
