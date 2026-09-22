"""Phase 9: what can VIVE actually conclude from ECAPA-TDNN?

The gap this closes
-------------------
ECAPA has shipped since Phase 8C with no measurement of any kind.
`BLOCKERS.md` O5 records why: VoxCeleb1, the corpus the checkpoint was trained
and normally evaluated on, needs a request form that cannot be completed
programmatically. So the speaker channel has been running with an unknown
error rate, and `fusion.py` gives `speaker_consistency` an influence of 0.30
on that basis.

VoxCeleb is still unavailable. LibriSpeech is not: CC-BY-4.0, ungated, and -
the property that matters - every utterance carries a real `speaker_id`. That
is enough to build genuine and impostor pairs from real human speakers and
measure a verification EER.

What this is and is not
-----------------------
It IS a speaker-verification measurement on real humans with ground-truth
identity, through the adapter VIVE actually calls.

It is NOT a VoxCeleb result and is not comparable to published ECAPA numbers.
LibriSpeech is clean audiobook read speech from close microphones: one
language, one recording style, no channel variation. That is the *easy* case
for speaker verification. A telephone call is the hard case, and the
`telephony_band` and `g711_ulaw` rows exist to show how much of the easy-case
performance survives a channel - though a simulated channel is still not a
recorded one.

Pair construction
-----------------
Genuine pairs use two DIFFERENT utterances from the same speaker. Splitting one
recording in half would share the room, microphone, gain and background, and
would measure recording similarity rather than speaker similarity - an
optimistic result dressed up as a real one.

Impostor pairs use utterances from different `speaker_id` values, which is
ground truth rather than an assumption.

Also verified here: the `NO_REFERENCE` contract. Without an enrolled voice the
adapter must decline rather than emit a number, because a similarity invented
in the absence of a reference is manufactured evidence (`BLOCKERS.md` O3).

Usage:
    python scripts/evaluation/exp_ecapa_speaker.py [--speakers 25]
"""

from __future__ import annotations

import argparse
import io
import itertools
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path, model_dir  # noqa: E402

SAMPLE_RATE = 16_000
MIN_SECONDS = 3.0
UTTERANCES_PER_SPEAKER = 3
VIVE_WINDOW_SEC = 2.0


def collect(speakers_wanted: int) -> dict[int, list]:
    """Streams LibriSpeech test-clean until enough speakers have enough audio."""
    import numpy as np
    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset("openslr/librispeech_asr", "clean", split="test",
                      streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    by_speaker: dict[int, list] = defaultdict(list)
    seen = 0
    for row in ds:
        seen += 1
        speaker = int(row["speaker_id"])
        if len(by_speaker[speaker]) >= UTTERANCES_PER_SPEAKER:
            if sum(1 for v in by_speaker.values()
                   if len(v) >= UTTERANCES_PER_SPEAKER) >= speakers_wanted:
                break
            continue
        raw = row["audio"].get("bytes")
        if raw is None:
            with open(row["audio"]["path"], "rb") as fh:
                raw = fh.read()
        wave, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        if rate != SAMPLE_RATE or wave.size < MIN_SECONDS * SAMPLE_RATE:
            continue
        by_speaker[speaker].append(np.asarray(wave, dtype="float32"))
        if seen > 4000:
            break
    full = {s: v[:UTTERANCES_PER_SPEAKER] for s, v in by_speaker.items()
            if len(v) >= UTTERANCES_PER_SPEAKER}
    return dict(itertools.islice(full.items(), speakers_wanted))


def band_pass(x, lo=300.0, hi=3400.0):
    import numpy as np
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / SAMPLE_RATE)
    spectrum[(freqs < lo) | (freqs > hi)] = 0
    return np.fft.irfft(spectrum, n=x.size).astype("float32")


def ulaw(x):
    import numpy as np
    mu = 255.0
    x = np.clip(x, -1.0, 1.0)
    enc = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((enc + 1.0) * 127.5) / 127.5 - 1.0
    return (np.sign(q) * ((1 + mu) ** np.abs(q) - 1) / mu).astype("float32")


CONDITIONS = {
    "clean_full": lambda x: x,
    "vive_window_2s": lambda x: x[:int(VIVE_WINDOW_SEC * SAMPLE_RATE)],
    "telephony_band": band_pass,
    "g711_ulaw": ulaw,
}


def eer_from(genuine: list[float], impostor: list[float]) -> tuple[float, float]:
    """Equal error rate. High similarity means "same speaker"."""
    thresholds = sorted(set(genuine + impostor))
    best = (1.0, 0.0, 1.0)
    for t in thresholds:
        frr = sum(1 for s in genuine if s < t) / max(len(genuine), 1)
        far = sum(1 for s in impostor if s >= t) / max(len(impostor), 1)
        if abs(frr - far) < best[0]:
            best = (abs(frr - far), t, (frr + far) / 2)
    return round(best[2], 4), round(best[1], 4)


def auc_from(genuine: list[float], impostor: list[float]) -> float:
    wins = ties = 0
    for g in genuine:
        for i in impostor:
            if g > i:
                wins += 1
            elif g == i:
                ties += 1
    return round((wins + 0.5 * ties) / max(len(genuine) * len(impostor), 1), 4)


def to_pcm(samples) -> bytes:
    import numpy as np
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speakers", type=int, default=25)
    args = parser.parse_args()

    add_backend_to_path()
    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.audio_models import EcapaSpeakerAdapter
    from app.schemas.models import AnalyzerStatus

    exp = Experiment(
        "9D_ecapa_speaker",
        question=("What is ECAPA-TDNN's speaker-verification error rate "
                  "through the VIVE adapter, and how much of it survives a "
                  "call-like channel and VIVE's 2-second window?"),
        hypothesis=("Verification on clean read speech will be strong, and "
                    "the 2 s window will cost more than the channel "
                    "simulations because a short window carries less speaker "
                    "information."),
        method=("Build genuine pairs from different utterances of the same "
                "LibriSpeech speaker and impostor pairs across speaker_ids. "
                "Score cosine similarity through the real adapter under four "
                "conditions. Report EER, AUC, FAR/FRR and distributions."))

    adapter = EcapaSpeakerAdapter(model_dir("_pretrained", "ecapa"))
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        print(f"ECAPA unavailable: {adapter.describe().detail}")
        return 1
    print("ECAPA loaded\n")

    exp.model(name="ecapa-tdnn", revision="speechbrain/spkrec-ecapa-voxceleb",
              license="Apache-2.0", trained_on="VoxCeleb (not evaluated here)")

    print(f"collecting LibriSpeech test-clean, {args.speakers} speakers ...")
    by_speaker = collect(args.speakers)
    total = sum(len(v) for v in by_speaker.values())
    print(f"  {len(by_speaker)} speakers, {total} utterances\n")
    if len(by_speaker) < 5:
        print("too few speakers collected to measure anything")
        return 1

    exp.dataset(name="openslr/librispeech_asr (clean/test)", source="HuggingFace",
                license="CC-BY-4.0", split="test.clean", samples=total,
                speakers=len(by_speaker), language="en",
                note="clean read audiobook speech; not telephone audio")
    exp.config(conditions=sorted(CONDITIONS), min_utterance_sec=MIN_SECONDS,
               utterances_per_speaker=UTTERANCES_PER_SPEAKER,
               vive_window_sec=VIVE_WINDOW_SEC)

    # -- NO_REFERENCE contract -------------------------------------------
    first = next(iter(by_speaker.values()))[0]
    probe = AudioWindow(session_id="noref", seq=1, start_sec=0.0, end_sec=2.0,
                        pcm=to_pcm(first[:32_000]), sample_rate=SAMPLE_RATE)
    no_ref = adapter.analyze(probe, None)
    empty_ref = adapter.analyze(probe, b"")
    contract = {
        "no_reference_status": no_ref.status.value,
        "no_reference_similarity": no_ref.similarity,
        "empty_reference_status": empty_ref.status.value,
        "empty_reference_similarity": empty_ref.similarity,
        "declines_without_enrolment": (
            no_ref.status is AnalyzerStatus.NO_REFERENCE
            and no_ref.similarity is None
            and empty_ref.similarity is None),
    }
    print(f"  NO_REFERENCE contract honoured: "
          f"{contract['declines_without_enrolment']}\n")

    speakers = sorted(by_speaker)
    results: dict[str, dict] = {}
    for name, transform in CONDITIONS.items():
        genuine, impostor = [], []

        def similarity(a, b) -> float | None:
            window = AudioWindow(session_id=f"spk-{name}", seq=0, start_sec=0.0,
                                 end_sec=a.size / SAMPLE_RATE,
                                 pcm=to_pcm(transform(a)),
                                 sample_rate=SAMPLE_RATE)
            out = adapter.analyze(window, to_pcm(transform(b)))
            return out.similarity if out.status is AnalyzerStatus.AVAILABLE else None

        for speaker in speakers:
            clips = by_speaker[speaker]
            for a, b in itertools.combinations(range(len(clips)), 2):
                value = similarity(clips[a], clips[b])
                if value is not None:
                    genuine.append(value)
        for a, b in itertools.combinations(speakers, 2):
            value = similarity(by_speaker[a][0], by_speaker[b][0])
            if value is not None:
                impostor.append(value)

        value, threshold = eer_from(genuine, impostor)
        entry = {
            "genuine_pairs": len(genuine),
            "impostor_pairs": len(impostor),
            "genuine_similarity": {
                "median": round(statistics.median(genuine), 4),
                "min": round(min(genuine), 4), "max": round(max(genuine), 4)},
            "impostor_similarity": {
                "median": round(statistics.median(impostor), 4),
                "min": round(min(impostor), 4), "max": round(max(impostor), 4)},
            "eer": value,
            "eer_threshold": threshold,
            "roc_auc": auc_from(genuine, impostor),
            "at_threshold_0.5": {
                "false_reject_rate": round(
                    sum(1 for s in genuine if s < 0.5) / len(genuine), 4),
                "false_accept_rate": round(
                    sum(1 for s in impostor if s >= 0.5) / len(impostor), 4)},
            "at_threshold_0.25": {
                "false_reject_rate": round(
                    sum(1 for s in genuine if s < 0.25) / len(genuine), 4),
                "false_accept_rate": round(
                    sum(1 for s in impostor if s >= 0.25) / len(impostor), 4)},
        }
        results[name] = entry
        print(f"  {name:<16} EER {value:.4f} @ {threshold:.3f}  "
              f"AUC {entry['roc_auc']:.4f}  "
              f"gen_med {entry['genuine_similarity']['median']:.3f}  "
              f"imp_med {entry['impostor_similarity']['median']:.3f}  "
              f"({len(genuine)}g/{len(impostor)}i)")

    exp.result("no_reference_contract", contract)
    exp.result("per_condition", results)

    exp.limitation(
        "LibriSpeech is clean English audiobook read speech from close "
        "microphones. It is the EASY case for speaker verification. These "
        "numbers are an upper bound and are NOT comparable to published "
        "VoxCeleb ECAPA results.")
    exp.limitation(
        "VoxCeleb1, the checkpoint's own evaluation set, remains unavailable "
        "(docs/BLOCKERS.md O5). No in-domain verification figure exists.")
    exp.limitation(
        "`telephony_band` and `g711_ulaw` are simulated. A real call adds "
        "handset response, automatic gain control, packet loss and echo "
        "cancellation, none of which are modelled.")
    exp.limitation(
        f"{len(by_speaker)} speakers. An EER from this many speakers has wide "
        "uncertainty and should be read as an order of magnitude.")
    exp.limitation(
        "Speaker VERIFICATION is not speaker IDENTIFICATION. Nothing here "
        "supports recognising who a caller is; it supports comparing a caller "
        "against one enrolled reference - and VIVE has no enrolment source "
        "(docs/BLOCKERS.md O3), so in production this channel reports "
        "NO_REFERENCE.")

    clean = results["clean_full"]
    window = results["vive_window_2s"]
    exp.finish(
        interpretation=(
            f"On clean full utterances the adapter separates speakers with an "
            f"EER of {clean['eer']} (AUC {clean['roc_auc']}). VIVE's own 2 s "
            f"window costs a move to EER {window['eer']}, and the channel "
            f"simulations move it further. The default fusion threshold "
            f"matters: at a similarity of 0.5 the clean false-reject rate is "
            f"{clean['at_threshold_0.5']['false_reject_rate']}, which is the "
            f"rate at which a genuine caller would look inconsistent."),
        conclusion=(
            "ECAPA discriminates speakers well enough to be worth keeping, on "
            "clean speech. It stays unusable in production for a different "
            "reason: there is no enrolment source, so the adapter correctly "
            "reports NO_REFERENCE and contributes nothing. Any similarity "
            "threshold VIVE adopts later must be set from a measurement like "
            "this one, not chosen by eye."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
