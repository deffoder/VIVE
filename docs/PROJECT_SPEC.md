# VIVE — Project Specification

> Authority: `CLAUDE.md` is the highest-priority project instruction. Where this
> document and `CLAUDE.md` disagree, `CLAUDE.md` wins and this document is wrong.

## 1. What VIVE is

VIVE (Voice Integrity Verification Engine) is a real-time voice integrity and
social-engineering risk analysis platform for **authorized** voice communication.

It analyses a live audio stream and produces, continuously:

- a calibrated **risk score** (0–100) and **risk level**
- a separate **confidence** value describing how much evidence supports that score
- packet-level **forensic evidence** that a human can inspect and audit

## 2. What VIVE is not

VIVE is **decision support**. It does not act on the user's behalf.

The system must never:

- transfer money, or authorize a transfer
- retrieve, display or request credentials
- bypass or satisfy an authentication challenge
- freeze, lock or modify an account
- make an autonomous banking decision

### 2.1 Claims the product must never make

| Forbidden claim | Why |
|---|---|
| "Synthetic voice detected, therefore fraud" | Synthetic speech has legitimate uses (accessibility, IVR, dubbing). |
| "Human voice detected, therefore safe" | Most social-engineering fraud uses a real human voice. |
| "87% AI voice" | The AASIST score is a spoof-likelihood signal, not a probability of fraud. |
| "100% accuracy" / "detects all future generators" | Unfalsifiable and false. |
| "Captures both sides of any cellular call" | Prohibited by the Android/telecom platform. See §5. |

Correct phrasing is evidence-shaped: *"High voice-integrity risk"*,
*"Elevated synthetic-voice indicators"*, *"Caller not independently verified"*.

## 3. Risk vs confidence

These are orthogonal and must never be merged or used interchangeably.

- **risk_score** — how concerning the evidence is (0–100).
- **confidence** — how much the system trusts its own assessment, driven by
  audio quality, amount of speech observed, model availability and agreement.

A 2-second window of poor-quality audio can produce a high risk score at low
confidence. The UI must show both, always, and label them distinctly.

## 4. Scope

### 4.1 In scope for the current build

Native Android application; FastAPI backend; WebSocket streaming; sliding-window
packetisation; VAD; anti-spoofing; speaker consistency; Indic ASR (Hindi, Tamil,
English); intent classification; behaviour classification; context signals; risk
fusion; temporal escalation; packet forensics; alerts and webhooks.

### 4.2 Explicitly deferred

Full telecom/operator integration; advanced OOD research; large-scale fine-tuning;
the full SDK suite; production gRPC; distributed inference; multi-region scaling;
advanced observability; extensive robustness experiments.

Deferred items are recorded in `BLOCKERS.md`, not silently dropped.

## 5. Platform boundary (non-negotiable)

Ordinary cellular call audio is **not** accessible to a third-party Android app.

| Path | Capability |
|---|---|
| Authorized VoIP / in-app audio | Full duplex audio → complete analysis pipeline |
| Cellular call | `CallScreeningService` only — number, metadata, screening decision |

The UI must make the active path visible to the user rather than implying that
cellular calls receive full analysis. See `ARCHITECTURE.md` §7.

## 6. Languages

Initial priority: **Hindi (hi)**, **Tamil (ta)**, **English (en)**.
The data model and UI are built for Indic expansion; see `DATA_SPEC.md`.

## 7. Taxonomies

Canonical and shared by backend, Android and all documents.

**Risk level:** `LOW` · `MEDIUM` · `HIGH` · `CRITICAL`

**Audio quality:** `GOOD` · `DEGRADED` · `POOR` · `NO_SPEECH`

**Analyzer status:** `AVAILABLE` · `UNAVAILABLE` · `NO_REFERENCE` ·
`INSUFFICIENT_AUDIO` · `ERROR`

**Intent (12):** `NORMAL_CONVERSATION` · `OTP_REQUEST` · `PASSWORD_REQUEST` ·
`CARD_DETAILS_REQUEST` · `BANKING_CREDENTIAL_REQUEST` · `MONEY_TRANSFER_REQUEST` ·
`ACCOUNT_CHANGE_REQUEST` · `REMOTE_ACCESS_REQUEST` · `URGENT_ACTION` ·
`THREAT_OR_INTIMIDATION` · `CONFIDENTIAL_INFORMATION` · `UNKNOWN`

**Behaviour (8):** `AUTHORITY_IMPERSONATION` · `URGENCY` · `THREAT` · `FEAR` ·
`SECRECY` · `PRESSURE` · `REWARD_PROMISE` · `NORMAL`

## 8. Build phase ordering

Real ML is deliberately **last**. The product must be fully demonstrable
end-to-end on mock adapters before any real checkpoint is integrated, so that
UI, transport and fusion defects are never confused with model defects.

Phase order is defined in `IMPLEMENTATION_PLAN.md`.

## 9. Related documents

| Document | Covers |
|---|---|
| `ARCHITECTURE.md` | System shape, components, data flow |
| `UI_SPEC.md` | Screens, design system, components, states |
| `API_SPEC.md` | REST + WebSocket contract, schemas |
| `ML_SPEC.md` | Model stack, adapter interfaces, fusion |
| `DATA_SPEC.md` | Datasets, manifests, provenance, splits |
| `SECURITY_SPEC.md` | Auth, privacy, retention, threat model |
| `DEMO_SPEC.md` | Demo scenarios and acceptance |
| `IMPLEMENTATION_PLAN.md` | Phases and exit criteria |
| `BLOCKERS.md` | Open issues, deferrals, decisions needed |
