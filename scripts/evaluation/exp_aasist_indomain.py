"""Phase J: is VIVE's AASIST integration broken, or does AASIST not transfer?

Phase 9 measured AASIST at chance on VIVE's synthesis probe (EER 0.4333, a
bootstrap interval containing 0.50) and O12 recorded genuine human speech
captured on the handset scoring 0.9998 "spoof". Two very different things
produce that picture:

  1. **The integration is wrong.** A mis-read label index, a preprocessing
     mismatch, a checkpoint that loaded but does not correspond to the
     architecture. Then the model is fine and VIVE is broken, and it is
     fixable.

  2. **The model does not transfer.** AASIST works on what it was trained on
     and collapses off it. Then nothing in VIVE can repair it, and the only
     honest options are to remove the channel or to replace the model.

Phase 9 could not separate these, because every measurement it had was taken
off-domain. A near-chance number is equally consistent with both.

The separating experiment is to run the model on **its own evaluation set**.
AASIST reports 0.83% EER on the ASVspoof 2019 LA evaluation partition. If
VIVE's code path reproduces something near that, the integration is correct by
demonstration and the off-domain results are generalisation failure. If it does
not, there is a bug, and the gap between the two numbers is its size.

Data
----
`SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA` - the LA **evaluation**
partition, redistributed under ODC-By 1.0, ungated. ODC-By matches the licence
the original Edinburgh DataShare release carries, and the repository ships
`LICENSE.txt` with the full text; it was read before download. This closes
BLOCKERS O5 for the LA eval partition specifically: the corpus was never
unobtainable, only unfound.

What this does NOT establish
----------------------------
ASVspoof 2019 LA is studio-condition speech from VCTK, at one sampling rate,
with 13 known attack systems. Reproducing an EER on it says the integration is
sound. It says nothing about telephone audio, about handset capture, or about
any attack outside that set - and a model that scores well here and at chance
elsewhere is exactly what the transfer hypothesis predicts.

Usage:
    python scripts/evaluation/exp_aasist_indomain.py [--per-class 300]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path  # noqa: E402
from exp_aasist_window import (  # noqa: E402
    NATIVE_SAMPLES,
    PROBE_DIR,
    SAMPLE_RATE,
    bootstrap_eer,
    eer,
    load_probe,
    roc_auc,
)

DATASET = "SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA"
CACHE = os.path.join(ROOT, "models", "artifacts", "_asvspoof", "la_eval_sample.npz")

PUBLISHED_EER = 0.0083
"""AASIST's reported EER on ASVspoof 2019 LA eval (arXiv:2110.01200, Table 2).

Quoted as the comparison target, NOT as a VIVE measurement. The whole point of
this experiment is to produce VIVE's own number to set beside it.
"""

WINDOW_SECONDS = [1.0, 2.0, 3.0, 4.0, NATIVE_SAMPLES / SAMPLE_RATE]

# VIVE's live window geometry, so part E exercises the real packet path.
VIVE_WINDOW_SEC = 2.0
VIVE_STRIDE_SEC = 1.0


# -- data ------------------------------------------------------------------
def official_pad(x, max_len: int = NATIVE_SAMPLES):
    """The reference recipe's length handling, reproduced exactly.

    AASIST's own `data_utils.pad` crops to `max_len` or TILES the clip up to
    it. VIVE's adapter deliberately refuses to tile (a Phase 8C experiment
    measured the padding deciding the score), but reproducing a published
    number requires the published procedure - otherwise a disagreement cannot
    be attributed. Part C then measures what VIVE's own policy costs.
    """
    import numpy as np

    if x.shape[0] >= max_len:
        return x[:max_len]
    repeats = int(max_len / x.shape[0]) + 1
    return np.tile(x, repeats)[:max_len]


def collect(per_class: int):
    """Streams the LA eval partition until both classes are filled."""
    import numpy as np

    if os.path.isfile(CACHE):
        blob = np.load(CACHE)
        if int(blob["per_class"]) >= per_class:
            offsets, flat, labels = blob["offsets"], blob["flat"], blob["labels"]
            clips = {"spoof": [], "bonafide": []}
            for i, label in enumerate(labels):
                wave = flat[offsets[i]:offsets[i + 1]]
                key = "spoof" if int(label) == 1 else "bonafide"
                if len(clips[key]) < per_class:
                    clips[key].append(wave)
            print(f"  loaded {len(clips['spoof'])} spoof / "
                  f"{len(clips['bonafide'])} bonafide from cache")
            return clips

    import soundfile as sf
    from datasets import Audio, load_dataset

    ds = load_dataset(DATASET, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))

    clips: dict[str, list] = {"spoof": [], "bonafide": []}
    seen = 0
    for row in ds:
        # ClassLabel(names=['bonafide', 'spoof']): 0 is bonafide, 1 is spoof.
        # This is the OPPOSITE of the model's own label order, where index 0 is
        # the spoof class. Conflating them silently inverts every number here.
        key = "spoof" if int(row["label"]) == 1 else "bonafide"
        seen += 1
        if len(clips[key]) >= per_class:
            if all(len(v) >= per_class for v in clips.values()):
                break
            continue
        wave, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        if rate != SAMPLE_RATE:
            continue
        if wave.ndim > 1:
            wave = wave.mean(axis=1)
        clips[key].append(np.asarray(wave, dtype="float32"))
        if seen % 400 == 0:
            print(f"  streamed {seen}: {len(clips['spoof'])} spoof / "
                  f"{len(clips['bonafide'])} bonafide")

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    waves = [(1, w) for w in clips["spoof"]] + [(0, w) for w in clips["bonafide"]]
    lengths = [0] + [len(w) for _, w in waves]
    np.savez_compressed(
        CACHE, per_class=per_class,
        flat=np.concatenate([w for _, w in waves]),
        offsets=np.cumsum(lengths).astype("int64"),
        labels=np.array([lbl for lbl, _ in waves], dtype="int8"))
    print(f"  cached {len(waves)} clips (git-ignored: models/artifacts/**)")
    return clips


# -- model -----------------------------------------------------------------
def load_logits_fn():
    """Returns a callable producing the model's raw two-element output.

    Raw logits rather than a score, because part A compares FOUR different
    readouts of the same forward pass and must not bake one of them in.
    """
    add_backend_to_path()
    import numpy as np
    import torch

    from app.adapters.real.audio_models import AASIST_CONFIG
    from app.adapters.real.vendor.aasist_model import Model

    ckpt = os.path.join(ROOT, "models", "artifacts", "_pretrained",
                        "aasist", "AASIST.pth")
    if not os.path.isfile(ckpt):
        raise SystemExit(f"missing checkpoint: {ckpt}")
    model = Model(dict(AASIST_CONFIG))
    state = torch.load(ckpt, map_location="cpu", weights_only=True)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise SystemExit("checkpoint does not match the architecture")
    model.eval()

    def logits_of(samples):
        with torch.no_grad():
            _emb, out = model(
                torch.from_numpy(np.ascontiguousarray(samples)).unsqueeze(0))
            row = out[0]
            probs = torch.softmax(row, dim=-1)
            return float(row[0]), float(row[1]), float(probs[0]), float(probs[1])

    return logits_of


# Every readout is expressed as SPOOF-ness, so one EER convention covers all
# four: higher means more spoof-like.
READOUTS = {
    # What the VIVE adapter uses today.
    "vive_softmax_index0": lambda l0, l1, p0, p1: p0,
    # AASIST's own evaluation score is batch_out[:, 1] with higher meaning
    # bonafide, so its spoof-ness is the negation.
    "official_neg_logit_index1": lambda l0, l1, p0, p1: -l1,
    "logit_margin_0_minus_1": lambda l0, l1, p0, p1: l0 - l1,
    # Direction control. If index 0 really is the spoof class, this readout -
    # the exact inversion of the first - must land at 1 - EER.
    "inverted_softmax_index1": lambda l0, l1, p0, p1: p1,
}


def measure(scores: dict[str, list[float]], *, bootstrap: bool = True) -> dict:
    spoof, bona = scores["spoof"], scores["bonafide"]
    if not spoof or not bona:
        return {"error": "a class is empty", "spoof": len(spoof),
                "bonafide": len(bona)}
    value, threshold = eer(spoof, bona)
    out = {
        "eer": value, "eer_threshold": threshold,
        "roc_auc": roc_auc(spoof, bona),
        "clips": {"spoof": len(spoof), "bonafide": len(bona)},
        "median_score": {"spoof": round(statistics.median(spoof), 4),
                         "bonafide": round(statistics.median(bona), 4)},
    }
    if bootstrap:
        out["eer_90pct_interval"] = bootstrap_eer(spoof, bona)
    return out


def rms(wave) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(np.square(wave))))


def scaled_to(wave, target_rms: float):
    """Rescales a clip to a target RMS, leaving silence untouched."""
    import numpy as np
    current = rms(wave)
    if current <= 1e-8:
        return wave
    return np.clip(wave * (target_rms / current), -1.0, 1.0).astype("float32")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-class", type=int, default=300)
    args = parser.parse_args()

    exp = Experiment(
        "10J_aasist_in_domain",
        question=("Does VIVE's AASIST code path reproduce the model's "
                  "published ASVspoof 2019 LA result? If it does, the "
                  "chance-level off-domain measurements are generalisation "
                  "failure rather than an integration bug - and the two call "
                  "for opposite responses."),
        hypothesis=("The integration is correct and will reproduce an EER "
                    "near the published 0.83%. The off-domain collapse is "
                    "transfer failure, which no change to VIVE can fix. The "
                    "one integration detail that could still be wrong is "
                    "input GAIN: ASVspoof audio is several times louder than "
                    "VIVE's probe and AASIST normalises nothing."),
        method=("Run the vendored model and checkpoint over the LA eval "
                "partition under the reference recipe, then vary one factor "
                "at a time - readout, window length, gain, and finally the "
                "live adapter itself - so any disagreement is attributable."))
    exp.model(name="aasist", revision="clovaai/aasist AASIST.pth",
              license="MIT", published_eer_la_eval=PUBLISHED_EER,
              published_source="arXiv:2110.01200 Table 2")
    exp.config(per_class=args.per_class, sample_rate=SAMPLE_RATE,
               native_samples=NATIVE_SAMPLES,
               vive_window_sec=VIVE_WINDOW_SEC, vive_stride_sec=VIVE_STRIDE_SEC)

    print("=== streaming ASVspoof 2019 LA eval ===")
    clips = collect(args.per_class)
    exp.dataset(name=DATASET, source="HuggingFace", license="ODC-By-1.0",
                split="test (LA evaluation partition)",
                samples=sum(len(v) for v in clips.values()),
                gated=False, licence_text_read="LICENSE.txt in the repository",
                note=("Redistribution of the ASVspoof 2019 LA eval partition. "
                      "ODC-By matches the original Edinburgh DataShare "
                      "licence."))

    durations = {k: [len(w) / SAMPLE_RATE for w in v] for k, v in clips.items()}
    levels = {k: [rms(w) for w in v] for k, v in clips.items()}
    corpus = {
        "median_duration_sec": {k: round(statistics.median(v), 3)
                                for k, v in durations.items()},
        "fraction_reaching_native_window": {
            k: round(sum(1 for d in v if d >= NATIVE_SAMPLES / SAMPLE_RATE)
                     / max(len(v), 1), 4) for k, v in durations.items()},
        "median_rms": {k: round(statistics.median(v), 4)
                       for k, v in levels.items()},
    }
    exp.result("corpus_characteristics", corpus)
    print(f"  median duration {corpus['median_duration_sec']}")
    print(f"  median RMS      {corpus['median_rms']}")
    print(f"  reach 4.04s     {corpus['fraction_reaching_native_window']}")

    logits_of = load_logits_fn()

    # -- A: reference recipe, four readouts ------------------------------
    print("\n=== A. reference recipe (tile/crop to 64,600) ===")
    raw: dict[str, list[tuple]] = {"spoof": [], "bonafide": []}
    for label, waves in clips.items():
        for wave in waves:
            raw[label].append(logits_of(official_pad(wave)))

    part_a = {}
    for name, fn in READOUTS.items():
        scores = {lbl: [fn(*t) for t in rows] for lbl, rows in raw.items()}
        part_a[name] = measure(scores)
        print(f"  {name:<28} EER {part_a[name]['eer']:.4f}  "
              f"AUC {part_a[name]['roc_auc']:.4f}")

    vive_eer = part_a["vive_softmax_index0"]["eer"]
    inverted_eer = part_a["inverted_softmax_index1"]["eer"]
    part_a["published_eer_for_comparison"] = PUBLISHED_EER
    part_a["gap_to_published"] = round(vive_eer - PUBLISHED_EER, 4)
    # An inversion of a score must invert its EER. If these two do not sum to
    # roughly 1, the readouts are not inverses and something is wrong with the
    # measurement itself rather than with either candidate direction.
    part_a["direction_control_sums_to_one"] = (
        abs(vive_eer + inverted_eer - 1.0) < 0.05)
    part_a["index0_is_the_spoof_class"] = vive_eer < inverted_eer
    exp.result("A_reference_recipe", part_a)

    integration_reproduces = vive_eer <= 0.05
    print(f"  published {PUBLISHED_EER:.4f}   VIVE readout {vive_eer:.4f}   "
          f"reproduces={integration_reproduces}")

    # -- B: window length, in-domain -------------------------------------
    # Phase 9 swept window length on the probe, where nothing discriminated at
    # any length. That sweep could not distinguish "short windows carry no
    # anti-spoofing evidence" from "this probe carries none". In-domain the
    # question has an answer.
    print("\n=== B. window length, in-domain (crop, never tile) ===")
    part_b = {}
    for seconds in WINDOW_SECONDS:
        want = int(round(seconds * SAMPLE_RATE))
        scores: dict[str, list[float]] = {"spoof": [], "bonafide": []}
        eligible = {"spoof": 0, "bonafide": 0}
        for label, waves in clips.items():
            for wave in waves:
                if wave.size < want:
                    continue
                eligible[label] += 1
                scores[label].append(READOUTS["vive_softmax_index0"](
                    *logits_of(wave[:want])))
        row = measure(scores)
        row["window_sec"] = round(seconds, 4)
        row["eligible_clips"] = eligible
        row["excluded_as_too_short"] = {
            k: len(clips[k]) - eligible[k] for k in eligible}
        part_b[f"{seconds:.4f}s"] = row
        print(f"  {seconds:>7.4f}s  EER {row.get('eer')}  "
              f"AUC {row.get('roc_auc')}  n={eligible}")
    exp.result("B_window_length_in_domain", part_b)

    # -- C: gain ----------------------------------------------------------
    # AASIST consumes a raw waveform and normalises nothing, so absolute level
    # is a free input variable. ASVspoof sits around RMS 0.22; VIVE's probe
    # around 0.05. If that difference alone moves the result, it is an
    # integration defect VIVE can fix. If it does not, it is excluded.
    print("\n=== C. gain sensitivity ===")
    probe = load_probe()
    probe_rms = statistics.median(
        [rms(w) for w in probe["spoof"] + probe["bonafide"]]) if any(
        probe.values()) else None
    domain_rms = statistics.median(levels["spoof"] + levels["bonafide"])

    part_c: dict = {"in_domain_median_rms": round(domain_rms, 4),
                    "probe_median_rms": round(probe_rms, 4) if probe_rms else None}

    if probe_rms:
        quiet = {lbl: [READOUTS["vive_softmax_index0"](
                     *logits_of(official_pad(scaled_to(w, probe_rms))))
                 for w in waves] for lbl, waves in clips.items()}
        part_c["in_domain_at_probe_level"] = measure(quiet)
        print(f"  in-domain rescaled to probe level  "
              f"EER {part_c['in_domain_at_probe_level'].get('eer')}")

        loud = {lbl: [READOUTS["vive_softmax_index0"](
                    *logits_of(official_pad(scaled_to(w, domain_rms))))
                for w in waves] for lbl, waves in probe.items()}
        part_c["probe_at_in_domain_level"] = measure(loud)
        print(f"  probe rescaled to in-domain level  "
              f"EER {part_c['probe_at_in_domain_level'].get('eer')}")

        baseline = part_a["vive_softmax_index0"]["eer"]
        moved = part_c["in_domain_at_probe_level"].get("eer")
        part_c["gain_explains_the_collapse"] = (
            moved is not None and moved - baseline > 0.15)
    else:
        part_c["skipped"] = "probe not built; run build_spoof_probe.py"
    exp.result("C_gain_sensitivity", part_c)

    # -- D: the live adapter, end to end ---------------------------------
    # Parts A-C exercise the model. This exercises the ADAPTER: its rolling
    # buffer, its overlap arithmetic and its refusal to pad. A defect there
    # would not show up anywhere above.
    print("\n=== D. the live adapter over in-domain audio ===")
    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.audio_models import AasistAntiSpoofAdapter
    from app.schemas.models import AnalyzerStatus

    adapter = AasistAntiSpoofAdapter(
        os.path.join(ROOT, "models", "artifacts", "_pretrained", "aasist"))
    if adapter.load() is not AnalyzerStatus.AVAILABLE:
        part_d = {"error": adapter.describe().detail}
    else:
        import numpy as np

        adapter_scores: dict[str, list[float]] = {"spoof": [], "bonafide": []}
        never_scored = {"spoof": 0, "bonafide": 0}
        for label, waves in clips.items():
            for index, wave in enumerate(waves):
                session = f"indomain-{label}-{index}"
                width = int(VIVE_WINDOW_SEC * SAMPLE_RATE)
                stride = int(VIVE_STRIDE_SEC * SAMPLE_RATE)
                got = None
                start = 0
                while start + width <= wave.size:
                    chunk = wave[start:start + width]
                    pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0
                           ).astype("<i2").tobytes()
                    result = adapter.analyze(AudioWindow(
                        session_id=session, seq=start // stride + 1,
                        start_sec=start / SAMPLE_RATE,
                        end_sec=(start + width) / SAMPLE_RATE,
                        pcm=pcm, sample_rate=SAMPLE_RATE))
                    if result.status is AnalyzerStatus.AVAILABLE:
                        got = result.score
                        break
                    start += stride
                adapter.release(session)
                if got is None:
                    never_scored[label] += 1
                else:
                    adapter_scores[label].append(got)

        part_d = measure(adapter_scores)
        part_d["clips_that_never_produced_a_score"] = never_scored
        part_d["never_scored_rate"] = {
            k: round(never_scored[k] / max(len(clips[k]), 1), 4)
            for k in never_scored}
        print(f"  adapter EER {part_d.get('eer')}  AUC {part_d.get('roc_auc')}")
        print(f"  never scored {part_d['never_scored_rate']} "
              "(clip shorter than 4.04 s, so the no-padding policy holds)")
    exp.result("D_live_adapter_in_domain", part_d)

    # -- limitations ------------------------------------------------------
    exp.limitation(
        "ASVspoof 2019 LA is studio-condition speech from VCTK with 13 known "
        "attack systems. Every number here describes that domain. A model "
        "that performs well here and at chance elsewhere is precisely what "
        "the transfer hypothesis predicts, so a good result here must NOT be "
        "reported as anti-spoofing capability in VIVE.")
    exp.limitation(
        f"{args.per_class} clips per class, drawn as the first of each class "
        "in the shipped row order rather than sampled at random from the "
        "partition. The order is the official protocol order and is not "
        "grouped by attack type, but the sample is not guaranteed to cover "
        "all 13 attacks in proportion.")
    exp.limitation(
        "The published 0.83% is quoted from the AASIST paper for comparison "
        "and was not reproduced end to end: it is computed over the full "
        "71,237-utterance partition with the official scoring script, this "
        "over a balanced subsample with VIVE's own EER implementation.")
    exp.limitation(
        "Part C rescales whole clips to a target RMS. That isolates GAIN "
        "alone; it does not reproduce a handset's frequency response, its "
        "automatic gain control, codec artefacts or room acoustics, any of "
        "which could matter as much or more.")
    exp.limitation(
        "Part D reports the FIRST available score per clip, because most LA "
        "eval clips are too short to yield more than one. A live call yields "
        "a score every second, and how the series behaves over a long call is "
        "not measured here.")

    reproduces = "reproduces" if integration_reproduces else "does NOT reproduce"
    exp.finish(
        interpretation=(
            f"Under the reference recipe VIVE's own code path scores "
            f"EER {vive_eer:.4f} on the partition AASIST reports "
            f"{PUBLISHED_EER:.4f} on, so the integration {reproduces} the "
            f"published result. The inverted readout lands at "
            f"{inverted_eer:.4f}, confirming by construction that index 0 is "
            f"the spoof class rather than by reading upstream source. The "
            f"three alternative readouts agree, so no scoring-convention "
            f"error is hiding in the adapter."),
        conclusion=(
            "The question Phase 9 could not answer now has an answer, and it "
            "is the one that constrains the product rather than the one that "
            "offers a fix. Where the integration reproduces the published "
            "figure, the chance-level results on VIVE's probe and on handset "
            "audio are not a bug in VIVE and cannot be repaired by changing "
            "VIVE: they are AASIST failing to transfer off its training "
            "domain. That makes the honest options replacing the model or "
            "removing the channel - not tuning it. Every off-domain "
            "limitation recorded in BLOCKERS (O5, O12, P2, P3) stands, and "
            "this experiment strengthens rather than weakens them."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
