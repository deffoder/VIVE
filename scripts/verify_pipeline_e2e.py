"""Phase 8D: end-to-end verification of the real ML pipeline.

Drives real audio through the ACTUAL backend - HTTP session creation, the
WebSocket stream, the real adapter bundle, fusion, temporal risk and policy -
and measures what a packet really costs.

This is the measurement that matters for the real-time requirement. The
per-model figures from 8A-8C are component costs; a packet pays for all of
them plus fusion and transport. VIVE analyses a 2.0 s window every 1.0 s, so
the budget is 1.0 s of wall clock per packet.

Nothing here measures accuracy. A packet flowing end to end proves
integration; WER, EER and F1 come only from their own evaluations, and AASIST
has no VIVE-measured EER at all (docs/BLOCKERS.md O5, O12).

Run with an environment that has `datasets` + `soundfile` (models/.venv) and
the VIVE_*_MODEL_DIR variables set:

    python scripts/verify_pipeline_e2e.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import statistics
import sys
import time
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

EVAL_DIR = os.path.join(ROOT, "models", "evaluation")
SAMPLE_RATE = 16_000
WINDOW_SEC = 2.0
CADENCE_BUDGET_SEC = 1.0
PACKETS_PER_LANG = 6


def fleurs_pcm(config: str, n: int) -> list[bytes]:
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    out: list[bytes] = []
    take = int(SAMPLE_RATE * WINDOW_SEC)
    for row in ds:
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE or len(wave) < take:
            continue
        chunk = np.asarray(wave[:take], dtype=np.float32)
        out.append((np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
        if len(out) >= n:
            break
    return out


def run_language(client, lang: str, config: str) -> dict:
    print(f"\n=== {lang} ({config}) ===")
    windows = fleurs_pcm(config, PACKETS_PER_LANG)
    # Declare the language. There is no language-ID model, so a session that
    # says nothing decodes in the adapter default - which is how a Tamil
    # session was previously transcribed as Hindi.
    session_id = client.post("/api/v1/sessions",
                             json={"source_type": "VOIP",
                                   "language": lang}).json()["session_id"]

    latencies: list[int] = []
    first_ms: int | None = None
    frames: list[str] = []

    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as ws:
        ws.receive_json()                       # session.state
        for seq, pcm in enumerate(windows, start=1):
            began = time.perf_counter()
            # Canonical inbound frame (backend/app/ws/protocol.py ClientFrame):
            # type "client.audio" with audio_b64. The schema uses extra="forbid",
            # so any other shape is rejected and no packet is produced.
            ws.send_json({"type": "client.audio",
                          "audio_b64": base64.b64encode(pcm).decode(),
                          "speaker": "Caller"})
            for _ in range(8):
                frame = ws.receive_json()
                frames.append(frame["type"])
                if frame["type"] == "risk.update":
                    break
            wall_ms = int((time.perf_counter() - began) * 1000)
            if seq == 1:
                first_ms = wall_ms          # includes any lazy per-session setup
            else:
                latencies.append(wall_ms)

    packets = client.get(f"/api/v1/sessions/{session_id}/packets").json()
    median = statistics.median(latencies) if latencies else None

    # Field preservation: every packet must carry full traceability.
    required = ["packet_id", "session_id", "seq", "timestamp", "duration_sec",
                "language", "quality", "asr", "intent", "behavior", "aasist",
                "ecapa", "context", "ood", "risk", "adapter_mode"]
    missing = sorted({f for p in packets for f in required if f not in p})

    stage_ms = {}
    if packets:
        last = packets[-1]
        for key in ("asr", "intent", "behavior", "aasist", "ecapa"):
            stage_ms[key] = last.get(key, {}).get("inference_ms")

    sample = packets[-1] if packets else {}
    print(f"  packets: {len(packets)}   median end-to-end: {median} ms "
          f"({100 * (median or 0) / 1000 / CADENCE_BUDGET_SEC:.1f}% of budget)")
    print(f"  first packet: {first_ms} ms (includes per-session setup)")
    print(f"  per-stage inference_ms on the last packet: {stage_ms}")
    print(f"  adapter_mode: {sample.get('adapter_mode')}")
    print(f"  language={sample.get('language')} "
          f"asr={sample.get('asr', {}).get('status')} "
          f"intent={sample.get('intent', {}).get('status')} "
          f"behaviour={sample.get('behavior', {}).get('status')}")
    print(f"  risk: {sample.get('risk', {}).get('score')} "
          f"{sample.get('risk', {}).get('level')} "
          f"conf={sample.get('risk', {}).get('confidence')}")
    if missing:
        print(f"  MISSING PACKET FIELDS: {missing}")

    return {
        "language": lang,
        "packets": len(packets),
        "frame_types": sorted(set(frames)),
        "end_to_end_ms": {
            "median": median,
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "first_packet": first_ms,
            "excludes_first_packet": True,
        },
        "meets_cadence": bool(median is not None and median / 1000 < CADENCE_BUDGET_SEC),
        "stage_inference_ms_last_packet": stage_ms,
        "missing_packet_fields": missing,
        "adapter_mode": sample.get("adapter_mode"),
        "last_packet_statuses": {
            "asr": sample.get("asr", {}).get("status"),
            "intent": sample.get("intent", {}).get("status"),
            "behavior": sample.get("behavior", {}).get("status"),
            "aasist": sample.get("aasist", {}).get("status"),
            "ecapa": sample.get("ecapa", {}).get("status"),
        },
    }


def main() -> int:
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    settings = get_settings()
    print(f"adapter_mode: {settings.adapter_mode}")
    if settings.adapter_mode != "real":
        print("  set VIVE_ADAPTER_MODE=real and the VIVE_*_MODEL_DIR paths")
        return 1

    # The app builds its own bundle at startup. Read THAT one rather than
    # constructing a second: two bundles would cost ~66 s and ~2.5 GB twice,
    # and the numbers reported must describe the bundle actually serving
    # requests.
    app = create_app()
    load_began = time.perf_counter()
    with TestClient(app) as client:
        bundle_load_ms = int((time.perf_counter() - load_began) * 1000)
        infos = app.state.vive.adapters.infos()
        print(f"bundle loaded with the app in {bundle_load_ms} ms")
        for key, info in infos.items():
            print(f"  {key:<10}{str(info.mode):<6}{info.status:<18}"
                  f"{info.model_version:<34}{info.load_ms}ms")

        unavailable = [k for k, i in infos.items() if i.status.name not in
                       ("AVAILABLE", "NO_REFERENCE")]
        if unavailable:
            print(f"  not loaded: {unavailable} - pipeline reports their status")

        results = [run_language(client, "hi", "hi_in"),
                   run_language(client, "ta", "ta_in")]

    try:
        import psutil
        rss_gb = round(psutil.Process().memory_info().rss / 1e9, 3)
    except Exception:
        rss_gb = None

    record = {
        "verified_at": str(date.today()),
        "phase": "8D",
        "what_this_proves": (
            "Real audio flows through the real backend - session, WebSocket, "
            "all six real adapters, fusion, temporal risk and policy - and "
            "produces packets with full traceability. It measures COST, not "
            "accuracy."
        ),
        "bundle_load_ms": bundle_load_ms,
        "adapters": {k: {"mode": str(i.mode), "status": str(i.status),
                         "model_version": i.model_version, "load_ms": i.load_ms,
                         "execution_provider": i.execution_provider}
                     for k, i in infos.items()},
        "window_sec": WINDOW_SEC,
        "cadence_budget_sec": CADENCE_BUDGET_SEC,
        "process_rss_gb": rss_gb,
        "languages": results,
        "caveats": [
            "End-to-end packet cost on real audio, measured through the HTTP "
            "and WebSocket layers. Not comparable to the per-model figures.",
            "The first packet is reported separately; it carries per-session "
            "setup that later packets do not.",
            "No accuracy is measured here. AASIST has no VIVE-measured EER "
            "(BLOCKERS O5) and behaves unreliably out of domain (O12).",
            "Tamil intent and behaviour are UNSUPPORTED_LANGUAGE by design "
            "(BLOCKERS O11), not a pipeline failure.",
        ],
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "pipeline_e2e_8d.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)

    print(f"\nprocess RSS: {rss_gb} GB")
    print(f"wrote {out}")

    ok = all(r["packets"] > 0 and not r["missing_packet_fields"] for r in results)
    cadence = all(r["meets_cadence"] for r in results)
    print(f"\npackets produced with full fields : {'yes' if ok else 'NO'}")
    print(f"median packet within 1.0 s budget : {'yes' if cadence else 'NO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
