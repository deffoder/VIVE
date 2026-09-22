# VIVE — Voice Integrity Verification Engine

Real-time voice integrity verification and social-engineering risk analysis for
**authorized** voice communication.

VIVE analyses a live audio stream and continuously produces a risk score, a
separate confidence value, and packet-level forensic evidence that a human can
inspect and audit.

The score is **ordinal, not a probability.** Phase 9 measured its expected
calibration error at 0.3171, so "risk 78" means "more concerning than 40",
never "78% chance of fraud" ([`docs/EVALUATION.md`](docs/EVALUATION.md) §9).

> **VIVE is decision support.** It does not transfer money, retrieve
> credentials, bypass authentication or make banking decisions. Synthetic speech
> is not automatically fraud, and a genuine human voice is not automatically
> safe. See [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) §2.

## Architecture

```text
Android (Kotlin + Jetpack Compose)
        │  REST + WebSocket
        ▼
FastAPI backend
        │  model-service interfaces
        ▼
Model adapters (mock → real)
```

The Android app never runs inference. All models execute behind backend
interfaces, so mock and real adapters are interchangeable without touching
transport, fusion or UI.

| Decision | |
|---|---|
| Frontend | Native Android — Kotlin + Jetpack Compose (Material 3) |
| Backend | FastAPI, Python 3.11 |
| Real-time transport | WebSocket |
| On-device ML | None |
| React Native / web frontend | Not used |

## Repository

```text
android/    native Android application
backend/    FastAPI service
models/     interfaces, adapters, configs, training, evaluation, artifacts
data/       corpora (git-ignored) and manifests (tracked)
tests/      android · backend · integration · e2e
scripts/    setup · development · testing · training
design/     UI references — 02 is primary
docs/       specifications
```

## Setup

Nothing below downloads a model or a dataset. The ML phase is last
([`docs/ML_SPEC.md`](docs/ML_SPEC.md) §8).

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | Backend |
| JDK | 17 | Android build (Android Studio bundles one) |
| Android SDK | API 34+ | Platform + build-tools |
| Android Studio | Recent stable | Recommended for the app module |

Verify what is already on this machine:

```bash
python --version && java -version && echo $ANDROID_HOME
```

### Backend

```bash
cd backend && python -m venv .venv && . .venv/Scripts/activate && pip install -e ".[dev]"
```

On macOS or Linux the activate path is `.venv/bin/activate`.

### Android

Open `android/` in Android Studio and let it sync, or build from the command
line. Point the app at the backend by setting the base URL in
`android/local.properties` (git-ignored):

```
VIVE_API_BASE_URL=http://10.0.2.2:8000
```

`10.0.2.2` is the host machine as seen from the Android emulator.

## Development commands

These are the intended entry points. Commands whose module does not exist yet
will not run until the phase that creates it
([`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)).

### Backend — mock mode (default)

Deterministic, no weights needed. This is what the demo scenarios are
specified against.

```bash
uvicorn app.main:app --reload --port 8000
```

### Backend — real mode

Every `VIVE_*_MODEL_DIR` must point at a checkpoint directory; see
`backend/.env.example`. An adapter that cannot load reports `LOAD_ERROR` and
**stays** in real mode — the bundle never silently downgrades to mock.

```bash
VIVE_ADAPTER_MODE=real uvicorn app.main:app --port 8000
```

### Backend tests

Run per-file on a memory-constrained machine. Loading every real model in one
process needs more RAM than a 8 GB laptop has spare, and a concurrent full-run
was observed to exhaust it. This is a test-host limitation, not a product one.

```bash
pytest tests/test_pipeline.py -q
```

Do **not** set `VIVE_ADAPTER_MODE=real` for the suite: the API tests assert the
default mock bundle. The real-model tests activate from the
`VIVE_*_MODEL_DIR` variables alone and skip when those are unset.

### Android

```bash
./gradlew assembleDebug
```

```bash
./gradlew testDebugUnitTest
```

### Checks

```bash
curl -s localhost:8000/ready
```

`/ready` reports each adapter's status and whether it is running in `mock` or
`real` mode — the same value the app surfaces in its UI.

The end-to-end matrix runs every demo scenario through the real backend and
records expected against actual for each case:

```bash
python scripts/evaluation/e2e_matrix.py
```

Documentation and measurement integrity are themselves checked, so a figure
cited without its scope fails rather than shipping:

```bash
python scripts/evaluation/check_phase9_integrity.py
```

## Documentation

Start with [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md), then
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Document | Covers |
|---|---|
| [`PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) | Scope, taxonomies, claims discipline |
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, data flow, layout |
| [`UI_SPEC.md`](docs/UI_SPEC.md) | Design system, screens, components, states |
| [`API_SPEC.md`](docs/API_SPEC.md) | REST + WebSocket contract and schemas |
| [`ML_SPEC.md`](docs/ML_SPEC.md) | Model stack, adapters, fusion, training |
| [`DATA_SPEC.md`](docs/DATA_SPEC.md) | Datasets, manifests, provenance, splits |
| [`SECURITY_SPEC.md`](docs/SECURITY_SPEC.md) | Auth, privacy, retention, threats |
| [`DEMO_SPEC.md`](docs/DEMO_SPEC.md) | Scenarios and acceptance |
| [`IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Phases and exit criteria |
| [`BLOCKERS.md`](docs/BLOCKERS.md) | Open decisions, deferrals, limitations |
| [`EVALUATION.md`](docs/EVALUATION.md) | Measured results, what may and may not be claimed |
| [`PHASE6_REPORTS.md`](docs/PHASE6_REPORTS.md) | Security, test and demo-readiness reports |

[`CLAUDE.md`](CLAUDE.md) is the highest-priority project instruction. Where any
document disagrees with it, `CLAUDE.md` wins.

## Current status

**End-to-end pipeline running on REAL models (Phase 8 complete).** The Android
app drives a FastAPI backend over REST and WebSocket, and in `real` mode all
six analyzers are checkpoint-backed:

| Analyzer | Model | Licence |
|---|---|---|
| ASR | `ai4bharat/indic-conformer-600m-multilingual` (CTC) | MIT |
| Intent | fine-tuned multilingual DistilBERT | Apache-2.0 |
| Behaviour | fine-tuned multilingual DistilBERT | Apache-2.0 |
| VAD | Silero VAD v5 | MIT |
| Anti-spoofing | AASIST | MIT |
| Speaker | ECAPA-TDNN | Apache-2.0 |

**260 tests pass** (171 backend, 89 Android), plus a 15-case end-to-end
matrix. Mock adapters are retained and remain the default, so demos stay
deterministic without multi-GB weights present. Model weights live outside Git.

Phase 9 evaluated every component and Phase 10 reconciled the product with
what it found. The full evaluation report, including the results that were
unfavourable, is [`docs/EVALUATION.md`](docs/EVALUATION.md).

### What is NOT claimed

- **No overall VIVE accuracy figure exists.** There is no labelled corpus of
  real calls, so every metric is measured on a proxy - clean read speech, an
  SMS corpus, or synthetic sequences - and none is an end-to-end result
  (`BLOCKERS.md` O15).
- **No synthetic-voice detection capability.** Measured, not merely
  unmeasured: against the only two-class probe available, AASIST separates
  synthetic from genuine speech **at chance** - EER 0.4333 with a 90%
  interval of 0.3500–0.5000, which contains 0.50, at every window length
  tested (`EVALUATION.md` §5, O12). The UI reports the signal as
  inconclusive.
- **Risk is not a probability.** Expected calibration error 0.3171; records
  scoring 0.2–0.3 are scams 96.4% of the time. Fusion weights remain
  expert-set and provisional (O6).
- **Tamil is transcribed, not understood.** Tamil ASR is validated (WER
  0.2936 on clean read speech); Tamil intent and behaviour return
  `UNSUPPORTED_LANGUAGE` because the training corpus contains zero Tamil
  records (O11).
- **No guaranteed sub-second processing.** Steady-state median 751–844 ms
  against a 1000 ms budget, but p95 930–1069 ms, with 3.7–11.1% of packets
  overrunning on the measured hardware (O13).
- **No throughput or concurrency claim.** Never measured; all runtime figures
  are single-session.
- **No production alert threshold.** The policy threshold was not tuned,
  because the only labelled data available is an SMS proxy and fitting a
  production threshold to it would be a fabricated capability (O15).

Security, test and demo-readiness reports:
[`docs/PHASE6_REPORTS.md`](docs/PHASE6_REPORTS.md).
Phase 8 detail: [`docs/ML_SPEC.md`](docs/ML_SPEC.md) §2.3–2.6.

Phase-by-phase status:
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
Open decisions and limitations: [`docs/BLOCKERS.md`](docs/BLOCKERS.md).

## How the ML phases were sequenced

Real ML integration was deliberately sequenced last, so that UI, transport and
fusion defects could never be confused with model defects. That sequencing paid
off repeatedly: every defect found in Phases 8–10 was attributable to a
specific layer.

```text
Phase 7   data preparation and training
Phase 8   real model integration, one analyzer at a time
Phase 9   evaluation, calibration and robustness
Phase 10  final integration, product hardening, demo readiness
```

Two rules governed all of it. Adapters report `mock` or `real` and the app
shows which is active, so a demo can never be mistaken for production
inference. And **no metric is published that was not measured** — an unmeasured
figure is reported as absent rather than estimated.

That rule is why this README's limitations section is longer than its
capabilities section. Phase 9 set out to quantify the system and found, among
other things, that its anti-spoofing model does not discriminate and that its
risk score is not a probability. Both findings are recorded here rather than
softened, and both changed the product: the UI now reports the anti-spoof
signal as inconclusive, and the score is presented as ordinal.

Full detail: [`docs/EVALUATION.md`](docs/EVALUATION.md) and
[`docs/ML_SPEC.md`](docs/ML_SPEC.md) §2.1–2.8.

## Platform limitation

Ordinary cellular call audio is not accessible to a third-party Android app.
Cellular calls are screened via `CallScreeningService` (number and metadata
only); full analysis requires the authorized VoIP/in-app audio path. The product
does not claim otherwise. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §7.
