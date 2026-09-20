# VIVE — Security & Privacy Specification

> Endpoints and payloads are defined in `API_SPEC.md`. This document defines who
> may call them, what is stored, and for how long.

## 1. Posture

VIVE processes voice — among the most sensitive categories of personal data —
for **authorized** communication only. The system is decision support and holds
no authority to act on an account (`PROJECT_SPEC.md` §2).

Design rules:

1. Collect the minimum needed to produce a risk assessment.
2. Keep audio in memory; persist it only when explicitly configured.
3. Treat transcripts with the same sensitivity as audio.
4. Never transmit audio or transcript content to third-party channels.
5. Fail closed on authorization, open on analysis — a missing model degrades the
   assessment; a missing credential denies the request.

## 2. Authentication and authorization

REST: `Authorization: Bearer <token>`. WebSocket: the same token presented on the
first frame; the connection is closed with a policy violation if it is absent or
invalid.

Tokens are short-lived with refresh. On Android they are held in
`EncryptedSharedPreferences` backed by the Android Keystore — never in plain
preferences, never in source, never logged.

Sessions are owned. A caller may only read sessions, packets, transcripts and
alerts belonging to its own principal; cross-principal access returns `404`,
not `403`, so IDs cannot be probed.

## 3. Transport

TLS 1.2+ for REST and WSS in any non-local deployment. Certificate pinning on
Android for production endpoints. Cleartext HTTP is permitted only for
`localhost` during development and is disabled in release builds via the network
security configuration.

## 4. Data handling

| Data | Default | Retention |
|---|---|---|
| Raw audio | In memory only, bounded ring buffer | Discarded when the window leaves the buffer |
| Packet evidence | Persisted | Session lifetime + configured window |
| Transcript | Persisted with the session | Same as packet evidence |
| Risk / alerts | Persisted | Configured retention |
| Webhook payloads | Metadata only | Per receiving system |

Audio is **not** written to disk unless an operator explicitly enables evidence
retention. When enabled, it is encrypted at rest and covered by the same
retention window.

Webhooks carry `session_id`, `packet_id`, risk, intent and timing — **never**
transcript text and never audio (`API_SPEC.md` §8). The same applies to
notification payloads: the alert body must not contain transcript content,
because notifications render on a locked screen.

## 5. Logging

Logs record `request_id`, `session_id`, `packet_id`, status and latency. Logs
must never contain transcript text, audio bytes, tokens, API keys or webhook
signatures. PII appearing in transcripts — OTP digits, account numbers, names —
is redacted before any log or error path.

Error responses return a `request_id`, not a stack trace.

## 6. Android specifics

Permissions are requested with a stated reason at the point of use
(`UI_SPEC.md` §4, screen 3), not all at launch. Microphone access is bound to an
active authorized session and released when it ends.

`CallScreeningService` receives number and metadata only. The app must not
claim, imply or attempt to capture cellular call audio
(`ARCHITECTURE.md` §7). Screenshot protection (`FLAG_SECURE`) applies to the
transcript and packet-detail screens.

## 7. Backend specifics

Secrets come from the environment, never from source; `.env` is git-ignored.
Rate limiting per principal on session creation and REST reads. Request size
limits and a bounded ring buffer prevent unbounded memory growth from a hostile
stream. Webhook delivery is signed (HMAC-SHA256), idempotent on `event_id`, and
retried with backoff to operator-configured destinations only.

## 8. Threat model

| Threat | Mitigation |
|---|---|
| Stolen token | Short-lived tokens, refresh, Keystore storage, TLS |
| Session ID enumeration | Ownership checks, `404` on cross-principal access |
| Audio exfiltration via webhook | Metadata-only payloads, enforced at schema level |
| Transcript leak via notification | No transcript content in notification bodies |
| Memory exhaustion via stream | Bounded ring buffer, size and rate limits |
| Replay of webhook events | `event_id` idempotency, signature, timestamp window |
| Model output treated as proof | UI phrasing rules, mock/real mode surfaced (`UI_SPEC.md` §6) |

## 9. Compliance posture

Aligned with NIST AI RMF framing: the system is documented as decision support
with stated limitations, known failure modes and non-universal detection
(`ML_SPEC.md` §10). Consent for any recorded or retained audio is the deploying
organization's responsibility and must be established before deployment.
