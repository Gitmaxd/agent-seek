"""Minimal OAuth 2.0 authorization server + RFC 8414 / 9728 discovery.

Single-operator prototype: authorization code + PKCE (S256), anonymous /
service_auth agent registration, JWT-bearer token exchange. Secrets come from
env; never log tokens.
"""
from __future__ import annotations

import base64
import html
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.api.agent_ready import origin_from
from apps.api.config import get_settings
from packages.core.pipeline import AGENT_SEEK_VERSION

SCOPES: dict[str, str] = {
    "search:read": "Call ranked web search (POST /v1/search and search_web MCP tool).",
    "mcp:invoke": "Call Agent Seek MCP tools over Streamable HTTP.",
    "health:read": "Read health, docs, and capability metadata.",
}

GRANT_AUTHORIZATION_CODE = "authorization_code"
GRANT_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
GRANT_CLAIM = "urn:workos:agent-auth:grant-type:claim"
ASSERTION_ID_JAG = "urn:ietf:params:oauth:token-type:id-jag"

TEST_CLIENT_ID = "agent-seek-test"
TEST_REDIRECTS = (
    "http://127.0.0.1/callback",
    "http://127.0.0.1:8787/oauth/callback",
    "urn:ietf:wg:oauth:2.0:oob",
)

# In-memory prototype stores (process-local).
_clients: dict[str, dict[str, Any]] = {}
_codes: dict[str, dict[str, Any]] = {}
_registrations: dict[str, dict[str, Any]] = {}
_revoked: set[str] = set()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def signing_key() -> str:
    settings = get_settings()
    explicit = (settings.agent_seek_token_signing_key or "").strip()
    if explicit:
        return explicit
    # Derived fallback so local pytest works without a second secret.
    seed = (settings.agent_seek_api_key or "dev-agent-seek-key-change-me").encode("utf-8")
    return hashlib.sha256(b"agent-seek-oauth|" + seed).hexdigest()


def sign_jwt(payload: dict[str, Any], *, typ: str = "JWT") -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": typ}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(signing_key().encode("utf-8"), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def verify_jwt(token: str) -> dict[str, Any] | None:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(
        signing_key().encode("utf-8"),
        f"{header_b64}.{body_b64}".encode(),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_b64url(expected), sig_b64):
        return None
    try:
        payload = json.loads(_b64url_decode(body_b64))
    except (json.JSONDecodeError, ValueError):
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    if payload.get("jti") in _revoked:
        return None
    return payload


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def seed_clients() -> None:
    if TEST_CLIENT_ID not in _clients:
        _clients[TEST_CLIENT_ID] = {
            "client_id": TEST_CLIENT_ID,
            "client_name": "Agent Seek pytest client",
            "redirect_uris": list(TEST_REDIRECTS),
            "token_endpoint_auth_method": "none",
            "grant_types": [GRANT_AUTHORIZATION_CODE, GRANT_JWT_BEARER],
            "public": True,
        }


def www_authenticate(request: Request) -> str:
    """WorkOS / RFC 9728 shape: Bearer resource_metadata="…" (no realm)."""
    origin = origin_from(request)
    return f'Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource"'


def unauthorized(request: Request, message: str = "Unauthorized") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=message,
        headers={"WWW-Authenticate": www_authenticate(request)},
    )


def scopes_of(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("scope") or ""
    if isinstance(raw, list):
        return {str(s) for s in raw}
    return {s for s in str(raw).split() if s}


class Principal:
    """Authenticated caller: shared API key or OAuth access token."""

    def __init__(self, *, kind: str, subject: str, scopes: set[str]):
        self.kind = kind
        self.subject = subject
        self.scopes = scopes

    def has(self, needed: set[str]) -> bool:
        if self.kind == "api_key":
            return True
        return needed <= self.scopes


def _secret_eq(left: str, right: str) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def resolve_bearer(token: str | None) -> Principal | None:
    if not token:
        return None
    settings = get_settings()
    expected = settings.agent_seek_api_key
    if expected and _secret_eq(token, expected):
        return Principal(kind="api_key", subject="api_key", scopes=set(SCOPES))
    payload = verify_jwt(token)
    if payload and payload.get("token_use") == "access":
        return Principal(
            kind="oauth",
            subject=str(payload.get("sub") or "oauth"),
            scopes=scopes_of(payload),
        )
    return None


def principal_from_request(request: Request) -> Principal | None:
    authorization = request.headers.get("Authorization") or ""
    token = None
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.headers.get("X-API-Key")
    return resolve_bearer(token)


async def require_api_key(request: Request) -> Principal:
    """API key or OAuth access token with search:read (API key has all scopes)."""
    return await require_scopes(request, {"search:read"})


async def require_scopes(request: Request, needed: set[str]) -> Principal:
    principal = principal_from_request(request)
    if principal is None:
        raise unauthorized(request, "Unauthorized")
    if not principal.has(needed):
        raise HTTPException(
            status_code=403,
            detail="Insufficient scope",
            headers={"WWW-Authenticate": www_authenticate(request)},
        )
    return principal


def protected_resource_metadata(origin: str) -> dict[str, Any]:
    resource = origin + "/"
    return {
        "resource": resource,
        "resource_name": "Agent Seek",
        "resource_documentation": f"{origin}/auth.md",
        "authorization_servers": [origin + "/"],
        "scopes_supported": list(SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["HS256"],
    }


def authorization_server_metadata(origin: str) -> dict[str, Any]:
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth2/authorize",
        "token_endpoint": f"{origin}/oauth2/token",
        "revocation_endpoint": f"{origin}/oauth2/revoke",
        "registration_endpoint": f"{origin}/oauth2/register",
        "jwks_uri": f"{origin}/oauth2/jwks",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": [
            GRANT_AUTHORIZATION_CODE,
            GRANT_JWT_BEARER,
            GRANT_CLAIM,
        ],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": list(SCOPES),
        "client_id_metadata_document_supported": True,
        "service_documentation": f"{origin}/auth.md",
        "agent_auth": {
            "skill": f"{origin}/auth.md",
            "identity_endpoint": f"{origin}/agent/identity",
            "claim_endpoint": f"{origin}/agent/identity/claim",
            "events_endpoint": f"{origin}/agent/event/notify",
            "identity_types_supported": ["anonymous", "identity_assertion", "service_auth"],
            "identity_assertion": {
                "assertion_types_supported": [ASSERTION_ID_JAG],
            },
            "events_supported": [
                "https://schemas.workos.com/events/agent/auth/identity/assertion/revoked",
            ],
        },
    }


def _mint_access(sub: str, scopes: list[str], origin: str, ttl: int = 3600) -> dict[str, Any]:
    now = int(time.time())
    jti = "atk_" + secrets.token_urlsafe(16)
    token = sign_jwt(
        {
            "iss": origin,
            "aud": origin + "/",
            "sub": sub,
            "scope": " ".join(scopes),
            "iat": now,
            "exp": now + ttl,
            "jti": jti,
            "token_use": "access",
        },
        typ="at+jwt",
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "scope": " ".join(scopes),
    }


def _mint_assertion(sub: str, scopes: list[str], origin: str, *, reg_type: str) -> str:
    now = int(time.time())
    return sign_jwt(
        {
            "iss": origin,
            "aud": f"{origin}/oauth2/token",
            "sub": sub,
            "scope": " ".join(scopes),
            "iat": now,
            "exp": now + 300,
            "jti": "idt_" + secrets.token_urlsafe(12),
            "token_use": "identity_assertion",
            "registration_type": reg_type,
        },
        typ="identity_assertion+jwt",
    )


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _oauth_error(status: int, error: str, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "error_description": description},
    )


async def _read_form(request: Request) -> dict[str, str]:
    """Parse urlencoded or JSON bodies without python-multipart."""
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            body = await request.json()
        except Exception:
            return {}
        if not isinstance(body, dict):
            return {}
        return {str(k): "" if v is None else str(v) for k, v in body.items()}
    raw = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {k: (vals[-1] if vals else "") for k, vals in parsed.items()}


def register_oauth(app: FastAPI) -> None:
    seed_clients()

    def _origin(request: Request) -> str:
        return origin_from(request)

    @app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    async def oauth_as_metadata(request: Request):
        return JSONResponse(authorization_server_metadata(_origin(request)))

    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    async def oauth_prm(request: Request):
        return JSONResponse(protected_resource_metadata(_origin(request)))

    @app.get("/.well-known/oauth-client/agent-seek-test.json", include_in_schema=False)
    async def cimd_test_client(request: Request):
        origin = _origin(request)
        return JSONResponse(
            {
                "client_id": f"{origin}/.well-known/oauth-client/agent-seek-test.json",
                "client_name": "Agent Seek pytest CIMD client",
                "redirect_uris": list(TEST_REDIRECTS),
                "token_endpoint_auth_method": "none",
                "grant_types": [GRANT_AUTHORIZATION_CODE],
                "response_types": ["code"],
                "scope": " ".join(SCOPES),
            }
        )

    @app.api_route("/oauth2/jwks", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def jwks():
        # HS256 shared secret is not published. Empty JWKS is intentional.
        return JSONResponse({"keys": []})

    @app.api_route("/oauth2/authorize", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def authorize(
        request: Request,
        response_type: str = "",
        client_id: str = "",
        redirect_uri: str = "",
        scope: str = "",
        state: str = "",
        code_challenge: str = "",
        code_challenge_method: str = "",
    ):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        if request.method == "POST":
            form = await _read_form(request)
            response_type = str(form.get("response_type") or response_type)
            client_id = str(form.get("client_id") or client_id)
            redirect_uri = str(form.get("redirect_uri") or redirect_uri)
            scope = str(form.get("scope") or scope)
            state = str(form.get("state") or state)
            code_challenge = str(form.get("code_challenge") or code_challenge)
            code_challenge_method = str(form.get("code_challenge_method") or code_challenge_method)
        seed_clients()
        if response_type != "code":
            return _oauth_error(400, "unsupported_response_type", "Only response_type=code is supported.")
        client = _clients.get(client_id)
        if client is None and client_id.startswith("https://"):
            # CIMD: accept our seeded document URL as an alias of the test client.
            if client_id.endswith("/.well-known/oauth-client/agent-seek-test.json"):
                client = _clients[TEST_CLIENT_ID]
        if client is None:
            return _oauth_error(400, "invalid_client", "Unknown client_id. Use agent-seek-test or register.")
        if redirect_uri not in client["redirect_uris"]:
            return _oauth_error(400, "invalid_request", "redirect_uri is not registered for this client.")
        if code_challenge_method != "S256" or not code_challenge:
            return _oauth_error(400, "invalid_request", "PKCE S256 code_challenge is required.")
        requested = [s for s in scope.split() if s in SCOPES] or ["search:read", "health:read"]
        code = secrets.token_urlsafe(32)
        _codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": requested,
            "challenge": code_challenge,
            "exp": time.time() + 300,
            "sub": f"user:{client_id}",
        }
        if redirect_uri == "urn:ietf:wg:oauth:2.0:oob":
            return HTMLResponse(
                f"<!DOCTYPE html><html><body><h1>Agent Seek authorization code</h1>"
                f"<p>code={code}</p></body></html>"
            )
        params = {"code": code}
        if state:
            params["state"] = state
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)

    async def _token_from_form(request: Request) -> JSONResponse:
        origin = _origin(request)
        seed_clients()
        form = await _read_form(request)
        grant = str(form.get("grant_type") or "")
        if grant == GRANT_AUTHORIZATION_CODE:
            code = str(form.get("code") or "")
            verifier = str(form.get("code_verifier") or "")
            redirect_uri = str(form.get("redirect_uri") or "")
            client_id = str(form.get("client_id") or "")
            rec = _codes.pop(code, None)
            if not rec or rec["exp"] < time.time():
                return _oauth_error(400, "invalid_grant", "Authorization code is missing or expired.")
            if rec["client_id"] != client_id or rec["redirect_uri"] != redirect_uri:
                return _oauth_error(400, "invalid_grant", "code / client_id / redirect_uri mismatch.")
            if pkce_s256(verifier) != rec["challenge"]:
                return _oauth_error(400, "invalid_grant", "PKCE S256 verification failed.")
            return JSONResponse(_mint_access(rec["sub"], rec["scope"], origin))

        if grant == GRANT_JWT_BEARER:
            assertion = str(form.get("assertion") or "")
            payload = verify_jwt(assertion)
            if not payload or payload.get("token_use") != "identity_assertion":
                return _oauth_error(400, "invalid_grant", "identity_assertion is invalid or expired.")
            scopes = [s for s in scopes_of(payload) if s in SCOPES] or ["health:read"]
            return JSONResponse(_mint_access(str(payload.get("sub") or "agent"), scopes, origin))

        if grant == GRANT_CLAIM:
            claim_token = str(form.get("claim_token") or "")
            reg = next((r for r in _registrations.values() if r.get("claim_token") == claim_token), None)
            if not reg:
                return _oauth_error(400, "invalid_grant", "Unknown claim_token.")
            if not reg.get("claimed"):
                return JSONResponse(
                    status_code=400,
                    content={"error": "authorization_pending", "error_description": "User has not completed the claim ceremony."},
                )
            scopes = list(reg.get("post_claim_scopes") or ["search:read", "health:read", "mcp:invoke"])
            body = _mint_access(reg["registration_id"], scopes, origin)
            body["identity_assertion"] = _mint_assertion(
                reg["registration_id"], scopes, origin, reg_type=reg["type"]
            )
            return JSONResponse(body)

        return _oauth_error(400, "unsupported_grant_type", "Unsupported grant_type.")

    @app.api_route("/oauth2/token", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def token_endpoint(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        return await _token_from_form(request)

    @app.api_route("/oauth2/revoke", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def revoke(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        form = await _read_form(request)
        token = str(form.get("token") or "")
        payload = verify_jwt(token)
        if payload and payload.get("jti"):
            _revoked.add(str(payload["jti"]))
        return Response(status_code=200)

    @app.api_route("/oauth2/register", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def register_client(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        try:
            body = await request.json()
        except Exception:
            body = {}
        client_id = "cid_" + secrets.token_urlsafe(12)
        redirects = body.get("redirect_uris") or list(TEST_REDIRECTS)
        if not isinstance(redirects, list):
            redirects = list(TEST_REDIRECTS)
        rec = {
            "client_id": client_id,
            "client_name": body.get("client_name") or "Agent Seek registered client",
            "redirect_uris": [str(u) for u in redirects],
            "token_endpoint_auth_method": "none",
            "grant_types": [GRANT_AUTHORIZATION_CODE],
            "public": True,
        }
        _clients[client_id] = rec
        return JSONResponse({**rec, "client_id_issued_at": int(time.time())}, status_code=201)

    def _new_registration(reg_type: str, scopes: list[str], origin: str) -> dict[str, Any]:
        rid = "reg_" + secrets.token_urlsafe(10)
        claim_token = "clm_" + secrets.token_urlsafe(12)
        user_code = f"{secrets.randbelow(1000000):06d}"
        now = int(time.time())
        rec = {
            "registration_id": rid,
            "type": reg_type,
            "scopes": scopes,
            "post_claim_scopes": ["search:read", "mcp:invoke", "health:read"],
            "claim_token": claim_token,
            "user_code": user_code,
            "claimed": False,
            "exp": now + 86400,
        }
        _registrations[rid] = rec
        return rec

    @app.api_route("/agent/identity", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def identity_endpoint(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        origin = _origin(request)
        if request.method == "GET":
            return JSONResponse(
                {
                    "identity_endpoint": f"{origin}/agent/identity",
                    "identity_types_supported": ["anonymous", "identity_assertion", "service_auth"],
                    "identity_assertion": {"assertion_types_supported": [ASSERTION_ID_JAG]},
                }
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        kind = str(body.get("type") or "")
        settings = get_settings()

        if kind == "anonymous":
            rec = _new_registration("anonymous", ["health:read", "mcp:invoke"], origin)
            assertion = _mint_assertion(rec["registration_id"], rec["scopes"], origin, reg_type="anonymous")
            return JSONResponse(
                {
                    "registration_id": rec["registration_id"],
                    "registration_type": "anonymous",
                    "identity_assertion": assertion,
                    "assertion_expires": _iso(int(time.time()) + 300),
                    "pre_claim_scopes": rec["scopes"],
                    "claim_url": f"{origin}/agent/identity/claim",
                    "claim_token": rec["claim_token"],
                    "claim_token_expires": _iso(rec["exp"]),
                    "post_claim_scopes": rec["post_claim_scopes"],
                }
            )

        if kind == "service_auth":
            presented = str(body.get("client_secret") or body.get("api_key") or "")
            expected = settings.agent_seek_api_key
            if expected and presented and _secret_eq(presented, expected):
                rec = _new_registration("service_auth", list(SCOPES), origin)
                rec["claimed"] = True
                assertion = _mint_assertion(rec["registration_id"], rec["scopes"], origin, reg_type="service_auth")
                return JSONResponse(
                    {
                        "registration_id": rec["registration_id"],
                        "registration_type": "service_auth",
                        "identity_assertion": assertion,
                        "assertion_expires": _iso(int(time.time()) + 300),
                        "scopes": rec["scopes"],
                    }
                )
            rec = _new_registration("service_auth", ["health:read"], origin)
            return JSONResponse(
                {
                    "registration_id": rec["registration_id"],
                    "registration_type": "service_auth",
                    "claim_url": f"{origin}/agent/identity/claim",
                    "claim_token": rec["claim_token"],
                    "claim_token_expires": _iso(rec["exp"]),
                    "post_claim_scopes": rec["post_claim_scopes"],
                    "claim": {
                        "user_code": rec["user_code"],
                        "expires_in": 600,
                        "verification_uri": f"{origin}/oauth2/claim?claim_token={rec['claim_token']}",
                        "interval": 5,
                    },
                }
            )

        if kind == "identity_assertion":
            assertion_type = str(body.get("assertion_type") or "")
            if assertion_type and assertion_type != ASSERTION_ID_JAG:
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_request", "error_description": "Unsupported assertion_type."},
                )
            incoming = str(body.get("assertion") or "")
            if incoming.count(".") != 2:
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_request", "error_description": "assertion must be a JWT (id-jag)."},
                )
            rec = _new_registration("identity_assertion", list(SCOPES), origin)
            rec["claimed"] = True
            assertion = _mint_assertion(rec["registration_id"], rec["scopes"], origin, reg_type="identity_assertion")
            return JSONResponse(
                {
                    "registration_id": rec["registration_id"],
                    "registration_type": "identity_assertion",
                    "identity_assertion": assertion,
                    "assertion_expires": _iso(int(time.time()) + 300),
                    "scopes": rec["scopes"],
                }
            )

        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "type must be anonymous, service_auth, or identity_assertion."},
        )

    @app.api_route("/agent/identity/claim", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def claim_endpoint(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        origin = _origin(request)
        if request.method == "GET":
            return JSONResponse({"claim_endpoint": f"{origin}/agent/identity/claim"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        claim_token = str(body.get("claim_token") or "")
        rec = next((r for r in _registrations.values() if r.get("claim_token") == claim_token), None)
        if rec is None:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_claim_token", "error_description": "claim_token is unknown."},
            )
        rec["user_code"] = f"{secrets.randbelow(1000000):06d}"
        return JSONResponse(
            {
                "registration_id": rec["registration_id"],
                "claim_attempt_id": "cla_" + secrets.token_urlsafe(8),
                "status": "initiated",
                "expires_at": _iso(int(time.time()) + 600),
                "claim_attempt": {
                    "user_code": rec["user_code"],
                    "expires_in": 600,
                    "verification_uri": f"{origin}/oauth2/claim?claim_token={claim_token}",
                    "interval": 5,
                },
            }
        )

    @app.api_route("/oauth2/claim", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def claim_page(request: Request, claim_token: str = "", user_code: str = ""):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        if request.method == "POST":
            form = await _read_form(request)
            claim_token = str(form.get("claim_token") or claim_token)
            user_code = str(form.get("user_code") or user_code)
            rec = next((r for r in _registrations.values() if r.get("claim_token") == claim_token), None)
            if rec and user_code and user_code == rec.get("user_code"):
                rec["claimed"] = True
                return HTMLResponse("<!DOCTYPE html><html><body><h1>Claim complete</h1></body></html>")
            return HTMLResponse("<!DOCTYPE html><html><body><h1>Invalid user_code</h1></body></html>", status_code=400)
        safe_claim = html.escape(claim_token or "", quote=True)
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html lang="en"><body>
<h1>Agent Seek claim</h1>
<p>Enter the user_code from your agent to bind this registration.</p>
<form method="post" action="/oauth2/claim">
  <input type="hidden" name="claim_token" value="{safe_claim}" />
  <label>user_code <input name="user_code" required /></label>
  <button type="submit">Confirm</button>
</form>
</body></html>"""
        )

    @app.api_route("/agent/event/notify", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
    async def events_endpoint(request: Request):
        if request.method == "OPTIONS":
            return Response(status_code=204)
        if request.method == "GET":
            return JSONResponse(
                {
                    "events_endpoint": f"{_origin(request)}/agent/event/notify",
                    "events_supported": [
                        "https://schemas.workos.com/events/agent/auth/identity/assertion/revoked",
                    ],
                }
            )
        return Response(status_code=202)

