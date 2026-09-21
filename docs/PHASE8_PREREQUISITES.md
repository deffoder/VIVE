# VIVE — Phase 8 Prerequisites

What must be settled before real models replace the mock adapters. **This is a
checklist, not an implementation.** Nothing here has been built; Phase 8 has
not started.

Each item states what is true today, what must change, and what breaks if it
is skipped.

---

## 1. Reconcile the ASR model id across 11 sites

The ASR architecture is now **selected**: `ai4bharat/indic-conformer-600m-multilingual`,
CTC path (`ML_SPEC.md` §2.1). Canonical VIVE id **`indic-conformer-600m`**,
`model_version` **`indic-conformer-600m-ctc-v1`**.

The specs have been updated. The **code has not** - this checkpoint
deliberately did not touch backend or Android runtime code, so the running
system still emits the old `indicconformer` string:

| Location | Use | State |
|---|---|---|
| `docs/ML_SPEC.md` §2, §2.1, §9 | inventory, selection, integration order | **updated** |
| `docs/API_SPEC.md` §3, §5 | `model_version` example, model list | **updated** |
| `backend/app/adapters/interfaces.py` | `MODEL_IDS["asr"]` | stale |
| `backend/app/adapters/mock.py` | mock ASR `id` | stale |
| `backend/app/api/routes/system.py` | `/models` response | stale |
| `backend/tests/test_api.py` | asserts the id is present | stale |
| `android/.../DemoRepositories.kt`, `DemoData.kt`, `StubRepositories.kt` | model info screen | stale |

**Required:** change the six stale sites in one commit, with the test updated
in the same change. Until then the spec and the running code **disagree on the
id**, which is recorded here rather than left to be discovered.

---

## 2. ASR architecture selection — DECIDED

Selected on measured evidence, not preference. All candidates decoded identical
`google/fleurs` splits through one shared normaliser
(`models/training/asr_text.py`); per-window cost was measured directly on a
fixed 2 s window in an isolated process, not extrapolated.

| | IndicWav2Vec | Whisper turbo | **IndicConformer CTC** |
|---|---:|---:|---:|
| Hindi WER / CER | 0.1872 / 0.0699 | 0.3154 / 0.1218 | **0.1164 / 0.0460** |
| Tamil WER / CER | no model | 0.6752 / 0.1952 | **0.2833 / 0.1107** |
| Cost per 2 s window | 0.0627 s | 5.5478 s | **0.2549 s** |
| Meets 1.0 s cadence | yes | **no (5.5x over)** | yes (~25% of budget) |
| Execution | PyTorch CUDA | PyTorch CUDA | **ONNX CPU-only** |
| VRAM | 1.31 GB | 1.72 GB | **0.00 GB** |
| Languages | Hindi only | 100 | **IN-22** |
| Licence | Apache-2.0 | MIT | **MIT** |

**Rationale:** best accuracy in both priority languages; fits the cadence while
CPU-only, leaving the GPU free for the other analyzers; one model removes the
need for a language-routing layer.

**Rejected:** Whisper - worse at both languages it would unify and far over
budget. **Not selected but retained:** IndicWav2Vec, ~4x cheaper per window but
Hindi-only.

**Superseded measurements**, retained in `ML_SPEC.md` §2.2 and
`asr_comparison.json` and **never to be quoted**: the conformer RTF probe of
1.3912 (taken under contention; real value 0.1218) and the extrapolated Whisper
window cost of 1.503 s (real value 5.5478 s).

### Open items this selection does not close

- **CPU-only is an environment property.** `onnxruntime-gpu` needs CUDA 12; the
  driver here (461.72) caps at 11.2. The model already fits the budget without
  a GPU, so this is upside rather than a prerequisite. No driver was changed.
- **Confirm on target deployment hardware**, not this development machine.
- **Loading cost:** 2.50 GB on disk, ~9-11 s load, ~2.6 GB RSS. Needs a
  load-once lifecycle (§5), not per-request construction.
- **FLEURS is clean read speech.** Every figure above is a benchmark floor, not
  telephone or call-channel accuracy, which remains unmeasured.

---

## 3. Tamil quality

The original concern here was Whisper's Tamil WER of 0.6752 - roughly two words
in three wrong, feeding a transcript that intent and behaviour both consume.

**Superseded by measurement.** IndicConformer reaches Tamil WER **0.2833**
with a 1.0000 Tamil-script ratio - less than half Whisper's error rate and a
plausible basis for Tamil ASR support. The Whisper Tamil figure is no longer
the best available option.

**Still required:** Tamil remains degraded relative to Hindi (0.2833 vs
0.1164), so the UI must reflect lower confidence for Tamil rather than treating
the two as equivalent.

**Must not happen:** Tamil being listed as fully supported.

### 3.1 The Tamil text gap is separate and still open (O11)

Working Tamil ASR resolves **transcription only**. Audited 2026-09-21:

| Check | Result |
|---|---|
| Tamil records in the training corpus | **0 of 85,602** |
| Tamil codepoints anywhere in the corpus | **0** |
| Romanised Tamil (Tanglish) | 37 hits, **all false positives** |
| Tamil scam-labelled corpora found (19 examined) | **0 under any licence** |

So a Tamil call would be **transcribed correctly and then classified by a
model that has never seen Tamil**. Phase 8 must therefore either route Tamil
transcripts away from the intent/behaviour heads, or surface them with
explicitly reduced confidence - it must not present a Tamil intent prediction
as equivalent to an English one.

Remediation plan, including the human-only test-split rule that blocks
synthetic and translation leakage: `DATA_SPEC.md` §8.3.

---

## 4. Fusion cannot be calibrated against this corpus (O10)

`app/risk/fusion.py` combines intent and behaviour with a noisy-OR, which
assumes independent evidence. Measured:
`intent != NORMAL_CONVERSATION` reproduces `is_scam` for **100.0000%** of
85,602 records, and **0** benign records carry any behaviour flag.

Calibrating fusion on data where the two inputs cannot disagree would bake the
collinearity into the weights.

**Required:** acquire benign-with-behaviour examples (`DATA_SPEC.md` §8.2)
before fitting weights. Until then weights stay expert-set and provisional
(O6), and confidence must not be presented as calibrated.

---

## 5. Adapter lifecycle the real models need

The `interfaces.py` protocols are sufficient in shape, but the real adapters
add requirements the mocks never exercised:

- **Load cost.** The selected ASR model is 2.50 GB on disk, takes ~9-11 s to
  load and holds ~2.6 GB RSS. Loading per request is not viable. Adapters need
  a load-once lifecycle with `available()` reflecting real load state rather
  than returning a constant.
- **Device contention.** ASR runs on **CPU** while AASIST, ECAPA and the text
  classifiers run on the GPU, so the two do not contend for VRAM - a genuine
  advantage of the selection. They do contend for CPU threads: onnxruntime
  defaults to all 12 logical cores. Concurrent sessions still need a queue or
  a worker; nothing in the current design arbitrates this.
- **Checkpoint provenance.** `model_version` must carry the real checkpoint
  identity, and `models/artifacts/` is git-ignored, so deployment needs a
  documented fetch step. `scripts/training/safe_load_bin.py` must remain in the
  path for any `.bin` checkpoint — see item 7.
- **Failure mode.** A model that fails to load must return
  `AnalyzerStatus.UNAVAILABLE`, not raise. That path exists but has only ever
  been exercised by mocks.

---

## 6. Language detection must feed routing

`AsrResult` already carries `language` and `language_confidence`. Nothing
currently sets them from a real model.

The selection changes the shape of this problem. IndicConformer is a **single
multilingual model**, so a misdetected language no longer selects the wrong
*model* - but the CTC decoder applies a **per-language vocabulary mask**
(`language_masks.json`, 22 languages), so the language still determines which
tokens can be emitted. A wrong language code produces confident output in the
wrong script rather than an obvious failure.

**Required:** decide how the language code is chosen per packet, and what
happens when confidence in it is low. The safe default is to lower overall
confidence rather than guess — consistent with `PROJECT_SPEC.md` §2, where
missing evidence reduces confidence and never raises risk. The script-ratio
check used during evaluation (`eval_asr_whisper.py`) is a cheap runtime guard:
output that is not in the expected script signals a language error, not poor
accuracy.

---

## 7. Security invariants that must survive Phase 8

- `.bin` checkpoints stay behind the pickle audit
  (`scripts/training/safe_load_bin.py`). Do not relax it because a download is
  inconvenient; the torch < 2.6 restriction (CVE-2025-32434) is real.
- Model weights stay git-ignored. Nothing in `models/artifacts/` is committed.
- Transcripts are sensitive (`SECURITY_SPEC.md` §4). Real ASR produces real
  transcript content, so log redaction must be re-verified once a real adapter
  is wired — the mock never produced anything worth redacting.

---

## 8. Claims that must not be made when Phase 8 ships

Carried forward because integration is exactly when they tend to slip:

- No EER for AASIST, no verification metric for ECAPA — neither was measured.
- `OTP_REQUEST` is **unmeasurable** at 8 test records, not "63% accurate".
- Intent macro-F1 0.9219 covers 7 of 12 labels and partly measures the
  scam/not-scam boundary (O10). It is not intent-discrimination accuracy.
- All ASR WERs are FLEURS **clean read speech** — a benchmark floor, not
  telephone or call-channel accuracy, which has **not been measured**.
- Tamil **intent/behaviour** classification remains unsupported: the text
  corpus has **0 Tamil records and 0 Tamil codepoints** (O11), regardless of
  Tamil ASR working. Tamil transcription is validated; Tamil understanding is
  not. Do not describe VIVE as supporting Tamil scam detection.
- The superseded conformer probe (RTF 1.3912) and the extrapolated Whisper
  window cost (1.503 s) must never be quoted; the measured values are 0.1218
  and 5.5478 s.
