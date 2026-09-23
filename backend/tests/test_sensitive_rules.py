"""Rule-based sensitive-request detection and its fusion channel."""

from app.adapters.interfaces import (AntiSpoofResult, AsrResult, BehaviorResult,
                                     IntentResult, SpeakerResult, VadResult)
from app.risk.fusion import FusionInput, fuse
from app.risk.sensitive import detect, detect_in_context
from app.schemas.models import AdapterMode, AnalyzerStatus, AudioQuality, Intent

M, V = AdapterMode.REAL, "v"


def test_requests_fire_across_scripts():
    assert detect("please tell me the OTP right now").label == "OTP_REQUEST"
    assert detect("अभी आपके फोन पर एक ओटीपी आया होगा कृप्या वह ओटीपी तुरंत बताइए").label == "OTP_REQUEST"
    assert detect("உங்கள் OTP எண்ணை உடனே சொல்லுங்கள்").label == "OTP_REQUEST"
    assert detect("install anydesk and give me the code").label == "REMOTE_ACCESS_REQUEST"


def test_mentions_and_warnings_do_not_fire():
    assert detect("your OTP is 482913. Do not share it with anyone") is None
    assert detect("never share your otp with anyone") is None
    assert detect("I will call you about the otp tomorrow") is None   # no request cue
    assert detect("") is None
    assert detect("stop") is None                       # 'otp' must be a whole word


def test_context_needs_new_evidence_in_the_current_window():
    prev = "an OTP has come to your phone"
    assert detect_in_context("please tell me now", prev).label == "OTP_REQUEST"
    # The next window still has the request in context but adds nothing new.
    assert detect_in_context("have a nice day", "an OTP please tell me now") is None


def _fuse(rule):
    return fuse(FusionInput(
        vad=VadResult(status=AnalyzerStatus.AVAILABLE, model_version=V, mode=M, quality=AudioQuality.GOOD),
        antispoof=AntiSpoofResult(status=AnalyzerStatus.UNAVAILABLE, model_version=V, mode=M),
        speaker=SpeakerResult(status=AnalyzerStatus.NO_REFERENCE, model_version=V, mode=M),
        asr=AsrResult(status=AnalyzerStatus.AVAILABLE, model_version=V, mode=M, confidence=0.9),
        intent=IntentResult(status=AnalyzerStatus.AVAILABLE, model_version=V, mode=M,
                            label=Intent.NORMAL_CONVERSATION),
        behavior=BehaviorResult(status=AnalyzerStatus.AVAILABLE, model_version=V, mode=M),
        caller_verified=False, session_authenticated=False, sensitive_request=rule))


def test_rule_raises_risk_on_its_own_channel_without_rewriting_intent():
    none, otp = _fuse(None), _fuse(Intent.OTP_REQUEST)
    assert "sensitive_request" not in none.risk.contributions
    assert otp.risk.contributions["sensitive_request"] == 0.92
    assert otp.risk.contributions["intent"] == 0.05          # model label untouched
    assert otp.risk.score >= 65 > none.risk.score
    assert any("keyword rule" in r for r in otp.risk.reasons)
