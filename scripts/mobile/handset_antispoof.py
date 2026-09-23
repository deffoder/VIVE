"""Does the anti-spoof model survive the phone's microphone? Decides `validated`.

AASIST passed its benchmark and then scored genuine speech through this
handset as 0.9998 "spoof". A benchmark therefore cannot license the channel;
only handset-captured audio can. This measures exactly that:

  make   - builds a playlist: genuine FLEURS speech (en, hi, ta) and synthetic
           speech (SpeechT5 probe, en; edge-tts test calls, hi/en/ta), 4 s
           each with 1 s gaps, led by an alignment chirp.
  (the laptop plays the playlist; the phone records it through the same MIC
   source the app uses - androidTest HandsetRecordTest)
  score  - aligns the phone recording to the playlist by cross-correlation,
           cuts VIVE's 2 s windows out of each item, scores them with the
           shipped ONNX graph, and applies the criterion below.

Both classes travel the same path - laptop loudspeaker, room, phone mic, AGC -
so the channel cannot separate them; only synthesis can.

CRITERION, fixed before any recording was scored:
  1. English genuine vs English synthetic (no language confound): EER <= 0.20
  2. Genuine speech, all languages: <= 10% of windows score >= 0.5
Both must hold for `validated: true`. Otherwise the manifest stays false and
the phone keeps anti-spoofing out of the risk score.

Usage:
    python scripts/mobile/handset_antispoof.py make
    python scripts/mobile/handset_antispoof.py score <phone_recording.wav>
"""

from __future__ import annotations

import io
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MOBILE = os.path.join(ROOT, "models", "artifacts", "mobile")
PROBE = os.path.join(ROOT, "models", "artifacts", "_probe")
PLAYLIST = os.path.join(MOBILE, "handset", "playlist.wav")
META = os.path.join(MOBILE, "handset", "playlist.json")
REPORT = os.path.join(ROOT, "models", "evaluation", "mobile", "antispoof_handset_eval.json")
SR = 16_000
ITEM = 4 * SR
GAP = SR
EER_MAX = 0.20
GENUINE_FLAG_MAX = 0.10


def chirp():
    t = np.arange(int(0.5 * SR)) / SR
    return (0.6 * np.sin(2 * np.pi * (500 + 3000 * t) * t)).astype("float32")


def make() -> int:
    import soundfile as sf

    items = []
    ev = json.load(io.open(os.path.join(MOBILE, "eval", "eval.json"), encoding="utf-8"))["clips"]
    per_lang = {"en": 14, "hi": 8, "ta": 8}
    for lang, n in per_lang.items():
        for c in [c for c in ev if c["lang"] == lang][:n]:
            w, _ = sf.read(os.path.join(MOBILE, "eval", c["wav"]), dtype="float32")
            items.append(("genuine", lang, "fleurs", w))
    for name in sorted(os.listdir(os.path.join(PROBE, "spoof")))[:14]:
        w, _ = sf.read(os.path.join(PROBE, "spoof", name), dtype="float32")
        items.append(("synthetic", "en", "speecht5", w))
    calls = json.load(io.open(os.path.join(MOBILE, "calls", "calls.json"), encoding="utf-8"))["calls"]
    for name, call in calls.items():
        if not name.endswith("_call"):
            continue
        lang = name.split("_")[0]
        w, _ = sf.read(os.path.join(MOBILE, "calls", f"{name}.wav"), dtype="float32")
        for seg in call["segments"]:
            items.append(("synthetic", lang, "edge-tts",
                          w[int(seg["start_sec"] * SR):int(seg["end_sec"] * SR)]))

    parts = [np.zeros(SR, "float32"), chirp(), np.zeros(SR, "float32")]
    offset = sum(len(p) for p in parts)
    meta = []
    for kind, lang, src, w in items:
        w = w[:ITEM]
        w = 0.6 * w / max(1e-6, float(np.abs(w).max()))
        meta.append({"kind": kind, "lang": lang, "source": src,
                     "start": offset, "end": offset + len(w)})
        parts += [w.astype("float32"), np.zeros(GAP, "float32")]
        offset += len(w) + GAP
    os.makedirs(os.path.dirname(PLAYLIST), exist_ok=True)
    full = np.concatenate(parts)
    sf.write(PLAYLIST, full, SR, subtype="PCM_16")
    with io.open(META, "w", encoding="utf-8") as fh:
        json.dump({"items": meta, "seconds": round(len(full) / SR, 1)}, fh, indent=1)
    print(f"playlist {len(meta)} items, {len(full) / SR:.0f} s")
    return 0


def eer(spoof, bona):
    best = None
    for t in sorted(set(spoof + bona)):
        frr = sum(s < t for s in spoof) / len(spoof)
        far = sum(b >= t for b in bona) / len(bona)
        if best is None or abs(frr - far) < best[0]:
            best = (abs(frr - far), (frr + far) / 2, t)
    return round(best[1], 4), round(best[2], 4)


def score(recording: str) -> int:
    import onnxruntime as ort
    import soundfile as sf
    from scipy.signal import fftconvolve

    meta = json.load(io.open(META, encoding="utf-8"))["items"]
    ref, _ = sf.read(PLAYLIST, dtype="float32")
    rec, rate = sf.read(recording, dtype="float32")
    assert rate == SR, rate
    # Align on the first 20 s of the playlist (chirp plus speech).
    probe = ref[: 20 * SR]
    corr = fftconvolve(rec[: 60 * SR], probe[::-1], mode="valid")
    lag = int(np.argmax(corr))
    print(f"alignment lag {lag / SR:.2f} s")

    manifest_path = os.path.join(MOBILE, "antispoof_manifest.json")
    manifest = json.load(io.open(manifest_path, encoding="utf-8"))
    spec = manifest["models"]["antispoof"]
    sess = ort.InferenceSession(os.path.join(MOBILE, spec["file"]), providers=["CPUExecutionProvider"])

    def p_spoof(x):
        x = ((x - x.mean()) / np.sqrt(x.var() + 1e-7)).astype("float32")
        z = sess.run(None, {"input_values": x[None, :]})[0][0]
        e = np.exp(z - z.max())
        return float(e[spec["spoof_index"]] / e.sum())

    rows = []
    for m in meta:
        seg = rec[lag + m["start"]: lag + m["end"]]
        for start in range(0, max(1, len(seg) - 2 * SR + 1), SR):   # VIVE: 2 s window, 1 s stride
            w = seg[start:start + 2 * SR]
            if len(w) < 2 * SR or np.sqrt((w ** 2).mean()) < 1e-3:
                continue
            rows.append({**{k: m[k] for k in ("kind", "lang", "source")}, "score": round(p_spoof(w), 4)})

    def scores(kind, lang=None):
        return [r["score"] for r in rows if r["kind"] == kind and (lang is None or r["lang"] == lang)]

    en_eer, en_t = eer(scores("synthetic", "en"), scores("genuine", "en"))
    genuine = scores("genuine")
    flagged = sum(s >= 0.5 for s in genuine) / len(genuine)
    per = {f"{k}/{l}": {"windows": len(scores(k, l)),
                        "median": round(float(np.median(scores(k, l))), 4),
                        "share_ge_0.5": round(sum(s >= 0.5 for s in scores(k, l)) / len(scores(k, l)), 4)}
           for k in ("genuine", "synthetic") for l in ("en", "hi", "ta") if scores(k, l)}
    passed = en_eer <= EER_MAX and flagged <= GENUINE_FLAG_MAX
    report = {
        "channel": "laptop loudspeaker -> room -> OnePlus CPH2661 MIC source (the app's capture path)",
        "criterion": {"en_eer_max": EER_MAX, "genuine_flagged_max": GENUINE_FLAG_MAX},
        "en_vs_en_eer": en_eer, "en_eer_threshold": en_t,
        "genuine_windows_flagged_at_0.5": round(flagged, 4),
        "per_class": per, "passed": passed, "windows": len(rows),
        "scored_with": spec["file"] + " (desktop ONNX Runtime on the phone's recording)",
    }
    print(json.dumps(report, indent=1))
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with io.open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    spec["validated"] = passed
    spec["validation_note"] = ("passed handset criterion" if passed else "FAILED handset criterion") + \
        f": en EER {en_eer}, genuine flagged {flagged:.1%} (models/evaluation/mobile/antispoof_handset_eval.json)"
    with io.open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        sys.exit(make())
    sys.exit(score(sys.argv[2]))
