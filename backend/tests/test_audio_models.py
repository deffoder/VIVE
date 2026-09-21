"""Phase 8C: real VAD, anti-spoofing and speaker adapters.

Contract and failure paths run with no checkpoints present. Real-inference
tests are skipped unless the corresponding model directory is configured.

The speaker tests are the ones to read carefully: `NO_REFERENCE` must never be
confusable with a mismatch, because treating "we have nothing to compare
against" as "this is a different speaker" would manufacture evidence.
"""

from __future__ import annotations

import os
import struct

import pytest

from app.adapters.interfaces import AudioWindow
from app.adapters.real.audio_models import (
    AASIST_SAMPLES,
    SPEECH_THRESHOLD,
    AasistAntiSpoofAdapter,
    EcapaSpeakerAdapter,
    SileroVadAdapter,
)
from app.schemas.models import AdapterMode, AnalyzerStatus, AudioQuality

SAMPLE_RATE = 16_000

VAD_DIR = os.environ.get("VIVE_VAD_MODEL_DIR", "")
SPOOF_DIR = os.environ.get("VIVE_ANTISPOOF_MODEL_DIR", "")
SPK_DIR = os.environ.get("VIVE_SPEAKER_MODEL_DIR", "")

requires_vad = pytest.mark.skipif(
    not (VAD_DIR and os.path.isfile(os.path.join(VAD_DIR, "silero_vad.jit"))),
    reason="set VIVE_VAD_MODEL_DIR")
requires_spoof = pytest.mark.skipif(
    not (SPOOF_DIR and os.path.isfile(os.path.join(SPOOF_DIR, "AASIST.pth"))),
    reason="set VIVE_ANTISPOOF_MODEL_DIR")
requires_spk = pytest.mark.skipif(
    not (SPK_DIR and os.path.isfile(os.path.join(SPK_DIR, "hyperparams.yaml"))),
    reason="set VIVE_SPEAKER_MODEL_DIR")


def tone(seconds: float = 2.0, amp: int = 8000) -> bytes:
    n = int(SAMPLE_RATE * seconds)
    return struct.pack(f"<{n}h", *[(amp if i % 160 < 80 else -amp) for i in range(n)])


def silence(seconds: float = 2.0) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def window(pcm: bytes = b"") -> AudioWindow:
    return AudioWindow(session_id="s", seq=1, start_sec=0.0, end_sec=2.0,
                       pcm=pcm or tone(), sample_rate=SAMPLE_RATE)


# --------------------------------------------------------------------------
# failure states
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [SileroVadAdapter, AasistAntiSpoofAdapter,
                                 EcapaSpeakerAdapter])
def test_missing_weights_is_load_error_and_stays_real(cls):
    a = cls("no/such/dir")
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert a.describe().mode is AdapterMode.REAL
    assert a.available() is False


def test_vad_failure_reports_no_speech_without_claiming_silence_was_measured():
    a = SileroVadAdapter("no/such/dir")
    a.load()
    r = a.analyze(window())
    assert r.status is AnalyzerStatus.LOAD_ERROR
    assert r.has_speech is False


def test_antispoof_failure_yields_no_score():
    a = AasistAntiSpoofAdapter("no/such/dir")
    a.load()
    r = a.analyze(window())
    assert r.status is AnalyzerStatus.LOAD_ERROR
    assert r.score is None, "a failed anti-spoof model must not emit a score"


def test_speaker_failure_yields_no_similarity():
    a = EcapaSpeakerAdapter("no/such/dir")
    a.load()
    r = a.analyze(window(), None)
    assert r.status is AnalyzerStatus.LOAD_ERROR
    assert r.similarity is None


def test_aasist_input_length_matches_upstream():
    assert AASIST_SAMPLES == 64_600
    assert 0.0 < SPEECH_THRESHOLD < 1.0


# --------------------------------------------------------------------------
# real inference
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vad():
    a = SileroVadAdapter(VAD_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(a.describe().detail or "vad unavailable")
    return a


@pytest.fixture(scope="module")
def spoof():
    a = AasistAntiSpoofAdapter(SPOOF_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(a.describe().detail or "antispoof unavailable")
    return a


@pytest.fixture(scope="module")
def speaker():
    a = EcapaSpeakerAdapter(SPK_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(a.describe().detail or "speaker unavailable")
    return a


@requires_vad
def test_vad_reports_silence_as_no_speech(vad):
    r = vad.analyze(window(silence()))
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.has_speech is False
    assert r.quality is AudioQuality.NO_SPEECH


@requires_vad
def test_vad_short_audio_is_insufficient(vad):
    r = vad.analyze(window(b"\x00\x00" * 100))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO


@requires_vad
def test_vad_quality_never_encodes_suspicion(vad):
    """Quality is a measured signal property, not a risk signal."""
    assert vad.analyze(window(silence())).quality in {
        AudioQuality.NO_SPEECH, AudioQuality.POOR, AudioQuality.DEGRADED,
        AudioQuality.GOOD}


@requires_spoof
def test_antispoof_produces_a_bounded_score(spoof):
    r = spoof.analyze(window(tone()))
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.score is not None and 0.0 <= r.score <= 1.0


@requires_spoof
def test_antispoof_is_deterministic(spoof):
    """Same audio, same score: a demo must be reproducible."""
    pcm = tone()
    assert spoof.analyze(window(pcm)).score == spoof.analyze(window(pcm)).score


@requires_spoof
def test_antispoof_short_audio_is_insufficient(spoof):
    r = spoof.analyze(window(b"\x00\x00" * 100))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO
    assert r.score is None


@requires_spk
def test_speaker_without_reference_is_no_reference_not_a_mismatch(speaker):
    r = speaker.analyze(window(tone()), None)
    assert r.status is AnalyzerStatus.NO_REFERENCE
    assert r.similarity is None, (
        "no enrolled voice means no comparison; emitting a similarity would "
        "manufacture speaker evidence"
    )


@requires_spk
def test_speaker_identical_audio_is_maximally_similar(speaker):
    pcm = tone()
    r = speaker.analyze(window(pcm), pcm)
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.similarity is not None and r.similarity > 0.99


@requires_spk
def test_speaker_empty_reference_is_no_reference(speaker):
    r = speaker.analyze(window(tone()), b"")
    assert r.status is AnalyzerStatus.NO_REFERENCE
    assert r.similarity is None


@requires_spk
def test_speaker_similarity_is_bounded(speaker):
    r = speaker.analyze(window(tone()), silence())
    if r.status is AnalyzerStatus.AVAILABLE:
        assert -1.0 <= r.similarity <= 1.0
