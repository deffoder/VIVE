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
| `indicconformer` | Multilingual ASR (hi/ta/en) | Per packet | transcript + confidence |
| `intent-classifier` | Intent over transcript | Per packet | 1 of 12 labels + confidence |
| `behavior-classifier` | Social-engineering behaviour | Per packet | 0..n of 8 labels + confidence |
| `risk-fusion` | Evidence to calibrated risk | Per packet | score, level, confidence, reasons |

Adapter keys used in `/ready` and configuration: `vad`, `antispoof`, `speaker`,
`asr`, `intent`, `behavior`.

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
silero-vad → aasist → ecapa-tdnn → indicconformer
           → intent-classifier → behavior-classifier → risk-fusion calibration
```

## 10. Known limitations

Documented in `BLOCKERS.md` and stated to any evaluator:

- Unknown/future generators are out of distribution; detection is not universal.
- `ecapa-tdnn` is inert without an enrolled reference — status `NO_REFERENCE`.
- ASR quality varies by language, accent, code-switching and channel.
- Fusion weights for the current build are expert-set, not learned from a large
  labelled corpus; calibration is provisional.
- Cellular audio is inaccessible by platform design (`ARCHITECTURE.md` §7).
