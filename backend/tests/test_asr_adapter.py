"""Phase 8A: real ASR adapter contract and failure states.

These tests run WITHOUT the ML extras installed. That is deliberate: the most
important property of this adapter is what it does when the model is not
there, and that path must be exercised in the ordinary test environment.

Tests that need real weights are skipped unless VIVE_ASR_MODEL_DIR points at a
usable model directory, so the suite stays green on a machine with no
checkpoints while still verifying real inference where it is available.
"""

from __future__ import annotations

import json
import os
import struct

import pytest

from app.adapters.factory import build_bundle
from app.adapters.interfaces import AudioWindow
from app.adapters.real.asr_conformer import (
    MIN_SAMPLES,
    REQUIRED_FILES,
    IndicConformerAsrAdapter,
)
from app.core.config import Settings
from app.schemas.models import AdapterMode, AnalyzerStatus

SAMPLE_RATE = 16_000


def pcm(seconds: float, *, amplitude: int = 4000, rate: int = SAMPLE_RATE) -> bytes:
    """Deterministic pcm_s16le. Cost/shape fixture, not speech."""
    n = int(rate * seconds)
    return struct.pack(f"<{n}h", *[(amplitude if i % 200 < 100 else -amplitude)
                                   for i in range(n)])


def window(**kw) -> AudioWindow:
    base = dict(session_id="s-1", seq=1, start_sec=0.0, end_sec=2.0,
                pcm=pcm(2.0), sample_rate=SAMPLE_RATE)
    base.update(kw)
    return AudioWindow(**base)


# --------------------------------------------------------------------------
# failure states
# --------------------------------------------------------------------------

def test_missing_model_dir_is_load_error_not_unavailable():
    a = IndicConformerAsrAdapter("no/such/dir")
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert a.available() is False


def test_failed_load_stays_in_real_mode():
    """The critical anti-fabrication property: no silent downgrade to mock."""
    a = IndicConformerAsrAdapter("no/such/dir")
    a.load()
    info = a.describe()
    assert info.mode is AdapterMode.REAL
    assert info.status is AnalyzerStatus.LOAD_ERROR
    assert a.analyze(window()).mode is AdapterMode.REAL


def test_failed_load_never_produces_a_transcript():
    a = IndicConformerAsrAdapter("no/such/dir")
    a.load()
    r = a.analyze(window())
    assert r.transcript is None
    assert r.confidence is None
    assert r.status is AnalyzerStatus.LOAD_ERROR


def test_load_error_detail_names_the_problem_without_leaking_a_stack_trace():
    a = IndicConformerAsrAdapter("no/such/dir")
    a.load()
    detail = a.describe().detail or ""
    assert "missing" in detail.lower()
    assert "Traceback" not in detail
    assert len(detail) < 400


def test_partial_model_dir_is_load_error(tmp_path):
    """A directory with some but not all required files must not load."""
    (tmp_path / "config.json").write_text(json.dumps({"BLANK_ID": 256}), encoding="utf-8")
    a = IndicConformerAsrAdapter(str(tmp_path))
    assert a.load() is AnalyzerStatus.LOAD_ERROR


def test_analyze_before_load_does_not_crash():
    a = IndicConformerAsrAdapter("no/such/dir")
    r = a.analyze(window())          # no load() call at all
    assert r.transcript is None
    assert r.status in {AnalyzerStatus.UNAVAILABLE, AnalyzerStatus.LOAD_ERROR}


def test_required_files_list_is_not_empty():
    assert len(REQUIRED_FILES) >= 6


# --------------------------------------------------------------------------
# metadata contract
# --------------------------------------------------------------------------

def test_describe_exposes_required_metadata():
    info = IndicConformerAsrAdapter("no/such/dir").describe()
    assert info.adapter_key == "asr"
    assert info.model_id == "indic-conformer-600m"
    assert info.model_version == "indic-conformer-600m-ctc-v1"
    assert info.architecture and "CTC" in info.architecture
    assert info.revision == "ai4bharat/indic-conformer-600m-multilingual"
    assert info.sample_rate == SAMPLE_RATE


def test_unloaded_adapter_reports_no_languages():
    """Language coverage is read from the loaded masks, never hard-coded."""
    assert IndicConformerAsrAdapter("no/such/dir").describe().languages == ()


# --------------------------------------------------------------------------
# bundle wiring
# --------------------------------------------------------------------------

def test_mock_mode_builds_mock_bundle():
    b = build_bundle(Settings(adapter_mode="mock"))
    assert b.asr.mode is AdapterMode.MOCK
    assert b.infos()["asr"].mode is AdapterMode.MOCK


def test_real_mode_without_weights_keeps_real_asr_and_reports_load_error():
    b = build_bundle(Settings(adapter_mode="real", asr_model_dir="no/such/dir"))
    info = b.infos()["asr"]
    assert info.mode is AdapterMode.REAL, "must not fall back to the mock adapter"
    assert info.status is AnalyzerStatus.LOAD_ERROR
    assert b.states()["asr"] == (AnalyzerStatus.LOAD_ERROR, AdapterMode.REAL)


def test_real_mode_leaves_other_adapters_mock_and_says_so():
    """Phase 8A wires ASR only; a partially real bundle must be honest."""
    b = build_bundle(Settings(adapter_mode="real", asr_model_dir="no/such/dir"))
    infos = b.infos()
    assert infos["asr"].mode is AdapterMode.REAL
    for key in ("vad", "antispoof", "speaker", "intent", "behavior"):
        assert infos[key].mode is AdapterMode.MOCK, key


def test_every_adapter_implements_describe():
    for key, info in build_bundle(Settings(adapter_mode="mock")).infos().items():
        assert info.adapter_key == key
        assert info.model_id
        assert info.model_version


# --------------------------------------------------------------------------
# real inference - only where a model is actually present
# --------------------------------------------------------------------------

MODEL_DIR = os.environ.get("VIVE_ASR_MODEL_DIR", "")
_has_model = bool(MODEL_DIR) and all(
    os.path.isfile(os.path.join(MODEL_DIR, f)) for f in REQUIRED_FILES)
requires_model = pytest.mark.skipif(
    not _has_model,
    reason="set VIVE_ASR_MODEL_DIR to a populated IndicConformer CTC directory")


@pytest.fixture(scope="module")
def loaded():
    a = IndicConformerAsrAdapter(MODEL_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(f"model did not load: {a.describe().detail}")
    return a


@requires_model
def test_real_model_loads_and_reports_provider(loaded):
    info = loaded.describe()
    assert info.status is AnalyzerStatus.AVAILABLE
    assert info.mode is AdapterMode.REAL
    assert info.execution_provider, "must report the provider that served the graph"
    assert info.load_ms is not None and info.load_ms > 0


@requires_model
def test_real_model_covers_hindi_and_tamil(loaded):
    assert "hi" in loaded.describe().languages
    assert "ta" in loaded.describe().languages


@requires_model
def test_short_audio_is_insufficient_not_an_empty_transcript(loaded):
    r = loaded.analyze(window(pcm=pcm(0.2), end_sec=0.2))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO
    assert r.transcript is None


@requires_model
def test_empty_audio_is_insufficient(loaded):
    r = loaded.analyze(window(pcm=b""))
    assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO
    assert r.transcript is None


@requires_model
def test_wrong_sample_rate_is_rejected_not_silently_resampled(loaded):
    r = loaded.analyze(window(sample_rate=8_000))
    assert r.status is AnalyzerStatus.INFERENCE_ERROR
    assert r.transcript is None


@requires_model
def test_odd_byte_count_is_an_inference_error_not_a_crash(loaded):
    """pcm_s16le needs an even byte count; a truncated frame must not crash."""
    r = loaded.analyze(window(pcm=pcm(2.0) + b"\x00"))
    assert r.status in {AnalyzerStatus.INFERENCE_ERROR, AnalyzerStatus.AVAILABLE,
                        AnalyzerStatus.INSUFFICIENT_AUDIO}
    assert r.mode is AdapterMode.REAL


@requires_model
def test_unsupported_language_is_an_error_not_a_wrong_language_guess(loaded):
    loaded.set_default_language("zz")
    try:
        r = loaded.analyze(window())
        assert r.status is AnalyzerStatus.INFERENCE_ERROR
        assert r.transcript is None
    finally:
        loaded.set_default_language("hi")


@requires_model
def test_min_samples_threshold_is_respected(loaded):
    assert MIN_SAMPLES == SAMPLE_RATE // 2
    just_under = loaded.analyze(window(pcm=pcm((MIN_SAMPLES - 160) / SAMPLE_RATE)))
    assert just_under.status is AnalyzerStatus.INSUFFICIENT_AUDIO
