"""Builds the analyzer bundle from configuration.

One place decides mock versus real, so routes, session management, fusion and
the UI never branch on it (docs/ARCHITECTURE.md decision 7).

**The bundle never silently downgrades.** In real mode an adapter that cannot
load is still the real adapter, reporting `LOAD_ERROR`. It is not replaced by
its mock counterpart, because output that looks identical whether or not the
model loaded is indistinguishable from a fabricated result
(docs/ML_SPEC.md 4).

Real mode is per-component. Phase 8A wires ASR only; the remaining analyzers
stay mock and say so through `mode`, so a partially real bundle is honestly
represented rather than being advertised as fully real.
"""

from __future__ import annotations

import logging

from app.adapters.interfaces import AdapterBundle
from app.adapters.mock import (
    MockAntiSpoofAdapter,
    MockAsrAdapter,
    MockBehaviorAdapter,
    MockIntentAdapter,
    MockSpeakerAdapter,
    MockVadAdapter,
    build_mock_bundle,
)
from app.core.config import Settings

logger = logging.getLogger("vive.adapters")


def build_bundle(settings: Settings) -> AdapterBundle:
    """Returns the analyzer bundle selected by configuration."""
    if settings.adapter_mode == "mock":
        logger.info("adapter bundle: mock (deterministic, not model inference)")
        return build_mock_bundle()
    return _build_real_bundle(settings)


def _build_real_bundle(settings: Settings) -> AdapterBundle:
    """Real where implemented, mock elsewhere, honest about which is which."""
    # Imported here so `mock` mode never touches the real package.
    from app.adapters.real.asr_conformer import IndicConformerAsrAdapter

    asr = IndicConformerAsrAdapter(
        settings.asr_model_dir,
        prefer_gpu=settings.asr_prefer_gpu,
    )
    asr.set_default_language(settings.asr_default_language)
    status = asr.load()
    info = asr.describe()
    if status.name == "AVAILABLE":
        logger.info(
            "adapter bundle: real ASR %s loaded in %sms via %s, %d languages",
            info.model_version, info.load_ms, info.execution_provider,
            len(info.languages),
        )
    else:
        # Loud, and the adapter stays real: the pipeline will report
        # LOAD_ERROR per packet rather than inventing transcripts.
        logger.error(
            "adapter bundle: real ASR unavailable (%s) - %s. "
            "ASR results will report this status; no mock fallback is applied.",
            status, info.detail,
        )

    return AdapterBundle(
        vad=MockVadAdapter(),
        antispoof=MockAntiSpoofAdapter(),
        speaker=MockSpeakerAdapter(),
        asr=asr,
        intent=MockIntentAdapter(),
        behavior=MockBehaviorAdapter(),
    )


__all__ = ["build_bundle", "MockAsrAdapter"]
