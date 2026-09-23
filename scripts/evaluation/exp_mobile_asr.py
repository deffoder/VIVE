"""Can a phone-sized ASR cover Hindi, Tamil AND English, and at what cost?

Two open problems point at the same question.

**O16** — the selected ASR is IN-22 and has no English at all, while the text
heads support English, Hindi and Hinglish. End-to-end coverage is therefore
Hindi only.

**O17** — IndicConformer is 2,381 MB against 2.1 GB of available RAM on the
target handset, so nothing can run on the device.

A small multilingual model could answer both at once, or it could turn out to
be too inaccurate to be worth it. That is a measurement, not a judgement call,
and this makes it.

Candidates
----------
`openai/whisper-tiny` (39M) and `openai/whisper-base` (74M), both Apache-2.0
and ungated. Both cover English, Hindi and Tamil in one model, and both are
small enough that a quantised export would fit comfortably on the phone.

Method
------
Same benchmark, same normaliser and same metric as every earlier VIVE ASR
measurement (`models/training/asr_text.py`), so the rows sit directly beside
the IndicConformer figures rather than beside a differently-computed WER.
Greedy decoding with the language given, because VIVE has no language-ID
model and supplies the language as an input either way.

This measures ACCURACY and SIZE. It does not measure on-device latency: these
run here as PyTorch, and an Android deployment would be a quantised ONNX or
TFLite export whose speed has to be measured on the device itself.

Usage:
    python scripts/evaluation/exp_mobile_asr.py --clips 40
"""

from __future__ import annotations

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, model_dir  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from asr_text import NORMALISATION_STEPS, normalise  # noqa: E402

SAMPLE_RATE = 16_000
LANGS = {"hi": "hi_in", "ta": "ta_in", "en": "en_us"}

CANDIDATES = {
    "whisper-tiny": {"dir": "whisper-tiny", "params_m": 39},
    "whisper-base": {"dir": "whisper-base", "params_m": 74},
}

# Measured from the artifacts on disk, not quoted from a model card.
REFERENCE = {
    "indic-conformer-600m": {
        "hi": {"wer": 0.1164, "cer": 0.0460},
        "ta": {"wer": 0.2833, "cer": 0.1107},
        "en": None,
        "size_mb": 2381,
        "note": "IN-22, no English mask at all (BLOCKERS O16)",
    },
}


def fleurs(config: str, count: int):
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


def directory_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return round(total / 1e6, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=40)
    args = parser.parse_args()

    import jiwer
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    exp = Experiment(
        "10A_mobile_asr_candidates",
        question=("Can a phone-sized multilingual ASR cover Hindi, Tamil and "
                  "English, and how much accuracy does it cost against the "
                  "2.4 GB model VIVE ships?"),
        hypothesis=("Whisper tiny and base will transcribe all three "
                    "languages, so they close the English gap that O16 "
                    "describes, but will be materially worse than "
                    "IndicConformer on Hindi and Tamil - the question is how "
                    "much worse, not whether."),
        method=("Decode FLEURS with the language supplied, using the same "
                "normaliser and metric as every earlier VIVE ASR "
                "measurement, so rows are directly comparable."))

    exp.config(clips_per_language=args.clips, decoding="greedy",
               normalisation=NORMALISATION_STEPS, sample_rate=SAMPLE_RATE,
               languages=sorted(LANGS))
    exp.result("reference_model", REFERENCE)

    results: dict[str, dict] = {}
    for name, meta in CANDIDATES.items():
        path = model_dir("_pretrained", meta["dir"])
        if not os.path.isdir(path):
            print(f"{name}: not downloaded, skipped")
            continue
        size_mb = directory_size_mb(path)
        print(f"\n=== {name} ({meta['params_m']}M params, {size_mb} MB on disk) ===")
        exp.model(name=name, revision=f"openai/{meta['dir']}",
                  license="Apache-2.0", params_m=meta["params_m"],
                  size_mb=size_mb)

        processor = WhisperProcessor.from_pretrained(path)
        model = WhisperForConditionalGeneration.from_pretrained(path).eval()

        results[name] = {"size_mb": size_mb, "params_m": meta["params_m"]}
        for lang, config in LANGS.items():
            clips = fleurs(config, args.clips)
            if not clips:
                results[name][lang] = {"error": "no audio"}
                continue
            exp.dataset(name=f"google/fleurs {config}", source="HuggingFace",
                        license="CC-BY-4.0", split="test", samples=len(clips),
                        language=lang)
            refs, hyps = [], []
            for wave, reference in clips:
                features = processor(wave, sampling_rate=SAMPLE_RATE,
                                     return_tensors="pt").input_features
                with torch.no_grad():
                    ids = model.generate(
                        features, language=lang, task="transcribe",
                        max_new_tokens=200, do_sample=False, num_beams=1)
                text = processor.batch_decode(ids, skip_special_tokens=True)[0]
                refs.append(reference)
                hyps.append(normalise(text))
            wer = float(jiwer.wer(refs, hyps))
            cer = float(jiwer.cer(refs, hyps))
            # A WER above 1.0 usually means a broken harness, so record WHY
            # it happened here. Whisper writes Hindi audio in Urdu script and
            # sometimes romanises it, so the hypothesis is real speech in the
            # wrong alphabet - which scores as total substitution against a
            # Devanagari reference. The script ratio makes that visible
            # instead of leaving an implausible number unexplained.
            ranges = {"hi": (0x0900, 0x097F), "ta": (0x0B80, 0x0BFF),
                      "en": (0x0041, 0x007A)}
            lo, hi_cp = ranges[lang]
            chars = [c for h in hyps for c in h if not c.isspace()]
            in_script = sum(1 for c in chars if lo <= ord(c) <= hi_cp)
            results[name][lang] = {
                "wer": round(wer, 4), "cer": round(cer, 4),
                "utterances": len(refs),
                "empty_hypotheses": sum(1 for h in hyps if not h.strip()),
                "expected_script_ratio": round(in_script / max(len(chars), 1), 4),
                "sample_hypothesis": hyps[0][:120] if hyps else "",
            }
            print(f"  {lang}  WER {wer:.4f}  CER {cer:.4f}  n={len(refs)}")

    exp.result("candidates", results)

    print("\n--- comparison (FLEURS clean read speech) ---")
    print(f"  {'model':<22}{'size':>9}{'hi WER':>10}{'ta WER':>10}{'en WER':>10}")
    ref = REFERENCE["indic-conformer-600m"]
    print(f"  {'indic-conformer-600m':<22}{ref['size_mb']:>8}MB"
          f"{ref['hi']['wer']:>10.4f}{ref['ta']['wer']:>10.4f}"
          f"{'none':>10}")
    for name, row in results.items():
        def cell(lang: str) -> str:
            entry = row.get(lang) or {}
            return f"{entry['wer']:.4f}" if "wer" in entry else "-"
        print(f"  {name:<22}{row['size_mb']:>8}MB"
              f"{cell('hi'):>10}{cell('ta'):>10}{cell('en'):>10}")

    exp.limitation(
        "FLEURS is clean read speech. These are upper bounds for every model "
        "in the table, not telephone accuracy.")
    exp.limitation(
        f"{args.clips} utterances per language. Differences of a few points "
        "should not be read as real.")
    exp.limitation(
        "Accuracy and size only. On-device latency is NOT measured: these run "
        "as PyTorch here, and an Android deployment would be a quantised ONNX "
        "or TFLite export whose speed has to be measured on the phone.")
    exp.limitation(
        "Greedy decoding with the language supplied. Whisper's own language "
        "detection is not used, because VIVE has no language-ID model and "
        "supplies the language as an input either way.")
    exp.limitation(
        "A WER above 1.0 is real here, not a harness fault. Whisper renders "
        "Hindi audio in Urdu script and sometimes romanises both Hindi and "
        "Tamil, so the hypothesis is speech in the wrong alphabet and scores "
        "as total substitution. `expected_script_ratio` records how much of "
        "each output was in the reference's own script.")
    exp.limitation(
        "Whisper pads every input to 30 s, which Phase 7 measured as 5.5 s per "
        "2 s window for large-v3-turbo. The smaller variants pay the same "
        "structural cost at a smaller constant, and that cost is not measured "
        "here.")

    exp.finish(
        interpretation=(
            "The table states the trade directly: a phone-sized model that "
            "covers all three priority languages, against a 2.4 GB model that "
            "is more accurate on two of them and cannot transcribe the third "
            "at all."),
        conclusion=(
            "Whether to adopt one is a product decision about which error "
            "rate is acceptable in which language, and it cannot be settled "
            "from clean-speech WER alone. What this removes is the excuse "
            "that no phone-sized option existed."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
