"""Builds the analyzer bundle from configuration.

One place decides mock versus real, so routes, session management, fusion and
the UI never branch on it (docs/ARCHITECTURE.md decision 7).

**The bundle never silently downgrades.** In real mode an adapter that cannot
load is still the real adapter, reporting `LOAD_ERROR`. It is not replaced by
its mock counterpart, because output that looks identical whether or not the
model loaded is indistinguishable from a fabricated result
(docs/ML_SPEC.md 4).

Real mode is per-component, and each component reports its own `mode` and
`status`, so a bundle where some models loaded and others did not is
represented honestly rather than advertised as uniformly real.
"""

from __future__ import annotations

import logging

from app.adapters.interfaces import AdapterBundle
from app.adapters.mock import MockAsrAdapter, build_mock_bundle
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
    from app.adapters.real.antispoof_wav2vec import Wav2VecAntiSpoofAdapter
    from app.adapters.real.asr_conformer import IndicConformerAsrAdapter
    from app.adapters.real.asr_router import RoutingAsrAdapter
    from app.adapters.real.asr_whisper import WhisperAsrAdapter
    from app.adapters.real.audio_models import (
        AasistAntiSpoofAdapter,
        EcapaSpeakerAdapter,
        SileroVadAdapter,
    )
    from app.adapters.real.text_classifiers import RealBehaviorAdapter, RealIntentAdapter

    # IndicConformer first: it owns the Indic languages, and the router gives
    # a language to the FIRST backend that declares it. Whisper covers only
    # English here (Phase 10A measured it at WER 1.16 on Hindi), so the two
    # never compete for a language - the order documents the intent rather
    # than resolving a conflict.
    conformer = IndicConformerAsrAdapter(
        settings.asr_model_dir,
        prefer_gpu=settings.asr_prefer_gpu,
    )
    english = WhisperAsrAdapter(settings.asr_english_model_dir)
    asr = RoutingAsrAdapter(conformer, english)
    asr.set_default_language(settings.asr_default_language)
    intent = RealIntentAdapter(settings.intent_model_dir)
    behavior = RealBehaviorAdapter(settings.behavior_model_dir)
    vad = SileroVadAdapter(settings.vad_model_dir)
    # AASIST stays selectable and its integration is proven correct
    # (EER 0.0133 in-domain, Phase J), but it does not transfer to VIVE's
    # audio. The default is the model Phase J2 measured at 0.1000 on the
    # off-domain probe against AASIST's 0.4333.
    antispoof = (
        AasistAntiSpoofAdapter(settings.antispoof_model_dir)
        if settings.antispoof_kind == "aasist"
        else Wav2VecAntiSpoofAdapter(settings.antispoof_model_dir)
    )
    speaker = EcapaSpeakerAdapter(settings.speaker_model_dir)

    for adapter in (vad, antispoof, speaker, asr, intent, behavior):
        status = adapter.load()
        info = adapter.describe()
        if status.name == "AVAILABLE":
            logger.info(
                "adapter bundle: real %s %s loaded in %sms (%s)",
                info.adapter_key, info.model_version, info.load_ms,
                info.execution_provider,
            )
        else:
            # Loud, and the adapter stays real: the pipeline reports the
            # status per packet rather than inventing a result.
            logger.error(
                "adapter bundle: real %s unavailable (%s) - %s. "
                "Results will report this status; no mock fallback is applied.",
                info.adapter_key, status, info.detail,
            )

    return AdapterBundle(
        vad=vad, antispoof=antispoof, speaker=speaker,
        asr=asr, intent=intent, behavior=behavior,
    )


__all__ = ["build_bundle", "MockAsrAdapter"]
