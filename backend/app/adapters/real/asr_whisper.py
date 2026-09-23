"""Whisper ASR, for the languages IndicConformer does not cover.

Why this exists
---------------
`BLOCKERS.md` O16: the selected ASR is IndicConformer, which is IN-22 and has
no English mask at all, while the intent and behaviour heads support English,
Hindi and Hinglish. End-to-end coverage is therefore Hindi only, and an English
call reaches `UNSUPPORTED_LANGUAGE` at the ASR and stops there.

Whisper covers English and is small enough to run beside everything else.
`openai/whisper-base` is Apache-2.0 and ungated, and Phase 10A measured it at
WER 0.1209 on FLEURS English - comparable to IndicConformer's 0.1164 on Hindi.

Why English ONLY, when Whisper is multilingual
----------------------------------------------
Because it was measured, and it failed. The same experiment scored
`whisper-base` at WER 1.1640 on Hindi and 0.9084 on Tamil. Those are not
harness faults: the script-ratio control shows only 7.4% of its Hindi output in
Devanagari - it renders Hindi audio in Urdu script and romanises the rest - and
its Tamil output is in Tamil script yet still wrong. IndicConformer scores
0.1164 and 0.2833 on the same clips.

So this adapter declares English and nothing else. Registering it for Hindi or
Tamil would replace a good transcript with a bad one while looking like a
coverage improvement.

The latency cost, measured and not hidden
-----------------------------------------
Whisper pads every input to 30 s regardless of the real window, so a 2.0 s
window costs the same as a 30 s one. Measured on this machine over real FLEURS
English speech: `whisper-base` 869 ms median, `whisper-tiny` 546 ms. The
IndicConformer stage it replaces costs 265 ms, against a packet budget of
1000 ms whose p95 already sits at ~1000 ms (O13).

An English packet therefore does NOT meet the real-time budget while the
anti-spoof stage is also running. That stage costs 366 ms and Phase J measured
it carrying no usable signal on VIVE's audio (O12), so dropping it is what
makes English affordable - the two decisions are coupled, and the arithmetic is
in O16.

This is why the adapter is configured OFF by default: `asr_english_model_dir`
is empty unless a deployment sets it, and an unconfigured router behaves
exactly as before. Enabling a stage that misses the budget has to be a
deliberate act with the number in front of you.
"""

from __future__ import annotations

import logging
import os
import time

from app.adapters.interfaces import AdapterInfo, AsrResult, AudioWindow
from app.schemas.models import AdapterMode, AnalyzerStatus

logger = logging.getLogger("vive.adapters.asr.whisper")

SAMPLE_RATE = 16_000
MIN_SAMPLES = 4_000
"""Below 0.25 s there is nothing to transcribe."""

MAX_NEW_TOKENS = 64
"""A 2 s window holds a handful of words.

Whisper's own default is 448, which on short or silent input invites it to run
on and hallucinate a paragraph. Capping it bounds both the latency and that
failure mode.
"""

REQUIRED_FILES = ("config.json", "tokenizer.json")

DEFAULT_LANGUAGES = ("en",)
"""The only language this adapter may claim. See the module docstring."""


class WhisperAsrAdapter:
    """Whisper speech recognition, restricted to its measured languages."""

    adapter_key = "asr"
    mode = AdapterMode.REAL
    id = "whisper"
    architecture = "Whisper encoder-decoder"

    def __init__(self, model_dir: str,
                 languages: tuple[str, ...] = DEFAULT_LANGUAGES) -> None:
        self._dir = model_dir
        # Computed once: a backslash cannot appear inside an f-string
        # expression before Python 3.12, and this runs on 3.11.
        self._name = os.path.basename(os.path.normpath(model_dir)) if model_dir else ""

        self._languages = tuple(languages)
        self._model = None
        self._processor = None
        self._status = AnalyzerStatus.UNAVAILABLE
        self._detail: str | None = "not configured"
        self._load_ms: int | None = None
        self._default_language = ""
        self.version = "whisper-unloaded"

    def set_default_language(self, lang: str) -> None:
        """The language to assume when a window does not declare one.

        Mirrors the CTC adapter: the language is an INPUT to decoding, so the
        router and this adapter must resolve it the same way or a routed
        window could be refused by the very backend chosen to serve it.
        """
        self._default_language = (lang or "").lower()

    # --- lifecycle ----------------------------------------------------
    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()
        if not self._dir:
            # Not configured is not a failure. English simply stays
            # unsupported, which is the behaviour before this adapter existed.
            self._status = AnalyzerStatus.UNAVAILABLE
            self._detail = "asr_english_model_dir is not set"
            return self._status
        missing = [name for name in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(self._dir, name))]
        if missing:
            return self._fail(f"missing {', '.join(missing)} under {self._dir}",
                              began)
        try:
            from transformers import (
                WhisperForConditionalGeneration,
                WhisperProcessor,
            )
        except ImportError as exc:
            return self._fail(f"ML runtime not installed ({exc.name})", began)
        try:
            self._processor = WhisperProcessor.from_pretrained(self._dir)
            self._model = WhisperForConditionalGeneration.from_pretrained(
                self._dir).eval()
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
        logger.warning("whisper asr load failed: %s", detail)
        return self._status

    def available(self) -> bool:
        return self._status is AnalyzerStatus.AVAILABLE

    @property
    def languages(self) -> tuple[str, ...]:
        return self._languages if self.available() else ()

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=self._status,
            architecture=self.architecture,
            revision=f"openai/{self._name}" if self._name else None,
            languages=self.languages,
            execution_provider="torch cpu",
            sample_rate=SAMPLE_RATE,
            load_ms=self._load_ms,
            detail=self._detail,
        )

    # --- inference ----------------------------------------------------
    def analyze(self, window: AudioWindow) -> AsrResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            return self._empty(self._status)
        if window.sample_rate != SAMPLE_RATE:
            return self._empty(AnalyzerStatus.INFERENCE_ERROR)

        language = (getattr(window, "language", None)
                    or self._default_language or "").lower()
        if language not in self._languages:
            return self._empty(AnalyzerStatus.UNSUPPORTED_LANGUAGE)

        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            pcm = window.pcm or b""
            if len(pcm) < MIN_SAMPLES * 2:   # 2 bytes per pcm_s16le sample
                return self._empty(AnalyzerStatus.INSUFFICIENT_AUDIO)
            samples = (np.frombuffer(pcm, dtype="<i2").astype(np.float32)
                       / 32768.0).copy()

            features = self._processor(
                samples, sampling_rate=SAMPLE_RATE,
                return_tensors="pt").input_features
            with torch.no_grad():
                generated = self._model.generate(
                    features, language=language, task="transcribe",
                    max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                    num_beams=1, return_dict_in_generate=True,
                    output_scores=True)
            text = self._processor.batch_decode(
                generated.sequences, skip_special_tokens=True)[0].strip()
            confidence = _mean_token_confidence(generated, torch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("whisper inference failed: %s", type(exc).__name__)
            return self._empty(AnalyzerStatus.INFERENCE_ERROR)

        inference_ms = int((time.perf_counter() - began) * 1000)
        if not text:
            return AsrResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version, mode=self.mode,
                transcript=None, confidence=None, language=language,
                inference_ms=inference_ms)
        return AsrResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            transcript=text,
            confidence=confidence,
            language=language,
            # Whisper CAN identify a language, but it is not asked to: the
            # language is supplied as an input, exactly as for the CTC path.
            # Reporting a posterior for a value that was handed in would be
            # fabrication.
            language_confidence=None,
            inference_ms=inference_ms,
        )

    def _empty(self, status: AnalyzerStatus) -> AsrResult:
        return AsrResult(status=status, model_version=self.version,
                         mode=self.mode, transcript=None, confidence=None)


def _mean_token_confidence(generated, torch) -> float | None:
    """Mean per-token decoder probability.

    The same quantity the CTC path reports and with the same caveat: this is a
    DECODER confidence, not a probability that the transcript is correct, and
    certainly not a fraud probability (docs/ML_SPEC.md 4).
    """
    scores = getattr(generated, "scores", None)
    if not scores:
        return None
    tokens = generated.sequences[0][-len(scores):]
    probabilities = []
    for step, token in zip(scores, tokens):
        distribution = torch.softmax(step[0], dim=-1)
        probabilities.append(float(distribution[int(token)]))
    if not probabilities:
        return None
    return round(sum(probabilities) / len(probabilities), 4)
