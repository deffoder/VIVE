# VIVE — Implementation Plan

> Ordering principle: the product must work end-to-end on mock adapters before
> any real model is integrated, so that UI, transport and fusion defects are
> never confused with model defects. Real ML is the **last** major phase.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` complete

## Phase 0 — Repository and architecture `[x]`

- [x] Git rooted at `VIVE/`, home-directory repo not used
- [x] `.gitignore` covering secrets, builds, checkpoints, corpora
- [x] Final directory structure; `frontend/` removed
- [x] Documentation set written and mutually consistent

**Exit:** structure matches `ARCHITECTURE.md`; no contradictory paths, schemas or
model names across the specs.

## Phase 1 — Android foundation + typed contract `[~]`

Delivered as the Android application foundation, with the Kotlin half of the
typed contract. The backend half moves to Phase 2.

Android foundation — **complete**:

- [x] Gradle/AGP/Kotlin configuration, version catalog, wrapper
- [x] Package structure per `ARCHITECTURE.md` §6
- [x] Navigation architecture — 4 tabs + full drill-down, all 24 routes
- [x] Theme, colour system, typography, spacing, shapes (`UI_SPEC.md` §2)
- [x] Component foundation incl. all seven state components
- [x] Screen/state architecture (`UiState` sealed interface)
- [x] Repository/service interfaces + REST/WebSocket/event interfaces
- [x] Logging with transcript redaction, typed error handling
- [x] Test structure; 16 unit tests passing
- [x] Kotlin mirrors of every taxonomy and the canonical packet
- [x] Contract test pinning the `CLAUDE.md` example packet

Deferred to Phase 2 (backend side of the same contract):

- [ ] Pydantic schemas in `backend/app/schemas/`
- [ ] OpenAPI generated and checked against `API_SPEC.md`

**Exit (Android side, met):** app builds, launches, navigates; the canonical
packet models with no field renamed or dropped; a missing analyzer yields
`null`, never `0`.

## Phase 2 — Backend skeleton `[x]`

- [x] FastAPI app, env-driven config, health/ready/version
- [x] Session manager and state machine, VS-/P- id generation
- [x] Sliding-window packetizer (2.0 s window, 1.0 s stride, 16 kHz)
- [x] Analyzer orchestrator calling the adapter interfaces
- [x] REST routes per `API_SPEC.md` §3, §5, §8.1
- [x] WebSocket manager, frame envelopes, heartbeat, reconnect-safe sequencing
- [x] Structured error contract (§7) and JSON logging with redaction
- [x] Mock adapters, transparent fusion, temporal risk, policy engine
- [x] In-memory event store (resolves the interim part of `BLOCKERS.md` O4)
- [x] 48 backend tests

**Exit met:** a session streams end to end over WebSocket and produces
traceable packets with zero real models loaded. Verified against a live uvicorn
server, not only the test client.

### Implementation decisions taken here

- **Fusion is noisy-OR, not a weighted average.** An average lets a LOW signal
  cancel a HIGH one, so benign anti-spoof evidence suppressed a clear OTP
  request — exactly the "human voice is not automatically safe" failure mode.
  Noisy-OR raises risk on strong evidence in any channel while weak evidence
  merely contributes little.
- **Demo determinism is content-seeded.** Mock scores derive from the
  transcript, not the session id, so the same demo script yields identical
  scores on every run.
- **In-memory persistence**, per O4. Audio and transcripts never touch disk,
  which is also the privacy posture in `SECURITY_SPEC.md` §4.

## Phase 3 — Design system in Compose `[x]`

- [x] Theme tokens from `UI_SPEC.md` §2
- [x] `RiskGauge`, `EvidenceRow`, `RiskPill`, `MetricCard` first
- [x] Remaining components from `UI_SPEC.md` §7
- [x] Every component's Loading / Empty / Error / Unavailable variants
- [x] `@Preview` composables for visual review against `design/02`

**Exit met:** components render all states; screens share one card/row
vocabulary and one `StateHost`, so no screen invents its own "no data" wording.

## Phase 4 — Navigation and screens `[x]`

- [x] Nav graph, four-tab bottom nav, drill-down path
- [x] All 24 screens implemented against `UI_SPEC.md` §4
- [x] Each screen bound to a `UiState` sealed type via `StateHost`
- [x] Packet evidence reachable in 2 taps from an active call
- [x] Demo repositories serving `DEMO_SPEC.md` scenarios S1–S4

**Exit met:** all 24 flows navigable; every screen routes through the
seven-state host. Verified on an API 36 emulator with zero crash lines.

### Implementation decisions taken here

- **`material-icons-extended` added.** Phase 1 deliberately excluded it, but a
  complete 24-screen UI needs a real icon vocabulary and the core set lacks
  `GraphicEq`, `Group`, `Mic` and `Storage`. R8 tree-shakes unused icons in
  release builds.
- **Demo data lives in `data/demo/`**, separate from production paths, with
  every adapter reporting `MOCK` and versions reading `"demo"` rather than a
  plausible-looking semantic version.
- **Intent and behaviour severity derive from the label, not classifier
  confidence.** Deriving from confidence made a confidently-identified normal
  conversation render as "High" intent risk - a misleading presentation that
  `CLAUDE.md` forbids. Severity now comes from what was actually asked for.

## Phase 5 — Live wiring `[x]`

- [x] Retrofit client; OkHttp WebSocket client
- [x] Incremental packet append keyed by `packet_id`; no full rebuilds
- [x] Reconnect with exponential backoff; `since_seq` backfill on sequence gaps
- [x] Offline and error states wired; typed `ViveError` from HTTP status
- [x] Mock adapters driven by `DEMO_SPEC.md` scenarios
- [x] Demo-data indicator surfaced (`UI_SPEC.md` §6)
- [x] Backend-first repositories with a visible demo fallback

**Exit met:** the Android app drives a live FastAPI backend end to end. Verified
on an API 36 emulator against a running server: the app listed the backend's
sessions, packet count rose 5 to 7 as packets were pushed over WebSocket, the
timeline rendered P001-P007 with backend risk levels, and packet detail matched
the backend byte for byte (P004: 87 CRITICAL, 91% confidence, OTP_REQUEST).

### Implementation decisions taken here

- **Live events are applied in `SessionDetailViewModel`**, so every session
  screen becomes backend-driven with no UI change and no second state layer.
- **DTOs are separate from domain models.** The wire speaks snake_case and may
  add fields; `ignoreUnknownKeys` plus enum fallbacks mean a newer backend
  cannot crash an older client.
- **The demo fallback is never silent.** When the backend is unreachable the
  app serves demo data and `usingFallback` records it, so the viewer always
  knows which source is on screen.

## Phase 6 — Fusion, temporal, policy `[ ]`

- [ ] Transparent weighted fusion, weights in `models/configs/fusion.yaml`
- [ ] Separate confidence computation
- [ ] EMA smoothing, hysteresis, minimum-evidence gate, cooldown
- [ ] Escalation timings
- [ ] Policy → recommended action → alert
- [ ] Webhook delivery: signing, idempotency, retry

**Exit:** S2 escalates on semantic evidence alone; S4 lowers confidence without
raising risk.

## Phase 7 — Android telephony `[x]`

Implemented as two deliberately separate packages, so the paths cannot be
confused in code.

**PATH A — cellular screening (`com.vive.telephony`)**

- [x] `ViveCallScreeningService` registered with `BIND_SCREENING_SERVICE`
- [x] Metadata model covering exactly what the platform exposes: handle,
      direction, number presentation
- [x] Local synchronous screening policy - no network, no model, because the
      platform enforces a response deadline
- [x] `CallScreeningRole` for the API 29+ role request, with an honest
      Unsupported/Unavailable state on devices that cannot offer it
- [x] Decisions never reject a call; `ScreeningVerdict` has no REJECT member

**PATH B — authorized audio (`com.vive.audio`)**

- [x] `AudioSource` abstraction with explicit `AudioAuthorization` states
- [x] Canonical 16 kHz mono `pcm_s16le` format
- [x] `VoiceActivityDetector` interface; energy-gate stand-in, not Silero
- [x] Bounded `RingBuffer` - audio is overwritten, never accumulated
- [x] `Packetizer`: 2.0 s windows, 1.0 s stride, overlapping
- [x] Packet ids, call-relative timestamps, window bounds, duration
- [x] `AudioQualityMeter` reporting only measured properties (RMS, clipping)
- [x] `CaptureController` lifecycle: start / stop / cancel, refusing to run
      without authorization
- [x] `DemoAudioSource` - deterministic, no audio asset in the repo

**Exit met:** 29 new tests pass. Demo audio verified end to end: 10 s generated,
packetised into 9 overlapping windows, sent as binary WebSocket frames, five
analysed by the backend and reflected in session state. No claim of cellular
audio capture exists anywhere in the codebase.

### Implementation decisions taken here

- **Quality is measured, never estimated.** `AudioQualityMeter` reports RMS and
  clipping ratio, which are properties of the samples. SNR and MOS would need a
  model or a reference signal, so they are not reported at all rather than
  guessed.
- **The demo source generates rather than ships audio**, so the repo carries no
  media asset and every run is byte-identical.

## Phase 8 — Real ML `[ ]`

Last major phase. Strictly sequential (`ML_SPEC.md` §9). Training on Kaggle or
Google Colab; no local GPU assumed.

- [ ] Dataset manifests, licenses, leakage checks (`DATA_SPEC.md` §5)
- [ ] `silero-vad` → `aasist` → `ecapa-tdnn` → `indicconformer`
      → `intent-classifier` → `behavior-classifier`
- [ ] Per model: real sample, recorded inference time and version, UI verified
- [ ] Fusion recalibrated against real outputs
- [ ] Evaluation report

**Exit:** adapters report `mode: "real"`; every metric traces to a measured run.

## Phase 9 — Verification and hardening `[~]`

- [x] Backend tests — pipeline, fusion, temporal, policy (92 total)
- [x] Android tests — states, navigation, serialization, audio (84 total)
- [x] Integration — REST + WebSocket contract, live server verified
- [x] End-to-end — DEMO_SPEC scenarios S1–S4
- [x] Latency measured and recorded, not claimed
- [x] Security controls implemented and tested; report in `PHASE6_REPORTS.md`
- [x] Privacy controls: deletion, retention defaults, log redaction
- [x] Failure modes exercised: disconnect, reconnect, malformed input,
      oversized frames, empty transcript, model unavailable, deleted session
- [x] Demo hardening: deterministic scenarios, reset endpoint, MOCK/REAL
      boundary enforced in code and surfaced in the UI
- [ ] Scenarios S5–S10 (need real adapters or a second device)
- [ ] Design quality gate re-run after any further UI change

**Exit (partial):** 176 tests pass across both sides. The remaining items
depend on real models, which is Phase 8.

## Notes on sequencing

Phases 3 and 4 may run alongside Phase 2 once Phase 1 is frozen — the contract is
what decouples them. Phase 8 must not begin before Phase 5's exit criterion is
met. Nothing in Phases 0–7 requires a GPU or a large model download.
