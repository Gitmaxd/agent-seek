"""Agent Seek configuration from env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ydc_api_key: str = ""
    typesafe_api_key: str = ""
    agent_seek_api_key: str = Field(default="dev-agent-seek-key-change-me")
    port: int = 8787
    agent_seek_default_k: int = 10
    agent_seek_default_max_candidates: int = 50
    agent_seek_max_candidates: int = 100
    agent_seek_cache_ttl_sec: int = 1800
    agent_seek_log_level: str = "info"
    cors_origin: str = "*"
    agent_seek_ui_api_key: str = ""
    agent_seek_cache_dir: str = str(ROOT / "data" / "cache")
    agent_seek_rate_limit_per_min: int = 60
    # Lifetime website demo quota master switch. "disabled" (default) | "enabled".
    agent_seek_demo_mode: str = "disabled"
    # Lifetime website-demo searches per client IP when demo mode is enabled.
    agent_seek_demo_search_limit: int = 5
    # Official Upstash REST names. Both empty → rate limiting disabled.
    # Comma-separated IPs that skip burst + demo quota (operator workstation).
    agent_seek_rate_limit_allowlist: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    agent_seek_token_signing_key: str = ""
    agent_seek_oauth_client_id: str = "agent-seek-test"


def rate_limit_allowlist() -> set[str]:
    """Parsed ``AGENT_SEEK_RATE_LIMIT_ALLOWLIST`` (comma-separated IPs)."""
    raw = get_settings().agent_seek_rate_limit_allowlist or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_rate_limit_allowlisted(ip: str) -> bool:
    return bool(ip) and ip in rate_limit_allowlist()


def is_demo_mode_enabled(value: str | bool | None = None) -> bool:
    """True only for case-insensitive ``enabled``. Everything else is disabled."""
    if isinstance(value, bool):
        return value
    raw = get_settings().agent_seek_demo_mode if value is None else value
    return str(raw or "").strip().lower() == "enabled"


@lru_cache
def get_settings() -> Settings:
    return Settings()
