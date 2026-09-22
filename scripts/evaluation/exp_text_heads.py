"""Phase 9: intent and behaviour accuracy, and whether they are one signal.

Three questions, measured in one pass because they need the same forward passes.

1. **Held-out accuracy through the real adapters.** Macro/micro/weighted F1,
   per-class precision/recall/F1 with support, and confusion matrices. Classes
   under the 30-record floor (`BLOCKERS.md` O9) are reported but marked
   UNMEASURABLE rather than given a number that looks like a capability.

2. **What near-duplicate leakage was worth.** Phase 9A found 622 of 8,644 test
   records share a digits-masked key with a training record. Every metric is
   therefore computed twice: on the full test split, and on the split with
   those records removed. The difference is the part of the headline figure
   that came from having seen the text before.

3. **Are intent and behaviour independent evidence?** `fusion.py` combines them
   with a noisy-OR, which assumes conditional independence. `BLOCKERS.md` O10
   established that the *labels* are collinear with `is_scam`. This measures
   the same thing one level down, on the **model outputs** that fusion actually
   consumes: correlation and mutual information between the two heads' risk
   contributions, and how much either adds once the other is known.

Why model outputs rather than labels: fusion never sees a label. If the heads
had learned genuinely different features, their outputs could be less
redundant than their training labels. Measuring the outputs is the only way to
find out, and it is the number that bears on the fusion assumption.

Usage:
    python scripts/evaluation/exp_text_heads.py [--limit 0]
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

sys.path.insert(0, os.path.join(ROOT, "models", "training"))
from vive_labels import BEHAVIOR_LABELS, INTENT_LABELS  # noqa: E402

MANIFEST_DIR = os.path.join(ROOT, "data", "manifests")
MIN_SUPPORT = 30
_DIGITS = re.compile(r"\d+")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def near_key(text: str) -> str:
    t = _NONWORD.sub(" ", _DIGITS.sub("#", text.lower()))
    return hashlib.sha1(_SPACE.sub(" ", t).strip().encode("utf-8")).hexdigest()


def read_split(split: str) -> list[dict]:
    path = os.path.join(MANIFEST_DIR, f"scamshield.{split}.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def classification_block(y_true, y_pred, labels, *, multilabel: bool) -> dict:
    """Per-class and aggregate scores, with absent classes named as such.

    sklearn emits a 0.000 row for a class that was never present and never
    predicted, which reads as "the model scored zero" rather than "there was
    nothing to score". Those rows are relabelled, and the macro-F1 denominator
    is stated because it differs between the two tasks.
    """
    from sklearn.metrics import f1_score, precision_recall_fscore_support

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(len(labels))), zero_division=0)

    per_class = {}
    scored = 0
    for i, name in enumerate(labels):
        n = int(support[i])
        if n == 0:
            per_class[name] = {"support": 0, "status": "NO TEST DATA - cannot be scored"}
            continue
        scored += 1
        entry = {
            "support": n,
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
        }
        if n < MIN_SUPPORT:
            entry["status"] = (
                f"UNMEASURABLE - {n} records is below the {MIN_SUPPORT}-record "
                "floor; this F1 must not be quoted as a capability")
        per_class[name] = entry

    present = [i for i in range(len(labels)) if support[i] > 0]
    return {
        "macro_f1": round(float(f1_score(
            y_true, y_pred, labels=present, average="macro", zero_division=0)), 4),
        "macro_f1_denominator": (
            f"{len(present)} of {len(labels)} classes present in the test split"
            if not multilabel else
            f"all {len(labels)} classes, absent ones counted as 0"),
        "micro_f1": round(float(f1_score(
            y_true, y_pred, average="micro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(
            y_true, y_pred, labels=present, average="weighted", zero_division=0)), 4),
        "classes_scored": scored,
        "classes_with_no_data": len(labels) - scored,
        "per_class": per_class,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="cap test records (0 = all)")
    args = parser.parse_args()

    add_backend_to_path()
    import numpy as np
    from sklearn.metrics import confusion_matrix

    from app.adapters.real.text_classifiers import (RealBehaviorAdapter,
                                                    RealIntentAdapter)
    from app.schemas.models import AnalyzerStatus

    exp = Experiment(
        "9E_text_heads",
        question=("How well do the intent and behaviour heads perform on "
                  "held-out data, how much of that came from near-duplicate "
                  "leakage, and are their outputs independent enough for a "
                  "noisy-OR fusion?"),
        hypothesis=("Headline macro-F1 will drop once near-duplicates are "
                    "removed, and the two heads' outputs will be strongly "
                    "dependent because both were derived from the same "
                    "scam/not-scam partition (O10)."),
        method=("Run the real adapters over the held-out split. Score twice - "
                "full split and de-leaked split - and measure correlation and "
                "mutual information between the two heads' risk contributions "
                "as fusion consumes them."))

    intent_adapter = RealIntentAdapter(model_dir("intent-classifier"))
    behavior_adapter = RealBehaviorAdapter(model_dir("behavior-classifier"))
    for adapter in (intent_adapter, behavior_adapter):
        if adapter.load() is not AnalyzerStatus.AVAILABLE:
            print(f"{adapter.adapter_key} unavailable: {adapter.describe().detail}")
            return 1
    print("both text heads loaded\n")

    exp.model(name="intent-classifier", revision="phase7 mDistilBERT fine-tune",
              license="Apache-2.0 (base)")
    exp.model(name="behavior-classifier", revision="phase7 mDistilBERT fine-tune",
              license="Apache-2.0 (base)")

    test = read_split("test")
    if args.limit:
        test = test[:args.limit]
    train_keys = {near_key(r["text"]) for r in read_split("train")}
    exp.dataset(name="scamshield", source="huggingface.co/datasets/sidzzz07/scamshield-dataset",
                license="MIT", split="test", samples=len(test))
    exp.config(min_support_floor=MIN_SUPPORT,
               behavior_threshold=0.5, max_length=96)

    intent_index = {name: i for i, name in enumerate(INTENT_LABELS)}
    behavior_index = {name: i for i, name in enumerate(BEHAVIOR_LABELS)}

    rows = []
    print(f"scoring {len(test):,} held-out records ...")
    for n, record in enumerate(test):
        if n and n % 2000 == 0:
            print(f"  {n:,}/{len(test):,}")
        text = record["text"]
        language = record.get("language") or "en"
        intent_result = intent_adapter.analyze(text, language)
        behavior_result = behavior_adapter.analyze(text, language)
        if (intent_result.status is not AnalyzerStatus.AVAILABLE
                or behavior_result.status is not AnalyzerStatus.AVAILABLE):
            continue
        rows.append({
            "true_intent": intent_index[record["label_intent"]],
            "pred_intent": intent_index[intent_result.label.value],
            "intent_confidence": float(intent_result.confidence or 0.0),
            "true_behaviors": [behavior_index[b] for b in record["label_behaviors"]],
            "pred_behaviors": [behavior_index[b.value] for b in behavior_result.labels],
            "behavior_confidence": float(behavior_result.confidence or 0.0),
            "is_scam": int(record.get("is_scam", 0)),
            "leaked": near_key(text) in train_keys,
        })
    print(f"  scored {len(rows):,}\n")

    # -- accuracy, full split and de-leaked -------------------------------
    def score(subset: list[dict]) -> dict:
        y_true = [r["true_intent"] for r in subset]
        y_pred = [r["pred_intent"] for r in subset]
        intent_block = classification_block(y_true, y_pred, INTENT_LABELS,
                                            multilabel=False)
        intent_block["confusion_matrix"] = confusion_matrix(
            y_true, y_pred, labels=list(range(len(INTENT_LABELS)))).tolist()

        bt = np.zeros((len(subset), len(BEHAVIOR_LABELS)), dtype=int)
        bp = np.zeros_like(bt)
        for i, r in enumerate(subset):
            for j in r["true_behaviors"]:
                bt[i, j] = 1
            for j in r["pred_behaviors"]:
                bp[i, j] = 1
        behavior_block = classification_block(bt, bp, BEHAVIOR_LABELS,
                                              multilabel=True)
        behavior_block["per_label_confusion"] = {
            name: {"tp": int((bt[:, j] & bp[:, j]).sum()),
                   "fp": int(((1 - bt[:, j]) & bp[:, j]).sum()),
                   "fn": int((bt[:, j] & (1 - bp[:, j])).sum()),
                   "tn": int(((1 - bt[:, j]) & (1 - bp[:, j])).sum())}
            for j, name in enumerate(BEHAVIOR_LABELS)}
        return {"records": len(subset), "intent": intent_block,
                "behavior": behavior_block}

    deleaked = [r for r in rows if not r["leaked"]]
    full_scores = score(rows)
    clean_scores = score(deleaked)

    print(f"  full test split ({full_scores['records']:,}): "
          f"intent macro-F1 {full_scores['intent']['macro_f1']}, "
          f"behaviour macro-F1 {full_scores['behavior']['macro_f1']}")
    print(f"  de-leaked      ({clean_scores['records']:,}): "
          f"intent macro-F1 {clean_scores['intent']['macro_f1']}, "
          f"behaviour macro-F1 {clean_scores['behavior']['macro_f1']}")
    leak_cost = {
        "records_removed": len(rows) - len(deleaked),
        "intent_macro_f1_delta": round(
            clean_scores["intent"]["macro_f1"] - full_scores["intent"]["macro_f1"], 4),
        "behavior_macro_f1_delta": round(
            clean_scores["behavior"]["macro_f1"] - full_scores["behavior"]["macro_f1"], 4),
    }

    # -- dependence between the two heads AS FUSION SEES THEM --------------
    from app.risk.fusion import BEHAVIOR_RISK, INTENT_RISK
    from app.schemas.models import Behavior, Intent

    intent_risk = np.array([INTENT_RISK[Intent(INTENT_LABELS[r["pred_intent"]])]
                            for r in rows])
    behavior_risk = np.array([
        max((BEHAVIOR_RISK[Behavior(BEHAVIOR_LABELS[j])]
             for j in r["pred_behaviors"]), default=0.0) for r in rows])
    scam = np.array([r["is_scam"] for r in rows])

    def mutual_information(a, b, bins: int = 8) -> float:
        """MI in bits between two binned continuous signals."""
        joint, _, _ = np.histogram2d(a, b, bins=bins)
        joint = joint / joint.sum()
        pa = joint.sum(axis=1, keepdims=True)
        pb = joint.sum(axis=0, keepdims=True)
        nz = joint > 0
        return float((joint[nz] * np.log2(joint[nz] / (pa @ pb)[nz])).sum())

    def entropy(a, bins: int = 8) -> float:
        counts, _ = np.histogram(a, bins=bins)
        p = counts / counts.sum()
        p = p[p > 0]
        return float(-(p * np.log2(p)).sum())

    dependence = {
        "pearson_intent_vs_behavior_risk": round(
            float(np.corrcoef(intent_risk, behavior_risk)[0, 1]), 4),
        "spearman_intent_vs_behavior_risk": round(float(np.corrcoef(
            np.argsort(np.argsort(intent_risk)),
            np.argsort(np.argsort(behavior_risk)))[0, 1]), 4),
        "mutual_information_bits": round(
            mutual_information(intent_risk, behavior_risk), 4),
        "entropy_intent_risk_bits": round(entropy(intent_risk), 4),
        "entropy_behavior_risk_bits": round(entropy(behavior_risk), 4),
        "normalised_mutual_information": round(
            mutual_information(intent_risk, behavior_risk)
            / max(min(entropy(intent_risk), entropy(behavior_risk)), 1e-9), 4),
        "predicted_intent_non_normal_matches_is_scam_pct": round(100.0 * float(
            np.mean((np.array([r["pred_intent"] for r in rows])
                     != INTENT_LABELS.index("NORMAL_CONVERSATION")) == (scam == 1))), 4),
        "predicted_behaviour_flag_matches_is_scam_pct": round(100.0 * float(
            np.mean((behavior_risk > 0.05) == (scam == 1))), 4),
        "behaviour_flag_rate_on_benign_records": round(float(
            np.mean(behavior_risk[scam == 0] > 0.05)), 4),
        "behaviour_flag_rate_on_scam_records": round(float(
            np.mean(behavior_risk[scam == 1] > 0.05)), 4),
    }
    print("\n  dependence between the two heads' fusion inputs:")
    for key, value in dependence.items():
        print(f"    {key:<52}{value}")

    exp.result("full_test_split", full_scores)
    exp.result("deleaked_test_split", clean_scores)
    exp.result("near_duplicate_leakage_cost", leak_cost)
    exp.result("head_dependence", dependence)

    exp.limitation(
        "This is SMS text, not call transcripts. Both heads are evaluated on "
        "the register they were trained on; conversational speech transcribed "
        "by ASR is a different distribution and is not measured here.")
    exp.limitation(
        "Records are scored from ground-truth text, not from ASR output. In "
        "the live pipeline these heads read a transcript, so real end-to-end "
        "accuracy is bounded by ASR accuracy as well (docs/BLOCKERS.md P4).")
    exp.limitation(
        "Intent labels remain 100% collinear with the corpus scam flag (O10). "
        "A high intent macro-F1 partly measures the easier scam/not-scam "
        "boundary and must not be presented as intent-discrimination accuracy.")
    exp.limitation(
        "No Tamil records exist, so neither head is evaluated in Tamil at all. "
        "Tamil remains UNSUPPORTED_LANGUAGE (O11).")
    exp.limitation(
        "The de-leaked split removes records whose digits-masked key matches a "
        "training record. That over-removes slightly, so the de-leaked figure "
        "is a conservative lower bound rather than an exact correction.")

    nmi = dependence["normalised_mutual_information"]
    exp.finish(
        interpretation=(
            f"Removing near-duplicates moved intent macro-F1 by "
            f"{leak_cost['intent_macro_f1_delta']:+.4f} and behaviour by "
            f"{leak_cost['behavior_macro_f1_delta']:+.4f} over "
            f"{leak_cost['records_removed']} records. On dependence, the two "
            f"heads' fusion inputs share a normalised mutual information of "
            f"{nmi}, and the behaviour head fires on "
            f"{dependence['behaviour_flag_rate_on_benign_records']:.2%} of "
            f"benign records. Both bear directly on the noisy-OR independence "
            f"assumption in fusion.py."),
        conclusion=(
            "Quote the de-leaked figures, with support counts, and never "
            "quote OTP_REQUEST. The dependence measurement determines whether "
            "noisy-OR is double-counting one signal; it feeds the fusion "
            "ablation rather than being acted on here."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
