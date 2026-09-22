"""Phase 9: how far does ASR accuracy fall under call-like conditions?

The gap this closes
-------------------
VIVE's only ASR numbers are FLEURS WER 0.1164 (Hindi) and 0.2833 (Tamil).
FLEURS is clean read speech recorded on good microphones. VIVE's stated purpose
is analysing phone calls, which are band-limited, codec-compressed, noisy and
often short. The FLEURS figure is therefore a ceiling, and the honest question
is not "what is VIVE's accuracy" but "how much of that ceiling survives".

Nothing here converts a FLEURS number into a telephone number. Each condition
is a controlled perturbation of the SAME utterances, so every row is a
degradation measured against its own clean baseline on identical content.
Simulated degradation is not a recording from a real network, and the
difference matters: a real call also carries packet loss, echo cancellation,
automatic gain control and an unknown handset. Those are not modelled.

Conditions
----------
  clean                 baseline, unmodified FLEURS
  snr20 / snr10 / snr5  additive white Gaussian noise at a measured SNR
  telephony_band        300-3400 Hz band-pass, the classic PSTN passband
  g711_ulaw             G.711 mu-law encode/decode round trip (8 bit)
  narrowband_8k         16k -> 8k -> 16k resample, the narrowband call path
  reverb                synthetic exponential-decay room impulse response
  quiet_-20dB           gain reduction, a distant or badly held handset
  clipped               hard clipping at 0.3, an overdriven input
  window_2s             first 2.0 s only - VIVE's actual analysis window

`window_2s` is the one condition that is not a channel effect. It measures
what the packet pipeline actually sees, because VIVE never hands the model a
full utterance: it decodes a 2 s window every 1 s.

Runs through the real `IndicConformerAsrAdapter`, not a bare ONNX session, so
what is measured is the path that serves packets.

Usage:
    python scripts/evaluation/exp_asr_robustness.py [--clips 40]
"""

from __future__ import annotations

import argparse
import io
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..",
    "models", "training"))

from _harness import ROOT, Experiment, add_backend_to_path, model_dir  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from asr_text import NORMALISATION_STEPS, normalise  # noqa: E402

SAMPLE_RATE = 16_000
LANGS = {"hi": "hi_in", "ta": "ta_in"}
WINDOW_SEC = 2.0


# -- perturbations ---------------------------------------------------------
# Each takes and returns float32 at 16 kHz. None resamples the OUTPUT: even
# `narrowband_8k` returns to 16 kHz, because the adapter's contract is 16 kHz
# and changing the rate would measure a contract violation rather than a
# channel effect.

def _rms(x):
    import numpy as np
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def add_noise(x, snr_db: float):
    import numpy as np
    rng = np.random.default_rng(20260922)
    noise = rng.standard_normal(x.size).astype("float32")
    noise *= _rms(x) / (_rms(noise) * (10 ** (snr_db / 20.0)))
    return np.clip(x + noise, -1.0, 1.0).astype("float32")


def band_pass(x, lo: float, hi: float):
    """FFT brick-wall band-pass. Sharper than a real filter, so this is a
    slightly pessimistic stand-in for a handset's gentler roll-off."""
    import numpy as np
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / SAMPLE_RATE)
    spectrum[(freqs < lo) | (freqs > hi)] = 0
    return np.fft.irfft(spectrum, n=x.size).astype("float32")


def ulaw_roundtrip(x):
    """G.711 mu-law: 16-bit linear to 8-bit log and back. Lossy by design."""
    import numpy as np
    mu = 255.0
    x = np.clip(x, -1.0, 1.0)
    encoded = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    quantised = np.round((encoded + 1.0) * 127.5) / 127.5 - 1.0
    decoded = np.sign(quantised) * ((1 + mu) ** np.abs(quantised) - 1) / mu
    return decoded.astype("float32")


def narrowband(x):
    """16k -> 8k -> 16k. Everything above 4 kHz is gone for good."""
    import numpy as np
    from scipy.signal import resample_poly
    down = resample_poly(x, 1, 2)
    return np.asarray(resample_poly(down, 2, 1)[:x.size], dtype="float32")


def reverb(x, rt60: float = 0.35):
    """Convolution with a synthetic exponential-decay impulse response.

    A real room response has early reflections and a non-flat spectrum; this
    has neither, so it models smearing rather than a specific room.
    """
    import numpy as np
    rng = np.random.default_rng(7)
    length = int(rt60 * SAMPLE_RATE)
    envelope = np.exp(-6.9 * np.arange(length) / length)
    impulse = (rng.standard_normal(length) * envelope).astype("float32")
    impulse[0] = 1.0
    wet = np.convolve(x, impulse)[:x.size]
    return np.clip(wet / (np.max(np.abs(wet)) + 1e-9) * np.max(np.abs(x)),
                   -1.0, 1.0).astype("float32")


def gain(x, db: float):
    import numpy as np
    return np.clip(x * (10 ** (db / 20.0)), -1.0, 1.0).astype("float32")


def clip_hard(x, ceiling: float = 0.3):
    import numpy as np
    return np.clip(x, -ceiling, ceiling).astype("float32")


def first_window(x):
    return x[:int(WINDOW_SEC * SAMPLE_RATE)]


CONDITIONS = {
    "clean": lambda x: x,
    "snr20": lambda x: add_noise(x, 20),
    "snr10": lambda x: add_noise(x, 10),
    "snr5": lambda x: add_noise(x, 5),
    "telephony_band": lambda x: band_pass(x, 300.0, 3400.0),
    "g711_ulaw": ulaw_roundtrip,
    "narrowband_8k": narrowband,
    "reverb": reverb,
    "quiet_-20dB": lambda x: gain(x, -20.0),
    "clipped": clip_hard,
    "window_2s": first_window,
}


def fleurs_clips(config: str, count: int):
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    out = []
    for row in ds:
        reference = normalise(row.get("transcription") or "")
        if not reference:
            continue
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE:
            continue
        out.append((np.asarray(wave, dtype="float32"), reference))
        if len(out) >= count:
            break
    return out


def to_pcm(samples) -> bytes:
    import numpy as np
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=40)
    args = parser.parse_args()

    add_backend_to_path()
    import jiwer

    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.asr_conformer import IndicConformerAsrAdapter
    from app.schemas.models import AnalyzerStatus

    exp = Experiment(
        "9C_asr_robustness",
        question=("How much of the clean-speech ASR accuracy survives "
                  "call-like channel degradation, and what does VIVE's actual "
                  "2 s analysis window cost relative to a full utterance?"),
        hypothesis=("Band-limiting and codec compression will cost less than "
                    "additive noise, and the 2 s window will be the single "
                    "largest degradation because it truncates mid-sentence "
                    "and removes the context CTC relies on."),
        method=("Decode the same FLEURS utterances through the real VIVE ASR "
                "adapter under each perturbation. All outputs stay at 16 kHz. "
                "WER and CER use the same normaliser as every earlier VIVE "
                "ASR measurement, so rows are comparable to the Phase 7 "
                "baseline."))

    adapter = IndicConformerAsrAdapter(
        model_dir("_pretrained", "indic-conformer-ctc"), prefer_gpu=False)
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        print(f"ASR adapter unavailable: {adapter.describe().detail}")
        return 1
    print(f"adapter: {adapter.describe().model_version} "
          f"({adapter.describe().execution_provider})\n")

    exp.model(name="indic-conformer-600m", revision="ai4bharat CTC path",
              license="MIT", execution_provider=adapter.describe().execution_provider)
    exp.config(conditions=sorted(CONDITIONS), normalisation=NORMALISATION_STEPS,
               clips_per_language=args.clips, window_sec=WINDOW_SEC,
               output_sample_rate=SAMPLE_RATE)

    results: dict[str, dict] = {}
    for lang, config in LANGS.items():
        print(f"=== {lang} ({config}) ===")
        clips = fleurs_clips(config, args.clips)
        exp.dataset(name=f"google/fleurs {config}", source="HuggingFace",
                    license="CC-BY-4.0", split="test", samples=len(clips),
                    language=lang)
        results[lang] = {}
        for name, transform in CONDITIONS.items():
            refs, hyps, failures, latencies = [], [], 0, []
            for index, (wave, reference) in enumerate(clips):
                audio = transform(wave)
                window = AudioWindow(
                    session_id=f"rob-{lang}-{name}", seq=index,
                    start_sec=0.0, end_sec=audio.size / SAMPLE_RATE,
                    pcm=to_pcm(audio), sample_rate=SAMPLE_RATE, language=lang)
                began = time.perf_counter()
                result = adapter.analyze(window)
                latencies.append((time.perf_counter() - began) * 1000)
                if result.status is not AnalyzerStatus.AVAILABLE:
                    failures += 1
                    continue
                refs.append(reference)
                hyps.append(normalise(result.transcript or ""))

            if not refs:
                results[lang][name] = {"error": "no successful decodes",
                                       "failures": failures}
                print(f"  {name:<16} no successful decodes ({failures} failures)")
                continue

            # window_2s is scored against the FULL reference on purpose: the
            # pipeline has no per-window ground truth, and this states the
            # cost of the window rather than pretending a 2 s clip should
            # transcribe a 12 s sentence. Flagged in the record.
            wer = float(jiwer.wer(refs, hyps))
            cer = float(jiwer.cer(refs, hyps))
            empty = sum(1 for h in hyps if not h.strip())
            entry = {
                "wer": round(wer, 4), "cer": round(cer, 4),
                "utterances": len(refs), "decode_failures": failures,
                "empty_hypotheses": empty,
                "median_latency_ms": round(statistics.median(latencies), 1),
                "reference_is_full_utterance": name == "window_2s",
            }
            base = results[lang].get("clean")
            if base and name != "clean":
                entry["wer_delta_vs_clean"] = round(wer - base["wer"], 4)
                entry["wer_ratio_vs_clean"] = round(
                    wer / base["wer"], 3) if base["wer"] else None
            results[lang][name] = entry
            note = " (vs full reference)" if name == "window_2s" else ""
            print(f"  {name:<16} WER {wer:.4f}  CER {cer:.4f}  "
                  f"n={len(refs)}  empty={empty}  "
                  f"{entry['median_latency_ms']:.0f}ms{note}")
        print()

    exp.result("per_language_per_condition", results)

    exp.limitation(
        "All degradations are SIMULATED. A real call additionally carries "
        "packet loss, jitter concealment, echo cancellation, automatic gain "
        "control and an unknown handset response. None are modelled, so these "
        "rows are a lower bound on real-world degradation, not a telephone WER.")
    exp.limitation(
        f"{args.clips} utterances per language per condition. Differences "
        "smaller than a few points should not be read as real.")
    exp.limitation(
        "The `window_2s` row scores a 2 s decode against the FULL utterance "
        "reference, because no per-window ground truth exists. Its WER is "
        "therefore dominated by deletions and is NOT comparable to the other "
        "rows as an accuracy figure - it states the cost of windowing.")
    exp.limitation(
        "FLEURS speakers read prepared text. Spontaneous conversational "
        "speech - disfluency, overlap, code-switching - is not represented "
        "and is expected to be harder.")
    exp.limitation(
        "Noise is white Gaussian. Real call noise is non-stationary: traffic, "
        "babble, music on hold. White noise is the easy case.")
    exp.limitation(
        "`median_latency_ms` here is incidental, not a benchmark: this run may "
        "share the machine with other work. The authoritative latency figures "
        "come from the dedicated runtime experiment, which controls for that. "
        "A Phase 7 RTF probe was already invalidated once by exactly this "
        "contention, so these numbers are recorded but not quoted.")

    rows = {f"{lang}/{cond}": entry.get("wer")
            for lang, conds in results.items() for cond, entry in conds.items()}
    worst = max(((k, v) for k, v in rows.items()
                 if v is not None and not k.endswith("window_2s")),
                key=lambda kv: kv[1], default=(None, None))

    exp.finish(
        interpretation=(
            f"Clean FLEURS accuracy does not transfer unchanged to call-like "
            f"audio. The harshest channel condition measured was {worst[0]} at "
            f"WER {worst[1]}. The per-condition deltas identify which parts of "
            f"a call path cost the most, which is what a deployment decision "
            f"needs; they do not produce a telephone-call accuracy figure and "
            f"none may be quoted as one."),
        conclusion=(
            "Report ASR accuracy as a range across measured conditions with "
            "the condition named, never as a single number. The clean FLEURS "
            "WER stays the upper bound and must keep its 'clean read speech' "
            "label wherever it appears."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
