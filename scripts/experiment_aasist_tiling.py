"""Does the adapter's tiling inflate AASIST spoof scores?

Targeted Phase 8 follow-up. AASIST consumes a fixed 64,600-sample window
(~4.04 s at 16 kHz), but VIVE analyses 2.0 s windows (32,000 samples). The
adapter currently TILES the window to reach the required length, which splices
the waveform and creates a discontinuity at each repeat boundary. AASIST reads
raw waveform and is sensitive to exactly that kind of low-level artefact, so
the splice could plausibly look like a synthesis artefact.

Experimental design
-------------------
The confound to avoid is content. Comparing a tiled 2 s window against a native
4.04 s window changes BOTH the preprocessing and the audio, so a difference
would prove nothing.

So the primary comparison holds content fixed: the SAME 2 s segment is extended
to 64,600 samples four different ways. Any score difference between those is
caused purely by the extension strategy.

  tile         np.tile then truncate - what the adapter does today
  zero_pad     append silence
  reflect_pad  mirror the signal at the boundary (no hard discontinuity)
  edge_pad     repeat the final sample

A secondary comparison reports the native 64,600-sample window from the same
clip. That one DOES change content and is labelled as such; it is context, not
evidence about tiling.

This measures preprocessing sensitivity on a small sample. It is not an EER,
not a false-positive rate, and says nothing about detection accuracy.

Usage:
    python scripts/experiment_aasist_tiling.py
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

EVAL_DIR = os.path.join(ROOT, "models", "evaluation")
SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 32_000      # VIVE's 2.0 s analysis window
CLIPS = 12


def extend(samples, method: str, target: int):
    """Extends a short window to the model's required length."""
    import numpy as np

    if samples.size >= target:
        return samples[:target]
    if method == "tile":
        reps = int(np.ceil(target / samples.size))
        return np.tile(samples, reps)[:target]
    if method == "zero_pad":
        return np.pad(samples, (0, target - samples.size), mode="constant")
    if method == "reflect_pad":
        return np.pad(samples, (0, target - samples.size), mode="reflect")
    if method == "edge_pad":
        return np.pad(samples, (0, target - samples.size), mode="edge")
    raise ValueError(method)


def discontinuity(samples, method: str, window: int) -> float | None:
    """Max absolute sample-to-sample jump at the first splice boundary.

    A large jump is the mechanism by which tiling could look synthetic.
    """
    import numpy as np

    if samples.size <= window:
        return None
    edge = samples[window - 2:window + 2]
    return float(np.abs(np.diff(edge)).max())


def main() -> int:
    import numpy as np
    import soundfile as sf
    import torch
    from datasets import Audio, load_dataset

    from app.adapters.real.audio_models import AASIST_CONFIG, AASIST_SAMPLES
    from app.adapters.real.vendor.aasist_model import Model as AasistModel

    ckpt = os.path.join(ROOT, "models", "artifacts", "_pretrained",
                        "aasist", "AASIST.pth")
    model = AasistModel(dict(AASIST_CONFIG))
    state = torch.load(ckpt, map_location="cpu", weights_only=True)
    missing, unexpected = model.load_state_dict(state, strict=False)
    assert not missing and not unexpected, "checkpoint/architecture mismatch"
    model.eval()

    def spoof_score(x) -> float:
        with torch.no_grad():
            _emb, logits = model(torch.from_numpy(np.ascontiguousarray(x)).unsqueeze(0))
            return float(torch.softmax(logits[0], dim=-1)[0])

    print(f"AASIST requires {AASIST_SAMPLES:,} samples "
          f"({AASIST_SAMPLES / SAMPLE_RATE:.2f} s at {SAMPLE_RATE} Hz)")
    print(f"VIVE window is  {WINDOW_SAMPLES:,} samples "
          f"({WINDOW_SAMPLES / SAMPLE_RATE:.2f} s) -> extension required\n")

    ds = load_dataset("google/fleurs", "hi_in", split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))

    methods = ["tile", "zero_pad", "reflect_pad", "edge_pad"]
    rows: list[dict] = []
    for row in ds:
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE or len(wave) < AASIST_SAMPLES:
            continue

        window = np.asarray(wave[:WINDOW_SAMPLES], dtype=np.float32)
        native = np.asarray(wave[:AASIST_SAMPLES], dtype=np.float32)

        entry = {
            "clip": len(rows) + 1,
            "window_samples": int(window.size),
            "native_samples": int(native.size),
            "scores": {m: round(spoof_score(extend(window, m, AASIST_SAMPLES)), 4)
                       for m in methods},
            "native_4s_score": round(spoof_score(native), 4),
            "splice_discontinuity": {
                m: round(discontinuity(extend(window, m, AASIST_SAMPLES), m,
                                       WINDOW_SAMPLES) or 0.0, 4)
                for m in methods
            },
        }
        rows.append(entry)
        s = entry["scores"]
        print(f"  clip {entry['clip']:>2}  tile={s['tile']:.4f}  "
              f"zero={s['zero_pad']:.4f}  reflect={s['reflect_pad']:.4f}  "
              f"edge={s['edge_pad']:.4f}  | native4s={entry['native_4s_score']:.4f}")
        if len(rows) >= CLIPS:
            break

    if not rows:
        print("no usable clips")
        return 1

    def med(key: str) -> float:
        return round(statistics.median(r["scores"][key] for r in rows), 4)

    summary = {m: med(m) for m in methods}
    native_med = round(statistics.median(r["native_4s_score"] for r in rows), 4)

    print("\n--- median spoof score over "
          f"{len(rows)} clips (identical 2 s content per method) ---")
    for m in methods:
        print(f"  {m:<12} {summary[m]:.4f}")
    print(f"  {'native 4.04s':<12} {native_med:.4f}   (different content - context only)")

    # How far does the choice of extension move the score, per clip?
    spreads = [max(r["scores"].values()) - min(r["scores"].values()) for r in rows]
    tile_vs_reflect = [r["scores"]["tile"] - r["scores"]["reflect_pad"] for r in rows]
    tile_highest = sum(1 for r in rows
                       if r["scores"]["tile"] == max(r["scores"].values()))

    print(f"\n  per-clip spread across methods: median {statistics.median(spreads):.4f}, "
          f"max {max(spreads):.4f}")
    print(f"  tile minus reflect_pad: median {statistics.median(tile_vs_reflect):+.4f}, "
          f"max {max(tile_vs_reflect):+.4f}, min {min(tile_vs_reflect):+.4f}")
    print(f"  clips where tiling gave the HIGHEST score: {tile_highest}/{len(rows)}")

    disc = {m: round(statistics.median(r["splice_discontinuity"][m] for r in rows), 4)
            for m in methods}
    print(f"\n  median splice discontinuity at the boundary: {disc}")

    record = {
        "experiment": "aasist_window_extension",
        "run_at": str(date.today()),
        "question": ("Does the adapter's tiling of a 2 s window to 64,600 "
                     "samples inflate AASIST spoof scores?"),
        "design": ("Identical 2 s content extended four ways; any difference "
                   "is caused by the extension strategy alone. The native "
                   "4.04 s score uses different content and is context only."),
        "model": {"checkpoint": "AASIST.pth", "required_samples": AASIST_SAMPLES,
                  "sample_rate": SAMPLE_RATE, "resampling_performed": False},
        "vive_window_samples": WINDOW_SAMPLES,
        "clips": len(rows),
        "median_scores": summary,
        "median_native_4s_score": native_med,
        "per_clip_spread": {"median": round(statistics.median(spreads), 4),
                            "max": round(max(spreads), 4)},
        "tile_minus_reflect": {
            "median": round(statistics.median(tile_vs_reflect), 4),
            "max": round(max(tile_vs_reflect), 4),
            "min": round(min(tile_vs_reflect), 4)},
        "clips_where_tile_scored_highest": tile_highest,
        "median_splice_discontinuity": disc,
        "rows": rows,
        "caveat": (
            f"{len(rows)} clips of one corpus. This measures sensitivity to "
            "input extension, NOT detection accuracy. It is not an EER and not "
            "a false-positive rate."
        ),
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "aasist_tiling_experiment.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
