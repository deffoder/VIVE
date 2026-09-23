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

VIVE supports dual deployment modes:

### 1. On-Device Phone-Only Mode (Primary Production Target)

```text
Android Native App (Kotlin + Jetpack Compose)
  │
  ├── Audio Capture & Signal Processing (16 kHz PCM, AudioPreprocessor)
  ├── On-Device ML Inference (ONNX Runtime Mobile, arm64-v8a)
  │     ├── Silero VAD v5 (Speech gating)
  │     ├── Vakyansh Multilingual ASR (Hindi, Tamil, Indian English)
  │     ├── ECAPA-TDNN (Speaker verification against enrolled voice profile)
  │     └── Fine-tuned MiniLM / DistilBERT (Semantic intent classification)
  ├── Sensitive Request Rule Engine (Deterministic regex/keyword matching)
  ├── Local Multi-Factor Risk Fusion & Decision Engine (0–100 ordinal score)
  ├── On-Device Session Persistence (SQLite `vive_sessions.db`)
  ├── System Heads-Up Notifications (`NotificationManager` risk channels)
  └── Telephony Metadata Screening (`CallScreeningService`)
```

The on-device phone-only engine operates entirely locally on Android handsets without any backend server, Python runtime, or adb bridge dependencies.

### 2. Client-Server Backend Mode (Benchmarking & Development)

```text
Android (Kotlin + Jetpack Compose)
        │  REST + WebSocket
        ▼
FastAPI backend (Python 3.11)
        │  model-service interfaces
        ▼
Model adapters (mock → real)
```

| Decision | Implementation |
|---|---|
| Primary Deployment | Standalone Android App (On-device ONNX Runtime Mobile, arm64-v8a) |
| Backend Mode | FastAPI, Python 3.11 (REST + WebSocket) for evaluation and dev |
| Audio Input | Authorized microphone / in-app audio stream |
| Telephony Screening | Android `CallScreeningService` (incoming caller ID & metadata screening) |
| On-device Models | Silero VAD v5, Vakyansh ASR (hi/ta/en), ECAPA-TDNN, DistilBERT/MiniLM |
| Session Persistence | SQLite database (`vive_sessions.db`) |
| UI Framework | Native Android — Kotlin + Jetpack Compose (Material 3) |
| React Native / Web | Not used |

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

**Phone-only on-device standalone engine + client-server backend mode.**
VIVE executes complete voice integrity verification and social-engineering risk analysis directly on physical Android hardware (verified on OnePlus CPH2661, Android 16, ARM64) without backend or network dependencies:

### 1. On-Device Model Stack (Android Standalone)

| Component | Model / Engine | Format / Size | Measured Device Latency / Metric | Licence |
|---|---|---|---|---|
| ASR (Hindi) | `vakyansh-wav2vec2-hindi-him-4200` | ONNX fp32 (377.8 MB) | 290 ms per 2s audio window | MIT |
| ASR (Tamil) | `vakyansh-wav2vec2-tamil-tam-250` | ONNX fp32 (377.8 MB) | 161 ms per 2s window (WER 0.4240) | MIT |
| ASR (Indian English) | `vakyansh-wav2vec2-indian-english-enm-700` | ONNX fp32 (377.8 MB) | 276.5 ms per 2s window (100% security keyword hit) | MIT |
| Speaker Verification | ECAPA-TDNN | ONNX fp32 (24.7 MB) | 192-dim vector (100% genuine accept / 100% impostor reject) | Apache-2.0 |
| Voice Activity Detection | Silero VAD v5 | ONNX fp32 (1.8 MB) | Gating active speech segments | MIT |
| Intent Classification | Fine-tuned MiniLM / DistilBERT | ONNX fp32 (133.5 MB) | Hindi/English scam categorization (`UNKNOWN` for Tamil) | Apache-2.0 |
| Sensitive Request Engine | Regex / Deterministic Rule Engine | JSON compiled rules | 0 / 1,200 false positives (0.00%) on spoken FLEURS | Proprietary/VIVE |
| Anti-Spoofing | AASIST | ONNX | Excluded from risk score (`validated=false`, EER 0.72) | MIT |

### 2. Client-Server Backend Stack (Evaluation & Development)

| Analyzer | Model | Licence |
|---|---|---|
| ASR | `ai4bharat/indic-conformer-600m-multilingual` (CTC) | MIT |
| Intent | fine-tuned multilingual DistilBERT | Apache-2.0 |
| Behaviour | fine-tuned multilingual DistilBERT | Apache-2.0 |
| VAD | Silero VAD v5 | MIT |
| Anti-spoofing | AASIST (unvalidated, zero-weighted) | MIT |
| Speaker | ECAPA-TDNN | Apache-2.0 |

**311 automated tests pass** (173 backend pytest, 138 Android unit tests), plus on-device instrumented tests (`ModelsDeviceEvalTest`, `AsrDeviceEvalTest`), a 15-case end-to-end matrix, and live device call acceptance verification.

### What is NOT claimed

- **No two-way cellular call audio interception.** Android platform security forbids third-party apps from intercepting raw cellular voice call audio. VIVE provides metadata screening via `CallScreeningService` for incoming cellular calls; full voice analysis operates over authorized microphone or VoIP/in-app audio streams (`ARCHITECTURE.md` §7).
- **No synthetic-voice detection capability on telephone audio.** AASIST exhibits target-domain acoustic failure (EER 0.72) when evaluating acoustic phone audio. Anti-spoofing is marked `validated=false`, reported as `UNAVAILABLE` or inconclusive in the UI, and completely zero-weighted in composite risk calculation (`EVALUATION.md` §5).
- **Tamil is transcribed, not semantically classified.** Tamil ASR is validated (WER 0.4240 on device); Tamil semantic analysis intentionally returns `UNSUPPORTED_LANGUAGE` (`UNKNOWN`) with a confidence penalty, strictly avoiding hallucinated risk (`BLOCKERS.md` O11).
- **Risk score is ordinal, not a calibrated probability.** Expected calibration error is 0.3171. A score of 74 denotes "higher risk than 40", never "74% probability of scam" (`EVALUATION.md` §9).
- **Acoustic over-the-air playback degradation.** Direct digital audio achieves 100% keyword detection; loudspeaker-to-microphone playback experiences acoustic room reverberation and distance attenuation.
- **No overall end-to-end VIVE accuracy figure.** Measurements are reported per-component against concrete proxy datasets (FLEURS, synthetic sequences); fabricating a single blanket accuracy metric is strictly avoided.
- **Single-session runtime.** Benchmarks reflect single-session performance on target OnePlus CPH2661 (idle PSS 125 MB, peak call PSS 850–926 MB).

Security, test and demo-readiness reports: [`docs/PHASE6_REPORTS.md`](docs/PHASE6_REPORTS.md).
Mobile on-device implementation & acceptance: [`docs/AUTONOMOUS_PROGRESS.md`](docs/AUTONOMOUS_PROGRESS.md).
Open decisions and limitations: [`docs/BLOCKERS.md`](docs/BLOCKERS.md).
Evaluation details: [`docs/EVALUATION.md`](docs/EVALUATION.md).

## Platform limitation

Ordinary cellular call audio is not accessible to a third-party Android app.
Cellular calls are screened via `CallScreeningService` (number and metadata
only); full analysis requires the authorized VoIP/in-app audio path. The product
does not claim otherwise. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §7.
