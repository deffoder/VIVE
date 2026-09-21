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

## 8.1 Data inventory (verified 2026-09-21)

License and gating status below were read from each repository's own metadata,
not assumed. Sample counts come from the built manifests.

### Acquired and in use

| Field | Value |
|---|---|
| Dataset | `sidzzz07/scamshield-dataset` |
| Source | <https://huggingface.co/datasets/sidzzz07/scamshield-dataset> |
| License | **MIT** — declared as `license:mit` in repository metadata |
| Gated | No |
| Permitted use | Research and commercial, with attribution |
| Language | English 76,246 · Hindi 6,352 · Hinglish 3,004 |
| Task | intent (single-label), behaviour (multi-label) |
| Samples | 85,602 unique after de-duplication (78 duplicates removed) |
| Splits | train 68,412 · val 8,546 · test 8,644 |
| Provenance | Smishing_Dataset 69,343 · UCI_SMS_Spam 5,153 · Kaggle_Hindi_Merged 4,567 · Synthetic_Tier_C 3,720 · Indian_Telecom_SMS 2,032 · Indian_Cyber_Scam_Hinglish 743 · Benchmark_Ground_Truth 44 |
| Preprocessing | Whitespace normalised; content-hashed for de-duplication |

**Known limitations — these bound every claim made from this corpus:**

1. **It is SMS/short-message text, not call transcripts.** Register, length and
   turn-taking all differ from speech. A classifier trained here is a starting
   point for call analysis, not a validated call model.
2. **`OTP_REQUEST` has 103 samples** — roughly 0.1% — despite being the
   highest-value intent in the whole product.
3. **Five of twelve intents have no data at all:** `PASSWORD_REQUEST`,
   `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`, `REMOTE_ACCESS_REQUEST`,
   `CONFIDENTIAL_INFORMATION`. The classifier cannot predict them.
4. **Two of eight behaviours have no label source:** `THREAT` and `SECRECY`.
5. **No Tamil** (`BLOCKERS.md` O8), despite Tamil being a priority language.
6. `Synthetic_Tier_C` (3,720 records) is itself synthetic; it is retained but
   flagged in the `provenance` field so it can be excluded from evaluation.

### Acquired for ASR evaluation

| Field | Value |
|---|---|
| Dataset | `google/fleurs` config `hi_in`, split `test` |
| License | **CC-BY-4.0** — declared in repository metadata |
| Gated | No |
| Content | 418 Hindi utterances, 4832 s of 16 kHz read speech |
| Use | Hindi ASR WER/CER only. Not used for training |
| Result | WER 0.1872 / CER 0.0699 (`PHASE7_REPORT.md` §4.1) |

FLEURS is **clean read speech**: no telephony codec, channel noise,
disfluency or code-switching. It establishes a floor for Hindi ASR, not a
call-channel figure, and no Tamil equivalent was obtained.

### Investigated and rejected or deferred

| Dataset | Status | Reason |
|---|---|---|
| ASVspoof | **NOT ACQUIRED** | Requires registration/agreement that cannot be completed programmatically. AASIST ships a usable pretrained checkpoint, so anti-spoofing works without it — but **no independent EER can be reported**. |
| VoxCeleb | **NOT ACQUIRED** | Requires a request form. ECAPA-TDNN ships pretrained weights, so speaker embedding works without it. |
| Common Voice 17 | **AVAILABLE, not yet used** | Ungated, but no declared license in repository metadata — marked **UNVERIFIED** until the terms are read. Not used for training. |
| IndicSynth, Vaani, ScamShield (original) | **UNVERIFIED** | Not located as openly-licensed downloadable corpora under those names. The HuggingFace `scamshield-dataset` above is a different, MIT-licensed resource. |
| `BothBosu/multi-agent-scam-conversation` | **AVAILABLE, not used** | Apache-2.0, ungated, and conversational rather than SMS — a better register match. Deferred: its label scheme was not mapped in this phase. |

### Pretrained models verified (2026-09-21)

Load-and-run smoke tests only. **No accuracy was measured for any of these.**

| Model | License | Status |
|---|---|---|
| Silero VAD | MIT | **OK** — loads from torch.hub, runs |
| AASIST | MIT | **OK** — checkpoint loads, 229 tensors. Model class not yet vendored, so no forward pass |
| ECAPA-TDNN (SpeechBrain) | Apache-2.0 | **OK** — produces a 192-dim embedding |
| AI4Bharat Indic ASR (`indicwav2vec-hindi`) | Apache-2.0 | **OK** — gate cleared; 1.26 GB snapshot downloads, `Wav2Vec2ForCTC` loads (315.5M params, vocab 68) and runs (`BLOCKERS.md` R7) |

## 9. Test fixtures

`tests/fixtures/` holds short audio for automated tests and demo replay. These
are tracked in git (explicitly un-ignored) and must be small, synthetic or
consented, and free of PII. They back the scenarios in `DEMO_SPEC.md`.
