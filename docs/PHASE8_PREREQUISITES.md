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

All three candidates have now been measured on identical FLEURS splits with
one shared normaliser (`PHASE7_REPORT.md` §7):

| | IndicWav2Vec | Whisper turbo | IndicConformer |
|---|---|---|---|
| Hindi WER | 0.1872 | 0.3154 | **0.1164** |
| Tamil WER | no model | 0.6752 | **0.2833** |
| RTF | **0.0038** | 0.7513 | 0.1218 (CPU) |
| Cost / 2 s window | 0.008 s | 1.503 s | 0.2437 s |
| Meets 1.0 s cadence | yes | **no** | yes |
| Languages | Hindi only | 100 | IN-22 |

**Whisper is eliminated on measurement**: worse at both languages it would
unify, and over the latency budget.

The remaining choice is IndicConformer (best accuracy in both languages, one
model, CPU-only here) versus IndicWav2Vec (fastest by far, Hindi only, needs a
second Tamil model). IndicConformer's latency is an **environment** property -
onnxruntime has no CUDA provider under driver 461.72 - so a CUDA 12 environment
would change it.

**Required before choosing:** confirm the numbers on the target deployment
hardware rather than the development machine, and decide whether the CPU-only
ONNX path is acceptable in production.

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

**Must not happen:** Tamil being listed as fully supported. Tamil **text**
intent and behaviour classification is still untrained - the corpus has no
Tamil (O8) - so working Tamil ASR resolves only the transcription half.

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
