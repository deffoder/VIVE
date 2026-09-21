"""Measures Hindi ASR word- and character-error rate on an open benchmark.

Step 11 of Phase 7. Produces the first REAL audio metric in the project: every
figure comes from decoding actual speech and comparing it to a reference
transcript that the model never saw.

Benchmark: `google/fleurs` (CC-BY-4.0, ungated), config `hi_in`, `test` split.
FLEURS is read-speech at 16 kHz, which matches the VIVE audio contract, but it
is NOT telephony: no codec loss, no channel noise, no spontaneous speech. The
WER reported here is therefore a FLOOR - a clean-speech best case. Call-channel
WER will be worse, and this number must never be presented as call accuracy.

Normalisation is applied identically to hypothesis and reference and is listed
in the report, because WER is extremely sensitive to it and an unstated
normalisation makes a number unreproducible.

Usage:
    python scripts/training/eval_asr_hindi.py --limit 200
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

DATASET = "google/fleurs"
DATASET_LICENSE = "CC-BY-4.0"
CONFIG = "hi_in"
SPLIT = "test"

# Punctuation stripped from BOTH sides. Includes the Devanagari danda and
# double danda, which the CTC vocabulary does not contain at all - leaving them
# in the reference would charge the model for tokens it cannot emit.
PUNCT = re.compile(r"[।॥,.!?;:\"'`()\[\]{}<>\-–—_/\|@#$%^&*+=~]")
WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Applied identically to reference and hypothesis. Reported verbatim."""
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = PUNCT.sub(" ", text)
    return WS.sub(" ", text).strip()


NORMALISATION_STEPS = [
    "Unicode NFC",
    "lowercase",
    "strip punctuation including Devanagari danda U+0964 and double danda U+0965",
    "collapse whitespace",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--limit", type=int, default=200,
                        help="utterances to decode; 0 means the whole split")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out", default=os.path.join(EVAL_DIR, "asr_hindi_report.json"))
    args = parser.parse_args()

    import numpy as np
    import soundfile as sf
    import torch
    import jiwer
    from datasets import Audio, load_dataset
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    device = args.device if torch.cuda.is_available() else "cpu"
    print(f"model={args.model_dir}\ndevice={device}")

    processor = Wav2Vec2Processor.from_pretrained(args.model_dir)
    model = Wav2Vec2ForCTC.from_pretrained(args.model_dir).to(device).eval()
    print(f"  loaded: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params")

    print(f"\nloading {DATASET} [{CONFIG}] {SPLIT} (streaming)")
    stream = load_dataset(DATASET, CONFIG, split=SPLIT, streaming=True)
    # datasets>=5 decodes audio through torchcodec, which needs FFmpeg and
    # is not available here. Take the raw bytes and decode with soundfile;
    # the samples are identical and it drops a heavy dependency.
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
        if wave.ndim > 1:          # collapse to mono per the audio contract
            wave = wave.mean(axis=1)
        wave = np.asarray(wave, dtype=np.float32)
        if rate != 16_000:
            raise SystemExit(f"unexpected sample rate {rate}; VIVE assumes 16 kHz")

        reference = normalise(sample.get("transcription") or "")
        if not reference:
            empty_refs += 1
            continue

        inputs = processor(wave, sampling_rate=rate, return_tensors="pt",
                           padding=True)
        began = time.time()
        with torch.no_grad():
            logits = model(inputs.input_values.to(device)).logits
        decode_seconds += time.time() - began
        audio_seconds += len(wave) / rate

        predicted = torch.argmax(logits, dim=-1)
        hypothesis = normalise(processor.batch_decode(predicted)[0])

        references.append(reference)
        hypotheses.append(hypothesis)

        if len(references) <= 3:
            print(f"\n  [{len(references)}] REF: {reference[:90]}")
            print(f"      HYP: {hypothesis[:90]}")
        elif len(references) % 50 == 0:
            print(f"  decoded {len(references)} ...")

    if not references:
        print("\n  NO USABLE REFERENCES - no metric can be reported.")
        return 1

    finished = datetime.now(timezone.utc)
    wer = float(jiwer.wer(references, hypotheses))
    cer = float(jiwer.cer(references, hypotheses))
    measures = jiwer.process_words(references, hypotheses)

    record = {
        "task": "asr_hindi",
        "model_id": "ai4bharat/indicwav2vec-hindi",
        "model_dir": args.model_dir,
        "benchmark": {
            "dataset": DATASET,
            "license": DATASET_LICENSE,
            "config": CONFIG,
            "split": SPLIT,
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
        "performance": {
            "decode_seconds": round(decode_seconds, 1),
            "real_time_factor": round(decode_seconds / audio_seconds, 4)
            if audio_seconds else None,
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
            "FLEURS is clean read speech at 16 kHz. It has no telephony codec "
            "loss, channel noise or spontaneous-speech disfluency, so this WER "
            "is a best-case floor and not a call-channel accuracy figure. "
            "Greedy CTC decoding, no language model."
        ),
    }

    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"\n  utterances: {len(references)}")
    print(f"  WER = {wer:.4f}")
    print(f"  CER = {cer:.4f}")
    print(f"  RTF = {record['performance']['real_time_factor']}")
    print(f"  report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
