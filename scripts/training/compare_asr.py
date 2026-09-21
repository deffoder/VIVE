"""Builds the ASR candidate comparison table from measured reports.

Every cell is read from a JSON artifact written by an executed evaluation.
A candidate with no report for a language renders as "not measured" rather
than being omitted or estimated, so a gap in the evidence stays visible.

The streaming verdict is computed, not asserted: VIVE analyses a 2.0 s window
every 1.0 s, so ASR must cost well under 1.0 s per window. The table reports
the projected per-window cost from the measured real-time factor and says
plainly whether it fits.

Usage:
    python scripts/training/compare_asr.py
    python scripts/training/compare_asr.py --markdown
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL = os.path.join(ROOT, "models", "evaluation")

WINDOW_SEC = 2.0
CADENCE_BUDGET_SEC = 1.0

# report file per (candidate, language); None where no run exists
CANDIDATES = [
    {
        "key": "indicwav2vec",
        "name": "IndicWav2Vec Hindi",
        "model_id": "ai4bharat/indicwav2vec-hindi",
        "arch": "wav2vec2 CTC",
        "params_m": 315.5,
        "license": "Apache-2.0",
        "access": "gated, terms accepted",
        "languages": "Hindi only",
        "runtime": "PyTorch CUDA (fp32)",
        "reports": {"hi": "asr_hindi_report.json", "ta": None},
    },
    {
        "key": "whisper",
        "name": "Whisper large-v3-turbo",
        "model_id": "openai/whisper-large-v3-turbo",
        "arch": "encoder-decoder, autoregressive",
        "params_m": 808.9,
        "license": "MIT",
        "access": "ungated",
        "languages": "100 incl. hi + ta",
        "runtime": "PyTorch CUDA (fp16)",
        "reports": {"hi": "asr_hi_whisper_report.json",
                    "ta": "asr_ta_whisper_report.json"},
    },
    {
        "key": "indicconformer",
        "name": "IndicConformer-600M",
        "model_id": "ai4bharat/indic-conformer-600m-multilingual",
        "arch": "Conformer hybrid CTC/RNNT (CTC path)",
        "params_m": 600.0,
        "license": "MIT",
        "access": "gated, terms accepted",
        "languages": "IN-22 incl. hi + ta",
        "runtime": "ONNX Runtime CPU only (no CUDA 12)",
        "reports": {"hi": "asr_hi_conformer_report.json",
                    "ta": "asr_ta_conformer_report.json"},
    },
]

NOT_MEASURED = "not measured"


def load(name: str | None) -> dict | None:
    if not name:
        return None
    path = os.path.join(EVAL, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def fmt(value, digits=4):
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) else NOT_MEASURED


def collect() -> list[dict]:
    rows = []
    for cand in CANDIDATES:
        hi = load(cand["reports"].get("hi"))
        ta = load(cand["reports"].get("ta"))
        any_report = hi or ta

        # RTF: prefer a dedicated bench when one exists, else the eval run.
        bench = load("asr_conformer_bench_hi.json") if cand["key"] == "indicconformer" else None
        rtf = None
        if bench:
            rtf = bench.get("rtf")
        elif any_report:
            rtf = (any_report.get("performance") or {}).get("real_time_factor")

        vram = ram = None
        if any_report:
            perf = any_report.get("performance") or {}
            vram = perf.get("peak_vram_gb")
            ram = perf.get("process_rss_gb")
        if bench:
            vram = bench.get("peak_vram_gb", vram)
            ram = bench.get("process_rss_gb", ram)

        window_cost = rtf * WINDOW_SEC if isinstance(rtf, (int, float)) else None
        rows.append({
            "name": cand["name"],
            "model_id": cand["model_id"],
            "arch": cand["arch"],
            "params_m": cand["params_m"],
            "license": cand["license"],
            "access": cand["access"],
            "languages": cand["languages"],
            "runtime": cand["runtime"],
            "wer_hi": (hi or {}).get("metrics", {}).get("wer"),
            "cer_hi": (hi or {}).get("metrics", {}).get("cer"),
            "wer_ta": (ta or {}).get("metrics", {}).get("wer"),
            "cer_ta": (ta or {}).get("metrics", {}).get("cer"),
            "utt_hi": (hi or {}).get("benchmark", {}).get("utterances_decoded"),
            "utt_ta": (ta or {}).get("benchmark", {}).get("utterances_decoded"),
            "rtf": rtf,
            "window_cost_sec": window_cost,
            "meets_cadence": (window_cost < CADENCE_BUDGET_SEC) if window_cost else None,
            "vram_gb": vram,
            "ram_gb": ram,
        })
    return rows


def streaming_verdict(row: dict) -> str:
    if row["window_cost_sec"] is None:
        return NOT_MEASURED
    if row["meets_cadence"]:
        headroom = CADENCE_BUDGET_SEC / row["window_cost_sec"]
        return f"YES - {headroom:.0f}x headroom"
    over = row["window_cost_sec"] / CADENCE_BUDGET_SEC
    return f"NO - {over:.1f}x over budget"


def render_markdown(rows: list[dict]) -> str:
    out = []
    out.append("| Model | Languages | License | WER hi | WER ta | CER hi | CER ta | RTF | Runtime | VRAM / RAM | Streaming | Access |")
    out.append("|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|")
    for r in rows:
        vram = f"{r['vram_gb']} GB" if r["vram_gb"] is not None else "-"
        ram = f"{r['ram_gb']} GB" if r["ram_gb"] is not None else "-"
        out.append(
            f"| {r['name']} | {r['languages']} | {r['license']} | "
            f"{fmt(r['wer_hi'])} | {fmt(r['wer_ta'])} | "
            f"{fmt(r['cer_hi'])} | {fmt(r['cer_ta'])} | "
            f"{fmt(r['rtf'])} | {r['runtime']} | {vram} / {ram} | "
            f"{streaming_verdict(r)} | {r['access']} |"
        )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    rows = collect()

    if args.markdown:
        print(render_markdown(rows))
    else:
        for r in rows:
            print(f"\n=== {r['name']} ===")
            print(f"  arch      : {r['arch']}  ({r['params_m']}M)")
            print(f"  licence   : {r['license']}   access: {r['access']}")
            print(f"  runtime   : {r['runtime']}")
            print(f"  Hindi     : WER {fmt(r['wer_hi'])}  CER {fmt(r['cer_hi'])}"
                  f"  ({r['utt_hi'] or '-'} utt)")
            print(f"  Tamil     : WER {fmt(r['wer_ta'])}  CER {fmt(r['cer_ta'])}"
                  f"  ({r['utt_ta'] or '-'} utt)")
            print(f"  RTF       : {fmt(r['rtf'])}")
            print(f"  2s window : {fmt(r['window_cost_sec'], 3)}s vs {CADENCE_BUDGET_SEC}s budget")
            print(f"  streaming : {streaming_verdict(r)}")
            print(f"  VRAM/RAM  : {r['vram_gb']} / {r['ram_gb']} GB")

    record = {
        "compared_at": str(date.today()),
        "window_sec": WINDOW_SEC,
        "cadence_budget_sec": CADENCE_BUDGET_SEC,
        "benchmark": "google/fleurs test split (CC-BY-4.0), shared normaliser",
        "candidates": rows,
        "caveat": (
            "FLEURS is clean read speech. Every WER here is a floor, not a "
            "call-channel figure. RTF was measured on a GTX 1650 Ti 4 GB with "
            "driver 461.72; onnxruntime had no CUDA provider available, so the "
            "ONNX candidate ran CPU-only and its latency would change in a "
            "CUDA 12 environment."
        ),
    }
    out = os.path.join(EVAL, "asr_comparison.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
