"""Writes the VIVE label mapping into a trained checkpoint's config.

Phase 8B. The Phase 7 training runs saved generic `LABEL_0..LABEL_11`, so the
checkpoints did not carry their own label mapping: index-to-label depended
entirely on an external file staying in the same order. A silent reordering
would have produced confident predictions for the WRONG labels.

This makes each checkpoint self-describing. The real adapter
(`backend/app/adapters/real/text_classifiers.py`) then validates the stamped
mapping against the live taxonomy at load time and refuses to load on any
mismatch.

Checkpoints are git-ignored, so this script is what makes the fix reproducible
on another machine rather than a one-off local edit.

Safety: the order is taken from `models/training/vive_labels.py` and is
cross-checked against the order recorded in the training report before
anything is written. If they disagree the script refuses - that disagreement
would mean the true order is unknown, and guessing is exactly the failure this
exists to prevent.

Usage:
    python scripts/training/stamp_label_mapping.py            # both tasks
    python scripts/training/stamp_label_mapping.py --task intent
    python scripts/training/stamp_label_mapping.py --check    # verify only
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "models", "training"))

from vive_labels import BEHAVIOR_LABELS, INTENT_LABELS  # noqa: E402

TASKS = {
    "intent": (INTENT_LABELS, "intent-classifier"),
    "behavior": (BEHAVIOR_LABELS, "behavior-classifier"),
}


def verify_against_report(task: str, labels: list[str]) -> list[str] | None:
    """Returns an error list, or None when the report agrees."""
    path = os.path.join(ROOT, "models", "evaluation", f"{task}_training_report.json")
    if not os.path.exists(path):
        return [f"no training report at {path}; cannot confirm the label order"]
    with open(path, encoding="utf-8") as fh:
        recorded = json.load(fh).get("labels")
    if recorded is None:
        return ["training report records no label order"]
    if list(recorded) != list(labels):
        return [f"training report order differs from vive_labels.py at index {i}: "
                f"report={a!r} taxonomy={b!r}"
                for i, (a, b) in enumerate(zip(recorded, labels)) if a != b]
    return None


def stamp(task: str, *, check_only: bool) -> bool:
    labels, folder = TASKS[task]
    labels = list(labels)
    config_path = os.path.join(ROOT, "models", "artifacts", folder, "config.json")
    if not os.path.exists(config_path):
        print(f"  {task}: no checkpoint at {config_path} - skipped")
        return True

    problems = verify_against_report(task, labels)
    if problems:
        print(f"  {task}: REFUSING to stamp")
        for p in problems[:3]:
            print(f"     {p}")
        return False

    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    head = cfg.get("id2label") or {}
    if len(head) != len(labels):
        print(f"  {task}: REFUSING - checkpoint head has {len(head)} outputs, "
              f"taxonomy has {len(labels)}")
        return False

    current = [head.get(str(i)) for i in range(len(labels))]
    if current == labels:
        print(f"  {task}: already stamped correctly ({len(labels)} labels)")
        return True
    if check_only:
        print(f"  {task}: NOT stamped (found {current[0]!r} at index 0)")
        return False

    cfg["id2label"] = {str(i): l for i, l in enumerate(labels)}
    cfg["label2id"] = {l: i for i, l in enumerate(labels)}
    cfg["vive_label_source"] = "models/training/vive_labels.py"
    cfg["vive_label_verified_against"] = f"models/evaluation/{task}_training_report.json"
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)

    with open(config_path, encoding="utf-8") as fh:
        back = json.load(fh)
    ordered = [back["id2label"][str(i)] for i in range(len(labels))]
    ok = ordered == labels
    print(f"  {task}: stamped {len(labels)} labels, read-back {'OK' if ok else 'FAILED'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(TASKS))
    parser.add_argument("--check", action="store_true",
                        help="verify without writing; non-zero exit if unstamped")
    args = parser.parse_args()

    tasks = [args.task] if args.task else sorted(TASKS)
    print("verifying" if args.check else "stamping", "label mappings\n")
    ok = all(stamp(t, check_only=args.check) for t in tasks)
    print("\n" + ("all good" if ok else "FAILED - see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
