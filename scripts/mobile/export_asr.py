"""Exports the on-device ASR models to ONNX and measures what the phone will run.

Why this architecture
---------------------
Phase-only operation needs speech recognition that fits in a phone's memory
and keeps up with a 1 s packet stride. The server ASR cannot: IndicConformer is
2,381 MB against ~1.4 GB of free RAM on the target handset (O17). Whisper fits
but fails Hindi and Tamil (Phase 10A: WER 1.16 and 0.91 - wrong script) and
pads every window to 30 s, so it is slow for streaming (O16).

So the phone uses one small CTC model PER LANGUAGE, all the same architecture:

    hi  Harveenchadha/vakyansh-wav2vec2-hindi-him-4200   MIT         4,200 h Hindi
    ta  Harveenchadha/vakyansh-wav2vec2-tamil-tam-250    MIT         Tamil
    en  facebook/wav2vec2-base-960h                      Apache-2.0  LibriSpeech

wav2vec2-base CTC is ~95M parameters, consumes a 2 s window as it is (no
padding to 30 s), and decodes greedily - argmax, collapse repeats, drop blank -
which is a dozen lines of Kotlin. One decoder serves all three languages.

What this script measures, and why it decodes the way the phone does
--------------------------------------------------------------------
Every figure below is produced by ONNX Runtime running the exported graph and
decoded with the same greedy CTC the Kotlin side implements, from the same
manifest. A WER measured through PyTorch and HF's tokenizer would describe a
system the phone does not run.

Quantisation is measured, not assumed. Phase H found int8 nearly free on
whisper-base and ruinous on whisper-tiny, so each model is exported twice and
the int8 graph is shipped only if its WER stays within the declared tolerance
of the fp32 graph. Only MatMul is quantised: the transformer layers hold most
of the weights, while the convolutional feature encoder is small and the part
most sensitive to rounding.

Output (git-ignored, models/artifacts/**):
    models/artifacts/mobile/asr-<lang>.onnx
    models/artifacts/mobile/asr_manifest.json

Usage:
    python scripts/mobile/export_asr.py [--clips 30] [--langs hi ta en]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import statistics
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from asr_text import normalise  # noqa: E402

PRETRAINED = os.path.join(ROOT, "models", "artifacts", "_pretrained")
OUT = os.path.join(ROOT, "models", "artifacts", "mobile")

SAMPLE_RATE = 16_000
WINDOW = 32_000               # VIVE's 2.0 s analysis window
INT8_TOLERANCE = 0.02         # max WER increase for the int8 graph to ship

MODELS = {
    "hi": {"dir": "asr-hi-w2v2", "fleurs": "hi_in",
           "source": "Harveenchadha/vakyansh-wav2vec2-hindi-him-4200",
           "license": "MIT"},
    "ta": {"dir": "asr-ta-w2v2", "fleurs": "ta_in",
           "source": "Harveenchadha/vakyansh-wav2vec2-tamil-tam-250",
           "license": "MIT"},
    "en": {"dir": "asr-en-w2v2", "fleurs": "en_us",
           "source": "facebook/wav2vec2-base-960h", "license": "Apache-2.0"},
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: str):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
        wave, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        if rate != SAMPLE_RATE:
            continue
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        out.append((np.asarray(wave, dtype="float32"), reference))
        if len(out) >= count:
            break
    return out


def normalise_wave(wave):
    """Zero mean, unit variance - Wav2Vec2FeatureExtractor(do_normalize=True).

    Reproduced here rather than calling the HF extractor so that the numbers
    describe the arithmetic the Kotlin side performs. The 1e-7 matches HF.
    """
    import numpy as np

    return ((wave - wave.mean()) / np.sqrt(wave.var() + 1e-7)).astype("float32")


def ctc_greedy(logits, vocab: list[str], blank: int, delimiter: str) -> str:
    """Argmax, collapse repeats, drop blank, delimiter to space.

    This is the whole decoder. The Kotlin implementation is a line-for-line
    port, and `tests` there pin it against strings produced here.
    """
    ids = logits.argmax(axis=-1)
    pieces = []
    previous = -1
    for index in ids:
        index = int(index)
        if index != previous and index != blank:
            pieces.append(vocab[index])
        previous = index
    text = "".join(p for p in pieces if not is_special(p)).replace(delimiter, " ")
    return " ".join(text.split())


def is_special(token: str) -> bool:
    """`<s>`, `<pad>`, `</s>`, `<unk>`: never part of a transcript."""
    return len(token) > 2 and token.startswith("<") and token.endswith(">")


def measure_blank(path: str, clips, vocab: list[str], do_normalize: bool) -> tuple[int, float]:
    """Finds the CTC blank from what the model actually emits.

    The blank is not reliably the tokenizer's pad token. The two vakyansh
    checkpoints were converted from fairseq, whose CTC blank is `<s>` (id 0),
    while their HF config declares `<pad>` (id 1). Decoding with the declared
    id printed `<s>` between every character - WER 8.05 Hindi, 10.2 Tamil -
    and made int8 look worse than fp32 on noise. On real speech the blank is
    by far the most frequent argmax, so it is measured here and required to
    be a special token; anything else aborts rather than guessing.
    """
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    counts = np.zeros(len(vocab), dtype=np.int64)
    for wave, _ in clips[:8]:
        x = normalise_wave(wave) if do_normalize else wave
        ids = session.run(None, {"input_values": x[None, :]})[0][0].argmax(axis=-1)
        counts += np.bincount(ids, minlength=len(vocab))
    blank = int(counts.argmax())
    share = float(counts[blank] / counts.sum())
    if not is_special(vocab[blank]):
        raise SystemExit(f"dominant token {vocab[blank]!r} ({share:.0%}) is not a "
                         "special token; refusing to guess the CTC blank")
    return blank, share


def export(lang: str, meta: dict) -> dict:
    import numpy as np
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import Wav2Vec2ForCTC

    src = os.path.join(PRETRAINED, meta["dir"])
    vocab_map = read_json(os.path.join(src, "vocab.json"))
    tokenizer = read_json(os.path.join(src, "tokenizer_config.json"))
    extractor = read_json(os.path.join(src, "preprocessor_config.json"))
    vocab = [None] * len(vocab_map)
    for token, index in vocab_map.items():
        vocab[index] = token
    pad = tokenizer.get("pad_token", "<pad>")
    delimiter = tokenizer.get("word_delimiter_token") or "|"

    model = Wav2Vec2ForCTC.from_pretrained(src).eval()
    if model.config.vocab_size != len(vocab):
        raise SystemExit(f"{lang}: vocab.json has {len(vocab)} entries but "
                         f"the head has {model.config.vocab_size}")

    os.makedirs(OUT, exist_ok=True)
    fp32 = os.path.join(OUT, f"asr-{lang}.fp32.onnx")
    int8 = os.path.join(OUT, f"asr-{lang}.onnx")
    dummy = torch.zeros(1, WINDOW, dtype=torch.float32)
    torch.onnx.export(
        model, (dummy,), fp32,
        input_names=["input_values"], output_names=["logits"],
        dynamic_axes={"input_values": {1: "samples"},
                      "logits": {1: "frames"}},
        opset_version=17, do_constant_folding=True, dynamo=False)
    quantize_dynamic(fp32, int8, weight_type=QuantType.QInt8,
                     op_types_to_quantize=["MatMul"])

    return {
        "vocab": vocab, "declared_pad_id": vocab_map[pad],
        "delimiter": delimiter,
        "do_normalize": bool(extractor.get("do_normalize", True)),
        "fp32_path": fp32, "int8_path": int8,
    }


def evaluate(path: str, clips, spec: dict) -> dict:
    import jiwer
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    refs, hyps = [], []
    for wave, reference in clips:
        x = normalise_wave(wave) if spec["do_normalize"] else wave
        logits = session.run(None, {"input_values": x[None, :]})[0][0]
        refs.append(reference)
        hyps.append(normalise(ctc_greedy(logits, spec["vocab"],
                                         spec["blank_id"], spec["delimiter"])))

    # Per-window latency on a real 2 s speech window, steady state.
    window = clips[0][0][:WINDOW]
    window = normalise_wave(window) if spec["do_normalize"] else window
    timings = []
    for _ in range(6):
        began = time.perf_counter()
        session.run(None, {"input_values": window[None, :]})
        timings.append((time.perf_counter() - began) * 1000)

    return {
        "wer": round(float(jiwer.wer(refs, hyps)), 4),
        "cer": round(float(jiwer.cer(refs, hyps)), 4),
        "utterances": len(refs),
        "window_ms_laptop": round(statistics.median(timings[2:]), 1),
        "size_mb": round(os.path.getsize(path) / 1e6, 1),
        "sample": hyps[0][:100] if hyps else "",
        "reference": refs[0][:100] if refs else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=30)
    parser.add_argument("--langs", nargs="+", default=list(MODELS))
    args = parser.parse_args()

    manifest_path = os.path.join(OUT, "asr_manifest.json")
    manifest = read_json(manifest_path) if os.path.isfile(manifest_path) else {}
    manifest.setdefault("models", {})

    for lang in args.langs:
        meta = MODELS[lang]
        print(f"\n=== {lang}: {meta['source']} ===")
        spec = export(lang, meta)
        clips = fleurs(meta["fleurs"], args.clips)
        blank, share = measure_blank(spec["fp32_path"], clips, spec["vocab"],
                                     spec["do_normalize"])
        spec["blank_id"] = blank
        print(f"  blank {spec['vocab'][blank]!r} id {blank} ({share:.0%} of frames);"
              f" config pad id {spec['declared_pad_id']}")
        fp32 = evaluate(spec["fp32_path"], clips, spec)
        int8 = evaluate(spec["int8_path"], clips, spec)
        print(f"  fp32  {fp32['size_mb']:>7} MB  WER {fp32['wer']:.4f}  "
              f"{fp32['window_ms_laptop']} ms/window")
        print(f"  int8  {int8['size_mb']:>7} MB  WER {int8['wer']:.4f}  "
              f"{int8['window_ms_laptop']} ms/window")
        print(f"  ref   {int8['reference']}")
        print(f"  hyp   {int8['sample']}")

        ship_int8 = int8["wer"] - fp32["wer"] <= INT8_TOLERANCE
        shipped = spec["int8_path"] if ship_int8 else spec["fp32_path"]
        if not ship_int8:
            # int8 failed the tolerance: ship fp32 under the canonical name so
            # the app never loads a graph that measured worse.
            os.replace(spec["fp32_path"], spec["int8_path"])
            shipped = spec["int8_path"]
            print(f"  int8 rejected (+{int8['wer'] - fp32['wer']:.4f} WER); "
                  "shipping fp32")
        elif os.path.exists(spec["fp32_path"]):
            os.remove(spec["fp32_path"])

        manifest["models"][lang] = {
            "file": os.path.basename(shipped),
            "sha256": sha256(shipped),
            "bytes": os.path.getsize(shipped),
            "precision": "int8-matmul" if ship_int8 else "fp32",
            "source": meta["source"], "license": meta["license"],
            "sample_rate": SAMPLE_RATE, "do_normalize": spec["do_normalize"],
            "blank_id": spec["blank_id"], "delimiter": spec["delimiter"],
            "blank_source": "measured dominant argmax; config pad id "
                            f"{spec['declared_pad_id']}",
            "vocab": spec["vocab"],
            "measured": {"fleurs_config": meta["fleurs"], "fp32": fp32,
                         "int8": int8, "int8_tolerance": INT8_TOLERANCE,
                         "decoder": "greedy CTC, identical to Kotlin"},
        }

    with io.open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(f"\nwrote {os.path.relpath(manifest_path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
