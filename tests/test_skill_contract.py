"""Skill / agent contract — single source of truth locked by tests."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("AGENT_SEEK_API_KEY", "test-agent-seek-key")
os.environ.setdefault("YDC_API_KEY", "test-ydc")
os.environ.setdefault("TYPESAFE_API_KEY", "test-typesafe")
os.environ.setdefault("AGENT_SEEK_UI_API_KEY", "test-agent-seek-key")

from apps.api.mcp_server import DEFAULT_PROTOCOL, PROTOCOL_VERSIONS, TOOLS
from packages.core.models import RankedResult, SearchMeta, SearchRequest
from packages.core.pipeline import AGENT_SEEK_VERSION

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "agent_contract.json"
SKILL_PATH = ROOT / "skills" / "agent-seek" / "SKILL.md"
REFERENCE_PATH = ROOT / "skills" / "agent-seek" / "reference.md"
DOCS_HTML_PATH = ROOT / "apps" / "web" / "docs.html"

MCP_SEARCH_ARGS = ("q", "k", "max_candidates", "mode")
REST_ONLY_FIELDS = ("nocache", "rank")
MCP_TOOL_NAMES = ("search_web", "get_service_health", "get_api_docs", "list_search_capabilities")


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_version_matches_agent_seek_version():
    contract = _load_contract()
    assert AGENT_SEEK_VERSION == contract["version"]


def test_search_request_fields_cover_contract():
    contract = _load_contract()
    model_fields = set(SearchRequest.model_fields.keys())
    required = set(contract["request_fields"])
    assert required <= model_fields, f"missing request fields: {required - model_fields}"


def test_ranked_result_and_meta_fields():
    contract = _load_contract()
    result_fields = set(RankedResult.model_fields.keys())
    expected_results = set(contract["response_result_fields"])
    assert expected_results <= result_fields, (
        f"missing result fields: {expected_results - result_fields}"
    )
    meta_fields = set(SearchMeta.model_fields.keys())
    assert contract["meta_version_field"] in meta_fields
    assert "signals" in result_fields


def test_skill_md_locked_to_contract():
    contract = _load_contract()
    skill = SKILL_PATH.read_text(encoding="utf-8")
    reference = REFERENCE_PATH.read_text(encoding="utf-8")
    combined = skill + "\n" + reference

    assert re.search(r"(?m)^name:\s*agent-seek\s*$", skill)
    assert contract["skill_name"] == "agent-seek"
    assert "AGENT_SEEK_API_KEY" in skill
    assert "POST /v1/search" in skill
    assert "/health" in skill
    assert "/docs" in skill
    assert "/api/docs" in skill
    assert "agent_seek_version" in skill
    assert "score" in skill
    assert "signals" in skill

    # Factory-style workflow: numbered Instructions, MCP-first, progressive disclosure.
    assert re.search(r"(?m)^## Instructions\s*$", skill)
    assert "When to use" in skill
    assert "reference.md" in skill

    # MCP surface must match mcp_server.py exactly (remote SKILL is self-sufficient).
    assert [t["name"] for t in TOOLS] == list(MCP_TOOL_NAMES)
    for name in MCP_TOOL_NAMES:
        assert name in skill, f"SKILL.md missing MCP tool {name}"
    search_schema = next(t for t in TOOLS if t["name"] == "search_web")["inputSchema"]
    assert set(search_schema["properties"]) == set(MCP_SEARCH_ARGS)
    assert search_schema["required"] == ["q"]
    assert search_schema["properties"]["mode"]["default"] == "snip"
    for field in MCP_SEARCH_ARGS:
        assert field in skill, f"SKILL.md missing MCP arg {field}"
    assert "Streamable HTTP" in skill
    assert "/.well-known/mcp/server-card.json" in skill
    assert DEFAULT_PROTOCOL in skill
    assert "2025-06-18" in skill
    assert set(PROTOCOL_VERSIONS) == {DEFAULT_PROTOCOL, "2025-06-18"}

    for field in REST_ONLY_FIELDS:
        assert field in skill, f"SKILL.md missing REST-only field {field}"
        assert field in reference, f"reference.md missing REST-only field {field}"
    for field in contract["request_fields"]:
        assert field in combined, f"skill package missing request field {field}"

    for key in contract["signal_keys"]:
        assert key in skill, f"SKILL.md missing signal key {key}"
        assert key in reference, f"reference.md missing signal key {key}"

    assert contract["default_mode"] == "snip"
    assert contract["default_k"] == 10
    assert contract["default_max_candidates"] == 50
    assert contract["hard_cap"] == 100
    assert contract["deep_fetch_cap"] == 12
    assert contract["hard_gates"] == [
        "subject_match",
        "is_republisher",
        "prompt_injection",
    ]
    assert contract["hard_gate_threshold"] == 0.55
    assert contract["hard_gate_missing_parse"] == {
        "subject_match": "fail-open",
        "is_republisher": "fail-open",
        "prompt_injection": "fail-flagged",
    }
    assert contract["ui_signal_labels"]["prompt_injection"] == "Injection risk"
    assert "cap 12" in skill
    assert "subject_match → is_republisher → prompt_injection" in skill
    assert "Injection risk" in skill
    assert "default `snip`" in skill
    assert "Website UI is fixed `snip`" in skill
    assert "scored for prompt injection before the agent reads them" in skill
    assert "fail-open" in skill
    assert "fail-flagged" in skill
    assert "gates_relaxed" in contract["response_result_fields"]
    assert "gates_relaxed" in skill
    assert "gates_relaxed" in reference
    assert "not a `SearchMeta` field" in reference or "not a SearchMeta field" in reference

    # No legacy product name as current product
    assert "SIEVE" not in combined
    assert "Sieve" not in combined


def test_skill_does_not_claim_mcp_supports_rest_only_knobs():
    """nocache/rank exist on REST SearchRequest only — never on MCP search_web."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    reference = REFERENCE_PATH.read_text(encoding="utf-8")
    search_props = next(t for t in TOOLS if t["name"] == "search_web")["inputSchema"]["properties"]
    assert "nocache" not in search_props
    assert "rank" not in search_props

    rest_markers = ("rest", "searchrequest", "does **not**", "does not", "not accept", "not exposed")
    nocache_lines = [ln for ln in skill.splitlines() if "nocache" in ln]
    assert nocache_lines, "SKILL.md must mention REST-only nocache"
    for ln in nocache_lines:
        assert any(token in ln.lower() for token in rest_markers), (
            f"SKILL.md must not claim MCP supports nocache: {ln}"
        )
    assert re.search(r"does \*\*not\*\* accept `nocache` or `rank`", skill)
    assert "nocache" in reference and "rank" in reference
    assert "not exposed" in reference or "MCP `search_web`" in reference


def test_reference_md_holds_deep_contract():
    reference = REFERENCE_PATH.read_text(encoding="utf-8")
    assert "POST /v1/search" in reference
    assert '"results"' in reference
    assert '"meta"' in reference
    assert "agent_seek_version" in reference
    assert "GET /v1/sandbox" in reference
    for field in MCP_SEARCH_ARGS + REST_ONLY_FIELDS:
        assert field in reference, field


def test_docs_html_mentions_agent_contract():
    assert DOCS_HTML_PATH.exists()
    html = DOCS_HTML_PATH.read_text(encoding="utf-8")
    assert "Bearer" in html
    assert "POST /v1/search" in html or "POST /v1/search" in html.replace("`", "")
    assert "/v1/search" in html
