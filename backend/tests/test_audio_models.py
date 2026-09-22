"""Phase 8C: real VAD, anti-spoofing and speaker adapters.

Contract and failure paths run with no checkpoints present. Real-inference
tests are skipped unless the corresponding model directory is configured.

The speaker tests are the ones to read carefully: `NO_REFERENCE` must never be
confusable with a mismatch, because treating "we have nothing to compare
against" as "this is a different speaker" would manufacture evidence.
"""

from __future__ import annotations

import io
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


def fill(spoof, session_id: str, pcm_fn=tone):
    """Feeds overlapping windows until the adapter holds a full real window."""
    last = None
    for seq in range(1, 9):
        start = (seq - 1) * 1.0          # 2.0 s wide, 1.0 s stride
        last = spoof.analyze(AudioWindow(
            session_id=session_id, seq=seq, start_sec=start,
            end_sec=start + 2.0, pcm=pcm_fn(2.0), sample_rate=SAMPLE_RATE))
        if last.status is AnalyzerStatus.AVAILABLE:
            return last
    return last


@requires_spoof
def test_antispoof_produces_a_bounded_score(spoof):
    """A score appears only once enough REAL audio has accumulated.

    One 2 s window is not enough: the model needs 64,600 samples and the
    adapter no longer manufactures the difference.
    """
    spoof.release("bounded")
    r = fill(spoof, "bounded")
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.score is not None and 0.0 <= r.score <= 1.0


@requires_spoof
def test_antispoof_is_deterministic(spoof):
    """Same audio, same score: a demo must be reproducible.

    Both sessions are filled identically, so a real score is compared rather
    than two INSUFFICIENT_AUDIO results trivially matching as None.
    """
    spoof.release("det-a")
    spoof.release("det-b")
    a = fill(spoof, "det-a")
    b = fill(spoof, "det-b")
    assert a.score is not None and b.score is not None
    assert a.score == b.score


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


# --------------------------------------------------------------------------
# AASIST windowing - regression guard for the padding defect
# --------------------------------------------------------------------------

def test_aasist_never_pads_a_short_window():
    """The adapter must not invent audio to reach the model's input length.

    Regression guard. The adapter used to tile a 2 s window up to 64,600
    samples, so HALF of every input was filler it had created. A controlled
    experiment showed the resulting score was decided by the padding strategy
    rather than the speech: holding audio fixed and varying only the padding
    moved the score by a median of 0.43 and up to 0.89, with one clip going
    from 0.0317 to 0.8056.
    """
    src = io.open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "app", "adapters", "real", "audio_models.py"),
        encoding="utf-8").read()
    analyze = src.split("class AasistAntiSpoofAdapter")[1]
    assert "np.tile" not in analyze, "tiling re-introduced"
    assert "_accumulate" in analyze, "rolling real-audio buffer missing"


@requires_spoof
def test_first_short_window_is_insufficient_not_scored(spoof):
    """One 2 s window is not enough real audio; say so rather than padding."""
    spoof.release("buf-1")
    w = AudioWindow(session_id="buf-1", seq=1, start_sec=0.0, end_sec=2.0,
                    pcm=tone(2.0), sample_rate=SAMPLE_RATE)
    r = spoof.analyze(w)
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO
    assert r.score is None


@requires_spoof
def test_score_appears_once_enough_real_audio_accumulates(spoof):
    """Successive overlapping windows must fill the buffer with real audio."""
    spoof.release("buf-2")
    scored = None
    for seq in range(1, 8):
        start = (seq - 1) * 1.0          # 2.0 s wide, 1.0 s stride
        r = spoof.analyze(AudioWindow(
            session_id="buf-2", seq=seq, start_sec=start, end_sec=start + 2.0,
            pcm=tone(2.0), sample_rate=SAMPLE_RATE))
        if r.status is AnalyzerStatus.AVAILABLE:
            scored = r
            break
    assert scored is not None, "a score must appear once 64,600 samples exist"
    assert scored.score is not None and 0.0 <= scored.score <= 1.0


@requires_spoof
def test_sessions_do_not_share_a_buffer(spoof):
    """One caller's audio must never contribute to another caller's score."""
    for sid in ("iso-a", "iso-b"):
        spoof.release(sid)
    for seq in range(1, 6):
        start = (seq - 1) * 1.0
        spoof.analyze(AudioWindow(session_id="iso-a", seq=seq, start_sec=start,
                                  end_sec=start + 2.0, pcm=tone(2.0),
                                  sample_rate=SAMPLE_RATE))
    # A fresh session starts empty despite the other session being full.
    r = spoof.analyze(AudioWindow(session_id="iso-b", seq=1, start_sec=0.0,
                                  end_sec=2.0, pcm=tone(2.0),
                                  sample_rate=SAMPLE_RATE))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO


@requires_spoof
def test_release_frees_the_buffer(spoof):
    for seq in range(1, 8):
        start = (seq - 1) * 1.0
        spoof.analyze(AudioWindow(session_id="rel-1", seq=seq, start_sec=start,
                                  end_sec=start + 2.0, pcm=tone(2.0),
                                  sample_rate=SAMPLE_RATE))
    spoof.release("rel-1")
    r = spoof.analyze(AudioWindow(session_id="rel-1", seq=1, start_sec=0.0,
                                  end_sec=2.0, pcm=tone(2.0),
                                  sample_rate=SAMPLE_RATE))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO


def test_buffer_count_is_bounded():
    from app.adapters.real.audio_models import AASIST_MAX_SESSIONS
    assert 0 < AASIST_MAX_SESSIONS <= 1024
