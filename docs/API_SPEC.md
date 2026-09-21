# VIVE — API Specification

> **Authority.** The packet schema in `CLAUDE.md` is canonical. Fields defined
> there keep their exact names and types below. Everything this document adds is
> **additive** and marked *(extension)*. No field from `CLAUDE.md` is renamed,
> retyped or removed.

Base path: **`/api/v1`** · Content type: `application/json; charset=utf-8`
Audio transport: binary frames over WebSocket.

## 1. Conventions

- IDs are opaque strings. Session: `VS-<n>`. Packet: `P` + zero-padded sequence.
- `timestamp` on a packet is a **call-relative** `mm:ss` string (per `CLAUDE.md`).
  Absolute wall-clock times use `created_at` in RFC 3339 *(extension)*.
- Scores in `0.0–1.0` are model outputs. `risk.score` is an integer `0–100`.
- All enums are from `PROJECT_SPEC.md` §7.

## 2. Operational endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness. Always cheap. |
| GET | `/ready` | Readiness — includes adapter load state. |
| GET | `/version` | Build + API version. |

`GET /ready`:

```json
{
  "ready": true,
  "api_version": "v1",
  "adapters": {
    "vad":       { "status": "AVAILABLE",    "mode": "mock" },
    "antispoof": { "status": "AVAILABLE",    "mode": "mock" },
    "speaker":   { "status": "NO_REFERENCE", "mode": "mock" },
    "asr":       { "status": "AVAILABLE",    "mode": "mock" },
    "intent":    { "status": "AVAILABLE",    "mode": "mock" },
    "behavior":  { "status": "AVAILABLE",    "mode": "mock" }
  }
}
```

`mode` is `mock` or `real` and must be surfaced in the UI (`UI_SPEC.md` §6) so a
demo is never mistaken for production inference.

## 3. Session endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/sessions` | Create a session |
| GET | `/api/v1/sessions` | List sessions (history) |
| GET | `/api/v1/sessions/{session_id}` | Session state |
| POST | `/api/v1/sessions/{session_id}/end` | End a session |
| GET | `/api/v1/sessions/{session_id}/risk` | Current aggregate risk |
| GET | `/api/v1/sessions/{session_id}/packets` | Packet list (paged) |
| GET | `/api/v1/sessions/{session_id}/packets/{packet_id}` | Single packet |
| GET | `/api/v1/sessions/{session_id}/transcript` | Ordered transcript |
| GET | `/api/v1/sessions/{session_id}/report` | Final call report |
| GET | `/api/v1/sessions/{session_id}/events` | Event history (alias of `/packets`) |
| POST | `/api/v1/sessions/{session_id}/context` | Set authorized context signals |
| DELETE | `/api/v1/sessions/{session_id}` | Delete a session and all derived data |

### 3.1 Create session

`POST /api/v1/sessions`

```json
{
  "source_type": "VOIP",
  "audio": { "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le" },
  "language": "auto",
  "context": {
    "caller_verified": false,
    "session_authenticated": false,
    "requested_action": "SENSITIVE"
  }
}
```

Response `201`:

```json
{
  "session_id": "VS-001",
  "status": "READY",
  "stream_path": "/api/v1/sessions/VS-001/stream",
  "expires_in": 3600
}
```

`source_type`: `VOIP` · `IN_APP` · `CELLULAR_SCREENING` · `REPLAY`.
`REPLAY` drives a fixture through the pipeline (`DEMO_SPEC.md`).

### 3.2 Session object

`status`: `READY` · `STREAMING` · `ENDED` · `ERROR`.

```json
{
  "session_id": "VS-001",
  "status": "STREAMING",
  "source_type": "VOIP",
  "started_at": "2026-09-20T18:04:21Z",
  "duration_sec": 267,
  "packets_processed": 52,
  "language": "ta",
  "current_risk": { "score": 72, "level": "HIGH", "confidence": 0.89 },
  "overall_risk": { "score": 68, "level": "HIGH", "confidence": 0.86 },
  "timings": {
    "first_anomaly_sec": 6,
    "first_warning_sec": 8,
    "first_high_sec": 10,
    "first_critical_sec": null
  }
}
```

## 4. Packet object — canonical

Core fields are exactly those in `CLAUDE.md`.

```json
{
  "packet_id": "P007",
  "timestamp": "00:08",
  "duration_sec": 2,
  "language": "ta",
  "quality": "GOOD",

  "aasist":   { "score": 0.87 },
  "ecapa":    { "status": "AVAILABLE", "similarity": 0.43 },
  "asr":      { "transcript": "OTP sollunga...", "confidence": 0.91 },
  "intent":   { "label": "OTP_REQUEST", "confidence": 0.94 },
  "behavior": { "labels": ["URGENCY"], "confidence": 0.89 },
  "context":  { "caller_verified": false },
  "risk":     { "score": 91, "level": "CRITICAL", "confidence": 0.84 }
}
```

### 4.1 Extensions

Additive only. Clients must tolerate their absence.

```json
{
  "session_id": "VS-001",
  "seq": 7,
  "window": { "start_sec": 6.0, "end_sec": 8.0 },
  "language_confidence": 0.88,
  "created_at": "2026-09-20T18:04:29Z",

  "aasist":   { "status": "AVAILABLE", "model_version": "aasist-v1",
                "inference_ms": 182 },
  "ecapa":    { "model_version": "ecapa-tdnn-v1", "inference_ms": 41 },
  "asr":      { "status": "AVAILABLE", "model_version": "indic-conformer-600m-ctc-v1",
                "inference_ms": 310 },
  "intent":   { "status": "AVAILABLE", "model_version": "intent-classifier-v1" },
  "behavior": { "status": "AVAILABLE", "model_version": "behavior-classifier-v1" },
  "context":  { "session_authenticated": false, "source_type": "VOIP",
                "requested_action": "SENSITIVE", "context_risk": 0.82 },

  "ood": { "state": "KNOWN_SYNTHETIC_LIKELY", "uncertainty": 0.16 },

  "risk": {
    "contributions": {
      "synthetic": 0.87,
      "intent": 0.94,
      "context": 0.82,
      "speaker_consistency": 0.43,
      "behavior": 0.89
    },
    "reasons": [
      "Elevated synthetic-voice indicators",
      "OTP request detected",
      "Urgency in conversation",
      "Caller not independently verified"
    ]
  }
}
```

`risk.contributions` drives the packet-detail explainability bars
(`UI_SPEC.md` §4.12). Values are `0.0–1.0`; the UI renders them as percentages.
They are **evidence strengths, not a decomposition that sums to `risk.score`.**

`ood` carries the uncertainty / unknown-generator layer required by `CLAUDE.md`
(Model Stack). `state` is `IN_DISTRIBUTION` · `KNOWN_SYNTHETIC_LIKELY` ·
`UNKNOWN_GENERATOR_SUSPECTED` · `OUT_OF_DISTRIBUTION` · `UNAVAILABLE`.
`uncertainty` is `0.0–1.0`. High uncertainty **lowers `risk.confidence`; it does
not raise `risk.score`** — an unfamiliar generator is unfamiliarity, not guilt.

### 4.2 Degraded packets

When an analyzer cannot run, its block carries a status and omits its value:

```json
{
  "ecapa":   { "status": "NO_REFERENCE" },
  "asr":     { "status": "INSUFFICIENT_AUDIO" },
  "quality": "POOR",
  "risk":    { "score": 12, "level": "LOW", "confidence": 0.21 }
}
```

Low confidence with low risk is the correct output for unusable audio. Poor
audio must never inflate `risk.score`.

## 5. Alerts, integrations, models

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/alerts` | List alerts (filter `?level=`, `?session_id=`) |
| GET | `/api/v1/alerts/{alert_id}` | Alert detail |
| POST | `/api/v1/alerts/{alert_id}/ack` | Acknowledge |
| GET | `/api/v1/integrations` | Configured channels |
| PUT | `/api/v1/integrations/{integration_id}` | Update a channel |
| GET | `/api/v1/models` | Model inventory (Model Information screen) |

Alert object:

```json
{
  "alert_id": "AL-014",
  "session_id": "VS-001",
  "level": "CRITICAL",
  "raised_at": "2026-09-20T18:04:29Z",
  "packet_id": "P007",
  "intent": "OTP_REQUEST",
  "reason": "OTP request with elevated synthetic indicators from unverified caller",
  "recommended_action": "SECONDARY_VERIFICATION",
  "acknowledged": false
}
```

`recommended_action`: `MONITOR` · `WARN_USER` · `SECONDARY_VERIFICATION` ·
`ESCALATE` · `HOLD_SENSITIVE_ACTION`. Advisory only — see `PROJECT_SPEC.md` §2.

`GET /api/v1/models` returns, per model: `id`, `display_name`, `purpose`,
`version`, `mode` (`mock` | `real`), `status`, `last_updated`. IDs are those in
`ML_SPEC.md` §2 — `silero-vad`, `aasist`, `ecapa-tdnn`,
`indic-conformer-600m`, `intent-classifier`, `behavior-classifier`,
`risk-fusion`.

> The ASR id was `indicconformer` until the architecture was selected
> (`ML_SPEC.md` §2.1). The backend and Android clients still emit the old
> string; reconciling all of them is a Phase 8 task
> (`PHASE8_PREREQUISITES.md` §1) and has **not** been done, so the running
> code and this spec currently disagree on the id.

## 6. WebSocket

`WS /api/v1/sessions/{session_id}/stream`

**Client to server:** binary frames of 16 kHz mono `pcm_s16le`, plus JSON control
frames `{"type":"client.pause"}`, `{"type":"client.resume"}`,
`{"type":"client.end"}`.

**Server to client:** JSON envelope.

```json
{ "type": "packet.new", "session_id": "VS-001", "seq": 7, "data": {} }
```

| `type` | `data` |
|---|---|
| `session.state` | Session object (§3.2) |
| `packet.new` | Packet object (§4) |
| `risk.update` | `{ current_risk, overall_risk, timings }` |
| `transcript.append` | `{ packet_id, speaker, text, language, confidence }` |
| `alert.raised` | Alert object (§5) |
| `session.ended` | Report summary |
| `error` | Error object (§7) |

`seq` is monotonic per session. A client that detects a gap backfills via
`GET /api/v1/sessions/{id}/packets?since_seq=`.

## 7. Errors

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "No session with id VS-999.",
    "detail": null,
    "request_id": "req_01J..."
  }
}
```

`400 VALIDATION_ERROR` · `401 UNAUTHENTICATED` · `403 FORBIDDEN` ·
`404 SESSION_NOT_FOUND` / `PACKET_NOT_FOUND` · `409 SESSION_ALREADY_ENDED` ·
`429 RATE_LIMITED` · `503 ADAPTER_UNAVAILABLE`.

`503` is expected while adapters load and must be handled, not treated as fatal.

## 8. Outbound webhook

`POST` to the configured endpoint:

```json
{
  "event": "VOICE_RISK_ESCALATION",
  "event_id": "evt_01J...",
  "session_id": "VS-001",
  "packet_id": "P007",
  "risk_score": 91,
  "risk_level": "CRITICAL",
  "intent": "OTP_REQUEST",
  "raised_at": "2026-09-20T18:04:29Z"
}
```

Signed (`X-VIVE-Signature`, HMAC-SHA256), idempotent on `event_id`, retried with
backoff. Transcripts and audio are **never** sent in a webhook
(`SECURITY_SPEC.md` §4).

## 8.1 Policy and webhook-test endpoints

Implemented in the backend phase.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/policies/evaluate` | Map a risk assessment to a recommended action |
| POST | `/api/v1/webhooks/test` | Build and sign a webhook payload, without sending it |

`POST /api/v1/policies/evaluate` takes `risk_score`, `confidence`, optional
`risk_level`, `intent` and `caller_verified`, and returns
`recommended_action`, `should_alert`, `reasons` and `policy_version`.
**Confidence gates escalation**: below 0.5 the response never sets
`should_alert`, because thin evidence must not drive an escalation.

`POST /api/v1/webhooks/test` is a development and security-workflow endpoint,
**not a bank integration**. It constructs the payload a real delivery would
send and signs it when `VIVE_WEBHOOK_SIGNING_KEY` is configured, then returns
`delivered: false` — nothing is transmitted. Claiming delivery here would be
fabricating an integration.

## 8.2 Path prefix

The canonical prefix is `/api/v1`. A `/v1` alias is mounted for the shorter
form used in external documents; both resolve to the same handlers
(`BLOCKERS.md` R3).

## 9. Auth

Bearer token on REST; the same token is presented on the first WebSocket frame.
Details in `SECURITY_SPEC.md` §2.
