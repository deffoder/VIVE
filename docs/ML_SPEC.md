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
| Languages | 22 (IN-22), including `hi` and `ta`. **No English** - see `BLOCKERS.md` O16 |
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

## 2.3 Phase 8A — real ASR integrated

The selected model now runs **inside the backend** behind the existing
`AsrAdapter` protocol (`backend/app/adapters/real/asr_conformer.py`).

| Property | Value |
|---|---|
| Adapter | `IndicConformerAsrAdapter`, CTC path |
| Mode | `REAL` |
| Execution provider | `CPUExecutionProvider` |
| Languages loaded | 22 |
| Load time | 25419 ms (includes a warm-up inference) |
| Process RSS | 2.503 GB |

**Verified on real speech** (`google/fleurs`, CC-BY-4.0, first 2.0 s of each
clip — `models/evaluation/asr_integration_8a.json`):

| Language | Packets | Transcribed | Median packet latency | Within 1.0 s cadence |
|---|---:|---:|---:|---|
| Hindi | 8 | 8 | **326 ms** | yes |
| Tamil | 8 | 7 | **494.5 ms** | yes |

One Tamil clip returned `INSUFFICIENT_AUDIO` rather than an empty string,
which is the intended behaviour: the adapter reports a status instead of
emitting a transcript it did not produce.

### What these latency numbers are

Integrated adapter cost on **real** audio, including pcm_s16le decoding and the
`AudioWindow` envelope. They are **not** the Phase 7 standalone figure
(0.2549 s on synthetic audio, bypassing the adapter) and **not** end-to-end
pipeline latency, which Phase 8D measures. The three are reported separately.

### Warm-up

`load()` runs one throwaway inference. onnxruntime resolves kernels and
allocates arenas on the **first** run, not at session creation: measured, the
first packet cost ~8.7 s against a ~0.32 s steady state, which would have blown
the cadence at the start of every session. Paying it once at load removes the
spike — a direct post-load profile then shows 273-328 ms with no first-call
outlier.

### Failure states, and no silent downgrade

`AnalyzerStatus` gained `LOAD_ERROR` and `INFERENCE_ERROR`. A real adapter that
cannot load **stays in REAL mode** reporting `LOAD_ERROR`; it is never replaced
by its mock counterpart, because output that looks identical whether or not the
model loaded cannot be distinguished from a fabricated result. Mock adapters
remain available and are still the default (`adapter_mode=mock`).

### Still mock after 8A

VAD, anti-spoofing, speaker, intent and behaviour remain mock and report
`mode: mock`. A partially real bundle is represented honestly rather than
advertised as fully real.

### Not claimed

Producing a transcript proves **integration**, not accuracy. WER and CER come
only from the Phase 7 FLEURS evaluation, which is clean read speech and
therefore a floor, not telephone accuracy. Tamil **transcription** works; Tamil
**intent and behaviour** remain unsupported (`BLOCKERS.md` O11).

## 2.4 Phase 8B — real intent and behaviour integrated

Both Phase 7 checkpoints now run in the backend behind the existing adapter
protocols (`backend/app/adapters/real/text_classifiers.py`).

| | intent | behaviour |
|---|---|---|
| Model version | `intent-classifier-distilbert-v1` | `behavior-classifier-distilbert-v1` |
| Head | single-label softmax, 12 labels | multi-label sigmoid, 8 labels, threshold 0.5 |
| `max_length` | 96 | 96 |
| Mode | `REAL` | `REAL` |

`max_length` and the 0.5 threshold match Phase 7 training exactly, so the
training report describes this code path rather than a near variant.

### Label safety — the checkpoints are now self-describing

The Phase 7 checkpoints saved generic `LABEL_0..LABEL_11`: they did **not**
carry their own label mapping, so index-to-label depended entirely on an
external file staying in the same order. A silent reordering would have
produced confident predictions for the **wrong** labels.

Fixed in two steps. The real VIVE taxonomy was written into each checkpoint's
`config.json` (`id2label`/`label2id`), verified first against the training
report's recorded label order; and `load()` now validates that mapping against
the live taxonomy and **refuses to load on any mismatch** — wrong order, wrong
count, missing mapping, or an unrecognised label name. No label is ever coerced
onto a "nearest" VIVE label. Tests cover each refusal.

### Language policy

Supported: `en`, `hi`, `hi-en` — the languages actually present in the training
corpus. Anything else returns **`UNSUPPORTED_LANGUAGE`**, a new
`AnalyzerStatus` that is distinct from an error: the pipeline is working and
the honest answer is "cannot say".

Tamil is the live case. Tamil ASR is validated, so a Tamil transcript reaches
these heads, but the corpus held **0 Tamil records and 0 Tamil codepoints**
(`BLOCKERS.md` O11). The mock adapters honour the same rule, so a demo cannot
show Tamil understanding that production lacks.

### A demo scenario that was overstating the product

`DEMO_SPEC` scenario **S3** was written in romanised Tamil, so it was
demonstrating Tamil scam detection VIVE cannot perform. It has been moved to
Hindi — keeping its actual purpose, synthetic-voice escalation — and a new
scenario **S11** asserts the honest Tamil path: transcript `AVAILABLE`, intent
and behaviour `UNSUPPORTED_LANGUAGE`, and risk that does not reach `CRITICAL`
on text evidence the model never produced.

### Limitations carried forward, not hidden

- `OTP_REQUEST` had **8 test records**: unmeasurable, not "63% accurate".
- 5 intents and 2 behaviours have no training data and can never be emitted.
  A test asserts `THREAT` and `SECRECY` never fire.
- Intent is **100% collinear** with the corpus scam flag (O10), so the intent
  head partly measures scam/not-scam rather than intent discrimination.
- Reported `confidence` is a decoder output, **not** a calibrated probability
  and never a fraud probability. Calibration is Phase 9.

## 2.5 Phase 8C — real audio models integrated

| Model | Licence | Version | Status |
|---|---|---|---|
| Silero VAD | MIT | `silero-vad-v5-jit` | **Real**, local TorchScript, no runtime download |
| AASIST | MIT | `aasist-pretrained-v1` | **Real**, forward pass now possible (see below) |
| ECAPA-TDNN | Apache-2.0 | `ecapa-tdnn-voxceleb-v1` | **Real**, 192-dim embedding |

### AASIST: the Phase 7 limitation is resolved

Phase 7 recorded "checkpoint loads, model class not vendored, so no forward
pass". The published AASIST release ships **weights only**. The MIT-licensed
model definition is now vendored under
`backend/app/adapters/real/vendor/aasist_model.py` with its licence text, and
the checkpoint loads into it with **0 missing and 0 unexpected keys**.

### Verified on real speech (FLEURS `hi_in`)

| Input | VAD | quality |
|---|---|---|
| 4 genuine speech clips | `has_speech=True` on all 4 | GOOD / DEGRADED |
| digital silence | `has_speech=False` | `NO_SPEECH` |

Speaker: identical audio scores similarity **1.0**, a different clip scores
**0.2222**, and with no enrolled reference the adapter returns
`NO_REFERENCE` with `similarity=None` rather than inventing a comparison.

### AASIST does NOT behave correctly out of domain (`BLOCKERS.md` O12)

The same spot check found the anti-spoofing model scoring **2 of 3 genuine
human clips as likely synthetic** (P(spoof) 0.8377 and 0.9994), and scoring
**digital silence as bonafide** (0.9885). The class-index convention was
verified against upstream, so this is the model's behaviour and not a wiring
error: AASIST was trained on ASVspoof2019 LA and FLEURS is a different
recording domain.

Four samples is a **spot check, not a measurement**. It is not an EER and not
a false-positive rate, and must never be quoted as either. VIVE has measured
**no EER of its own** because no anti-spoofing corpus was acquired (O5).

**No synthetic-voice detection capability may be claimed.** The existing
`SYNTHETIC_ONLY_CEILING` in fusion limits how far a synthetic score alone can
drive risk, which bounds the impact; calibrating or replacing the model is
Phase 9 work.

### What the audio models are not

- VAD decides speech vs silence and drives quality. `NO_SPEECH` and `POOR`
  suppress downstream analyzers and lower confidence; they never raise risk.
- An AASIST score is evidence of **synthesis**, not a probability of fraud.
  Synthetic speech is not fraud and human speech is not safety (P3).
- `NO_REFERENCE` is **not** a speaker mismatch. There is no enrolment source
  (O3), so speaker consistency is unavailable rather than negative.

## 2.6 Phase 8D — full real ML pipeline

Real audio now flows through the complete backend: session, WebSocket, all six
real adapters, fusion, temporal risk, policy and back out as packets. Verified
by `scripts/verify_pipeline_e2e.py`
(`models/evaluation/pipeline_e2e_8d.json`).

| | Hindi | Tamil |
|---|---|---|
| Packets produced | 6 | 6 |
| `adapter_mode` | `real` | `real` |
| Decoded language | `hi` | `ta` |
| ASR | `AVAILABLE` | `AVAILABLE` |
| Intent / behaviour | `AVAILABLE` | **`UNSUPPORTED_LANGUAGE`** |
| Risk | 57 MEDIUM, confidence 0.8998 | 58 MEDIUM, confidence **0.4716** |

The Tamil column is the one to read. Tamil transcribes, both text heads
decline, and **confidence halves while risk does not rise** — missing evidence
lowers confidence rather than becoming incriminating evidence
(`PROJECT_SPEC.md` §2). All packet fields are present in both languages, so
traceability survives a partially unavailable analyzer set.

### A real defect this found: every session decoded in one language

The ASR adapter fell back to its configured default for every packet, because
the session's language never reached it. Measured consequence: a **Tamil
session was transcribed as Hindi**, and because the packet then carried
`language: hi`, the text heads *ran* instead of declining — silently defeating
the O11 protection end to end.

`AudioWindow` now carries `language`, populated from the session, and three
regression tests guard it. There is still **no language-identification model**
(`PHASE8_PREREQUISITES.md` §6): a session that declares nothing decodes in the
adapter default, which is a documented gap, not a silent one.

### Latency: at the budget, not inside it (`BLOCKERS.md` O13)

Median packet cost across runs: **830-1197 ms** against a **1.0 s** budget.
Some runs fit, some do not. Per stage: AASIST ~364-395 ms, ASR ~254-273 ms,
ECAPA ~68-87 ms, plus VAD, both text heads, fusion and transport. The first
packet of a session costs ~10-32 s of setup.

**Near-real-time operation is not claimed as demonstrated on this hardware.**

An optimisation was tried and **measured rather than assumed**: running the
four window analyzers on a thread pool made things *worse* (Hindi
938 → 1197 ms; ASR 273 → 584 ms, AASIST 395 → 741 ms, ECAPA 81 → 732 ms),
because torch and onnxruntime each already use every core, so concurrent
analyzers contend rather than overlap. It was reverted, and the measurement is
recorded in `session_manager.py` so the next person does not repeat it.

### Risk fusion untouched

Fusion, temporal risk and policy are exactly as they were; only the evidence
feeding them changed from mock to real. Fusion weights remain expert-set and
provisional (O6), intent and behaviour remain collinear in the training data
(O10), and **no calibrated fraud probability is claimed**. Phase 9 owns
calibration.

## 2.7 AASIST windowing — investigated, defect found and fixed

**Question:** was the adapter's tiling of a 2.0 s window up to AASIST's
64,600-sample input inflating spoof scores?

**Answer: no — but the investigation found a worse problem.**

### Design

Comparing a tiled 2 s window against a native 4.04 s window changes both the
preprocessing *and* the audio, so it proves nothing. The experiment instead
holds content fixed: the **same** 2 s segment extended to 64,600 samples four
ways, so any difference is caused by the extension alone.
`scripts/experiment_aasist_tiling.py`, 12 FLEURS clips.

| Extension | Median spoof score |
|---|---:|
| `zero_pad` | 0.2738 |
| **`tile` (what the adapter did)** | **0.5675** |
| `edge_pad` | 0.8519 |
| `reflect_pad` | 0.8563 |

### Tiling was not the problem

Tiling scored **lower** than two of the three alternatives (median
tile − reflect_pad = -0.0221) and produced the highest score on only
**3 of 12** clips. Splice
discontinuity at the repeat boundary was ~0.008, far too small to be the
mechanism. No resampling is performed anywhere: the audio is already 16 kHz.

### The actual defect

**Per-clip spread across extension methods: median 0.4298, max
0.8872** on a 0–1 scale. One clip moved from 0.0317 to 0.8056 on
*identical* audio.

The cause is structural. AASIST scores the whole 64,600-sample window, and a
2 s VIVE window fills barely half of it, so **half of every input was filler
the adapter invented**. The adapter was not asking "is this speech synthetic";
it was asking "is this speech plus 2 s of my own padding synthetic". No choice
of padding fixes that — which is why the tiling-versus-alternatives comparison
came out roughly even.

### Fix

The adapter no longer pads. It keeps a **rolling buffer of recent real audio
per session**, appends only the new portion of each overlapping window, and
runs the model only once it holds a full genuine 64,600-sample window. Until
then it reports `INSUFFICIENT_AUDIO` — an honest "not yet" instead of a score
decided by filler.

Buffers are bounded (`AASIST_MAX_SESSIONS`), isolated per session, and
released when a session ends or is deleted, because they hold caller speech
(`SECURITY_SPEC.md` §4).

**Consequence:** anti-spoofing now begins ~4 s into a call rather than at the
first packet. That is the correct trade: a late honest score beats an
immediate meaningless one.

### What this does and does not establish

It measures **sensitivity to input preparation**, on 12 clips of one
corpus. It is **not** an EER, not a false-positive rate, and says nothing about
detection accuracy. O12 stands unchanged: AASIST still has no VIVE-measured
EER, and still scored genuine human speech as synthetic on the earlier
native-length spot check — that finding used full 64,600-sample windows with no
padding at all, so this fix does not explain it away.

## 2.8 Phase 9 — evaluation, calibration and robustness

Full report: `docs/EVALUATION.md`. Records: `models/evaluation/phase9/`.
This section carries only what changes how a model may be described.

### AASIST: no measured discrimination

The early-window study asked whether anti-spoof evidence could arrive before
~4 s. It answered a larger question instead. Against a two-class probe — 60
SpeechT5+HiFiGAN clips (MIT) against 60 FLEURS bonafide clips — AASIST scores
at **chance at every window length**:

| Window | EER | 90% interval | AUC |
|---|---:|---|---:|
| 1.0 s | 0.4500 | 0.3667–0.5500 | 0.4875 |
| 2.0 s | 0.4500 | 0.3833–0.5500 | 0.5039 |
| 3.0 s | 0.4167 | 0.3583–0.5000 | 0.5317 |
| 4.0 s | 0.4333 | 0.3500–0.5000 | 0.5592 |
| 4.0375 s (native) | **0.4333** | **0.3500–0.5000** | **0.5600** |

Every interval reaches or crosses 0.50. A Silero VAD control confirms the
synthetic half is speech (20/20 clips, GOOD quality), so this is a fact about
the model rather than about broken audio; reversing the class-index convention
gives AUC 0.4400, also chance.

Architecturally, shorter windows need no adapter change at all: AASIST pools
over time before its classifier, so it accepts variable-length input natively.
No padding, tiling or resampling was used anywhere in the study — the Phase 8
rule holds.

**Consequence for this spec:** the anti-spoof channel has no measured
capability and must not be presented as synthetic-voice evidence
(`BLOCKERS.md` O12). Fusion weights were **not** changed on the strength of
one synthesis family; that needs a real corpus (O5).

### Risk score: measured not to be a probability

Expected calibration error **0.3171** over 8,022 de-leaked held-out records.
Records scoring 0.2–0.3 are scams 96.4% of the time. `PROJECT_SPEC.md` §2.1's
prohibition on reading `risk.score` as a fraud probability is now an empirical
finding. The score is a well-separating **ordinal** signal, not a likelihood.

### ASR: channel is cheap, the window is not

Clean Hindi WER 0.1141 / Tamil 0.2936 on 40 FLEURS utterances each. Telephony
band-limiting costs Hindi 0.1141 → 0.1340; μ-law and narrowband are nearly
free; additive noise is the harsher axis (Tamil 0.2936 → 0.3994 at SNR 5).
Every degradation is **simulated** — no telephone-call WER exists for VIVE.

### ECAPA: measured for the first time

EER **0.0000** on clean LibriSpeech (25 speakers), **0.0150** on VIVE's 2 s
window. The window barely moves the ranking (AUC 0.9980) but moves the
operating point sharply: a fixed threshold of 0.5 would falsely reject
**29.33%** of genuine 2 s windows. In production the channel still contributes
nothing, because there is no enrolment source (O3).

### A fusion defect found by failure injection

Intent entered the noisy-OR unconditionally, so a head that had never run
contributed `UNKNOWN`'s 0.10 — double a benign `NORMAL_CONVERSATION`'s 0.05. A
model outage therefore **raised** risk (26 → 28), the score stopped
reconciling with `contributions`, confidence did not fall, and every Tamil
packet — always `UNSUPPORTED_LANGUAGE` by design (O11) — was scored higher than
an identical Hindi one. Fixed: intent enters the noisy-OR only when its status
is `AVAILABLE`. Verified after the fix, `text_heads_failed` 28 → 26 with
confidence 0.960 → 0.900, and no failure configuration raises risk.

### Per-stage cost, now complete

`IntentEvidence` and `BehaviorEvidence` carried no `inference_ms`, so two of
six analyzers were invisible in every latency breakdown. Added as an additive
optional field (`API_SPEC.md` §4.1). Measured medians: aasist 366.0 ms, asr
265.0 ms, ecapa 74.0 ms, intent 65.5 ms, behaviour 41.5 ms — 812 ms of an
844 ms packet, leaving ~32 ms for fusion, temporal risk, policy and transport.

AASIST is ~45% of the packet budget and is the stage with no measured
discrimination.

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

**Both figures are measured on SMS text, and neither transfers to speech.**
Phase L scored the same intent head on conversational telephone speech and
found it firing on 3.40% of legitimate calls against 0.60% of scam calls -
inverted (`BLOCKERS.md` O18). These numbers describe the register they were
measured on and must never be quoted as call-analysis accuracy.

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
