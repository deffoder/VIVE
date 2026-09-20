"""Environment-driven configuration.

Secrets come from the environment, never from source (docs/SECURITY_SPEC.md 7).
Defaults are safe for local development and deliberately insecure-by-omission
rather than insecure-by-value: no token is baked in, so an unconfigured
deployment has no credentials to leak.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_PREFIX = "/api/v1"
"""Canonical API prefix.

CLAUDE.md and docs/API_SPEC.md both specify /api/v1. The external phase prompt
used /v1; docs/BLOCKERS.md R3 already resolved that conflict in favour of
CLAUDE.md. A /v1 compatibility alias is mounted alongside it so both work.
"""

LEGACY_API_PREFIX = "/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIVE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    api_tokens: str = ""
    """Comma-separated bearer tokens. Empty in development disables auth."""

    webhook_signing_key: str = ""

    session_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    ws_heartbeat_seconds: int = Field(default=20, ge=1, le=300)
    ws_idle_timeout_seconds: int = Field(default=60, ge=5, le=600)

    adapter_mode: Literal["mock", "real"] = "mock"
    """Only "mock" is implemented. Real adapters arrive in the ML phase."""

    max_audio_frame_bytes: int = Field(default=1_048_576, ge=1024)
    max_packets_per_session: int = Field(default=10_000, ge=10)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def tokens(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.api_tokens.split(",") if t.strip())

    @property
    def auth_enforced(self) -> bool:
        """Auth is enforced whenever tokens are configured.

        Production without tokens is refused at startup rather than silently
        running open - see app.main.
        """
        return bool(self.tokens)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
