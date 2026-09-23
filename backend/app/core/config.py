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

    asr_english_model_dir: str = ""
    """Whisper checkpoint directory serving ENGLISH only, or empty to disable.

    IndicConformer is IN-22 and has no English mask, so without this English
    reaches `UNSUPPORTED_LANGUAGE` at the ASR and the whole downstream chain
    stops - which is `BLOCKERS.md` O16.

    Empty by DEFAULT, and deliberately. Whisper pads every input to 30 s, so a
    2 s window costs 869 ms on `whisper-base` (546 ms on `whisper-tiny`)
    against the 265 ms IndicConformer stage it replaces, and the packet budget
    is 1000 ms with a p95 already at ~1000 ms (O13). Enabling English buys
    coverage and spends the real-time budget, and that trade has to be made
    deliberately rather than inherited from a default. The arithmetic,
    including how dropping the anti-spoof stage changes it, is in O16.
    """

    vad_model_dir: str = ""
    """Directory containing `silero_vad.jit`."""

    antispoof_model_dir: str = ""
    """Directory holding the anti-spoof checkpoint.

    Interpreted according to `antispoof_kind`: an AASIST directory containing
    `AASIST.pth`, or a HuggingFace audio-classification directory containing
    `config.json` and `preprocessor_config.json`.
    """

    antispoof_kind: Literal["aasist", "wav2vec2"] = "wav2vec2"
    """Which anti-spoof implementation to load.

    Defaults to `wav2vec2`. AASIST is not removed - it remains selectable and
    its integration is proven correct (EER 0.0133 in-domain, Phase J) - but it
    does not transfer to VIVE's audio, scoring at chance on the synthesis
    probe and 0.9998 on genuine handset speech (O12). Phase J2 measured a
    wav2vec2 checkpoint at 0.1000 on the same probe against AASIST's 0.4333.

    Defaulting to the model that transfers is the point: a default that has to
    be changed to get the measured behaviour is a default that ships the
    unmeasured one.
    """

    speaker_model_dir: str = ""
    """SpeechBrain ECAPA-TDNN directory (`hyperparams.yaml` + checkpoints)."""

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

    store_path: str = ""
    """SQLite file for durable sessions. Empty keeps everything in memory.

    Empty is still the default because in-memory is the stronger privacy
    position and is what the tests assume: nothing reaches disk unless an
    operator asks for it. Setting a path makes sessions, packets, transcripts
    and alerts survive a restart (docs/BLOCKERS.md O4). Raw audio is never
    written either way.
    """

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
