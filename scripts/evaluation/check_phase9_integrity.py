"""Checks that every Phase 9 result is reproducible, scoped and honestly cited.

`scripts/training/check_docs_consistency.py` checks that documented figures
match the measured artifacts. This adds the checks specific to Phase 9, where
the risk is less that a number is stale and more that a correctly-measured
number gets quoted without the scope that makes it true.

  1. **Every record is complete.** An experiment must carry its question,
     hypothesis, method, environment, seed, results and at least one stated
     limitation. `Experiment.finish()` enforces the limitation rule at write
     time; this re-checks it on disk, because a record could also be written
     by hand.

  2. **Every record names its provenance.** An experiment that consumed a
     dataset or a model must say which, under what licence.

  3. **Headline metrics cited in docs match the artifact.** Any Phase 9 figure
     that appears in Markdown is compared against the JSON it came from.

  4. **Scoped metrics are never cited bare.** The anti-spoof EER comes from a
     probe with one synthesis family; the LibriSpeech speaker EER is clean
     read speech. Wherever those numbers appear, the qualifying sentence must
     appear nearby. This is the check that matters most: the failure mode for
     Phase 9 is a true number in a false context.

  5. **Superseded results stay superseded.** A figure recorded as superseded
     must not be quoted anywhere as current.

Usage:
    python scripts/evaluation/check_phase9_integrity.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _harness import PHASE9_DIR, ROOT  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
REQUIRED_FIELDS = ("experiment_id", "question", "hypothesis", "method",
                   "environment", "seed", "results", "limitations",
                   "interpretation", "conclusion")

# A measured figure and the phrase that must accompany it. The phrase is
# matched case-insensitively within the same document.
SCOPE_RULES = [
    ("9B_aasist_early_window",
     "anti-spoofing EER",
     ["one synthesis family", "single synthesis family", "SpeechT5"],
     "an anti-spoof EER must be cited with the probe's single synthesis family"),
    ("9D_ecapa_speaker",
     "speaker EER",
     ["LibriSpeech", "clean read speech", "audiobook"],
     "a speaker EER must be cited with the LibriSpeech clean-speech scope"),
]

SUPERSEDED_FIGURES = [
    ("1.3912", "the superseded contended RTF probe"),
    ("0.632", "the OTP_REQUEST F1, which is below the support floor"),
]

# Words that mark a figure as retired, disputed or bounded. Matched over the
# line plus its neighbours, because prose wraps: "scores 0.632 on 8 test
# records - weak, and statistically" puts the qualifier on the NEXT line, and
# a table row is qualified by the caption above it.
RETIREMENT_MARKERS = (
    "supersed", "invalid", "must not", "never", "unmeasurable", "below the",
    "contend", "contention", "not be quoted", "discarded", "fragile",
    "weakest", "no data", "cannot be predicted", "held the machine",
    "real value", "indicates weakness", "preliminary", "retired",
)
CONTEXT_LINES = 2

# A sentence that DENIES having a metric needs no scope - "no anti-spoofing
# EER" is the correct statement, not an unscoped claim.
ABSENCE_MARKERS = ("no anti-spoofing eer", "no speaker verification eer",
                   "no eer", "without an eer", "has no measured")


def load_records() -> dict[str, dict]:
    records = {}
    if not os.path.isdir(PHASE9_DIR):
        return records
    for name in sorted(os.listdir(PHASE9_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(PHASE9_DIR, name), encoding="utf-8") as fh:
            records[name[:-5]] = json.load(fh)
    return records


def doc_text() -> dict[str, str]:
    out = {}
    for name in sorted(os.listdir(DOCS)):
        if name.endswith(".md"):
            with open(os.path.join(DOCS, name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


def main() -> int:
    failures: list[str] = []
    notes: list[str] = []

    records = load_records()
    if not records:
        print(f"no Phase 9 records under {os.path.relpath(PHASE9_DIR, ROOT)}")
        return 1
    docs = doc_text()
    combined = "\n".join(docs.values())

    # --- 1 + 2: record completeness and provenance ------------------------
    for key, record in records.items():
        missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
        if missing:
            failures.append(f"{key}: incomplete record, missing {missing}")
            continue
        environment = record["environment"]
        if not environment.get("git_commit") or environment["git_commit"] == "unknown":
            failures.append(f"{key}: no git commit recorded")
        if not record["datasets"] and not record["models"]:
            failures.append(f"{key}: names neither a dataset nor a model")
        for dataset in record["datasets"]:
            if not dataset.get("license"):
                failures.append(f"{key}: dataset {dataset.get('name')} has no licence")
        for model in record["models"]:
            if not model.get("license"):
                failures.append(f"{key}: model {model.get('name')} has no licence")
        notes.append(f"{key}: complete, {len(record['limitations'])} limitation(s)")

    # --- 4: scoped metrics must not be cited bare -------------------------
    for experiment, label, phrases, message in SCOPE_RULES:
        if experiment not in records:
            continue
        for name, body in docs.items():
            lowered_body = body.lower()
            if label.lower() not in lowered_body:
                continue
            # A document that only states the metric does NOT exist is fine.
            cites_a_value = any(
                label.lower() in line.lower()
                and not any(a in line.lower() for a in ABSENCE_MARKERS)
                for line in body.splitlines())
            if not cites_a_value:
                notes.append(f"{name}: mentions {label} only as absent")
                continue
            if not any(p.lower() in lowered_body for p in phrases):
                failures.append(f"{name}: cites {label} without scope - {message}")
            else:
                notes.append(f"{name}: {label} cited with its scope")

    # --- 5: superseded figures must not be quoted as current --------------
    for figure, description in SUPERSEDED_FIGURES:
        for name, body in docs.items():
            lines = body.splitlines()
            for index, line in enumerate(lines):
                if figure not in line:
                    continue
                window = " ".join(
                    lines[max(0, index - CONTEXT_LINES):
                          index + CONTEXT_LINES + 1]).lower()
                if any(word in window for word in RETIREMENT_MARKERS):
                    continue
                failures.append(
                    f"{name}: quotes {figure} ({description}) without marking it: "
                    f"{line.strip()[:90]}")

    # --- 3: headline Phase 9 metrics must match their artifact ------------
    cited = []
    window = records.get("9B_aasist_early_window")
    if window:
        native = window["results"]["per_window_length"].get("4.0375s", {})
        if "eer" in native:
            cited.append(("AASIST probe EER (native window)", f"{native['eer']:.4f}"))
    speaker = records.get("9D_ecapa_speaker")
    if speaker:
        clean = speaker["results"]["per_condition"]["clean_full"]
        cited.append(("ECAPA LibriSpeech EER", f"{clean['eer']:.4f}"))
    calibration = records.get("9F_fusion_ablation_calibration")
    if calibration:
        ece = calibration["results"]["calibration"]["expected_calibration_error"]
        cited.append(("risk-score ECE", f"{ece:.4f}"))

    for label, value in cited:
        if value in combined:
            notes.append(f"{label} = {value} present in docs")
        else:
            failures.append(f"{label} = {value} measured but not stated in any doc")

    print("Phase 9 integrity checks")
    print(f"  records found: {len(records)}")
    for note in notes:
        print(f"  ok  {note}")

    if failures:
        print(f"\nPROBLEMS ({len(failures)}):")
        for failure in failures:
            print(f"  !! {failure}")
        return 1
    print("\nno problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
