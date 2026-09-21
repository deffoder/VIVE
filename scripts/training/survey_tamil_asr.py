"""Surveys Tamil ASR candidates and records license/provenance from the hub.

Phase 7 follow-up (BLOCKERS O8). Requirement: license and provenance must be
documented, and access must be something obtainable legitimately. Every field
here is READ FROM the repository's own metadata and from a real access probe -
none of it is copied from a model card's prose.

A model card that lists Tamil is not evidence of Tamil support. This script
only establishes licence and reachability; actual Tamil inference is verified
separately by `eval_asr_tamil.py`.

Usage:
    python scripts/training/survey_tamil_asr.py
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date

from huggingface_hub import HfApi, hf_hub_download

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

CANDIDATES = [
    ("ai4bharat/indicwav2vec_v1_tamil", "Tamil-specific AI4Bharat wav2vec2"),
    ("ai4bharat/indic-conformer-600m-multilingual", "AI4Bharat multilingual conformer"),
    ("openai/whisper-large-v3-turbo", "Whisper turbo, multilingual encoder-decoder"),
    ("openai/whisper-medium", "Whisper medium, multilingual"),
    ("openai/whisper-small", "Whisper small, multilingual"),
    ("facebook/mms-1b-all", "Meta MMS, 1000+ languages"),
    ("vasista22/whisper-tamil-medium", "Community Tamil fine-tune of Whisper"),
    ("Harveenchadha/vakyansh-wav2vec2-tamil-tam-250", "Vakyansh Tamil wav2vec2"),
]

# Licences that forbid commercial use. VIVE is a product, so these are not
# usable even though the weights download freely.
NON_COMMERCIAL = {"cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0"}


def probe(api: HfApi, repo: str) -> dict:
    entry: dict = {"model_id": repo}
    try:
        info = api.model_info(repo)
    except Exception as exc:
        entry["metadata"] = f"FAIL {type(exc).__name__}"
        entry["usable"] = False
        entry["reason"] = str(exc).splitlines()[0][:160]
        return entry

    card = info.card_data or {}
    license_ = card.get("license")
    files = [s.rfilename for s in info.siblings]

    entry.update({
        "metadata": "OK",
        "license": license_,
        "license_source": "HuggingFace repository metadata",
        "gated": getattr(info, "gated", None),
        "private": info.private,
        "downloads_30d": info.downloads,
        "has_safetensors": any(f.endswith(".safetensors") for f in files),
        "has_pytorch_bin": any(f.endswith(".bin") for f in files),
        "has_onnx": any(f.endswith(".onnx") for f in files),
        "weight_files_visible": sum(
            1 for f in files
            if f.endswith((".safetensors", ".bin", ".onnx", ".pt", ".ckpt"))
        ),
    })

    # Real access probe: can a file actually be fetched, not just listed?
    small = next((f for f in files if f.endswith(".json")), None)
    if small is None:
        entry["file_access"] = "NO_JSON_FILE_TO_PROBE"
    else:
        try:
            # Probe into a temp dir, never into the repository: this is a
            # throwaway reachability check, not an artifact.
            with tempfile.TemporaryDirectory() as probe_dir:
                hf_hub_download(repo_id=repo, filename=small,
                                cache_dir=probe_dir)
            entry["file_access"] = "OK"
        except Exception as exc:
            entry["file_access"] = f"FAIL {type(exc).__name__}"
            entry["file_access_detail"] = str(exc).splitlines()[0][:160]

    blockers = []
    if entry.get("file_access", "").startswith("FAIL"):
        blockers.append("files not downloadable with current access")
    if (license_ or "").lower() in NON_COMMERCIAL:
        blockers.append(f"licence {license_} forbids commercial use")
    if license_ is None:
        blockers.append("no licence declared in repository metadata")
    if entry["weight_files_visible"] == 0:
        blockers.append("no weight files present in the repository")

    entry["usable"] = not blockers
    entry["blockers"] = blockers
    return entry


def main() -> None:
    api = HfApi()
    results = []
    for repo, note in CANDIDATES:
        print(f"probing {repo}")
        entry = probe(api, repo)
        entry["note"] = note
        results.append(entry)
        flag = "USABLE" if entry["usable"] else "; ".join(entry["blockers"])
        print(f"   licence={entry.get('license')}  gated={entry.get('gated')}  "
              f"files={entry.get('file_access')}")
        print(f"   -> {flag}")

    record = {
        "surveyed_at": str(date.today()),
        "purpose": "Tamil ASR option survey for BLOCKERS O8",
        "method": ("Licence and gating read from HuggingFace repository "
                   "metadata; file access confirmed by an actual download "
                   "attempt. Model-card prose was not treated as evidence."),
        "candidates": results,
        "caveat": ("Usable here means licence-clear and downloadable. It does "
                   "NOT mean Tamil inference was verified - that requires a "
                   "real decode, measured separately."),
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    out = os.path.join(EVAL_DIR, "tamil_asr_survey.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    print(f"\n  {sum(1 for r in results if r['usable'])}/{len(results)} usable")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
