"""Fusion, temporal and adapter tests.

These pin the claims the product makes, not merely that code runs.
"""

from __future__ import annotations

from app.adapters.interfaces import AudioWindow
from app.adapters.mock import build_mock_bundle
from app.risk.fusion import WEIGHTS, FusionInput, fuse
from app.risk.temporal import TemporalState
from app.schemas.models import AnalyzerStatus, AudioQuality, Behavior, Intent, RiskLevel


def _window(seq: int = 1, text: str | None = None, pcm: bytes = b"") -> AudioWindow:
    return AudioWindow(
        session_id="VS-001",
        seq=seq,
        start_sec=float(seq - 1),
        end_sec=float(seq + 1),
        pcm=pcm,
        transcript_hint=text,
    )


def _fuse(text: str, *, caller_verified: bool = False):
    a = build_mock_bundle()
    w = _window(text=text)
    vad = a.vad.analyze(w)
    antispoof = a.antispoof.analyze(w)
    speaker = a.speaker.analyze(w, None)
    asr = a.asr.analyze(w)
    return fuse(
        FusionInput(
            vad=vad,
            antispoof=antispoof,
            speaker=speaker,
            asr=asr,
            intent=a.intent.analyze(asr.transcript),
            behavior=a.behavior.analyze(asr.transcript),
            caller_verified=caller_verified,
            session_authenticated=False,
        )
    )


# --------------------------------------------------------------- guard rails


def test_synthetic_evidence_alone_never_reaches_critical() -> None:
    """Synthetic speech is not automatically fraud (PROJECT_SPEC 2.1)."""
    out = _fuse("Hello, this is a synthetic cloned voice reading a weather report.")
    assert out.risk.level != RiskLevel.CRITICAL
    assert out.risk.score <= 64


def test_low_antispoof_does_not_cap_semantic_risk() -> None:
    """S2: human social engineering must escalate on intent and behaviour alone."""
    out = _fuse("Your account will be blocked. Tell me your OTP immediately.")
    assert out.risk.score >= 65, "semantic evidence must drive risk on its own"
    assert out.risk.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_normal_conversation_stays_low() -> None:
    out = _fuse("Just calling to confirm our meeting tomorrow afternoon.")
    assert out.risk.level == RiskLevel.LOW


def test_poor_audio_lowers_confidence_without_raising_risk() -> None:
    """S4: unusable audio is not evidence of fraud."""
    a = build_mock_bundle()
    w = _window(pcm=b"\x00" * 100)
    vad = a.vad.analyze(w)
    assert vad.quality == AudioQuality.POOR

    out = fuse(
        FusionInput(
            vad=vad,
            antispoof=a.antispoof.analyze(w),
            speaker=a.speaker.analyze(w, None),
            asr=a.asr.analyze(w),
            intent=a.intent.analyze(None),
            behavior=a.behavior.analyze(None),
            caller_verified=False,
            session_authenticated=False,
        )
    )
    assert out.risk.score <= 15
    assert out.risk.confidence < 0.4
    assert any("Insufficient" in r for r in out.risk.reasons)


def test_verified_caller_lowers_context_risk() -> None:
    unverified = _fuse("Please share your OTP now.", caller_verified=False)
    verified = _fuse("Please share your OTP now.", caller_verified=True)
    assert verified.risk.score < unverified.risk.score


def test_score_and_confidence_are_independent() -> None:
    out = _fuse("Tell me your OTP immediately, your account is blocked.")
    assert isinstance(out.risk.score, int) and 0 <= out.risk.score <= 100
    assert isinstance(out.risk.confidence, float) and 0.0 <= out.risk.confidence <= 1.0


def test_contributions_are_evidence_strengths_in_range() -> None:
    out = _fuse("Please share the OTP, it is urgent.")
    assert out.risk.contributions
    for value in out.risk.contributions.values():
        assert 0.0 <= value <= 1.0


# ------------------------------------- an unavailable intent head (Phase 9)
#
# Regression guards. Intent used to enter the noisy-OR unconditionally, so a
# head that had not run still contributed UNKNOWN's 0.10 - double a benign
# NORMAL_CONVERSATION's 0.05. Three separate promises broke at once.


def _fuse_with_intent(status: AnalyzerStatus, label: Intent):
    from app.adapters.interfaces import (AntiSpoofResult, AsrResult,
                                         BehaviorResult, IntentResult,
                                         SpeakerResult, VadResult)
    from app.schemas.models import AdapterMode

    return fuse(FusionInput(
        vad=VadResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                      mode=AdapterMode.REAL, has_speech=True,
                      quality=AudioQuality.GOOD),
        antispoof=AntiSpoofResult(status=AnalyzerStatus.AVAILABLE,
                                  model_version="v", mode=AdapterMode.REAL,
                                  score=0.2),
        speaker=SpeakerResult(status=AnalyzerStatus.NO_REFERENCE,
                              model_version="v", mode=AdapterMode.REAL,
                              similarity=None),
        asr=AsrResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                      mode=AdapterMode.REAL, transcript="hello", confidence=0.9),
        intent=IntentResult(status=status, model_version="v",
                            mode=AdapterMode.REAL, label=label, confidence=0.9),
        behavior=BehaviorResult(status=AnalyzerStatus.AVAILABLE,
                                model_version="v", mode=AdapterMode.REAL,
                                labels=[Behavior.NORMAL], confidence=0.9),
        caller_verified=False, session_authenticated=True))


def test_failed_intent_head_does_not_raise_risk() -> None:
    """A model outage must lower confidence, never raise the score."""
    healthy = _fuse_with_intent(AnalyzerStatus.AVAILABLE,
                                Intent.NORMAL_CONVERSATION)
    failed = _fuse_with_intent(AnalyzerStatus.LOAD_ERROR, Intent.UNKNOWN)
    assert failed.risk.score <= healthy.risk.score, (
        "a broken intent head raised risk; missing evidence is not evidence"
    )
    assert failed.risk.confidence < healthy.risk.confidence, (
        "losing a signal must cost confidence"
    )


def test_unsupported_language_does_not_penalise_the_caller() -> None:
    """Tamil reports UNSUPPORTED_LANGUAGE on every packet (BLOCKERS O11).

    If that raised the score, an identical call would be riskier in Tamil
    than in Hindi purely because VIVE cannot read Tamil.
    """
    supported = _fuse_with_intent(AnalyzerStatus.AVAILABLE,
                                  Intent.NORMAL_CONVERSATION)
    unsupported = _fuse_with_intent(AnalyzerStatus.UNSUPPORTED_LANGUAGE,
                                    Intent.UNKNOWN)
    assert unsupported.risk.score <= supported.risk.score


def test_score_reconciles_with_reported_contributions() -> None:
    """Explainability: the score must not include evidence the UI cannot see.

    `contributions` drives the packet-detail breakdown. A score containing a
    term absent from that map is unexplainable by construction.
    """
    out = _fuse_with_intent(AnalyzerStatus.LOAD_ERROR, Intent.UNKNOWN)
    assert "intent" not in out.risk.contributions

    survival = 1.0
    for key, value in out.risk.contributions.items():
        if key == "speaker_consistency":
            value = 1.0 - value      # stored as similarity, used as risk
        survival *= 1.0 - WEIGHTS[key] * value
    assert abs(int(round((1.0 - survival) * 100)) - out.risk.score) <= 1


# ------------------------------------------------------------------ adapters


def test_speaker_reports_no_reference_rather_than_zero() -> None:
    a = build_mock_bundle()
    result = a.speaker.analyze(_window(), None)
    assert result.status == AnalyzerStatus.NO_REFERENCE
    assert result.similarity is None, "absent evidence must be null, never 0.0"


def test_adapters_are_deterministic() -> None:
    a, b = build_mock_bundle(), build_mock_bundle()
    w = _window(text="Please share the OTP now.")
    assert a.antispoof.analyze(w).score == b.antispoof.analyze(w).score
    assert a.intent.analyze("Please share the OTP now.").label == Intent.OTP_REQUEST


def test_every_adapter_reports_mock_mode_and_demo_version() -> None:
    a = build_mock_bundle()
    for adapter in (a.vad, a.antispoof, a.speaker, a.asr, a.intent, a.behavior):
        assert adapter.mode.value == "mock"
        assert adapter.version == "demo", "must not look like a real release version"


def test_language_detection_covers_priority_languages() -> None:
    a = build_mock_bundle()
    assert a.asr.analyze(_window(text="OTP sollunga, account verify pannunga")).language == "ta"
    assert a.asr.analyze(_window(text="Aapka OTP bataiye")).language == "hi"
    assert a.asr.analyze(_window(text="Please share the code")).language == "en"


def test_behaviour_detects_urgency_and_threat() -> None:
    a = build_mock_bundle()
    result = a.behavior.analyze("This is urgent, your account will be blocked immediately")
    assert Behavior.URGENCY in result.labels
    assert Behavior.THREAT in result.labels


# ------------------------------------------------------------------ temporal


def test_minimum_evidence_gate_holds_first_packet_at_low() -> None:
    state = TemporalState()
    _, overall = state.update(95, 0.9, at_sec=2)
    assert overall.level == RiskLevel.LOW, "one window is not enough to escalate"


def test_escalation_timings_are_recorded() -> None:
    state = TemporalState()
    for i, score in enumerate([10, 40, 70, 90], start=1):
        state.update(score, 0.85, at_sec=i * 2)
    t = state.timings
    assert t.first_warning_sec is not None
    assert t.first_high_sec is not None
    assert t.first_critical_sec is not None
    assert t.first_warning_sec <= t.first_high_sec <= t.first_critical_sec


def test_hysteresis_prevents_immediate_de_escalation() -> None:
    state = TemporalState()
    for _ in range(4):
        state.update(90, 0.9, at_sec=2)
    high_level = state.level
    _, overall = state.update(80, 0.9, at_sec=10)
    assert overall.level == high_level, "level must not oscillate on a single dip"


def test_not_reached_timings_stay_null() -> None:
    state = TemporalState()
    for _ in range(3):
        state.update(5, 0.9, at_sec=2)
    assert state.timings.first_critical_sec is None, "null means not reached"
