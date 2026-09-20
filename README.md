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

[`CLAUDE.md`](CLAUDE.md) is the highest-priority project instruction. Where any
document disagrees with it, `CLAUDE.md` wins.

## Current status

**Architecture phase.** The directory structure and the ten specifications are in
place. No application code has been written; `android/` and `backend/` are empty.

No dataset has been downloaded and no model has been trained.

Phase-by-phase status:
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
Open decisions and limitations: [`docs/BLOCKERS.md`](docs/BLOCKERS.md).

## Future ML phase

Real ML integration is deliberately the **last** major phase. The product must
run end-to-end on mock adapters first, so that UI, transport and fusion defects
are never confused with model defects.

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
