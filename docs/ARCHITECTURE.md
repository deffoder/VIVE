# VIVE — Architecture

> Canonical definitions live in `PROJECT_SPEC.md` §7 (taxonomies) and
> `API_SPEC.md` (wire schemas). This document describes structure, not payloads.

## 1. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Frontend is **native Android** | Design targets Android phones; `CallScreeningService` requires native. |
| 2 | **Kotlin + Jetpack Compose (Material 3)** | Matches the component vocabulary in `CLAUDE.md` (`TopAppBar`, `BottomNavigation`). |
| 3 | **No React Native** | Single UI stack; avoids a native-bridge layer for audio and telephony. |
| 4 | **No separate web frontend** | The mobile app is the product. `frontend/` has been removed. |
| 5 | Backend is **FastAPI** (Python 3.11) | Async I/O, native WebSocket support, same runtime as the ML stack. |
| 6 | **WebSocket** for real-time session updates | Server-push of packets and risk; REST alone would require polling. |
| 7 | ML is reached only via **model-service interfaces** | Swap mock ↔ real without touching transport, fusion or UI. |
| 8 | Android **never runs the ML pipeline** | No on-device inference; the app is a client of the backend. |
| 9 | Real ML integration is the **final** phase | Isolates model defects from system defects. |
| 10 | Training runs on **Kaggle / Google Colab** | No local GPU; see `ML_SPEC.md` §8. |

## 2. System shape

```text
┌──────────────────────────────┐
│  ANDROID (Kotlin + Compose)  │
│  UI · ViewModels · Repos     │
│  Audio capture · WS client   │
└──────────────┬───────────────┘
               │  REST  (control, history)
               │  WS    (live packets, risk, alerts)
               ▼
┌──────────────────────────────┐
│  FASTAPI BACKEND             │
│  routers · schemas · auth    │
│  session mgr · ring buffer   │
│  packetizer · orchestrator   │
│  fusion · temporal · policy  │
└──────────────┬───────────────┘
               │  in-process adapter calls
               ▼
┌──────────────────────────────┐
│  MODEL SERVICE LAYER         │
│  interfaces/  ← contracts    │
│  adapters/    ← mock | real  │
└──────────────────────────────┘
```

The Android app has **no** dependency on any model library, checkpoint or
inference runtime. Its only contract is `API_SPEC.md`.

## 3. Audio → risk pipeline

```text
authorized audio
  → WebSocket ingestion
  → session manager
  → ring buffer (bounded)
  → sliding-window packetizer   (2.0 s window, 1.0 s stride, 16 kHz mono)
  → VAD + DSP + quality scoring
  → ┌─ anti-spoof (AASIST)
    ├─ speaker consistency (ECAPA-TDNN)
    └─ ASR (IndicConformer)
        → intent classification
        → behaviour classification
  → context signals
  → risk fusion
  → temporal risk (smoothing, hysteresis, escalation)
  → policy engine
  → persistence + WebSocket broadcast + alert dispatch
```

Every stage is skippable and degradable. A stage that cannot run emits a status
(`UNAVAILABLE`, `NO_REFERENCE`, `INSUFFICIENT_AUDIO`, `ERROR`) rather than
throwing, and fusion re-weights around the missing evidence.

## 4. Packet model

Windows overlap, so a packet is not a partition of the call:

```text
P001  00:00 – 00:02
P002  00:01 – 00:03
P003  00:02 – 00:04
```

Each packet is independently inspectable and carries its own evidence, risk,
confidence and contribution breakdown. Packet IDs are `P` + zero-padded
sequence, stable for the life of the session.

## 5. Backend layout (`backend/`)

```text
backend/
├── app/
│   ├── main.py                 FastAPI application factory
│   ├── config.py               settings (env-driven)
│   ├── api/
│   │   ├── routes/             sessions · packets · risk · alerts ·
│   │   │                       integrations · models · health
│   │   └── deps.py             auth / session dependencies
│   ├── ws/
│   │   ├── manager.py          connection registry, broadcast
│   │   └── protocol.py         frame envelopes (see API_SPEC §6)
│   ├── schemas/                Pydantic models — the single source of truth
│   ├── core/
│   │   ├── session.py          lifecycle + state machine
│   │   ├── ring_buffer.py      bounded PCM buffer
│   │   ├── packetizer.py       sliding-window segmentation
│   │   └── orchestrator.py     per-packet analyzer fan-out
│   ├── risk/
│   │   ├── fusion.py           evidence → score (transparent weights)
│   │   ├── temporal.py         EMA, hysteresis, escalation timings
│   │   └── policy.py           risk → recommended action / alert
│   ├── alerts/                 dispatch + webhook delivery
│   └── store/                  session + packet persistence
└── pyproject.toml
```

## 6. Android layout (`android/`)

```text
android/
├── app/src/main/java/com/vive/
│   ├── ui/
│   │   ├── theme/              colour · type · shape tokens (UI_SPEC §2)
│   │   ├── components/         RiskGauge · EvidenceRow · PacketCard · …
│   │   └── screens/            one package per screen
│   ├── navigation/             NavGraph, routes, bottom-nav host
│   ├── data/
│   │   ├── remote/             Retrofit API + OkHttp WebSocket client
│   │   ├── model/              Kotlin mirrors of the API schemas
│   │   └── repository/         session · alert · packet repositories
│   ├── domain/                 use cases, risk formatting rules
│   └── telephony/              CallScreeningService integration
└── build.gradle.kts
```

Presentation uses MVVM: ViewModel exposes an immutable `UiState` sealed type
covering `Loading` / `Success` / `Empty` / `Error` / `Offline` / `Unavailable` /
`InsufficientData`, as required by `CLAUDE.md`.

## 7. Telephony boundary

```text
Cellular call ──▶ CallScreeningService ──▶ number + metadata + screening only
                                           (NO audio — platform restriction)

VoIP / in-app ──▶ AudioRecord 16 kHz ────▶ WebSocket ──▶ full pipeline
```

This boundary is surfaced in the UI, not hidden. See `UI_SPEC.md` §6.

## 8. Performance constraints

- Packets stream in at ~1/second per session; the UI appends incrementally and
  must never rebuild a full list or screen per packet.
- Compose lists are keyed by `packet_id` so recomposition stays scoped.
- Risk history is capped in memory; older packets are paged from REST.
- WebSocket frames carry deltas, not whole-session snapshots.

## 9. Failure behaviour

| Failure | Behaviour |
|---|---|
| Model adapter unavailable | Packet emits that analyzer's status; fusion re-weights; UI shows "Unavailable" |
| WebSocket drops | Exponential backoff reconnect; UI shows Offline; REST backfills missed packets |
| Backend unreachable | UI shows Error with retry; no crash, no fabricated values |
| Audio quality `POOR` / `NO_SPEECH` | Confidence drops; insufficient-data state, **not** an automatic high risk |
