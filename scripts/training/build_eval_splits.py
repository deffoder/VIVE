"""Builds the Phase 7 evaluation splits.

Step 10. Each split isolates one condition so a later evaluation can say which
condition a failure came from, rather than reporting one undifferentiated
number.

**Splits that cannot be populated are emitted with `available: false` and a
reason.** They are not silently dropped, and they are not filled with
substitutes - an empty Tamil split is information, a faked one is a lie.

Usage:
    python scripts/training/build_eval_splits.py
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFESTS = os.path.join(ROOT, "data", "manifests")
OUT_DIR = os.path.join(MANIFESTS, "eval")

# Below this, a split cannot support a metric anyone should read. A split
# with a handful of records is reported as BLOCKED rather than BUILT: a
# per-class F1 over 1 record is noise wearing the costume of a measurement.
MIN_EVAL_RECORDS = 30


def load(split: str) -> list[dict]:
    path = os.path.join(MANIFESTS, f"scamshield.{split}.jsonl")
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write(name: str, rows: list[dict], description: str, caveat: str = "") -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "name": name,
        "available": True,
        "count": len(rows),
        "path": os.path.relpath(path, ROOT).replace("\\", "/"),
        "description": description,
        "caveat": caveat,
    }


def unavailable(name: str, description: str, reason: str, blocker: str = "") -> dict:
    return {
        "name": name,
        "available": False,
        "count": 0,
        "description": description,
        "reason": reason,
        "blocker": blocker,
    }


def build_or_block(name: str, rows: list[dict], description: str,
                   caveat: str = "", blocker: str = "") -> dict:
    """Writes a split, or records it as blocked when it is too small to measure."""
    if len(rows) >= MIN_EVAL_RECORDS:
        return write(name, rows, description, caveat)
    return unavailable(
        name, description,
        f"Only {len(rows)} held-out record(s) - below the {MIN_EVAL_RECORDS}-record "
        f"minimum for a meaningful metric. Reported as blocked rather than built.",
        blocker,
    )


def main() -> None:
    test = load("test")
    splits: list[dict] = []

    # 1. Standard held-out test - the natural distribution, unmodified.
    splits.append(write(
        "standard_heldout", test,
        "Full held-out test split with its natural class distribution.",
        "Class imbalance is extreme; macro-F1 is the honest headline, not accuracy.",
    ))

    # 2. Per-language splits.
    for code, label in (("en", "english"), ("hi", "hindi"), ("hi-en", "hinglish")):
        rows = [r for r in test if r["language"] == code]
        splits.append(build_or_block(
            f"language_{label}", rows,
            f"Held-out records in {label}.",
            "Small sample; per-class figures will be unstable." if len(rows) < 1000 else "",
        ))

    # 3. Tamil - a priority language with no data at all.
    splits.append(unavailable(
        "language_tamil",
        "Held-out Tamil records.",
        "The corpus contains no Tamil. Tamil intent/behaviour classification is "
        "not supported and must not be described as supported.",
        "O8",
    ))

    # 4. Social-engineering split: records carrying at least one behaviour.
    social = [r for r in test if r["label_behaviors"] != ["NORMAL"]]
    splits.append(write(
        "social_engineering", social,
        "Records exhibiting at least one social-engineering behaviour.",
    ))

    # 5. Human-scam split: scam records WITHOUT synthetic provenance. This is
    #    the scenario that matters most - a genuine human running a scam.
    human_scam = [
        r for r in test
        if r["is_scam"] == 1 and r["provenance"] != "Synthetic_Tier_C"
    ]
    splits.append(write(
        "human_scam", human_scam,
        "Scam records from real-world corpora, excluding synthetically generated ones.",
        "Tests whether risk is driven by semantics rather than by generation artefacts.",
    ))

    # 6. Synthetic-but-legitimate: the corpus has no such records. Fabricating
    #    them would defeat the purpose of the split.
    splits.append(unavailable(
        "synthetic_but_legitimate",
        "Machine-generated but legitimate messages, to test that synthetic "
        "origin alone does not raise risk.",
        "No corpus record is labelled both synthetic-origin and legitimate. "
        "Synthetic_Tier_C records are synthetic AND scam, so they cannot "
        "separate the two factors.",
    ))

    # 7. Benchmark subset: the small human-curated ground-truth slice.
    benchmark = [r for r in test if r["provenance"] == "Benchmark_Ground_Truth"]
    splits.append(build_or_block(
        "benchmark_ground_truth", benchmark,
        "Human-curated benchmark records.",
        "Small; indicative only.",
    ))

    # --- audio-domain splits: none can be built in this phase ---
    for name, description, reason, blocker in [
        ("generator_disjoint",
         "Anti-spoofing evaluation where test-set generators are unseen in training.",
         "No anti-spoofing corpus was acquired. ASVspoof requires registration, "
         "and AASIST is used as a pretrained checkpoint without independent "
         "evaluation. No EER can be reported.", "O5"),
        ("codec_noise_robustness",
         "Codec, bandwidth and noise degradation robustness.",
         "Requires an audio corpus. The text classifiers cannot be evaluated "
         "for acoustic robustness.", ""),
        ("speaker_disjoint",
         "Speaker verification with speakers unseen in training.",
         "No speaker corpus was acquired; VoxCeleb requires a request form. "
         "ECAPA-TDNN is used pretrained, and there is no enrolment source "
         "anyway.", "O3"),
        ("asr_hindi", "Hindi ASR word-error-rate evaluation.",
         "No real ASR model is loadable: the AI4Bharat repositories are gated "
         "and return 403 on download.", "O7"),
        ("asr_tamil", "Tamil ASR word-error-rate evaluation.",
         "Blocked by both the gated ASR model and the absence of Tamil data.",
         "O7, O8"),
    ]:
        splits.append(unavailable(name, description, reason, blocker))

    summary = {
        "built_at": str(date.today()),
        "source_manifest": "scamshield.test.jsonl",
        "source_records": len(test),
        "available_splits": sum(1 for s in splits if s["available"]),
        "unavailable_splits": sum(1 for s in splits if not s["available"]),
        "splits": splits,
        "note": (
            "Unavailable splits are recorded rather than dropped. An evaluation "
            "that omits them must say so; none may be reported as passed."
        ),
    }
    out = os.path.join(MANIFESTS, "eval_splits.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    print(f"  source: {len(test):,} held-out records\n")
    for split in splits:
        if split["available"]:
            print(f"  [BUILT]   {split['name']:<28} {split['count']:>6,} records")
        else:
            tag = f" ({split['blocker']})" if split.get("blocker") else ""
            print(f"  [BLOCKED] {split['name']:<28} {split['reason'][:60]}{tag}")
    print(f"\n  {summary['available_splits']} built, "
          f"{summary['unavailable_splits']} blocked")
    print(f"  wrote {out}")

    languages = Counter(r["language"] for r in test)
    print(f"  held-out languages: {dict(languages)}")


if __name__ == "__main__":
    main()
