"""Measures per-window latency and memory for each ASR candidate.

The comparison table's "cost per 2 s window" was extrapolated as RTF x 2.0 from
FLEURS utterances averaging ~12 s. That extrapolation is unsafe, because the
candidates do not scale linearly with input length:

  * Whisper pads EVERY input to 30 s of mel frames, so a 2 s window costs
    essentially what a 30 s one costs. Its effective RTF on short windows is
    far worse than on 12 s utterances.
  * CTC models process only the frames given, so they do scale roughly with
    input length, but fixed per-call overhead still dominates at 2 s.

VIVE feeds a 2.0 s window every 1.0 s, so the 2 s figure is the one that
decides streaming suitability. This script measures it directly on synthetic
2 s audio rather than inferring it, and records peak VRAM and process RSS for
each model - values the evaluation runs did not capture.

Synthetic audio is used deliberately: this measures COST, not accuracy, and a
fixed input keeps the comparison identical across models.

Usage:
    python scripts/training/measure_asr_window.py
    python scripts/training/measure_asr_window.py --only conformer
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import sys
import time
from datetime import date

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")
ART = os.path.join(ROOT, "models", "artifacts", "_pretrained")

sys.path.insert(0, os.path.join(ROOT, "scripts", "training"))

WINDOW_SEC = 2.0
CADENCE_BUDGET_SEC = 1.0
SAMPLE_RATE = 16_000
WARMUP = 2
RUNS = 10


def synthetic_window() -> np.ndarray:
    """A fixed 2 s speech-like signal. Identical for every candidate."""
    rng = np.random.default_rng(20260921)
    t = np.linspace(0, WINDOW_SEC, int(SAMPLE_RATE * WINDOW_SEC), endpoint=False)
    signal = np.zeros_like(t)
    for f in (120, 240, 360, 480):          # rough voiced harmonics
        signal += np.sin(2 * np.pi * f * t) / f * 40
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))   # syllable-rate envelope
    signal = signal * envelope + 0.005 * rng.standard_normal(t.shape)
    peak = float(np.abs(signal).max()) or 1.0
    return (0.5 * signal / peak).astype(np.float32)


def rss_gb() -> float:
    import psutil
    return round(psutil.Process().memory_info().rss / 1e9, 3)


def timed(fn, runs: int = RUNS, warmup: int = WARMUP) -> dict:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        began = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - began)
    samples.sort()
    return {
        "runs": runs,
        "mean_sec": round(sum(samples) / len(samples), 4),
        "median_sec": round(samples[len(samples) // 2], 4),
        "min_sec": round(samples[0], 4),
        "max_sec": round(samples[-1], 4),
    }


def finish(name: str, stats: dict, extra: dict) -> dict:
    cost = stats["median_sec"]
    record = {
        "model": name,
        "window_sec": WINDOW_SEC,
        "cadence_budget_sec": CADENCE_BUDGET_SEC,
        "latency": stats,
        "cost_per_window_sec": cost,
        "effective_rtf_at_2s": round(cost / WINDOW_SEC, 4),
        "meets_cadence": cost < CADENCE_BUDGET_SEC,
        "budget_utilisation_pct": round(100 * cost / CADENCE_BUDGET_SEC, 1),
        **extra,
    }
    verdict = "FITS" if record["meets_cadence"] else "OVER BUDGET"
    print(f"  median {cost:.4f}s per 2s window  "
          f"({record['budget_utilisation_pct']}% of budget)  -> {verdict}")
    print(f"  effective RTF at 2s input: {record['effective_rtf_at_2s']}")
    print(f"  peak VRAM {record.get('peak_vram_gb')} GB   RSS {record.get('rss_gb')} GB")
    return record


def measure_wav2vec(wave: np.ndarray) -> dict:
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    print("\n=== IndicWav2Vec Hindi (wav2vec2 CTC, PyTorch CUDA) ===")
    d = os.path.join(ART, "indicwav2vec-hindi")
    base_rss = rss_gb()
    torch.cuda.reset_peak_memory_stats() if torch.cuda.is_available() else None
    proc = Wav2Vec2Processor.from_pretrained(d)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = Wav2Vec2ForCTC.from_pretrained(d).to(device).eval()

    def run():
        x = proc(wave, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            logits = model(x.input_values.to(device)).logits
        proc.batch_decode(torch.argmax(logits, dim=-1))
        if device == "cuda":
            torch.cuda.synchronize()

    stats = timed(run)
    rec = finish("IndicWav2Vec Hindi", stats, {
        "model_id": "ai4bharat/indicwav2vec-hindi",
        "execution": f"PyTorch {device.upper()} fp32",
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3)
        if torch.cuda.is_available() else 0.0,
        "rss_gb": rss_gb(), "rss_delta_gb": round(rss_gb() - base_rss, 3),
        "pads_input": False,
    })
    del model, proc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return rec


def measure_whisper(wave: np.ndarray) -> dict:
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    print("\n=== Whisper large-v3-turbo (autoregressive, PyTorch CUDA fp16) ===")
    d = os.path.join(ART, "whisper-large-v3-turbo")
    base_rss = rss_gb()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    proc = WhisperProcessor.from_pretrained(d)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = (WhisperForConditionalGeneration.from_pretrained(d, torch_dtype=dtype)
             .to(device).eval())

    # Confirm the padding behaviour rather than asserting it from the docs.
    feats = proc(wave, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
    padded_frames = int(feats.shape[-1])
    print(f"  2s input -> mel frames: {padded_frames} "
          f"({padded_frames * 0.01:.0f}s equivalent) - input is padded")

    def run():
        x = proc(wave, sampling_rate=SAMPLE_RATE,
                 return_tensors="pt").input_features.to(device, dtype)
        with torch.no_grad():
            model.generate(x, language="hindi", task="transcribe", max_new_tokens=220)
        if device == "cuda":
            torch.cuda.synchronize()

    stats = timed(run)
    rec = finish("Whisper large-v3-turbo", stats, {
        "model_id": "openai/whisper-large-v3-turbo",
        "execution": f"PyTorch {device.upper()} fp16",
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3)
        if torch.cuda.is_available() else 0.0,
        "rss_gb": rss_gb(), "rss_delta_gb": round(rss_gb() - base_rss, 3),
        "pads_input": True,
        "mel_frames_for_2s_input": padded_frames,
        "padding_note": ("Whisper pads every input to a fixed 30 s window, so a "
                         "2 s VIVE window costs what a 30 s clip costs. This is "
                         "why its per-window cost is far worse than its "
                         "utterance-level RTF suggests."),
    })
    del model, proc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return rec


def measure_conformer(wave: np.ndarray) -> dict:
    import torch
    from eval_asr_conformer import ConformerCTC
    print("\n=== IndicConformer-600M CTC (ONNX Runtime) ===")
    d = os.path.join(ART, "indic-conformer-ctc")
    base_rss = rss_gb()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    model = ConformerCTC(d, prefer_gpu=False)
    gpu = any("CUDA" in p for p in model.providers_active)
    print(f"  providers active: {model.providers_active}  -> "
          f"{'GPU' if gpu else 'CPU ONLY'}")

    stats = timed(lambda: model.transcribe(wave, "hi"))
    rec = finish("IndicConformer-600M CTC", stats, {
        "model_id": "ai4bharat/indic-conformer-600m-multilingual",
        "execution": f"ONNX Runtime {'GPU' if gpu else 'CPU only'}",
        "providers_active": model.providers_active,
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3)
        if torch.cuda.is_available() else 0.0,
        "rss_gb": rss_gb(), "rss_delta_gb": round(rss_gb() - base_rss, 3),
        "pads_input": False,
    })
    del model
    gc.collect()
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["wav2vec", "whisper", "conformer"])
    args = parser.parse_args()

    wave = synthetic_window()
    print(f"fixed synthetic window: {WINDOW_SEC}s @ {SAMPLE_RATE} Hz "
          f"({len(wave):,} samples), identical for every candidate")
    print(f"budget: {CADENCE_BUDGET_SEC}s per window "
          f"({WARMUP} warmup + {RUNS} timed runs, median reported)")

    plan = [("wav2vec", measure_wav2vec), ("whisper", measure_whisper),
            ("conformer", measure_conformer)]
    results = []
    for key, fn in plan:
        if args.only and key != args.only:
            continue
        try:
            results.append(fn(wave))
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            results.append({"model": key, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    import torch
    record = {
        "measured_at": str(date.today()),
        "window_sec": WINDOW_SEC,
        "cadence_budget_sec": CADENCE_BUDGET_SEC,
        "method": (f"Fixed synthetic 2 s window, {WARMUP} warmup + {RUNS} timed "
                   f"runs, median reported. Measures COST not accuracy."),
        "environment": {
            "python": platform.python_version(), "torch": torch.__version__,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
            "total_vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
            if torch.cuda.is_available() else None,
            "platform": platform.platform(),
        },
        "results": results,
        "caveat": ("Latency only. Accuracy comes from the FLEURS evaluations. "
                   "The superseded preliminary probe measured 1.3912 RTF for "
                   "the conformer while another job held the machine and must "
                   "not be quoted."),
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "asr_window_latency.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
