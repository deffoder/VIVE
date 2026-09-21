"""Builds VIVE data manifests from the raw corpora.

Manifests are the source of truth for every split (docs/DATA_SPEC.md 3). This
script is the only thing that writes them, so a dataset state is always
reproducible from a commit plus this script.

Leakage safety (DATA_SPEC 5): the scamshield corpus ships a `split_group`
field identifying the originating sub-corpus. Splitting on a hash of the RECORD
TEXT rather than the row index means a duplicated message cannot land in two
splits, which is the realistic leakage risk for an SMS/text corpus.

Usage:
    python scripts/training/build_manifests.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "models", "training"))

from vive_labels import (  # noqa: E402
    BEHAVIOR_UNSUPPORTED,
    map_behaviors,
    map_intent,
    normalise_language,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "data", "raw", "scamshield")
MANIFESTS = os.path.join(ROOT, "data", "manifests")

DATASET_ID = "scamshield"
DATASET_SOURCE = "https://huggingface.co/datasets/sidzzz07/scamshield-dataset"
DATASET_LICENSE = "MIT"
DATASET_LICENSE_STATUS = "VERIFIED"  # license:mit declared in HF repo metadata
DATASET_VERSION = "2026-09-21-snapshot"


def stream_jsonl(path: str):
    """Tolerant JSONL reader - some records contain raw newlines in `text`."""
    decoder = json.JSONDecoder()
    blob = open(path, encoding="utf-8", errors="replace").read()
    index, end = 0, len(blob)
    while index < end:
        while index < end and blob[index] in " \r\n\t":
            index += 1
        if index >= end:
            break
        obj, index = decoder.raw_decode(blob, index)
        yield obj


def content_hash(text: str) -> str:
    """Stable id from normalised content, so duplicates collide by design."""
    normalised = " ".join(text.lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def assign_split(text_hash: str) -> str:
    """Deterministic content-addressed split: 80 / 10 / 10.

    Content-addressed rather than random so a duplicated message always lands
    in the same split, which is what actually prevents train/test leakage here.
    """
    bucket = int(text_hash[:8], 16) % 100
    if bucket < 80:
        return "train"
    return "val" if bucket < 90 else "test"


def build() -> None:
    os.makedirs(MANIFESTS, exist_ok=True)

    records: dict[str, dict] = {}
    duplicates = 0
    source_counts: Counter[str] = Counter()

    for split_file in ("train", "val", "test"):
        path = os.path.join(RAW, f"{split_file}.jsonl")
        if not os.path.exists(path):
            print(f"  missing raw file: {path}", file=sys.stderr)
            continue
        for row in stream_jsonl(path):
            text = (row.get("text") or "").strip()
            if not text:
                continue

            digest = content_hash(text)
            if digest in records:
                duplicates += 1
                continue

            flags = row.get("head1_social_engineering") or {}
            if isinstance(flags, str):
                flags = json.loads(flags.replace("'", '"'))

            public_intent = row.get("head2_scam_intent", "")
            source_counts[row.get("source_dataset", "unknown")] += 1

            records[digest] = {
                "sample_id": f"{DATASET_ID}_{digest[:16]}",
                "dataset_id": DATASET_ID,
                "source": DATASET_SOURCE,
                "dataset_version": DATASET_VERSION,
                "license": DATASET_LICENSE,
                "license_status": DATASET_LICENSE_STATUS,
                "provenance": row.get("source_dataset", "unknown"),
                "split": assign_split(digest),
                "split_group": row.get("split_group", "unknown"),
                "language": normalise_language(row.get("language", "")),
                "language_raw": row.get("language", ""),
                "task": ["intent", "behavior"],
                "text": text,
                "label_intent": map_intent(public_intent),
                "label_intent_public": public_intent,
                "label_behaviors": map_behaviors(flags),
                "is_scam": int(row.get("is_scam", 0)),
                "preprocessing_status": "normalised_whitespace",
                "added_at": str(date.today()),
            }

    rows = list(records.values())

    # --- write per-split manifests ---
    by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for record in rows:
        by_split[record["split"]].append(record)

    for split, items in by_split.items():
        # Full manifest, including message text. Stays LOCAL: it is ~76 MB, and
        # the bodies carry PII-shaped content - phone numbers, URLs, OTP-length
        # digit runs - which docs/SECURITY_SPEC.md 4 keeps out of the repo.
        out = os.path.join(MANIFESTS, f"{DATASET_ID}.{split}.jsonl")
        with open(out, "w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Tracked index: everything needed to verify or rebuild a split, with
        # the body replaced by its hash. Small, and carries no message text.
        # Only per-record varying fields. Constants (source, license, version)
        # live once in the summary rather than 68,412 times, which is the
        # difference between a 47 MB file and a reviewable one.
        index_out = os.path.join(MANIFESTS, f"{DATASET_ID}.{split}.index.jsonl")
        with open(index_out, "w", encoding="utf-8") as handle:
            for item in items:
                entry = {
                    "id": item["sample_id"],
                    "sha": hashlib.sha256(item["text"].encode("utf-8")).hexdigest()[:32],
                    "n": len(item["text"]),
                    "lang": item["language"],
                    "src": item["provenance"],
                    "intent": item["label_intent"],
                    "behaviors": item["label_behaviors"],
                    "scam": item["is_scam"],
                }
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"  wrote {out}  ({len(items):,} records, local only)")
        print(f"  wrote {index_out}  (tracked index, no message text)")

    # --- leakage check: no content hash may appear in two splits ---
    seen: dict[str, str] = {}
    collisions = 0
    for record in rows:
        digest = record["sample_id"]
        if digest in seen and seen[digest] != record["split"]:
            collisions += 1
        seen[digest] = record["split"]

    # --- summary manifest ---
    summary = {
        "dataset_id": DATASET_ID,
        "source": DATASET_SOURCE,
        "version": DATASET_VERSION,
        "license": DATASET_LICENSE,
        "license_status": DATASET_LICENSE_STATUS,
        "built_at": str(date.today()),
        "total_records": len(rows),
        "duplicates_removed": duplicates,
        "cross_split_collisions": collisions,
        "splits": {k: len(v) for k, v in by_split.items()},
        "languages": dict(Counter(r["language"] for r in rows)),
        "intent_distribution": dict(Counter(r["label_intent"] for r in rows)),
        "behavior_distribution": dict(
            Counter(b for r in rows for b in r["label_behaviors"])
        ),
        "provenance_counts": dict(source_counts),
        "behaviors_without_label_source": BEHAVIOR_UNSUPPORTED,
        "known_limitations": [
            "No Tamil records: the corpus covers English, Hindi and Hinglish only.",
            "OTP_REQUEST is severely under-represented despite being the highest-value VIVE intent.",
            "THREAT and SECRECY behaviours have no label source and are not trained.",
            "Corpus is SMS/short-message text, not call transcripts; register differs from speech.",
            "Four public genre labels map to UNKNOWN because they do not determine an intent.",
        ],
    }
    out = os.path.join(MANIFESTS, f"{DATASET_ID}.summary.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    print(f"  wrote {out}")

    print(f"\n  total: {len(rows):,} unique records ({duplicates:,} duplicates removed)")
    print(f"  cross-split collisions: {collisions} (must be 0)")
    print(f"  splits: {summary['splits']}")
    print(f"  languages: {summary['languages']}")
    print("\n  intent distribution:")
    for label, count in sorted(summary["intent_distribution"].items(), key=lambda x: -x[1]):
        print(f"    {count:>7,}  {label}")
    print("\n  behaviour distribution:")
    for label, count in sorted(summary["behavior_distribution"].items(), key=lambda x: -x[1]):
        print(f"    {count:>7,}  {label}")


if __name__ == "__main__":
    build()
