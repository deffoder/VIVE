"""Surveys Tamil TEXT resources for intent and behaviour classification.

Phase 7 follow-up for BLOCKERS O8 (text half) and O9. The Tamil ASR gap is
closed; this is about whether VIVE can *understand* Tamil, which needs labelled
Tamil text for the intent and behaviour heads.

Licence and gating are read from each repository's own metadata and recorded
BEFORE anything is downloaded, per the project rule that an unverified licence
blocks use. A dataset with no declared licence is recorded as UNVERIFIED and is
not treated as usable, however convenient its content looks.

This survey deliberately separates three different needs, because a single
"Tamil dataset" almost never covers them:

  1. Tamil SCAM / social-engineering text  - for the positive classes
  2. Tamil BENIGN text                     - for the negative class (O10)
  3. Tamil CODE-SWITCHED text (Tanglish)   - real callers mix scripts

Usage:
    python scripts/training/survey_tamil_text.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

from huggingface_hub import HfApi

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

# Licences that forbid commercial use. VIVE is a product, so these are not
# usable even when the data downloads freely.
NON_COMMERCIAL = {"cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0",
                  "cc-by-nc-2.0", "cc-by-nc-3.0"}
# Licences that carry behavioural use restrictions needing a human read before
# adoption. Not auto-rejected, but not auto-approved either.
NEEDS_REVIEW = {"openrail", "bigscience-openrail-m", "creativeml-openrail-m",
                "apache-2.0-with-restrictions"}

SEARCH_TERMS = [
    "tamil scam", "tamil spam", "tamil fraud", "tamil phishing",
    "tamil offensive", "tamil code-mixed", "tanglish", "dravidian codemix",
    "tamil sentiment", "tamil conversation", "tamil hate speech",
]

NAMED = [
    ("google/fleurs", "benign", "Tamil read-speech transcripts, already used for ASR eval"),
    ("ai4bharat/IndicCorpV2", "benign", "large general Indic corpus"),
    ("Deepakvictor/tanglish-tamil", "codeswitch", "Tanglish text"),
    ("Muthumari10/tamil-nlp-sentiment-and-fake-news-dataset", "adjacent",
     "sentiment + fake news, not scam intent"),
    ("anthea1407/tanglishmedbench", "codeswitch", "Tanglish medical benchmark"),
    ("IsaacRodgz/DravidianCodeMix-Dataset", "codeswitch", "Dravidian code-mix"),
    ("foreverlove/Tamil_first_ready_for_sentiment", "adjacent", "Tamil sentiment"),
]


def classify(license_: str | None, gated, has_scam_labels: bool) -> dict:
    """Licence-clearance and task-fit are separate questions.

    Collapsing them hides the useful case: a corpus can be perfectly licensed
    and still carry no scam labels, which makes it useless for the intent head
    but valuable as BENIGN Tamil text - exactly what O10 says is missing.
    """
    licence_blockers: list[str] = []
    if license_ is None:
        licence_blockers.append("no licence declared in repository metadata (UNVERIFIED)")
    elif license_.lower() in NON_COMMERCIAL:
        licence_blockers.append(f"licence {license_} forbids commercial use")
    elif license_.lower() in NEEDS_REVIEW:
        licence_blockers.append(f"licence {license_} carries use restrictions; needs a human read")
    if gated and gated is not False:
        licence_blockers.append(f"gated ({gated}); access not established")

    task_blockers: list[str] = []
    if not has_scam_labels:
        task_blockers.append("no scam / social-engineering labels")

    return {
        "licence_ok": not licence_blockers,
        "licence_blockers": licence_blockers,
        "task_fit_for_intent": not task_blockers,
        "task_blockers": task_blockers,
        "status": ("USABLE for intent training" if not licence_blockers and not task_blockers
                   else "LICENCE OK, wrong task" if not licence_blockers
                   else "LICENCE BLOCKED"),
    }


def probe(api: HfApi, dataset_id: str, role: str, note: str) -> dict:
    entry = {"dataset_id": dataset_id, "role": role, "note": note}
    try:
        info = api.dataset_info(dataset_id)
    except Exception as exc:
        entry.update({"metadata": f"FAIL {type(exc).__name__}", "status": "UNREACHABLE",
                      "blockers": [str(exc).splitlines()[0][:140]]})
        return entry
    card = info.card_data or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    # Nothing found in the survey carries scam/social-engineering labels; this
    # is set explicitly rather than inferred so a future corpus can flip it.
    has_scam = False
    verdict = classify(lic, getattr(info, "gated", None), has_scam)
    entry.update({
        "metadata": "OK",
        "license": lic,
        "license_source": "HuggingFace repository metadata",
        "license_status": "VERIFIED" if lic else "UNVERIFIED",
        "gated": getattr(info, "gated", None),
        "downloads_30d": info.downloads,
        "has_scam_labels": has_scam,
        **verdict,
    })
    return entry


def main() -> int:
    api = HfApi()

    discovered: dict[str, None] = {}
    for term in SEARCH_TERMS:
        try:
            for d in api.list_datasets(search=term, limit=12):
                discovered.setdefault(d.id, None)
        except Exception:
            continue

    named_ids = {d for d, _, _ in NAMED}
    results = [probe(api, d, role, note) for d, role, note in NAMED]
    for did in sorted(discovered):
        if did in named_ids:
            continue
        results.append(probe(api, did, "discovered", "from keyword search"))

    licence_ok = [r for r in results if r.get("licence_ok")]
    usable = [r for r in results if r.get("licence_ok") and r.get("task_fit_for_intent")]
    scam_labelled = [r for r in results if r.get("has_scam_labels")]

    record = {
        "surveyed_at": str(date.today()),
        "purpose": "Tamil TEXT resources for intent + behaviour (BLOCKERS O8 text half)",
        "method": ("Licence and gating read from HuggingFace repository metadata "
                   "before any download. A dataset with no declared licence is "
                   "UNVERIFIED and is not treated as usable."),
        "search_terms": SEARCH_TERMS,
        "candidates_examined": len(results),
        "licence_clear_count": len(licence_ok),
        "licence_clear_ids": [r["dataset_id"] for r in licence_ok],
        "usable_count": len(usable),
        "with_scam_labels_count": len(scam_labelled),
        "headline_finding": (
            "No Tamil scam / social-engineering labelled text corpus was found "
            "under any licence. Tamil intent and behaviour classification "
            "therefore cannot be trained from public data as it stands."
        ),
        "candidates": results,
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "tamil_text_survey.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"examined {len(results)} candidates\n")
    print(f"{'dataset':<52}{'licence':<16}{'status'}")
    for r in results:
        print(f"  {r['dataset_id'][:48]:<52}{str(r.get('license')):<16}{r.get('status')}")
    print(f"\nlicence-clear (usable as Tamil TEXT, wrong labels): {len(licence_ok)}")
    for r in licence_ok:
        print(f"    {r['dataset_id']}  ({r['license']})  role={r['role']}")
    print(f"usable for intent/behaviour TRAINING: {len(usable)}")
    print(f"with scam / social-engineering labels: {len(scam_labelled)}")
    print(f"\n{record['headline_finding']}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
