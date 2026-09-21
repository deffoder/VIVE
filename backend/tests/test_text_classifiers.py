"""Phase 8B: real intent and behaviour adapters.

Like the ASR tests, the contract and failure paths run without any checkpoint
present. Real-inference tests are skipped unless VIVE_INTENT_MODEL_DIR and
VIVE_BEHAVIOR_MODEL_DIR point at usable directories.

The label-safety tests matter most. A head whose label order silently diverged
from the taxonomy would emit confident predictions for the WRONG labels, which
is far worse than failing to load, so the adapter must refuse.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from app.adapters.real.text_classifiers import (
    BEHAVIOR_THRESHOLD,
    MAX_LENGTH,
    SUPPORTED_LANGUAGES,
    RealBehaviorAdapter,
    RealIntentAdapter,
)
from app.schemas.models import AdapterMode, AnalyzerStatus, Behavior, Intent

INTENT_DIR = os.environ.get("VIVE_INTENT_MODEL_DIR", "")
BEHAVIOR_DIR = os.environ.get("VIVE_BEHAVIOR_MODEL_DIR", "")


def _usable(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "model.safetensors"))


requires_intent = pytest.mark.skipif(
    not _usable(INTENT_DIR), reason="set VIVE_INTENT_MODEL_DIR")
requires_behavior = pytest.mark.skipif(
    not _usable(BEHAVIOR_DIR), reason="set VIVE_BEHAVIOR_MODEL_DIR")


# --------------------------------------------------------------------------
# failure states
# --------------------------------------------------------------------------

def test_missing_checkpoint_is_load_error():
    a = RealIntentAdapter("no/such/dir")
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert a.available() is False


def test_failed_load_stays_real_and_returns_unknown_not_a_guess():
    a = RealIntentAdapter("no/such/dir")
    a.load()
    r = a.analyze("please send the otp", "en")
    assert r.mode is AdapterMode.REAL
    assert r.status is AnalyzerStatus.LOAD_ERROR
    assert r.label is Intent.UNKNOWN
    assert r.confidence is None


def test_behaviour_failed_load_returns_no_labels():
    a = RealBehaviorAdapter("no/such/dir")
    a.load()
    r = a.analyze("act now or your account closes", "en")
    assert r.status is AnalyzerStatus.LOAD_ERROR
    assert r.labels == []
    assert r.confidence is None


# --------------------------------------------------------------------------
# label safety - the most important property here
# --------------------------------------------------------------------------

def _stub_checkpoint(tmp_path, id2label: dict) -> str:
    """A checkpoint-shaped directory. Only the config needs to be real:
    validation must reject before any weights are touched."""
    d = tmp_path / "ckpt"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"id2label": id2label}), encoding="utf-8")
    (d / "model.safetensors").write_bytes(b"not-a-real-checkpoint")
    (d / "tokenizer.json").write_text("{}", encoding="utf-8")
    return str(d)


def test_reordered_labels_are_refused(tmp_path):
    labels = [i.value for i in Intent]
    labels[0], labels[1] = labels[1], labels[0]      # swap two
    a = RealIntentAdapter(_stub_checkpoint(tmp_path, dict(enumerate(labels))))
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert "mismatch" in (a.describe().detail or "").lower()


def test_wrong_label_count_is_refused(tmp_path):
    labels = [i.value for i in Intent][:5]
    a = RealIntentAdapter(_stub_checkpoint(tmp_path, dict(enumerate(labels))))
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    detail = (a.describe().detail or "").lower()
    assert "5 labels" in detail or "taxonomy has" in detail


def test_checkpoint_without_id2label_is_refused(tmp_path):
    d = tmp_path / "ckpt"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"num_labels": 12}), encoding="utf-8")
    (d / "model.safetensors").write_bytes(b"x")
    (d / "tokenizer.json").write_text("{}", encoding="utf-8")
    a = RealIntentAdapter(str(d))
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert "id2label" in (a.describe().detail or "")


def test_unknown_label_name_is_refused_not_remapped(tmp_path):
    """An unrecognised label must never be coerced onto a nearby VIVE label."""
    labels = [i.value for i in Intent]
    labels[3] = "SOME_OTHER_TAXONOMY_LABEL"
    a = RealIntentAdapter(_stub_checkpoint(tmp_path, dict(enumerate(labels))))
    assert a.load() is AnalyzerStatus.LOAD_ERROR
    assert "SOME_OTHER_TAXONOMY_LABEL" in (a.describe().detail or "")


def test_behaviour_label_order_is_validated_too(tmp_path):
    labels = [b.value for b in Behavior][::-1]
    a = RealBehaviorAdapter(_stub_checkpoint(tmp_path, dict(enumerate(labels))))
    assert a.load() is AnalyzerStatus.LOAD_ERROR


# --------------------------------------------------------------------------
# language policy
# --------------------------------------------------------------------------

def test_tamil_is_not_in_the_supported_set():
    """O11: the training corpus held zero Tamil records."""
    assert "ta" not in SUPPORTED_LANGUAGES
    assert {"en", "hi"} <= SUPPORTED_LANGUAGES


def test_training_constants_match_phase_7():
    assert MAX_LENGTH == 96
    assert BEHAVIOR_THRESHOLD == 0.5


# --------------------------------------------------------------------------
# real inference
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def intent_model():
    a = RealIntentAdapter(INTENT_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(f"intent model did not load: {a.describe().detail}")
    return a


@pytest.fixture(scope="module")
def behavior_model():
    a = RealBehaviorAdapter(BEHAVIOR_DIR)
    if a.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip(f"behaviour model did not load: {a.describe().detail}")
    return a


@requires_intent
def test_real_checkpoint_label_order_matches_taxonomy(intent_model):
    """The shipped checkpoint must pass the same validation as a stub."""
    assert intent_model.available()
    assert intent_model.describe().status is AnalyzerStatus.AVAILABLE


@requires_intent
def test_tamil_transcript_is_declined_not_predicted(intent_model):
    r = intent_model.analyze("OTP sollunga now", "ta")
    assert r.status is AnalyzerStatus.UNSUPPORTED_LANGUAGE
    assert r.label is Intent.UNKNOWN
    assert r.confidence is None, "no confidence may be reported for a model that did not run"


@requires_behavior
def test_tamil_behaviour_is_declined(behavior_model):
    r = behavior_model.analyze("OTP sollunga now", "ta")
    assert r.status is AnalyzerStatus.UNSUPPORTED_LANGUAGE
    assert r.labels == []


@requires_intent
def test_english_otp_request_is_recognised(intent_model):
    r = intent_model.analyze("Please share the OTP you received immediately", "en")
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.label is Intent.OTP_REQUEST
    assert r.confidence is not None and 0.0 <= r.confidence <= 1.0


@requires_intent
def test_benign_text_is_normal_conversation(intent_model):
    r = intent_model.analyze("Hi, are we still on for lunch tomorrow?", "en")
    assert r.status is AnalyzerStatus.AVAILABLE
    assert r.label is Intent.NORMAL_CONVERSATION


@requires_intent
def test_empty_transcript_is_insufficient_not_normal(intent_model):
    """Silence must not be classified as a benign conversation."""
    for text in ("", "   ", None):
        r = intent_model.analyze(text, "en")
        assert r.status is AnalyzerStatus.INSUFFICIENT_AUDIO
        assert r.confidence is None


@requires_intent
def test_predicted_label_is_always_in_the_taxonomy(intent_model):
    for text in ("send money now", "your account is blocked",
                 "install anydesk so I can help", "hello how are you"):
        r = intent_model.analyze(text, "en")
        assert isinstance(r.label, Intent)


@requires_behavior
def test_behaviour_returns_taxonomy_members_only(behavior_model):
    r = behavior_model.analyze("Act immediately or your account will be closed", "en")
    assert r.status is AnalyzerStatus.AVAILABLE
    for label in r.labels:
        assert isinstance(label, Behavior)


@requires_behavior
def test_behaviour_untrained_labels_never_fire(behavior_model):
    """THREAT and SECRECY have no training data (O9) and cannot be emitted."""
    texts = ["do not tell anyone about this, keep it secret",
             "I will have you arrested if you hang up"]
    fired: set[str] = set()
    for t in texts:
        fired |= {b.value for b in behavior_model.analyze(t, "en").labels}
    assert "THREAT" not in fired
    assert "SECRECY" not in fired


@requires_intent
def test_long_transcript_is_truncated_not_rejected(intent_model):
    r = intent_model.analyze("please send the otp " * 200, "en")
    assert r.status is AnalyzerStatus.AVAILABLE


@requires_intent
def test_unspecified_language_is_still_analysed(intent_model):
    """A None language means 'unknown', not 'unsupported'."""
    r = intent_model.analyze("Please share the OTP", None)
    assert r.status is AnalyzerStatus.AVAILABLE
