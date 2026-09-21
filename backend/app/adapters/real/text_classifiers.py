"""Real intent and behaviour adapters: fine-tuned multilingual DistilBERT.

Trained in Phase 7 (docs/ML_SPEC.md 9.1). Both heads share a backbone and a
tokenizer but are separate checkpoints with different heads:

  intent   - single-label softmax over 12 labels
  behaviour - multi-label sigmoid over 8 labels, threshold 0.5

Decoding mirrors training exactly. The behaviour threshold is the same 0.5 the
evaluation used, so the numbers in the training report describe this code path.

Label safety
------------
The checkpoint config carries an explicit `id2label`, written from
`models/training/vive_labels.py` and cross-checked against the training report.
`load()` verifies that mapping against the live VIVE taxonomy and **refuses to
load on any mismatch**, because a silently reordered head would produce
confident predictions for the wrong labels - the single most dangerous failure
mode for this component. No label is ever coerced, renamed or mapped onto a
"nearest" VIVE label.

Language safety
---------------
These models were trained on a corpus with English, Hindi and Hinglish and
**zero Tamil records** (docs/BLOCKERS.md O11). Tamil ASR is validated, so Tamil
transcripts do reach this code. For an unsupported language the adapters return
`UNSUPPORTED_LANGUAGE` rather than a prediction: an untrained guess presented
as an intent would misrepresent the product's capability.

Known limitations, carried from the Phase 7 audit and not hidden here:
  * `OTP_REQUEST` had 8 test records - unmeasurable, not "63% accurate".
  * 5 intents and 2 behaviours have no training data and can never be emitted.
  * Intent is 100% collinear with the corpus scam flag (O10), so the intent
    head partly measures scam/not-scam rather than intent discrimination.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app.adapters.interfaces import AdapterInfo, BehaviorResult, IntentResult
from app.schemas.models import AdapterMode, AnalyzerStatus, Behavior, Intent

logger = logging.getLogger("vive.adapters.text")

MAX_LENGTH = 96
"""Matches the Phase 7 training configuration. Changing it changes the
truncation point and therefore the predictions."""

BEHAVIOR_THRESHOLD = 0.5
"""The multi-label threshold used at evaluation time."""

SUPPORTED_LANGUAGES = frozenset({"en", "hi", "hi-en"})
"""Languages present in the training corpus. Everything else is declined.

Tamil is deliberately absent: the corpus held 0 Tamil records and 0 Tamil
codepoints (docs/DATA_SPEC.md 8.3)."""

REQUIRED_FILES = ("config.json", "model.safetensors", "tokenizer.json")


class _TextAdapter:
    """Shared load, validation and language gating."""

    mode = AdapterMode.REAL

    def __init__(self, model_dir: str, *, labels: tuple[str, ...],
                 adapter_key: str, model_id: str, version: str) -> None:
        self._model_dir = model_dir
        self._labels = labels
        self.adapter_key = adapter_key
        self.id = model_id
        self.version = version
        self._model: Any = None
        self._tokenizer: Any = None
        self._status = AnalyzerStatus.UNAVAILABLE
        self._detail: str | None = "not loaded yet"
        self._load_ms: int | None = None

    # --- lifecycle ----------------------------------------------------

    def load(self) -> AnalyzerStatus:
        if self._model is not None:
            return self._status
        began = time.perf_counter()

        missing = [f for f in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(self._model_dir, f))]
        if missing:
            return self._fail(f"missing {len(missing)} required file(s) under "
                              f"{self._model_dir}: {missing[0]}"
                              + (" (+more)" if len(missing) > 1 else ""), began)

        try:
            import torch  # noqa: F401
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            return self._fail(f"ML runtime not installed ({exc.name}). "
                              'Install with: pip install -e "backend[ml]"', began)

        try:
            with open(os.path.join(self._model_dir, "config.json"), encoding="utf-8") as fh:
                cfg = json.load(fh)
            problem = self._validate_labels(cfg)
            if problem:
                return self._fail(problem, began)

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_dir)
            model = AutoModelForSequenceClassification.from_pretrained(self._model_dir)
            model.eval()
            self._model = model
            self._status = AnalyzerStatus.AVAILABLE
            self._detail = None
        except Exception as exc:  # noqa: BLE001
            return self._fail(f"{type(exc).__name__}: {str(exc)[:160]}", began)

        self._load_ms = int((time.perf_counter() - began) * 1000)
        return self._status

    def _validate_labels(self, cfg: dict) -> str | None:
        """Returns a reason string on mismatch, else None.

        Refusing to load is the correct response: a head whose label order does
        not match the taxonomy would emit confident, wrong labels.
        """
        id2label = cfg.get("id2label")
        if not id2label:
            return ("checkpoint declares no id2label; refusing to guess the "
                    "label order")
        try:
            ordered = [id2label[str(i)] for i in range(len(id2label))]
        except KeyError:
            return "checkpoint id2label is not densely indexed from 0"
        if len(ordered) != len(self._labels):
            return (f"checkpoint has {len(ordered)} labels, VIVE taxonomy has "
                    f"{len(self._labels)}")
        mismatch = [(i, a, b) for i, (a, b) in enumerate(zip(ordered, self._labels))
                    if a != b]
        if mismatch:
            i, got, want = mismatch[0]
            return (f"label order mismatch at index {i}: checkpoint says "
                    f"{got!r}, taxonomy says {want!r} ({len(mismatch)} differ)")
        return None

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
            architecture="DistilBERT (multilingual) sequence classification",
            revision="distilbert/distilbert-base-multilingual-cased (fine-tuned)",
            languages=tuple(sorted(SUPPORTED_LANGUAGES)),
            execution_provider="torch cpu",
            load_ms=self._load_ms,
            detail=self._detail,
        )

    # --- shared inference ---------------------------------------------

    def _logits(self, transcript: str):
        import torch
        batch = self._tokenizer(transcript, truncation=True,
                                max_length=MAX_LENGTH, return_tensors="pt")
        with torch.no_grad():
            return self._model(**batch).logits[0]

    def _guard(self, transcript: str | None, language: str | None) -> AnalyzerStatus | None:
        """Returns a status to short-circuit on, or None to proceed."""
        if self._status is not AnalyzerStatus.AVAILABLE:
            return self._status
        if language is not None and language not in SUPPORTED_LANGUAGES:
            return AnalyzerStatus.UNSUPPORTED_LANGUAGE
        if not (transcript or "").strip():
            return AnalyzerStatus.INSUFFICIENT_AUDIO
        return None


class RealIntentAdapter(_TextAdapter):
    """Single-label intent over the 12-label VIVE taxonomy."""

    def __init__(self, model_dir: str) -> None:
        super().__init__(
            model_dir,
            labels=tuple(i.value for i in Intent),
            adapter_key="intent",
            model_id="intent-classifier",
            version="intent-classifier-distilbert-v1",
        )

    def analyze(self, transcript: str | None,
                language: str | None = None) -> IntentResult:
        blocked = self._guard(transcript, language)
        if blocked is not None:
            return IntentResult(status=blocked, model_version=self.version,
                                mode=self.mode, label=Intent.UNKNOWN,
                                confidence=None)
        began = time.perf_counter()
        try:
            import torch
            probs = torch.softmax(self._logits(transcript or ""), dim=-1)
            index = int(torch.argmax(probs))
            # Constructed from the validated taxonomy, never from a free string,
            # so an out-of-range index raises here rather than inventing a label.
            label = Intent(self._labels[index])
            confidence = round(float(probs[index]), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intent inference failed: %s", type(exc).__name__)
            return IntentResult(status=AnalyzerStatus.INFERENCE_ERROR,
                                model_version=self.version, mode=self.mode,
                                label=Intent.UNKNOWN, confidence=None)
        return IntentResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, label=label, confidence=confidence,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )


class RealBehaviorAdapter(_TextAdapter):
    """Multi-label social-engineering behaviour over the 8-label taxonomy."""

    def __init__(self, model_dir: str) -> None:
        super().__init__(
            model_dir,
            labels=tuple(b.value for b in Behavior),
            adapter_key="behavior",
            model_id="behavior-classifier",
            version="behavior-classifier-distilbert-v1",
        )

    def analyze(self, transcript: str | None,
                language: str | None = None) -> BehaviorResult:
        blocked = self._guard(transcript, language)
        if blocked is not None:
            return BehaviorResult(status=blocked, model_version=self.version,
                                  mode=self.mode, labels=[], confidence=None)
        began = time.perf_counter()
        try:
            import torch
            probs = torch.sigmoid(self._logits(transcript or ""))
            fired = [(i, float(p)) for i, p in enumerate(probs)
                     if float(p) >= BEHAVIOR_THRESHOLD]
            labels = [Behavior(self._labels[i]) for i, _ in fired]
            # Mean probability of the labels that fired. A per-packet decoder
            # confidence, NOT a calibrated probability and NOT a fraud score.
            confidence = (round(sum(p for _, p in fired) / len(fired), 4)
                          if fired else None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("behaviour inference failed: %s", type(exc).__name__)
            return BehaviorResult(status=AnalyzerStatus.INFERENCE_ERROR,
                                  model_version=self.version, mode=self.mode,
                                  labels=[], confidence=None)
        return BehaviorResult(
            status=AnalyzerStatus.AVAILABLE, model_version=self.version,
            mode=self.mode, labels=labels, confidence=confidence,
            inference_ms=int((time.perf_counter() - began) * 1000),
        )
