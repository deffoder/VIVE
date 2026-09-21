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
    """Selects the analyzer bundle.

    "mock" keeps the deterministic scripted adapters, which remain the default
    so demos and tests are reproducible without multi-GB weights present.
    "real" loads checkpoint-backed adapters.

    A real adapter that cannot load reports LOAD_ERROR and stays in REAL mode.
    The bundle NEVER silently downgrades to mock output, because a demo that
    looks identical whether or not the model loaded is indistinguishable from
    a fabricated result (docs/ML_SPEC.md 4).
    """

    asr_model_dir: str = ""
    """Filesystem path to the IndicConformer CTC artifacts.

    Empty means "not configured", which yields LOAD_ERROR in real mode rather
    than a guess at a default location. Weights live outside Git
    (docs/ML_SPEC.md 8.6); the path is deployment configuration.
    """

    asr_prefer_gpu: bool = False
    """Request the CUDA execution provider when onnxruntime exposes one.

    Default False: on the development machine onnxruntime has no CUDA provider
    (it needs CUDA 12; the driver caps at 11.2) and the model already meets the
    latency budget on CPU. The adapter reports the provider that actually
    served the graph, not the one requested.
    """

    intent_model_dir: str = ""
    """Filesystem path to the fine-tuned intent checkpoint. Empty means not
    configured, which yields LOAD_ERROR in real mode rather than a guess."""

    behavior_model_dir: str = ""
    """Filesystem path to the fine-tuned behaviour checkpoint."""

    asr_default_language: str = "hi"
    """Decoding language when no language-ID signal is available.

    The CTC decoder applies a per-language vocabulary mask, so the language is
    a required INPUT, not an output. There is no language-ID model yet
    (docs/PHASE8_PREREQUISITES.md 6).
    """

    max_audio_frame_bytes: int = Field(default=1_048_576, ge=1024)
    max_packets_per_session: int = Field(default=10_000, ge=10)

    # --- privacy ---
    retain_raw_audio: bool = False
    """Raw audio is NEVER persisted unless an operator opts in.

    Default False, and the current store has no disk path at all, so enabling
    it is not sufficient to make audio persist - it is a forward-looking switch
    (docs/SECURITY_SPEC.md 4).
    """

    session_retention_seconds: int = Field(default=3600, ge=60, le=604_800)
    """How long an ended session's evidence is kept before deletion."""

    # --- rate limiting (per-node; see security.RateLimiter) ---
    rate_limit_requests: int = Field(default=120, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_session_creates: int = Field(default=20, ge=1)

    # --- TLS readiness ---
    require_tls: bool = False
    """When true the app refuses plaintext forwarded requests.

    TLS itself is terminated by the deployment (reverse proxy or ASGI server);
    this flag only enforces that it happened. Setting it does not itself
    provide encryption, and the product must not claim it does.
    """

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
