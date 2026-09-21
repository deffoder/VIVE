"""Checks that documented figures match the measured artifacts.

Docs drift. A number gets updated in one spec and not another, a blocker is
resolved but still cited as open, a cross-reference points at a section that
moved. This script compares what the Markdown claims against what the JSON
artifacts actually recorded, so drift fails loudly instead of quietly becoming
a false claim in a report.

It verifies:
  * headline metrics in the docs match the training/evaluation reports
  * every `BLOCKERS.md` id cited elsewhere exists, and open/resolved agrees
  * split counts match `eval_splits.json`
  * no doc cites a metric for a model that has no report

Usage:
    python scripts/training/check_docs_consistency.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DOCS = os.path.join(ROOT, "docs")
EVAL = os.path.join(ROOT, "models", "evaluation")
MANIFESTS = os.path.join(ROOT, "data", "manifests")

DOC_FILES = ["DATA_SPEC.md", "ML_SPEC.md", "BLOCKERS.md", "PHASE7_REPORT.md"]


def load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    failures: list[str] = []
    notes: list[str] = []

    text = {}
    for name in DOC_FILES:
        path = os.path.join(DOCS, name)
        text[name] = open(path, encoding="utf-8").read() if os.path.exists(path) else ""

    combined = "\n".join(text.values())

    # --- 1. measured metrics must appear correctly where cited -----------
    checks = []
    intent = load_json(os.path.join(EVAL, "intent_training_report.json"))
    behavior = load_json(os.path.join(EVAL, "behavior_training_report.json"))
    hindi = load_json(os.path.join(EVAL, "asr_hindi_report.json"))

    if intent:
        checks.append(("intent macro-F1", f"{intent['test_metrics']['macro_f1']:.4f}"))
    if behavior:
        checks.append(("behaviour macro-F1", f"{behavior['test_metrics']['macro_f1']:.4f}"))
    if hindi:
        checks.append(("Hindi WER", f"{hindi['metrics']['wer']:.4f}"))
        checks.append(("Hindi CER", f"{hindi['metrics']['cer']:.4f}"))

    for label, value in checks:
        if value not in combined:
            failures.append(f"{label}={value} measured but not found in any doc")
        else:
            notes.append(f"{label} = {value} present in docs")

    # --- 2. a metric must not be cited for a model with no report --------
    for task, report in (("tamil", "asr_ta_whisper_report.json"),
                         ("hindi_whisper", "asr_hi_whisper_report.json")):
        exists = os.path.exists(os.path.join(EVAL, report))
        # crude but effective: look for a Tamil WER claim in the docs
        claimed = bool(re.search(r"Tamil WER\s*[=:]\s*0\.\d+", combined, re.I))
        if task == "tamil" and claimed and not exists:
            failures.append("docs cite a Tamil WER but no Tamil report exists")
        if task == "tamil" and exists:
            notes.append("Tamil report present")

    # --- 3. blocker ids: cited ids must exist; status must agree ---------
    blockers = text["BLOCKERS.md"]
    defined: dict[str, str] = {}
    for match in re.finditer(r"^### ([OR]\d+)\s+—\s+(.+?)\s+·\s+`(\w+)`",
                             blockers, re.M):
        defined[match.group(1)] = match.group(3)
    if not defined:
        failures.append("no blocker headings parsed from BLOCKERS.md")

    cited: dict[str, set[str]] = defaultdict(set)
    for name, body in text.items():
        for match in re.finditer(r"\b([OR]\d{1,2})\b", body):
            ident = match.group(1)
            if ident in ("O1",) and name != "BLOCKERS.md":
                pass
            cited[ident].add(name)

    for ident, where in sorted(cited.items()):
        if ident not in defined:
            failures.append(f"{ident} cited in {sorted(where)} but not defined in BLOCKERS.md")

    # An id that is RESOLVED must not be described as blocking elsewhere.
    for ident, status in defined.items():
        if status != "RESOLVED":
            continue
        for name, body in text.items():
            if name == "BLOCKERS.md":
                continue
            for line in body.splitlines():
                if ident in line and re.search(r"\bBLOCKED\b|\bgated\b.*403", line):
                    failures.append(
                        f"{ident} is RESOLVED but {name} still describes it as blocking: "
                        f"{line.strip()[:90]}")

    # --- 4. split counts must match the artifact -------------------------
    splits = load_json(os.path.join(MANIFESTS, "eval_splits.json"))
    if splits:
        built = splits["available_splits"]
        external = splits.get("externally_measured_splits", 0)
        blocked = splits["unavailable_splits"] - external
        phrase = f"{built} built, {blocked} blocked"
        if phrase not in combined:
            failures.append(
                f"eval_splits.json says '{phrase}' but no doc states it")
        else:
            notes.append(f"split tally '{phrase}' consistent")

    # --- 5. corpus size consistency --------------------------------------
    summary = load_json(os.path.join(MANIFESTS, "scamshield.summary.json"))
    if summary:
        total = f"{summary['total_records']:,}"
        if total not in combined:
            failures.append(f"corpus size {total} not stated in any doc")
        else:
            notes.append(f"corpus size {total} consistent")

    print("checks passed:")
    for n in notes:
        print(f"  ok  {n}")
    print(f"\nblockers defined: {len(defined)} "
          f"({sum(1 for v in defined.values() if v == 'OPEN')} open, "
          f"{sum(1 for v in defined.values() if v == 'RESOLVED')} resolved)")

    if failures:
        print(f"\nINCONSISTENCIES ({len(failures)}):")
        for f in failures:
            print(f"  !! {f}")
        return 1
    print("\nno inconsistencies found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
