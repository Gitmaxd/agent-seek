"""Shared candidate / result models."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Candidate(BaseModel):
    id: str
    url: str
    title: str = ""
    snippet: str = ""
    body: str = ""  # deep mode: extracted main text for Stage B
    raw_rank: int
    provider: str = "you.com"


class RankedResult(BaseModel):
    rank: int = Field(..., description="1-based Agent Seek rank after Jev cascade", ge=1)
    url: str = Field(..., description="Result URL")
    title: str = Field(..., description="Result title")
    snippet: str = Field(..., description="Short excerpt used for ranking and display")
    score: float = Field(..., description="Jev relevance score in 0–1")
    flags: list[str] = Field(default_factory=list, description="Keep/skip chips such as on_topic")
    raw_rank: int = Field(..., description="Original You.com discover rank", ge=1)
    provider: str = Field(default="you.com", description="Discover provider id (you.com or sandbox)")
    signals: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional Jev noul map (answerability, authority, on_topic, "
            "states_sought_fact, subject_match, spam, prompt_injection)"
        ),
    )
    gates_relaxed: bool = Field(
        default=False,
        description=(
            "gates_relaxed is true when hard gates emptied the scored list and "
            "this row was restored from the pre-gate ranking. Treat true as a "
            "relaxed-safety response (including prompt injection). Not a SearchMeta field."
        ),
    )


class SearchMeta(BaseModel):
    q: str = Field(..., description="Echo of the search query")
    candidates_in: int = Field(..., description="Discover candidates considered", ge=0)
    kept: int = Field(..., description="Results returned after ranking and gates", ge=0)
    latency_ms: int = Field(..., description="End-to-end latency in milliseconds", ge=0)
    mode: str = Field(default="snip", description="snip (default) or deep")
    provider: str = Field(default="you.com", description="Discover provider id")
    agent_seek_version: str = Field(default="0.3.0", description="Prototype build version")
    ranking: str = Field(
        default="jev",
        description="Ranking path: jev | raw | raw_fallback | sandbox",
    )
    discover_ms: int | None = Field(default=None, description="Discover-stage latency ms")
    rank_ms: int | None = Field(default=None, description="Rank-stage latency ms")
    fetch_ms: int | None = Field(default=None, description="Deep page-fetch wall time ms")
    cache_hit: bool | None = Field(default=None, description="True when discover cache hit")
    cache_scope: str | None = Field(default=None, description="Cache scope, e.g. discover")


class SearchResponse(BaseModel):
    results: list[RankedResult] = Field(..., description="Top-k ranked results in Agent Seek order")
    meta: SearchMeta = Field(..., description="Query accounting and ranking path")
    raw_results: list[RankedResult] | None = Field(
        default=None,
        description="Same candidate set in original discover order (UI toggle)",
    )


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500, description="Search query (1–500 characters)")
    k: int = Field(default=10, ge=1, le=25, description="Number of ranked results to return")
    max_candidates: int = Field(default=50, ge=1, le=100, description="Discover cap (hard max 100)")
    mode: str = Field(
        default="snip",
        description="snip (default; title/URL/snippet, cheaper/faster) or deep (Stage A survivor fetch, cap 12)",
    )
    rank: str = Field(default="on", description="on | off")
    nocache: bool = Field(default=False, description="Force discover cache miss")

    @field_validator("mode", mode="before")
    @classmethod
    def coerce_blank_mode(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return "snip"
        return value

    def clamped_max_candidates(self, hard_cap: int = 100) -> int:
        return max(1, min(int(self.max_candidates), hard_cap))


class HealthResponse(BaseModel):
    ok: bool = Field(..., description="Process liveness")
    version: str = Field(..., description="Prototype version (same as OpenAPI info.version)")


class ApiDiscoveryResponse(BaseModel):
    name: str = Field(..., description="Public API display name (Agent Seek API)")
    version: str = Field(..., description="Prototype build version")
    description: str = Field(..., description="One-line description of the ranked search API")
    openapi: str = Field(..., description="Absolute URL of Agent Seek OpenAPI (/openapi.json)")
    docs: str = Field(..., description="Absolute URL of Agent Seek docs (/docs)")
    developers: str = Field(..., description="Absolute URL of Agent Seek API portal (/developers)")
    auth: str = Field(..., description="Absolute URL of Agent Seek authentication (/auth.md)")
    health: str = Field(..., description="Absolute URL of GET /health")
    search: str = Field(..., description="Absolute URL of POST /v1/search")
    search_get: str = Field(..., description="Absolute URL of GET /v1/search")
    mcp: str = Field(..., description="Absolute URL of Agent Seek MCP (/mcp)")
    sandbox: str = Field(..., description="Absolute URL of zero-auth GET /v1/sandbox")
    versioning: str = Field(..., description="Absolute URL of /docs/versioning.md")
    oauth_authorization_server: str = Field(..., description="RFC 8414 authorization-server metadata URL")
    oauth_protected_resource: str = Field(..., description="RFC 9728 protected-resource metadata URL")
    scopes: dict[str, str] = Field(..., description="OAuth scope name → description")
    auth_methods: list[str] = Field(..., description="Accepted auth methods (oauth2, api_key)")
    errors: str = Field(..., description="Error format (RFC 9457 application/problem+json)")
    deprecation_policy: str = Field(..., description="URL versioning and Sunset policy summary")
