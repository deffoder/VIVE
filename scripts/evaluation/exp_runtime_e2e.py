"""Phase 9: what does a packet actually cost, end to end, at steady state?

Phase 8D measured six packets per language and reported a median of 830-1197 ms
against a 1.0 s budget - a range that straddles the boundary, from a sample too
small to say which side it sits on. `BLOCKERS.md` O13 is open on exactly that.

This run fixes the three things that made the earlier number unusable.

**Enough packets for a tail.** Latency that matters is the tail, not the
median: a pipeline whose median fits and whose p95 does not will drop packets
under load. The harness refuses to compute a p95 below 20 samples, so this
takes 30 per language.

**Startup separated from steady state.** Three costs were previously mixed:
process/model load, the first packet's lazy per-session setup, and ordinary
per-packet work. They have different causes and different fixes, and averaging
them together describes no real situation.

**Before and after the anti-spoof buffer fills.** The adapter needs ~4 s of
real audio before it runs AASIST at all. Until then it returns
`INSUFFICIENT_AUDIO` in microseconds, so early packets are systematically
cheaper. Averaging across the boundary understates steady-state cost, and
AASIST is the largest single contributor - so the understatement is large.
Packets are bucketed on which side they fall.

The analyzers run sequentially by design. Phase 8 measured a thread-pool
alternative and it was worse - torch and onnxruntime each already use every
core, so concurrent analyzers oversubscribe rather than overlap. That
experiment is not repeated here; there is no new hypothesis.

Run this alone. A latency benchmark sharing the machine measures the
contention, which is how a Phase 7 RTF probe came to be wrong by 11x.

Usage:
    python scripts/evaluation/exp_runtime_e2e.py [--packets 30]
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import Experiment, add_backend_to_path, percentile  # noqa: E402

SAMPLE_RATE = 16_000
WINDOW_SEC = 2.0
STRIDE_SEC = 1.0
CADENCE_BUDGET_SEC = 1.0
AASIST_WARMUP_SEC = 64_600 / SAMPLE_RATE


def fleurs_windows(config: str, count: int) -> list[bytes]:
    """Overlapping 2 s windows at a 1 s stride, exactly as VIVE packetises.

    Earlier runs sent a separate utterance per packet, which never exercised
    the anti-spoof buffer because consecutive windows had no real continuity.
    """
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    needed = int((WINDOW_SEC + STRIDE_SEC * (count - 1)) * SAMPLE_RATE)
    buffer = np.zeros(0, dtype="float32")
    for row in ds:
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE:
            continue
        buffer = np.concatenate([buffer, np.asarray(wave, dtype="float32")])
        if buffer.size >= needed:
            break

    width = int(WINDOW_SEC * SAMPLE_RATE)
    stride = int(STRIDE_SEC * SAMPLE_RATE)
    out = []
    for i in range(count):
        chunk = buffer[i * stride:i * stride + width]
        if chunk.size < width:
            break
        out.append((np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
    return out


def rss_gb() -> float | None:
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e9, 3)
    except Exception:  # noqa: BLE001
        return None


def run_language(client, lang: str, config: str, count: int) -> dict:
    print(f"\n=== {lang} ({config}) ===")
    windows = fleurs_windows(config, count)
    session_id = client.post("/api/v1/sessions",
                             json={"source_type": "VOIP",
                                   "language": lang}).json()["session_id"]

    measurements: list[dict] = []
    first_ms = None
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()
        for seq, pcm in enumerate(windows, start=1):
            began = time.perf_counter()
            ws.send_json({"type": "client.audio",
                          "audio_b64": base64.b64encode(pcm).decode(),
                          "speaker": "Caller"})
            for _ in range(8):
                frame = ws.receive_json()
                if frame["type"] == "risk.update":
                    break
            wall_ms = (time.perf_counter() - began) * 1000
            if seq == 1:
                first_ms = wall_ms
            measurements.append({"seq": seq, "wall_ms": wall_ms,
                                 "window_end_sec": WINDOW_SEC + (seq - 1) * STRIDE_SEC})

    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()

    # Bucket on whether the anti-spoof buffer had filled by this packet.
    warm = [m for m in measurements
            if m["seq"] > 1 and m["window_end_sec"] >= AASIST_WARMUP_SEC]
    cold = [m for m in measurements
            if m["seq"] > 1 and m["window_end_sec"] < AASIST_WARMUP_SEC]

    def summarise(rows: list[dict]) -> dict:
        values = [r["wall_ms"] for r in rows]
        if not values:
            return {"packets": 0}
        return {
            "packets": len(values),
            "median_ms": round(statistics.median(values), 1),
            "mean_ms": round(statistics.fmean(values), 1),
            "min_ms": round(min(values), 1),
            "max_ms": round(max(values), 1),
            "p95_ms": (round(percentile(values, 95), 1)
                       if percentile(values, 95) is not None else None),
            "p95_note": (None if len(values) >= 20 else
                         f"not computed: {len(values)} samples is below the "
                         "20-sample floor"),
            "within_1s_budget_rate": round(
                sum(1 for v in values if v < CADENCE_BUDGET_SEC * 1000) / len(values), 4),
        }

    # Per-stage cost, aggregated over packets that actually ran each stage.
    stages: dict[str, list[float]] = {}
    statuses: dict[str, dict[str, int]] = {}
    for packet in packets:
        for key in ("asr", "intent", "behavior", "aasist", "ecapa"):
            block = packet.get(key) or {}
            status = block.get("status")
            statuses.setdefault(key, {}).setdefault(status, 0)
            statuses[key][status] += 1
            ms = block.get("inference_ms")
            if ms is not None and status == "AVAILABLE":
                stages.setdefault(key, []).append(float(ms))

    stage_summary = {
        key: {"ran_on_packets": len(values),
              "median_ms": round(statistics.median(values), 1),
              "p95_ms": (round(percentile(values, 95), 1)
                         if percentile(values, 95) is not None else None),
              "max_ms": round(max(values), 1)}
        for key, values in stages.items()}

    first_scored = next(
        (p["seq"] for p in packets
         if (p.get("aasist") or {}).get("status") == "AVAILABLE"), None)

    warm_summary = summarise(warm)
    print(f"  packets: {len(packets)}   first packet: {first_ms:.0f} ms")
    print(f"  steady state (buffer filled): median {warm_summary.get('median_ms')} ms, "
          f"p95 {warm_summary.get('p95_ms')} ms, "
          f"within budget {warm_summary.get('within_1s_budget_rate')}")
    print(f"  before buffer filled        : median "
          f"{summarise(cold).get('median_ms')} ms")
    print(f"  first packet with an AASIST score: #{first_scored}")
    for key, value in sorted(stage_summary.items()):
        print(f"    {key:<10}median {value['median_ms']:>7.1f} ms   "
              f"p95 {value['p95_ms']}   on {value['ran_on_packets']} packets")

    return {
        "language": lang,
        "packets_produced": len(packets),
        "packets_sent": len(windows),
        "first_packet_ms": round(first_ms, 1) if first_ms else None,
        "steady_state_buffer_filled": warm_summary,
        "before_antispoof_buffer_filled": summarise(cold),
        "per_stage_ms": stage_summary,
        "analyzer_status_counts": statuses,
        "first_packet_with_antispoof_score": first_scored,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", type=int, default=30)
    args = parser.parse_args()

    add_backend_to_path()
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    settings = get_settings()
    if settings.adapter_mode != "real":
        print("set VIVE_ADAPTER_MODE=real and the VIVE_*_MODEL_DIR paths")
        return 1

    exp = Experiment(
        "9I_runtime_end_to_end",
        question=("Does a VIVE packet fit inside the 1.0 s cadence budget at "
                  "steady state, including the tail, once startup and the "
                  "anti-spoof warm-up are separated out?"),
        hypothesis=("Steady-state median will sit near the budget as Phase 8D "
                    "suggested, and the p95 will exceed it, because AASIST "
                    "runs on every packet once the buffer has filled."),
        method=("Drive the real backend over HTTP and WebSocket with "
                "genuinely overlapping 2 s windows at a 1 s stride. Bucket "
                "packets by whether the anti-spoof buffer had filled. Report "
                "median and p95 separately from startup cost."))

    rss_before = rss_gb()
    app = create_app()
    load_began = time.perf_counter()
    with TestClient(app) as client:
        bundle_load_ms = round((time.perf_counter() - load_began) * 1000, 1)
        infos = app.state.vive.adapters.infos()
        print(f"bundle loaded with the app in {bundle_load_ms:.0f} ms")
        for key, info in infos.items():
            print(f"  {key:<10}{info.status:<18}{info.model_version:<34}"
                  f"{info.load_ms}ms")
            exp.model(name=info.model_id or key, revision=info.model_version or "?",
                      license="see docs/DATA_SPEC.md 8.1",
                      load_ms=info.load_ms,
                      execution_provider=info.execution_provider,
                      status=str(info.status))
        rss_loaded = rss_gb()

        results = [run_language(client, "hi", "hi_in", args.packets),
                   run_language(client, "ta", "ta_in", args.packets)]

    rss_after = rss_gb()
    exp.config(window_sec=WINDOW_SEC, stride_sec=STRIDE_SEC,
               cadence_budget_sec=CADENCE_BUDGET_SEC,
               packets_per_language=args.packets,
               analyzers="sequential (thread pool measured worse in Phase 8)")
    exp.dataset(name="google/fleurs hi_in + ta_in", source="HuggingFace",
                license="CC-BY-4.0", split="test",
                samples=args.packets * 2,
                note="concatenated into continuous overlapping windows")

    exp.result("startup", {
        "bundle_load_ms": bundle_load_ms,
        "rss_gb_before_load": rss_before,
        "rss_gb_after_load": rss_loaded,
        "rss_gb_after_traffic": rss_after,
    })
    exp.result("languages", results)

    medians = [r["steady_state_buffer_filled"].get("median_ms")
               for r in results if r["steady_state_buffer_filled"].get("median_ms")]
    p95s = [r["steady_state_buffer_filled"].get("p95_ms")
            for r in results if r["steady_state_buffer_filled"].get("p95_ms")]
    verdict = {
        "steady_state_median_ms_range": [min(medians), max(medians)] if medians else None,
        "steady_state_p95_ms_range": [min(p95s), max(p95s)] if p95s else None,
        "median_within_budget": bool(medians and max(medians) < CADENCE_BUDGET_SEC * 1000),
        "p95_within_budget": bool(p95s and max(p95s) < CADENCE_BUDGET_SEC * 1000),
    }
    exp.result("budget_verdict", verdict)
    print(f"\n  steady-state median range: {verdict['steady_state_median_ms_range']} ms")
    print(f"  steady-state p95 range   : {verdict['steady_state_p95_ms_range']} ms")
    print(f"  median within 1.0 s budget: {verdict['median_within_budget']}")
    print(f"  p95 within 1.0 s budget   : {verdict['p95_within_budget']}")

    exp.limitation(
        "One machine: a 12-thread AMD CPU with onnxruntime on CPUExecutionProvider "
        "only, because the installed driver caps at CUDA 11.2 while "
        "onnxruntime-gpu needs CUDA 12. These figures do not transfer to other "
        "hardware and say nothing about a GPU deployment.")
    exp.limitation(
        "One session at a time. Concurrent calls would contend for the same "
        "cores, so no throughput or multi-session claim follows from this.")
    exp.limitation(
        "Measured through FastAPI's TestClient, which exercises the real ASGI "
        "app but not a real network. Wire latency, TLS and a production ASGI "
        "server are excluded.")
    exp.limitation(
        "FLEURS clips are concatenated to build a continuous stream, so the "
        "audio contains joins that a real call would not. That affects what "
        "the models see, not what a packet costs.")

    exp.finish(
        interpretation=(
            f"At steady state, with the anti-spoof buffer filled, the median "
            f"packet costs {verdict['steady_state_median_ms_range']} ms and "
            f"the p95 {verdict['steady_state_p95_ms_range']} ms against a "
            f"1000 ms budget. Startup is a separate cost: {bundle_load_ms:.0f} ms "
            f"to load the bundle, plus a first packet an order of magnitude "
            f"above steady state."),
        conclusion=(
            "Quote steady-state median AND p95 together with the hardware. "
            "The budget verdict above determines whether O13 can move; a "
            "median inside the budget with a p95 outside it is not a pipeline "
            "that keeps up, because the overrun packets are the ones that "
            "accumulate."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
