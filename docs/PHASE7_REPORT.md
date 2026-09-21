# VIVE — Phase 7 Report: Data Preparation and Training

What was actually built, measured and blocked in the data and training phase.

> **Nothing here is a VIVE accuracy claim.** Every measured figure comes from a
> held-out split of one **SMS corpus**. That is not a call-transcript benchmark
> and not an end-to-end fraud-detection result. Figures for models that were
> not evaluated are reported as absent, never estimated.

Date of run: 2026-09-21 · GPU: GeForce GTX 1650 Ti (4 GB) · torch 2.5.1+cu118

---

## 1. Credentials and access — resolved at the start of the phase

| Requirement | Status |
|---|---|
| HuggingFace authentication | **Resolved.** `hf auth whoami` succeeds |
| GPU for training | **Resolved.** Local 4 GB GPU; no cloud credits needed for the text models |
| Gated/registration corpora (ASVspoof, VoxCeleb) | **Not obtained.** Both require human-completed agreements |
| Gated AI4Bharat ASR repositories | **Outstanding — needs one human action** (§6) |

---

## 2. Data that is ready

`sidzzz07/scamshield-dataset` — **MIT**, verified from repository metadata
rather than assumed.

| Property | Value |
|---|---|
| Unique records | 85,602 (78 duplicates removed by content hash) |
| Splits | train 68,412 · val 8,546 · test 8,644 |
| Cross-split collisions | **0** |
| Languages | English 76,246 · Hindi 6,352 · Hinglish 3,004 |

Splits are **content-addressed**: the split is a function of a hash of the
normalised text, so a message that appears twice always lands in the same
split. Random splitting would not give that guarantee, and duplicate-driven
leakage is the realistic failure mode for an SMS corpus.

### Manifests and PII

The full manifests (62.6 MB) carry the message bodies, which contain
phone numbers, URLs and OTP-length digit runs. `SECURITY_SPEC.md` §4 keeps that
out of the repository, so the build emits two artefacts:

- `scamshield.{split}.jsonl` — full text, **git-ignored**, local only
- `scamshield.{split}.index.jsonl` — **tracked**, body replaced by a hash

The tracked indexes were scanned across all 85,602 records: every digit run
found lies inside a hex hash, **zero occur in any other field**, and no record
carries a key outside the fixed eight-field schema. The split assignment is
therefore auditable from the repository without the repository holding message
text.

---

## 3. Measured results

### intent-classifier — measured on the held-out test split

- Base model: `distilbert/distilbert-base-multilingual-cased`
- Test records: 8,644 (train 68,412, val 8,546)
- Trained: 120 min on GeForce GTX 1650 Ti, peak VRAM 1.51 GB
- Seed: 20260921 · torch 2.5.1+cu118

**macro-F1 = 0.9219** · weighted-F1 = 0.9799

Macro-F1 is the headline because the class distribution is extremely
skewed; accuracy would be dominated by the majority class.

**This macro average is over the 7 of 12 labels that have test data**, not the full taxonomy. The other 5 are excluded entirely rather than scored, so the headline says nothing about them; spread over all 12 it would be **0.5378**. Excluded: `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`, `REMOTE_ACCESS_REQUEST`, `CONFIDENTIAL_INFORMATION`.

| Label | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| `NORMAL_CONVERSATION` | 0.987 | 0.988 | 0.987 | 5,479 |
| `OTP_REQUEST` | 0.545 | 0.750 | 0.632 | 8 |
| `PASSWORD_REQUEST` | — | — | — | **0 — no data, cannot be predicted** |
| `CARD_DETAILS_REQUEST` | — | — | — | **0 — no data, cannot be predicted** |
| `BANKING_CREDENTIAL_REQUEST` | 0.970 | 0.994 | 0.981 | 160 |
| `MONEY_TRANSFER_REQUEST` | 0.954 | 0.954 | 0.954 | 151 |
| `ACCOUNT_CHANGE_REQUEST` | — | — | — | **0 — no data, cannot be predicted** |
| `REMOTE_ACCESS_REQUEST` | — | — | — | **0 — no data, cannot be predicted** |
| `URGENT_ACTION` | 0.949 | 0.959 | 0.954 | 97 |
| `THREAT_OR_INTIMIDATION` | 0.989 | 0.966 | 0.977 | 89 |
| `CONFIDENTIAL_INFORMATION` | — | — | — | **0 — no data, cannot be predicted** |
| `UNKNOWN` | 0.971 | 0.967 | 0.969 | 2,660 |

> Measured on a held-out split of the scamshield SMS corpus only. Not a call-transcript benchmark and not a VIVE end-to-end accuracy claim.

---

### behavior-classifier — measured on the held-out test split

- Base model: `distilbert/distilbert-base-multilingual-cased`
- Test records: 8,644 (train 68,412, val 8,546)
- Trained: 119 min on GeForce GTX 1650 Ti, peak VRAM 1.51 GB
- Seed: 20260921 · torch 2.5.1+cu118

**macro-F1 = 0.7095** · micro-F1 = 0.9728

Macro-F1 is the headline because the class distribution is extremely
skewed; accuracy would be dominated by the majority class.

**This macro average is over all 8 labels, including 2 that have no training data and therefore score a hard 0.000.** Those 2 cannot be learned from this corpus, so the headline understates performance on what was actually trainable: across the 6 labels with data the macro-F1 is **0.9460**. Neither figure covers `THREAT`, `SECRECY`.

| Label | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| `AUTHORITY_IMPERSONATION` | 0.918 | 0.908 | 0.913 | 347 |
| `URGENCY` | 0.960 | 0.985 | 0.973 | 665 |
| `THREAT` | — | — | — | **0 — no data, cannot be predicted** |
| `FEAR` | 0.963 | 0.972 | 0.968 | 324 |
| `SECRECY` | — | — | — | **0 — no data, cannot be predicted** |
| `PRESSURE` | 0.884 | 0.860 | 0.872 | 507 |
| `REWARD_PROMISE` | 0.964 | 0.968 | 0.966 | 976 |
| `NORMAL` | 0.992 | 0.977 | 0.985 | 6,738 |

> Measured on a held-out split of the scamshield SMS corpus only. Not a call-transcript benchmark and not a VIVE end-to-end accuracy claim.

---

## 4. Pretrained stack — load-verified, accuracy NOT measured

| Model | License | Status |
|---|---|---|
| Silero VAD | MIT | **Loads and runs** |
| AASIST | MIT | **Checkpoint loads** (229 tensors). Model class not vendored, so no forward pass yet |
| ECAPA-TDNN | Apache-2.0 | **Loads and runs**, 192-dim embedding |
| AI4Bharat Indic ASR | Apache-2.0 | **BLOCKED** — gated, 403 on file download |

These are smoke tests. **No EER, WER or accuracy exists for any of them**, and
none may be quoted. Wiring them into the backend is the next phase.

---

## 5. Evaluation splits: 6 built, 8 blocked

Built: `standard_heldout` (8,644) · `language_english` (7,757) ·
`language_hindi` (622) · `language_hinglish` (265) ·
`social_engineering` (1,906) · `human_scam` (3,059).

Blocked, each with a recorded reason and blocker id rather than being dropped:

| Split | Reason |
|---|---|
| `language_tamil` | No Tamil in the corpus (O8) |
| `benchmark_ground_truth` | Only 1 held-out record, below the 30-record minimum |
| `synthetic_but_legitimate` | No record is both synthetic-origin and legitimate, so the two factors cannot be separated |
| `generator_disjoint` | No anti-spoofing corpus (O5) |
| `codec_noise_robustness` | Requires audio |
| `speaker_disjoint` | No speaker corpus (O3) |
| `asr_hindi` | Gated ASR model (O7) |
| `asr_tamil` | Gated ASR model and no Tamil (O7, O8) |

A blocked split is never reported as passed.

---

## 6. What remains blocked

### O7 — Indic ASR is gated (needs one human action)

The token authenticates and repository metadata reads successfully, but **file
downloads return 403** until the terms are accepted once on the model page:

<https://huggingface.co/ai4bharat/indicwav2vec-hindi> → "Agree and access repository"

Approval is automatic. Until then there is **no real ASR model**, and no WER
can be reported for any language.

### O8 — no Tamil data

Tamil is a priority language in `CLAUDE.md` and the corpus contains none.
Tamil is **not supported** and must not be described as supported.

### Coverage gaps that bound every claim

| Gap | Effect |
|---|---|
| 5 of 12 intents have no data | `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`, `REMOTE_ACCESS_REQUEST`, `CONFIDENTIAL_INFORMATION` **cannot be predicted** |
| 2 of 8 behaviours have no label source | `THREAT` and `SECRECY` are not trained |
| `OTP_REQUEST` has 103 samples (~0.1%) | The highest-value intent is the worst-supported |
| Corpus is SMS, not call transcripts | Register differs from speech; transfer is unvalidated |

### Not attempted in this phase

Anti-spoofing, speaker and ASR models were **not trained** — they are used as
pretrained checkpoints. No audio corpus was acquired, so no audio metric of any
kind exists.

---

## 7. Reproducibility

Every run records base model, label set, seed (`20260921`), hyperparameters,
dataset sizes, python/torch versions, device, platform, timestamps, wall-clock
duration, peak VRAM and the measured metrics, in
`models/evaluation/<task>_training_report.json`.

The metrics in §3 are **generated** from those JSON files by
`scripts/training/render_metrics.py`, not typed by hand, so a figure in this
document cannot drift from the figure that was measured.

Checkpoints are git-ignored; manifests, scripts and reports are tracked, so a
run is reproducible from a commit without the repository carrying weights.
