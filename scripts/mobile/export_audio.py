"""Exports the on-device audio models - Silero VAD and ECAPA-TDNN - and proves them.

ECAPA-TDNN
----------
SpeechBrain computes its filterbank through `torch.stft(return_complex=True)`,
which does not export to ONNX. The STFT is re-expressed here as a fixed-weight
conv1d whose kernels are the Hamming-windowed DFT basis - the same arithmetic,
in real-valued ops - and SpeechBrain's own Filterbank module, sentence mean
normalisation and ECAPA_TDNN follow unchanged. The whole path, waveform in,
192-d embedding out, is one graph, so the phone does no feature engineering
of its own that could drift.

Fidelity is measured, not assumed: cosine between the ONNX embedding and
SpeechBrain `encode_batch` on real LibriSpeech speech.

Speaker protocol and threshold
------------------------------
The app enrols from >= 3 s of speech and compares each 2 s analysis window
against that reference. This script measures THAT protocol on LibriSpeech
test-clean (real speaker_id): genuine = enrolment and window from different
utterances of one speaker, impostor = different speakers. The MATCH/MISMATCH
threshold is the EER point of that measurement, written to the manifest with
its provenance. It is not tuned on the phone's own audio - nothing labelled
exists for that - and the app says so.

Silero VAD
----------
The official `silero_vad.onnx` (MIT) from the same release as the JIT the
backend runs. Per-frame speech probabilities are compared against the JIT.

Outputs (git-ignored models/artifacts/mobile/):
    ecapa.onnx, silero_vad.onnx, audio_manifest.json
    eval/speaker/*.wav, eval/speaker_eval.json   (device parity + protocol)
Report (tracked): models/evaluation/mobile/audio_export_eval.json

Usage:
    python scripts/mobile/export_audio.py [--speakers 20]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ART = os.path.join(ROOT, "models", "artifacts")
OUT = os.path.join(ART, "mobile")
ECAPA_DIR = os.path.join(ART, "_pretrained", "ecapa")
VAD_JIT = os.path.join(ART, "_pretrained", "silero-vad", "silero_vad.jit")
VAD_ONNX_SRC = os.path.expanduser(
    "~/.cache/torch/hub/snakers4_silero-vad_master/src/silero_vad/data/silero_vad.onnx")
REPORT = os.path.join(ROOT, "models", "evaluation", "mobile", "audio_export_eval.json")

SR = 16_000
WINDOW = 32_000
ENROL_MIN = 48_000        # 3 s, as the backend enforces
SEED = 20260923


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ecapa():
    from speechbrain.inference import EncoderClassifier
    return EncoderClassifier.from_hparams(source=ECAPA_DIR, savedir=ECAPA_DIR,
                                          run_opts={"device": "cpu"})


def build_exportable(clf):
    import torch

    stft = clf.mods.compute_features.compute_STFT
    n_fft, hop, win = stft.n_fft, stft.hop_length, stft.win_length
    if not (stft.center and stft.pad_mode == "constant" and not stft.normalized_stft
            and stft.onesided and win == n_fft):
        raise SystemExit("SpeechBrain STFT configuration differs from what this "
                         "export reproduces; refusing to export a different transform")
    window = stft.window.detach().double()
    n = torch.arange(n_fft, dtype=torch.float64)
    k = torch.arange(n_fft // 2 + 1, dtype=torch.float64)[:, None]
    angle = 2 * torch.pi * k * n / n_fft
    real = (torch.cos(angle) * window)[:, None, :].float()
    imag = (-torch.sin(angle) * window)[:, None, :].float()

    class Ecapa(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("real", real)
            self.register_buffer("imag", imag)
            self.fbanks = clf.mods.compute_features.compute_fbanks
            self.embed = clf.mods.embedding_model

        def forward(self, wav):                         # [1, T]
            x = torch.nn.functional.pad(wav[:, None, :], (n_fft // 2, n_fft // 2))
            re = torch.nn.functional.conv1d(x, self.real, stride=hop)
            im = torch.nn.functional.conv1d(x, self.imag, stride=hop)
            power = (re * re + im * im).transpose(1, 2)  # [1, frames, 201]
            feats = self.fbanks(power)
            feats = feats - feats.mean(dim=1, keepdim=True)   # sentence mean norm
            emb = self.embed(feats, torch.ones(1))
            return emb.reshape(1, -1)

    return Ecapa().eval()


def librispeech(speakers: int, per_speaker: int = 3):
    """First `per_speaker` utterances >= 3.5 s from each of `speakers` speakers."""
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("openslr/librispeech_asr", "clean", split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    by: dict[int, list] = {}
    for row in ds:
        sid = int(row["speaker_id"])
        if len(by) >= speakers and sid not in by:
            continue
        got = by.setdefault(sid, [])
        if len(got) >= per_speaker:
            if len(by) >= speakers and all(len(v) >= per_speaker for v in by.values()):
                break
            continue
        wave, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        if rate == SR and len(wave) >= int(3.5 * SR):
            got.append(wave)
    return {s: v for s, v in by.items() if len(v) >= per_speaker}


def quantised(wave):
    pcm = np.clip(np.round(wave * 32768.0), -32768, 32767).astype("<i2")
    return pcm, pcm.astype("float32") / 32768.0


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def eer(genuine, impostor):
    scores = sorted(set(genuine + impostor))
    best = None
    for t in scores:
        frr = sum(g < t for g in genuine) / len(genuine)
        far = sum(i >= t for i in impostor) / len(impostor)
        if best is None or abs(frr - far) < best[0]:
            best = (abs(frr - far), t, frr, far)
    _, t, frr, far = best
    top_impostor, low_genuine = max(impostor), min(genuine)
    if low_genuine > top_impostor:
        # Perfect separation: every score in the gap is an EER point, and the
        # first one scanned is the lowest genuine score - zero margin on the
        # genuine side. The middle of the gap is the one choice that favours
        # neither error on audio this measurement did not see.
        t = (top_impostor + low_genuine) / 2
    return {"eer": round((frr + far) / 2, 4), "threshold": round(t, 4),
            "frr_at_threshold": round(sum(g < t for g in genuine) / len(genuine), 4),
            "far_at_threshold": round(sum(i >= t for i in impostor) / len(impostor), 4),
            "max_impostor": round(top_impostor, 4), "min_genuine": round(low_genuine, 4)}


def vad_parity(clips) -> dict:
    import onnxruntime as ort
    import torch

    jit = torch.jit.load(VAD_JIT, map_location="cpu").eval()
    sess = ort.InferenceSession(os.path.join(OUT, "silero_vad.onnx"),
                                providers=["CPUExecutionProvider"])
    worst, frames = 0.0, 0
    for wave in clips:
        x = wave[:WINDOW]
        jit.reset_states()
        state = np.zeros((2, 1, 128), dtype="float32")
        context = np.zeros((1, 64), dtype="float32")
        for i in range(len(x) // 512):
            chunk = x[i * 512:(i + 1) * 512][None, :]
            with torch.no_grad():
                pj = float(jit(torch.from_numpy(chunk[0].copy()), SR))
            inp = np.concatenate([context, chunk], axis=1)
            out, state = sess.run(None, {"input": inp, "state": state,
                                         "sr": np.array(SR, dtype="int64")})
            context = inp[:, -64:]
            worst = max(worst, abs(pj - float(out[0][0])))
            frames += 1
    return {"frames": frames, "max_abs_prob_diff_vs_jit": round(worst, 6)}


def main() -> int:
    import onnxruntime as ort
    import soundfile as sf
    import torch

    parser = argparse.ArgumentParser()
    parser.add_argument("--speakers", type=int, default=20)
    args = parser.parse_args()
    os.makedirs(OUT, exist_ok=True)

    # --- ECAPA export ----------------------------------------------------
    clf = load_ecapa()
    model = build_exportable(clf)
    path = os.path.join(OUT, "ecapa.onnx")
    torch.onnx.export(model, (torch.zeros(1, WINDOW),), path,
                      input_names=["wav"], output_names=["embedding"],
                      dynamic_axes={"wav": {1: "samples"}},
                      opset_version=17, do_constant_folding=True, dynamo=False)
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])

    def onnx_embed(x):
        return sess.run(None, {"wav": x[None, :].astype("float32")})[0][0]

    speakers = librispeech(args.speakers)
    print(f"librispeech: {len(speakers)} speakers")

    # Fidelity against SpeechBrain on real speech, full and 2 s.
    fidelity = []
    for waves in list(speakers.values())[:8]:
        for x in (waves[0], waves[0][:WINDOW]):
            with torch.no_grad():
                ref = clf.encode_batch(torch.from_numpy(x[None, :])).squeeze().numpy()
            fidelity.append(cos(ref, onnx_embed(x)))

    # Protocol: enrol on utterance 0 (full, >= 3 s), probe 2 s windows of
    # utterances 1 and 2 of every speaker.
    root = os.path.join(OUT, "eval", "speaker")
    os.makedirs(root, exist_ok=True)
    items, enrol, probes = [], {}, []
    for sid, waves in speakers.items():
        for u, wave in enumerate(waves):
            pcm, x = quantised(wave if u == 0 else wave[:WINDOW])
            name = f"speaker/{sid}_{u}.wav"
            sf.write(os.path.join(OUT, "eval", name), pcm, SR, subtype="PCM_16")
            emb = onnx_embed(x)
            items.append({"speaker": sid, "utt": u, "wav": name,
                          "role": "enrol" if u == 0 else "probe",
                          "desktop_embedding": [round(float(v), 6) for v in emb]})
            (enrol.__setitem__(sid, emb) if u == 0 else probes.append((sid, emb)))
    genuine = [cos(enrol[s], e) for s, e in probes]
    impostor = [cos(enrol[o], e) for s, e in probes for o in enrol if o != s]
    protocol = eer(genuine, impostor)
    protocol.update({"genuine_pairs": len(genuine), "impostor_pairs": len(impostor),
                     "genuine_median": round(float(np.median(genuine)), 4),
                     "impostor_median": round(float(np.median(impostor)), 4)})
    print("protocol", protocol)
    with io.open(os.path.join(OUT, "eval", "speaker_eval.json"), "w", encoding="utf-8") as fh:
        json.dump({"items": items}, fh)

    # --- Silero VAD ------------------------------------------------------
    shutil.copyfile(VAD_ONNX_SRC, os.path.join(OUT, "silero_vad.onnx"))
    vad = vad_parity([w[0] for w in list(speakers.values())[:6]])
    print("vad", vad)

    manifest = {"models": {
        "ecapa": {"file": "ecapa.onnx", "bytes": os.path.getsize(path), "sha256": sha256(path),
                  "source": "speechbrain/spkrec-ecapa-voxceleb", "license": "Apache-2.0",
                  "version": "ecapa-tdnn-voxceleb-v1-onnx", "embedding_dim": 192,
                  "min_enrol_samples": ENROL_MIN,
                  "match_threshold": protocol["threshold"],
                  "threshold_source": (
                      "EER point, enrol >= 3 s vs 2 s window, LibriSpeech test-clean "
                      f"({protocol['genuine_pairs']} genuine / {protocol['impostor_pairs']} "
                      "impostor pairs); clean read English, not call audio")},
        "vad": {"file": "silero_vad.onnx",
                "bytes": os.path.getsize(os.path.join(OUT, "silero_vad.onnx")),
                "sha256": sha256(os.path.join(OUT, "silero_vad.onnx")),
                "source": "snakers4/silero-vad", "license": "MIT",
                "version": "silero-vad-v5-onnx", "frame": 512, "context": 64},
    }}
    with io.open(os.path.join(OUT, "audio_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    report = {"ecapa_fidelity_cosine_vs_speechbrain": {
                  "min": round(min(fidelity), 6), "n": len(fidelity)},
              "speaker_protocol": protocol, "vad": vad,
              "ecapa_size_mb": round(os.path.getsize(path) / 1e6, 1)}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with io.open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
