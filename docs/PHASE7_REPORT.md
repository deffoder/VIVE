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
| Gated AI4Bharat ASR repositories | **Resolved.** Terms already accepted; full snapshot downloads and the model runs (`BLOCKERS.md` R7) |

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

## 4. Pretrained stack

| Model | License | Status |
|---|---|---|
| Silero VAD | MIT | **Loads and runs.** No accuracy measured |
| AASIST | MIT | **Checkpoint loads** (229 tensors). Model class not vendored, so no forward pass yet. **No EER measured** |
| ECAPA-TDNN | Apache-2.0 | **Loads and runs**, 192-dim embedding. **No verification metric measured** |
| `ai4bharat/indicwav2vec-hindi` | Apache-2.0 | **Loads, runs and is EVALUATED** — see §4.1 |

Three of the four are load-and-run smoke tests only: **no EER or accuracy
exists for Silero, AASIST or ECAPA**, and none may be quoted. ASR is the one
stage with a real measured metric.

### 4.1 Hindi ASR — measured

Access to the gated AI4Bharat repository was verified directly: the full
1.26 GB snapshot, including `pytorch_model.bin`
(1,262,181,719 bytes), downloads under the existing token
(`BLOCKERS.md` R7). The model loads as `Wav2Vec2ForCTC` — 315.5M parameters,
vocabulary 68, 16 kHz — and a forward pass returns well-formed logits.

The repository ships **only a `.bin`**, which transformers refuses to
`torch.load` on torch < 2.6 (CVE-2025-32434). That check was **not disabled**.
`scripts/training/safe_load_bin.py` audits the pickle opcode stream *without
executing it* and allowlists the global symbols it may import; this file
references only `collections.OrderedDict`, `torch.FloatStorage` and
`torch._utils._rebuild_tensor_v2`. Only after that audit passed was it loaded
with `weights_only=True` and converted to 424 safetensors tensors, which every
later load reads instead.

**Benchmark:** `google/fleurs` [`hi_in`] `test` — CC-BY-4.0,
ungated. 418 utterances, 4832 s of audio.

| Metric | Value |
|---|---|
| **WER** | **0.1872** |
| **CER** | **0.0699** |
| Substitutions / Deletions / Insertions | 1,499 / 243 / 191 |
| Hits | 8,585 |
| Real-time factor (GPU) | 0.0039 |

Normalisation, applied identically to reference and hypothesis: Unicode NFC, lowercase, strip punctuation including Devanagari danda U+0964 and double danda U+0965, collapse whitespace.
The Devanagari danda (U+0964) is stripped because the CTC vocabulary cannot
emit it; leaving it in the reference would charge the model for tokens it has
no way to produce.

**What this number is not.** FLEURS is clean read speech at 16 kHz — no
telephony codec, no channel noise, no spontaneous-speech disfluency, no
code-switching. This WER is therefore a **floor**: a best case on easy audio.
Call-channel Hindi WER will be worse, by an amount that has not been measured.
It must never be presented as VIVE call-transcription accuracy. Decoding is
greedy CTC with no language model, which a production path would improve.

The real-time factor excludes feature extraction, audio I/O and the rest of
the VIVE pipeline, and was measured at batch size 1 on a GTX 1650 Ti.

---

## 5. Evaluation splits: 6 built, 7 blocked, 1 measured externally

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
| `asr_tamil` | No Tamil ASR evaluation data (O8) |

`asr_hindi` is **not** blocked: it is measured against FLEURS (§4.1) rather
than derived from this text corpus, and is recorded as
`measured_externally` so it is neither hidden nor credited to the corpus.

A blocked split is never reported as passed.

---

## 6. What remains blocked

### R7 — Indic ASR access · **RESOLVED**

Previously recorded here as blocked. Re-verified rather than assumed: the
repository terms had been accepted, the 1.26 GB snapshot downloads under the
existing token, and the model loads and runs. Hindi WER is measured in §4.1.

### O8 — Tamil

Tamil is a priority language in `CLAUDE.md` and the **text** corpus contains
none, so Tamil intent and behaviour classification remain unsupported. Tamil
**ASR** is addressed separately in §7.

### O9 / O10 — label coverage and label independence

Measured by `scripts/training/audit_label_coverage.py`
(`models/evaluation/label_coverage_audit.json`):

- `OTP_REQUEST` has **8 test records**, below the 30-record floor. It is
  **unmeasurable**, not merely weak; its 0.632 F1 must not be quoted.
- `intent != NORMAL_CONVERSATION` reproduces `is_scam` for **100.0000%** of
  85,602 records, so the intent head is a scam detector with sub-classes and
  its macro-F1 partly measures that easier task.
- **0** benign records carry any social-engineering behaviour, so the
  behaviour head has never seen legitimate urgency and false positives on
  legitimate urgent calls are expected.
- Risk fusion combines these two as independent evidence, which the data does
  not support. Fusion weights stay provisional (O6).

Remediation plan, with a verified Apache-2.0 candidate corpus:
`DATA_SPEC.md` §8.2.

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

## 7. ASR candidate comparison (measured)

All three candidates decoded the **same** `google/fleurs` test splits
(CC-BY-4.0) through the **same** normaliser, and were separately benchmarked on
a fixed synthetic 2 s window in an isolated process. Generated from the report
JSONs by `scripts/training/compare_asr.py`; a candidate with no run for a
language renders as "not measured" rather than being dropped.

| Model | Languages | License | WER hi | CER hi | WER ta | CER ta | RTF (utterance) | Cost / 2s window | Execution | VRAM | RAM | Streaming | Access |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|
| IndicWav2Vec Hindi | Hindi only | Apache-2.0 | 0.1872 | 0.0699 | not measured | not measured | 0.0038 | **0.0627 s** | PyTorch CUDA fp32 | 1.31 GB | 2.841 GB | YES - 16x headroom | gated, terms accepted |
| Whisper large-v3-turbo | 100 incl. hi + ta | MIT | 0.3154 | 0.1218 | 0.6752 | 0.1952 | 0.7513 | **5.5478 s** | PyTorch CUDA fp16 | 1.717 GB | 2.99 GB | NO - 5.5x over budget | ungated |
| IndicConformer-600M | IN-22 incl. hi + ta | MIT | 0.1164 | 0.0460 | 0.2833 | 0.1107 | 0.1218 | **0.2549 s** | ONNX Runtime CPU only | 0.0 GB | 2.755 GB | YES - 4x headroom | gated, terms accepted |

wrote C:\Users\cvumj\Downloads\SIH26104-ALL\VIVE\models\evaluation\asr_comparison.json

### Per-window cost is measured, not extrapolated

`RTF x 2.0` understates the autoregressive model badly. Whisper pads every
input to a fixed 30 s window - a 2 s input yields
3000 mel frames - so its
measured cost is **5.5478 s**
against 1.503 s extrapolated, **3.7x** worse. The CTC candidates scale with
input length and their two figures agree.

### Superseded measurement

A preliminary conformer probe reported RTF **1.3912** under contention with a
running evaluation. It is **superseded** by the completed benchmark
(**0.1218**, ~11x faster) and recorded in `asr_comparison.json` under
`superseded_measurements`. It must not be quoted.

### What the measurements settle

**IndicConformer-600M leads on accuracy in both languages.** Hindi WER 0.1164
beats IndicWav2Vec's 0.1872; Tamil WER 0.2833 is less than half Whisper's
0.6752. Script ratio is **1.0000** for both, so output is genuinely in the
target script.

**The single-multilingual-model preference was not supported.** Whisper is the
only candidate covering both languages natively, but is worse at both and 5.5x
over the per-window budget.

**Architecture dominates size.** IndicWav2Vec (315M, CTC) costs 0.063 s per
window; Whisper (809M, autoregressive) costs 5.548 s - ~88x more for a larger
error rate.

**Memory.** The conformer runs CPU-only with effectively **0 GB VRAM**, leaving
the GPU free for the rest of the pipeline. Measured in isolated processes: a
first combined run reported an implausible 0.153 GB RSS for Whisper because
Windows trimmed the working set after the previous model was freed.

### Caveats

- FLEURS is clean read speech: every WER is a **floor**, not call-channel
  accuracy. Greedy decoding, no language model.
- The conformer's CPU-only execution is an environment property
  (`onnxruntime-gpu` needs CUDA 12; driver 461.72 caps at 11.2), not a model
  property. No driver or CUDA change was made.
- Moving the TorchScript preprocessor to GPU made it **slower** (RTF 0.315 vs
  0.1218): host-to-device transfer costs more than the preprocessing saves.
- Tamil **text** classification remains unsupported regardless
  (`BLOCKERS.md` O8). Working Tamil ASR resolves only transcription.
- **Selection made 2026-09-21** on this evidence:
  `ai4bharat/indic-conformer-600m-multilingual`, CTC path
  (`ML_SPEC.md` §2.1). No application code was changed; the backend and
  Android clients still emit the old `indicconformer` id, which is a Phase 8
  task (`PHASE8_PREREQUISITES.md` §1).

---

## 8. Reproducibility

Every run records base model, label set, seed (`20260921`), hyperparameters,
dataset sizes, python/torch versions, device, platform, timestamps, wall-clock
duration, peak VRAM and the measured metrics, in
`models/evaluation/<task>_training_report.json`.

The metrics in §3 are **generated** from those JSON files by
`scripts/training/render_metrics.py`, not typed by hand, so a figure in this
document cannot drift from the figure that was measured.

Checkpoints are git-ignored; manifests, scripts and reports are tracked, so a
run is reproducible from a commit without the repository carrying weights.
