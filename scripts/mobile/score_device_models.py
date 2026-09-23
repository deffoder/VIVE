"""Compares the phone's text-head, ECAPA and VAD outputs with the desktop graphs.

Inputs pulled from the phone (androidTest ModelsDeviceEvalTest):
    text_device.json, speaker_device.json
Desktop references: models/artifacts/mobile/eval/{text_eval,speaker_eval}.json

Reports, for the phone:
  * text: intent top-1 and behaviour-set agreement with the desktop graph,
    max |logit| difference, per-text latency, memory;
  * speaker: cosine(device embedding, desktop embedding), and the enrol-vs-2 s
    protocol recomputed from DEVICE embeddings at the manifest threshold -
    genuine accept rate and impostor reject rate;
  * VAD: speech ratio and quality per clip vs the desktop ONNX graph run
    through the same frame/context logic as the Kotlin class.

Writes models/evaluation/mobile/models_device_eval.json.

Usage:
    python scripts/mobile/score_device_models.py <dir with pulled json>
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MOBILE = os.path.join(ROOT, "models", "artifacts", "mobile")
OUT = os.path.join(ROOT, "models", "evaluation", "mobile", "models_device_eval.json")


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cos(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def desktop_vad(wav_path):
    import onnxruntime as ort
    import soundfile as sf

    sess = ort.InferenceSession(os.path.join(MOBILE, "silero_vad.onnx"),
                                providers=["CPUExecutionProvider"])
    pcm, _ = sf.read(wav_path, dtype="int16")
    x = (pcm.astype("float32") / 32768.0)[:32000]
    state = np.zeros((2, 1, 128), dtype="float32")
    ctx = np.zeros((1, 64), dtype="float32")
    speech = frames = 0
    for i in range(len(x) // 512):
        inp = np.concatenate([ctx, x[i * 512:(i + 1) * 512][None, :]], axis=1)
        out, state = sess.run(None, {"input": inp, "state": state,
                                     "sr": np.array(16000, dtype="int64")})
        ctx = inp[:, -64:]
        speech += float(out[0][0]) >= 0.5
        frames += 1
    return speech / max(frames, 1)


def main(pulled: str) -> int:
    report = {"device": "OnePlus CPH2661 (arm64-v8a, Android 16), ORT 1.30 CPU"}

    text_dev = load(os.path.join(pulled, "text_device.json"))
    text_ref = load(os.path.join(MOBILE, "eval", "text_eval.json"))["items"]
    dev_rows = text_dev["rows"]
    n = len(dev_rows)
    i_agree = sum(int(np.argmax(d["intent"]) == np.argmax(r["intent"]))
                  for d, r in zip(dev_rows, text_ref)) / n
    b_agree = sum(int(all((np.asarray(d["behavior"]) >= 0) == (np.asarray(r["behavior"]) >= 0)))
                  for d, r in zip(dev_rows, text_ref)) / n
    diff = max(float(np.max(np.abs(np.asarray(d[h]) - np.asarray(r[h]))))
               for d, r in zip(dev_rows, text_ref) for h in ("intent", "behavior"))
    ms = text_dev["both_heads_ms"]
    report["text"] = {
        "texts": n, "load_status": text_dev["load_status"], "load_ms": text_dev.get("load_ms"),
        "intent_top1_agreement_vs_desktop": round(i_agree, 4),
        "behavior_set_agreement_vs_desktop": round(b_agree, 4),
        "max_abs_logit_diff": round(diff, 5),
        "both_heads_ms_median": statistics.median(ms), "both_heads_ms_max": max(ms),
        "rss_loaded_mb": round(text_dev["rss_loaded_kb"] / 1024, 1),
        "rss_increase_mb": round((text_dev["rss_loaded_kb"] - text_dev["rss_before_kb"]) / 1024, 1),
    }
    print("text", report["text"])

    sp_dev = load(os.path.join(pulled, "speaker_device.json"))
    sp_ref = load(os.path.join(MOBILE, "eval", "speaker_eval.json"))["items"]
    by_wav = {r["wav"]: r for r in sp_dev["rows"]}
    fidelity = [cos(by_wav[r["wav"]]["embedding"], r["desktop_embedding"]) for r in sp_ref]
    enrol = {r["speaker"]: by_wav[r["wav"]]["embedding"] for r in sp_ref if r["role"] == "enrol"}
    probes = [(r["speaker"], by_wav[r["wav"]]["embedding"]) for r in sp_ref if r["role"] == "probe"]
    t = sp_dev["threshold"]
    genuine = [cos(enrol[s], e) for s, e in probes]
    impostor = [cos(enrol[o], e) for s, e in probes for o in enrol if o != s]
    embed_ms = [r["embed_ms"] for r in sp_dev["rows"] if r["samples"] <= 32000]
    report["speaker"] = {
        "embedding_cosine_vs_desktop_min": round(min(fidelity), 6),
        "threshold": t, "genuine_pairs": len(genuine), "impostor_pairs": len(impostor),
        "genuine_accept_rate": round(sum(g >= t for g in genuine) / len(genuine), 4),
        "impostor_reject_rate": round(sum(i < t for i in impostor) / len(impostor), 4),
        "genuine_min": round(min(genuine), 4), "impostor_max": round(max(impostor), 4),
        "embed_2s_ms_median": statistics.median(embed_ms),
    }
    print("speaker", report["speaker"])

    vad_diffs, q_counts = [], {}
    for r in sp_ref:
        d = by_wav[r["wav"]]
        vad_diffs.append(abs(d["vad_ratio"] - desktop_vad(os.path.join(MOBILE, "eval", r["wav"]))))
        q_counts[d["vad_quality"]] = q_counts.get(d["vad_quality"], 0) + 1
    report["vad"] = {"clips": len(vad_diffs), "max_speech_ratio_diff_vs_desktop": round(max(vad_diffs), 4),
                     "quality_counts": q_counts,
                     "vad_2s_ms_median": statistics.median(r["vad_ms"] for r in sp_dev["rows"] if "vad_ms" in r)}
    print("vad", report["vad"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
