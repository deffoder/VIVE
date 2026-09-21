"""Wire schemas.

Mirrors docs/API_SPEC.md. The packet shape in CLAUDE.md is canonical: its field
names and types are reproduced exactly, and everything this module adds is
additive and optional, matching API_SPEC 4.1.

These schemas are the single source of truth for the contract. The Kotlin
mirrors in android/.../data/model/ must stay identical to them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------- taxonomies
# Canonical values from docs/PROJECT_SPEC.md 7.


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AudioQuality(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    POOR = "POOR"
    NO_SPEECH = "NO_SPEECH"


class AnalyzerStatus(StrEnum):
    """Why an analyzer did or did not produce a value.

    The two failure states below are distinct on purpose. A model that never
    loaded and a model that loaded but failed on one packet need different
    operator responses, and collapsing both into ERROR hid that. Neither ever
    carries a value: a failed analyzer returns a status, never a substituted
    or mock score (docs/PROJECT_SPEC.md 7).
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_REFERENCE = "NO_REFERENCE"
    INSUFFICIENT_AUDIO = "INSUFFICIENT_AUDIO"
    LOAD_ERROR = "LOAD_ERROR"
    """The model could not be loaded at all - missing weights, missing runtime
    dependency, or an unreadable checkpoint. The adapter stays in REAL mode and
    reports this; it does NOT fall back to mock output."""
    INFERENCE_ERROR = "INFERENCE_ERROR"
    """The model loaded but failed on this packet. Other packets may succeed."""
    ERROR = "ERROR"
    """Retained for compatibility. Prefer LOAD_ERROR or INFERENCE_ERROR."""


class AdapterMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class SessionStatus(StrEnum):
    READY = "READY"
    STREAMING = "STREAMING"
    ENDED = "ENDED"
    ERROR = "ERROR"


class SourceType(StrEnum):
    VOIP = "VOIP"
    IN_APP = "IN_APP"
    CELLULAR_SCREENING = "CELLULAR_SCREENING"
    REPLAY = "REPLAY"


class Intent(StrEnum):
    NORMAL_CONVERSATION = "NORMAL_CONVERSATION"
    OTP_REQUEST = "OTP_REQUEST"
    PASSWORD_REQUEST = "PASSWORD_REQUEST"
    CARD_DETAILS_REQUEST = "CARD_DETAILS_REQUEST"
    BANKING_CREDENTIAL_REQUEST = "BANKING_CREDENTIAL_REQUEST"
    MONEY_TRANSFER_REQUEST = "MONEY_TRANSFER_REQUEST"
    ACCOUNT_CHANGE_REQUEST = "ACCOUNT_CHANGE_REQUEST"
    REMOTE_ACCESS_REQUEST = "REMOTE_ACCESS_REQUEST"
    URGENT_ACTION = "URGENT_ACTION"
    THREAT_OR_INTIMIDATION = "THREAT_OR_INTIMIDATION"
    CONFIDENTIAL_INFORMATION = "CONFIDENTIAL_INFORMATION"
    UNKNOWN = "UNKNOWN"


class Behavior(StrEnum):
    AUTHORITY_IMPERSONATION = "AUTHORITY_IMPERSONATION"
    URGENCY = "URGENCY"
    THREAT = "THREAT"
    FEAR = "FEAR"
    SECRECY = "SECRECY"
    PRESSURE = "PRESSURE"
    REWARD_PROMISE = "REWARD_PROMISE"
    NORMAL = "NORMAL"


class OodState(StrEnum):
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    KNOWN_SYNTHETIC_LIKELY = "KNOWN_SYNTHETIC_LIKELY"
    UNKNOWN_GENERATOR_SUSPECTED = "UNKNOWN_GENERATOR_SUSPECTED"
    OUT_OF_DISTRIBUTION = "OUT_OF_DISTRIBUTION"
    UNAVAILABLE = "UNAVAILABLE"


class RecommendedAction(StrEnum):
    MONITOR = "MONITOR"
    WARN_USER = "WARN_USER"
    SECONDARY_VERIFICATION = "SECONDARY_VERIFICATION"
    ESCALATE = "ESCALATE"
    HOLD_SENSITIVE_ACTION = "HOLD_SENSITIVE_ACTION"


# ------------------------------------------------------------ evidence blocks

_Strict = ConfigDict(extra="forbid")


class AasistEvidence(BaseModel):
    """Anti-spoofing. `score` is spoof likelihood, NOT probability of fraud."""

    model_config = _Strict
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AnalyzerStatus = AnalyzerStatus.AVAILABLE
    model_version: str | None = None
    inference_ms: int | None = Field(default=None, ge=0)


class EcapaEvidence(BaseModel):
    """Speaker consistency. Inert without an enrolled reference."""

    model_config = _Strict
    status: AnalyzerStatus
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    model_version: str | None = None
    inference_ms: int | None = Field(default=None, ge=0)


class AsrEvidence(BaseModel):
    """Transcript. Sensitive: never logged, never sent in a webhook."""

    model_config = _Strict
    transcript: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AnalyzerStatus = AnalyzerStatus.AVAILABLE
    model_version: str | None = None
    inference_ms: int | None = Field(default=None, ge=0)


class IntentEvidence(BaseModel):
    model_config = _Strict
    label: Intent
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AnalyzerStatus = AnalyzerStatus.AVAILABLE
    model_version: str | None = None


class BehaviorEvidence(BaseModel):
    model_config = _Strict
    labels: list[Behavior] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AnalyzerStatus = AnalyzerStatus.AVAILABLE
    model_version: str | None = None


class ContextEvidence(BaseModel):
    model_config = _Strict
    caller_verified: bool
    session_authenticated: bool | None = None
    source_type: SourceType | None = None
    requested_action: str | None = None
    context_risk: float | None = Field(default=None, ge=0.0, le=1.0)


class OodEvidence(BaseModel):
    """Uncertainty layer. High uncertainty lowers confidence, never raises risk."""

    model_config = _Strict
    state: OodState
    uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)


class AnalysisWindow(BaseModel):
    model_config = _Strict
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(ge=0.0)


class PacketRisk(BaseModel):
    """Score is 0-100; confidence is 0-1 and is a SEPARATE concept."""

    model_config = _Strict
    score: int = Field(ge=0, le=100)
    level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    contributions: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class Packet(BaseModel):
    """One analysis window. Core fields are exactly CLAUDE.md's."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str
    timestamp: str
    duration_sec: int = Field(ge=0)
    language: str
    quality: AudioQuality

    aasist: AasistEvidence
    ecapa: EcapaEvidence
    asr: AsrEvidence
    intent: IntentEvidence
    behavior: BehaviorEvidence
    context: ContextEvidence
    risk: PacketRisk

    # --- extensions (API_SPEC 4.1); optional, clients tolerate absence ---
    session_id: str | None = None
    seq: int | None = Field(default=None, ge=0)
    window: AnalysisWindow | None = None
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: str | None = None
    ood: OodEvidence | None = None
    adapter_mode: AdapterMode | None = None
    """Set to `mock` whenever demo adapters produced this packet."""


# ----------------------------------------------------------------- sessions


class RiskSummary(BaseModel):
    model_config = _Strict
    score: int = Field(ge=0, le=100)
    level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)


class EscalationTimings(BaseModel):
    """Null means "not reached" - information, not a missing value."""

    model_config = _Strict
    first_anomaly_sec: int | None = None
    first_warning_sec: int | None = None
    first_high_sec: int | None = None
    first_critical_sec: int | None = None


class AudioConfig(BaseModel):
    model_config = _Strict
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    channels: int = Field(default=1, ge=1, le=2)
    encoding: str = "pcm_s16le"


class SessionContext(BaseModel):
    model_config = _Strict
    caller_verified: bool = False
    session_authenticated: bool = False
    requested_action: str | None = None
    source_type: SourceType | None = None


class CreateSessionRequest(BaseModel):
    model_config = _Strict
    source_type: SourceType = SourceType.VOIP
    audio: AudioConfig = Field(default_factory=AudioConfig)
    language: str = "auto"
    context: SessionContext = Field(default_factory=SessionContext)


class CreateSessionResponse(BaseModel):
    model_config = _Strict
    session_id: str
    status: SessionStatus
    stream_path: str
    expires_in: int


class Session(BaseModel):
    model_config = _Strict
    session_id: str
    status: SessionStatus
    source_type: SourceType
    started_at: str | None = None
    ended_at: str | None = None
    duration_sec: int = 0
    packets_processed: int = 0
    language: str | None = None
    current_risk: RiskSummary | None = None
    overall_risk: RiskSummary | None = None
    timings: EscalationTimings = Field(default_factory=EscalationTimings)
    context: SessionContext = Field(default_factory=SessionContext)


class TranscriptLine(BaseModel):
    model_config = _Strict
    packet_id: str
    speaker: str
    text: str
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: str | None = None


# ------------------------------------------------------------------- alerts


class Alert(BaseModel):
    model_config = _Strict
    alert_id: str
    session_id: str
    level: RiskLevel
    raised_at: str
    reason: str
    packet_id: str | None = None
    intent: Intent | None = None
    recommended_action: RecommendedAction | None = None
    acknowledged: bool = False


# ------------------------------------------------------------------- policy


class PolicyEvaluateRequest(BaseModel):
    model_config = _Strict
    session_id: str | None = None
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    intent: Intent | None = None
    caller_verified: bool = False


class PolicyEvaluateResponse(BaseModel):
    model_config = _Strict
    recommended_action: RecommendedAction
    should_alert: bool
    reasons: list[str]
    policy_version: str


# ------------------------------------------------------------------ models


class AdapterState(BaseModel):
    model_config = _Strict
    status: AnalyzerStatus
    mode: AdapterMode


class ReadyResponse(BaseModel):
    model_config = _Strict
    ready: bool
    api_version: str
    adapters: dict[str, AdapterState]


class ModelInfo(BaseModel):
    model_config = _Strict
    id: str
    display_name: str
    purpose: str
    version: str
    mode: AdapterMode
    status: AnalyzerStatus
    last_updated: str | None = None


class VersionResponse(BaseModel):
    model_config = _Strict
    api_version: str
    app_version: str
    adapter_mode: AdapterMode


# ------------------------------------------------------------------- errors


class ErrorBody(BaseModel):
    model_config = _Strict
    code: str
    message: str
    detail: str | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    model_config = _Strict
    error: ErrorBody


# ---------------------------------------------------------------- webhooks


class WebhookTestRequest(BaseModel):
    """Development/security-workflow test endpoint - not a bank integration."""

    model_config = _Strict
    url: str | None = None
    event: str = "VOICE_RISK_ESCALATION"
    session_id: str | None = None


class WebhookTestResponse(BaseModel):
    model_config = _Strict
    event_id: str
    signature: str
    signed: bool
    delivered: bool
    payload: dict[str, Any]
    note: str
