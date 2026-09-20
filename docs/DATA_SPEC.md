# VIVE — Data Specification

> Model IDs and audio parameters follow `ML_SPEC.md`. Taxonomies follow
> `PROJECT_SPEC.md` §7. Handling and retention rules follow `SECURITY_SPEC.md`.

## 1. Layout

```text
data/
├── raw/          source corpora as downloaded — git-ignored
├── processed/    resampled / segmented / feature-ready — git-ignored
├── manifests/    JSONL indexes — tracked in git
└── README.md
```

Audio never enters git. `data/raw/**` and `data/processed/**` are ignored;
manifests and this README are tracked, so the dataset is reproducible from its
index without shipping corpora.

## 2. Audio contract

Canonical working format, matching `ML_SPEC.md` §5:

**16 kHz · mono · `pcm_s16le` · 2.0 s window · 1.0 s stride.**

Anything in `raw/` is converted into this form in `processed/`. Conversion is
scripted (`scripts/setup/`), never manual, so it is reproducible.

## 3. Manifests

One JSONL record per clip. This is the source of truth for every split.

Field shapes only — every value below is a placeholder. No real dataset,
license, speaker or generator identifier is asserted anywhere in this document.

```json
{
  "clip_id": "<dataset>_<source-clip-id>",
  "path": "processed/<task>/<clip_id>.wav",
  "dataset": "<DATASET_NAME>",
  "license": "<SPDX-OR-LICENSE-NAME — verified at download time>",
  "duration_sec": 0.0,
  "sample_rate": 16000,
  "language": "<ISO 639-1>",
  "speaker_id": "<opaque speaker key>",
  "label": { "task": "antispoof", "value": "spoof | bonafide" },
  "generator": "<generator key, anti-spoofing only>",
  "split": "train | val | test",
  "provenance": "<source URL or agreement reference>",
  "added_at": "<YYYY-MM-DD>"
}
```

Required on every record: `clip_id`, `path`, `dataset`, `license`, `label`,
`split`, `provenance`. A clip without a verified license and provenance is not
usable. The `license` field is populated from the dataset's actual terms when it
is obtained — never guessed and never copied from another dataset.

Manifests by task: `antispoof.jsonl`, `speaker.jsonl`, `asr.jsonl`,
`intent.jsonl`, `behavior.jsonl`.

## 4. Candidate sources

Every dataset must be license-checked before download. Nothing is downloaded
during the architecture phase (`ML_SPEC.md` §1).

| Purpose | Candidate | Note |
|---|---|---|
| Anti-spoofing | ASVspoof (LA/DF) | Standard benchmark; check edition terms |
| Anti-spoofing, Indic | IndicSynth | Indic synthetic speech |
| Speaker | VoxCeleb | Verify redistribution terms |
| ASR, Indic | Publicly licensed Hindi/Tamil corpora | Per-corpus license |
| Intent / behaviour | ScamShield, Hinglish/English scam text | Text, not audio |
| Gap-filling | Project-recorded, consented samples | Consent recorded in manifest |

## 5. Splits and leakage

Splits are `train` / `val` / `test`, assigned in the manifest and never at load
time.

Two leakage checks are mandatory before any training run:

- **Speaker leakage** — no `speaker_id` appears in more than one split.
- **Generator leakage** — for anti-spoofing, at least one `generator` is held
  out of `train` entirely, so the test set measures unseen-generator behaviour
  rather than memorisation.

Both checks are scripted under `scripts/training/` and their output is recorded
with the run. A failed check blocks the run.

## 6. Labelling

Intent uses the 12 labels; behaviour uses the 8, multi-label
(`PROJECT_SPEC.md` §7). Behaviour records may carry several labels; `NORMAL` is
exclusive. Label provenance — human, heuristic or model-assisted — is recorded
per record. Model-assisted labels are never treated as ground truth in
evaluation.

## 7. Privacy

Real call audio is never committed, never used for training without recorded
consent, and never leaves the configured storage boundary. Demo and test
fixtures are synthetic or consented. Transcripts are treated as sensitive
(`SECURITY_SPEC.md` §4). PII in text — account numbers, OTP digits, names — is
redacted in manifests and fixtures.

## 8. Versioning

Each manifest carries `dataset_version` and a generation date. Training and
evaluation runs record the manifest version they consumed, so a result can be
traced to an exact dataset state. Manifest changes are commits, not edits in
place.

## 9. Test fixtures

`tests/fixtures/` holds short audio for automated tests and demo replay. These
are tracked in git (explicitly un-ignored) and must be small, synthetic or
consented, and free of PII. They back the scenarios in `DEMO_SPEC.md`.
