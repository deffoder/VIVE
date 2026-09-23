"""Risk fusion.

Transparent weighted fusion over the evidence a packet produced. Weights live
in WEIGHTS and are versioned as `risk-fusion`; no final score is hard-coded
(docs/ML_SPEC.md 6).

The rules this enforces, restating docs/PROJECT_SPEC.md 2-3:

  * High anti-spoof evidence ALONE must not reach CRITICAL. Synthetic speech is
    not automatically fraud.
  * Low anti-spoof evidence must not cap risk. Human-voice social engineering
    is the common case, so intent and behaviour can drive risk on their own.
  * Missing evidence lowers CONFIDENCE, not risk.
  * Poor audio must never inflate the score.
  * Score and confidence are computed separately and never substituted.

Weights here are expert-set, not learned. They are provisional until real model
outputs exist to calibrate against (docs/BLOCKERS.md O6).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.interfaces import (
    AntiSpoofResult,
    AsrResult,
    BehaviorResult,
    IntentResult,
    SpeakerResult,
    VadResult,
)
from app.schemas.models import (
    AnalyzerStatus,
    AudioQuality,
    Behavior,
    Intent,
    OodState,
    PacketRisk,
    RiskLevel,
)

FUSION_VERSION = "risk-fusion-demo-1"

INFLUENCE: dict[str, float] = {
    "synthetic": 0.45,
    "intent": 0.72,
    "behavior": 0.45,
    "context": 0.22,
    "speaker_consistency": 0.30,
    "sensitive_request": 0.72,
}
"""Maximum influence each signal can exert, used in a noisy-OR combination.

NOT a weighted average. An average lets a LOW signal actively cancel a HIGH
one: benign anti-spoof evidence would suppress a clear OTP request, which is
precisely the failure mode docs/PROJECT_SPEC.md 2.1 warns about ("human voice
is not automatically safe"). Noisy-OR has the property risk actually needs -
strong evidence on any channel raises the score, and weak evidence on another
simply contributes little rather than subtracting.
"""

# Retained name so callers and docs referring to WEIGHTS still resolve.
WEIGHTS = INFLUENCE

LEVEL_THRESHOLDS: list[tuple[int, RiskLevel]] = [
    (85, RiskLevel.CRITICAL),
    (65, RiskLevel.HIGH),
    (35, RiskLevel.MEDIUM),
    (0, RiskLevel.LOW),
]

SYNTHETIC_ONLY_CEILING = 64
"""Anti-spoof evidence alone cannot push a packet past HIGH's lower bound."""

INTENT_RISK: dict[Intent, float] = {
    Intent.NORMAL_CONVERSATION: 0.05,
    Intent.UNKNOWN: 0.10,
    Intent.URGENT_ACTION: 0.50,
    Intent.CONFIDENTIAL_INFORMATION: 0.60,
    Intent.ACCOUNT_CHANGE_REQUEST: 0.65,
    Intent.REMOTE_ACCESS_REQUEST: 0.85,
    Intent.OTP_REQUEST: 0.92,
    Intent.PASSWORD_REQUEST: 0.92,
    Intent.CARD_DETAILS_REQUEST: 0.90,
    Intent.BANKING_CREDENTIAL_REQUEST: 0.92,
    Intent.MONEY_TRANSFER_REQUEST: 0.94,
    Intent.THREAT_OR_INTIMIDATION: 0.88,
}

BEHAVIOR_RISK: dict[Behavior, float] = {
    Behavior.NORMAL: 0.05,
    Behavior.REWARD_PROMISE: 0.45,
    Behavior.PRESSURE: 0.55,
    Behavior.URGENCY: 0.60,
    Behavior.SECRECY: 0.70,
    Behavior.FEAR: 0.72,
    Behavior.AUTHORITY_IMPERSONATION: 0.80,
    Behavior.THREAT: 0.85,
}


REQUEST_PHRASE: dict[Intent, str] = {
    Intent.OTP_REQUEST: "a one-time password (OTP)",
    Intent.PASSWORD_REQUEST: "a password or PIN",
    Intent.CARD_DETAILS_REQUEST: "card details",
    Intent.REMOTE_ACCESS_REQUEST: "remote access to the phone",
    Intent.MONEY_TRANSFER_REQUEST: "a money transfer",
}
"""How a rule finding reads to a person: 'Caller asked for a password or PIN'."""


@dataclass(frozen=True)
class FusionInput:
    vad: VadResult
    antispoof: AntiSpoofResult
    speaker: SpeakerResult
    asr: AsrResult
    intent: IntentResult
    behavior: BehaviorResult
    caller_verified: bool
    session_authenticated: bool
    sensitive_request: Intent | None = None
    """What the rule-based detector (app.risk.sensitive) found, if anything.

    Its own channel, at the intent head's influence and severity table,
    because it answers the same question from a different mechanism. It never
    replaces the intent label: when both fire, noisy-OR counts both, which is
    the point - two independent mechanisms agreeing is stronger evidence.
    None (the default) leaves fusion exactly as before."""


@dataclass(frozen=True)
class FusionOutput:
    risk: PacketRisk
    quality: AudioQuality
    ood_state: OodState
    uncertainty: float
    context_risk: float


def fuse(data: FusionInput) -> FusionOutput:
    quality = data.vad.quality
    contributions: dict[str, float] = {}
    reasons: list[str] = []

    # --- context ---------------------------------------------------------
    context_risk = 0.15
    if not data.caller_verified:
        context_risk += 0.45
        reasons.append("Caller not independently verified")
    if not data.session_authenticated:
        context_risk += 0.20
    context_risk = min(context_risk, 1.0)
    contributions["context"] = round(context_risk, 4)

    # --- synthetic evidence ---------------------------------------------
    synthetic = data.antispoof.score
    if synthetic is not None:
        contributions["synthetic"] = round(synthetic, 4)
        if synthetic >= 0.75:
            reasons.append("Elevated synthetic-voice indicators")

    # --- intent ----------------------------------------------------------
    intent_risk = INTENT_RISK.get(data.intent.label, 0.10)
    if data.intent.status == AnalyzerStatus.AVAILABLE:
        contributions["intent"] = round(intent_risk, 4)
        if intent_risk >= 0.85:
            reasons.append(f"{_humanise(data.intent.label)} detected")

    # --- behaviour -------------------------------------------------------
    behavior_risk = 0.0
    if data.behavior.status == AnalyzerStatus.AVAILABLE and data.behavior.labels:
        behavior_risk = max(BEHAVIOR_RISK.get(b, 0.3) for b in data.behavior.labels)
        contributions["behavior"] = round(behavior_risk, 4)
        notable = [b for b in data.behavior.labels if BEHAVIOR_RISK.get(b, 0) >= 0.6]
        if notable:
            reasons.append(f"{_humanise(notable[0])} in conversation")

    # --- speaker ---------------------------------------------------------
    speaker_risk = 0.0
    if data.speaker.status == AnalyzerStatus.AVAILABLE and data.speaker.similarity is not None:
        # Low similarity to the enrolled voice is the risky direction.
        speaker_risk = 1.0 - data.speaker.similarity
        contributions["speaker_consistency"] = round(data.speaker.similarity, 4)

    # --- rule-based sensitive request -----------------------------------
    rule_risk = 0.0
    if data.sensitive_request is not None:
        rule_risk = INTENT_RISK.get(data.sensitive_request, 0.10)
        contributions["sensitive_request"] = round(rule_risk, 4)
        reasons.append(f"Caller asked for {REQUEST_PHRASE.get(data.sensitive_request, 'sensitive information')} "
                       "(keyword rule)")

    # --- noisy-OR over AVAILABLE evidence only ---------------------------
    #
    # Intent is included only when the head actually ran. It used to be added
    # unconditionally, which broke the rule above that missing evidence lowers
    # confidence rather than risk: a failed or UNSUPPORTED_LANGUAGE head still
    # carried UNKNOWN's 0.10, which is DOUBLE a benign NORMAL_CONVERSATION's
    # 0.05. A model outage raised the score (measured: 26 -> 28), the score
    # stopped reconciling with `contributions` - which correctly omitted
    # intent - and confidence did not fall, because signal_count counts these
    # parts. It also penalised Tamil specifically, since every Tamil packet
    # reports UNSUPPORTED_LANGUAGE by design (docs/BLOCKERS.md O11), so an
    # identical call scored higher in Tamil than in Hindi.
    parts: dict[str, float] = {"context": context_risk}
    if data.intent.status == AnalyzerStatus.AVAILABLE:
        parts["intent"] = intent_risk
    if synthetic is not None:
        parts["synthetic"] = synthetic
    if behavior_risk:
        parts["behavior"] = behavior_risk
    if speaker_risk:
        parts["speaker_consistency"] = speaker_risk
    if rule_risk:
        parts["sensitive_request"] = rule_risk

    survival = 1.0
    for key, value in parts.items():
        survival *= 1.0 - INFLUENCE[key] * value
    raw = 1.0 - survival
    score = int(round(raw * 100))

    # --- guard rails -----------------------------------------------------
    # Read from `parts` so an unavailable intent head cannot contribute
    # semantic pressure it never measured.
    semantic_pressure = max(parts.get("intent", 0.0), behavior_risk, rule_risk)
    if semantic_pressure < 0.4 and score > SYNTHETIC_ONLY_CEILING:
        # Synthetic evidence alone cannot reach CRITICAL.
        score = SYNTHETIC_ONLY_CEILING
        reasons.append("Synthetic indicators alone are not treated as fraud")

    if quality in (AudioQuality.POOR, AudioQuality.NO_SPEECH):
        # Unusable audio is not evidence. Cap risk low and say so.
        score = min(score, 15)
        reasons = ["Insufficient clear speech to assess", f"Audio quality {quality.value}"]
        contributions = {k: v for k, v in contributions.items() if k == "context"}

    score = max(0, min(100, score))
    level = _level_for(score)

    # --- confidence, computed separately ---------------------------------
    confidence, uncertainty = _confidence(data, quality, len(parts))

    return FusionOutput(
        risk=PacketRisk(
            score=score,
            level=level,
            confidence=round(confidence, 4),
            contributions=contributions,
            reasons=reasons or ["No notable risk indicators"],
        ),
        quality=quality,
        ood_state=_ood_state(synthetic, quality),
        uncertainty=round(uncertainty, 4),
        context_risk=round(context_risk, 4),
    )


def _confidence(data: FusionInput, quality: AudioQuality, signal_count: int) -> tuple[float, float]:
    """Confidence reflects how much evidence supports the assessment.

    It is independent of the score: a 2-second window of poor audio can yield a
    low score at low confidence, and that is the correct output.
    """
    confidence = 0.55
    confidence += min(signal_count, 5) * 0.06

    if quality == AudioQuality.GOOD:
        confidence += 0.15
    elif quality == AudioQuality.DEGRADED:
        confidence -= 0.10
    else:
        confidence -= 0.40

    if data.asr.status == AnalyzerStatus.AVAILABLE and data.asr.confidence:
        confidence += (data.asr.confidence - 0.8) * 0.2
    if data.speaker.status == AnalyzerStatus.NO_REFERENCE:
        confidence -= 0.05
    if data.antispoof.score is None:
        confidence -= 0.15

    confidence = max(0.05, min(0.97, confidence))
    return confidence, max(0.03, 1.0 - confidence)


def _ood_state(synthetic: float | None, quality: AudioQuality) -> OodState:
    if quality in (AudioQuality.POOR, AudioQuality.NO_SPEECH) or synthetic is None:
        return OodState.UNAVAILABLE
    if synthetic >= 0.75:
        return OodState.KNOWN_SYNTHETIC_LIKELY
    return OodState.IN_DISTRIBUTION


def _level_for(score: int) -> RiskLevel:
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _humanise(value: Intent | Behavior) -> str:
    return value.value.replace("_", " ").capitalize()
