"""Audits label coverage and label independence in the training corpus.

Phase 7 follow-up for BLOCKERS O9. Answers three questions that a headline
macro-F1 cannot:

1. Which taxonomy labels have no data, and which have too little to measure?
2. Is any label merely a proxy for another column?
3. Does the corpus contain the negative examples the product actually needs?

Question 2 matters more than it looks. The risk engine combines intent and
behaviour with a noisy-OR, which assumes the two carry INDEPENDENT evidence.
If both are collinear with a single underlying flag, that assumption fails and
fusion overstates confidence by counting one signal twice. This script measures
the collinearity instead of assuming it either way.

Reads the full local manifests, which carry the public labels the slim tracked
index omits. Writes `models/evaluation/label_coverage_audit.json`.

Usage:
    python scripts/training/audit_label_coverage.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFESTS = os.path.join(ROOT, "data", "manifests")
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

sys.path.insert(0, os.path.join(ROOT, "models", "training"))

from vive_labels import BEHAVIOR_LABELS, INTENT_LABELS  # noqa: E402

# Below this many test records a per-class metric is not worth reporting.
MIN_MEASURABLE_SUPPORT = 30
SPLITS = ("train", "val", "test")


def load() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for split in SPLITS:
        path = os.path.join(MANIFESTS, f"scamshield.{split}.jsonl")
        if not os.path.exists(path):
            raise SystemExit(
                f"missing {path}. Run scripts/training/build_manifests.py first; "
                "the full manifests are local-only by design."
            )
        with open(path, encoding="utf-8") as handle:
            rows[split] = [json.loads(line) for line in handle if line.strip()]
    return rows


def main() -> int:
    rows = load()
    every = [r for split in SPLITS for r in rows[split]]
    total = len(every)

    # --- intent coverage -------------------------------------------------
    intent_rows = []
    for label in INTENT_LABELS:
        counts = {s: sum(1 for r in rows[s] if r["label_intent"] == label)
                  for s in SPLITS}
        support = sum(counts.values())
        if support == 0:
            status = "NO_DATA"
        elif counts["test"] < MIN_MEASURABLE_SUPPORT:
            status = "UNMEASURABLE"
        else:
            status = "OK"
        intent_rows.append({
            "label": label, **counts, "total": support,
            "share_pct": round(100 * support / total, 4), "status": status,
        })

    # --- behaviour coverage ---------------------------------------------
    behavior_rows = []
    for label in BEHAVIOR_LABELS:
        counts = {s: sum(1 for r in rows[s] if label in r["label_behaviors"])
                  for s in SPLITS}
        support = sum(counts.values())
        if support == 0:
            status = "NO_DATA"
        elif counts["test"] < MIN_MEASURABLE_SUPPORT:
            status = "UNMEASURABLE"
        else:
            status = "OK"
        behavior_rows.append({
            "label": label, **counts, "total": support, "status": status,
        })

    # --- independence checks --------------------------------------------
    intent_agrees = sum(
        1 for r in every
        if (r["label_intent"] != "NORMAL_CONVERSATION") == bool(r["is_scam"]))
    behavior_agrees = sum(
        1 for r in every
        if (r["label_behaviors"] != ["NORMAL"]) == bool(r["is_scam"]))
    benign_with_behavior = sum(
        1 for r in every
        if r["label_behaviors"] != ["NORMAL"] and r["is_scam"] == 0)
    scam_without_behavior = sum(
        1 for r in every
        if r["label_behaviors"] == ["NORMAL"] and r["is_scam"] == 1)

    # --- where the UNKNOWN bucket comes from ------------------------------
    public_map: dict[str, Counter] = defaultdict(Counter)
    for r in every:
        public_map[r.get("label_intent_public") or "(empty)"][r["label_intent"]] += 1
    unknown_sources = sorted(
        ((p, c["UNKNOWN"]) for p, c in public_map.items() if c["UNKNOWN"]),
        key=lambda x: -x[1],
    )
    unknown_scam = Counter(
        r["is_scam"] for r in every if r["label_intent"] == "UNKNOWN")

    findings = []
    if intent_agrees == total:
        findings.append({
            "id": "INTENT_COLLINEAR_WITH_IS_SCAM",
            "severity": "HIGH",
            "detail": (
                f"'intent != NORMAL_CONVERSATION' reproduces is_scam for "
                f"{intent_agrees:,}/{total:,} records (100%). The intent head is "
                f"therefore a scam detector with sub-classes, not an independent "
                f"intent model, and its macro-F1 partly measures that easier task."
            ),
        })
    if benign_with_behavior == 0:
        findings.append({
            "id": "NO_BENIGN_BEHAVIOUR_EXAMPLES",
            "severity": "HIGH",
            "detail": (
                "No legitimate record carries any social-engineering behaviour. "
                "Real legitimate calls do use urgency and authority - a delivery "
                "notice, a genuine bank fraud alert. The behaviour head has never "
                "seen a benign instance of any behaviour, so it cannot learn that "
                "urgency alone is not fraud, and will likely fire on legitimate "
                "urgent calls."
            ),
        })
    if unknown_scam.get(0, 0) == 0 and unknown_scam.get(1, 0) > 0:
        findings.append({
            "id": "UNKNOWN_MEANS_UNMAPPED_SCAM",
            "severity": "MEDIUM",
            "detail": (
                f"All {unknown_scam[1]:,} UNKNOWN records are scams. In the VIVE "
                f"taxonomy UNKNOWN means 'intent could not be determined', which "
                f"includes benign speech; here it means 'scam genre outside the "
                f"taxonomy'. A production UNKNOWN prediction therefore does not "
                f"mean what the taxonomy says it means."
            ),
        })

    record = {
        "audited_at": str(date.today()),
        "blocker": "O9",
        "corpus": {"dataset_id": "scamshield", "records": total,
                   "splits": {s: len(rows[s]) for s in SPLITS}},
        "min_measurable_support": MIN_MEASURABLE_SUPPORT,
        "intent_coverage": intent_rows,
        "behavior_coverage": behavior_rows,
        "summary": {
            "intent_labels_total": len(INTENT_LABELS),
            "intent_no_data": sum(1 for r in intent_rows if r["status"] == "NO_DATA"),
            "intent_unmeasurable": sum(1 for r in intent_rows if r["status"] == "UNMEASURABLE"),
            "behavior_labels_total": len(BEHAVIOR_LABELS),
            "behavior_no_data": sum(1 for r in behavior_rows if r["status"] == "NO_DATA"),
            "behavior_unmeasurable": sum(1 for r in behavior_rows if r["status"] == "UNMEASURABLE"),
        },
        "independence": {
            "intent_predicts_is_scam_pct": round(100 * intent_agrees / total, 4),
            "behavior_predicts_is_scam_pct": round(100 * behavior_agrees / total, 4),
            "benign_records_with_a_behaviour": benign_with_behavior,
            "scam_records_without_a_behaviour": scam_without_behavior,
            "note": ("Risk fusion combines intent and behaviour as independent "
                     "evidence. These figures show how far that holds in the "
                     "training data."),
        },
        "unknown_bucket": {
            "total": sum(unknown_scam.values()),
            "by_is_scam": dict(unknown_scam),
            "public_label_sources": [{"public_label": p, "count": n}
                                     for p, n in unknown_sources],
        },
        "findings": findings,
    }

    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "label_coverage_audit.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"corpus: {total:,} records\n")
    print(f"{'intent label':<30}{'train':>8}{'val':>7}{'test':>7}  status")
    for r in intent_rows:
        print(f"  {r['label']:<28}{r['train']:>8,}{r['val']:>7,}{r['test']:>7,}  {r['status']}")
    print(f"\n{'behaviour label':<30}{'train':>8}{'val':>7}{'test':>7}  status")
    for r in behavior_rows:
        print(f"  {r['label']:<28}{r['train']:>8,}{r['val']:>7,}{r['test']:>7,}  {r['status']}")

    print("\nindependence:")
    print(f"  intent   reproduces is_scam: {record['independence']['intent_predicts_is_scam_pct']}%")
    print(f"  behaviour reproduces is_scam: {record['independence']['behavior_predicts_is_scam_pct']}%")
    print(f"  benign records with a behaviour flag: {benign_with_behavior}")

    print(f"\nfindings: {len(findings)}")
    for f in findings:
        print(f"  [{f['severity']}] {f['id']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
