"""Phase 9: can AASIST give useful evidence before ~4 seconds of audio?

The question
------------
Phase 8 removed padding from the anti-spoof adapter: it now buffers real audio
and returns `INSUFFICIENT_AUDIO` until it holds AASIST's native 64,600 samples
(~4.04 s). That is correct, and it costs ~4 s before the first anti-spoof
score in a call. This experiment asks whether that cost is necessary.

Is a shorter window technically valid?
--------------------------------------
Checked before measuring, because forcing a model to accept an input shape it
was not built for would produce numbers about nothing. AASIST's classifier
reads max- and average-pooled features plus a master node, so the time
dimension is reduced by pooling and `nn.Linear(5 * gat_dims[1], 2)` sees a
fixed width regardless of input length. Shorter inputs run natively - no
reshaping, no padding, no resampling, no adapter change.

Architecturally valid is not the same as trained for. The checkpoint was
trained on 64,600-sample inputs, so anything shorter is off the training
distribution, and that is precisely what is being measured rather than assumed.

Design
------
Every window is a PREFIX of the same clip, so across lengths the audio is the
same recording and only the amount of it changes. No clip is padded, tiled or
resampled at any length: a clip too short for a given length is dropped from
that length rather than extended, which is the rule Phase 8 established.

Two measurements, reported separately because they answer different questions:

1. **Discrimination per window length** - EER, ROC AUC and error rates at a
   fixed threshold, using the two-class probe set
   (`scripts/evaluation/build_spoof_probe.py`). This is the only part that
   says anything about detection, and it is bounded by the probe's single
   synthesis family and its language/channel confound.

2. **Self-agreement per window length** - how far a short window's score sits
   from the same clip's full-window score. This needs no labels and is a
   necessary condition: a short window that disagrees with the model's own
   full-window answer cannot be a cheaper substitute for it. It is not a
   sufficient condition, because O12 leaves the full-window answer itself
   unvalidated.

Usage:
    python scripts/evaluation/exp_aasist_window.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path  # noqa: E402

PROBE_DIR = os.path.join(ROOT, "models", "artifacts", "_probe")
SAMPLE_RATE = 16_000
NATIVE_SAMPLES = 64_600
WINDOW_SECONDS = [1.0, 2.0, 3.0, 4.0, NATIVE_SAMPLES / SAMPLE_RATE]
FIXED_THRESHOLD = 0.5
BOOTSTRAP = 400


def load_model():
    add_backend_to_path()
    import torch

    from app.adapters.real.audio_models import AASIST_CONFIG
    from app.adapters.real.vendor.aasist_model import Model

    ckpt = os.path.join(ROOT, "models", "artifacts", "_pretrained",
                        "aasist", "AASIST.pth")
    model = Model(dict(AASIST_CONFIG))
    state = torch.load(ckpt, map_location="cpu", weights_only=True)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise SystemExit("checkpoint does not match the architecture")
    model.eval()

    def score(samples) -> float:
        import numpy as np
        with torch.no_grad():
            _emb, logits = model(
                torch.from_numpy(np.ascontiguousarray(samples)).unsqueeze(0))
            # Index 0 is the spoof class in the official AASIST label order,
            # verified against upstream during Phase 8C.
            return float(torch.softmax(logits[0], dim=-1)[0])

    return score


def probe_is_speech(clips: dict[str, list], limit: int = 20) -> dict:
    """Validity control: is the synthetic half actually speech?

    A near-chance discrimination result has two possible causes - the model
    cannot tell these classes apart, or one class is not what it claims to be.
    Vocoder output that had collapsed to noise or silence would produce the
    same near-chance number and would mean nothing about AASIST.

    Silero VAD is an independent model with no stake in the outcome, so its
    verdict on both halves separates those cases before the result is read.
    """
    import numpy as np

    from app.adapters.interfaces import AudioWindow
    from app.adapters.real.audio_models import SileroVadAdapter
    from app.schemas.models import AnalyzerStatus

    vad = SileroVadAdapter(os.path.join(ROOT, "models", "artifacts",
                                        "_pretrained", "silero-vad"))
    if vad.load() is not AnalyzerStatus.AVAILABLE:
        return {"checked": False, "reason": vad.describe().detail}

    out: dict[str, dict] = {"checked": True}
    for label, waves in clips.items():
        speech = 0
        rms = []
        for wave in waves[:limit]:
            rms.append(float(np.sqrt(np.mean(np.square(wave)))))
            pcm = (np.clip(wave[:32_000], -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            result = vad.analyze(AudioWindow(
                session_id="probe-validity", seq=1, start_sec=0.0, end_sec=2.0,
                pcm=pcm, sample_rate=SAMPLE_RATE))
            speech += int(bool(result.has_speech))
        out[label] = {
            "clips_checked": min(len(waves), limit),
            "vad_detected_speech": speech,
            "median_rms": round(statistics.median(rms), 4) if rms else None,
        }
    return out


def load_probe() -> dict[str, list]:
    import numpy as np
    import soundfile as sf

    clips: dict[str, list] = {"spoof": [], "bonafide": []}
    for label in clips:
        directory = os.path.join(PROBE_DIR, label)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".wav"):
                continue
            wave, rate = sf.read(os.path.join(directory, name),
                                 dtype="float32", always_2d=False)
            if rate != SAMPLE_RATE:
                # Never resample into a probe: resampling is itself a
                # low-level transform AASIST can key on.
                continue
            if wave.ndim > 1:
                wave = wave.mean(axis=1)
            clips[label].append(np.asarray(wave, dtype="float32"))
    return clips


# -- metrics ---------------------------------------------------------------

def eer(spoof: list[float], bona: list[float]) -> tuple[float, float]:
    """Equal error rate and its threshold.

    Convention: a HIGH score means spoof. A spoof clip scoring below the
    threshold is a miss; a bonafide clip scoring above it is a false alarm.
    """
    thresholds = sorted(set(spoof + bona))
    best = (1.0, 0.5, 1.0)
    for t in thresholds:
        fnr = sum(1 for s in spoof if s < t) / max(len(spoof), 1)
        fpr = sum(1 for s in bona if s >= t) / max(len(bona), 1)
        gap = abs(fnr - fpr)
        if gap < best[0]:
            best = (gap, t, (fnr + fpr) / 2)
    return round(best[2], 4), round(best[1], 4)


def roc_auc(spoof: list[float], bona: list[float]) -> float:
    """Probability a random spoof clip outscores a random bonafide clip."""
    wins = ties = 0
    for s in spoof:
        for b in bona:
            if s > b:
                wins += 1
            elif s == b:
                ties += 1
    total = max(len(spoof) * len(bona), 1)
    return round((wins + 0.5 * ties) / total, 4)


def bootstrap_eer(spoof: list[float], bona: list[float]) -> dict:
    """Percentile interval for the EER, so the sample size is visible."""
    import numpy as np

    rng = np.random.default_rng(20260922)
    draws = []
    for _ in range(BOOTSTRAP):
        s = [spoof[i] for i in rng.integers(0, len(spoof), len(spoof))]
        b = [bona[i] for i in rng.integers(0, len(bona), len(bona))]
        draws.append(eer(s, b)[0])
    draws.sort()
    return {"p05": round(draws[int(0.05 * len(draws))], 4),
            "p95": round(draws[int(0.95 * len(draws)) - 1], 4),
            "resamples": BOOTSTRAP}


def main() -> int:
    import numpy as np

    exp = Experiment(
        "9B_aasist_early_window",
        question=("Can AASIST produce useful anti-spoofing evidence from less "
                  "than its native 64,600-sample (~4.04 s) window, using only "
                  "genuine audio and without any adapter change?"),
        hypothesis=("Shorter windows will degrade discrimination gradually "
                    "rather than collapse, so a 2 s window may retain enough "
                    "separation to be worth reporting early at lower "
                    "confidence."),
        method=("Score prefixes of the same clips at 1, 2, 3, 4 and 4.0375 s. "
                "No padding, tiling or resampling at any length; clips too "
                "short for a length are dropped from it. Report EER, ROC AUC "
                "and fixed-threshold error rates per length against the "
                "two-class probe, plus label-free agreement with each clip's "
                "own full-window score."))

    print("AASIST accepts variable-length input natively: the classifier reads")
    print("pooled features, so the time dimension is reduced before the head.")
    print("No shape forcing is performed anywhere in this experiment.\n")

    score_fn = load_model()
    clips = load_probe()
    have_two_classes = bool(clips["spoof"]) and bool(clips["bonafide"])

    if not have_two_classes:
        print("probe set absent - run build_spoof_probe.py first for the")
        print("discrimination half; continuing with agreement only.\n")

    exp.model(name="aasist", revision="clovaai/aasist AASIST.pth", license="MIT",
              trained_on="ASVspoof2019 LA", native_input_samples=NATIVE_SAMPLES,
              accepts_variable_length=True)

    manifest_path = os.path.join(PROBE_DIR, "manifest.json")
    probe_manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            probe_manifest = json.load(fh)
        exp.dataset(name="vive-aasist-probe-v1 (spoof half)",
                    source="microsoft/speecht5_tts + speecht5_hifigan",
                    license="MIT", split="probe", samples=len(clips["spoof"]))
        exp.dataset(name="vive-aasist-probe-v1 (bonafide half)",
                    source="google/fleurs test hi_in+ta_in",
                    license="CC-BY-4.0", split="probe",
                    samples=len(clips["bonafide"]))
    exp.config(window_seconds=WINDOW_SECONDS, fixed_threshold=FIXED_THRESHOLD,
               padding="none", resampling="none", sample_rate=SAMPLE_RATE)

    # Control first: establish both halves are speech before reading anything
    # into how well - or badly - they are separated.
    validity = probe_is_speech(clips) if have_two_classes else {"checked": False}
    if validity.get("checked"):
        for label in ("spoof", "bonafide"):
            v = validity[label]
            print(f"  validity: {label:<9} VAD detected speech in "
                  f"{v['vad_detected_speech']}/{v['clips_checked']} clips, "
                  f"median RMS {v['median_rms']}")
        print()
    exp.result("probe_validity_control", validity)

    # -- score every clip at every length --------------------------------
    per_length: dict[str, dict] = {}
    scores_by_label: dict[float, dict[str, list[float]]] = {}
    latency: dict[float, list[float]] = {}
    native = WINDOW_SECONDS[-1]

    for seconds in WINDOW_SECONDS:
        n = int(round(seconds * SAMPLE_RATE))
        scores_by_label[seconds] = {"spoof": [], "bonafide": []}
        latency[seconds] = []
        for label, waves in clips.items():
            for wave in waves:
                if wave.size < n:
                    continue          # never extend; drop instead
                began = time.perf_counter()
                s = score_fn(wave[:n])
                latency[seconds].append((time.perf_counter() - began) * 1000)
                scores_by_label[seconds][label].append(s)
        counted = {k: len(v) for k, v in scores_by_label[seconds].items()}
        print(f"  {seconds:>6.4f}s ({n:>6} samples)  clips scored: {counted}")

    # -- discrimination ---------------------------------------------------
    for seconds in WINDOW_SECONDS:
        sp = scores_by_label[seconds]["spoof"]
        bo = scores_by_label[seconds]["bonafide"]
        entry: dict = {
            "window_sec": round(seconds, 4),
            "window_samples": int(round(seconds * SAMPLE_RATE)),
            "clips": {"spoof": len(sp), "bonafide": len(bo)},
            "median_score": {
                "spoof": round(statistics.median(sp), 4) if sp else None,
                "bonafide": round(statistics.median(bo), 4) if bo else None},
            "latency_ms": {
                "median": round(statistics.median(latency[seconds]), 1)
                if latency[seconds] else None,
                "max": round(max(latency[seconds]), 1) if latency[seconds] else None},
        }
        if sp and bo:
            value, threshold = eer(sp, bo)
            entry["eer"] = value
            entry["eer_threshold"] = threshold
            entry["eer_90pct_interval"] = bootstrap_eer(sp, bo)
            entry["roc_auc"] = roc_auc(sp, bo)
            entry["at_fixed_threshold_0.5"] = {
                "spoof_missed_rate": round(
                    sum(1 for s in sp if s < FIXED_THRESHOLD) / len(sp), 4),
                "bonafide_false_alarm_rate": round(
                    sum(1 for s in bo if s >= FIXED_THRESHOLD) / len(bo), 4),
            }
        per_length[f"{seconds:.4f}s"] = entry

    # -- agreement with each clip's own full-window score ------------------
    agreement: dict[str, dict] = {}
    full_index: dict[str, list[float]] = {}
    n_native = int(round(native * SAMPLE_RATE))
    for label, waves in clips.items():
        full_index[label] = [score_fn(w[:n_native]) for w in waves
                             if w.size >= n_native]

    for seconds in WINDOW_SECONDS[:-1]:
        n = int(round(seconds * SAMPLE_RATE))
        deltas, flips, pairs = [], 0, 0
        for label, waves in clips.items():
            usable = [w for w in waves if w.size >= n_native]
            for wave, full in zip(usable, full_index[label]):
                if wave.size < n:
                    continue
                short = score_fn(wave[:n])
                deltas.append(abs(short - full))
                flips += int((short >= FIXED_THRESHOLD) != (full >= FIXED_THRESHOLD))
                pairs += 1
        agreement[f"{seconds:.4f}s"] = {
            "pairs": pairs,
            "median_abs_delta_vs_full_window": round(statistics.median(deltas), 4)
            if deltas else None,
            "max_abs_delta_vs_full_window": round(max(deltas), 4) if deltas else None,
            "verdict_flip_rate_at_0.5": round(flips / pairs, 4) if pairs else None,
        }
        a = agreement[f"{seconds:.4f}s"]
        print(f"  agreement {seconds:>5.2f}s vs full: median delta "
              f"{a['median_abs_delta_vs_full_window']}, "
              f"verdict flips {a['verdict_flip_rate_at_0.5']}")

    exp.result("per_window_length", per_length)
    exp.result("agreement_with_full_window", agreement)
    exp.result("probe_manifest", probe_manifest)
    exp.result("variable_length_input_is_native", True)
    exp.result("padding_or_resampling_used", False)

    print("\n--- summary ---")
    for key, entry in per_length.items():
        line = (f"  {key:>9}  spoof_med={entry['median_score']['spoof']}  "
                f"bona_med={entry['median_score']['bonafide']}")
        if "eer" in entry:
            line += (f"  EER={entry['eer']:.4f} "
                     f"[{entry['eer_90pct_interval']['p05']:.4f},"
                     f"{entry['eer_90pct_interval']['p95']:.4f}]  "
                     f"AUC={entry['roc_auc']:.4f}")
        line += f"  {entry['latency_ms']['median']}ms"
        print(line)

    # -- limitations -------------------------------------------------------
    exp.limitation(
        "The probe has ONE synthesis family (SpeechT5 + HiFiGAN). Nothing here "
        "generalises to other generators (docs/BLOCKERS.md P2), and this is "
        "not an ASVspoof-comparable EER.")
    exp.limitation(
        "The two probe classes differ in language and recording channel as "
        "well as in authenticity: spoof is English vocoder output, bonafide is "
        "Hindi/Tamil recorded speech. Separation measured here may partly "
        "reflect channel rather than synthesis, which would make these numbers "
        "OPTIMISTIC.")
    exp.limitation(
        "Sample size is small. The bootstrap interval is reported for exactly "
        "that reason and must be quoted alongside any EER from this table.")
    exp.limitation(
        "Agreement with the full-window score is label-free and only a "
        "necessary condition. The full-window answer is itself unvalidated "
        "out of domain (docs/BLOCKERS.md O12), so agreeing with it is not "
        "evidence of correctness.")
    exp.limitation(
        "Clips shorter than a given window length are dropped from that "
        "length, so the clip set can differ slightly between lengths. Counts "
        "are reported per length.")

    scored = [e for e in per_length.values() if "eer" in e]
    best = min(scored, key=lambda e: e["eer"], default=None)

    if not best:
        interpretation = (
            "No two-class probe was available, so only label-free agreement "
            "was measured. Agreement alone cannot establish that a shorter "
            "window carries usable evidence.")
        conclusion = (
            "Shorter windows run natively and need no adapter change, so the "
            "question is evidential rather than technical. It cannot be "
            "settled without a two-class probe.")
    else:
        # A bootstrap interval that spans 0.5, or an AUC at chance, means the
        # model is not separating the classes at all. That has to be said
        # plainly rather than reported as "the best window length", which
        # would imply a working detector with a tuning question.
        chance = (best["eer_90pct_interval"]["p95"] >= 0.50
                  or abs(best["roc_auc"] - 0.5) < 0.10)
        exp.result("discriminates_above_chance", not chance)
        if chance:
            interpretation = (
                f"AASIST does not separate this synthesis family from genuine "
                f"speech at ANY window length. The best window was "
                f"{best['window_sec']}s at EER {best['eer']} "
                f"(90% interval "
                f"{best['eer_90pct_interval']['p05']}-"
                f"{best['eer_90pct_interval']['p95']}, AUC {best['roc_auc']}), "
                f"and that interval includes 0.50 - chance. The stated "
                f"language and channel confound cuts the reassuring way here: "
                f"English vocoder output against Hindi/Tamil recorded speech "
                f"should have been EASIER to separate than genuine spoofing, "
                f"so a near-chance result under a favourable confound is a "
                f"conservative reading, not an optimistic one. The class-index "
                f"convention cannot rescue it either: reversing it gives "
                f"AUC {1 - best['roc_auc']:.4f}, also chance.")
            conclusion = (
                "The early-window question is moot. Shorter windows run "
                "natively and need no adapter change, but there is no "
                "measured anti-spoofing performance at the native length to "
                "deliver earlier. VIVE must not present AASIST output as "
                "synthetic-voice evidence on audio of this kind, and no "
                "real-time anti-spoofing capability may be claimed. Fusion "
                "weights are NOT changed on the strength of one synthesis "
                "family; that needs a real corpus (docs/BLOCKERS.md O5).")
        else:
            interpretation = (
                f"Discrimination against this one synthesis family is best at "
                f"{best['window_sec']}s (EER {best['eer']}, 90% interval "
                f"{best['eer_90pct_interval']['p05']}-"
                f"{best['eer_90pct_interval']['p95']}). Read it with the "
                f"channel confound above, which plausibly accounts for part "
                f"of the separation and makes this optimistic.")
            conclusion = (
                "Shorter windows run natively and need no adapter change, so "
                "the question is evidential rather than technical. Whether to "
                "lower the adapter's threshold below 64,600 samples depends on "
                "the agreement and error figures above, and on the fact that "
                "neither is validated against a real anti-spoofing corpus "
                "(O5). Real-time anti-spoofing must not be claimed on the "
                "strength of this experiment alone.")

    exp.finish(interpretation=interpretation, conclusion=conclusion)
    return 0


if __name__ == "__main__":
    sys.exit(main())
