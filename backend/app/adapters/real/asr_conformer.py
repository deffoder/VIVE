"""Real ASR adapter: AI4Bharat IndicConformer-600M, CTC path.

Selected in Phase 7 on measured evidence (docs/ML_SPEC.md 2.1):
Hindi WER 0.1164 / CER 0.0460, Tamil WER 0.2833 / CER 0.1107 on FLEURS, and
0.2549 s per 2 s window measured directly. Those are **clean read-speech
benchmark** figures, not telephone or call-channel accuracy, and nothing in
this module may be described as the latter.

Only the CTC path is loaded: `encoder.onnx` + `ctc_decoder.onnx`, 2 of the
repository's 28 components. The upstream loader constructs the RNNT decoder and
all 22 joint networks even when decoding with CTC, which costs load time and
memory VIVE does not need.

Decoding follows upstream `_ctc_decode` exactly: per-language vocabulary mask,
log-softmax, greedy argmax, collapse repeats, drop blanks, map through the
language vocabulary.

Failure policy (docs/PROJECT_SPEC.md 7): this adapter never invents a
transcript. Missing weights or a missing runtime give `LOAD_ERROR`; a failure
on one packet gives `INFERENCE_ERROR`; audio too short to analyse gives
`INSUFFICIENT_AUDIO`. In every case `transcript` is None and `mode` stays
REAL.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

from app.adapters.interfaces import AdapterInfo, AsrResult, AudioWindow
from app.schemas.models import AdapterMode, AnalyzerStatus

logger = logging.getLogger("vive.adapters.asr")

MODEL_ID = "indic-conformer-600m"
"""Canonical VIVE id (docs/ML_SPEC.md 2)."""

HF_REPO = "ai4bharat/indic-conformer-600m-multilingual"
MODEL_VERSION = "indic-conformer-600m-ctc-v1"
ARCHITECTURE = "Conformer hybrid CTC/RNNT, CTC decoding path"
SAMPLE_RATE = 16_000

MIN_SAMPLES = SAMPLE_RATE // 2
"""Below 0.5 s the encoder's downsampling leaves too few frames to decode.
Reported as INSUFFICIENT_AUDIO rather than returning an empty transcript that
would look like confident silence."""

REQUIRED_FILES = (
    "config.json",
    os.path.join("assets", "encoder.onnx"),
    os.path.join("assets", "ctc_decoder.onnx"),
    os.path.join("assets", "preprocessor.ts"),
    os.path.join("assets", "vocab.json"),
    os.path.join("assets", "language_masks.json"),
)


@dataclass(frozen=True)
class _Loaded:
    """Everything the hot path needs, resolved once."""

    preprocessor: object
    encoder: object
    ctc: object
    vocab: dict
    masks: dict
    blank_id: int
    providers: tuple[str, ...]


class IndicConformerAsrAdapter:
    """CTC-only IndicConformer behind the existing `AsrAdapter` protocol."""

    id = MODEL_ID
    version = MODEL_VERSION
    mode = AdapterMode.REAL
    adapter_key = "asr"

    def __init__(self, model_dir: str, *, prefer_gpu: bool = False,
                 eager: bool = False) -> None:
        self._model_dir = model_dir
        self._prefer_gpu = prefer_gpu
        self._loaded: _Loaded | None = None
        self._status = AnalyzerStatus.UNAVAILABLE
        self._detail: str | None = "not loaded yet"
        self._load_ms: int | None = None
        if eager:
            self.load()

    # --- lifecycle ----------------------------------------------------

    def load(self) -> AnalyzerStatus:
        """Loads once. Records why on failure; never raises to the caller."""
        if self._loaded is not None:
            return self._status

        began = time.perf_counter()
        missing = [f for f in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(self._model_dir, f))]
        if missing:
            self._status = AnalyzerStatus.LOAD_ERROR
            self._detail = (f"missing {len(missing)} required file(s) under "
                            f"{self._model_dir}: {missing[0]}"
                            + (" (+more)" if len(missing) > 1 else ""))
            logger.warning("asr adapter load failed: %s", self._detail)
            return self._status

        try:
            # Imported here, not at module level, so the backend and its tests
            # run without the ML extras installed.
            import onnxruntime as ort
            import torch
        except ImportError as exc:
            self._status = AnalyzerStatus.LOAD_ERROR
            self._detail = (f"ML runtime not installed ({exc.name}). "
                            'Install with: pip install -e "backend[ml]"')
            logger.warning("asr adapter load failed: %s", self._detail)
            return self._status

        try:
            assets = os.path.join(self._model_dir, "assets")
            with open(os.path.join(self._model_dir, "config.json"), encoding="utf-8") as fh:
                blank_id = int(json.load(fh)["BLANK_ID"])

            device = torch.device(
                "cuda" if (self._prefer_gpu and torch.cuda.is_available()) else "cpu")
            preprocessor = torch.jit.load(
                os.path.join(assets, "preprocessor.ts"), map_location=device)

            available = ort.get_available_providers()
            wanted = ["CPUExecutionProvider"]
            if self._prefer_gpu and "CUDAExecutionProvider" in available:
                wanted = ["CUDAExecutionProvider", "CPUExecutionProvider"]

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            encoder = ort.InferenceSession(
                os.path.join(assets, "encoder.onnx"), opts, providers=wanted)
            ctc = ort.InferenceSession(
                os.path.join(assets, "ctc_decoder.onnx"), opts, providers=wanted)

            with open(os.path.join(assets, "vocab.json"), encoding="utf-8") as fh:
                vocab = json.load(fh)
            with open(os.path.join(assets, "language_masks.json"), encoding="utf-8") as fh:
                masks = json.load(fh)

            self._loaded = _Loaded(
                preprocessor=preprocessor, encoder=encoder, ctc=ctc,
                vocab=vocab, masks=masks, blank_id=blank_id,
                # What actually served the graph, not what was requested.
                providers=tuple(encoder.get_providers()),
            )
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
            self._warmup()
        except Exception as exc:  # noqa: BLE001 - must not propagate
            self._status = AnalyzerStatus.LOAD_ERROR
            # Type and message only: never a stack trace, never a submitted
            # value (docs/SECURITY_SPEC.md 6).
            self._detail = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("asr adapter load failed: %s", self._detail)

        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    def _warmup(self) -> None:
        """Primes the graphs with one throwaway inference.

        onnxruntime allocates arenas and resolves kernels on the FIRST run, not
        at session creation. Measured: the first real packet cost ~8.7 s against
        a ~0.32 s steady-state median - 27x - which would blow the 1.0 s cadence
        at the start of every session. Paying it once at load moves it off the
        hot path.

        Failure here is not fatal: the model is loaded and usable, the first
        packet would just be slow, so warm-up problems are logged and swallowed
        rather than downgrading a working adapter to LOAD_ERROR.
        """
        try:
            began = time.perf_counter()
            silence = b"\x00" * (SAMPLE_RATE * 2 * 2)   # 2 s of pcm_s16le
            self.analyze(AudioWindow(
                session_id="__warmup__", seq=0, start_sec=0.0, end_sec=2.0,
                pcm=silence, sample_rate=SAMPLE_RATE))
            self._warmup_ms = int((time.perf_counter() - began) * 1000)
            logger.info("asr warm-up completed in %sms", self._warmup_ms)
        except Exception as exc:  # noqa: BLE001
            self._warmup_ms = None
            logger.warning("asr warm-up failed (model still usable): %s",
                           type(exc).__name__)

    _warmup_ms: int | None = None

    def available(self) -> bool:
        return self._status is AnalyzerStatus.AVAILABLE

    @property
    def languages(self) -> tuple[str, ...]:
        if self._loaded is None:
            return ()
        return tuple(sorted(self._loaded.masks))

    def describe(self) -> AdapterInfo:
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=self._status,
            architecture=ARCHITECTURE,
            revision=HF_REPO,
            languages=self.languages,
            execution_provider=(", ".join(self._loaded.providers)
                                if self._loaded else None),
            sample_rate=SAMPLE_RATE,
            load_ms=self._load_ms,
            detail=self._detail if self._detail else (
                f"warm-up {self._warmup_ms}ms" if self._warmup_ms else None),
        )

    # --- inference ----------------------------------------------------

    def analyze(self, window: AudioWindow) -> AsrResult:
        if self._status is not AnalyzerStatus.AVAILABLE:
            # Covers both "never loaded" and "load failed". Either way there is
            # no transcript, and the mode stays REAL.
            return self._empty(self._status if self._status is not AnalyzerStatus.UNAVAILABLE
                               else AnalyzerStatus.UNAVAILABLE)

        if window.sample_rate != SAMPLE_RATE:
            return self._empty(
                AnalyzerStatus.INFERENCE_ERROR,
                detail=f"expected {SAMPLE_RATE} Hz, got {window.sample_rate}")

        lang = self._resolve_language(window)
        if lang is None:
            return self._empty(AnalyzerStatus.INFERENCE_ERROR,
                               detail="no supported language selected")

        began = time.perf_counter()
        try:
            import numpy as np
            import torch

            pcm = window.pcm or b""
            if len(pcm) < MIN_SAMPLES * 2:   # 2 bytes per pcm_s16le sample
                return self._empty(AnalyzerStatus.INSUFFICIENT_AUDIO)

            # pcm_s16le -> float32 in [-1, 1]. Copy because np.frombuffer gives
            # a read-only view over the original bytes.
            samples = (np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0).copy()
            if samples.size < MIN_SAMPLES:
                return self._empty(AnalyzerStatus.INSUFFICIENT_AUDIO)

            model = self._loaded
            assert model is not None
            tensor = torch.from_numpy(samples).reshape(1, -1)
            signal, length = model.preprocessor(
                input_signal=tensor, length=torch.tensor([tensor.shape[-1]]))
            outputs, _lengths = model.encoder.run(
                ["outputs", "encoded_lengths"],
                {"audio_signal": signal.cpu().numpy(), "length": length.cpu().numpy()})
            logprobs = model.ctc.run(["logprobs"], {"encoder_output": outputs})[0]
            masked = torch.from_numpy(logprobs[:, :, model.masks[lang]]).log_softmax(dim=-1)
            indices = torch.argmax(masked[0], dim=-1)
            collapsed = torch.unique_consecutive(indices, dim=-1)
            text = "".join(model.vocab[lang][int(i)] for i in collapsed
                           if int(i) != model.blank_id).replace("▁", " ").strip()

            # Mean per-frame max log-prob over non-blank frames, exponentiated.
            # This is a decoder confidence, NOT a probability that the
            # transcript is correct and NOT a fraud probability.
            kept = indices != model.blank_id
            confidence = (float(masked[0].max(dim=-1).values[kept].mean().exp())
                          if bool(kept.any()) else None)
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {str(exc)[:160]}"
            logger.warning("asr inference failed: %s", detail)
            return self._empty(AnalyzerStatus.INFERENCE_ERROR, detail=detail)

        inference_ms = int((time.perf_counter() - began) * 1000)
        if not text:
            # The model ran and emitted only blanks: silence or non-speech.
            return AsrResult(
                status=AnalyzerStatus.INSUFFICIENT_AUDIO,
                model_version=self.version, mode=self.mode,
                transcript=None, confidence=None,
                language=lang, inference_ms=inference_ms,
            )
        return AsrResult(
            status=AnalyzerStatus.AVAILABLE,
            model_version=self.version,
            mode=self.mode,
            transcript=text,
            confidence=round(confidence, 4) if confidence is not None else None,
            language=lang,
            # The CTC path decodes a language it is TOLD, it does not identify
            # one, so there is no language posterior to report. Reporting a
            # number here would be fabrication.
            language_confidence=None,
            inference_ms=inference_ms,
        )

    # --- helpers ------------------------------------------------------

    def _resolve_language(self, window: AudioWindow) -> str | None:
        """Picks the decoding language.

        The CTC decoder applies a per-language vocabulary mask, so the language
        determines which tokens can be emitted at all. It is a required input,
        not an output. Until a language-ID model exists the session default is
        used; `PHASE8_PREREQUISITES.md` 6 tracks that gap.
        """
        model = self._loaded
        if model is None:
            return None
        hint = getattr(window, "language", None) or self._default_language
        return hint if hint in model.masks else None

    _default_language = "hi"

    def set_default_language(self, lang: str) -> None:
        self._default_language = lang

    def _empty(self, status: AnalyzerStatus, detail: str | None = None) -> AsrResult:
        if detail:
            logger.debug("asr empty result: %s (%s)", status, detail)
        return AsrResult(
            status=status,
            model_version=self.version,
            mode=self.mode,
            transcript=None,
            confidence=None,
            language=None,
            language_confidence=None,
            inference_ms=0,
        )
