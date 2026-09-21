"""MOCK / DEMO adapters - NOT MODEL OUTPUT.

Nothing in this module runs inference. Every value is produced by deterministic
keyword and hash rules over a transcript so integration tests and demos are
repeatable. None of it may be cited as accuracy, detection capability or
performance.

Three things keep it identifiable at every layer:
  * every result carries `mode = AdapterMode.MOCK`;
  * every `model_version` is the literal string "demo", never a plausible
    semantic version;
  * the packets these produce carry `adapter_mode: "mock"`, which the Android
    client renders as a non-dismissable "Demo data" badge.

Replaced by real adapters in the ML phase (docs/ML_SPEC.md 9). The interfaces
in app.adapters.interfaces are what makes that a configuration change.
"""

from __future__ import annotations

import hashlib
import re

from app.adapters.interfaces import (
    AdapterBundle,
    AdapterInfo,
    AntiSpoofResult,
    AsrResult,
    AudioWindow,
    BehaviorResult,
    IntentResult,
    SpeakerResult,
    VadResult,
)
from app.schemas.models import (
    AdapterMode,
    AnalyzerStatus,
    AudioQuality,
    Behavior,
    Intent,
)

DEMO_VERSION = "demo"
"""Deliberately not a semantic version, so it cannot be mistaken for a release."""

_MODE = AdapterMode.MOCK


class _MockInfo:
    """Shared `describe()` for the mock adapters.

    Every mock reports `mode=MOCK` and carries no execution provider, so a
    consumer can never mistake scripted output for real inference. Mock
    adapters are retained deliberately for deterministic tests and demo
    fallback (docs/ML_SPEC.md 4).
    """

    adapter_key: str = "?"
    architecture: str | None = "scripted"
    languages: tuple[str, ...] = ()

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=(AnalyzerStatus.AVAILABLE if self.available()
                    else AnalyzerStatus.UNAVAILABLE),
            architecture=self.architecture,
            languages=self.languages,
            sample_rate=16_000,
            detail="Deterministic scripted output. Not model inference.",
        )


_WORD_RE = re.compile("[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    """Whole-word match, including multi-word phrases.

    Substring matching is wrong here: "fir" (from the threat list) occurs
    inside "confirm", so a meeting confirmation was classified as
    intimidation. Matching on token sequences fixes that and keeps phrases
    like "card number" working, which a naive per-word check would not.
    """
    words = _tokens(text)
    for keyword in keywords:
        needle = _tokens(keyword)
        if not needle:
            continue
        span = len(needle)
        if any(words[i : i + span] == needle for i in range(len(words) - span + 1)):
            return True
    return False


def _stable_unit(*parts: str) -> float:
    """Deterministic 0-1 value from the inputs. Same input, same output, always."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


# Keyword tables driving the demo classifiers. These are scenario scripting,
# not a model: they exist so DEMO_SPEC S1-S4 behave predictably.
_INTENT_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.OTP_REQUEST, ("otp", "one time", "code", "sollunga", "bataiye")),
    (Intent.PASSWORD_REQUEST, ("password", "pin", "passcode")),
    (Intent.CARD_DETAILS_REQUEST, ("card number", "cvv", "card")),
    (Intent.BANKING_CREDENTIAL_REQUEST, ("net banking", "login", "credential")),
    (Intent.MONEY_TRANSFER_REQUEST, ("transfer", "send money", "payment")),
    (Intent.ACCOUNT_CHANGE_REQUEST, ("change account", "update account")),
    (Intent.REMOTE_ACCESS_REQUEST, ("anydesk", "teamviewer", "remote", "screen share")),
    (Intent.THREAT_OR_INTIMIDATION, ("arrest", "police", "legal action", "fir")),
    (Intent.CONFIDENTIAL_INFORMATION, ("confidential", "don't tell", "mat bataiye", "secret")),
    (Intent.URGENT_ACTION, ("urgent", "immediately", "seekiram", "turant", "jaldi", "blocked")),
]

_BEHAVIOR_KEYWORDS: list[tuple[Behavior, tuple[str, ...]]] = [
    (Behavior.URGENCY, ("urgent", "immediately", "seekiram", "turant", "jaldi", "hurry")),
    (Behavior.THREAT, ("blocked", "close", "arrest", "suspend", "band")),
    (Behavior.AUTHORITY_IMPERSONATION, ("bank officer", "from your bank", "officer", "official")),
    (Behavior.SECRECY, ("confidential", "don't tell", "mat bataiye", "secret", "sollaadhe")),
    (Behavior.PRESSURE, ("now", "quickly", "must", "have to")),
    (Behavior.FEAR, ("suspicious", "fraud", "problem", "unauthorized")),
    (Behavior.REWARD_PROMISE, ("prize", "cashback", "reward", "lottery")),
]

_SYNTHETIC_HINTS = ("synthetic", "cloned", "deepfake")


class MockVadAdapter(_MockInfo):
    id = "silero-vad"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "vad"

    def available(self) -> bool:
        return True

    def analyze(self, window: AudioWindow) -> VadResult:
        has_text = bool(window.transcript_hint and window.transcript_hint.strip())
        has_audio = len(window.pcm) > 0

        if not has_text and not has_audio:
            return VadResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version,
                mode=self.mode,
                has_speech=False,
                quality=AudioQuality.NO_SPEECH,
            )

        # Very short payloads stand in for unusable audio (DEMO_SPEC S4).
        if has_audio and len(window.pcm) < 640 and not has_text:
            return VadResult(
                status=AnalyzerStatus.AVAILABLE,
                model_version=self.version,
                mode=self.mode,
                has_speech=False,
                quality=AudioQuality.POOR,
            )

        return VadResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            has_speech=True,
            quality=AudioQuality.GOOD,
            inference_ms=3,
        )


class MockAntiSpoofAdapter(_MockInfo):
    id = "aasist"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "antispoof"

    def available(self) -> bool:
        return True

    def analyze(self, window: AudioWindow) -> AntiSpoofResult:
        text = (window.transcript_hint or "").lower()
        if not text and not window.pcm:
            return AntiSpoofResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version,
                mode=self.mode,
                score=None,
            )
        # Scenario scripting: an explicit marker drives the synthetic path so
        # S3 is reproducible; otherwise a stable low-to-moderate value.
        #
        # Seeded from the CONTENT, not the session id: a demo must produce the
        # same scores every run, and session ids differ between runs.
        seed = _stable_unit(text, str(window.seq))
        if _matches(text, _SYNTHETIC_HINTS):
            score = 0.80 + 0.15 * seed
        else:
            score = 0.04 + 0.12 * seed
        return AntiSpoofResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            score=round(min(score, 0.99), 4),
            inference_ms=12,
        )


class MockSpeakerAdapter(_MockInfo):
    """Always NO_REFERENCE: no enrolment source is defined (docs/BLOCKERS.md O3)."""

    id = "ecapa-tdnn"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "speaker"

    def available(self) -> bool:
        return True

    def analyze(self, window: AudioWindow, reference: bytes | None) -> SpeakerResult:
        if not reference:
            return SpeakerResult(
                status=AnalyzerStatus.NO_REFERENCE,
                model_version=self.version,
                mode=self.mode,
                similarity=None,
            )
        similarity = round(0.35 + 0.4 * _stable_unit(str(window.seq)), 4)
        return SpeakerResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            similarity=similarity,
            inference_ms=6,
        )


class MockAsrAdapter(_MockInfo):
    """Echoes the caller-supplied transcript hint. It does not transcribe audio."""

    id = "indic-conformer-600m"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "asr"
    languages = ('hi', 'ta', 'en')

    def available(self) -> bool:
        return True

    def analyze(self, window: AudioWindow) -> AsrResult:
        text = (window.transcript_hint or "").strip()
        if not text:
            return AsrResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version,
                mode=self.mode,
                transcript=None,
                confidence=None,
            )
        language = _guess_language(text)
        return AsrResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            transcript=text,
            confidence=round(0.85 + 0.1 * _stable_unit(text), 4),
            language=language,
            language_confidence=0.88,
            inference_ms=28,
        )


def _guess_language(text: str) -> str:
    """Crude script/keyword check. A stand-in for language ID, not a model."""
    lowered = text.lower()
    if any(word in lowered for word in ("sollunga", "pannunga", "vanakkam", "irukku", "aagidum")):
        return "ta"
    if any(word in lowered for word in ("bataiye", "kijiye", "hai", "aapke", "karna")):
        return "hi"
    return "en"


class MockIntentAdapter(_MockInfo):
    id = "intent-classifier"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "intent"
    languages = ('en', 'hi')

    def available(self) -> bool:
        return True

    def analyze(self, transcript: str | None) -> IntentResult:
        if not transcript:
            return IntentResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version,
                mode=self.mode,
                label=Intent.UNKNOWN,
                confidence=None,
            )
        lowered = transcript.lower()
        for label, keywords in _INTENT_KEYWORDS:
            if _matches(lowered, keywords):
                return IntentResult(
                    status=AnalyzerStatus.AVAILABLE,
                    model_version=self.version,
                    mode=self.mode,
                    label=label,
                    confidence=round(0.80 + 0.15 * _stable_unit(lowered, label), 4),
                )
        return IntentResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            label=Intent.NORMAL_CONVERSATION,
            confidence=round(0.75 + 0.2 * _stable_unit(lowered), 4),
        )


class MockBehaviorAdapter(_MockInfo):
    id = "behavior-classifier"
    version = DEMO_VERSION
    mode = _MODE
    adapter_key = "behavior"
    languages = ('en', 'hi')

    def available(self) -> bool:
        return True

    def analyze(self, transcript: str | None) -> BehaviorResult:
        if not transcript:
            return BehaviorResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version,
                mode=self.mode,
                labels=[],
                confidence=None,
            )
        lowered = transcript.lower()
        labels = [label for label, keywords in _BEHAVIOR_KEYWORDS
                  if _matches(lowered, keywords)]
        if not labels:
            labels = [Behavior.NORMAL]
        return BehaviorResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            labels=labels,
            confidence=round(0.78 + 0.15 * _stable_unit(lowered, "behavior"), 4),
        )


def build_mock_bundle() -> AdapterBundle:
    return AdapterBundle(
        vad=MockVadAdapter(),
        antispoof=MockAntiSpoofAdapter(),
        speaker=MockSpeakerAdapter(),
        asr=MockAsrAdapter(),
        intent=MockIntentAdapter(),
        behavior=MockBehaviorAdapter(),
    )
