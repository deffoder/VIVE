"""Reproducible audio preprocessing to the VIVE canonical format.

Step 4 of Phase 7. Converts arbitrary input audio into the single format every
analyzer expects, so no model ever sees a sample rate or channel count it was
not built for:

    16 kHz - mono - 16-bit signed little-endian PCM

The same 2.0 s window / 1.0 s stride segmentation as the Android client
(`com.vive.audio.Packetizer`) and the backend session manager, so a window
produced here is byte-comparable with one produced on device.

Deterministic by construction: no random resampling, no dithering, no
normalisation that depends on batch statistics. The same input file always
yields the same windows.

Self-test (no corpus required):
    python scripts/setup/preprocess_audio.py --self-test

Convert a directory:
    python scripts/setup/preprocess_audio.py --input data/raw/audio --output data/processed/audio
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import wave
from dataclasses import dataclass, asdict

import numpy as np

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes, 16-bit
WINDOW_SECONDS = 2.0
STRIDE_SECONDS = 1.0


@dataclass(frozen=True)
class AudioStats:
    """Measured properties. Nothing here is estimated or inferred."""

    duration_sec: float
    rms: float
    peak: float
    clipping_ratio: float
    dc_offset: float


def read_wav(path: str) -> tuple[np.ndarray, int, int]:
    """Reads a WAV into float32 in [-1, 1], plus its rate and channel count."""
    with wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())

    if width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width: {width} bytes")

    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate, channels


def to_mono(data: np.ndarray) -> np.ndarray:
    """Averages channels. Averaging rather than channel-picking keeps energy
    from both legs of a two-party call."""
    return data if data.ndim == 1 else data.mean(axis=1)


def resample_linear(data: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Deterministic linear resampling.

    Linear interpolation is not the highest-fidelity method - a windowed-sinc
    filter would be better and is what a production path should use. It is
    chosen here because it is dependency-free and exactly reproducible, and
    because this module's job is format normalisation, not restoration. The
    limitation is recorded rather than hidden.
    """
    if source_rate == target_rate:
        return data
    duration = len(data) / source_rate
    target_length = int(round(duration * target_rate))
    source_positions = np.linspace(0, len(data) - 1, num=len(data))
    target_positions = np.linspace(0, len(data) - 1, num=target_length)
    return np.interp(target_positions, source_positions, data).astype(np.float32)


def measure(data: np.ndarray) -> AudioStats:
    """Computes only what is directly measurable from the samples."""
    if data.size == 0:
        return AudioStats(0.0, 0.0, 0.0, 0.0, 0.0)
    peak = float(np.abs(data).max())
    clipped = int((np.abs(data) >= 0.999).sum())
    return AudioStats(
        duration_sec=round(len(data) / SAMPLE_RATE, 4),
        rms=round(float(np.sqrt((data.astype(np.float64) ** 2).mean())), 6),
        peak=round(peak, 6),
        clipping_ratio=round(clipped / len(data), 6),
        dc_offset=round(float(data.mean()), 6),
    )


def to_pcm16(data: np.ndarray) -> bytes:
    """Clips to [-1, 1] and converts to 16-bit LE. Clipping is explicit so a
    hot input is truncated predictably rather than wrapping."""
    return (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def window_stream(pcm: bytes) -> list[dict]:
    """Segments canonical PCM into overlapping analysis windows.

    Matches the Android packetizer exactly: 2 s wide, advancing 1 s, so
    consecutive windows overlap and a window is NOT a partition of the call.
    """
    bytes_per_second = SAMPLE_RATE * SAMPLE_WIDTH
    window_bytes = int(WINDOW_SECONDS * bytes_per_second)
    stride_bytes = int(STRIDE_SECONDS * bytes_per_second)

    windows = []
    position = 0
    sequence = 0
    while position + window_bytes <= len(pcm):
        sequence += 1
        start = position / bytes_per_second
        windows.append({
            "seq": sequence,
            "packet_id": f"P{sequence:03d}",
            "start_sec": round(start, 3),
            "end_sec": round(start + WINDOW_SECONDS, 3),
            "bytes": window_bytes,
            "sha256": hashlib.sha256(pcm[position:position + window_bytes]).hexdigest()[:16],
        })
        position += stride_bytes
    return windows


def preprocess_file(path: str) -> dict:
    raw, rate, channels = read_wav(path)
    mono = to_mono(raw)
    resampled = resample_linear(mono, rate, SAMPLE_RATE)
    pcm = to_pcm16(resampled)
    return {
        "source_path": path,
        "source_rate": rate,
        "source_channels": channels,
        "target_rate": SAMPLE_RATE,
        "target_channels": CHANNELS,
        "encoding": "pcm_s16le",
        "measurements": asdict(measure(resampled)),
        "windows": window_stream(pcm),
        "pcm": pcm,
    }


def self_test() -> int:
    """Verifies the pipeline on generated audio. No corpus required."""
    print("Self-test on generated audio (no corpus needed)\n")
    failures = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        if condition:
            print(f"  [PASS] {name}")
        else:
            failures += 1
            print(f"  [FAIL] {name}  {detail}")

    # Stereo, 44.1 kHz input - the common real-world case.
    duration = 5.0
    source_rate = 44_100
    t = np.linspace(0, duration, int(source_rate * duration), endpoint=False)
    left = 0.4 * np.sin(2 * np.pi * 220 * t)
    right = 0.4 * np.sin(2 * np.pi * 330 * t)
    stereo = np.stack([left, right], axis=1).astype(np.float32)

    mono = to_mono(stereo)
    check("stereo collapses to mono", mono.ndim == 1 and len(mono) == len(stereo))

    resampled = resample_linear(mono, source_rate, SAMPLE_RATE)
    expected = int(round(duration * SAMPLE_RATE))
    check("resampled to 16 kHz", abs(len(resampled) - expected) <= 1,
          f"got {len(resampled)}, expected {expected}")

    check("resampling is deterministic",
          np.array_equal(resampled, resample_linear(mono, source_rate, SAMPLE_RATE)))

    pcm = to_pcm16(resampled)
    check("PCM is 16-bit", len(pcm) == len(resampled) * SAMPLE_WIDTH)

    windows = window_stream(pcm)
    check("windows produced", len(windows) == 4, f"got {len(windows)}")
    check("windows are 2 s wide",
          all(abs(w["end_sec"] - w["start_sec"] - 2.0) < 1e-6 for w in windows))
    check("stride is 1 s and windows overlap",
          all(b["start_sec"] - a["start_sec"] == 1.0 and b["start_sec"] < a["end_sec"]
              for a, b in zip(windows, windows[1:])))
    check("packet ids are zero-padded and sequential",
          [w["packet_id"] for w in windows] == ["P001", "P002", "P003", "P004"])

    stats = measure(resampled)
    check("rms is measured and positive", stats.rms > 0)
    check("no false clipping on a clean signal", stats.clipping_ratio == 0.0)

    hot = np.ones(SAMPLE_RATE, dtype=np.float32) * 1.5
    check("clipping is detected on a hot signal",
          measure(np.clip(hot, -1.0, 1.0)).clipping_ratio == 1.0)

    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    check("silence measures zero rms", measure(silence).rms == 0.0)

    short = to_pcm16(np.zeros(int(SAMPLE_RATE * 1.5), dtype=np.float32))
    check("audio shorter than one window yields no windows",
          len(window_stream(short)) == 0)

    print(f"\n  {'ALL PASS' if failures == 0 else str(failures) + ' FAILED'}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", help="directory of .wav files")
    parser.add_argument("--output", help="directory for canonical PCM + sidecars")
    args = parser.parse_args()

    if args.self_test or not args.input:
        return self_test()

    os.makedirs(args.output, exist_ok=True)
    processed = 0
    for name in sorted(os.listdir(args.input)):
        if not name.lower().endswith(".wav"):
            continue
        result = preprocess_file(os.path.join(args.input, name))
        stem = os.path.splitext(name)[0]
        with open(os.path.join(args.output, f"{stem}.pcm"), "wb") as handle:
            handle.write(result.pop("pcm"))
        with open(os.path.join(args.output, f"{stem}.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        processed += 1
        print(f"  {name}: {result['source_rate']} Hz x{result['source_channels']} "
              f"-> 16 kHz mono, {len(result['windows'])} windows")

    print(f"\n  processed {processed} file(s) into {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
