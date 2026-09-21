# VIVE — Phase 8 Prerequisites

What must be settled before real models replace the mock adapters. **This is a
checklist, not an implementation.** Nothing here has been built; Phase 8 has
not started.

Each item states what is true today, what must change, and what breaks if it
is skipped.

---

## 1. The canonical ASR model id is wrong

`ML_SPEC.md` §2 names the ASR model `indicconformer`. That id is hard-coded in
**11 places** across the specs, backend, tests and the Android client:

| Location | Use |
|---|---|
| `docs/ML_SPEC.md` §2, §9 | model inventory, integration order |
| `docs/API_SPEC.md` §3, §5 | `model_version` example, model list |
| `backend/app/adapters/interfaces.py` | `MODEL_IDS["asr"]` |
| `backend/app/adapters/mock.py` | mock ASR `id` |
| `backend/app/api/routes/system.py` | `/models` response |
| `backend/tests/test_api.py` | asserts the id is present |
| `android/.../DemoRepositories.kt`, `DemoData.kt`, `StubRepositories.kt` | model info screen |

When this was written no `indicconformer` checkpoint had been obtained. One
now has been, and it is the accuracy leader (§2) - so the id may turn out to be
correct after all. It must still be reconciled deliberately rather than by
coincidence, and `ML_SPEC.md` §2 currently describes it as covering hi/ta/en
when the checkpoint covers IN-22.

**Required:** decide the real id(s), then change all 11 sites in one commit
with the test updated in the same change. Leaving a stale id would put a model
name in the UI and in `model_version` that corresponds to nothing that ran —
exactly the fabrication `CLAUDE.md` forbids.

**Blocked on:** item 2, because the id depends on the routing decision.

---

## 2. One multilingual model, or one model per language

All three candidates measured on identical `google/fleurs` test splits through
one shared normaliser (`models/training/asr_text.py`), and separately
benchmarked on a fixed synthetic 2 s window in an isolated process
(`scripts/training/measure_asr_window.py`).

| Model | Languages | License | WER hi | CER hi | WER ta | CER ta | RTF (utterance) | Cost / 2s window | Execution | VRAM | RAM | Streaming | Access |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|
| IndicWav2Vec Hindi | Hindi only | Apache-2.0 | 0.1872 | 0.0699 | not measured | not measured | 0.0038 | **0.0627 s** | PyTorch CUDA fp32 | 1.31 GB | 2.841 GB | YES - 16x headroom | gated, terms accepted |
| Whisper large-v3-turbo | 100 incl. hi + ta | MIT | 0.3154 | 0.1218 | 0.6752 | 0.1952 | 0.7513 | **5.5478 s** | PyTorch CUDA fp16 | 1.717 GB | 2.99 GB | NO - 5.5x over budget | ungated |
| IndicConformer-600M | IN-22 incl. hi + ta | MIT | 0.1164 | 0.0460 | 0.2833 | 0.1107 | 0.1218 | **0.2549 s** | ONNX Runtime CPU only | 0.0 GB | 2.755 GB | YES - 4x headroom | gated, terms accepted |

wrote C:\Users\cvumj\Downloads\SIH26104-ALL\VIVE\models\evaluation\asr_comparison.json

### Cost per window is measured, not extrapolated

The earlier table derived per-window cost as `RTF x 2.0` from FLEURS utterances
averaging ~12 s. That is unsafe, and the measurement proves it: Whisper pads
**every** input to a fixed 30 s of mel frames - a 2 s VIVE window produces
**3000 mel frames, a 30 s equivalent**. Its real cost
per window is **5.5478 s**, against
**1.503 s** predicted by extrapolation: understated **3.7x**.

The CTC candidates scale with input length, so their extrapolated and measured
figures agree closely. Only the autoregressive, fixed-window model diverges -
which is exactly the model the naive figure would have made look viable.

### Superseded measurement

An early conformer probe reported **RTF 1.3912** and "does not meet cadence".
It was taken while the Whisper evaluation still held the machine and is
**superseded**; the completed benchmark measures **RTF 0.1218**, about 11x
faster. It is recorded in `models/evaluation/asr_comparison.json` under
`superseded_measurements` so it cannot be mistaken for a result. **Do not quote
1.3912 anywhere.**

### What this settles, and what it does not

**Whisper is eliminated on measurement.** Worse at *both* languages it would
unify - Hindi 0.3154 vs 0.1872, Tamil 0.6752 vs 0.2833 - and **5.5x over** the
per-window budget. Testing the single-multilingual-model preference was
worthwhile; adopting it untested would have regressed Hindi by 68%.

**Two candidates remain viable, for different reasons:**

- **IndicConformer-600M** has the best accuracy in both languages and covers
  IN-22 with one model. It fits the cadence at **25.5% of budget while running
  CPU-only**, leaving the GPU entirely free for AASIST, ECAPA and the
  classifiers. Its peak VRAM is effectively **0 GB**.
- **IndicWav2Vec** is ~4x cheaper per window (**6.3% of budget**) and the
  fastest by a wide margin, but covers **Hindi only** and would require a
  second model plus language routing for Tamil.

**Not decided here.** No selection has been made. The trade-off is one
multilingual model with the best accuracy versus a faster Hindi-only model
needing a Tamil partner and routing logic (item 6).

**Still required before choosing:** confirm on target deployment hardware
rather than this development machine. The conformer's CPU-only execution is an
environment property - `onnxruntime-gpu` needs CUDA 12 and the driver here
(461.72) caps at 11.2 - so its latency would change, though it already fits
without a GPU.

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

- **Load cost.** Whisper is 809M params / 1.62 GB; indicwav2vec is 315M.
  Loading per request is not viable. Adapters need a load-once lifecycle with
  `available()` reflecting real load state rather than returning a constant.
- **Device contention.** The models share one GPU. Concurrent sessions need a
  queue or a worker; nothing in the current design arbitrates this.
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
currently sets them from a real model or routes on them. If per-language models
are chosen (item 2), a misdetected language silently selects the wrong model.

**Required:** define behaviour when language confidence is low. The safe
default is to lower overall confidence rather than guess — consistent with
`PROJECT_SPEC.md` §2, where missing evidence reduces confidence and never
raises risk.

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
- All ASR WERs are FLEURS read speech — a floor, not call-channel accuracy.
- Tamil intent/behaviour classification remains unsupported: the text corpus
  has no Tamil (O8), regardless of Tamil ASR working.
