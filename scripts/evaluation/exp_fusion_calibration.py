"""Phase 9: what each evidence channel contributes, and what the score means.

Two questions that have to be answered together, because the answer to the
second depends on the first.

**Ablation.** `fusion.py` combines five channels with a noisy-OR. Phase 9E
measured that the two text heads are strongly dependent, and a noisy-OR over
dependent inputs double-counts. This runs the real fusion over real head
outputs with channels withheld one at a time, and reports both how well each
configuration separates scam from benign and how much the score moves.

**Calibration.** `risk.score = 91` must never be read as "91% probability of
fraud" (`PROJECT_SPEC.md` 2.1). That is a rule the product states; this
measures whether it is also true. If the score happened to be well calibrated
the rule would be a missed opportunity, and if it is badly calibrated the rule
is load-bearing and needs the evidence behind it.

The honest shape of this evaluation
-----------------------------------
There is no labelled corpus of VIVE calls. What exists is held-out SMS text
with an `is_scam` flag. So this drives fusion with REAL intent and behaviour
outputs on that text, and holds the audio channels at their real production
values for a text-only record: no anti-spoof score, and `NO_REFERENCE` for the
speaker. That is not a stand-in for audio evidence - it is what fusion
genuinely receives when audio evidence is absent, which is also what it
receives for the first ~4 seconds of every real call.

Consequences, stated rather than buried:
  * The ablation covers the intent, behaviour and context channels. The
    anti-spoof and speaker channels are exercised by a separate LABEL-FREE
    sensitivity sweep, because no labelled audio exists to score them against.
  * `is_scam` is a proxy for "this text is a scam", not for "this caller is
    committing fraud". Calibration against it is calibration against the
    proxy.
  * Intent labels are 100% collinear with `is_scam` (O10), so a configuration
    containing the intent channel is being graded against a target its own
    training labels were derived from. That inflates it, and the gap between
    the intent row and the behaviour row should be read with that in mind.

Thresholds are selected on the VALIDATION split and reported on TEST. Reusing
test data to pick an operating point and then reporting that point on the same
data is the standard way to produce a number that does not survive contact
with reality.

Usage:
    python scripts/evaluation/exp_fusion_calibration.py [--limit 0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import ROOT, Experiment, add_backend_to_path, model_dir  # noqa: E402

MANIFEST_DIR = os.path.join(ROOT, "data", "manifests")
ALERT_THRESHOLD = 65          # policy.py raises an alert at HIGH
CALIBRATION_BINS = 10
_DIGITS = re.compile(r"\d+")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def near_key(text: str) -> str:
    t = _NONWORD.sub(" ", _DIGITS.sub("#", text.lower()))
    return hashlib.sha1(_SPACE.sub(" ", t).strip().encode("utf-8")).hexdigest()


def read_split(split: str) -> list[dict]:
    with open(os.path.join(MANIFEST_DIR, f"scamshield.{split}.jsonl"),
              encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def roc_auc(positive: list[float], negative: list[float]) -> float:
    """Rank-based AUC; ties count a half. O(n log n) via merged ranking."""
    merged = sorted([(v, 1) for v in positive] + [(v, 0) for v in negative])
    ranks: list[float] = [0.0] * len(merged)
    i = 0
    while i < len(merged):
        j = i
        while j + 1 < len(merged) and merged[j + 1][0] == merged[i][0]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = average
        i = j + 1
    rank_sum = sum(r for r, (_v, label) in zip(ranks, merged) if label == 1)
    n_pos, n_neg = len(positive), len(negative)
    if not n_pos or not n_neg:
        return float("nan")
    return round((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    add_backend_to_path()
    import numpy as np

    from app.adapters.interfaces import (AntiSpoofResult, AsrResult,
                                         BehaviorResult, IntentResult,
                                         SpeakerResult, VadResult)
    from app.adapters.real.text_classifiers import (RealBehaviorAdapter,
                                                    RealIntentAdapter)
    from app.risk.fusion import FusionInput, fuse
    from app.schemas.models import (AdapterMode, AnalyzerStatus, AudioQuality,
                                    Behavior, Intent)

    exp = Experiment(
        "9F_fusion_ablation_calibration",
        question=("How much does each evidence channel contribute to the "
                  "fused risk score, and is that score calibrated well enough "
                  "to be read as a probability?"),
        hypothesis=("The intent channel will dominate, because its influence "
                    "weight is the highest and its labels are collinear with "
                    "the target. The score will NOT be calibrated as a "
                    "probability, since nothing in fusion was fitted to "
                    "produce one."),
        method=("Drive the real fusion with real intent and behaviour outputs "
                "over held-out text, ablating channels. Select thresholds on "
                "validation, report on test. Measure reliability, Brier score "
                "and expected calibration error against is_scam."))

    intent_adapter = RealIntentAdapter(model_dir("intent-classifier"))
    behavior_adapter = RealBehaviorAdapter(model_dir("behavior-classifier"))
    for adapter in (intent_adapter, behavior_adapter):
        if adapter.load() is not AnalyzerStatus.AVAILABLE:
            print(f"{adapter.adapter_key} unavailable: {adapter.describe().detail}")
            return 1

    exp.model(name="risk-fusion", revision="risk-fusion-demo-1",
              license="in-repo", note="expert-set weights, never fitted (O6)")

    train_keys = {near_key(r["text"]) for r in read_split("train")}

    def evidence(records: list[dict]) -> list[dict]:
        out = []
        for n, record in enumerate(records):
            if n and n % 2000 == 0:
                print(f"    {n:,}/{len(records):,}")
            language = record.get("language") or "en"
            intent_result = intent_adapter.analyze(record["text"], language)
            behavior_result = behavior_adapter.analyze(record["text"], language)
            if (intent_result.status is not AnalyzerStatus.AVAILABLE
                    or behavior_result.status is not AnalyzerStatus.AVAILABLE):
                continue
            out.append({
                "intent": intent_result.label,
                "behaviors": list(behavior_result.labels),
                "asr_confidence": 0.9,
                "is_scam": int(record.get("is_scam", 0)),
                "leaked": near_key(record["text"]) in train_keys,
            })
        return out

    test_records = read_split("test")
    val_records = read_split("val")
    if args.limit:
        test_records = test_records[:args.limit]
        val_records = val_records[:args.limit]
    print(f"scoring validation ({len(val_records):,}) ...")
    val = evidence(val_records)
    print(f"scoring test ({len(test_records):,}) ...")
    test = evidence(test_records)
    test_clean = [r for r in test if not r["leaked"]]
    print(f"  val {len(val):,}  test {len(test):,}  test de-leaked {len(test_clean):,}\n")

    exp.dataset(name="scamshield", source="huggingface.co/datasets/sidzzz07/scamshield-dataset",
                license="MIT", split="val (threshold selection)", samples=len(val))
    exp.dataset(name="scamshield", source="huggingface.co/datasets/sidzzz07/scamshield-dataset",
                license="MIT", split="test (reporting)", samples=len(test))
    exp.config(alert_threshold=ALERT_THRESHOLD, calibration_bins=CALIBRATION_BINS,
               audio_channels="absent (no anti-spoof score, speaker NO_REFERENCE)")

    # -- one fusion call, with channels selectively withheld ---------------
    def fused_score(row: dict, *, use_intent=True, use_behavior=True,
                    caller_verified=False, antispoof: float | None = None,
                    similarity: float | None = None) -> int:
        vad = VadResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                        mode=AdapterMode.REAL, has_speech=True,
                        quality=AudioQuality.GOOD)
        spoof = AntiSpoofResult(
            status=(AnalyzerStatus.AVAILABLE if antispoof is not None
                    else AnalyzerStatus.INSUFFICIENT_AUDIO),
            model_version="v", mode=AdapterMode.REAL, score=antispoof)
        speaker = SpeakerResult(
            status=(AnalyzerStatus.AVAILABLE if similarity is not None
                    else AnalyzerStatus.NO_REFERENCE),
            model_version="v", mode=AdapterMode.REAL, similarity=similarity)
        asr = AsrResult(status=AnalyzerStatus.AVAILABLE, model_version="v",
                        mode=AdapterMode.REAL, transcript="x",
                        confidence=row["asr_confidence"])
        intent = IntentResult(
            status=(AnalyzerStatus.AVAILABLE if use_intent
                    else AnalyzerStatus.UNAVAILABLE),
            model_version="v", mode=AdapterMode.REAL,
            label=row["intent"] if use_intent else Intent.UNKNOWN,
            confidence=0.9)
        behavior = BehaviorResult(
            status=(AnalyzerStatus.AVAILABLE if use_behavior
                    else AnalyzerStatus.UNAVAILABLE),
            model_version="v", mode=AdapterMode.REAL,
            labels=row["behaviors"] if use_behavior else [Behavior.NORMAL],
            confidence=0.9)
        return fuse(FusionInput(
            vad=vad, antispoof=spoof, speaker=speaker, asr=asr, intent=intent,
            behavior=behavior, caller_verified=caller_verified,
            session_authenticated=True)).risk.score

    CONFIGS = {
        "full_text_pipeline": dict(use_intent=True, use_behavior=True),
        "intent_only": dict(use_intent=True, use_behavior=False),
        "behavior_only": dict(use_intent=False, use_behavior=True),
        "context_only": dict(use_intent=False, use_behavior=False),
        "full_caller_verified": dict(use_intent=True, use_behavior=True,
                                     caller_verified=True),
    }

    # -- ablation: separation of scam from benign -------------------------
    ablation: dict[str, dict] = {}
    for name, kwargs in CONFIGS.items():
        scores = [fused_score(r, **kwargs) for r in test_clean]
        labels = [r["is_scam"] for r in test_clean]
        pos = [s for s, y in zip(scores, labels) if y == 1]
        neg = [s for s, y in zip(scores, labels) if y == 0]

        # Threshold chosen on validation, then applied here.
        val_scores = [fused_score(r, **kwargs) for r in val]
        val_labels = [r["is_scam"] for r in val]
        best_t, best_f1 = ALERT_THRESHOLD, -1.0
        for t in range(5, 100, 5):
            tp = sum(1 for s, y in zip(val_scores, val_labels) if s >= t and y == 1)
            fp = sum(1 for s, y in zip(val_scores, val_labels) if s >= t and y == 0)
            fn = sum(1 for s, y in zip(val_scores, val_labels) if s < t and y == 1)
            f1 = 2 * tp / max(2 * tp + fp + fn, 1)
            if f1 > best_f1:
                best_t, best_f1 = t, f1

        def rates(threshold: int) -> dict:
            tp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 1)
            fp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 0)
            fn = sum(1 for s, y in zip(scores, labels) if s < threshold and y == 1)
            tn = sum(1 for s, y in zip(scores, labels) if s < threshold and y == 0)
            return {
                "threshold": threshold,
                "precision": round(tp / max(tp + fp, 1), 4),
                "recall": round(tp / max(tp + fn, 1), 4),
                "false_positive_rate": round(fp / max(fp + tn, 1), 4),
                "false_negative_rate": round(fn / max(fn + tp, 1), 4),
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            }

        ablation[name] = {
            "roc_auc": roc_auc([float(s) for s in pos], [float(s) for s in neg]),
            "median_score_scam": int(np.median(pos)) if pos else None,
            "median_score_benign": int(np.median(neg)) if neg else None,
            "at_policy_alert_threshold_65": rates(ALERT_THRESHOLD),
            "at_threshold_selected_on_validation": rates(best_t),
            "validation_selected_threshold": best_t,
        }
        a = ablation[name]
        print(f"  {name:<24} AUC {a['roc_auc']:.4f}  "
              f"scam_med {a['median_score_scam']}  benign_med {a['median_score_benign']}  "
              f"P/R@65 {a['at_policy_alert_threshold_65']['precision']:.3f}/"
              f"{a['at_policy_alert_threshold_65']['recall']:.3f}")

    # -- label-free sensitivity for the audio channels ---------------------
    # No labelled audio exists, so these channels cannot be scored for
    # accuracy. What CAN be measured is how far each moves the output, which
    # is what determines whether a wrong anti-spoof score is dangerous.
    benign = {"intent": Intent.NORMAL_CONVERSATION, "behaviors": [Behavior.NORMAL],
              "asr_confidence": 0.9, "is_scam": 0, "leaked": False}
    risky = {"intent": Intent.OTP_REQUEST, "behaviors": [Behavior.URGENCY],
             "asr_confidence": 0.9, "is_scam": 1, "leaked": False}
    sensitivity = {
        "antispoof_sweep_on_benign_text": {
            str(v): fused_score(benign, antispoof=v)
            for v in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)},
        "antispoof_sweep_on_risky_text": {
            str(v): fused_score(risky, antispoof=v)
            for v in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)},
        "speaker_similarity_sweep_on_benign_text": {
            str(v): fused_score(benign, similarity=v)
            for v in (0.0, 0.25, 0.5, 0.75, 1.0)},
        "no_audio_evidence_benign": fused_score(benign),
        "no_audio_evidence_risky": fused_score(risky),
    }
    ceiling_binds = max(
        int(v) for v in sensitivity["antispoof_sweep_on_benign_text"].values())
    sensitivity["max_score_from_antispoof_alone"] = ceiling_binds
    sensitivity["synthetic_only_ceiling_binds"] = ceiling_binds <= 64
    print(f"\n  anti-spoof alone on benign text tops out at {ceiling_binds} "
          f"(SYNTHETIC_ONLY_CEILING binds: "
          f"{sensitivity['synthetic_only_ceiling_binds']})")

    # -- calibration -------------------------------------------------------
    scores = [fused_score(r, **CONFIGS["full_text_pipeline"]) for r in test_clean]
    labels = [r["is_scam"] for r in test_clean]
    probs = np.array(scores, dtype=float) / 100.0
    truth = np.array(labels, dtype=float)

    brier = float(np.mean((probs - truth) ** 2))
    bins, ece = [], 0.0
    for b in range(CALIBRATION_BINS):
        lo, hi = b / CALIBRATION_BINS, (b + 1) / CALIBRATION_BINS
        mask = (probs >= lo) & (probs < hi if b < CALIBRATION_BINS - 1 else probs <= hi)
        n = int(mask.sum())
        if not n:
            bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0})
            continue
        predicted = float(probs[mask].mean())
        observed = float(truth[mask].mean())
        ece += n / len(probs) * abs(predicted - observed)
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": n,
                     "mean_predicted": round(predicted, 4),
                     "observed_scam_rate": round(observed, 4),
                     "gap": round(observed - predicted, 4)})

    base_rate = float(truth.mean())
    calibration = {
        "brier_score": round(brier, 4),
        "brier_score_of_always_predicting_base_rate": round(
            float(np.mean((base_rate - truth) ** 2)), 4),
        "expected_calibration_error": round(ece, 4),
        "base_scam_rate_in_test": round(base_rate, 4),
        "reliability_bins": bins,
        "score_is_a_calibrated_probability": bool(ece < 0.05),
    }
    print(f"\n  Brier {calibration['brier_score']:.4f} "
          f"(base-rate baseline {calibration['brier_score_of_always_predicting_base_rate']:.4f})")
    print(f"  ECE   {calibration['expected_calibration_error']:.4f}  "
          f"-> score/100 is a calibrated probability: "
          f"{calibration['score_is_a_calibrated_probability']}")
    for b in bins:
        if b["n"]:
            print(f"    {b['bin']}  n={b['n']:<6} predicted {b['mean_predicted']:.3f}  "
                  f"observed {b['observed_scam_rate']:.3f}  gap {b['gap']:+.3f}")

    exp.result("ablation", ablation)
    exp.result("audio_channel_sensitivity_label_free", sensitivity)
    exp.result("calibration", calibration)
    exp.result("records_scored", {"validation": len(val), "test": len(test),
                                  "test_deleaked": len(test_clean)})

    exp.limitation(
        "Fusion is driven by TEXT records, not calls. The anti-spoof and "
        "speaker channels carry no evidence in the ablation because no "
        "labelled audio exists to score them against; their effect is "
        "reported separately as a label-free sensitivity sweep.")
    exp.limitation(
        "`is_scam` is a proxy. It marks scam TEXT, not confirmed fraud by a "
        "caller. Every precision, recall and calibration figure here is "
        "against that proxy.")
    exp.limitation(
        "Intent labels are 100% collinear with `is_scam` (O10), so any "
        "configuration containing the intent channel is graded against a "
        "target derived from its own training labels. Those rows are "
        "optimistic by construction and the size of that inflation is not "
        "separately measurable from this corpus.")
    exp.limitation(
        "Thresholds were selected on validation and reported on test, but "
        "both splits come from the same corpus, so the selection transfers "
        "only as far as the corpus does.")
    exp.limitation(
        "Calibration is measured on the de-leaked test split with the audio "
        "channels absent. A live call with anti-spoof evidence present would "
        "produce a different score distribution, which is not calibrated here.")

    exp.finish(
        interpretation=(
            f"The full text pipeline separates scam from benign text at AUC "
            f"{ablation['full_text_pipeline']['roc_auc']}, against "
            f"{ablation['behavior_only']['roc_auc']} for behaviour alone and "
            f"{ablation['context_only']['roc_auc']} for context alone - the "
            f"intent channel carries nearly all of it, as its influence "
            f"weight and its label collinearity both predict. On calibration, "
            f"the expected calibration error is "
            f"{calibration['expected_calibration_error']} and score/100 is "
            f"{'' if calibration['score_is_a_calibrated_probability'] else 'NOT '}"
            f"a usable probability."),
        conclusion=(
            "The prohibition on reading `risk.score` as a fraud probability is "
            "now measured rather than merely asserted, and the reliability "
            "table is the evidence. The ablation also shows the fused score is "
            "close to a one-channel score on text-only input, which is what "
            "the noisy-OR independence assumption was supposed to avoid; "
            "fusion weights stay provisional (O6)."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
