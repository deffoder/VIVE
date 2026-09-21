"""Measures Whisper ASR word- and character-error rate on FLEURS.

Phase 7 follow-up for BLOCKERS O8 (Tamil). Whisper is a single multilingual
encoder-decoder that covers both VIVE priority languages, which is why it is
preferred over a per-language model stack: one architecture, one adapter, one
set of failure modes.

Supports `--lang ta` and `--lang hi`. Running both against the SAME benchmark
and the SAME normaliser (`models/training/asr_text.py`) is the point: it makes
the Tamil figure interpretable next to the Hindi one, and lets Whisper be
compared against indicwav2vec on Hindi rather than assumed better or worse.

A model card listing Tamil is not evidence of Tamil support. This script
decodes real Tamil speech and scores it. If the decode is empty or not in
Tamil script, that shows up in the metric rather than being asserted away.

Usage:
    python scripts/training/eval_asr_whisper.py --lang ta --limit 0
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

LANGS = {
    "ta": {"fleurs": "ta_in", "whisper": "tamil", "script": (0x0B80, 0x0BFF)},
    "hi": {"fleurs": "hi_in", "whisper": "hindi", "script": (0x0900, 0x097F)},
}


def script_ratio(text: str, lo: int, hi: int) -> float:
    """Share of letters in the expected script.

    Guards against a failure mode WER alone can hide: Whisper silently
    transcribing into the wrong language or transliterating to Latin. A high
    WER together with a near-zero script ratio means "wrong language", not
    "poor accuracy", and those two need different responses.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=sorted(LANGS), required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out")
    args = parser.parse_args()

    import numpy as np
    import soundfile as sf
    import torch
    import jiwer
    from datasets import Audio, load_dataset
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    spec = LANGS[args.lang]
    out_path = args.out or os.path.join(
        EVAL_DIR, f"asr_{args.lang}_whisper_report.json")

    device = args.device if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"model={args.model_dir}")
    print(f"lang={args.lang} ({spec['whisper']})")
    print(f"device={device} dtype={dtype}")

    processor = WhisperProcessor.from_pretrained(args.model_dir)
    model = (WhisperForConditionalGeneration
             .from_pretrained(args.model_dir, torch_dtype=dtype)
             .to(device).eval())
    print(f"  loaded: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params")

    stream = load_dataset(DATASET, spec["fleurs"], split="test", streaming=True)
    # datasets>=5 decodes audio through torchcodec, which needs FFmpeg and is
    # not available here. Take the raw bytes and decode with soundfile.
    stream = stream.cast_column("audio", Audio(decode=False))

    references: list[str] = []
    hypotheses: list[str] = []
    empty_refs = 0
    started = datetime.now(timezone.utc)
    decode_seconds = 0.0
    audio_seconds = 0.0

    for index, sample in enumerate(stream):
        if args.limit and index >= args.limit:
            break
        audio = sample["audio"]
        raw = audio.get("bytes")
        if raw is None:
            with open(audio["path"], "rb") as handle:
                raw = handle.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        wave = np.asarray(wave, dtype=np.float32)
        if rate != 16_000:
            raise SystemExit(f"unexpected sample rate {rate}; VIVE assumes 16 kHz")

        reference = normalise(sample.get("transcription") or "")
        if not reference:
            empty_refs += 1
            continue

        features = processor(
            wave, sampling_rate=rate,
            return_tensors="pt").input_features.to(device, dtype)
        began = time.time()
        with torch.no_grad():
            tokens = model.generate(features, language=spec["whisper"],
                                    task="transcribe", max_new_tokens=220)
        decode_seconds += time.time() - began
        audio_seconds += len(wave) / rate

        hypothesis = normalise(
            processor.batch_decode(tokens, skip_special_tokens=True)[0])
        references.append(reference)
        hypotheses.append(hypothesis)

        if len(references) <= 3:
            print(f"\n  [{len(references)}] REF: {reference[:88]}")
            print(f"      HYP: {hypothesis[:88]}")
        elif len(references) % 50 == 0:
            print(f"  decoded {len(references)} ...")

    if not references:
        print("\n  NO USABLE REFERENCES - no metric can be reported.")
        return 1

    finished = datetime.now(timezone.utc)
    wer = float(jiwer.wer(references, hypotheses))
    cer = float(jiwer.cer(references, hypotheses))
    measures = jiwer.process_words(references, hypotheses)
    lo, hi = spec["script"]
    hyp_script = sum(script_ratio(h, lo, hi) for h in hypotheses) / len(hypotheses)
    ref_script = sum(script_ratio(r, lo, hi) for r in references) / len(references)
    empty_hyps = sum(1 for h in hypotheses if not h)

    record = {
        "task": f"asr_{args.lang}",
        "model_id": "openai/whisper-large-v3-turbo",
        "model_dir": args.model_dir,
        "language": {"code": args.lang, "whisper_name": spec["whisper"]},
        "benchmark": {
            "dataset": DATASET,
            "license": DATASET_LICENSE,
            "config": spec["fleurs"],
            "split": "test",
            "utterances_decoded": len(references),
            "utterances_skipped_empty_reference": empty_refs,
            "audio_seconds": round(audio_seconds, 1),
        },
        "normalisation": NORMALISATION_STEPS,
        "metrics": {
            "wer": wer,
            "cer": cer,
            "substitutions": measures.substitutions,
            "deletions": measures.deletions,
            "insertions": measures.insertions,
            "hits": measures.hits,
        },
        "sanity": {
            "hypothesis_expected_script_ratio": round(hyp_script, 4),
            "reference_expected_script_ratio": round(ref_script, 4),
            "empty_hypotheses": empty_hyps,
            "note": ("Script ratio separates 'wrong language' from 'poor "
                     "accuracy'. A low ratio means the model transcribed into "
                     "another script, which WER alone would not reveal."),
        },
        "performance": {
            "decode_seconds": round(decode_seconds, 1),
            "real_time_factor": round(decode_seconds / audio_seconds, 4)
            if audio_seconds else None,
            "dtype": str(dtype),
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
            "platform": platform.platform(),
        },
        "timing": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
        },
        "caveat": (
            "FLEURS is clean read speech at 16 kHz with no telephony codec, "
            "channel noise or spontaneous-speech disfluency, so this WER is a "
            "best-case floor and not a call-channel accuracy figure. Greedy "
            "decoding, no external language model."
        ),
    }

    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"\n  utterances: {len(references)}")
    print(f"  WER = {wer:.4f}")
    print(f"  CER = {cer:.4f}")
    print(f"  hypothesis script ratio = {hyp_script:.4f} (reference {ref_script:.4f})")
    print(f"  empty hypotheses = {empty_hyps}")
    print(f"  RTF = {record['performance']['real_time_factor']}")
    print(f"  report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
