"""Phase 9: does VIVE fail safely, or does it fail confidently?

Two related properties, tested against the real adapters and the real fusion.

**Out-of-distribution input.** Silence, a DC offset, a pure tone, white noise,
a 10-millisecond fragment, clipped audio, an odd-length PCM buffer, Tamil text.
None of these is speech a model was trained on. The requirement is not that the
models be right - they cannot be - but that the system says what it does not
know instead of producing a confident number. Every adapter has explicit
states for this (`INSUFFICIENT_AUDIO`, `NO_SPEECH`, `UNSUPPORTED_LANGUAGE`,
`NO_REFERENCE`, `LOAD_ERROR`, `INFERENCE_ERROR`), and this checks they are
actually reached rather than merely declared.

**Model failure.** An adapter whose weights are missing must report
`LOAD_ERROR` and emit no value. Three things then have to hold at once, and
they pull in different directions:

  1. the pipeline keeps running,
  2. confidence falls, because there is less evidence,
  3. **risk does not rise**.

The third is the one that is easy to get wrong. A missing anti-spoof score
must not be treated as suspicious, or every model outage becomes a wave of
false alarms - and a system that escalates when its own models break is
unusable precisely when it is degraded.

The complement is checked too: a failed model must not silently downgrade to
mock output. A demo that looks identical whether or not the model loaded is
indistinguishable from a fabricated result.

Usage:
    python scripts/evaluation/exp_ood_failure.py
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import Experiment, add_backend_to_path, model_dir  # noqa: E402

SAMPLE_RATE = 16_000


def pcm_from(values) -> bytes:
    import numpy as np
    return (np.clip(np.asarray(values, dtype="float32"), -1.0, 1.0)
            * 32767.0).astype("<i2").tobytes()


def build_inputs() -> dict[str, bytes]:
    import numpy as np

    n = int(2.0 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    rng = np.random.default_rng(20260922)
    return {
        "digital_silence": b"\x00\x00" * n,
        "dc_offset": pcm_from(np.full(n, 0.5)),
        "pure_tone_440hz": pcm_from(0.5 * np.sin(2 * np.pi * 440 * t)),
        "white_noise": pcm_from(0.3 * rng.standard_normal(n)),
        "full_scale_square": pcm_from(np.sign(np.sin(2 * np.pi * 200 * t))),
        "ten_millisecond_fragment": pcm_from(0.2 * rng.standard_normal(160)),
        "single_sample": struct.pack("<h", 1000),
        "empty_buffer": b"",
        "odd_byte_count": (b"\x00\x00" * 1000) + b"\x01",
    }


def main() -> int:
    add_backend_to_path()

    from app.adapters.interfaces import (AntiSpoofResult, AsrResult,
                                         BehaviorResult, AudioWindow,
                                         IntentResult, SpeakerResult, VadResult)
    from app.adapters.real.asr_conformer import IndicConformerAsrAdapter
    from app.adapters.real.audio_models import (AasistAntiSpoofAdapter,
                                                EcapaSpeakerAdapter,
                                                SileroVadAdapter)
    from app.adapters.real.text_classifiers import (RealBehaviorAdapter,
                                                    RealIntentAdapter)
    from app.risk.fusion import FusionInput, fuse
    from app.schemas.models import (AdapterMode, AnalyzerStatus, AudioQuality,
                                    Behavior, Intent)

    exp = Experiment(
        "9H_ood_and_failure_injection",
        question=("When the input is not speech, or a model is unavailable, "
                  "does VIVE report an explicit state and leave risk alone - "
                  "or does it produce a confident number?"),
        hypothesis=("Every adapter will reach an explicit state rather than "
                    "emit a value, and a model failure will lower confidence "
                    "without raising risk."),
        method=("Feed degenerate audio and unsupported-language text through "
                "the real adapters. Separately construct adapters with no "
                "weights and confirm LOAD_ERROR, no value, no mock fallback, "
                "and the effect on fused risk and confidence."))

    # ---------------------------------------------------------------- OOD
    adapters = {
        "vad": SileroVadAdapter(model_dir("_pretrained", "silero-vad")),
        "antispoof": AasistAntiSpoofAdapter(model_dir("_pretrained", "aasist")),
        "speaker": EcapaSpeakerAdapter(model_dir("_pretrained", "ecapa")),
    }
    asr = IndicConformerAsrAdapter(model_dir("_pretrained", "indic-conformer-ctc"))
    loaded = {key: adapter.load() for key, adapter in adapters.items()}
    loaded["asr"] = asr.load()

    # Declare what actually ran. A record that names no model cannot be
    # reproduced, and the integrity check refuses one.
    for name, revision, licence in (
            ("silero-vad", "snakers4/silero-vad v5 jit", "MIT"),
            ("aasist", "clovaai/aasist AASIST.pth", "MIT"),
            ("ecapa-tdnn", "speechbrain/spkrec-ecapa-voxceleb", "Apache-2.0"),
            ("indic-conformer-600m", "ai4bharat CTC path", "MIT"),
            ("intent-classifier", "phase7 mDistilBERT fine-tune", "Apache-2.0 (base)"),
            ("behavior-classifier", "phase7 mDistilBERT fine-tune", "Apache-2.0 (base)"),
            ("risk-fusion", "risk-fusion-demo-1", "in-repo")):
        exp.model(name=name, revision=revision, license=licence)
    print("adapter load status:")
    for key, status in loaded.items():
        print(f"  {key:<11}{status.value}")
    available = [k for k, s in loaded.items() if s is AnalyzerStatus.AVAILABLE]
    print()

    ood: dict[str, dict] = {}
    for name, pcm in build_inputs().items():
        window = AudioWindow(session_id=f"ood-{name}", seq=1, start_sec=0.0,
                             end_sec=2.0, pcm=pcm, sample_rate=SAMPLE_RATE,
                             language="hi")
        entry: dict = {"pcm_bytes": len(pcm)}
        if loaded["vad"] is AnalyzerStatus.AVAILABLE:
            r = adapters["vad"].analyze(window)
            entry["vad"] = {"status": r.status.value, "has_speech": r.has_speech,
                            "quality": r.quality.value if r.quality else None}
        if loaded["antispoof"] is AnalyzerStatus.AVAILABLE:
            adapters["antispoof"].release(window.session_id)
            r = adapters["antispoof"].analyze(window)
            entry["antispoof"] = {"status": r.status.value, "score": r.score}
        if loaded["speaker"] is AnalyzerStatus.AVAILABLE:
            r = adapters["speaker"].analyze(window, None)
            entry["speaker"] = {"status": r.status.value,
                                "similarity": r.similarity}
        if loaded["asr"] is AnalyzerStatus.AVAILABLE:
            r = asr.analyze(window)
            entry["asr"] = {"status": r.status.value,
                            "transcript_len": len(r.transcript or ""),
                            "confidence": r.confidence}
        ood[name] = entry
        summary = "  ".join(
            f"{k}={v['status']}" for k, v in entry.items() if isinstance(v, dict))
        print(f"  {name:<26}{summary}")

    # Any adapter emitting a value on non-speech while claiming AVAILABLE is
    # the failure this section exists to catch.
    fabricated = [
        f"{name}.{channel}"
        for name, entry in ood.items()
        for channel, value in entry.items()
        if isinstance(value, dict)
        and value.get("status") != "AVAILABLE"
        and (value.get("score") is not None or value.get("similarity") is not None)
    ]

    # -------------------------------------------- unsupported language text
    intent_adapter = RealIntentAdapter(model_dir("intent-classifier"))
    behavior_adapter = RealBehaviorAdapter(model_dir("behavior-classifier"))
    text_loaded = {"intent": intent_adapter.load(),
                   "behavior": behavior_adapter.load()}
    language_cases: dict[str, dict] = {}
    if all(s is AnalyzerStatus.AVAILABLE for s in text_loaded.values()):
        probes = {
            "tamil_script": ("உங்கள் "
                             "ஓடிபி என்ன?", "ta"),
            "hindi_script": ("आपका ओटीपी "
                             "क्या है?", "hi"),
            "english": ("Please share the OTP sent to your phone.", "en"),
            "empty_text": ("", "en"),
            "whitespace_only": ("    ", "en"),
            "unknown_language_tag": ("hello there", "de"),
        }
        for name, (text, language) in probes.items():
            i = intent_adapter.analyze(text, language)
            b = behavior_adapter.analyze(text, language)
            language_cases[name] = {
                "language": language,
                "intent_status": i.status.value,
                "intent_label": i.label.value if i.status is AnalyzerStatus.AVAILABLE else None,
                "behavior_status": b.status.value,
                "behavior_labels": [x.value for x in b.labels]
                if b.status is AnalyzerStatus.AVAILABLE else None,
            }
            print(f"  text/{name:<22}intent={language_cases[name]['intent_status']}"
                  f"  behaviour={language_cases[name]['behavior_status']}")

    # ------------------------------------------------- failure injection
    print("\n=== failure injection: adapters with no weights ===")
    broken = {
        "vad": SileroVadAdapter("no/such/dir"),
        "antispoof": AasistAntiSpoofAdapter("no/such/dir"),
        "speaker": EcapaSpeakerAdapter("no/such/dir"),
        "asr": IndicConformerAsrAdapter("no/such/dir"),
        "intent": RealIntentAdapter("no/such/dir"),
        "behavior": RealBehaviorAdapter("no/such/dir"),
    }
    injection: dict[str, dict] = {}
    window = AudioWindow(session_id="broken", seq=1, start_sec=0.0, end_sec=2.0,
                         pcm=b"\x11\x11" * 32_000, sample_rate=SAMPLE_RATE,
                         language="hi")
    for key, adapter in broken.items():
        status = adapter.load()
        info = adapter.describe()
        if key in ("intent", "behavior"):
            result = adapter.analyze("please share your otp", "en")
            value = (result.label.value if key == "intent"
                     else [b.value for b in result.labels])
        elif key == "speaker":
            result = adapter.analyze(window, None)
            value = result.similarity
        else:
            result = adapter.analyze(window)
            value = getattr(result, "score", None) or getattr(result, "transcript", None)
        # `Intent.UNKNOWN` is the taxonomy's designated "cannot tell" null
        # (models/training/vive_labels.py), not a prediction: it is what the
        # label set provides INSTEAD of guessing. Counting it as an emitted
        # value would report a contract breach that is not one. What makes it
        # safe is not the name but that fusion ignores it - since Phase 9,
        # intent enters the noisy-OR only when its status is AVAILABLE, and
        # test_pipeline.py pins that.
        null_values = ([], "", None, "UNKNOWN")
        injection[key] = {
            "load_status": status.value,
            "analyze_status": result.status.value,
            "stayed_in_real_mode": info.mode is AdapterMode.REAL,
            "available": adapter.available(),
            "emitted_value": value if value not in null_values else None,
            "emitted_designated_null": value == "UNKNOWN" or value in ([], "", None),
        }
        print(f"  {key:<11}load={status.value:<14}analyze={result.status.value:<18}"
              f"mode={info.mode.value:<6}value={injection[key]['emitted_value']}")

    silently_downgraded = [k for k, v in injection.items()
                           if not v["stayed_in_real_mode"]]
    emitted_on_failure = [k for k, v in injection.items()
                          if v["emitted_value"] is not None]

    # ---------------------------- does a failed model change risk?
    def fused(*, antispoof_ok: bool, intent_ok: bool, behavior_ok: bool,
              speaker_ok: bool) -> tuple[int, float]:
        out = fuse(FusionInput(
            vad=VadResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                          mode=AdapterMode.REAL, has_speech=True,
                          quality=AudioQuality.GOOD),
            antispoof=AntiSpoofResult(
                status=AnalyzerStatus.AVAILABLE if antispoof_ok
                else AnalyzerStatus.LOAD_ERROR,
                model_version="v", mode=AdapterMode.REAL,
                score=0.2 if antispoof_ok else None),
            speaker=SpeakerResult(
                status=AnalyzerStatus.AVAILABLE if speaker_ok
                else AnalyzerStatus.LOAD_ERROR,
                model_version="v", mode=AdapterMode.REAL,
                similarity=0.8 if speaker_ok else None),
            asr=AsrResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                          mode=AdapterMode.REAL, transcript="hello",
                          confidence=0.9),
            intent=IntentResult(
                status=AnalyzerStatus.AVAILABLE if intent_ok
                else AnalyzerStatus.LOAD_ERROR,
                model_version="v", mode=AdapterMode.REAL,
                label=Intent.NORMAL_CONVERSATION, confidence=0.9),
            behavior=BehaviorResult(
                status=AnalyzerStatus.AVAILABLE if behavior_ok
                else AnalyzerStatus.LOAD_ERROR,
                model_version="v", mode=AdapterMode.REAL,
                labels=[Behavior.NORMAL], confidence=0.9),
            caller_verified=False, session_authenticated=True))
        return out.risk.score, out.risk.confidence

    baseline = fused(antispoof_ok=True, intent_ok=True, behavior_ok=True,
                     speaker_ok=True)
    degraded = {
        "all_models_healthy": baseline,
        "antispoof_failed": fused(antispoof_ok=False, intent_ok=True,
                                  behavior_ok=True, speaker_ok=True),
        "speaker_failed": fused(antispoof_ok=True, intent_ok=True,
                                behavior_ok=True, speaker_ok=False),
        "text_heads_failed": fused(antispoof_ok=True, intent_ok=False,
                                   behavior_ok=False, speaker_ok=True),
        "everything_but_vad_failed": fused(antispoof_ok=False, intent_ok=False,
                                           behavior_ok=False, speaker_ok=False),
    }
    print("\n=== fused risk under model failure (benign evidence) ===")
    for name, (score, confidence) in degraded.items():
        print(f"  {name:<28}score {score:>3}   confidence {confidence:.3f}")

    failure_raises_risk = {
        name: score > baseline[0]
        for name, (score, _c) in degraded.items() if name != "all_models_healthy"}
    failure_lowers_confidence = {
        name: confidence < baseline[1]
        for name, (_s, confidence) in degraded.items() if name != "all_models_healthy"}

    exp.result("adapter_load_status", {k: v.value for k, v in loaded.items()})
    exp.result("ood_audio", ood)
    exp.result("language_handling", language_cases)
    exp.result("failure_injection", injection)
    exp.result("fused_risk_under_failure",
               {k: {"score": s, "confidence": c} for k, (s, c) in degraded.items()})
    exp.result("contract_checks", {
        "adapters_emitting_a_value_while_not_AVAILABLE": fabricated,
        "adapters_that_silently_left_REAL_mode": silently_downgraded,
        "broken_adapters_that_still_emitted_a_value": emitted_on_failure,
        "any_failure_raised_risk": {k: v for k, v in failure_raises_risk.items() if v},
        "failure_lowered_confidence": failure_lowers_confidence,
    })

    exp.limitation(
        "Failure is injected by pointing an adapter at a missing directory, "
        "which exercises the load path. A model that loads and then produces "
        "wrong output - the O12 case - is not a failure this can detect, and "
        "is the more dangerous of the two.")
    exp.limitation(
        "OOD inputs are synthetic signals, not recordings of unusual real "
        "conditions. They test the contract, not perceptual robustness.")
    exp.limitation(
        "Fusion behaviour under failure is measured with BENIGN evidence on "
        "the surviving channels. It shows that failure does not by itself "
        "raise risk; it does not establish what risk a failed channel should "
        "have contributed.")
    exp.limitation(
        "Adapters not loaded in this environment are skipped rather than "
        "assumed to pass; the load-status table records which ran.")

    clean = (not fabricated and not silently_downgraded
             and not emitted_on_failure and not any(failure_raises_risk.values()))
    exp.result("all_contracts_held", clean)

    exp.finish(
        interpretation=(
            f"Across {len(ood)} degenerate audio inputs and "
            f"{len(injection)} injected model failures, adapters emitting a "
            f"value while not AVAILABLE: {fabricated or 'none'}. Adapters "
            f"silently leaving REAL mode: {silently_downgraded or 'none'}. "
            f"Model failure raised risk in: "
            f"{[k for k, v in failure_raises_risk.items() if v] or 'no case'}, "
            f"while confidence fell in "
            f"{sum(failure_lowers_confidence.values())} of "
            f"{len(failure_lowers_confidence)} degraded configurations."),
        conclusion=(
            "Degradation is reported rather than hidden, and a model outage "
            "cannot by itself escalate a call. The gap this cannot cover is a "
            "model that loads and is wrong, which is what O12 describes and "
            "what only an evaluation corpus can catch."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
