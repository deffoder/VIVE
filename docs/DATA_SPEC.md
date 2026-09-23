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
| ASVspoof | **ACQUIRED 2026-09-23** | LA **evaluation** partition via `SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA`, ODC-By 1.0, ungated, `LICENSE.txt` read before download. The earlier note that this required an uncompletable registration was an assumption about the canonical channel and was wrong. Used for the Phase J in-domain measurement (O12); not committed, cached under git-ignored `models/artifacts/`. |
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
| **`indic-conformer-600m-multilingual`** | **MIT** | **SELECTED ASR** (`ML_SPEC.md` §2.1). Gated, terms accepted; CTC subset downloads (2.50 GB) and runs. Hindi WER 0.1164, Tamil WER 0.2833 |
| `indicwav2vec-hindi` | Apache-2.0 | **Evaluated, not selected.** Gate cleared; `.bin` audited and converted to safetensors (`BLOCKERS.md` R7). Hindi-only, WER 0.1872 |
| `whisper-large-v3-turbo` | MIT | **Evaluated, rejected.** Ungated. Worse at both languages, 5.5x over the per-window budget |

## 8.2 Data-gap remediation plan (O9, O10)

Derived from `scripts/training/audit_label_coverage.py`, whose output is
`models/evaluation/label_coverage_audit.json`. Every figure below is measured,
not estimated.

### What is actually wrong

| Gap | Measured | Effect |
|---|---|---|
| 5 intents with no data | `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`, `REMOTE_ACCESS_REQUEST`, `CONFIDENTIAL_INFORMATION` all 0 | Cannot be predicted at all |
| 2 behaviours with no data | `THREAT`, `SECRECY` all 0 | Cannot be predicted at all |
| `OTP_REQUEST` under-supported | 80 train / 15 val / **8 test** | Below the 30-record floor: **unmeasurable**, not merely weak |
| Intent collinear with `is_scam` | **100.0000%** | The intent head is a scam detector with sub-classes |
| No benign behaviour examples | **0** of 85,602 | Behaviour head has never seen legitimate urgency |

The last two are the serious ones, and they are not fixed by adding more of
the same data. They are properties of the corpus design.

### Why collinearity matters for risk fusion

`app/risk/fusion.py` combines intent and behaviour with a noisy-OR, which
assumes the inputs carry **independent** evidence. In this corpus they do not:
both are derived from the same underlying `is_scam` flag. Two signals that are
really one signal, combined as if independent, inflate the fused score and its
confidence. Fusion weights stay provisional (`BLOCKERS.md` O6) until they are
calibrated against data where intent and behaviour can disagree.

### Remediation, in priority order

**1. Acquire benign-with-behaviour examples (highest value, unblocks O10).**
`BothBosu/multi-agent-scam-conversation` — Apache-2.0, ungated, verified by
inspection: 1,280 dialogues, balanced 640 benign / 640 scam, in **call
register** rather than SMS. Its benign scenarios (`appointment`, `delivery`,
`insurance`, `wrong` number) are legitimate calls that use authority and
urgency framing, which is exactly the negative evidence the behaviour head
lacks.

**2. Fill two missing intents from the same source.** Inspection of the
dialogue text confirms `ssn` scenarios are Social-Security impersonation
(`CONFIDENTIAL_INFORMATION`) and `support` scenarios are tech-support intrusion
(`REMOTE_ACCESS_REQUEST`). Mapping must be verified per dialogue, not assumed
from the scenario name.

**3. `OTP_REQUEST` needs targeted collection, not augmentation.** 8 test
records cannot support a metric however the training set grows. SMS contains
OTP codes being *delivered*; VIVE needs a caller *soliciting* one, which is a
different speech act. This requires either scripted collection or a
conversational corpus, and until then `OTP_REQUEST` performance is
**unmeasurable and must not be quoted**.

**4. Still unsourced:** `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`,
`ACCOUNT_CHANGE_REQUEST`, `THREAT`, `SECRECY`. No openly-licensed corpus has
been identified. These stay unsupported and must not be described otherwise.

### Constraints on any of the above

The conversational corpus is **English-only** in the sampled rows, so it does
nothing for Hindi or Tamil coverage. It is also **LLM-generated**, so it is
suitable for teaching label boundaries but cannot support a real-world
accuracy claim, and any model trained with it must record that provenance.

Adding it is a **Phase 8+ decision**, not a Phase 7 action: it changes the
training distribution, so it would invalidate the measured Phase 7 figures and
require a re-run and re-evaluation.

## 8.3 Tamil data-gap remediation plan (O8 text half, O11)

Audited 2026-09-21. Every figure here is measured or read from repository
metadata; nothing is projected.

### What the audit established

| Check | Result |
|---|---|
| Tamil records in the training corpus | **0 of 85,602** |
| Tamil codepoints (U+0B80-U+0BFF) anywhere in the corpus | **0** |
| Romanised Tamil (Tanglish) markers | 37 candidate hits, **all false positives** ("b**unga**low", "chah**unga**") |
| Tamil scam / social-engineering labelled corpora found | **0 under any licence** |
| Tamil text corpora examined | 19 |
| Licence-clear but wrong task | 5 |

Tamil is absent **by script, not by labelling**, so no relabelling or
re-parsing of the existing corpus can recover it. The gap is real data.

Survey artifact: `models/evaluation/tamil_text_survey.json`.

### Why nothing found is directly usable

| Dataset | Licence | Why not |
|---|---|---|
| `google/fleurs` (ta_in) | CC-BY-4.0 | Licence clear. Read speech, **benign only**, no scam labels |
| `Muthumari10/tamil-nlp-sentiment-and-fake-news` | CC-BY-4.0 | Sentiment / fake news, not caller intent |
| `krishan-CSE/Tamil_Hate_Speech` | Apache-2.0 | Hate speech overlaps `THREAT` framing but is not social engineering |
| `foreverlove/Tamil_first_ready_for_sentiment` | MIT | Sentiment only |
| `anthea1407/tanglishmedbench` | **CC-BY-NC-4.0** | Non-commercial; **rejected** |
| `Deepakvictor/tanglish-tamil` | **openrail** | Use restrictions; needs a human licence read before adoption |
| 11 other Tanglish sets | **none declared** | **UNVERIFIED**; not usable regardless of content |

### The plan

Because no Tamil scam corpus exists, Tamil data must be **created**. The plan
below is deliberately conservative about what such data can support.

**1. Tamil intent classification.** Source in priority order:
(a) **human-authored** Tamil scam scripts written against the 12-label intent
taxonomy by a Tamil speaker, owned by the project so provenance and licence are
unambiguous; (b) **translated** English/Hindi scam text, marked
`provenance=translated`; (c) **LLM-generated** Tamil, marked
`provenance=synthetic`. Tiers (b) and (c) are training-only - see leakage rules.

**2. Tamil behaviour classification.** The 8 behaviour labels are annotated on
the same records as intent, not collected separately, so a record can carry
both. `THREAT` and `SECRECY` have **no source in any language**
(`BLOCKERS.md` O9), so Tamil cannot fix them; they stay untrained.

**3. Tamil benign / negative examples.** This is the part that can start now
with clean licensing. `google/fleurs` `ta_in` is **CC-BY-4.0** and already
downloaded for ASR evaluation; its **591 held-out transcripts** (plus larger
train/validation splits) are real Tamil sentences carrying no scam intent.

They are **read news-style sentences, not conversational**, so they are a
partial fix: they teach the model what ordinary Tamil looks like, but not what
a *legitimate Tamil phone call* looks like. Benign Tamil records that carry
social-engineering behaviours - a real delivery notice using urgency - remain
missing, which is the Tamil instance of **O10**.

**4. Code-switching / Tanglish.** Real Tamil callers mix Tamil script, romanised
Tamil and English in one utterance. A Tamil-script-only dataset would not
represent them, and the ASR output itself is Tamil script, so the text model
must handle both. Requirements: every collected record carries a measured
`script_ratio` (share of letters in Tamil script); the corpus must span the
range, not cluster at 1.0; and `language` takes a distinct value `ta-en`,
mirroring the existing `hi-en`.

**5. Train / validation / test separation.** Reuse the existing mechanism:
content-addressed splits from a hash of the normalised text
(`scripts/training/build_manifests.py`), 80/10/10, so a duplicate always lands
in the same split. Tamil records enter the same manifest pipeline; no separate
splitting logic.

**6. Provenance and licence verification.** No dataset is downloaded before its
licence is recorded. Each record carries `license`, `license_status`
(`VERIFIED`/`UNVERIFIED`), `source`, `provenance` and `dataset_version`, as the
manifest schema already requires. A corpus with no declared licence is
**UNVERIFIED** and is not used, regardless of how well it fits.

**7. Preventing synthetic and translation leakage.** Three rules, because the
existing content-hash de-duplication does **not** catch either case - a
translation and its source have different text and therefore different hashes:

- Every record carries `provenance` in `{human, translated, synthetic}`.
- **The test split contains `human` records only.** Synthetic and translated
  records are training-only. A model evaluated on its own generator's output
  measures imitation, not detection.
- A translated record carries `source_sample_id` pointing at its original, and
  the split is assigned from the **source** record's hash, so a translated pair
  cannot straddle train and test.

**8. Minimum support per label.** Consistent with the existing evaluation floor
(`MIN_EVAL_RECORDS = 30`):

| Tier | Requirement |
|---|---|
| Reportable at all | >= 30 **human** test records for that label |
| Trainable | >= 200 train records |
| Below either | label reported as `UNMEASURABLE` / `NO_DATA`, never as a score |

At 80/10/10 this implies roughly **300 human records per label** to make one
label reportable. Across even the 7 labels that have data in English, that is
~2,100 human-authored Tamil records - a real collection effort, not a
weekend task. Saying so now is the point of this plan.

**9. Evaluation metrics.** Macro-F1 as the headline plus **per-class F1 with
support**, using the existing renderer
(`scripts/training/render_metrics.py`), which already states its denominator
and prints `no data, cannot be predicted` for absent labels. Accuracy is not
reported: the class distribution is too skewed for it to mean anything.

**10. Tamil evaluated separately, never merged.** Tamil gets its own report and
its own row. A combined multilingual macro-F1 would let 76,246 English records
mask Tamil performance entirely. The existing per-language evaluation splits
(`language_english`, `language_hindi`, `language_hinglish`) extend with
`language_tamil` and `language_tanglish`, and each is subject to the same
30-record floor - a Tamil split below it is reported **blocked**, not scored.

### Honest limitation

Until this data exists, **Tamil intent and behaviour classification are not
supported and must not be described as supported.** Tamil ASR works
(`PHASE7_REPORT.md` §7) and that is the transcription half only - transcribing
Tamil is not understanding it. No Tamil intent or behaviour metric exists, and
none may be quoted or estimated.

## 8.4 Phase 9 re-audit (2026-09-22)

Every property below was re-derived from the manifests by
`scripts/evaluation/audit_datasets.py`, not read from
`scamshield.summary.json` - trusting the build script's own summary would only
confirm it agrees with itself. Record:
`models/evaluation/phase9/9A_dataset_provenance_audit.json`.

**Licensing.** All 85,602 records carry `MIT/VERIFIED`. Zero records lack a
verified licence.

**Exact leakage.** Zero identical texts shared between train and test.

**Near-duplicate leakage, and what it was worth.** Hashing with digits masked
and punctuation stripped finds **622 of 8,644 test records (7.20%)** sharing a
key with a training record, concentrated in `Synthetic_Tier_C` (320) and
`Smishing_Dataset` (250). Exact hashing could not have caught these, because
SMS corpora are full of template text.

Scoring the held-out split twice then settled what it cost: removing all 622
moved intent macro-F1 by **-0.0006** and behaviour by **-0.0057**. The leakage
is real and immaterial. The hypothesis that it inflated the headline figures
is **refuted**, and is recorded here rather than deleted. De-leaked figures are
the ones quoted in `EVALUATION.md` regardless, because they cost nothing to
prefer.

**Lineage separation.** 134 of 178 `split_group` lineages appear in more than
one split. The large ones are whole source corpora, which cannot be held out
entirely and still leave test data drawn from them; 129 straddling groups hold
<=200 records and account for 359 test records. Content-addressed splitting
keeps texts disjoint but does **not** make source lineages disjoint, and the
manifest schema should not be read as promising that it does.

**Synthetic provenance.** 3,009 train / 353 val / **358 test** records carry a
`Synthetic_*` provenance, so a small part of the test split is machine-written
text rather than collected messages.

**Tamil.** Re-measured rather than cited: **0** Tamil codepoints
(U+0B80-U+0BFF) across all 85,602 records and 0 records tagged Tamil. O11
stands as written.

**Collinearity.** Re-measured: `intent != NORMAL_CONVERSATION` reproduces
`is_scam` for 85,602/85,602 records (100.0000%), and **0** benign records carry
a non-NORMAL behaviour. See O10 for what the *model outputs* do, which is less
extreme than the labels.

### Corpora added in Phase 9

| Source | Licence | Gated | Role |
|---|---|---|---|
| `openslr/librispeech_asr` clean/test | CC-BY-4.0 | no | speaker verification; carries a real `speaker_id` |
| `microsoft/speecht5_tts` | MIT | no | synthetic half of the anti-spoofing probe |
| `microsoft/speecht5_hifigan` | MIT | no | vocoder for the above |
| `Matthijs/cmu-arctic-xvectors` | MIT | no | speaker embeddings for synthesis |

Rejected, with the reason recorded so the decision is not silently revisited:

| Source | Licence | Why not |
|---|---|---|
| `facebook/mms-tts-hin`, `-tam` | CC-BY-NC-4.0 | non-commercial; same rule that rejected `facebook/mms-1b-all` in Phase 7 |
| `ai4bharat/indic-parler-tts` | Apache-2.0 | `gated: auto` - needs account-holder acceptance; **not downloaded** |
| ASVspoof2019 LA | ODC-By 1.0 | **no longer rejected** - acquired 2026-09-23 from an ungated ODC-By redistribution of the eval partition (O5, O12) |
| VoxCeleb1 | request form | cannot be completed programmatically (O5) |

Both SpeechT5 checkpoints ship only `pytorch_model.bin`. They were **not**
loaded directly: `scripts/training/safe_load_bin.py` audited each pickle opcode
stream without executing it, both audits passed with only tensor-rebuild and
container symbols present, and each was then converted to safetensors. The
`.bin` files were deleted afterwards. Same procedure as R7.

The probe audio lives under `models/artifacts/_probe/` and is **git-ignored**
(`models/artifacts/**` plus `*.wav`). It is regenerated by
`scripts/evaluation/build_spoof_probe.py`, which is tracked.

## 9. Test fixtures

`tests/fixtures/` holds short audio for automated tests and demo replay. These
are tracked in git (explicitly un-ignored) and must be small, synthetic or
consented, and free of PII. They back the scenarios in `DEMO_SPEC.md`.
