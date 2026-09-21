# VIVE — Final Implementation Plan

**Project:** VIVE — Voice Integrity Verification Engine  
**Problem Statement:** SIH26104 — AI-Powered Real-Time Detection and Prevention of Voice Cloning Impersonation Attacks  
**Canonical Phase Numbering:** Phase 0 → Phase 10  
**Current Status:** Phases 0–6 complete; Phase 7 is next  
**Android:** Kotlin + Jetpack Compose  
**Backend:** FastAPI + WebSocket  
**Primary UI reference:** `design/02_vive_ui_reference.png`

---

## 1. Purpose

This is the **single canonical implementation roadmap for VIVE**. It defines the project-wide phase numbering, implementation objectives, acceptance criteria, testing expectations, Git checkpoints, ML transition, security boundaries, and the path from the current Phase 6 prototype to the final Phase 10 system.

If an older document uses another phase numbering scheme, **this document is the canonical numbering after reconciliation**.

---

## 2. Canonical Phase Numbering

| Phase | Name | Status |
|---|---|---|
| **0** | Repository & Specifications | COMPLETE |
| **1** | Android Foundation | COMPLETE |
| **2** | Complete Android UI | COMPLETE |
| **3** | FastAPI + WebSocket Backend | COMPLETE |
| **4** | Android ↔ Backend Integration | COMPLETE |
| **5** | Communication Integration | COMPLETE |
| **6** | Security, Privacy & Hardening | COMPLETE |
| **7** | Data Preparation + Cloud Training | **NEXT** |
| **8** | Real ML Integration | NOT STARTED |
| **9** | ML Evaluation, Calibration & Robustness | NOT STARTED |
| **10** | Final End-to-End Integration | NOT STARTED |

---

## 3. Current Verified State

### Completed commits

```text
6926316  Repo scaffold / Git root
0328ea8  Project instructions + blocker format
1dccf81  Final architecture + specifications
2aa728b  Android foundation
2353869  Complete Android UI
62b737c  FastAPI + WebSocket backend
f26254a  Android ↔ backend integration
84d0bc5  Communication integration
36fad4b  Security/privacy/resilience/demo hardening
```

Reported Phase 6 checkpoint:

```text
Working tree: CLEAN
Tests: 176
Failures: 0
```

---

## 4. What Is Real at Phase 6

Implemented and tested:

- Android application architecture;
- Jetpack Compose UI;
- all 24 screens;
- navigation and design system;
- FastAPI backend;
- REST APIs;
- WebSocket streaming;
- session lifecycle;
- packet/event model;
- overlapping 2-second windows with 1-second step;
- packet traceability;
- mock model-service interfaces;
- risk fusion;
- noisy-OR risk guard;
- temporal smoothing;
- escalation timing;
- policy engine;
- alerts;
- Android/backend real-time integration;
- backend-driven packet timeline/details/risk graph;
- `CallScreeningService` metadata-only cellular screening;
- authorized audio pipeline;
- audio capture abstraction;
- bounded ring buffer;
- packetization;
- authentication/authorization boundaries;
- session ownership;
- rate limiting;
- replay guard;
- audit events;
- HMAC webhook signatures;
- TLS-readiness boundary;
- log redaction;
- real session deletion;
- demo reset;
- resilience/failure handling;
- deterministic demo mode.

The application has been verified end to end on an emulator.

---

## 5. What Is Not Real Yet

**No real ML model runs inside VIVE at the Phase 6 checkpoint.**

The following are deterministic/demo analyzers:

- AASIST;
- ECAPA-TDNN;
- ASR;
- intent classifier;
- behaviour classifier;
- other ML evidence adapters.

Therefore there is currently:

- no ML accuracy claim;
- no anti-spoofing EER;
- no ASR WER;
- no intent F1;
- no speaker verification EER/FAR/FRR;
- no end-to-end fraud-risk accuracy.

These must remain unclaimed until controlled evaluation in Phase 9.

---

## 6. Permanent Architecture Principles

### Core pipeline

```text
Authorized Communication Source
        ↓
Secure Ingestion
        ↓
Session Manager
        ↓
Streaming Ring Buffer
        ↓
VAD / DSP / Audio Quality
        ↓
┌───────┬────────┬──────────┐
↓       ↓        ↓
AASIST ECAPA    Indic ASR
↓       ↓        ↓
Synthetic Speaker Transcript
Voice    │        │
         └────┬───┘
              ↓
       Intent + Behaviour
              ↓
         Context Engine
              ↓
       OOD / Uncertainty
              ↓
          Risk Fusion
              ↓
       Temporal Risk Engine
              ↓
         Policy Engine
              ↓
┌────────┬──────────┬──────────┐
↓        ↓          ↓
Android  Alerts     API/Webhook
Dashboard
```

### Risk rules

- Risk score and confidence are separate.
- Synthetic voice is not automatically fraud.
- Genuine human voice is not automatically safe.
- Missing evidence must not silently become safe evidence.
- Uncertainty must be represented.
- Risk is decision support, not proof of fraud.
- A risk score is not a probability unless properly calibrated.

### Cellular limitation

Do not claim unrestricted access to both sides of ordinary cellular-call audio.

Cellular path:

```text
CallScreeningService
→ supported call metadata
→ screening workflow
```

Full audio analysis:

```text
authorized VoIP / in-app / collaboration / prerecorded audio
```

### Banking boundary

VIVE does not independently:

- transfer money;
- freeze accounts;
- access private banking databases;
- retrieve credentials;
- bypass authentication;
- make unauthorized transaction decisions.

VIVE provides risk/policy information for authorized organizational workflows.

---

# PHASE 0 — REPOSITORY & SPECIFICATIONS

**Status:** COMPLETE

## Objective

Create the safe, isolated, documented VIVE repository and establish a single technical source of truth.

## Completed

- Git root corrected to `VIVE/`;
- parent-repository risk identified;
- `frontend/` removed;
- final project structure created;
- `CLAUDE.md` created;
- project specifications created;
- packet schema conflicts reconciled;
- blocker format established;
- architecture finalized.

## Required artifacts

```text
CLAUDE.md
README.md
docs/PROJECT_SPEC.md
docs/ARCHITECTURE.md
docs/UI_SPEC.md
docs/API_SPEC.md
docs/ML_SPEC.md
docs/DATA_SPEC.md
docs/SECURITY_SPEC.md
docs/DEMO_SPEC.md
docs/IMPLEMENTATION_PLAN.md
docs/BLOCKERS.md
```

## Acceptance

- repository isolated;
- specifications mutually consistent;
- Git clean;
- no accidental parent-repository tracking.

---

# PHASE 1 — ANDROID FOUNDATION

**Status:** COMPLETE  
**Commit:** `2aa728b`

## Objective

Create the Android application foundation without complete UI or real ML.

## Completed

- Gradle/AGP/Kotlin configuration;
- Compose foundation;
- package architecture;
- navigation;
- state architecture;
- typed data models;
- design tokens;
- repositories/interfaces;
- REST/WebSocket interfaces;
- logging/error boundaries;
- tests.

## Acceptance

- Android builds;
- emulator launches;
- navigation does not crash;
- architecture is ready for Phase 2.

---

# PHASE 2 — COMPLETE ANDROID UI

**Status:** COMPLETE  
**Commit:** `2353869`

## Objective

Implement the complete VIVE interface using the approved design system.

## Completed

All 24 specified screens and reusable components including:

- RiskGauge;
- PacketRow;
- RiskTimeline;
- ContributionBar;
- active-call analysis;
- packet detail;
- alerts;
- sessions;
- reports;
- settings;
- integrations;
- help;
- profile/about.

## Correctness fixes

1. Intent severity was incorrectly derived from classifier confidence.
2. Session current risk could drift from the latest packet.

Both were corrected.

## Acceptance

- all screens navigable;
- UI follows `UI_SPEC.md`;
- demo scenarios render;
- emulator verification passes.

---

# PHASE 3 — FASTAPI + WEBSOCKET BACKEND

**Status:** COMPLETE  
**Commit:** `62b737c`

## Objective

Create the backend contract consumed by Android and future ML services.

## Completed

- FastAPI;
- configuration;
- structured/redacted logging;
- structured errors;
- session manager;
- REST endpoints;
- WebSocket;
- heartbeat;
- reconnect-safe sequencing;
- mock model adapters;
- fusion;
- temporal risk;
- policy engine;
- in-memory store;
- webhook boundary;
- tests.

## Important fixes

### Keyword false match

Substring matching caused `"fir"` to match inside `"confirm"`. Token-aware matching replaced it.

### Fusion cancellation

A weighted average allowed low anti-spoof evidence to cancel high intent risk. Fusion was changed to noisy-OR-style risk combination with guard rails.

## Acceptance flow

```text
create session
→ WebSocket
→ packet
→ result
→ session query
→ event history
→ policy
→ webhook
→ disconnect
→ reconnect
```

---

# PHASE 4 — ANDROID ↔ BACKEND INTEGRATION

**Status:** COMPLETE  
**Commit:** `f26254a`

## Objective

Make Android consume real backend session/event state.

## Completed

- Retrofit;
- OkHttp WebSocket;
- DTO/domain separation;
- typed error mapping;
- backend-first repositories;
- controlled demo fallback;
- live WebSocket event processing;
- backend-driven packet timeline;
- backend-driven packet details;
- backend-driven risk graph.

## Live verification

On an emulator:

```text
backend sessions listed
packet count 5 → 7
P001–P007 rendered
backend-computed risk shown
packet detail matched backend
```

## Acceptance

- Android creates sessions;
- WebSocket works;
- backend events reach UI;
- packet data is traceable;
- reconnect/error handling works.

---

# PHASE 5 — COMMUNICATION INTEGRATION

**Status:** COMPLETE  
**Commit:** `84d0bc5`

## Objective

Provide supported phone-facing and authorized audio paths.

### Path A — Cellular

Uses:

```text
CallScreeningService
```

Characteristics:

- metadata only;
- role handling;
- no unrestricted cellular audio;
- no unsupported recording.

### Path B — Full authorized audio

Includes:

- audio-source abstraction;
- canonical 16 kHz format;
- VAD interface;
- bounded ring buffer;
- 2-second windows;
- 1-second step;
- measured audio-quality fields;
- deterministic demo source;
- binary WebSocket audio path.

## Verified

A generated 10-second demo audio stream produced 9 overlapping windows and reached the backend analysis pipeline.

## Acceptance

- screening path works;
- authorized audio path works;
- packetization works;
- ring buffer works;
- timestamps and packet IDs are traceable;
- demo audio reaches backend.

---

# PHASE 6 — SECURITY, PRIVACY & HARDENING

**Status:** COMPLETE  
**Commit:** `36fad4b`

## Objective

Harden the end-to-end prototype before real ML.

## Completed

- principals;
- RBAC;
- session ownership;
- 404 behavior for unauthorized session probing;
- rate limiting;
- replay guard;
- audit events;
- HMAC signatures;
- TLS-readiness flag;
- log redaction;
- real session deletion;
- demo reset;
- resilience/failure handling.

## Measured latency

With mock adapters:

```text
p50 = 2.0 ms
p95 = 2.7 ms
```

These are prototype/mock measurements, not final ML performance claims.

## Not implemented

- persistence across restart;
- token rotation;
- distributed rate limiting;
- encryption at rest;
- external security audit.

## Acceptance

Security, privacy, resilience and demo behavior verified; 176 tests passing.

---

# PHASE 7 — DATA PREPARATION + CLOUD TRAINING

**Status:** NEXT

## Objective

Prepare legally usable datasets and train project-specific ML components using cloud GPU resources.

## First task — resolve O5

Before training:

**Verify dataset licenses and provenance.**

For every dataset record:

```text
dataset name
source URL
version
license
license verification status
provenance
language
speaker information where available
real/synthetic label
generator information where available
split information
preprocessing
intended use
restrictions
```

Do not train merely because a dataset is publicly downloadable.

## Data categories

### Anti-spoofing

Potential resources:

- ASVspoof;
- Indic synthetic-speech datasets such as IndicSynth where permitted;
- other legally usable synthetic/genuine speech datasets.

### Speaker verification

Potential foundation:

- VoxCeleb;
- other legally usable speaker datasets.

### Indic speech

Potential resources:

- Vaani;
- Common Voice where permitted;
- consented recordings;
- other approved Indian-language datasets.

### Intent/behaviour

Potential resources:

- ScamShield;
- Hinglish/English financial scam datasets;
- other legally usable social-engineering datasets;
- carefully constructed/consented examples.

## Language priority

1. Hindi
2. Tamil
3. English where stable
4. additional Indic languages later

Support code-switching where the selected model supports it.

## Preprocessing

Create reproducible pipelines for:

- format;
- sample rate;
- channels;
- duration;
- silence;
- segmentation;
- normalization;
- codec/channel transformations;
- language labels;
- speaker labels;
- synthetic/genuine labels;
- generator labels.

Avoid leakage.

Use speaker-disjoint and generator-disjoint evaluation.

## Training strategy

Do not train huge foundation models from scratch.

Prefer:

```text
pretrained model
→ project adaptation
→ validation
→ checkpoint
→ evaluation
```

Train in a controlled order:

```text
1. Anti-spoofing
2. Speaker verification foundation
3. Indic ASR evaluation/integration
4. Intent classifier
5. Behaviour classifier
6. Calibration/fusion data
```

Use Kaggle/Colab or another available GPU environment for heavy training.

## Deliverables

- verified dataset manifests;
- preprocessing scripts;
- reproducible splits;
- training notebooks/scripts;
- checkpoints;
- model metadata/cards;
- initial evaluation results;
- reproducibility instructions;
- license/provenance documentation.

## Acceptance gate

Do not proceed to Phase 8 until:

- dataset licenses are verified;
- provenance is documented;
- splits are reproducible;
- training scripts run;
- checkpoints are versioned;
- initial model evaluation exists;
- no fabricated metrics exist;
- model artifacts can be loaded independently.

---

# PHASE 8 — REAL ML INTEGRATION

**Status:** NOT STARTED

## Objective

Replace deterministic analyzers with real ML models without breaking the application architecture.

## Model boundary

```text
Backend
   ↓
Model Interface
   ↓
Real Model Adapter
   ↓
Model Artifact
```

Do not put ML inference directly inside Android Compose screens.

## AASIST

```text
audio → synthetic/spoof evidence
```

## ECAPA-TDNN

```text
audio → speaker embedding
```

Only compare against a legitimate reference when one exists.

Without a reference:

```text
speaker_state = NO_REFERENCE
```

Do not invent identity.

## Indic ASR

```text
audio → transcript
```

Priority:

- Hindi;
- Tamil;
- English;
- additional Indic languages later.

## Intent taxonomy

```text
NORMAL_CONVERSATION
OTP_REQUEST
PASSWORD_REQUEST
CARD_DETAILS_REQUEST
BANKING_CREDENTIAL_REQUEST
MONEY_TRANSFER_REQUEST
ACCOUNT_CHANGE_REQUEST
REMOTE_ACCESS_REQUEST
URGENT_ACTION
THREAT_OR_INTIMIDATION
CONFIDENTIAL_INFORMATION
UNKNOWN
```

## Behaviour taxonomy

```text
AUTHORITY_IMPERSONATION
URGENCY
THREAT
FEAR
SECRECY
PRESSURE
REWARD_PROMISE
NORMAL
```

## OOD / uncertainty

Target states:

```text
GENUINE_LIKELY
KNOWN_SYNTHETIC_LIKELY
UNKNOWN_SYNTHETIC_PATTERN
UNCERTAIN
INSUFFICIENT_AUDIO
```

## Acceptance gate

- real AASIST adapter works;
- real ECAPA adapter works;
- real ASR works;
- real intent model works;
- real behaviour model works;
- model versions are visible;
- demo/mock mode remains available;
- model failures degrade gracefully;
- latency is measured;
- real-model mode contains no fabricated outputs.

---

# PHASE 9 — ML EVALUATION, CALIBRATION & ROBUSTNESS

**Status:** NOT STARTED

## Objective

Measure the real ML system under documented, reproducible conditions.

## Metrics

### Anti-spoofing

- EER;
- minDCF where applicable;
- FAR;
- miss/FNR;
- ROC-AUC/PR-AUC where useful.

### Speaker verification

- EER;
- FAR;
- FRR;
- threshold analysis.

### ASR

- WER;
- language-specific WER;
- code-switching evaluation where possible.

### Intent

- accuracy;
- precision;
- recall;
- F1;
- macro-F1.

### Behaviour

- precision;
- recall;
- F1;
- macro-F1.

### Complete risk system

- precision;
- recall;
- F1;
- FPR;
- FNR;
- calibration;
- time-to-first-warning;
- latency;
- throughput.

## Required experiments

### A — Leave-One-Generator-Out

```text
Train: A + B + C + D
Test:  E
```

Rotate generators.

### B — Telephone/VoIP robustness

Evaluate:

- codec compression;
- low bitrate;
- noise;
- reverberation;
- GSM/telephone-like degradation;
- VoIP processing.

### C — Evidence ablation

Compare:

```text
voice only
voice + speaker
voice + intent
voice + intent + context
full system
```

### D — Indic robustness

Evaluate:

- Hindi;
- Tamil;
- English;
- code-switching where supported.

### E — Real human scam

Test suspicious/scam intent using genuine human speech.

### F — Synthetic legitimate conversation

Test synthetic speech that is not malicious.

### G — Early warning

Measure:

```text
time-to-first-warning
time-to-high-risk
time-to-critical
```

### H — Calibration

Determine whether confidence/risk is calibrated.

Do not call a score a probability unless calibrated and defined as such.

### I — OOD/unknown-generator

Evaluate unseen generators separately.

### J — End-to-end latency

Measure:

- inference;
- backend;
- WebSocket;
- Android update;
- first-result latency.

## Accuracy claim policy

Never claim a universal:

```text
95%
98%
99%
99.9%
100%
zero false positives
```

without a controlled evaluation supporting the exact statement.

Every claim must identify:

```text
metric
dataset
sample count
split
population
protocol
model version
conditions
```

## Acceptance gate

- held-out evaluation;
- no leakage;
- reproducible metrics;
- robustness results;
- calibration results;
- OOD behavior;
- component metrics;
- limitations;
- no unsupported accuracy claims.

---

# PHASE 10 — FINAL END-TO-END INTEGRATION

**Status:** NOT STARTED

## Objective

Integrate the validated ML system into the full VIVE prototype and produce the final reproducible demonstration.

## Final flow

```text
Real authorized communication
        ↓
Secure ingestion
        ↓
Session Manager
        ↓
VAD + DSP + quality
        ↓
┌────────┬────────┬─────────┐
↓        ↓        ↓
AASIST   ECAPA    Indic ASR
↓        ↓        ↓
Synthetic Speaker Transcript
Voice
        ↓
Intent + Behaviour
        ↓
Context
        ↓
OOD / Uncertainty
        ↓
Calibrated Risk Fusion
        ↓
Temporal Engine
        ↓
Policy Engine
        ↓
┌────────────┬─────────────┬────────────┐
↓            ↓             ↓
Dashboard   Mobile Alert   API/Webhook
```

## Dashboard

Must show:

- call/session ID;
- duration;
- packet count;
- current risk;
- risk level;
- confidence;
- synthetic evidence;
- speaker consistency;
- intent risk;
- context risk;
- overall risk graph;
- every packet in the timeline;
- first anomaly;
- first warning;
- escalation timing;
- recommended action.

## Packet detail

Every packet must be clickable.

Show:

- packet ID;
- timestamp;
- start/end;
- duration;
- language;
- synthetic score;
- speaker evidence;
- transcript;
- intent;
- behaviour;
- context;
- uncertainty;
- packet risk;
- confidence;
- contribution graph;
- model/version metadata where applicable.

## Alerts

Where implemented:

- dashboard;
- Android notification;
- secure webhook;
- email.

## API/SDK

Finalize applicable:

- REST;
- WebSocket;
- gRPC;
- authentication;
- session lifecycle;
- webhooks;
- Python SDK;
- Android SDK boundary;
- JavaScript SDK;
- enterprise integration.

## Final demo scenarios

### 1. Normal call

```text
normal speech
→ low risk
→ no unnecessary interruption
```

### 2. Synthetic voice

```text
synthetic indicators
→ risk increases
→ evidence shown
```

### 3. Human scam

```text
genuine voice
+
OTP/credential request
+
urgency
→ high risk
```

### 4. Synthetic legitimate conversation

```text
synthetic voice
+
normal conversation
→ synthetic evidence
→ not automatically fraud
```

### 5. Unknown generator

```text
unseen synthetic pattern
→ uncertainty/OOD evidence
→ cautious handling
```

### 6. Poor audio

```text
low-quality audio
→ insufficient/uncertain evidence
→ no fabricated confidence
```

## Acceptance gate

- real ML runs end to end;
- packet results are traceable;
- dashboard is backend/model driven;
- alerts work;
- APIs work;
- authorized communication paths work;
- security controls remain active;
- evaluation metrics are documented;
- demo scenarios are reproducible;
- known limitations are visible;
- Git tree is clean;
- final documentation is complete.

---

# AFTER PHASE 10 — PRODUCTION ROADMAP

Phase 10 completes the implementation roadmap, but not the product lifecycle.

## Production readiness

- persistent database;
- scalable event storage;
- distributed rate limiting;
- token rotation;
- encryption at rest;
- secret management;
- production TLS;
- observability;
- backups;
- disaster recovery.

## Model operations

- model registry;
- model versioning;
- drift monitoring;
- data drift;
- generator drift;
- language drift;
- performance monitoring;
- retraining pipeline;
- rollback.

## Security

- threat modeling;
- penetration testing;
- dependency scanning;
- mobile security review;
- API security review;
- ML security review;
- external audit where required.

## Legal/compliance

Obtain qualified review for applicable:

- privacy;
- telecom;
- banking;
- consent/recording;
- retention;
- cross-border processing;
- organizational requirements.

Do not label the system compliant merely because technical controls were implemented.

## Real organizational integration

Only with appropriate authorization:

```text
Bank
Telecom
Contact Centre
Enterprise
```

can connect their workflows to VIVE.

VIVE remains a risk/evidence service rather than an unauthorized controller of financial transactions.

---

# PERMANENT LIMITATIONS

## P1 — Cellular audio

Ordinary third-party Android applications cannot be assumed to have unrestricted access to both sides of standard cellular-call audio.

## P2 — Unknown generators

No system can honestly guarantee detection of every future/unseen synthetic generator.

VIVE should report uncertainty/OOD evidence.

## P3 — Synthetic ≠ fraud

Synthetic speech can be legitimate.

Human speech can be fraudulent.

Risk therefore requires multiple evidence sources.

## P4 — ASR variability

ASR quality varies with:

- language;
- accent;
- noise;
- codec;
- code-switching;
- speaker characteristics.

Poor transcription must not be treated as proof of malicious intent.

---

# CURRENT OPEN BLOCKERS

Reported open blockers:

```text
O1 — Parent/home Git metadata remains outside VIVE
O2 — Some original source material is outside the VIVE repository
O3 — Speaker-enrolment/reference source is not finalized
O4 — Long-term backend persistence engine is not finalized
O5 — Dataset licenses/provenance are not yet fully verified
O6 — Fusion weights/calibration remain provisional until real ML outputs exist
```

Current impact:

- O1/O2: repository/documentation hygiene;
- O3: important for real ECAPA identity comparison;
- O4: production persistence/scaling;
- O5: directly relevant to Phase 7;
- O6: directly relevant to Phase 9.

---

# GIT CHECKPOINT POLICY

Every phase receives a separate commit.

```text
Phase 0 → commit
Phase 1 → commit
Phase 2 → commit
Phase 3 → commit
Phase 4 → commit
Phase 5 → commit
Phase 6 → commit
Phase 7 → commit
Phase 8 → commit
Phase 9 → commit
Phase 10 → final commit
```

Before commit:

```text
git status
git diff
```

After commit:

```text
git status
git log --oneline -5
```

The working tree should be clean at each checkpoint.

---

# AUTONOMOUS ERROR RECOVERY POLICY

For every implementation phase:

1. Read the complete error.
2. Diagnose the root cause.
3. Inspect source/configuration/dependencies.
4. Apply the smallest safe fix.
5. Re-run the failing check.
6. Try up to three technically different fixes where reasonable.
7. Do not repeat a failed approach without new evidence.
8. Isolate genuine blockers.
9. Record blockers in `docs/BLOCKERS.md`.
10. Continue independent work.
11. Never fabricate success.
12. Never fabricate metrics.
13. Never mark an acceptance gate passed without verification.

---

# TESTING PHILOSOPHY

Keep these separate:

```text
Software correctness
        ≠
ML accuracy
        ≠
Security assurance
        ≠
Production readiness
```

A passing test suite proves only what those tests cover.

Real ML performance requires controlled evaluation.

Security readiness requires appropriate security testing/review.

Production readiness requires infrastructure, operations, security and organizational controls beyond the prototype.

---

# FINAL DEFINITION OF DONE

VIVE is fully implemented at Phase 10 when:

```text
Real authorized communication
        ↓
Secure ingestion
        ↓
Streaming packetization
        ↓
Real ML inference
        ↓
Synthetic voice evidence
        ↓
Speaker evidence where reference exists
        ↓
Indic ASR
        ↓
Intent
        ↓
Behaviour
        ↓
Context
        ↓
OOD / uncertainty
        ↓
Calibrated risk fusion
        ↓
Temporal analysis
        ↓
Explainable packet-level evidence
        ↓
Call-level evidence
        ↓
Dashboard
        ↓
Alerts
        ↓
Secure APIs/webhooks
        ↓
Measured evaluation
        ↓
Robustness validation
```

The final system must clearly communicate:

- what it knows;
- what it does not know;
- why risk increased;
- which evidence contributed;
- confidence/uncertainty;
- when evidence is insufficient;
- recommended action;
- which capabilities are measured versus provisional.

---

# PHASE STATUS TEMPLATE

At every phase checkpoint:

```text
PHASE:
NAME:

STATUS:
COMPLETE / PARTIAL / BLOCKED

COMMIT:
<hash>

IMPLEMENTED:
<list>

TESTS:
<passed>/<total>

FAILURES:
<list>

FIXES:
<list>

BLOCKERS:
<list>

MEASUREMENTS:
<actual measurements only>

MOCK/DEMO:
<what remains mocked>

REAL:
<what is actually real>

NEXT:
<next phase>
```

---

# FINAL ROADMAP

```text
PHASE 0  ✅ Repository & Specifications
    ↓
PHASE 1  ✅ Android Foundation
    ↓
PHASE 2  ✅ Complete Android UI
    ↓
PHASE 3  ✅ FastAPI + WebSocket Backend
    ↓
PHASE 4  ✅ Android ↔ Backend Integration
    ↓
PHASE 5  ✅ Communication Integration
    ↓
PHASE 6  ✅ Security, Privacy & Hardening
    ↓
PHASE 7  ← NEXT: Data Preparation + Cloud Training
    ↓
PHASE 8  ⏳ Real ML Integration
    ↓
PHASE 9  ⏳ Evaluation, Calibration & Robustness
    ↓
PHASE 10 ⏳ Final End-to-End Integration
    ↓
PRODUCTION READINESS
```

**Current next objective: Phase 7 — Data Preparation + Cloud Training.**

Before training, reconcile the phase-numbering documentation and verify dataset licenses/provenance.  
