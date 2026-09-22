"""Bearer AGENT_SEEK_API_KEY or OAuth access token auth."""
from __future__ import annotations

from fastapi import Request

from apps.api.oauth import Principal, require_api_key, require_scopes

__all__ = ["Principal", "require_api_key", "require_scopes", "require_search_auth"]


async def require_search_auth(request: Request) -> Principal:
    return await require_scopes(request, {"search:read"})
