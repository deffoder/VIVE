"""Speaker enrolment (docs/BLOCKERS.md O3).

ECAPA cannot say anything without a reference, and until now VIVE had no way
to create one - the channel reported `NO_REFERENCE` on every packet of every
session, for the life of the product.

These tests pin the three properties that matter:

  * no enrolment reports NO_REFERENCE, never a mismatch;
  * the same speaker scores higher than a different speaker;
  * the stored reference is an EMBEDDING, never the audio it came from.

The real-model tests use LibriSpeech, which carries genuine `speaker_id`
labels, so "same speaker" and "different speaker" are ground truth rather than
an assumption.
"""

from __future__ import annotations

import base64
import io as _io
import os
import struct

import pytest
from fastapi.testclient import TestClient

from app.schemas.models import AnalyzerStatus

SPK_DIR = os.environ.get("VIVE_SPEAKER_MODEL_DIR", "")
requires_speaker = pytest.mark.skipif(
    not (SPK_DIR and os.path.isfile(os.path.join(SPK_DIR, "hyperparams.yaml"))),
    reason="set VIVE_SPEAKER_MODEL_DIR")

SAMPLE_RATE = 16_000


def tone(seconds: float, amp: int = 8000, period: int = 160) -> bytes:
    n = int(SAMPLE_RATE * seconds)
    return struct.pack(f"<{n}h",
                       *[(amp if i % period < period // 2 else -amp) for i in range(n)])


def enrol(client: TestClient, session_id: str, pcm: bytes, label: str | None = None):
    return client.post(
        f"/api/v1/sessions/{session_id}/enrolment",
        json={"audio_b64": base64.b64encode(pcm).decode(), "label": label},
    )


# ------------------------------------------------------------------ contract

def test_without_enrolment_the_speaker_channel_reports_no_reference(
    client: TestClient, session_id: str,
) -> None:
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "client.audio", "transcript": "hello there",
                      "speaker": "Caller"})
        for _ in range(6):
            if ws.receive_json()["type"] == "risk.update":
                break

    packet = client.get(f"/api/v1/sessions/{session_id}/packets").json()[-1]
    assert packet["ecapa"]["status"] == "NO_REFERENCE"
    assert packet["ecapa"]["similarity"] is None, (
        "no enrolled voice means no comparison; a similarity here would be "
        "manufactured evidence"
    )


def test_short_audio_is_refused_rather_than_enrolled_badly(
    client: TestClient, session_id: str,
) -> None:
    """A 1 s reference would anchor every later comparison badly (O3)."""
    response = enrol(client, session_id, tone(1.0))
    assert response.status_code == 200
    body = response.json()
    assert body["enrolled"] is False
    assert "3 seconds" in body["reason"]


def test_enrolment_round_trips_and_can_be_removed(
    client: TestClient, session_id: str,
) -> None:
    accepted = enrol(client, session_id, tone(4.0), label="Primary voice").json()
    assert accepted["enrolled"] is True
    assert accepted["label"] == "Primary voice"
    assert accepted["enrolled_at"]

    cleared = client.delete(f"/api/v1/sessions/{session_id}/enrolment").json()
    assert cleared["enrolled"] is False


def test_malformed_enrolment_audio_is_rejected(
    client: TestClient, session_id: str,
) -> None:
    response = client.post(
        f"/api/v1/sessions/{session_id}/enrolment",
        json={"audio_b64": "not base64!!", "label": None},
    )
    assert response.status_code == 400


def test_enrolment_stores_an_embedding_not_the_audio(
    client: TestClient, session_id: str,
) -> None:
    """The reference is a voiceprint, not a recording."""
    from app.api.deps import get_state

    marker = tone(4.0)
    enrol(client, session_id, marker)
    state = get_state.__wrapped__(client.app) if hasattr(get_state, "__wrapped__") \
        else client.app.state.vive
    record = state.store.get(session_id)

    assert record.reference_embedding, "no embedding was stored"
    assert record.reference_audio is None, (
        "the raw enrolment audio must not be retained"
    )


# -------------------------------------------------------------- real models

@requires_speaker
def test_same_speaker_scores_higher_than_a_different_speaker() -> None:
    """Ground truth from LibriSpeech speaker_id, not an assumption."""
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.audio_models import EcapaSpeakerAdapter

    adapter = EcapaSpeakerAdapter(SPK_DIR)
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip("speaker model unavailable")

    ds = load_dataset("openslr/librispeech_asr", "clean", split="test",
                      streaming=True).cast_column("audio", Audio(decode=False))
    by_speaker: dict[int, list] = {}
    for row in ds:
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(_io.BytesIO(raw), dtype="float32", always_2d=False)
        if rate != SAMPLE_RATE or wave.size < SAMPLE_RATE * 4:
            continue
        speaker = int(row["speaker_id"])
        by_speaker.setdefault(speaker, []).append(wave)
        if len(by_speaker) >= 2 and all(len(v) >= 2 for v in by_speaker.values()):
            break

    speakers = [s for s, clips in by_speaker.items() if len(clips) >= 2][:2]
    if len(speakers) < 2:
        pytest.skip("not enough LibriSpeech speakers streamed")

    def pcm(wave) -> bytes:
        return (np.clip(wave, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    reference = adapter.enrol(pcm(by_speaker[speakers[0]][0]))
    assert reference is not None and len(reference) == 192

    def similarity(wave) -> float:
        window = AudioWindow(session_id="e", seq=1, start_sec=0.0, end_sec=2.0,
                             pcm=pcm(wave), sample_rate=SAMPLE_RATE)
        result = adapter.compare(window, reference)
        assert result.status is AnalyzerStatus.AVAILABLE
        return result.similarity

    same = similarity(by_speaker[speakers[0]][1])
    different = similarity(by_speaker[speakers[1]][0])

    assert same > different, (
        f"the enrolled speaker ({same}) must score above an impostor "
        f"({different})"
    )


@requires_speaker
def test_comparison_without_a_reference_is_no_reference_not_zero() -> None:
    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.audio_models import EcapaSpeakerAdapter

    adapter = EcapaSpeakerAdapter(SPK_DIR)
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip("speaker model unavailable")

    window = AudioWindow(session_id="e", seq=1, start_sec=0.0, end_sec=2.0,
                         pcm=tone(2.0), sample_rate=SAMPLE_RATE)
    result = adapter.compare(window, None)

    assert result.status is AnalyzerStatus.NO_REFERENCE
    assert result.similarity is None


@requires_speaker
def test_enrolment_refuses_audio_shorter_than_the_floor() -> None:
    from app.adapters.real.audio_models import EcapaSpeakerAdapter

    adapter = EcapaSpeakerAdapter(SPK_DIR)
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        pytest.skip("speaker model unavailable")

    assert adapter.enrol(tone(1.0)) is None
    assert adapter.enrol(b"") is None
    assert adapter.enrol(tone(4.0)) is not None
