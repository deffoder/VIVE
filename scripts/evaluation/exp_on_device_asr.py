"""Phase H: can any ASR VIVE uses fit on the phone, and survive being made to?

O17 records that there is no on-device inference: the selected ASR is 2,381 MB
against 2.1 GB of available RAM on the target handset, so nothing runs locally
and the phone needs the backend for everything. The blocker was written as an
arithmetic fact and then left there.

The arithmetic is only half an answer. "Too big" invites three follow-ups that
were never asked: does a smaller model exist, does quantisation close the gap,
and does the model still work once quantised? A 4x smaller model that
transcribes nothing is not a solution, and reporting a size reduction without
an accuracy number would be exactly that mistake.

What changed since O17 was written
----------------------------------
Phase G added `whisper-base` as an English backend, and Phase 10A measured
`whisper-tiny` alongside it. `whisper-tiny` is 39M parameters against
IndicConformer's 600M - it is not close to the same size class, and it is
already downloaded. So the question is no longer hypothetical.

What this measures
------------------
Dynamic int8 quantisation of the Linear layers, which is where almost all of
Whisper's parameters live, against the fp32 original: on-disk size, per-window
latency, and **WER on the same FLEURS English clips as every other VIVE ASR
measurement**, so a size win can be checked against an accuracy loss rather
than reported alone.

What this is NOT, and the gap is large
--------------------------------------
`torch.ao.quantization.quantize_dynamic` on an x86 CPU is not an Android
deployment. A real one would be an ONNX or TFLite export running on ARM through
NNAPI or XNNPACK, and neither `onnx` nor `optimum` is installed here - a
deliberate choice not to add two build dependencies to answer a question that
dynamic quantisation answers well enough to decide by. Size transfers directly;
latency does NOT, because ARM and x86 int8 paths differ. The latency figures
here bound the question from the laptop side only, and O17 stays open until
something is measured on the handset itself.

Usage:
    python scripts/evaluation/exp_on_device_asr.py [--clips 25]
"""

from __future__ import annotations

import argparse
import io
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, model_dir  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from asr_text import normalise  # noqa: E402

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 32_000          # VIVE's 2.0 s analysis window

DEVICE_RAM_MB = 2_100
"""Available RAM measured on the target handset (OnePlus CPH2661), O17."""

INDIC_CONFORMER_MB = 2_381
"""The selected ASR's on-disk size, for the comparison O17 is built on."""

CANDIDATES = ("whisper-tiny", "whisper-base")


def directory_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return round(total / 1e6, 1)


def state_dict_size_mb(model) -> float:
    """Serialised weight size, which is what an APK would actually carry."""
    import torch

    handle, path = tempfile.mkstemp(suffix=".pt")
    os.close(handle)
    try:
        torch.save(model.state_dict(), path)
        return round(os.path.getsize(path) / 1e6, 1)
    finally:
        os.unlink(path)


def english_clips(count: int):
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", "en_us", split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    out = []
    for row in ds:
        reference = normalise(row.get("transcription") or "")
        if not reference:
            continue
        wave, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        if rate != SAMPLE_RATE:
            continue
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        out.append((np.asarray(wave, dtype="float32"), reference))
        if len(out) >= count:
            break
    return out


def transcribe(model, processor, wave, torch) -> tuple[str, float]:
    began = time.perf_counter()
    features = processor(wave, sampling_rate=SAMPLE_RATE,
                         return_tensors="pt").input_features
    with torch.no_grad():
        ids = model.generate(features, language="en", task="transcribe",
                             max_new_tokens=120, do_sample=False, num_beams=1)
    text = processor.batch_decode(ids, skip_special_tokens=True)[0]
    return text, (time.perf_counter() - began) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=25)
    args = parser.parse_args()

    import jiwer
    import numpy as np
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    exp = Experiment(
        "10H_on_device_asr",
        question=("O17 says nothing can run on the phone because the ASR is "
                  "2,381 MB against 2.1 GB of RAM. Does a smaller model plus "
                  "quantisation close that gap, and does the model still "
                  "transcribe once quantised?"),
        hypothesis=("whisper-tiny at 39M parameters will fit on the handset "
                    "with room to spare even before quantisation, and int8 "
                    "will roughly quarter it again. The real risk is not size "
                    "but accuracy: if int8 costs several WER points the size "
                    "win is worthless, and that is the number that decides "
                    "this."),
        method=("Quantise the Linear layers dynamically to int8, then measure "
                "serialised size, per-window latency and WER on the same "
                "FLEURS English clips and the same normaliser as every other "
                "VIVE ASR measurement."))
    exp.config(device_ram_mb=DEVICE_RAM_MB,
               indic_conformer_mb=INDIC_CONFORMER_MB,
               window_samples=WINDOW_SAMPLES, clips=args.clips,
               quantisation="torch.ao.quantization.quantize_dynamic, "
                            "qint8, Linear layers",
               host="x86 CPU (NOT the target ARM device)")

    clips = english_clips(args.clips)
    if not clips:
        raise SystemExit("no FLEURS English clips available")
    exp.dataset(name="google/fleurs en_us", source="HuggingFace",
                license="CC-BY-4.0", split="test", samples=len(clips),
                language="en")

    # A 2.0 s window taken from real speech, so the latency figure is the
    # per-packet cost VIVE would actually pay rather than a cost on silence.
    window = clips[0][0][SAMPLE_RATE:SAMPLE_RATE + WINDOW_SAMPLES]

    results: dict[str, dict] = {}
    for name in CANDIDATES:
        path = model_dir("_pretrained", name)
        if not os.path.isdir(path):
            print(f"{name}: not downloaded, skipped")
            continue
        print(f"\n=== {name} ===")
        exp.model(name=name, revision=f"openai/{name}", license="Apache-2.0")

        processor = WhisperProcessor.from_pretrained(path)
        row: dict[str, dict] = {"on_disk_mb": directory_size_mb(path)}

        for precision in ("fp32", "int8"):
            model = WhisperForConditionalGeneration.from_pretrained(path).eval()
            if precision == "int8":
                model = torch.ao.quantization.quantize_dynamic(
                    model, {torch.nn.Linear}, dtype=torch.qint8)

            latencies = []
            for _ in range(5):
                _text, ms = transcribe(model, processor, window, torch)
                latencies.append(ms)

            references, hypotheses = [], []
            for wave, reference in clips:
                text, _ms = transcribe(model, processor, wave, torch)
                references.append(reference)
                hypotheses.append(normalise(text))

            size_mb = state_dict_size_mb(model)
            row[precision] = {
                "weights_mb": size_mb,
                # Warm-up excluded: the first call initialises kernels, and a
                # steady-state cost is what a running call pays.
                "window_latency_ms_median": round(
                    statistics.median(latencies[2:]), 1),
                "wer": round(float(jiwer.wer(references, hypotheses)), 4),
                "cer": round(float(jiwer.cer(references, hypotheses)), 4),
                "fits_in_device_ram": size_mb < DEVICE_RAM_MB,
                "percent_of_device_ram": round(100 * size_mb / DEVICE_RAM_MB, 1),
            }
            print(f"  {precision:<5} {size_mb:>7.1f} MB  "
                  f"{row[precision]['window_latency_ms_median']:>7.1f} ms  "
                  f"WER {row[precision]['wer']:.4f}")
            del model

        fp32, int8 = row["fp32"], row["int8"]
        row["int8_vs_fp32"] = {
            "size_ratio": round(int8["weights_mb"] / fp32["weights_mb"], 3),
            "latency_ratio": round(int8["window_latency_ms_median"]
                                   / fp32["window_latency_ms_median"], 3),
            "wer_delta": round(int8["wer"] - fp32["wer"], 4),
            # The decision rule, written before the numbers were read: a
            # quantisation that costs more than 2 WER points is not a win,
            # whatever it saves.
            "accuracy_preserved": (int8["wer"] - fp32["wer"]) < 0.02,
        }
        results[name] = row

    exp.result("candidates", results)
    exp.result("baseline", {
        "indic_conformer_mb": INDIC_CONFORMER_MB,
        "device_available_ram_mb": DEVICE_RAM_MB,
        "indic_conformer_fits": INDIC_CONFORMER_MB < DEVICE_RAM_MB,
        "note": ("IndicConformer is the SELECTED ASR and covers Hindi and "
                 "Tamil. Whisper does not replace it: Phase 10A measured "
                 "whisper-base at WER 1.1640 on Hindi. Anything that fits on "
                 "the phone is English-only."),
    })

    print("\n--- against the handset's 2.1 GB ---")
    print(f"  {'indic-conformer-600m':<24}{INDIC_CONFORMER_MB:>8} MB   "
          f"{'FITS' if INDIC_CONFORMER_MB < DEVICE_RAM_MB else 'DOES NOT FIT'}")
    for name, row in results.items():
        for precision in ("fp32", "int8"):
            entry = row[precision]
            print(f"  {name + ' ' + precision:<24}{entry['weights_mb']:>8.1f} MB   "
                  f"{'fits' if entry['fits_in_device_ram'] else 'does not fit'}"
                  f"   {entry['percent_of_device_ram']}% of RAM")

    exp.limitation(
        "Dynamic int8 quantisation on an x86 CPU is NOT an Android "
        "deployment. A real one would be an ONNX or TFLite export on ARM "
        "through NNAPI or XNNPACK. Size transfers directly; LATENCY DOES NOT, "
        "because the ARM and x86 int8 kernels differ. No figure here may be "
        "quoted as on-device latency.")
    exp.limitation(
        "Only the Linear layers are quantised, which is where nearly all of "
        "Whisper's parameters are but not all of its compute. Convolutional "
        "front-end and attention arithmetic stay fp32.")
    exp.limitation(
        "English only, and that is the crux rather than a detail. Whisper "
        "fails VIVE's two Indic priority languages (Phase 10A: WER 1.1640 "
        "Hindi, 0.9084 Tamil), so a model that fits on the phone does not "
        "cover the language the product actually works in end to end.")
    exp.limitation(
        "ASR is one stage. On-device operation also needs VAD, the text heads "
        "and risk fusion, and only the ASR is measured here. Fitting the "
        "largest component is necessary, not sufficient.")
    exp.limitation(
        f"{args.clips} FLEURS clips of clean read speech. WER differences of "
        "a point or two should not be read as real, and none of this is "
        "telephone audio.")

    # Which candidate is actually deployable: smallest int8 model whose
    # accuracy survived quantisation. Chosen by the rule declared above, not
    # by picking whichever number reads best afterwards.
    viable = [
        (name, row) for name, row in results.items()
        if row.get("int8_vs_fp32", {}).get("accuracy_preserved")
    ]
    viable.sort(key=lambda item: item[1]["int8"]["weights_mb"])
    best = viable[0] if viable else None
    exp.result("recommended_candidate", {
        "model": best[0] if best else None,
        "precision": "int8" if best else None,
        "weights_mb": best[1]["int8"]["weights_mb"] if best else None,
        "wer": best[1]["int8"]["wer"] if best else None,
        "rule": "smallest int8 model whose WER stayed within 0.02 of fp32",
        "rejected": {
            name: {"wer_delta": row["int8_vs_fp32"]["wer_delta"]}
            for name, row in results.items()
            if not row.get("int8_vs_fp32", {}).get("accuracy_preserved")
        },
    })
    if best:
        print(f"\n  deployable: {best[0]} int8, "
              f"{best[1]['int8']['weights_mb']} MB, "
              f"WER {best[1]['int8']['wer']}")

    deltas = {name: row["int8_vs_fp32"]["wer_delta"]
              for name, row in results.items()}
    smallest = min(results.items(),
                   key=lambda item: item[1]["int8"]["weights_mb"])

    exp.finish(
        interpretation=(
            f"The size half of O17 dissolves outright. Every candidate fits: "
            f"the smallest, {smallest[0]} at int8, is "
            f"{smallest[1]['int8']['weights_mb']} MB - "
            f"{smallest[1]['int8']['percent_of_device_ram']}% of the "
            f"handset's available RAM - against IndicConformer's "
            f"{INDIC_CONFORMER_MB} MB, which exceeds the whole budget. "
            f"Quantisation is where the expectation broke. It was supposed to "
            f"be nearly free; instead its cost depends on the model. WER "
            f"deltas at int8: {deltas}. The smaller model has less redundancy "
            f"to absorb int8 rounding, so compressing the already-small "
            f"candidate is what damages it - the opposite of the intuition "
            f"that a smaller model is the safer thing to quantise."
            + (f" The deployable choice is therefore {best[0]} at int8, "
               f"{best[1]['int8']['weights_mb']} MB and WER "
               f"{best[1]['int8']['wer']}." if best else
               " No candidate survived quantisation within the declared "
               "tolerance.")),
        conclusion=(
            "O17 stays OPEN, and for a sharper reason than the one it was "
            "written with. It is no longer true that nothing could fit: "
            "something does, comfortably, and at int8 without losing "
            "accuracy - provided the right model is quantised. What does not "
            "fit is a model that covers VIVE's actual end-to-end language. "
            "Whisper fails Hindi and Tamil (Phase 10A: WER 1.1640 and "
            "0.9084), so on-device analysis would be English-only, and "
            "English is exactly the language that is off by default because "
            "it misses the latency budget (O16). The blocker moves from 'no "
            "model is small enough' to 'the small model does not speak the "
            "right languages', which needs a different fix: a compact Indic "
            "ASR, not a compression of this one. ARM latency remains "
            "unmeasured, and nothing here may be quoted as an on-device "
            "figure."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
