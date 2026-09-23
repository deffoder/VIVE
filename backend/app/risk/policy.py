"""Policy engine.

Maps a risk assessment to a recommended action and decides whether an alert is
raised. Every action is ADVISORY: VIVE never acts on an account
(docs/PROJECT_SPEC.md 2).

A call is never actioned on risk score alone - confidence gates escalation, so
a high score from thin evidence recommends verification rather than a hold.
"""

from __future__ import annotations

from app.schemas.models import (
    Intent,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    RecommendedAction,
    RiskLevel,
)

POLICY_VERSION = "policy-demo-1"

MIN_CONFIDENCE_FOR_ESCALATION = 0.5
"""Below this, evidence is too thin to recommend anything stronger than verification."""

SENSITIVE_INTENTS = {
    Intent.OTP_REQUEST,
    Intent.PASSWORD_REQUEST,
    Intent.CARD_DETAILS_REQUEST,
    Intent.BANKING_CREDENTIAL_REQUEST,
    Intent.MONEY_TRANSFER_REQUEST,
    Intent.REMOTE_ACCESS_REQUEST,
}


def evaluate(request: PolicyEvaluateRequest) -> PolicyEvaluateResponse:
    level = request.risk_level or _level_for(request.risk_score)
    reasons: list[str] = []

    if request.confidence < MIN_CONFIDENCE_FOR_ESCALATION:
        reasons.append("Confidence is low; evidence is insufficient to escalate")
        action = (
            RecommendedAction.SECONDARY_VERIFICATION
            if level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            else RecommendedAction.MONITOR
        )
        return PolicyEvaluateResponse(
            recommended_action=action,
            should_alert=False,
            reasons=reasons,
            policy_version=POLICY_VERSION,
        )

    sensitive = request.intent in SENSITIVE_INTENTS
    if sensitive:
        reasons.append(f"Sensitive request: {request.intent.value.replace('_', ' ').lower()}")
    if not request.caller_verified:
        reasons.append("Caller not independently verified")

    if level == RiskLevel.CRITICAL:
        action = (
            RecommendedAction.HOLD_SENSITIVE_ACTION
            if sensitive and not request.caller_verified
            else RecommendedAction.ESCALATE
        )
    elif level == RiskLevel.HIGH:
        action = (
            RecommendedAction.SECONDARY_VERIFICATION
            if sensitive
            else RecommendedAction.ESCALATE
        )
    elif level == RiskLevel.MEDIUM:
        action = RecommendedAction.WARN_USER
    else:
        action = RecommendedAction.MONITOR

    should_alert = level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    if should_alert:
        reasons.append(f"{level.value} risk with sufficient confidence")

    return PolicyEvaluateResponse(
        recommended_action=action,
        should_alert=should_alert,
        reasons=reasons or ["No policy condition met"],
        policy_version=POLICY_VERSION,
    )


def _level_for(score: int) -> RiskLevel:
    if score >= 85:
        return RiskLevel.CRITICAL
    if score >= 65:
        return RiskLevel.HIGH
    if score >= 35:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
