"""Routes a window to the ASR that covers its language.

`BLOCKERS.md` O16: no single model VIVE can use covers its three priority
languages. IndicConformer is IN-22 and has no English at all; Whisper covers
English well and Hindi and Tamil badly (Phase 10A: WER 1.1640 and 0.9084
against IndicConformer's 0.1164 and 0.2833). Each is good at what the other
cannot do.

So the router does not choose a *better* model. It sends each language to the
only model measured to handle it, and declines languages no backend covers.

Rules, and why each one
-----------------------
**A language is served by exactly one backend.** The first registered backend
declaring a language wins, and the order is the order given at construction.
No fallback chain: if the model that owns a language fails, the packet reports
that failure. Falling back to a model measured at WER 1.16 would replace a
missing transcript with a wrong one, and a wrong transcript feeds the intent
head and becomes risk.

**An unrouted language is UNSUPPORTED_LANGUAGE, never an error.** That is the
status the conformer already returns for English, and the Android UI renders it
as "not supported" rather than "analysis failed".

**The result carries the backend's own `model_version`.** A packet says which
model transcribed it, so evidence stays attributable when two models are in
play. `describe()` reports the union of covered languages and names the
backends, so a session can tell before any packet arrives.
"""

from __future__ import annotations

import logging

from app.adapters.interfaces import AdapterInfo, AsrResult, AudioWindow
from app.schemas.models import AdapterMode, AnalyzerStatus

logger = logging.getLogger("vive.adapters.asr.router")


class RoutingAsrAdapter:
    """Dispatches by language across several ASR backends."""

    adapter_key = "asr"
    mode = AdapterMode.REAL
    id = "asr-router"
    architecture = "language-routed ASR"

    def __init__(self, *backends) -> None:
        """`backends` in priority order; the first to claim a language wins."""
        self._backends = [b for b in backends if b is not None]
        self._primary = self._backends[0] if self._backends else None
        self._status = AnalyzerStatus.UNAVAILABLE
        self._default_language = "hi"

    @property
    def version(self) -> str:
        return "+".join(b.version for b in self._backends) or "asr-router-empty"

    # --- lifecycle ----------------------------------------------------
    def load(self) -> AnalyzerStatus:
        """Loads every backend; the router is available if ANY of them is.

        One backend failing must not take the others down with it. A broken
        English model should cost English, not Hindi.
        """
        for backend in self._backends:
            try:
                backend.load()
            except Exception as exc:  # noqa: BLE001
                logger.warning("asr backend %s failed to load: %s",
                               getattr(backend, "id", "?"), type(exc).__name__)
        self._status = (AnalyzerStatus.AVAILABLE
                        if any(b.available() for b in self._backends)
                        else self._primary_status())
        return self._status

    def _primary_status(self) -> AnalyzerStatus:
        """The status to report when nothing loaded.

        The primary backend's own status, because it is the more informative
        one: LOAD_ERROR with a reason beats a bare UNAVAILABLE.
        """
        if self._primary is None:
            return AnalyzerStatus.UNAVAILABLE
        return self._primary.describe().status

    def available(self) -> bool:
        return any(b.available() for b in self._backends)

    @property
    def languages(self) -> tuple[str, ...]:
        seen: list[str] = []
        for backend in self._backends:
            for lang in backend.languages:
                if lang not in seen:
                    seen.append(lang)
        return tuple(sorted(seen))

    def set_default_language(self, lang: str) -> None:
        self._default_language = lang
        for backend in self._backends:
            setter = getattr(backend, "set_default_language", None)
            if callable(setter):
                setter(lang)

    def describe(self) -> AdapterInfo:
        parts = []
        for backend in self._backends:
            info = backend.describe()
            covered = ",".join(backend.languages) or "-"
            parts.append(f"{info.model_id}[{covered}]={info.status.value}")
        primary = self._primary.describe() if self._primary else None
        return AdapterInfo(
            adapter_key=self.adapter_key,
            model_id=self.id,
            model_version=self.version,
            mode=self.mode,
            status=self._status,
            architecture=self.architecture,
            revision=" + ".join(
                b.describe().revision or "?" for b in self._backends) or None,
            languages=self.languages,
            execution_provider=primary.execution_provider if primary else None,
            sample_rate=primary.sample_rate if primary else None,
            load_ms=sum(b.describe().load_ms or 0 for b in self._backends) or None,
            detail="; ".join(parts) or "no ASR backends configured",
        )

    # --- inference ----------------------------------------------------
    def _backend_for(self, language: str | None):
        wanted = (language or self._default_language or "").lower()
        for backend in self._backends:
            if wanted in backend.languages:
                return backend
        return None

    def analyze(self, window: AudioWindow) -> AsrResult:
        language = getattr(window, "language", None) or self._default_language
        backend = self._backend_for(language)
        if backend is None:
            # No backend covers it. Not a failure of any model - a gap in
            # coverage, which is what O16 describes and what the UI must say.
            return AsrResult(
                status=AnalyzerStatus.UNSUPPORTED_LANGUAGE,
                model_version=self.version, mode=self.mode,
                transcript=None, confidence=None, language=language)
        return backend.analyze(window)
