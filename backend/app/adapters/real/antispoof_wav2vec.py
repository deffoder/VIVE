"""Anti-spoofing over a self-supervised speech backbone.

Why this exists
---------------
Phase J proved VIVE's AASIST integration correct - EER 0.0133 on ASVspoof 2019
LA eval against a published 0.0083, three readouts agreeing, the live adapter
separating the classes perfectly - and then proved the model does not transfer.
On VIVE's own synthesis probe it scores at chance (EER 0.4333, interval
containing 0.50), and on genuine human speech captured by the handset it
returned 0.9998 "spoof" (`BLOCKERS.md` O12).

That left two honest options: replace the model or drop the channel. Phase J2
measured four openly-licensed candidates on the same two corpora with the same
EER implementation:

    model                                   in-domain    VIVE probe
    AASIST (incumbent)                         0.0133        0.4333
    mo-thecreator/Deepfake-audio-detection     0.0000        0.1000
    Hemgg/Deepfake-audio-detection             0.1333        0.3167
    MelodyMachine/Deepfake-audio-detection-V2  0.2083        0.4167

The adoption rule was written before any candidate ran: beat AASIST
*off-domain* decisively, and pass in-domain as a control. One candidate did.

What this is NOT
----------------
A better off-domain number on one synthesis family is not a detection
capability. This probe is SpeechT5 + HiFiGAN in one language; it says nothing
about generators outside it (`BLOCKERS.md` P2), and it is not an
ASVspoof-comparable claim. Synthetic speech is still not fraud and human speech
is still not safety (P3). The fused score keeps its `SYNTHETIC_ONLY_CEILING`
bound, and the UI keeps describing this signal as inconclusive until it has
been measured on handset-captured audio.

One practical gain besides accuracy
-----------------------------------
wav2vec2 consumes variable-length audio natively, so a 2.0 s analysis window is
scored directly. AASIST needs 64,600 samples and VIVE refuses to pad, so it
stays silent until ~4.04 s of real audio has accumulated - which Phase J
measured as leaving 90%+ of short utterances unscored. This produces evidence
from the first speech-bearing window instead of the fourth.
"""

from __future__ import annotations

import logging
import os
import time

from app.adapters.interfaces import AdapterInfo, AntiSpoofResult, AudioWindow
from app.schemas.models import AdapterMode, AnalyzerStatus

logger = logging.getLogger("vive.adapters.antispoof")

SAMPLE_RATE = 16_000

MIN_SAMPLES = 8_000
"""Half a second. Below this there is too little speech to judge."""

MAX_SAMPLES = 64_000
"""Four seconds, matching the length Phase J2 measured at.

Longer inputs cost more for no measured gain, and a length the model was never
evaluated at is a silent change to what its score means.
"""

REQUIRED_FILES = ("config.json", "preprocessor_config.json")

SPOOF_LABELS = frozenset({
    "spoof", "fake", "deepfake", "synthetic", "generated", "ai", "aivoice",
    "aigenerated", "spoofed",
})
"""Label names that denote the synthetic class.

The spoof index is read from the checkpoint's own `id2label`, never assumed.
These checkpoints genuinely disagree - `fake`/`real`, `AIVoice`/`HumanVoice`,
`spoof`/`bonafide` - and picking index 0 by convention would produce a
perfectly inverted score with no error anywhere to notice it.
"""


class Wav2VecAntiSpoofAdapter:
    """Audio-classification anti-spoofing, label order read from the model."""

    adapter_key = "antispoof"
    mode = AdapterMode.REAL
    id = "wav2vec2-antispoof"
    architecture = "wav2vec2 audio classification"

    def __init__(self, model_dir: str) -> None:
        self._dir = model_dir
        self._name = os.path.basename(os.path.normpath(model_dir)) if model_dir else ""
        self._model = None
        self._extractor = None
        self._spoof_index: int | None = None
        self._labels: dict[int, str] = {}
        self._status = AnalyzerStatus.UNAVAILABLE
        self._detail: str | None = "not configured"
        self._load_ms: int | None = None
        self.version = "wav2vec2-antispoof-unloaded"

    # --- lifecycle ----------------------------------------------------
    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()
        if not self._dir:
            # LOAD_ERROR, not UNAVAILABLE. Anti-spoofing is a core adapter
            # selected in real mode, so an unset path is a misconfiguration
            # and must be loud on every component - not a quiet opt-out the
            # way an unset English ASR legitimately is.
            return self._fail("antispoof_model_dir is not set", began)
        missing = [f for f in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(self._dir, f))]
        if missing:
            return self._fail(f"missing {', '.join(missing)} under {self._dir}",
                              began)
        try:
            from transformers import (
                AutoFeatureExtractor,
                AutoModelForAudioClassification,
            )
        except ImportError as exc:
            return self._fail(f"ML runtime not installed ({exc.name})", began)
        try:
            self._extractor = AutoFeatureExtractor.from_pretrained(self._dir)
            model = AutoModelForAudioClassification.from_pretrained(self._dir)
            model.eval()
            self._labels = {int(k): str(v) for k, v in
                            (getattr(model.config, "id2label", {}) or {}).items()}
            self._spoof_index = _spoof_index(self._labels)
            if self._spoof_index is None:
                # Refuse rather than guess. A wrong index yields a plausible
                # score that is exactly backwards, which is worse than no
                # score at all because nothing downstream can detect it.
                return self._fail(
                    f"no recognisable spoof class in id2label={self._labels}",
                    began)
            self._model = model
            self.version = f"{self._name}-v1"
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"{type(exc).__name__}: {str(exc)[:160]}", began)
        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    def _fail(self, detail: str, began: float) -> AnalyzerStatus:
        self._status = AnalyzerStatus.LOAD_ERROR
        self._detail = detail
        self._load_ms = int((time.perf_counter() - began) * 1000)
        logger.warning("antispoof adapter load failed: %s", detail)
        return self._status

    def available(self) -> bool:
        return self._status is AnalyzerStatus.AVAILABLE

    def release(self, session_id: str) -> None:
        """No per-session state: each window is scored on its own audio."""

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=self._status,
            architecture=self.architecture,
            revision=self._name or None,
            execution_provider="torch cpu",
            sample_rate=SAMPLE_RATE,
            load_ms=self._load_ms,
            detail=self._detail if self._detail else
            f"spoof class = {self._labels.get(self._spoof_index or 0)!r}",
        )

    # --- inference ----------------------------------------------------
    def analyze(self, window: AudioWindow) -> AntiSpoofResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            return self._empty(self._status)
        if window.sample_rate != SAMPLE_RATE:
            return self._empty(AnalyzerStatus.INFERENCE_ERROR)
        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            pcm = window.pcm or b""
            if len(pcm) < MIN_SAMPLES * 2:   # 2 bytes per pcm_s16le sample
                return self._empty(AnalyzerStatus.INSUFFICIENT_AUDIO)
            samples = (np.frombuffer(pcm, dtype="<i2").astype(np.float32)
                       / 32768.0).copy()[:MAX_SAMPLES]

            inputs = self._extractor(samples, sampling_rate=SAMPLE_RATE,
                                     return_tensors="pt")
            with torch.no_grad():
                logits = self._model(**inputs).logits[0]
                probs = torch.softmax(logits, dim=-1)
            score = round(float(probs[self._spoof_index]), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("antispoof inference failed: %s", type(exc).__name__)
            return self._empty(AnalyzerStatus.INFERENCE_ERROR)
        return AntiSpoofResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, score=score,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )

    def _empty(self, status: AnalyzerStatus) -> AntiSpoofResult:
        return AntiSpoofResult(status=status, model_version=self.version,
                               mode=self.mode, score=None)


def _spoof_index(labels: dict[int, str]) -> int | None:
    for index, name in labels.items():
        cleaned = str(name).strip().lower().replace("_", "").replace(" ", "")
        if cleaned in SPOOF_LABELS:
            return int(index)
    return None
