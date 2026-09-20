"""Operational, policy, model-inventory and webhook-test routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter

from app.api.deps import AuthDep, StateDep
from app.core.security import AuditEvent, audit, sign_payload
from app.core.config import get_settings
from app.risk import policy
from app.risk.fusion import FUSION_VERSION
from app.schemas.models import (
    AdapterState,
    AnalyzerStatus,
    ModelInfo,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    ReadyResponse,
    VersionResponse,
    WebhookTestRequest,
    WebhookTestResponse,
)

router = APIRouter(tags=["system"])

APP_VERSION = "0.1.0"
API_VERSION = "v1"

_MODEL_CATALOG = [
    ("silero-vad", "Silero VAD", "Speech activity detection", "vad"),
    ("aasist", "AASIST", "Synthetic-voice evidence", "antispoof"),
    ("ecapa-tdnn", "ECAPA-TDNN", "Speaker consistency", "speaker"),
    ("indicconformer", "IndicConformer", "Multilingual speech recognition", "asr"),
    ("intent-classifier", "Intent Classifier", "Caller intent", "intent"),
    ("behavior-classifier", "Behaviour Classifier", "Social-engineering behaviour", "behavior"),
]


@router.get("/health", tags=["operational"], summary="Liveness")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadyResponse, tags=["operational"], summary="Readiness")
async def ready(state: StateDep) -> ReadyResponse:
    adapters = {
        name: AdapterState(status=status, mode=mode)
        for name, (status, mode) in state.adapters.states().items()
    }
    return ReadyResponse(ready=True, api_version=API_VERSION, adapters=adapters)


@router.get("/version", response_model=VersionResponse, tags=["operational"], summary="Version")
async def version(state: StateDep) -> VersionResponse:
    return VersionResponse(
        api_version=API_VERSION,
        app_version=APP_VERSION,
        adapter_mode=state.adapters.mode,
    )


@router.get("/models", response_model=list[ModelInfo], summary="Model inventory")
async def list_models(state: StateDep, principal: AuthDep) -> list[ModelInfo]:
    """Inventory with per-model mode.

    No accuracy field exists on purpose: none has been measured, and
    docs/ML_SPEC.md 8.5 forbids publishing an unmeasured metric.
    """
    states = state.adapters.states()
    models = [
        ModelInfo(
            id=model_id,
            display_name=display,
            purpose=purpose,
            version="demo" if states[key][1].value == "mock" else "",
            mode=states[key][1],
            status=states[key][0],
        )
        for model_id, display, purpose, key in _MODEL_CATALOG
    ]
    models.append(
        ModelInfo(
            id="risk-fusion",
            display_name="Risk Fusion",
            purpose="Calibrated risk from evidence",
            version=FUSION_VERSION,
            mode=state.adapters.mode,
            status=AnalyzerStatus.AVAILABLE,
        )
    )
    return models


@router.post(
    "/policies/evaluate",
    response_model=PolicyEvaluateResponse,
    summary="Evaluate the policy for a risk assessment",
)
async def evaluate_policy(
    request: PolicyEvaluateRequest, principal: AuthDep
) -> PolicyEvaluateResponse:
    return policy.evaluate(request)


@router.post(
    "/webhooks/test",
    response_model=WebhookTestResponse,
    summary="Exercise the webhook signing path (development only)",
)
async def webhook_test(
    request: WebhookTestRequest, state: StateDep, principal: AuthDep
) -> WebhookTestResponse:
    """Development/security-workflow test endpoint. NOT a bank integration.

    It builds and signs the payload that a real delivery would send, so the
    signing path is exercised, and reports `delivered: false` because nothing
    is transmitted. Claiming delivery here would be fabricating an integration.

    The payload carries risk metadata only - never transcript text or audio
    (docs/API_SPEC.md 8, SECURITY_SPEC 4).
    """
    settings = get_settings()
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    # Replay protection: a repeated event id is rejected, which is what makes
    # webhook delivery idempotent (docs/API_SPEC.md 8).
    state.replay_guard.check_and_record(event_id)
    audit(AuditEvent.WEBHOOK_TEST, principal, detail=event_id)
    payload = {
        "event": request.event,
        "event_id": event_id,
        "session_id": request.session_id,
        "risk_score": None,
        "risk_level": None,
        "intent": None,
        "note": "TEST EVENT - no real risk assessment attached",
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    if settings.webhook_signing_key:
        signature = sign_payload(settings.webhook_signing_key, body)
        signed = True
    else:
        signature = ""
        signed = False

    return WebhookTestResponse(
        event_id=event_id,
        signature=signature,
        signed=signed,
        delivered=False,
        payload=payload,
        note=(
            "Development test endpoint. The payload was built and signed but NOT "
            "transmitted. Configure VIVE_WEBHOOK_SIGNING_KEY to enable signing."
        ),
    )


@router.post(
    "/demo/reset",
    tags=["demo"],
    summary="Clear all sessions and demo state",
)
async def demo_reset(state: StateDep, principal: AuthDep) -> dict[str, object]:
    """Resets demo state so a demonstration can be rehearsed repeatedly.

    Removes every session and everything derived from it, clears WebSocket
    channels and resets the replay guard and rate limiters. This is real
    deletion, not a flag: the records are gone.

    Available because every adapter is a mock. It is refused once real
    adapters are configured, so it can never wipe production evidence.
    """
    if state.adapters.mode.value != "mock":
        from app.core.errors import ErrorCode, ViveError

        raise ViveError(
            ErrorCode.FORBIDDEN,
            "Demo reset is only available while adapters are in mock mode.",
        )

    cleared = state.store.count()
    state.store.clear()
    state.connections.reset()
    state.owners.clear()
    state.replay_guard.reset()
    state.rate_limiter.reset()
    state.create_limiter.reset()

    audit(AuditEvent.SESSION_DELETED, principal, detail=f"demo reset: {cleared} sessions")
    return {"reset": True, "sessions_cleared": cleared, "adapter_mode": "mock"}
