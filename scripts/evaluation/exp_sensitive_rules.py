"""How well do the sensitive-request rules work, on data they were not written from?

Positives: scamshield TEST rows whose gold intent is a sensitive request
(OTP_REQUEST, BANKING_CREDENTIAL_REQUEST, MONEY_TRANSFER_REQUEST). These are
SMS, not speech, and the rules were not tuned on them.
Negatives:
  * scamshield TEST NORMAL_CONVERSATION rows - includes genuine bank SMS
    ("your OTP is ..., do not share"), the hardest benign case;
  * FLEURS test transcripts in hi, ta and en - benign read speech, the closest
    thing to benign spoken text available, and the only Tamil check.

Reports firing rates per group and per rule, with examples of false
positives so they can be read, not just counted.

Output: models/evaluation/mobile/sensitive_rules_eval.json

Usage (models venv; needs `datasets`):
    VIVE_DATA_DIR=<main checkout>/data python scripts/evaluation/exp_sensitive_rules.py
"""

from __future__ import annotations

import collections
import io
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app.risk.sensitive import detect  # noqa: E402

DATA = os.environ.get("VIVE_DATA_DIR") or os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "models", "evaluation", "mobile", "sensitive_rules_eval.json")
SENSITIVE = {"OTP_REQUEST", "BANKING_CREDENTIAL_REQUEST", "MONEY_TRANSFER_REQUEST"}


def fleurs(config: str, n: int) -> list[str]:
    from datasets import Audio, load_dataset
    ds = load_dataset("google/fleurs", config, split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    out = []
    for row in ds:
        out.append(row.get("transcription") or row.get("raw_transcription") or "")
        if len(out) >= n:
            break
    return out


def rate(texts: list[str]) -> dict:
    hits = [(t, detect(t)) for t in texts]
    fired = [(t, d) for t, d in hits if d]
    return {"n": len(texts), "fired": len(fired), "rate": round(len(fired) / max(1, len(texts)), 4),
            "by_rule": dict(collections.Counter(d.label for _, d in fired)),
            "examples": [{"text": t[:160], "rule": d.label, "secret": d.secret, "request": d.request}
                         for t, d in fired[:8]]}


def main() -> int:
    rows = [json.loads(l) for l in io.open(os.path.join(DATA, "manifests", "scamshield.test.jsonl"),
                                           encoding="utf-8") if l.strip()]
    report = {"rules": "models/configs/sensitive_requests.json", "groups": {}}
    for label in sorted(SENSITIVE):
        report["groups"][f"positive/{label}"] = rate([r["text"] for r in rows if r["label_intent"] == label])
    pos = [r["text"] for r in rows if r["label_intent"] in SENSITIVE]
    report["groups"]["positive/all_sensitive"] = rate(pos)
    for lang in ("en", "hi", "hi-en"):
        report["groups"][f"negative/scamshield_normal_{lang}"] = rate(
            [r["text"] for r in rows if r["label_intent"] == "NORMAL_CONVERSATION" and r["language"] == lang])
    report["groups"]["negative/scamshield_unknown_benign"] = rate(
        [r["text"] for r in rows if r["label_intent"] == "UNKNOWN" and not r["is_scam"]])
    for cfg, lang in (("hi_in", "hi"), ("ta_in", "ta"), ("en_us", "en")):
        report["groups"][f"negative/fleurs_{lang}"] = rate(fleurs(cfg, 400))
    for k, v in report["groups"].items():
        print(f"{k:45s} {v['fired']:5d}/{v['n']:<5d} {v['rate']:.4f} {v['by_rule']}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
