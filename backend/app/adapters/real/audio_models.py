"""Real audio adapters: Silero VAD, AASIST anti-spoofing, ECAPA-TDNN speaker.

Phase 8C. All three sit behind the existing protocols and follow the same
failure policy as the ASR and text adapters: a model that cannot load reports
`LOAD_ERROR` and stays in REAL mode, and no adapter ever substitutes a
plausible-looking value for a result it did not compute.

What each one is, and is not
----------------------------
**Silero VAD** decides speech vs silence per window and drives audio quality.
It does not decide risk. `NO_SPEECH` and `POOR` suppress downstream analyzers
and lower confidence; they never raise risk (docs/PROJECT_SPEC.md 2).

**AASIST** produces a synthetic-speech score. That is evidence of synthesis,
**not a probability of fraud**: synthetic speech is not fraud and human speech
is not safety (docs/BLOCKERS.md P3). The pretrained checkpoint runs here, but
VIVE has measured **no EER of its own** - no anti-spoofing corpus was acquired
(docs/BLOCKERS.md O5) - so no detection-accuracy claim may be made from it.

**ECAPA-TDNN** produces a speaker embedding. Speaker *consistency* needs an
enrolled reference, and there is no enrolment source (docs/BLOCKERS.md O3).
Without one the adapter reports `NO_REFERENCE` and never invents an identity
or a similarity score. `NO_REFERENCE` is not a mismatch.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Any

from app.adapters.interfaces import (
    AdapterInfo,
    AntiSpoofResult,
    AudioWindow,
    SpeakerResult,
    VadResult,
)
from app.schemas.models import AdapterMode, AnalyzerStatus, AudioQuality

logger = logging.getLogger("vive.adapters.audio")

SAMPLE_RATE = 16_000

# Silero v5 consumes fixed 512-sample frames at 16 kHz.
SILERO_FRAME = 512
SPEECH_THRESHOLD = 0.5
"""Per-frame speech probability above which a frame counts as speech. The
upstream default; changing it changes what counts as silence."""

MIN_SPEECH_RATIO = 0.10
"""Share of frames that must contain speech before a window is treated as
speech-bearing. Guards against a single spurious frame marking silence as
speech."""

# AASIST expects a fixed-length waveform: 64,600 samples (~4.04 s at 16 kHz).
#
# VIVE's analysis window is 2.0 s (32,000 samples), barely half of that. The
# adapter originally padded each window up to length - tiling it - so HALF of
# every input was filler the adapter invented.
#
# A controlled experiment (scripts/experiment_aasist_tiling.py,
# models/evaluation/aasist_tiling_experiment.json) measured what that costs.
# Holding the audio fixed and varying only the padding strategy moved the
# spoof score by a median of 0.43 and up to 0.89 on a 0-1 scale; one clip went
# from 0.0317 to 0.8056. The score was being decided by the padding, not by
# the speech.
#
# Tiling was not uniquely bad - it scored LOWER than reflect- and edge-padding
# and highest on only 3 of 12 clips - so the fix is not a better padding
# choice. There isn't one. The fix is to stop padding: the adapter keeps a
# rolling buffer of recent REAL audio per session and runs the model only once
# it holds a full genuine window.
AASIST_SAMPLES = 64_600

AASIST_MAX_SESSIONS = 64
"""Cap on buffered sessions, so a long-running process cannot grow unbounded.
The oldest buffer is evicted first; an evicted session simply refills."""

AASIST_CONFIG = {
    "architecture": "AASIST",
    "nb_samp": AASIST_SAMPLES,
    "first_conv": 128,
    "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]],
    "gat_dims": [64, 32],
    "pool_ratios": [0.5, 0.7, 0.5, 0.5],
    "temperatures": [2.0, 2.0, 100.0, 100.0],
}


def _pcm_to_float(pcm: bytes):
    import numpy as np
    return (np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0).copy()


class _RealAudioAdapter:
    """Shared lifecycle and metadata."""

    mode = AdapterMode.REAL
    adapter_key = "?"
    id = "?"
    version = "?"
    architecture: str | None = None
    revision: str | None = None

    def __init__(self, path: str) -> None:
        self._path = path
        self._model: Any = None
        self._status = AnalyzerStatus.UNAVAILABLE
        self._detail: str | None = "not loaded yet"
        self._load_ms: int | None = None

    def _fail(self, detail: str, began: float) -> AnalyzerStatus:
        self._status = AnalyzerStatus.LOAD_ERROR
        self._detail = detail
        self._load_ms = int((time.perf_counter() - began) * 1000)
        logger.warning("%s adapter load failed: %s", self.adapter_key, detail)
        return self._status

    def available(self) -> bool:
        return self._status is AnalyzerStatus.AVAILABLE

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=self._status,
            architecture=self.architecture,
            revision=self.revision,
            execution_provider="torch cpu",
            sample_rate=SAMPLE_RATE,
            load_ms=self._load_ms,
            detail=self._detail,
        )


class SileroVadAdapter(_RealAudioAdapter):
    """Real Silero VAD (MIT), loaded from a local TorchScript file."""

    adapter_key = "vad"
    id = "silero-vad"
    version = "silero-vad-v5-jit"
    architecture = "Silero VAD v5 (TorchScript)"
    revision = "snakers4/silero-vad"

    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()
        jit_path = os.path.join(self._path, "silero_vad.jit")
        if not os.path.isfile(jit_path):
            return self._fail(f"missing silero_vad.jit under {self._path}", began)
        try:
            import torch
        except ImportError as exc:
            return self._fail(f"ML runtime not installed ({exc.name})", began)
        try:
            model = torch.jit.load(jit_path, map_location="cpu")
            model.eval()
            self._model = model
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"{type(exc).__name__}: {str(exc)[:160]}", began)
        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    def analyze(self, window: AudioWindow) -> VadResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            return VadResult(status=self._status, model_version=self.version,
                             mode=self.mode, has_speech=False,
                             quality=AudioQuality.NO_SPEECH)
        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            samples = _pcm_to_float(window.pcm or b"")
            if samples.size < SILERO_FRAME:
                return VadResult(status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                                 model_version=self.version, mode=self.mode,
                                 has_speech=False, quality=AudioQuality.NO_SPEECH)

            if hasattr(self._model, "reset_states"):
                self._model.reset_states()
            frames = samples.size // SILERO_FRAME
            probs = []
            with torch.no_grad():
                for i in range(frames):
                    chunk = samples[i * SILERO_FRAME:(i + 1) * SILERO_FRAME]
                    probs.append(float(self._model(torch.from_numpy(chunk), SAMPLE_RATE)))

            speech_ratio = sum(p >= SPEECH_THRESHOLD for p in probs) / max(len(probs), 1)
            has_speech = speech_ratio >= MIN_SPEECH_RATIO
            peak = float(np.abs(samples).max()) if samples.size else 0.0
            clipped = float((np.abs(samples) >= 0.999).mean()) if samples.size else 0.0
            quality = self._quality(has_speech, speech_ratio, peak, clipped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vad inference failed: %s", type(exc).__name__)
            return VadResult(status=AnalyzerStatus.INFERENCE_ERROR,
                             model_version=self.version, mode=self.mode,
                             has_speech=False, quality=AudioQuality.NO_SPEECH)
        return VadResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, has_speech=has_speech, quality=quality,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )

    @staticmethod
    def _quality(has_speech: bool, ratio: float, peak: float,
                 clipped: float) -> AudioQuality:
        """Measured signal properties only. Quality never encodes suspicion."""
        if not has_speech:
            return AudioQuality.NO_SPEECH
        if clipped > 0.01 or peak < 0.02:
            return AudioQuality.POOR
        if ratio < 0.35 or peak < 0.08:
            return AudioQuality.DEGRADED
        return AudioQuality.GOOD


class AasistAntiSpoofAdapter(_RealAudioAdapter):
    """Real AASIST anti-spoofing over the vendored model definition."""

    adapter_key = "antispoof"
    id = "aasist"
    version = "aasist-pretrained-v1"
    architecture = "AASIST graph-attention anti-spoofing"
    revision = "clovaai/aasist"

    def __init__(self, path: str) -> None:
        super().__init__(path)
        # session_id -> (float32 samples, last end_sec seen)
        self._buffers: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = Lock()

    def _accumulate(self, window: AudioWindow, samples) -> Any | None:
        """Appends this window's NEW audio and returns a full genuine window.

        Consecutive windows overlap (2.0 s wide, 1.0 s stride), so only the
        portion after the previous window's end is new. Returns None until
        64,600 samples of real audio have accumulated.
        """
        import numpy as np

        with self._lock:
            buffered, last_end = self._buffers.pop(
                window.session_id, (np.zeros(0, dtype=np.float32), None))

            if last_end is None or window.start_sec >= last_end:
                fresh = samples                      # first window, or a gap
            else:
                overlap = min(int(round((last_end - window.start_sec) * SAMPLE_RATE)),
                              samples.size)
                fresh = samples[overlap:] if overlap > 0 else samples

            buffered = np.concatenate([buffered, fresh])[-AASIST_SAMPLES:]
            self._buffers[window.session_id] = (buffered, window.end_sec)
            while len(self._buffers) > AASIST_MAX_SESSIONS:
                self._buffers.popitem(last=False)

            return buffered.copy() if buffered.size >= AASIST_SAMPLES else None

    def release(self, session_id: str) -> None:
        """Drops a finished session's buffer."""
        with self._lock:
            self._buffers.pop(session_id, None)

    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()
        ckpt = os.path.join(self._path, "AASIST.pth")
        if not os.path.isfile(ckpt):
            return self._fail(f"missing AASIST.pth under {self._path}", began)
        try:
            import torch

            from app.adapters.real.vendor.aasist_model import Model as AasistModel
        except ImportError as exc:
            return self._fail(f"ML runtime not installed ({exc.name})", began)
        try:
            model = AasistModel(dict(AASIST_CONFIG))
            state = torch.load(ckpt, map_location="cpu", weights_only=True)
            missing, unexpected = model.load_state_dict(state, strict=False)
            if missing or unexpected:
                # A partially-loaded anti-spoofing model would emit confident
                # nonsense, so refuse rather than run a half-initialised net.
                return self._fail(
                    f"checkpoint does not match the architecture: "
                    f"{len(missing)} missing, {len(unexpected)} unexpected keys",
                    began)
            model.eval()
            self._model = model
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"{type(exc).__name__}: {str(exc)[:160]}", began)
        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    def analyze(self, window: AudioWindow) -> AntiSpoofResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            return AntiSpoofResult(status=self._status, model_version=self.version,
                                   mode=self.mode, score=None)
        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            samples = _pcm_to_float(window.pcm or b"")
            if samples.size < SILERO_FRAME:
                return AntiSpoofResult(status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                                       model_version=self.version,
                                       mode=self.mode, score=None)

            # Never pad. Accumulate real audio until a full window exists.
            full = self._accumulate(window, samples)
            if full is None:
                # Honest "not yet" rather than a score decided by filler.
                return AntiSpoofResult(status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                                       model_version=self.version,
                                       mode=self.mode, score=None)
            samples = full

            with torch.no_grad():
                _emb, logits = self._model(torch.from_numpy(samples).unsqueeze(0))
                probs = torch.softmax(logits[0], dim=-1)
            # Index 0 is the spoof class in the official AASIST label order.
            score = round(float(probs[0]), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("antispoof inference failed: %s", type(exc).__name__)
            return AntiSpoofResult(status=AnalyzerStatus.INFERENCE_ERROR,
                                   model_version=self.version, mode=self.mode,
                                   score=None)
        return AntiSpoofResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, score=score,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )


class EcapaSpeakerAdapter(_RealAudioAdapter):
    """Real ECAPA-TDNN speaker embedding (SpeechBrain, Apache-2.0)."""

    adapter_key = "speaker"
    id = "ecapa-tdnn"
    version = "ecapa-tdnn-voxceleb-v1"
    architecture = "ECAPA-TDNN speaker embedding (192-dim)"
    revision = "speechbrain/spkrec-ecapa-voxceleb"

    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()
        if not os.path.isfile(os.path.join(self._path, "hyperparams.yaml")):
            return self._fail(f"missing hyperparams.yaml under {self._path}", began)
        try:
            import torch  # noqa: F401
            from speechbrain.inference import EncoderClassifier
        except ImportError as exc:
            return self._fail(
                f"ML runtime not installed ({exc.name}). "
                'Install with: pip install -e "backend[ml]"', began)
        try:
            self._model = EncoderClassifier.from_hparams(
                source=self._path, savedir=self._path, run_opts={"device": "cpu"})
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"{type(exc).__name__}: {str(exc)[:160]}", began)
        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    MIN_ENROLMENT_SECONDS = 3.0
    """Shortest audio accepted for enrolment.

    Phase 9 measured that a 2 s window moves the operating point sharply - the
    genuine-pair median similarity falls 0.813 -> 0.555 and the EER threshold
    0.554 -> 0.292 (docs/BLOCKERS.md O3). A reference built from a window that
    short would be a poor anchor for every later comparison, so enrolment asks
    for more audio than analysis does.
    """

    def _embed(self, samples):
        import torch
        with torch.no_grad():
            return self._model.encode_batch(
                torch.from_numpy(samples).unsqueeze(0)).squeeze()

    def enrol(self, pcm: bytes) -> list[float] | None:
        """Turns enrolment audio into a reference embedding.

        Returns the 192-dim embedding, or None when the audio is too short to
        anchor anything. The caller stores the EMBEDDING and discards the
        audio: a voiceprint is sensitive, and keeping the recording as well
        would be keeping a copy of someone's voice for no additional purpose
        (docs/SECURITY_SPEC.md 4).
        """
        if self._status is not AnalyzerStatus.AVAILABLE:
            return None
        samples = _pcm_to_float(pcm or b"")
        if samples.size < int(self.MIN_ENROLMENT_SECONDS * SAMPLE_RATE):
            return None
        try:
            return [float(v) for v in self._embed(samples).flatten()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("enrolment failed: %s", type(exc).__name__)
            return None

    def compare(self, window: AudioWindow,
                reference_embedding: list[float] | None) -> SpeakerResult:
        """Compares a window against a stored reference embedding.

        Preferred over passing raw reference audio on every packet: that
        re-embedded the same recording once per second and required the audio
        itself to be retained. With an embedding the reference costs one
        forward pass at enrolment and 192 floats thereafter.
        """
        if self._status is not AnalyzerStatus.AVAILABLE:
            return SpeakerResult(status=self._status, model_version=self.version,
                                 mode=self.mode, similarity=None)
        if not reference_embedding:
            # No enrolment is NOT a mismatch and must never read as one.
            return SpeakerResult(status=AnalyzerStatus.NO_REFERENCE,
                                 model_version=self.version, mode=self.mode,
                                 similarity=None)
        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            samples = _pcm_to_float(window.pcm or b"")
            if samples.size < SILERO_FRAME:
                return SpeakerResult(status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                                     model_version=self.version,
                                     mode=self.mode, similarity=None)
            embedding = self._embed(samples).flatten()
            reference = torch.from_numpy(
                np.asarray(reference_embedding, dtype="float32"))
            similarity = round(float(torch.nn.functional.cosine_similarity(
                embedding, reference, dim=0)), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("speaker comparison failed: %s", type(exc).__name__)
            return SpeakerResult(status=AnalyzerStatus.INFERENCE_ERROR,
                                 model_version=self.version, mode=self.mode,
                                 similarity=None)
        return SpeakerResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, similarity=similarity,
            inference_ms=int((time.perf_counter() - began) * 1000))

    def analyze(self, window: AudioWindow,
                reference: bytes | None = None) -> SpeakerResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            return SpeakerResult(status=self._status, model_version=self.version,
                                 mode=self.mode, similarity=None)
        began = time.perf_counter()
        try:
            import torch

            samples = _pcm_to_float(window.pcm or b"")
            if samples.size < SILERO_FRAME:
                return SpeakerResult(status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                                     model_version=self.version,
                                     mode=self.mode, similarity=None)
            embedding = self._embed(samples)

            if not reference:
                # The model ran and produced an embedding; there is simply no
                # enrolled voice to compare against (docs/BLOCKERS.md O3).
                # NO_REFERENCE is not a mismatch and must never be read as one.
                return SpeakerResult(
                    status=AnalyzerStatus.NO_REFERENCE,
                    model_version=self.version, mode=self.mode, similarity=None,
                    inference_ms=int((time.perf_counter() - began) * 1000))

            ref_samples = _pcm_to_float(reference)
            if ref_samples.size < SILERO_FRAME:
                return SpeakerResult(status=AnalyzerStatus.NO_REFERENCE,
                                     model_version=self.version,
                                     mode=self.mode, similarity=None)
            ref_embedding = self._embed(ref_samples)
            similarity = round(float(torch.nn.functional.cosine_similarity(
                embedding.flatten(), ref_embedding.flatten(), dim=0)), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("speaker inference failed: %s", type(exc).__name__)
            return SpeakerResult(status=AnalyzerStatus.INFERENCE_ERROR,
                                 model_version=self.version, mode=self.mode,
                                 similarity=None)
        return SpeakerResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, similarity=similarity,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )
