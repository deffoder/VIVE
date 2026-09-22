"""Builds a small, fully-provenanced synthetic-speech probe set.

Why this exists
---------------
`BLOCKERS.md` O5 records that no anti-spoofing corpus was acquired: ASVspoof
requires a registration agreement that cannot be completed programmatically. So
VIVE has never measured AASIST against anything, and O12 rests on a 4-clip spot
check. That is not enough to say whether AASIST works, and it is not enough to
answer the Phase 9 question of whether short windows can carry anti-spoofing
evidence.

A discrimination measurement needs two classes. Bonafide speech is available
under CC-BY-4.0 (FLEURS). The missing half is synthetic speech, and it can be
generated from openly-licensed components rather than obtained from a corpus
that needs a signed agreement.

What this is NOT
----------------
This is **not** ASVspoof and does not replace it. It is a probe set with
exactly one synthesis family, in one language, from one vocoder, at one
sampling rate. Any figure computed from it describes AASIST's behaviour against
*that* family and nothing wider. It cannot support a general anti-spoofing
claim, an ASVspoof-comparable EER, or any statement about generators it does
not contain (`BLOCKERS.md` P2).

Its value is narrow and real: it converts "no measurement exists" into "one
measured operating point exists, with its scope written down".

Licensing, verified against repository metadata before download
---------------------------------------------------------------
  microsoft/speecht5_tts          MIT          ungated
  microsoft/speecht5_hifigan      MIT          ungated
  Matthijs/cmu-arctic-xvectors    MIT          ungated
  google/fleurs                   CC-BY-4.0    ungated   (bonafide half)

`facebook/mms-tts-{hin,tam}` would have given Hindi and Tamil synthesis but is
CC-BY-NC-4.0, which forbids commercial use - rejected for the same reason
`facebook/mms-1b-all` was rejected during the Phase 7 Tamil survey.
`ai4bharat/indic-parler-tts` is Apache-2.0 but `gated: auto`, so it needs the
account holder to accept terms; it was not downloaded.

That leaves the probe **English-only**, which is itself a stated limitation:
VIVE's priority languages are Hindi, Tamil and English, and this probe
exercises only the third.

Output (git-ignored: `*.wav` and `models/artifacts/**`)
    models/artifacts/_probe/spoof/*.wav
    models/artifacts/_probe/bonafide/*.wav
    models/artifacts/_probe/manifest.json

Usage:
    python scripts/evaluation/build_spoof_probe.py [--clips 60]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, seed_everything  # noqa: E402

PROBE_DIR = os.path.join(ROOT, "models", "artifacts", "_probe")
SAMPLE_RATE = 16_000
MIN_SAMPLES = 64_600          # AASIST's native window; clips must reach it

TTS_DIR = os.path.join(ROOT, "models", "artifacts", "_pretrained", "speecht5_tts")
VOC_DIR = os.path.join(ROOT, "models", "artifacts", "_pretrained", "speecht5_hifigan")

# Sentences to synthesise. Deliberately in the register VIVE cares about -
# social-engineering phone calls - so the probe exercises the kind of speech
# the product would actually meet, not read-aloud news copy. They are written
# here rather than drawn from the corpus so no manifest text is duplicated
# into an audio artifact.
PROMPTS = [
    "Hello, I am calling from the bank security department about your account.",
    "We have detected an unauthorized transaction on your card this morning.",
    "Please confirm the one time password that was just sent to your phone.",
    "Your account will be suspended within the hour unless you act now.",
    "I need to verify your identity before I can release the hold on your funds.",
    "Do not discuss this call with anyone, it is part of an active investigation.",
    "Sir, your electricity connection will be disconnected tonight at nine.",
    "A warrant has been issued in your name and you must respond immediately.",
    "Kindly install the application I am sending so I can assist you remotely.",
    "Congratulations, you have won a cash prize in our customer loyalty draw.",
    "The refund has been approved but I need your card number to process it.",
    "This is a courtesy call regarding the renewal of your insurance policy.",
    "Please transfer the amount to the safe account I am about to provide.",
    "Your parcel is held at customs and a small fee is required for release.",
    "I am from the technical team and your computer is sending us error reports.",
]


def speaker_embeddings():
    """One 512-dim x-vector per distinct CMU Arctic speaker.

    Read straight out of the repository's `spkrec-xvect.zip` rather than
    through `load_dataset`, which cannot open this repo any more: it ships a
    loading script, and `datasets` 5.x refuses to execute dataset scripts.
    Reading the archive avoids the script entirely, which is the safer path
    regardless.

    Filenames encode the speaker (`cmu_us_bdl_arctic-...`), so picking one
    embedding per speaker prefix gives genuinely different voices rather than
    several samples of the same one.
    """
    import io
    import zipfile

    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download

    path = hf_hub_download("Matthijs/cmu-arctic-xvectors", "spkrec-xvect.zip",
                           repo_type="dataset")
    archive = zipfile.ZipFile(path)
    chosen: dict[str, object] = {}
    for name in sorted(archive.namelist()):
        if not name.endswith(".npy"):
            continue
        speaker = os.path.basename(name).split("-wav-")[0]
        if speaker in chosen:
            continue
        vector = np.load(io.BytesIO(archive.read(name)))
        chosen[speaker] = torch.tensor(vector).unsqueeze(0)
    return list(chosen.items())


def synthesise(count: int) -> list[tuple[str, "object"]]:
    import numpy as np
    import torch
    from transformers import (SpeechT5ForTextToSpeech, SpeechT5HifiGan,
                              SpeechT5Processor)

    print("loading SpeechT5 (MIT) ...")
    processor = SpeechT5Processor.from_pretrained(TTS_DIR)
    model = SpeechT5ForTextToSpeech.from_pretrained(TTS_DIR).eval()
    vocoder = SpeechT5HifiGan.from_pretrained(VOC_DIR).eval()

    named = speaker_embeddings()
    speakers = [vector for _name, vector in named]
    print(f"  {len(speakers)} distinct speakers: "
          f"{', '.join(name for name, _v in named)}")

    out: list[tuple[str, object]] = []
    idx = 0
    while len(out) < count:
        prompt = PROMPTS[idx % len(PROMPTS)]
        speaker = speakers[idx % len(speakers)]
        # Pairing a different speaker with each repeat of a prompt keeps the
        # clips distinct; the vocoder output differs materially per speaker.
        inputs = processor(text=prompt, return_tensors="pt")
        with torch.no_grad():
            wave = model.generate_speech(inputs["input_ids"], speaker,
                                         vocoder=vocoder).numpy()
        idx += 1
        # SpeechT5 emits 16 kHz, which is already VIVE's rate - no resampling.
        if wave.size < MIN_SAMPLES:
            # Too short for a native AASIST window. Concatenate the next
            # utterance from the SAME speaker rather than padding: padding is
            # exactly the defect Phase 8 removed from the adapter.
            extra_prompt = PROMPTS[idx % len(PROMPTS)]
            inputs2 = processor(text=extra_prompt, return_tensors="pt")
            with torch.no_grad():
                wave2 = model.generate_speech(inputs2["input_ids"], speaker,
                                              vocoder=vocoder).numpy()
            idx += 1
            wave = np.concatenate([wave, wave2])
        if wave.size < MIN_SAMPLES:
            continue
        out.append((prompt, np.asarray(wave, dtype="float32")))
        print(f"  spoof {len(out):>3}/{count}  {wave.size/SAMPLE_RATE:.2f}s")
    return out


def collect_bonafide(count: int, config: str) -> list[tuple[str, object]]:
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    print(f"collecting bonafide FLEURS {config} (CC-BY-4.0) ...")
    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    out: list[tuple[str, object]] = []
    for row in ds:
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE or wave.size < MIN_SAMPLES:
            continue
        out.append((str(row.get("id", len(out))), np.asarray(wave, dtype="float32")))
        if len(out) >= count:
            break
    print(f"  {len(out)} bonafide clips")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=60,
                        help="clips per class")
    args = parser.parse_args()
    seed_everything()

    import soundfile as sf

    for sub in ("spoof", "bonafide"):
        os.makedirs(os.path.join(PROBE_DIR, sub), exist_ok=True)

    spoof = synthesise(args.clips)
    # Bonafide is drawn from both priority-language FLEURS configs so the
    # bonafide half is not a single acoustic domain.
    half = args.clips // 2
    bonafide = (collect_bonafide(half, "hi_in")
                + collect_bonafide(args.clips - half, "ta_in"))

    manifest = {
        "probe_id": "vive-aasist-probe-v1",
        "purpose": ("Two-class probe for AASIST. One synthesis family only; "
                    "not a substitute for ASVspoof."),
        "sample_rate": SAMPLE_RATE,
        "resampling_performed": False,
        "classes": {
            "spoof": {
                "count": len(spoof),
                "generator": "microsoft/speecht5_tts + microsoft/speecht5_hifigan",
                "license": "MIT",
                "license_status": "VERIFIED",
                "speaker_embeddings": "Matthijs/cmu-arctic-xvectors (MIT)",
                "language": "en",
                "native_sample_rate": SAMPLE_RATE,
            },
            "bonafide": {
                "count": len(bonafide),
                "source": "google/fleurs test (hi_in + ta_in)",
                "license": "CC-BY-4.0",
                "license_status": "VERIFIED",
                "language": "hi, ta",
                "native_sample_rate": SAMPLE_RATE,
            },
        },
        "known_confounds": [
            "The two classes differ in LANGUAGE as well as in authenticity: "
            "spoof is English, bonafide is Hindi and Tamil. A separation "
            "measured here could partly reflect language or channel rather "
            "than synthesis. This is the probe's most serious weakness and "
            "any number derived from it must carry it.",
            "The two classes differ in RECORDING CHANNEL: FLEURS is recorded "
            "read speech, the spoof half is vocoder output with no channel at "
            "all. AASIST is known to key on low-level channel cues.",
            "One synthesis family. Nothing here generalises to other "
            "generators (docs/BLOCKERS.md P2).",
        ],
        "rejected_alternatives": {
            "facebook/mms-tts-hin, facebook/mms-tts-tam":
                "CC-BY-NC-4.0 forbids commercial use",
            "ai4bharat/indic-parler-tts":
                "Apache-2.0 but gated:auto; needs account-holder acceptance, "
                "not downloaded",
            "ASVspoof2019 LA": "registration agreement required (O5)",
        },
    }

    for label, clips in (("spoof", spoof), ("bonafide", bonafide)):
        for i, (_tag, wave) in enumerate(clips):
            sf.write(os.path.join(PROBE_DIR, label, f"{label}_{i:04d}.wav"),
                     wave, SAMPLE_RATE, subtype="PCM_16")

    with open(os.path.join(PROBE_DIR, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(f"\nwrote {len(spoof)} spoof + {len(bonafide)} bonafide clips "
          f"to {os.path.relpath(PROBE_DIR, ROOT)}")
    print("NOTE: this probe is one synthesis family in one language. "
          "It does not establish general anti-spoofing performance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
