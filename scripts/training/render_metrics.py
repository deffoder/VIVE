"""Renders the measured training metrics as Markdown.

Every figure is read from `models/evaluation/<task>_training_report.json`, which
is written only by an executed training run. Nothing here is typed by hand, so
a number in the report cannot drift from the number that was measured, and a
metric that was never produced renders as absent rather than as a guess.

Usage:
    python scripts/training/render_metrics.py
    python scripts/training/render_metrics.py --task intent
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "models", "training"))

from vive_labels import BEHAVIOR_LABELS, INTENT_LABELS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

AGGREGATE_ROWS = {"accuracy", "macro avg", "micro avg", "weighted avg", "samples avg"}


def load(task: str) -> dict | None:
    path = os.path.join(EVAL_DIR, f"{task}_training_report.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def render(task: str, record: dict) -> str:
    metrics = record["test_metrics"]
    per_class = metrics.get("per_class", {})
    all_labels = INTENT_LABELS if task == "intent" else BEHAVIOR_LABELS

    lines: list[str] = []
    lines.append(f"### {task}-classifier — measured on the held-out test split")
    lines.append("")
    lines.append(f"- Base model: `{record['base_model']}`")
    lines.append(f"- Test records: {record['data']['test']:,}"
                 f" (train {record['data']['train']:,}, val {record['data']['val']:,})")
    lines.append(f"- Trained: {record['timing']['duration_sec'] // 60} min"
                 f" on {record['environment']['device']},"
                 f" peak VRAM {record['peak_vram_gb']} GB")
    lines.append(f"- Seed: {record['seed']} · torch {record['environment']['torch']}")
    lines.append("")

    headline = [f"**macro-F1 = {metrics['macro_f1']:.4f}**"]
    if "weighted_f1" in metrics:
        headline.append(f"weighted-F1 = {metrics['weighted_f1']:.4f}")
    if "micro_f1" in metrics:
        headline.append(f"micro-F1 = {metrics['micro_f1']:.4f}")
    lines.append(" · ".join(headline))
    lines.append("")
    lines.append("Macro-F1 is the headline because the class distribution is extremely")
    lines.append("skewed; accuracy would be dominated by the majority class.")
    lines.append("")

    # How sklearn's macro average treats a label with no test data differs by
    # task, so the denominator is DETECTED rather than assumed:
    #   single-label -> absent classes are dropped from the average entirely
    #   multi-label  -> every label is a column, so an untrainable label is
    #                   averaged in as a hard 0.0 and drags the figure down
    # Either way the reported number needs its denominator stated, or it will
    # be read as covering the full taxonomy.
    measured = [l for l in all_labels
                if l in per_class and int(per_class[l].get("support", 0)) > 0]
    missing = [l for l in all_labels if l not in measured]
    if missing and measured:
        total = sum(per_class[l]["f1-score"] for l in measured)
        over_measured = total / len(measured)
        over_all = total / len(all_labels)
        reported = metrics["macro_f1"]
        counts_missing = abs(reported - over_all) < abs(reported - over_measured)

        if counts_missing:
            lines.append(
                f"**This macro average is over all {len(all_labels)} labels, including "
                f"{len(missing)} that have no training data and therefore score a hard "
                f"0.000.** Those {len(missing)} cannot be learned from this corpus, so the "
                f"headline understates performance on what was actually trainable: "
                f"across the {len(measured)} labels with data the macro-F1 is "
                f"**{over_measured:.4f}**. Neither figure covers "
                f"{', '.join('`' + m + '`' for m in missing)}."
            )
        else:
            lines.append(
                f"**This macro average is over the {len(measured)} of {len(all_labels)} "
                f"labels that have test data**, not the full taxonomy. The other "
                f"{len(missing)} are excluded entirely rather than scored, so the headline "
                f"says nothing about them; spread over all {len(all_labels)} it would be "
                f"**{over_all:.4f}**. Excluded: "
                f"{', '.join('`' + m + '`' for m in missing)}."
            )
        lines.append("")

    lines.append("| Label | Precision | Recall | F1 | Support |")
    lines.append("|---|---:|---:|---:|---:|")
    for label in all_labels:
        row = per_class.get(label)
        # support == 0 means the label has no ground truth in the test split.
        # sklearn still emits a row when the model *predicted* the class, but
        # precision/recall against zero true instances is not a measurement.
        if row is None or int(row.get("support", 0)) == 0:
            lines.append(f"| `{label}` | — | — | — | **0 — no data, cannot be predicted** |")
            continue
        lines.append(
            f"| `{label}` | {row['precision']:.3f} | {row['recall']:.3f} |"
            f" {row['f1-score']:.3f} | {int(row['support']):,} |"
        )

    unexpected = sorted(set(per_class) - set(all_labels) - AGGREGATE_ROWS)
    if unexpected:
        lines.append("")
        lines.append(f"Unexpected label rows in the report: {unexpected}")

    lines.append("")
    lines.append(f"> {record['caveat']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["intent", "behavior"])
    args = parser.parse_args()

    tasks = [args.task] if args.task else ["intent", "behavior"]
    blocks: list[str] = []
    for task in tasks:
        record = load(task)
        if record is None:
            blocks.append(f"### {task}-classifier\n\n"
                          f"**Not trained.** No report at "
                          f"`models/evaluation/{task}_training_report.json`. "
                          f"No metric may be quoted for this model.")
            continue
        blocks.append(render(task, record))

    print("\n\n---\n\n".join(blocks))


if __name__ == "__main__":
    main()
