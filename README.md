# VIVE — Voice Integrity Verification Engine

Real-time voice integrity verification and social-engineering risk analysis for
**authorized** voice communication.

VIVE analyses a live audio stream and continuously produces a calibrated risk
score, a separate confidence value, and packet-level forensic evidence that a
human can inspect and audit.

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

### Backend

```bash
uvicorn app.main:app --reload --port 8000
```

```bash
pytest ../tests/backend -v
```

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

**241 tests pass** (157 backend with all real models loaded, 84 Android).
Mock adapters are retained and remain the default, so demos stay deterministic
without multi-GB weights present. Model weights live outside Git.

### What is NOT claimed

- **No overall VIVE accuracy figure exists.** Component metrics come from
  their own evaluations on clean read speech and an SMS corpus; neither is a
  call-channel or end-to-end result.
- **No synthetic-voice detection capability.** AASIST has no VIVE-measured
  EER, and on a spot check it scored genuine human speech as synthetic
  (`BLOCKERS.md` O12).
- **Tamil is transcribed, not understood.** Tamil ASR is validated; Tamil
  intent and behaviour return `UNSUPPORTED_LANGUAGE` because the training
  corpus contains zero Tamil records (O11).
- **Near-real-time is not demonstrated.** Median packet latency sits at the
  1.0 s budget rather than inside it, 830–1197 ms across runs (O13).
- **Risk is not a calibrated fraud probability.** Fusion weights are
  expert-set and provisional (O6); calibration is Phase 9.

Security, test and demo-readiness reports:
[`docs/PHASE6_REPORTS.md`](docs/PHASE6_REPORTS.md).
Phase 8 detail: [`docs/ML_SPEC.md`](docs/ML_SPEC.md) §2.3–2.6.

Phase-by-phase status:
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
Open decisions and limitations: [`docs/BLOCKERS.md`](docs/BLOCKERS.md).

## ML phase (done) and what comes next

Real ML integration was deliberately sequenced last, so that UI, transport and
fusion defects could never be confused with model defects. That sequencing paid
off: every defect found during Phase 8 was attributable to a specific layer.

Phase 9 owns evaluation, calibration and robustness — the questions Phase 8
deliberately did not answer.

The documented process — not yet executed — is:

```text
dataset preparation → preprocessing → cloud training → validation
→ evaluation → checkpoint/versioning → model integration
→ calibration → robustness testing
```

Training will run on **online GPU environments such as Kaggle or Google Colab**;
no local GPU is assumed. Model integration is strictly sequential, and after each
model the measured inference time and version are recorded before the next one
starts.

Two rules govern this phase. Adapters report `mock` or `real`, and the app shows
which is active — a demo can never be mistaken for production inference. And no
metric is published that was not measured: an unmeasured figure is reported as
absent rather than estimated.

Full detail: [`docs/ML_SPEC.md`](docs/ML_SPEC.md) §8.

## Platform limitation

Ordinary cellular call audio is not accessible to a third-party Android app.
Cellular calls are screened via `CallScreeningService` (number and metadata
only); full analysis requires the authorized VoIP/in-app audio path. The product
does not claim otherwise. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §7.
