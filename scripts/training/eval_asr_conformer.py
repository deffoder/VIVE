"""Evaluates AI4Bharat IndicConformer-600M via its CTC path.

Phase 7 ASR comparison. The official `model_onnx.py` constructs every component
at load time - the RNNT decoder, the joint networks and all 22 language heads -
even when only CTC decoding is used. This module loads the CTC path alone, so
the download and the resident footprint cover what VIVE would actually run.

Decoding follows the upstream `_ctc_decode` exactly: language-masked logits,
log-softmax, greedy argmax, collapse repeats, drop blanks, map through the
per-language vocabulary. No reimplementation of the algorithm beyond restricting
which components are instantiated.

Streaming relevance: VIVE analyses a 2.0 s window every 1.0 s, so a window must
cost under ~1.0 s of wall clock for the whole pipeline, of which ASR is one
stage. `--bench` reports per-stage latency and the real-time factor on this
machine, and states which ONNX execution provider actually served the run
rather than which one was requested.

Usage:
    python scripts/training/eval_asr_conformer.py --model-dir <dir> --bench
    python scripts/training/eval_asr_conformer.py --model-dir <dir> --lang ta --limit 0
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

sys.path.insert(0, os.path.join(ROOT, "models", "training"))

from asr_text import NORMALISATION_STEPS, normalise  # noqa: E402

DATASET = "google/fleurs"
DATASET_LICENSE = "CC-BY-4.0"
MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"

LANGS = {
    "ta": {"fleurs": "ta_in", "script": (0x0B80, 0x0BFF)},
    "hi": {"fleurs": "hi_in", "script": (0x0900, 0x097F)},
}


class ConformerCTC:
    """CTC-only IndicConformer. Loads 2 graphs instead of 28."""

    def __init__(self, model_dir: str, prefer_gpu: bool = True):
        import onnxruntime as ort
        import torch

        self.torch = torch
        assets = os.path.join(model_dir, "assets")
        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
        self.blank_id = cfg["BLANK_ID"]

        # The preprocessor is TorchScript, so it can use CUDA even when
        # onnxruntime cannot. Recorded separately because it makes the run
        # genuinely hybrid rather than purely CPU.
        self.device = torch.device(
            "cuda" if (prefer_gpu and torch.cuda.is_available()) else "cpu")
        self.preprocessor = torch.jit.load(
            os.path.join(assets, "preprocessor.ts"), map_location=self.device)

        available = ort.get_available_providers()
        wanted = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                  if p in available] or ["CPUExecutionProvider"]
        if not prefer_gpu:
            wanted = ["CPUExecutionProvider"]

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.encoder = ort.InferenceSession(
            os.path.join(assets, "encoder.onnx"), opts, providers=wanted)
        self.ctc = ort.InferenceSession(
            os.path.join(assets, "ctc_decoder.onnx"), opts, providers=wanted)

        # What actually served the graph, not what was requested.
        self.providers_available = available
        self.providers_requested = wanted
        self.providers_active = self.encoder.get_providers()

        with open(os.path.join(assets, "vocab.json"), encoding="utf-8") as handle:
            self.vocab = json.load(handle)
        with open(os.path.join(assets, "language_masks.json"), encoding="utf-8") as handle:
            self.masks = json.load(handle)

        self.timing = {"preprocess": 0.0, "encode": 0.0, "decode": 0.0}

    def transcribe(self, wave, lang: str) -> str:
        torch = self.torch
        tensor = torch.as_tensor(wave, dtype=torch.float32).reshape(1, -1)

        began = time.perf_counter()
        signal, length = self.preprocessor(
            input_signal=tensor.to(self.device),
            length=torch.tensor([tensor.shape[-1]]).to(self.device))
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        self.timing["preprocess"] += time.perf_counter() - began

        began = time.perf_counter()
        outputs, _lengths = self.encoder.run(
            ["outputs", "encoded_lengths"],
            {"audio_signal": signal.cpu().numpy(), "length": length.cpu().numpy()})
        self.timing["encode"] += time.perf_counter() - began

        began = time.perf_counter()
        logprobs = self.ctc.run(["logprobs"], {"encoder_output": outputs})[0]
        logprobs = torch.from_numpy(logprobs[:, :, self.masks[lang]]).log_softmax(dim=-1)
        indices = torch.argmax(logprobs[0], dim=-1)
        collapsed = torch.unique_consecutive(indices, dim=-1)
        text = "".join(self.vocab[lang][i] for i in collapsed
                       if i != self.blank_id).replace("▁", " ").strip()
        self.timing["decode"] += time.perf_counter() - began
        return text


def rss_gb() -> float | None:
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e9, 3)
    except Exception:
        return None


def script_ratio(text: str, lo: int, hi: int) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters)


def load_stream(config: str):
    from datasets import Audio, load_dataset
    stream = load_dataset(DATASET, config, split="test", streaming=True)
    return stream.cast_column("audio", Audio(decode=False))


def read_audio(sample):
    import numpy as np
    import soundfile as sf
    audio = sample["audio"]
    raw = audio.get("bytes")
    if raw is None:
        with open(audio["path"], "rb") as handle:
            raw = handle.read()
    wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    return np.asarray(wave, dtype=np.float32), rate


def bench(model: ConformerCTC, lang: str, n: int) -> dict:
    """Latency on real audio, reported against VIVE's 1.0 s cadence."""
    import torch
    spec = LANGS[lang]
    stream = load_stream(spec["fleurs"])
    per_utt = []
    audio_total = 0.0
    model.timing = {k: 0.0 for k in model.timing}

    for index, sample in enumerate(stream):
        if index >= n:
            break
        wave, rate = read_audio(sample)
        began = time.perf_counter()
        model.transcribe(wave, lang)
        elapsed = time.perf_counter() - began
        per_utt.append({"audio_sec": round(len(wave) / rate, 3),
                        "wall_sec": round(elapsed, 4),
                        "rtf": round(elapsed / (len(wave) / rate), 4)})
        audio_total += len(wave) / rate

    wall_total = sum(u["wall_sec"] for u in per_utt)
    # VIVE cadence: a 2.0 s window must complete inside 1.0 s.
    window_cost = 2.0 * (wall_total / audio_total) if audio_total else None
    return {
        "utterances": len(per_utt),
        "audio_seconds": round(audio_total, 2),
        "wall_seconds": round(wall_total, 2),
        "rtf": round(wall_total / audio_total, 4) if audio_total else None,
        "stage_seconds": {k: round(v, 3) for k, v in model.timing.items()},
        "stage_share_pct": {
            k: round(100 * v / wall_total, 1) for k, v in model.timing.items()
        } if wall_total else {},
        "projected_cost_per_2s_window_sec": round(window_cost, 4) if window_cost else None,
        "vive_cadence_budget_sec": 1.0,
        "meets_cadence": bool(window_cost and window_cost < 1.0),
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3)
        if torch.cuda.is_available() else None,
        "process_rss_gb": rss_gb(),
        "per_utterance": per_utt,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--lang", choices=sorted(LANGS))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--smoke", type=int, default=0,
                        help="decode N utterances and print them, no scoring")
    parser.add_argument("--bench", action="store_true")
    parser.add_argument("--bench-n", type=int, default=20)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    import jiwer
    import torch

    started = datetime.now(timezone.utc)
    load_began = time.perf_counter()
    model = ConformerCTC(args.model_dir, prefer_gpu=not args.cpu_only)
    load_seconds = round(time.perf_counter() - load_began, 2)

    print(f"model dir : {args.model_dir}")
    print(f"load      : {load_seconds}s")
    print(f"providers available : {model.providers_available}")
    print(f"providers requested : {model.providers_requested}")
    print(f"providers ACTIVE    : {model.providers_active}")
    print(f"preprocessor device : {model.device}")
    gpu_onnx = any("CUDA" in p or "Tensorrt" in p for p in model.providers_active)
    print(f"ONNX acceleration   : {'GPU' if gpu_onnx else 'CPU ONLY'}")
    print(f"process RSS         : {rss_gb()} GB")

    if args.bench:
        lang = args.lang or "hi"
        print(f"\nbenchmarking {args.bench_n} utterances [{lang}] ...")
        result = bench(model, lang, args.bench_n)
        result.update({
            "model_id": MODEL_ID, "decoding": "ctc", "language": lang,
            "load_seconds": load_seconds,
            "onnx_acceleration": "GPU" if gpu_onnx else "CPU_ONLY",
            "providers_available": model.providers_available,
            "providers_active": model.providers_active,
            "preprocessor_device": str(model.device),
            "environment": {
                "python": platform.python_version(), "torch": torch.__version__,
                "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
                "platform": platform.platform(),
            },
            "measured_at": started.isoformat(),
        })
        out = args.out or os.path.join(EVAL_DIR, f"asr_conformer_bench_{lang}.json")
        os.makedirs(EVAL_DIR, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
        print(f"  RTF                      = {result['rtf']}")
        print(f"  cost per 2s window       = {result['projected_cost_per_2s_window_sec']}s")
        print(f"  meets 1.0s VIVE cadence  = {result['meets_cadence']}")
        print(f"  stage share              = {result['stage_share_pct']}")
        print(f"  peak VRAM                = {result['peak_vram_gb']} GB")
        print(f"  process RSS              = {result['process_rss_gb']} GB")
        print(f"  report: {out}")
        return 0

    if not args.lang:
        parser.error("--lang is required unless --bench is used")
    spec = LANGS[args.lang]

    if args.smoke:
        print(f"\nsmoke test [{args.lang}] - {args.smoke} utterances, no scoring")
        for index, sample in enumerate(load_stream(spec["fleurs"])):
            if index >= args.smoke:
                break
            wave, _rate = read_audio(sample)
            hyp = model.transcribe(wave, args.lang)
            ref = sample.get("transcription") or ""
            print(f"\n  [{index+1}] REF: {normalise(ref)[:88]}")
            print(f"      HYP: {normalise(hyp)[:88]}")
        return 0

    references, hypotheses = [], []
    audio_seconds = decode_seconds = 0.0
    empty_refs = 0
    for index, sample in enumerate(load_stream(spec["fleurs"])):
        if args.limit and index >= args.limit:
            break
        wave, rate = read_audio(sample)
        reference = normalise(sample.get("transcription") or "")
        if not reference:
            empty_refs += 1
            continue
        began = time.perf_counter()
        hyp = model.transcribe(wave, args.lang)
        decode_seconds += time.perf_counter() - began
        audio_seconds += len(wave) / rate
        references.append(reference)
        hypotheses.append(normalise(hyp))
        if len(references) <= 3:
            print(f"\n  [{len(references)}] REF: {references[-1][:88]}")
            print(f"      HYP: {hypotheses[-1][:88]}")
        elif len(references) % 50 == 0:
            print(f"  decoded {len(references)} ...")

    if not references:
        print("\n  NO USABLE REFERENCES - no metric can be reported.")
        return 1

    wer = float(jiwer.wer(references, hypotheses))
    cer = float(jiwer.cer(references, hypotheses))
    measures = jiwer.process_words(references, hypotheses)
    lo, hi = spec["script"]
    hyp_script = sum(script_ratio(h, lo, hi) for h in hypotheses) / len(hypotheses)

    record = {
        "task": f"asr_{args.lang}",
        "model_id": MODEL_ID,
        "decoding": "ctc",
        "model_dir": args.model_dir,
        "benchmark": {
            "dataset": DATASET, "license": DATASET_LICENSE,
            "config": spec["fleurs"], "split": "test",
            "utterances_decoded": len(references),
            "utterances_skipped_empty_reference": empty_refs,
            "audio_seconds": round(audio_seconds, 1),
        },
        "normalisation": NORMALISATION_STEPS,
        "metrics": {
            "wer": wer, "cer": cer,
            "substitutions": measures.substitutions,
            "deletions": measures.deletions,
            "insertions": measures.insertions,
            "hits": measures.hits,
        },
        "sanity": {
            "hypothesis_expected_script_ratio": round(hyp_script, 4),
            "empty_hypotheses": sum(1 for h in hypotheses if not h),
        },
        "performance": {
            "decode_seconds": round(decode_seconds, 1),
            "real_time_factor": round(decode_seconds / audio_seconds, 4)
            if audio_seconds else None,
            "stage_seconds": {k: round(v, 2) for k, v in model.timing.items()},
            "onnx_acceleration": "GPU" if gpu_onnx else "CPU_ONLY",
            "providers_active": model.providers_active,
            "preprocessor_device": str(model.device),
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3)
            if torch.cuda.is_available() else None,
            "process_rss_gb": rss_gb(),
        },
        "environment": {
            "python": platform.python_version(), "torch": torch.__version__,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
            "platform": platform.platform(),
        },
        "timing": {"started_utc": started.isoformat(),
                   "finished_utc": datetime.now(timezone.utc).isoformat()},
        "caveat": (
            "FLEURS is clean read speech at 16 kHz with no telephony codec, "
            "channel noise or spontaneous-speech disfluency, so this WER is a "
            "best-case floor and not a call-channel accuracy figure. Greedy "
            "CTC decoding, no external language model."
        ),
    }
    out = args.out or os.path.join(EVAL_DIR, f"asr_{args.lang}_conformer_report.json")
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"\n  utterances: {len(references)}")
    print(f"  WER = {wer:.4f}")
    print(f"  CER = {cer:.4f}")
    print(f"  script ratio = {hyp_script:.4f}")
    print(f"  RTF = {record['performance']['real_time_factor']}")
    print(f"  report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
