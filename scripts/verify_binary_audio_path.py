"""Proves the exact transport the Android microphone uses, end to end.

The phone sends RAW BINARY WebSocket frames - `OkHttpEventStream.sendAudio`
calls `webSocket.send(ByteString)`. Every earlier verification script used the
scripted JSON path (`client.audio` with a transcript or `audio_b64`), so the
transport the live microphone actually depends on had never been exercised
against real models.

This sends real speech as binary 2.0 s windows at a 1.0 s stride - byte for
byte what `Packetizer` emits on the device - to a running REAL-mode backend,
and reports what came back.

What it proves: real audio over the real transport reaches the real ML
pipeline and produces real packets with real transcripts.

What it does NOT prove: that `AudioRecord` captures correctly on a specific
handset. Only the device can show that; `scripts/verify_android_live.py`
covers it.

Requires a backend already running in real mode:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Usage:
    python scripts/verify_binary_audio_path.py --language hi
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
SAMPLE_RATE = 16_000
WINDOW_SEC = 2.0
STRIDE_SEC = 1.0


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BACKEND + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def get(path: str):
    with urllib.request.urlopen(BACKEND + path, timeout=30) as response:
        return json.loads(response.read().decode())


def fleurs_windows(config: str, count: int) -> list[bytes]:
    """Real speech, packetised exactly as the device packetises it."""
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))

    buffer = np.zeros(0, dtype="float32")
    needed = int((WINDOW_SEC + STRIDE_SEC * (count - 1)) * SAMPLE_RATE)
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
    windows = []
    for i in range(count):
        chunk = buffer[i * stride:i * stride + width]
        if chunk.size < width:
            break
        windows.append((np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
    return windows


async def stream(session_id: str, windows: list[bytes]) -> list[str]:
    import websockets

    seen: list[str] = []
    url = f"{WS}/api/v1/sessions/{session_id}/stream"
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as socket:
        await socket.recv()                       # session.state
        for index, pcm in enumerate(windows, start=1):
            # BINARY frame - the Android path. Not JSON, not base64.
            await socket.send(pcm)
            for _ in range(8):
                frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=60))
                seen.append(frame["type"])
                if frame["type"] == "risk.update":
                    break
            print(f"  window {index}/{len(windows)} sent ({len(pcm)} bytes)")
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", default="hi", choices=["hi", "ta"])
    parser.add_argument("--windows", type=int, default=6)
    args = parser.parse_args()

    config = {"hi": "hi_in", "ta": "ta_in"}[args.language]

    version = get("/api/v1/version")
    print(f"backend adapter_mode = {version['adapter_mode']}")
    if version["adapter_mode"] != "real":
        print("  refusing to run: this proves nothing unless the models are real")
        return 1

    ready = get("/api/v1/ready")["adapters"]
    for name, info in ready.items():
        print(f"  {name:<10}{info['status']:<18}{info['mode']}")

    print(f"\npreparing {args.windows} real {args.language} windows ...")
    windows = fleurs_windows(config, args.windows)
    if not windows:
        print("  no audio available")
        return 1

    session_id = post("/api/v1/sessions",
                      {"source_type": "IN_APP", "language": args.language})["session_id"]
    print(f"session {session_id}\n")

    frames = asyncio.run(stream(session_id, windows))

    packets = get(f"/api/v1/sessions/{session_id}/packets")
    print(f"\nframe types seen: {sorted(set(frames))}")
    print(f"packets produced: {len(packets)}")

    for packet in packets:
        asr = packet.get("asr", {})
        print(f"  {packet['packet_id']}  {packet['timestamp']}  "
              f"lang={packet['language']}  mode={packet.get('adapter_mode')}")
        print(f"     asr      {asr.get('status'):<20} {str(asr.get('transcript'))[:60]}")
        print(f"     intent   {packet['intent']['status']:<20} {packet['intent']['label']}")
        print(f"     aasist   {packet['aasist']['status']:<20} {packet['aasist']['score']}")
        print(f"     risk     {packet['risk']['score']} {packet['risk']['level']} "
              f"conf={packet['risk']['confidence']}")

    transcripts = [p["asr"].get("transcript") for p in packets
                   if p["asr"].get("transcript")]
    real = all(p.get("adapter_mode") == "real" for p in packets)

    print("\n--- verdict ---")
    print(f"  binary frames accepted            : {'yes' if packets else 'NO'}")
    print(f"  packets carry real adapter output : {'yes' if real else 'NO'}")
    print(f"  non-empty transcripts             : {len(transcripts)}/{len(packets)}")

    out = os.path.join(ROOT, "models", "evaluation", "phase10",
                       f"binary_audio_path_{args.language}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "transport": "raw binary WebSocket frames, as the Android client sends",
            "language": args.language,
            "adapter_mode": version["adapter_mode"],
            "session_id": session_id,
            "windows_sent": len(windows),
            "packets": len(packets),
            "non_empty_transcripts": len(transcripts),
            "all_packets_real": real,
            "sample": packets[-1] if packets else None,
        }, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")

    return 0 if packets and real else 1


if __name__ == "__main__":
    sys.exit(main())
