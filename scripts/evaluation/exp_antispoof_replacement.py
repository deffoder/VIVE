"""Phase J2: is there an anti-spoof model that actually transfers?

Phase J established that VIVE's AASIST integration is correct - EER 0.0133 on
ASVspoof 2019 LA eval against a published 0.0083 - and that the model simply
does not transfer: chance on VIVE's synthesis probe, and 0.9998 "spoof" on
genuine human speech captured by the handset.

That leaves exactly two honest options: replace the model, or remove the
channel from the risk score. Choosing between them needs evidence, not
preference, and the evidence required is specific: a candidate has to beat
AASIST **off-domain**, because on-domain performance is not the thing that
failed.

The bar, set before any candidate was run
-----------------------------------------
1. **In-domain sanity.** Separate ASVspoof 2019 LA eval. A candidate that
   cannot do the easy case is not a candidate; this is a control, not a
   selling point.
2. **Off-domain transfer.** Separate VIVE's probe - SpeechT5 + HiFiGAN
   synthesis against FLEURS bonafide - where AASIST scores at chance
   (EER 0.4333, interval containing 0.50).

A candidate is adopted only if (2) is decisively better than AASIST's. Passing
(1) alone reproduces exactly the situation the product is already in.

Candidates
----------
Four Apache-2.0, ungated wav2vec2-based detectors, licences read from
repository metadata before download. They share a backbone, which is itself
worth knowing: if all four fail the same way, that is evidence about the
approach rather than about any one checkpoint.

Usage:
    python scripts/evaluation/exp_antispoof_replacement.py [--per-class 120]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path  # noqa: E402
from exp_aasist_indomain import collect  # noqa: E402
from exp_aasist_window import (  # noqa: E402
    SAMPLE_RATE,
    bootstrap_eer,
    eer,
    load_probe,
    roc_auc,
)

CANDIDATES = {
    "mo-thecreator/Deepfake-audio-detection": "apache-2.0",
    "MelodyMachine/Deepfake-audio-detection-V2": "apache-2.0",
    "Bisher/wav2vec2_ASV_deepfake_audio_detection": "apache-2.0",
    "Hemgg/Deepfake-audio-detection": "apache-2.0",
}

CACHE = os.path.join(ROOT, "models", "artifacts", "_antispoof_candidates")

# AASIST's own numbers, from Phase J and Phase 9, for the comparison.
AASIST = {
    "in_domain_eer": 0.0133,
    "probe_eer": 0.4333,
    "probe_roc_auc": 0.56,
    "source": ("models/evaluation/phase9/10J_aasist_in_domain.json and "
               "9B_aasist_early_window.json"),
}

MAX_SECONDS = 4.0
"""Clip length fed to every candidate.

Fixed across candidates and across both corpora so length cannot be the
variable that separates them. Four seconds also matches AASIST's native
window, keeping this comparable to the numbers above.
"""


def spoof_index(config) -> int | None:
    """Finds which output index means 'spoof' from the model's own label map.

    Never assumed. These checkpoints disagree - some use `fake`/`real`, others
    `spoof`/`bonafide`, and at least one orders them the other way round.
    Guessing would produce a beautifully inverted EER and no error.
    """
    labels = getattr(config, "id2label", None) or {}
    for index, name in labels.items():
        cleaned = str(name).strip().lower().replace("_", "").replace(" ", "")
        if cleaned in {"spoof", "fake", "deepfake", "synthetic", "generated",
                       "ai", "aivoice", "aigenerated", "spoofed", "1"}:
            return int(index)
    return None


def score_clips(model, extractor, clips, torch, spoof_at: int) -> list[float]:
    import numpy as np

    limit = int(MAX_SECONDS * SAMPLE_RATE)
    out = []
    for wave in clips:
        chunk = np.asarray(wave[:limit], dtype="float32")
        inputs = extractor(chunk, sampling_rate=SAMPLE_RATE,
                           return_tensors="pt")
        with torch.no_grad():
            logits = model(**inputs).logits[0]
            probs = torch.softmax(logits, dim=-1)
        out.append(float(probs[spoof_at]))
    return out


def measure(spoof: list[float], bona: list[float]) -> dict:
    if not spoof or not bona:
        return {"error": "empty class"}
    value, threshold = eer(spoof, bona)
    return {
        "eer": value,
        "eer_threshold": threshold,
        "roc_auc": roc_auc(spoof, bona),
        "clips": {"spoof": len(spoof), "bonafide": len(bona)},
        "median_score": {"spoof": round(statistics.median(spoof), 4),
                         "bonafide": round(statistics.median(bona), 4)},
        "eer_90pct_interval": bootstrap_eer(spoof, bona),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-class", type=int, default=120)
    args = parser.parse_args()

    import torch
    from huggingface_hub import HfApi, snapshot_download
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    add_backend_to_path()

    exp = Experiment(
        "10J2_antispoof_replacement",
        question=("Phase J left two honest options - replace AASIST or drop "
                  "the channel. Is there an ungated, openly-licensed "
                  "anti-spoof model that transfers to VIVE's audio, where "
                  "AASIST scores at chance?"),
        hypothesis=("At least one wav2vec2-based detector will transfer "
                    "better than AASIST, because a self-supervised speech "
                    "backbone trained on thousands of hours of varied audio "
                    "should be less brittle to channel change than a model "
                    "trained only on ASVspoof."),
        method=("Score the SAME two corpora Phase J used - ASVspoof 2019 LA "
                "eval as an in-domain control and VIVE's synthesis probe as "
                "the off-domain test - with the same EER implementation, so "
                "every row sits directly beside AASIST's."))
    exp.config(per_class=args.per_class, max_seconds=MAX_SECONDS,
               sample_rate=SAMPLE_RATE,
               adoption_rule="adopt only if probe EER is decisively better "
                             "than AASIST's 0.4333")
    exp.result("aasist_baseline", AASIST)

    api = HfApi()
    print("=== corpora ===")
    in_domain = collect(args.per_class)
    probe = load_probe()
    print(f"  ASVspoof LA eval: {len(in_domain['spoof'])} spoof / "
          f"{len(in_domain['bonafide'])} bonafide")
    print(f"  VIVE probe:       {len(probe['spoof'])} spoof / "
          f"{len(probe['bonafide'])} bonafide")
    exp.dataset(name="SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA",
                source="HuggingFace", license="ODC-By-1.0",
                split="test (LA eval)",
                samples=sum(len(v) for v in in_domain.values()),
                role="in-domain control")
    exp.dataset(name="VIVE synthesis probe (SpeechT5 + HiFiGAN vs FLEURS)",
                source="in-repo", license="MIT + CC-BY-4.0", split="probe",
                samples=sum(len(v) for v in probe.values()),
                role="off-domain test")

    results: dict[str, dict] = {}
    for repo, expected_license in CANDIDATES.items():
        print(f"\n=== {repo} ===")
        try:
            info = api.model_info(repo)
            declared = (info.card_data or {}).get("license")
            if declared != expected_license:
                results[repo] = {"skipped": f"license={declared!r}, "
                                            f"expected {expected_license!r}"}
                print(f"  skipped: {results[repo]['skipped']}")
                continue
            path = snapshot_download(repo, cache_dir=CACHE,
                                     allow_patterns=["*.json", "*.safetensors",
                                                     "*.txt"])
            extractor = AutoFeatureExtractor.from_pretrained(path)
            model = AutoModelForAudioClassification.from_pretrained(path).eval()
        except Exception as exc:  # noqa: BLE001
            results[repo] = {"error": f"{type(exc).__name__}: {str(exc)[:140]}"}
            print(f"  unavailable: {results[repo]['error']}")
            continue

        labels = dict(getattr(model.config, "id2label", {}) or {})
        spoof_at = spoof_index(model.config)
        if spoof_at is None:
            # Without a label map there is no defensible readout. Guessing an
            # index produces a plausible number that may be exactly inverted.
            results[repo] = {"skipped": f"no spoof label in id2label={labels}"}
            print(f"  skipped: {results[repo]['skipped']}")
            continue

        exp.model(name=repo, revision=repo, license=declared,
                  id2label=labels, spoof_index=spoof_at,
                  parameters_m=round(
                      sum(p.numel() for p in model.parameters()) / 1e6, 1))
        print(f"  labels {labels}, spoof index {spoof_at}")

        row = {"id2label": labels, "spoof_index": spoof_at}
        for name, clips in (("in_domain", in_domain), ("vive_probe", probe)):
            scored = {k: score_clips(model, extractor, v, torch, spoof_at)
                      for k, v in clips.items()}
            row[name] = measure(scored["spoof"], scored["bonafide"])
            print(f"  {name:<12} EER {row[name].get('eer')}  "
                  f"AUC {row[name].get('roc_auc')}")

        probe_eer = row["vive_probe"].get("eer")
        row["beats_aasist_off_domain"] = (
            probe_eer is not None and probe_eer < AASIST["probe_eer"] - 0.10)
        row["passes_in_domain_control"] = (
            row["in_domain"].get("eer") is not None
            and row["in_domain"]["eer"] < 0.20)
        results[repo] = row
        del model

    exp.result("candidates", results)

    viable = [r for r, row in results.items()
              if row.get("beats_aasist_off_domain")
              and row.get("passes_in_domain_control")]
    exp.result("viable_replacements", viable)

    print("\n--- off-domain transfer, the question that matters ---")
    print(f"  {'AASIST (current)':<48}{AASIST['probe_eer']:.4f}")
    for repo, row in results.items():
        value = (row.get("vive_probe") or {}).get("eer")
        print(f"  {repo:<48}{value if value is not None else 'n/a'}")

    exp.limitation(
        "The off-domain test is ONE synthesis family (SpeechT5 + HiFiGAN) in "
        "one language against FLEURS bonafide. A candidate that beat AASIST "
        "here would still need evaluating on handset-captured audio and on "
        "generators outside this probe before shipping (P2).")
    exp.limitation(
        "All four candidates share a wav2vec2 backbone. Common failure across "
        "them is evidence about that approach on this probe, not proof that "
        "no anti-spoof model transfers.")
    exp.limitation(
        "Training data for these checkpoints is not documented in their "
        "cards. If any was trained on ASVspoof, its in-domain row is a "
        "training-set score and not a measurement - which is why in-domain "
        "is used only as a sanity control and never as a reason to adopt.")
    exp.limitation(
        "Scores are the softmax over a two-class head, read through each "
        "model's own id2label. No calibration is claimed and these are not "
        "probabilities of fraud (P3).")
    exp.limitation(
        f"{args.per_class} clips per class in-domain and whatever the probe "
        "holds. EER differences of a few points should not be read as real.")

    if viable:
        interpretation = (
            f"{len(viable)} candidate(s) beat AASIST off-domain while passing "
            f"the in-domain control: {viable}. The replacement option is "
            f"therefore live rather than hypothetical.")
        conclusion = (
            "A replacement exists and should be integrated behind the "
            "existing anti-spoof interface, then re-measured on "
            "handset-captured audio before any detection claim is made. "
            "Until that measurement exists the channel stays bounded by "
            "SYNTHETIC_ONLY_CEILING and is not presented to a user as "
            "synthetic-voice evidence.")
    else:
        interpretation = (
            "No candidate cleared the bar. Every model that could be loaded "
            "either failed the in-domain control or failed to transfer to "
            "VIVE's probe, the same way AASIST does. Four checkpoints sharing "
            "a wav2vec2 backbone failing together is a statement about "
            "off-domain anti-spoofing on this audio, not about one model.")
        conclusion = (
            "The replacement option is closed with the models available, so "
            "the remaining honest choice is the other one Phase J named: "
            "REMOVE the anti-spoof contribution from the fused risk score. "
            "It costs ~45% of the packet budget (O13) and contributes no "
            "measured signal on VIVE's audio, and a channel that cannot "
            "discriminate can still move a score - which is contamination, "
            "not evidence. Intent, behaviour, speaker consistency, context "
            "and temporal evidence remain.")

    exp.finish(interpretation=interpretation, conclusion=conclusion)
    return 0


if __name__ == "__main__":
    sys.exit(main())
