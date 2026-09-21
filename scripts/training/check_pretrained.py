"""Verifies the pretrained model stack actually loads and runs.

Step 7 of Phase 7. These are SMOKE TESTS, not evaluations: they prove a
checkpoint downloads, loads and produces an output of the expected shape on
synthetic audio. They do NOT measure accuracy, and nothing here may be quoted
as a performance figure (docs/ML_SPEC.md 8.5).

The application deliberately does not depend on any of this yet - the backend
still runs mock adapters. Integration is Phase 8.

Runs on CPU by default so it does not contend with a training run for VRAM.

Usage:
    python scripts/training/check_pretrained.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import date

import numpy as np
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "models", "evaluation", "pretrained_checks.json")
SAMPLE_RATE = 16_000

results: list[dict] = []


def record(name: str, model_id: str, status: str, detail: dict) -> None:
    results.append({"component": name, "model_id": model_id, "status": status, **detail})
    marker = "OK  " if status == "OK" else "FAIL"
    print(f"  [{marker}] {name:<22} {model_id}")
    for key, value in detail.items():
        print(f"           {key}: {value}")


def synthetic_speechlike(seconds: float = 2.0) -> np.ndarray:
    """Deterministic speech-band signal. NOT speech - it exercises shapes only."""
    rng = np.random.default_rng(20260921)
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False)
    signal = sum(0.3 * np.sin(2 * np.pi * f * t) for f in (140, 280, 560))
    signal += 0.05 * rng.standard_normal(t.shape)
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))
    return (signal * envelope).astype(np.float32)


def check_silero_vad() -> None:
    """Silero VAD - MIT, loaded from torch.hub (GitHub, no token required)."""
    try:
        started = time.perf_counter()
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad",
            force_reload=False, trust_repo=True, onnx=False,
        )
        get_speech_timestamps = utils[0]
        audio = torch.from_numpy(synthetic_speechlike(3.0))
        stamps = get_speech_timestamps(audio, model, sampling_rate=SAMPLE_RATE)
        record("Silero VAD", "snakers4/silero-vad", "OK", {
            "license": "MIT",
            "load_seconds": round(time.perf_counter() - started, 2),
            "segments_on_synthetic_input": len(stamps),
            "note": "Shape/run check only. Synthetic tone is not speech, so a "
                    "low segment count is expected and is not a quality signal.",
        })
    except Exception as exc:
        record("Silero VAD", "snakers4/silero-vad", "FAIL",
               {"error": f"{type(exc).__name__}: {exc}"})


def check_ecapa() -> None:
    """ECAPA-TDNN speaker embeddings - SpeechBrain, Apache-2.0, public."""
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except Exception as exc:
        record("ECAPA-TDNN", "speechbrain/spkrec-ecapa-voxceleb", "SKIPPED",
               {"reason": f"speechbrain not installed: {type(exc).__name__}"})
        return
    try:
        started = time.perf_counter()
        cache = os.path.join(ROOT, "models", "artifacts", "_pretrained", "ecapa")
        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb", savedir=cache,
            run_opts={"device": "cpu"},
        )
        audio = torch.from_numpy(synthetic_speechlike(3.0)).unsqueeze(0)
        embedding = classifier.encode_batch(audio)
        record("ECAPA-TDNN", "speechbrain/spkrec-ecapa-voxceleb", "OK", {
            "license": "Apache-2.0",
            "load_seconds": round(time.perf_counter() - started, 2),
            "embedding_shape": list(embedding.shape),
            "note": "Produces a speaker embedding. Speaker consistency still "
                    "requires an enrolled reference (BLOCKERS O3), so this "
                    "remains unusable end-to-end.",
        })
    except Exception as exc:
        record("ECAPA-TDNN", "speechbrain/spkrec-ecapa-voxceleb", "FAIL",
               {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})


def check_aasist_checkpoint() -> None:
    """AASIST anti-spoofing - checkpoint availability from the official repo."""
    import urllib.request
    url = ("https://raw.githubusercontent.com/clovaai/aasist/main/models/weights/AASIST.pth")
    cache_dir = os.path.join(ROOT, "models", "artifacts", "_pretrained", "aasist")
    os.makedirs(cache_dir, exist_ok=True)
    dst = os.path.join(cache_dir, "AASIST.pth")
    try:
        started = time.perf_counter()
        if not os.path.exists(dst):
            urllib.request.urlretrieve(url, dst)
        size = os.path.getsize(dst)
        state = torch.load(dst, map_location="cpu", weights_only=True)
        record("AASIST", "clovaai/aasist", "OK", {
            "license": "MIT (repo LICENSE)",
            "load_seconds": round(time.perf_counter() - started, 2),
            "checkpoint_bytes": size,
            "tensors_in_state_dict": len(state),
            "note": "Checkpoint loads. The AASIST model CLASS is not vendored "
                    "here, so no forward pass was run. Wiring it is Phase 8.",
        })
    except Exception as exc:
        record("AASIST", "clovaai/aasist", "FAIL",
               {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})


def check_indic_asr() -> None:
    """AI4Bharat Indic ASR - gated:auto, needs an HF token."""
    model_id = "ai4bharat/indicwav2vec-hindi"
    try:
        from transformers import AutoModelForCTC, AutoProcessor
        started = time.perf_counter()
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModelForCTC.from_pretrained(model_id).eval()
        audio = synthetic_speechlike(2.0)
        inputs = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            logits = model(**inputs).logits
        transcript = processor.batch_decode(logits.argmax(dim=-1))[0]
        record("Indic ASR (Hindi)", model_id, "OK", {
            "license": "Apache-2.0",
            "load_seconds": round(time.perf_counter() - started, 2),
            "logits_shape": list(logits.shape),
            "vocab_size": logits.shape[-1],
            "decoded_on_synthetic_input": repr(transcript[:60]),
            "note": "Synthetic tone is not speech, so the decode is meaningless "
                    "by design. This confirms load + forward + decode only.",
        })
    except Exception as exc:
        record("Indic ASR (Hindi)", model_id, "FAIL",
               {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})


def main() -> None:
    print("Pretrained stack smoke tests (CPU). Shapes only - no accuracy measured.\n")
    check_silero_vad()
    check_aasist_checkpoint()
    check_ecapa()
    check_indic_asr()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "checked_at": str(date.today()),
        "purpose": "Availability and load verification only. No accuracy measured.",
        "torch": torch.__version__,
        "results": results,
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"\n  {ok}/{len(results)} components loaded. Report: {OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
