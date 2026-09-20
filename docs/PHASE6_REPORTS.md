# VIVE — Phase 6 Verification Reports

Security, testing and demo-readiness reports for the hardening pass.

> **This is not a certification.** Every control below is implemented and
> tested in a prototype. None has been penetration-tested, externally audited
> or deployed. Where a control is designed but not deployed, it says so.

Date of run: 2026-09-21 · Commit: Phase 6

---

## 1. Security verification report

### 1.1 Implemented and tested

| # | Control | Implementation | Test evidence |
|---|---|---|---|
| 1 | Authentication boundary | Bearer token on REST; same token on WebSocket via query param or header | 4 tests: missing, wrong, malformed header, valid |
| 2 | Authorization / RBAC | `Principal` + `Role` (viewer/analyst/admin); per-session ownership | 4 tests incl. cross-principal read, packet access and delete |
| 3 | Secure configuration | `pydantic-settings` from environment; no secret in source | `.env` git-ignored; `.env.example` carries no values |
| 4 | Secret handling | Principal id is a digest of the token; the token is never stored, logged or audited | `test_principal_id_is_derived_not_the_token` |
| 6 | REST input validation | Pydantic with `extra="forbid"`; range-checked numerics | 4 tests incl. unknown field, bad enum, out-of-range |
| 7 | WebSocket validation | `ClientFrame` with `extra="forbid"`; frame-size and transcript-length caps | 5 tests incl. malformed JSON, oversized frame, bad base64 |
| 8 | Rate limiting | Per-principal fixed window; a tighter separate limit on session creation | 4 tests incl. window expiry and a live 429 |
| 9 | Webhook signature | HMAC-SHA256, constant-time verification | 3 tests: round trip, tampered body, wrong key |
| 10 | Audit events | 10 event types to a dedicated `vive.audit` logger | Observed in test output; identifiers only |
| 11 | Replay protection | Bounded `ReplayGuard` on webhook `event_id` | 2 tests incl. the bounded-memory trade-off |
| 12 | Error sanitisation | Opaque 500s; no stack trace, no submitted values echoed | 3 tests incl. formatter omitting tracebacks |

### 1.2 Implemented, not fully exercised

| # | Control | Status |
|---|---|---|
| 5 | TLS-ready configuration | `require_tls` rejects non-HTTPS forwarded requests. **TLS itself is terminated by the deployment**; the flag only enforces that it happened. Not exercised against a real TLS terminator. |
| — | Admin role | `Role.ADMIN` bypasses ownership. No endpoint issues admin tokens yet, so the path is implemented but unreachable in practice. |

### 1.3 Not implemented

- Token rotation, refresh and expiry. Tokens are static configuration.
- Distributed rate limiting. The limiter is per-process, so it guards against a
  careless client, not a distributed attacker.
- Encryption at rest. Nothing is written to disk, so there is nothing to
  encrypt — this becomes required the moment a persistence engine is chosen
  (`BLOCKERS.md` O4).
- mTLS, certificate pinning verification against a live endpoint.

### 1.4 Limitations

- **No external audit or penetration test has been performed.**
- The in-memory store means all evidence is lost on restart. That is a privacy
  property today and a durability gap for production.
- Ownership is tracked in process memory and is lost on restart, after which
  previously created sessions become unowned and readable by any authenticated
  principal. Acceptable for a prototype; not for production.

---

## 2. Privacy report

| # | Control | Status |
|---|---|---|
| 13 | Minimal raw-audio retention | Audio is never persisted. `retain_raw_audio` defaults false, and the store has no disk path, so enabling it alone would not persist audio. |
| 14 | Raw-audio access boundary | Audio exists only in the request path and a bounded ring buffer on device. No endpoint returns audio. |
| 15 | Session deletion | `DELETE /api/v1/sessions/{id}` removes the record, packets, transcript and alerts. Verified by test that subsequent reads 404. Real deletion, not a tombstone. |
| 16 | Consent / authorization states | `AudioAuthorization` models Granted / PermissionMissing / Denied / NotPermittedByPlatform. Capture refuses to start without Granted. |
| 17 | Minimal PII | No name, email or account identifier is stored. The screening path never logs a phone number. |
| 18 | No secrets or PII in logs | `SensitiveDataFilter` scrubs bearer tokens and key-shaped strings; `JsonFormatter` omits stack traces; `redact()` for any transcript reference. |

**Not claimed:** there is no data-subject request workflow, no retention
enforcement job, and no cross-restart deletion guarantee — because there is no
persistence to delete from.

---

## 3. Test report

| Suite | Tests | Passed | Failed | Skipped |
|---|---|---|---|---|
| Backend — API | 13 | 13 | 0 | 0 |
| Backend — WebSocket | 13 | 13 | 0 | 0 |
| Backend — pipeline / fusion / temporal | 16 | 16 | 0 | 0 |
| Backend — end-to-end | 6 | 6 | 0 | 0 |
| Backend — security | 27 | 27 | 0 | 0 |
| Backend — resilience | 17 | 17 | 0 | 0 |
| **Backend total** | **92** | **92** | **0** | **0** |
| Android — audio pipeline | 20 | 20 | 0 | 0 |
| Android — repository / serialization | 17 | 17 | 0 | 0 |
| Android — screening | 9 | 9 | 0 | 0 |
| Android — UI error states | 9 | 9 | 0 | 0 |
| Android — demo data | 9 | 9 | 0 | 0 |
| Android — core / contract / navigation | 20 | 20 | 0 | 0 |
| **Android total** | **84** | **84** | **0** | **0** |
| **TOTAL** | **176** | **176** | **0** | **0** |

### 3.1 Real failures found and fixed during these phases

These were genuine defects, not test-authoring mistakes:

1. **Substring keyword matching.** `"fir"` matched inside `"confirm"`, so a
   meeting confirmation classified as `THREAT_OR_INTIMIDATION`. Fixed with
   whole-word token matching.
2. **Weighted-average fusion diluted evidence.** A low anti-spoof score
   actively cancelled a high intent score: a clear OTP scam capped at 64 while
   a benign call scored MEDIUM. Replaced with noisy-OR.
3. **Mock scores seeded from `session_id`.** The same demo script produced
   different results per run, making a demo unrehearsable. Now content-seeded.
4. **Demo audio generator repeated every 5 chunks.** Frequency and phase both
   realigned, so chunk 0 and chunk 5 were byte-identical. Fixed with coprime
   stepping.
5. **Intent severity derived from classifier confidence** (Android, Phase 2).
   A confidently-identified normal conversation rendered as "High" intent risk.
   Severity now derives from the label.
6. **Session `current_risk` drifted from its latest packet** (Phase 2).

### 3.2 Failure modes exercised

network disconnect · WebSocket reconnect · superseded connection · malformed
JSON · oversized audio frame · over-length transcript · invalid base64 ·
invalid context · out-of-range values · empty transcript · no audio · model
unavailable (`NO_REFERENCE`) · streaming to an ended session · operations on a
deleted session · packet cap / bounded memory · backend unreachable from the
app.

### 3.3 Measured performance

**p50 2.0 ms, p95 2.7 ms** for the full in-process packet path (ingest →
adapters → fusion → temporal → policy → frame), n=10.

This is an **in-process measurement with mock adapters**, not a benchmark of a
deployed system, and not a prediction of latency with real models. Real model
inference will dominate and has not been measured because no real model exists
yet.

---

## 4. Demo readiness report

### 4.1 Working, end to end

- FastAPI backend: REST + WebSocket, 18 documented paths, OpenAPI 3.1.0
- Session lifecycle: create, stream, context, end, delete
- Overlapping 2 s / 1 s packetisation with full traceability
- Risk fusion, temporal smoothing, escalation timings, policy and alerts
- Android app: all 24 screens, backend-driven
- Live streaming into the UI, with reconnect and `since_seq` backfill
- Cellular screening path (metadata only)
- Authorized audio path: capture, ring buffer, packetisation, demo source
- Demo reset for repeatable runs

### 4.2 Mock / demo, clearly labelled

- **Every analyzer.** AASIST, ECAPA, ASR, intent and behaviour are keyword and
  hash rules over a transcript. No inference runs anywhere.
- Model versions read `"demo"`, never a plausible semantic version.
- `GET /ready` reports `mode` per adapter; packets carry `adapter_mode`.
- The app shows a non-dismissable **Demo data** badge.
- `DemoAudioSource` generates a tone, not speech.

### 4.3 Real, not mocked

Transport, session management, packetisation, the fusion arithmetic and its
guard rails, temporal smoothing, the policy engine, the security controls in
§1, audio buffering and windowing, and all 176 tests.

### 4.4 Limitations to state in any demonstration

1. No real ML. Nothing detects a deepfake today.
2. No accuracy figure exists, because none has been measured.
3. Cellular call audio is inaccessible by platform design.
4. Fusion weights are expert-set and uncalibrated (`BLOCKERS.md` O6).
5. Data is lost on restart.
6. No external security audit.

### 4.5 Blockers

Unchanged: **O1–O6** open, **P1–P4** permanent. None blocks a demonstration.
