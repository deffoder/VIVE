# VIVE — ML Specification

> Model IDs here are canonical and are used verbatim in `API_SPEC.md` §5
> (`GET /api/v1/models`), in packet `model_version` fields, and on the Model
> Information screen (`UI_SPEC.md` §4).

## 1. Principles

1. **The app never runs inference.** Android is a client; all models execute
   behind backend model-service interfaces (`ARCHITECTURE.md` §1, decisions 7–8).
2. **Mock first.** Every interface ships a mock adapter. The product is fully
   demonstrable end-to-end before a single real checkpoint is integrated.
3. **No fabricated outputs.** Scores, versions and inference times are recorded
   from actual runs. Nothing production-looking is hard-coded, in either the
   backend or the UI.
4. **Degrade, never crash.** An adapter that cannot load reports a status; the
   pipeline continues and fusion re-weights.
5. **Real ML is the last major phase.** No large model downloads or training
   during the architecture phase.

## 2. Model inventory

| ID | Purpose | Stage | Output |
|---|---|---|---|
| `silero-vad` | Speech activity detection | Pre-filter | speech/silence, quality input |
| `aasist` | Anti-spoofing / synthetic-voice evidence | Per packet | `aasist.score` `0.0–1.0` |
| `ecapa-tdnn` | Speaker consistency | Per packet, needs reference | `ecapa.similarity` `0.0–1.0` |
| `indic-conformer-600m` | **Selected ASR** — multilingual, IN-22 (§2.1) | Per packet | transcript + confidence |
| `intent-classifier` | Intent over transcript | Per packet | 1 of 12 labels + confidence |
| `behavior-classifier` | Social-engineering behaviour | Per packet | 0..n of 8 labels + confidence |
| `risk-fusion` | Evidence to calibrated risk | Per packet | score, level, confidence, reasons |

Adapter keys used in `/ready` and configuration: `vad`, `antispoof`, `speaker`,
`asr`, `intent`, `behavior`.

## 2.1 Selected ASR architecture

**`ai4bharat/indic-conformer-600m-multilingual`, CTC decoding path.**
Selected 2026-09-21 on measured evidence (`PHASE7_REPORT.md` §7).

| Field | Value |
|---|---|
| Canonical VIVE id | `indic-conformer-600m` |
| `model_version` | `indic-conformer-600m-ctc-v1` |
| HuggingFace repo | `ai4bharat/indic-conformer-600m-multilingual` |
| Repo revision | `e9b71b369c048e2c6b634d4c131061c34e441179` |
| Licence | **MIT**, read from repository metadata |
| Access | Gated (`gated: auto`); terms accepted, files verified downloadable |
| Decoding | **CTC** (`decoding="ctc"`), greedy, no external language model |
| Runtime | ONNX Runtime; **CPU-only on the current machine** (§2.2) |
| Components loaded | `encoder.onnx` + `ctc_decoder.onnx` — **2 of 28** |
| Components not loaded | `rnnt_decoder`, `joint_enc/pred/pre_net`, 22x `joint_post_net_*` |
| Preprocessor | `assets/preprocessor.ts` (TorchScript), run on CPU |
| `BLANK_ID` | 256 |
| Vocabulary | 257 tokens per language; 5,633 mask ids |
| Languages | 22 (IN-22), including `hi` and `ta` |
| On-disk size | 2.50 GB, git-ignored under `models/artifacts/` |

### Why this and not the alternatives

Measured on identical `google/fleurs` splits through one shared normaliser:

| | IndicWav2Vec | Whisper turbo | **IndicConformer CTC** |
|---|---:|---:|---:|
| Hindi WER / CER | 0.1872 / 0.0699 | 0.3154 / 0.1218 | **0.1164 / 0.0460** |
| Tamil WER / CER | no model | 0.6752 / 0.1952 | **0.2833 / 0.1107** |
| Cost per 2 s window | 0.0627 s | 5.5478 s | **0.2549 s** |
| Meets the 1.0 s cadence | yes | **no** | yes |
| Languages | Hindi only | 100 | IN-22 |

- Best accuracy in **both** priority languages.
- Fits the cadence at ~25% of budget **while CPU-only**, leaving the GPU free
  for the other analyzers.
- One model covers both languages, so no language-routing layer is needed.
- IndicWav2Vec is ~4x cheaper per window but **Hindi only**; Whisper is worse
  at both languages and 5.5x over the per-window budget.

### What this selection does NOT claim

- FLEURS is **clean read speech**. These are benchmark figures, **not
  telephone or call-channel accuracy**, which has not been measured.
- Greedy CTC, no language model.
- Tamil **transcription** is validated. Tamil **intent and behaviour
  understanding is not** — the text corpus contains zero Tamil
  (`BLOCKERS.md` O11). Transcribing Tamil is not understanding it.
- CPU-only execution is an **environment** property, not a model property:
  `onnxruntime-gpu` requires CUDA 12 and the current driver (461.72) caps at
  CUDA 11.2. No driver or CUDA change was made.

## 2.2 Superseded measurements (retained, never quoted)

Kept so historical evidence is not destroyed and cannot resurface as fact:

| Measurement | Value | Why superseded |
|---|---|---|
| Conformer RTF probe | 1.3912 | Taken while another evaluation held the machine. Completed benchmark: **0.1218** |
| Extrapolated window cost (`RTF x 2.0`) | Whisper 1.503 s | Whisper pads every input to a fixed 30 s, so it does not scale with input length. Measured: **5.5478 s** |

Also recorded in `models/evaluation/asr_comparison.json` under
`superseded_measurements`. **Neither figure may be cited as a result.**

## 3. Interfaces (`models/interfaces/`)

One Python protocol per stage. Each returns a typed result carrying `status`,
`model_version` and `inference_ms` alongside its value. Sketch:

```python
class AntiSpoofModel(Protocol):
    id: str            # "aasist"
    version: str       # "aasist-v1"
    mode: Literal["mock", "real"]

    def load(self) -> None: ...
    def analyze(self, audio: AudioWindow) -> AntiSpoofResult: ...
```

`AntiSpoofResult` carries `status`, `score | None`, `model_version`,
`inference_ms`. Same shape for `SpeakerModel`, `ASRModel`, `IntentModel`,
`BehaviorModel`, `VADModel`.

`status` values are the canonical set from `PROJECT_SPEC.md` §7:
`AVAILABLE` · `UNAVAILABLE` · `NO_REFERENCE` · `INSUFFICIENT_AUDIO` · `ERROR`.

## 4. Adapters (`models/adapters/`)

```text
adapters/
├── mock/      deterministic, scripted, clearly labelled
└── real/      checkpoint-backed (final phase)
```

Selected by configuration (`models/configs/`), never by code edit. The active
mode is reported through `/ready` and rendered in the UI (`UI_SPEC.md` §6).

**Mock adapter rules.** Deterministic and seeded, so demos are repeatable.
Derived from a scenario script (`DEMO_SPEC.md`), not from random noise. Every
response is tagged `mode: "mock"` so it can never be mistaken for real
inference. Mock outputs are **not** presented as model accuracy anywhere.

## 5. Audio contract

16 kHz · mono · `pcm_s16le` · 2.0 s analysis window · 1.0 s stride.
Windows overlap; a packet is not a partition of the call (`ARCHITECTURE.md` §4).

Quality scoring precedes the models and yields `GOOD` · `DEGRADED` · `POOR` ·
`NO_SPEECH`. `POOR` and `NO_SPEECH` suppress downstream analyzers and lower
confidence — they never raise risk.

## 6. Risk fusion

Inputs: synthetic evidence, speaker consistency, intent, behaviour, context,
audio quality, uncertainty, temporal trend.

Fusion is **transparent and weighted**, with weights declared in
`models/configs/fusion.yaml` and versioned as `risk-fusion`. No final score is
hard-coded. Output:

```json
{
  "score": 91,
  "level": "CRITICAL",
  "confidence": 0.84,
  "contributions": { },
  "reasons": ["Elevated synthetic-voice indicators", "OTP request detected"]
}
```

Rules, restating `PROJECT_SPEC.md` §2–3:

- High `aasist.score` alone must not produce `CRITICAL`. Synthetic speech is not
  automatically fraud.
- Low `aasist.score` must not cap risk. Human-voice social engineering is the
  common case, and intent + behaviour must be able to drive risk on their own.
- Missing evidence lowers **confidence**, not risk.
- `score` and `confidence` are computed separately and never substituted.

Level thresholds are configuration, not literals in code.

## 7. Temporal risk

EMA smoothing over packet history; hysteresis so the level does not oscillate;
a minimum-evidence gate before the first non-`LOW` level; cooldown before
de-escalation. Recorded per session and returned in `timings`
(`API_SPEC.md` §3.2): `first_anomaly_sec`, `first_warning_sec`,
`first_high_sec`, `first_critical_sec`.

## 8. Future ML lifecycle

Training is the **final** phase and runs on **online GPU environments — Kaggle
or Google Colab**. No local GPU is assumed. Nothing in this section is executed
during the architecture phase: no dataset is downloaded, no model is trained.

```text
models/
├── training/     scripts + Colab/Kaggle entry points
├── evaluation/   metrics, calibration, confusion matrices
├── notebooks/    exploration (not a source of truth)
├── configs/      adapter selection, fusion weights, thresholds
└── artifacts/    checkpoints — git-ignored, see .gitignore
```

The nine stages below are the documented future process, in order.

### 8.1 Dataset preparation
Select corpora per `DATA_SPEC.md` §4. Verify each license before download —
an unlicensed corpus is not used. Build JSONL manifests with `clip_id`, `path`,
`dataset`, `license`, `label`, `split` and `provenance`. Assign splits in the
manifest. Run speaker- and generator-leakage checks; a failure blocks the run.

### 8.2 Preprocessing
Convert `raw/` to the canonical form in `processed/`: 16 kHz, mono,
`pcm_s16le`, segmented to the 2.0 s analysis window. Scripted under
`scripts/setup/`, never manual, so it is reproducible. Redact PII from
transcripts and manifests.

### 8.3 Cloud training
Package each model as a self-contained Kaggle/Colab notebook plus a
`scripts/training/` entry point: dependency pin, manifest fetch, training loop,
checkpoint export. Manifest version and hyperparameters are recorded with the
run. If GPU access is unavailable, the package is prepared and the required
external action is recorded in `BLOCKERS.md` rather than retried.

### 8.4 Validation
Evaluate on the held-out `val` split during training for model selection only.
The `test` split is never used for selection.

### 8.5 Evaluation
Measure on `test`: EER for anti-spoofing, verification metrics for the speaker
model, WER/CER per language for ASR, and per-class precision/recall for intent
and behaviour. Include an unseen-generator slice so generalisation is reported
rather than assumed. **Every figure comes from an executed run; a metric that
was not measured is reported as absent, never estimated.**

### 8.6 Checkpoint and versioning
Each checkpoint lands in `models/artifacts/` (git-ignored) with a manifest
recording model ID, semantic version, training manifest version, commit SHA,
metrics and date. The version string is what appears in packet `model_version`
and on the Model Information screen.

### 8.7 Model integration
Implement the `real` adapter behind the existing interface (§3). Selection is
configuration in `models/configs/`, never a code edit. Integration is strictly
sequential per §9; after each model, run a real sample, record measured
inference time, verify the UI renders it, then proceed.

### 8.8 Calibration
Recalibrate fusion against real outputs — raw model scores are not probabilities.
Fit on validation data, keep weights in `models/configs/fusion.yaml`, and report
calibration curves. Confidence is calibrated separately from risk (§6). Until
this completes, weights remain provisional (`BLOCKERS.md` O6).

### 8.9 Robustness testing
Exercise degraded conditions before release: background noise, codec and
bandwidth reduction, clipping, packet loss, accent and code-switching variation,
and unseen generators. Record where performance degrades. Known weaknesses are
documented in §10, not concealed.

## 9. Integration order (final phase)

Strictly sequential. After each: run a real sample, inspect output, record
inference time and version, verify it renders correctly, then proceed.

```text
silero-vad → aasist → ecapa-tdnn → indic-conformer-600m (CTC)
           → intent-classifier → behavior-classifier → risk-fusion calibration
```

## 9.1 Phase 7 status (data preparation + training)

What is actually built, as distinct from what is planned.

### Pretrained stack — verified to load and run

| Model | License | Status |
|---|---|---|
| `silero-vad` | MIT | **Loads and runs.** torch.hub, no credentials |
| `aasist` | MIT | **Checkpoint loads** (229 tensors, 1.28 MB). Model class not vendored, so no forward pass yet |
| `ecapa-tdnn` | Apache-2.0 | **Loads and runs.** Produces a 192-dim embedding |
| `indic-conformer-600m` | MIT | **SELECTED ASR** (§2.1). Loads and runs via ONNX CTC path; Hindi WER 0.1164, Tamil WER 0.2833 |
| `indicwav2vec-hindi` | Apache-2.0 | **Evaluated, not selected.** Hindi-only; Hindi WER 0.1872. Retained as a Hindi-only fallback, not the planned primary |
| `whisper-large-v3-turbo` | MIT | **Evaluated, rejected.** Worse at both languages and 5.5x over the per-window budget |

Silero, AASIST and ECAPA are load-and-run smoke tests: **no accuracy or EER has
been measured for them**, and none may be quoted.

ASR is the exception and has real measured figures. The **selected** model
(§2.1) measures **Hindi WER 0.1164 / CER 0.0460** (418 utterances) and
**Tamil WER 0.2833 / CER 0.1107** (591 utterances) on `google/fleurs`
(CC-BY-4.0), greedy CTC with no language model. FLEURS is clean read speech,
so these are **floors**, not call-channel accuracy
(`PHASE7_REPORT.md` §7).

### Trained in this phase

`intent-classifier` and `behavior-classifier` are fine-tuned locally from
multilingual DistilBERT on the scamshield corpus. Both runs completed on
2026-09-21 (2 epochs, seed 20260921, ~120 min each, peak VRAM 1.51 GB).

| Model | Test macro-F1 | Also |
|---|---|---|
| `intent-classifier` | **0.9219** over the 7 of 12 intents with data | weighted-F1 0.9799 |
| `behavior-classifier` | **0.7095** over all 8 behaviours | micro-F1 0.9728; 0.9460 over the 6 with data |

The two denominators differ because sklearn drops absent classes from a
single-label macro average but keeps them as zero columns in a multi-label one.
Both are stated wherever the figures appear; neither covers the labels with no
data. Full per-class tables: `docs/PHASE7_REPORT.md` §3, generated from the
report JSON by `scripts/training/render_metrics.py`.

**`OTP_REQUEST` scores 0.632 on 8 test records** — the weakest class and the
highest-value intent in the product, which is the 103-sample training count
surfacing exactly where it hurts. With 8 records the figure is fragile; it
indicates weakness, not a 63% capability.

These are **held-out F1 on an SMS corpus**, not a VIVE end-to-end figure.

Backbone choice was forced by two real constraints, both verified rather than
assumed:

- MuRIL is the better Indic backbone but ships only a `.bin` checkpoint, which
  transformers refuses to `torch.load` on torch < 2.6 (CVE-2025-32434).
- XLM-RoBERTa base ships safetensors but its AdamW optimizer states exhaust the
  4 GB development GPU — confirmed by an actual OOM.

A Colab notebook (`models/notebooks/`) runs either backbone on cloud GPU.

### Coverage gaps that bound every claim

| Gap | Effect |
|---|---|
| 5 of 12 intents have no training data | `PASSWORD_REQUEST`, `CARD_DETAILS_REQUEST`, `ACCOUNT_CHANGE_REQUEST`, `REMOTE_ACCESS_REQUEST` and `CONFIDENTIAL_INFORMATION` **cannot be predicted** |
| 2 of 8 behaviours have no label source | `THREAT` and `SECRECY` are not trained |
| `OTP_REQUEST` has 103 samples (~0.1%) | The highest-value intent is the worst-supported |
| No Tamil text (`BLOCKERS.md` O8, O11) | Tamil **ASR works** (WER 0.2833), but the text corpus has **0 Tamil records and 0 Tamil codepoints**, so Tamil intent/behaviour is **not supported**. Transcribing Tamil is not understanding it |
| Corpus is SMS, not call transcripts | Register differs from speech; transfer is unvalidated |

### Evaluation splits

`scripts/training/build_eval_splits.py` builds 6 splits, records 7 as
**blocked**, each with a reason and blocker id, rather than omitting them:
generator-disjoint, codec/noise robustness, speaker-disjoint, Hindi and Tamil
Tamil ASR, Tamil text, synthetic-but-legitimate, and the human-curated
benchmark slice — and marks 1 (`asr_hindi`) as **measured externally**, against
FLEURS rather than this corpus. A blocked split is never reported as passed,
and an externally measured one is never credited to the corpus.

A split is also blocked when it is merely *too small*: `MIN_EVAL_RECORDS = 30`.
`benchmark_ground_truth` has 1 held-out record, so it is reported as blocked
rather than built — a per-class F1 over one record is noise, not a measurement.

## 10. Known limitations

Documented in `BLOCKERS.md` and stated to any evaluator:

- Unknown/future generators are out of distribution; detection is not universal.
- `ecapa-tdnn` is inert without an enrolled reference — status `NO_REFERENCE`.
- ASR quality varies by language, accent, code-switching and channel.
- Fusion weights for the current build are expert-set, not learned from a large
  labelled corpus; calibration is provisional.
- Cellular audio is inaccessible by platform design (`ARCHITECTURE.md` §7).
