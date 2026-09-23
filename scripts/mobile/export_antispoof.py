"""Exports the Phase J2 anti-spoof model for the phone and measures it at 2 s.

Phase J2 selected `mo-thecreator/Deepfake-audio-detection` (Apache-2.0,
wav2vec2 audio classification) on 4 s clips: ASVspoof LA EER 0.000, VIVE
synthesis probe EER 0.100, against AASIST's 0.0133 / 0.4333. The phone scores
VIVE's 2 s analysis window, a length J2 never measured, so this script:

  1. exports the checkpoint to ONNX (fp32 and int8-MatMul),
  2. measures EER at 2 s AND 4 s for torch fp32, ONNX fp32 and ONNX int8 on
     both corpora, plus the English-only slice of the probe once it exists,
  3. writes antispoof_manifest.json with `validated: false`.

`validated` stays false here on purpose. Nothing in this script touches
handset-captured audio, and handset audio is exactly where AASIST failed
(0.9998 "spoof" on genuine speech). `handset_antispoof.py` measures that and
is the only thing that may set it. The phone's engine does not feed an
unvalidated anti-spoof score into risk.

The spoof index is read from id2label and checked against the name, never
assumed: these checkpoints disagree on label order.

Usage:
    python scripts/mobile/export_antispoof.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ART = os.path.join(ROOT, "models", "artifacts")
SRC = os.path.join(ART, "_pretrained", "antispoof-wav2vec2")
OUT = os.path.join(ART, "mobile")
PROBE = os.path.join(ART, "_probe")
LA = os.path.join(ART, "_asvspoof", "la_eval_sample.npz")
REPORT = os.path.join(ROOT, "models", "evaluation", "mobile", "antispoof_export_eval.json")

SR = 16_000
SOURCE = "mo-thecreator/Deepfake-audio-detection"
SPOOF_NAMES = {"fake", "spoof", "deepfake", "synthetic", "aivoice"}
INT8_MAX_EER_INCREASE = 0.02


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalise(x):
    return ((x - x.mean()) / np.sqrt(x.var() + 1e-7)).astype("float32")


def eer(spoof, bona):
    """Scores are P(spoof); higher = more synthetic."""
    ts = sorted(set(spoof + bona))
    best = None
    for t in ts:
        frr = sum(s < t for s in spoof) / len(spoof)      # spoof missed
        far = sum(b >= t for b in bona) / len(bona)       # bonafide flagged
        if best is None or abs(frr - far) < best[0]:
            best = (abs(frr - far), t, frr, far)
    _, t, frr, far = best
    return {"eer": round((frr + far) / 2, 4), "threshold": round(t, 4),
            "bonafide_flagged_at_0.5": round(sum(b >= 0.5 for b in bona) / len(bona), 4),
            "spoof_caught_at_0.5": round(sum(s >= 0.5 for s in spoof) / len(spoof), 4),
            "n": [len(spoof), len(bona)]}


def corpora():
    import soundfile as sf

    probe = {"spoof": [], "bonafide": []}
    for label in probe:
        d = os.path.join(PROBE, label)
        for name in sorted(os.listdir(d)):
            if name.endswith(".wav"):
                w, r = sf.read(os.path.join(d, name), dtype="float32")
                if r == SR:
                    probe[label].append(w if w.ndim == 1 else w.mean(1))
    blob = np.load(LA)
    # Read each member ONCE: indexing an npz member decompresses all of it,
    # and doing that per clip exhausted memory.
    flat, offsets, labels = blob["flat"], blob["offsets"], blob["labels"]
    la = {"spoof": [], "bonafide": []}
    for i, lab in enumerate(labels):   # ClassLabel: 1 = spoof
        key = "spoof" if int(lab) == 1 else "bonafide"
        if len(la[key]) < 120:
            la[key].append(flat[offsets[i]:offsets[i + 1]].copy())
    del flat
    return {"vive_probe": probe, "asvspoof_la": la}


def main() -> int:
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForAudioClassification

    model = AutoModelForAudioClassification.from_pretrained(SRC).eval()
    labels = {int(k): v for k, v in model.config.id2label.items()}
    spoof_index = [i for i, v in labels.items() if v.lower() in SPOOF_NAMES]
    if len(spoof_index) != 1:
        raise SystemExit(f"cannot identify the spoof class in {labels}")
    spoof_index = spoof_index[0]

    os.makedirs(OUT, exist_ok=True)
    fp32 = os.path.join(OUT, "antispoof.fp32.onnx")
    int8 = os.path.join(OUT, "antispoof.onnx")
    torch.onnx.export(model, (torch.zeros(1, 2 * SR),), fp32,
                      input_names=["input_values"], output_names=["logits"],
                      dynamic_axes={"input_values": {1: "samples"}},
                      opset_version=17, do_constant_folding=True, dynamo=False)
    quantize_dynamic(fp32, int8, weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul"])
    sessions = {name: ort.InferenceSession(p, providers=["CPUExecutionProvider"])
                for name, p in (("onnx_fp32", fp32), ("onnx_int8", int8))}

    def score(x, runner):
        x = normalise(x)
        if runner == "torch":
            with torch.no_grad():
                logits = model(torch.from_numpy(x[None, :])).logits[0].numpy()
        else:
            logits = sessions[runner].run(None, {"input_values": x[None, :]})[0][0]
        e = np.exp(logits - logits.max())
        return float(e[spoof_index] / e.sum())

    data = corpora()
    results = {}
    for corpus, clips in data.items():
        for seconds in (2.0, 4.0):
            n = int(seconds * SR)
            usable = {k: [w[:n] for w in v if len(w) >= n] for k, v in clips.items()}
            for runner in ("torch", "onnx_fp32", "onnx_int8"):
                s = [score(w, runner) for w in usable["spoof"]]
                b = [score(w, runner) for w in usable["bonafide"]]
                key = f"{corpus}@{seconds:.0f}s/{runner}"
                results[key] = eer(s, b)
                print(key, results[key], flush=True)

    worst = max(results[f"{c}@2s/onnx_int8"]["eer"] - results[f"{c}@2s/onnx_fp32"]["eer"]
                for c in data)
    ship_int8 = worst <= INT8_MAX_EER_INCREASE
    if not ship_int8:
        os.replace(fp32, int8)
    else:
        os.remove(fp32)
    manifest = {"models": {"antispoof": {
        "file": "antispoof.onnx", "bytes": os.path.getsize(int8), "sha256": sha256(int8),
        "source": SOURCE, "license": "Apache-2.0",
        "precision": "int8-matmul" if ship_int8 else "fp32",
        "version": "deepfake-audio-detection-w2v2-" + ("int8" if ship_int8 else "fp32"),
        "labels": [labels[i] for i in sorted(labels)], "spoof_index": spoof_index,
        "window_samples": 2 * SR, "do_normalize": True,
        "validated": False,
        "validation_note": "not measured on handset-captured audio; see handset_antispoof.py",
    }}}
    with io.open(os.path.join(OUT, "antispoof_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with io.open(REPORT, "w", encoding="utf-8") as fh:
        json.dump({"source": SOURCE, "spoof_index": spoof_index, "labels": labels,
                   "shipped": manifest["models"]["antispoof"]["precision"],
                   "results": results,
                   "confound": "probe spoof is English SpeechT5, bonafide is Hindi/Tamil FLEURS"},
                  fh, indent=1)
    print("shipped", manifest["models"]["antispoof"]["precision"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
