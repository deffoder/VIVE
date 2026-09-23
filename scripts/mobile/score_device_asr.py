"""Scores the phone's ASR output against FLEURS and against the desktop graph.

Reads `asr_device.json` pulled from the phone (androidTest AsrDeviceEvalTest)
and `eval/eval.json` (make_asr_eval.py), and reports per language:

  * device WER / CER against the FLEURS reference - the accuracy claim,
  * exact-match rate and WER between device and desktop transcripts of the
    same graph - the check that the Android port is faithful,
  * load time, 2 s window latency and process memory, measured on the phone.

Writes models/evaluation/mobile/asr_device_eval.json (tracked).

Usage:
    adb pull /sdcard/Android/data/com.vive/files/results/asr_device.json <tmp>
    python scripts/mobile/score_device_asr.py <tmp>/asr_device.json
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from asr_text import normalise  # noqa: E402

EVAL = os.path.join(ROOT, "models", "artifacts", "mobile", "eval", "eval.json")
MANIFEST = os.path.join(ROOT, "models", "artifacts", "mobile", "asr_manifest.json")
OUT = os.path.join(ROOT, "models", "evaluation", "mobile", "asr_device_eval.json")


def main(path: str) -> int:
    import jiwer

    with io.open(path, encoding="utf-8") as fh:
        device = json.load(fh)["results"]
    with io.open(EVAL, encoding="utf-8") as fh:
        clips = {c["wav"]: c for c in json.load(fh)["clips"]}
    with io.open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)["models"]

    report = {"device": "OnePlus CPH2661 (arm64-v8a, Android 16)", "languages": {}}
    for lang in sorted({r["lang"] for r in device if "lang" in r}):
        rows = [r for r in device if r.get("lang") == lang]
        summary = next(r for r in device if r.get("summary") == lang)
        refs = [normalise(clips[r["wav"]]["reference"]) for r in rows]
        hyps = [normalise(r["device_hyp"]) for r in rows]
        desk = [normalise(clips[r["wav"]]["desktop_hyp"]) for r in rows]
        exact = sum(a == b for a, b in zip(hyps, desk)) / len(rows)
        windows = summary.get("window_ms", [])
        spec = manifest[lang]
        report["languages"][lang] = {
            "model": spec["source"], "license": spec["license"],
            "precision": spec["precision"], "size_mb": round(spec["bytes"] / 1e6, 1),
            "utterances": len(rows),
            "device_wer": round(jiwer.wer(refs, hyps), 4),
            "device_cer": round(jiwer.cer(refs, hyps), 4),
            "desktop_wer_same_clips": round(jiwer.wer(refs, desk), 4),
            "device_vs_desktop_exact_match": round(exact, 4),
            "device_vs_desktop_wer": round(jiwer.wer(desk, hyps), 4) if any(desk) else None,
            "load_ms": summary.get("load_ms"),
            "window_2s_ms_median": statistics.median(windows) if windows else None,
            "window_2s_ms_max": max(windows) if windows else None,
            "rss_loaded_mb": round(summary["rss_loaded_kb"] / 1024, 1),
            "peak_rss_mb": round(summary["hwm_kb"] / 1024, 1),
            "sample": {"reference": refs[0][:90], "device": hyps[0][:90]},
        }
        r = report["languages"][lang]
        print(f"{lang}: WER {r['device_wer']:.4f} (desktop {r['desktop_wer_same_clips']:.4f}) "
              f"exact-match {exact:.0%}  load {r['load_ms']} ms  "
              f"2s window {r['window_2s_ms_median']} ms  peak RSS {r['peak_rss_mb']} MB")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
