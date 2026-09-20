"""Model-service interfaces.

These are the boundary docs/ARCHITECTURE.md decision 7 requires: the backend
calls analyzers only through these protocols, so a mock adapter and a real
checkpoint-backed adapter are interchangeable without touching transport,
fusion, routes or UI.

Every result carries `status`, `model_version` and `mode`. An analyzer that
cannot run returns a status rather than raising, so the pipeline degrades
instead of collapsing (docs/ARCHITECTURE.md 9).

No real AASIST, ECAPA or ASR implementation belongs in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.schemas.models import (
    AdapterMode,
    AnalyzerStatus,
    AudioQuality,
    Behavior,
    Intent,
)

MODEL_IDS = {
    "vad": "silero-vad",
    "antispoof": "aasist",
    "speaker": "ecapa-tdnn",
    "asr": "indicconformer",
    "intent": "intent-classifier",
    "behavior": "behavior-classifier",
    "fusion": "risk-fusion",
}
"""Canonical model ids from docs/ML_SPEC.md 2, keyed by adapter name."""


@dataclass(frozen=True)
class AudioWindow:
    """One analysis window handed to the analyzers.

    16 kHz mono pcm_s16le, 2.0 s wide with a 1.0 s stride
    (docs/ML_SPEC.md 5). `pcm` may be empty when a caller submits a
    transcript-only demo packet.
    """

    session_id: str
    seq: int
    start_sec: float
    end_sec: float
    pcm: bytes = b""
    sample_rate: int = 16_000
    transcript_hint: str | None = None
    """Demo/replay only: lets a scripted scenario drive the pipeline without audio."""


@dataclass(frozen=True)
class AdapterResult:
    """Common envelope. `mode` is what keeps demo output identifiable."""

    status: AnalyzerStatus
    model_version: str
    mode: AdapterMode
    inference_ms: int = 0


@dataclass(frozen=True)
class VadResult(AdapterResult):
    has_speech: bool = False
    quality: AudioQuality = AudioQuality.NO_SPEECH


@dataclass(frozen=True)
class AntiSpoofResult(AdapterResult):
    score: float | None = None
    """Spoof likelihood 0-1. NOT a probability that the call is fraudulent."""


@dataclass(frozen=True)
class SpeakerResult(AdapterResult):
    similarity: float | None = None


@dataclass(frozen=True)
class AsrResult(AdapterResult):
    transcript: str | None = None
    confidence: float | None = None
    language: str | None = None
    language_confidence: float | None = None


@dataclass(frozen=True)
class IntentResult(AdapterResult):
    label: Intent = Intent.UNKNOWN
    confidence: float | None = None


@dataclass(frozen=True)
class BehaviorResult(AdapterResult):
    labels: list[Behavior] = field(default_factory=list)
    confidence: float | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    id: str
    version: str
    mode: AdapterMode

    def available(self) -> bool: ...


@runtime_checkable
class VadAdapter(ModelAdapter, Protocol):
    def analyze(self, window: AudioWindow) -> VadResult: ...


@runtime_checkable
class AntiSpoofAdapter(ModelAdapter, Protocol):
    def analyze(self, window: AudioWindow) -> AntiSpoofResult: ...


@runtime_checkable
class SpeakerAdapter(ModelAdapter, Protocol):
    def analyze(self, window: AudioWindow, reference: bytes | None) -> SpeakerResult: ...


@runtime_checkable
class AsrAdapter(ModelAdapter, Protocol):
    def analyze(self, window: AudioWindow) -> AsrResult: ...


@runtime_checkable
class IntentAdapter(ModelAdapter, Protocol):
    def analyze(self, transcript: str | None) -> IntentResult: ...


@runtime_checkable
class BehaviorAdapter(ModelAdapter, Protocol):
    def analyze(self, transcript: str | None) -> BehaviorResult: ...


@dataclass(frozen=True)
class AdapterBundle:
    """The full analyzer set the orchestrator calls."""

    vad: VadAdapter
    antispoof: AntiSpoofAdapter
    speaker: SpeakerAdapter
    asr: AsrAdapter
    intent: IntentAdapter
    behavior: BehaviorAdapter

    @property
    def mode(self) -> AdapterMode:
        return self.antispoof.mode

    def states(self) -> dict[str, tuple[AnalyzerStatus, AdapterMode]]:
        return {
            "vad": (
                AnalyzerStatus.AVAILABLE if self.vad.available() else AnalyzerStatus.UNAVAILABLE,
                self.vad.mode,
            ),
            "antispoof": (
                AnalyzerStatus.AVAILABLE
                if self.antispoof.available()
                else AnalyzerStatus.UNAVAILABLE,
                self.antispoof.mode,
            ),
            # Speaker is NO_REFERENCE rather than UNAVAILABLE: the adapter loads
            # fine, there is simply no enrolled voice (docs/BLOCKERS.md O3).
            "speaker": (AnalyzerStatus.NO_REFERENCE, self.speaker.mode),
            "asr": (
                AnalyzerStatus.AVAILABLE if self.asr.available() else AnalyzerStatus.UNAVAILABLE,
                self.asr.mode,
            ),
            "intent": (
                AnalyzerStatus.AVAILABLE if self.intent.available() else AnalyzerStatus.UNAVAILABLE,
                self.intent.mode,
            ),
            "behavior": (
                AnalyzerStatus.AVAILABLE
                if self.behavior.available()
                else AnalyzerStatus.UNAVAILABLE,
                self.behavior.mode,
            ),
        }
